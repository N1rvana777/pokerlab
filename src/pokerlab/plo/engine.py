"""PLO4 single-hand engine for 2..8 players.

All amounts are integer chips.  ``HandState`` is the simulator's full state: it
holds every hole card and the predetermined board run-out.  Agents must only be
given ``Observation`` objects built by ``observe()``, which contain the acting
player's own cards and public information only.

Betting rules implemented (documented in docs/DECISIONS.md):
* Blinds: heads-up the button posts the small blind and acts first preflop;
  with 3+ players SB/BB are the two seats after the button.  Optional antes are
  dead money (count toward the pot, not toward calling amounts).  A player who
  cannot cover a blind/ante posts all-in; the preflop amount to call stays the
  nominal big blind.
* Pot limit (formulas in ``pokerlab.plo.betting``, shared with the subgame trees):
  with P the pot including this round's bets, h the actor's chips in this round
  and c the amount to call, max raise-to = h + P + 2c; an opening bet is capped at P.
* Minimum bet is the big blind; a raise must increase the bet by at least the
  last full bet/raise increment.  A short all-in may be smaller.  An all-in that
  is not a full raise does not reopen betting for players who already acted:
  they may raise again only if the total increase they face since their last
  action is at least one full raise (TDA-style cumulative rule).
* Folding is only offered when facing a bet; raising is not offered when no
  other live player has chips behind.
* Settlement: nobody wins more from a player than they put in themselves, so
  chips above the largest live contribution and the unmatched top of that
  contribution are returned first; pots are then split by contribution level
  among non-folded players; ties split evenly with odd chips going clockwise
  from the button.  Optional rake is explicit (default: none), computed with
  exact decimal arithmetic and taken from each pot in proportion to its size.
* Antes are posted before blinds, so a player short of both is all-in on the ante.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from typing import Sequence

import numpy as np

from pokerlab.plo.betting import raise_window
from pokerlab.plo.cards import DECK, format_cards, validate_disjoint
from pokerlab.plo.evaluator import plo_rank_batch

MIN_PLAYERS, MAX_PLAYERS = 2, 8
PREFLOP, FLOP, TURN, RIVER = 0, 1, 2, 3
STREET_NAMES = ("preflop", "flop", "turn", "river")
_BOARD_SIZE_AFTER = (0, 3, 4, 5)


class IllegalActionError(ValueError):
    pass


class ActionType(str, Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"


@dataclass(frozen=True)
class Action:
    type: ActionType
    to: int = 0  # BET/RAISE: the player's total street commitment after acting

    @staticmethod
    def fold() -> "Action":
        return Action(ActionType.FOLD)

    @staticmethod
    def check() -> "Action":
        return Action(ActionType.CHECK)

    @staticmethod
    def call() -> "Action":
        return Action(ActionType.CALL)

    @staticmethod
    def bet(to: int) -> "Action":
        return Action(ActionType.BET, int(to))

    @staticmethod
    def raise_to(to: int) -> "Action":
        return Action(ActionType.RAISE, int(to))


@dataclass(frozen=True)
class RakeRule:
    """Explicit rake: ``percent`` of the settled pot, optionally capped."""
    percent: float = 0.0
    cap: int | None = None
    no_flop_no_drop: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.percent <= 100.0:
            raise ValueError("rake percent must be in [0, 100]")
        if self.cap is not None and self.cap < 0:
            raise ValueError("rake cap must be non-negative")


@dataclass(frozen=True)
class TableRules:
    small_blind: int = 50
    big_blind: int = 100
    ante: int = 0
    rake: RakeRule | None = None  # None means no rake
    antes_count_for_pot_limit: bool = True  # rulesets differ; GTO Wizard ships both variants

    def __post_init__(self) -> None:
        if not (isinstance(self.small_blind, int) and isinstance(self.big_blind, int)
                and isinstance(self.ante, int)):
            raise TypeError("blinds and ante must be integer chips")
        if self.big_blind <= 0 or not 0 <= self.small_blind <= self.big_blind or self.ante < 0:
            raise ValueError("need 0 <= small_blind <= big_blind, big_blind > 0, ante >= 0")

    def describe(self) -> dict:
        return {
            "game": "PLO4", "betting": "pot-limit", "hole_cards": 4,
            "showdown": "exactly 2 hole + 3 board cards",
            "small_blind": self.small_blind, "big_blind": self.big_blind, "ante": self.ante,
            "antes_count_for_pot_limit": self.antes_count_for_pot_limit,
            "rake": None if self.rake is None else {
                "percent": self.rake.percent, "cap": self.rake.cap,
                "no_flop_no_drop": self.rake.no_flop_no_drop},
        }


@dataclass(frozen=True)
class LegalActions:
    can_fold: bool
    can_check: bool
    call_amount: int          # chips added by calling (0 when check is available)
    raise_type: ActionType | None  # BET, RAISE or None when aggression is not allowed
    min_to: int = 0           # smallest legal bet/raise-to (a short all-in may equal max_to)
    max_to: int = 0           # pot-limit or all-in cap

    @property
    def can_raise(self) -> bool:
        return self.raise_type is not None

    def validate(self, action: Action) -> None:
        t = action.type
        if t is ActionType.FOLD and not self.can_fold:
            raise IllegalActionError("fold is only offered when facing a bet")
        if t is ActionType.CHECK and not self.can_check:
            raise IllegalActionError("cannot check while facing a bet")
        if t is ActionType.CALL and self.can_check:
            raise IllegalActionError("nothing to call")
        if t in (ActionType.BET, ActionType.RAISE):
            if self.raise_type is not t:
                raise IllegalActionError(f"{t.value} is not available here")
            if not self.min_to <= action.to <= self.max_to:
                raise IllegalActionError(
                    f"{t.value} to {action.to} outside [{self.min_to}, {self.max_to}]")


@dataclass(frozen=True)
class ActionRecord:
    street: int
    seat: int
    type: ActionType
    added: int        # chips moved from stack into the pot
    to: int           # street commitment after the action
    all_in: bool
    full_raise: bool  # BET/RAISE that reopened betting


@dataclass(frozen=True)
class Post:
    seat: int
    kind: str         # "ante", "small_blind", "big_blind"
    amount: int


@dataclass(frozen=True)
class PotResult:
    amount: int
    eligible: tuple[int, ...]
    winners: tuple[int, ...]
    shares: tuple[int, ...]   # chips awarded to each winner (same order as winners)


@dataclass(frozen=True)
class HandResult:
    starting_stacks: tuple[int, ...]
    final_stacks: tuple[int, ...]
    net: tuple[int, ...]
    returned: tuple[int, ...]           # uncalled chips returned per seat
    pots: tuple[PotResult, ...]
    rake: int
    board: tuple[int, ...]              # cards actually dealt
    showdown: dict[int, tuple[int, ...]]  # seat -> revealed hole cards
    ranks: dict[int, int]               # seat -> PLO rank key at showdown


@dataclass(frozen=True)
class Observation:
    """Everything one seat may legally know at its decision point."""
    seat: int
    hand_id: int
    num_players: int
    button: int
    small_blind: int
    big_blind: int
    ante: int
    hole_cards: tuple[int, ...]
    board: tuple[int, ...]
    street: int
    starting_stacks: tuple[int, ...]
    stacks: tuple[int, ...]
    committed_street: tuple[int, ...]
    committed_total: tuple[int, ...]
    folded: tuple[bool, ...]
    pot: int
    current_bet: int
    to_call: int
    legal: LegalActions
    posts: tuple[Post, ...]
    history: tuple[ActionRecord, ...]
    limit_pot: int = 0   # P used by the pot-limit formulas (pot minus antes if they do not count)


@dataclass(frozen=True)
class PublicHandSummary:
    """What every seat may learn after a hand: no unrevealed hole cards, no undealt cards."""
    hand_id: int
    button: int
    starting_stacks: tuple[int, ...]
    board: tuple[int, ...]
    posts: tuple[Post, ...]
    history: tuple[ActionRecord, ...]
    showdown: dict[int, tuple[int, ...]]
    net: tuple[int, ...]


class HandState:
    """Full simulator state of one PLO4 hand.  Mutated in place by ``apply``."""

    def __init__(self, rules: TableRules, stacks: Sequence[int], button: int,
                 hole_cards: Sequence[Sequence[int]], board_runout: Sequence[int],
                 hand_id: int = 0) -> None:
        n = len(stacks)
        if not MIN_PLAYERS <= n <= MAX_PLAYERS:
            raise ValueError(f"PLO engine supports {MIN_PLAYERS}..{MAX_PLAYERS} players, got {n}")
        if any((not isinstance(s, (int, np.integer))) or s <= 0 for s in stacks):
            raise ValueError("every seat needs a positive integer stack")
        if not 0 <= button < n:
            raise ValueError("button out of range")
        if len(hole_cards) != n or any(len(h) != 4 for h in hole_cards):
            raise ValueError("each seat needs exactly 4 hole cards")
        if len(board_runout) != 5:
            raise ValueError("board run-out must have 5 cards")
        validate_disjoint(*hole_cards, board_runout)
        self.rules = rules
        self.n = n
        self.hand_id = hand_id
        self.button = button
        self.starting_stacks = tuple(int(s) for s in stacks)
        self.stacks = list(self.starting_stacks)
        self.hole_cards = tuple(tuple(int(c) for c in h) for h in hole_cards)
        self._runout = tuple(int(c) for c in board_runout)
        self.street = PREFLOP
        self.committed_street = [0] * n
        self.committed_total = [0] * n
        self.folded = [False] * n
        self.acted = [False] * n
        self.level_at_action = [0] * n
        self.current_bet = 0
        self.last_full_raise = rules.big_blind
        self.posts: list[Post] = []
        self.history: list[ActionRecord] = []
        self.to_act: int | None = None
        self.result: HandResult | None = None
        self._post_blinds()

    # ------------------------------------------------------------------ setup
    @property
    def sb_seat(self) -> int:
        return self.button if self.n == 2 else (self.button + 1) % self.n

    @property
    def bb_seat(self) -> int:
        return (self.sb_seat + 1) % self.n

    def _commit(self, seat: int, amount: int, street: bool = True) -> int:
        amount = min(int(amount), self.stacks[seat])
        self.stacks[seat] -= amount
        self.committed_total[seat] += amount
        if street:
            self.committed_street[seat] += amount
        return amount

    def _post_blinds(self) -> None:
        if self.rules.ante:
            for seat in range(self.n):
                self.posts.append(Post(seat, "ante", self._commit(seat, self.rules.ante, street=False)))
        if self.rules.small_blind:
            self.posts.append(Post(self.sb_seat, "small_blind",
                                   self._commit(self.sb_seat, self.rules.small_blind)))
        self.posts.append(Post(self.bb_seat, "big_blind", self._commit(self.bb_seat, self.rules.big_blind)))
        self.current_bet = self.rules.big_blind
        self.last_full_raise = self.rules.big_blind
        self._start_round(first=(self.bb_seat + 1) % self.n)

    # ---------------------------------------------------------------- queries
    @property
    def board(self) -> tuple[int, ...]:
        return self._runout[:_BOARD_SIZE_AFTER[self.street]]

    @property
    def is_terminal(self) -> bool:
        return self.result is not None

    @property
    def pot(self) -> int:
        return sum(self.committed_total)

    @property
    def limit_pot(self) -> int:
        """P in the pot-limit formulas (``pokerlab.plo.betting``): the pot incl. this round's bets."""
        if self.rules.antes_count_for_pot_limit:
            return self.pot
        return self.pot - sum(p.amount for p in self.posts if p.kind == "ante")

    def _can_act(self, seat: int) -> bool:
        return not self.folded[seat] and self.stacks[seat] > 0

    def _owes(self, seat: int) -> int:
        return max(0, self.current_bet - self.committed_street[seat])

    def legal_actions(self) -> LegalActions:
        if self.to_act is None:
            raise IllegalActionError("hand is over")
        s = self.to_act
        to_call = self._owes(s)
        call_amount = min(to_call, self.stacks[s])
        others_live = any(self._can_act(o) for o in range(self.n) if o != s)
        reopened = (not self.acted[s]) or (
            self.current_bet - self.level_at_action[s] >= self.last_full_raise)
        raise_type = None
        min_to = max_to = 0
        window = None
        if others_live and reopened:
            window = raise_window(self.limit_pot, self.committed_street[s], to_call, self.stacks[s],
                                  self.last_full_raise, self.rules.big_blind)
        if window is not None:
            raise_type = ActionType.BET if self.current_bet == 0 else ActionType.RAISE
            min_to, max_to = window.min_to, window.max_to
        return LegalActions(can_fold=to_call > 0, can_check=to_call == 0,
                            call_amount=call_amount if to_call > 0 else 0,
                            raise_type=raise_type, min_to=min_to, max_to=max_to)

    # ---------------------------------------------------------------- actions
    def apply(self, action: Action) -> None:
        legal = self.legal_actions()
        legal.validate(action)
        s = self.to_act
        assert s is not None
        t = action.type
        full = False
        if t is ActionType.FOLD:
            self.folded[s] = True
            added = 0
        elif t is ActionType.CHECK:
            added = 0
        elif t is ActionType.CALL:
            added = self._commit(s, legal.call_amount)
        else:
            added = self._commit(s, action.to - self.committed_street[s])
            increment = action.to - self.current_bet
            full = increment >= self.last_full_raise
            if full:
                self.last_full_raise = increment
            self.current_bet = action.to
        self.acted[s] = True
        self.level_at_action[s] = self.current_bet
        self.history.append(ActionRecord(self.street, s, t, added, self.committed_street[s],
                                         self.stacks[s] == 0, full))
        self._advance(after=s)

    def _start_round(self, first: int) -> None:
        """Find the first seat to act from ``first`` clockwise, or close the round."""
        self.to_act = None
        if self._round_complete():
            self._end_round()
            return
        for k in range(self.n):
            seat = (first + k) % self.n
            if self._needs_action(seat):
                self.to_act = seat
                return
        self._end_round()

    def _needs_action(self, seat: int) -> bool:
        return self._can_act(seat) and (not self.acted[seat] or self._owes(seat) > 0)

    def _round_complete(self) -> bool:
        live = [s for s in range(self.n) if self._can_act(s)]
        if len(live) <= 1:
            return all(self._owes(s) == 0 for s in live)
        return not any(self._needs_action(s) for s in live)

    def _advance(self, after: int) -> None:
        if sum(not f for f in self.folded) == 1:
            self._settle()
            return
        self._start_round(first=(after + 1) % self.n)

    def _end_round(self) -> None:
        if sum(not f for f in self.folded) == 1:
            self._settle()
            return
        if self.street == RIVER:
            self._settle()
            return
        self.street += 1
        self.committed_street = [0] * self.n
        self.acted = [False] * self.n
        self.level_at_action = [0] * self.n
        self.current_bet = 0
        self.last_full_raise = self.rules.big_blind
        self._start_round(first=(self.button + 1) % self.n)

    # ------------------------------------------------------------- settlement
    def _settle(self) -> None:
        n = self.n
        live = [s for s in range(n) if not self.folded[s]]
        contrib = list(self.committed_total)
        returned = [0] * n
        # Nobody can win more from a player than they put in themselves, so chips above the
        # largest live contribution (e.g. folded antes/blinds over a short all-in) go back to
        # whoever put them in; so does the unmatched top of the largest live contribution.
        cap = max(contrib[s] for s in live)
        for s in range(n):
            if contrib[s] > cap:
                returned[s] = contrib[s] - cap
                contrib[s] = cap
        top = max(live, key=lambda s: contrib[s])
        second = max(contrib[s] for s in range(n) if s != top)
        if contrib[top] > second:
            returned[top] += contrib[top] - second
            contrib[top] = second

        pots: list[tuple[int, tuple[int, ...]]] = []
        previous = 0
        for level in sorted({c for c in contrib if c > 0}):
            amount = sum(min(c, level) - min(c, previous) for c in contrib)
            eligible = tuple(s for s in range(n) if not self.folded[s] and contrib[s] >= level)
            if not eligible:
                raise AssertionError("pot level without an eligible player")
            if pots and pots[-1][1] == eligible:
                pots[-1] = (pots[-1][0] + amount, eligible)
            else:
                pots.append((amount, eligible))
            previous = level

        rake = self._rake(sum(a for a, _ in pots))
        takes = _proportional([a for a, _ in pots], rake)
        showdown = len(live) > 1
        ranks: dict[int, int] = {}
        if showdown:
            keys = plo_rank_batch(np.array([self.hole_cards[s] for s in live]), self._runout)
            ranks = {s: int(k) for s, k in zip(live, keys)}

        awards = list(returned)
        pot_results = []
        for (amount, eligible), take in zip(pots, takes):
            amount -= take
            if len(eligible) == 1 or not showdown:
                winners = (eligible[0],) if len(eligible) == 1 else tuple(live)
            else:
                best = max(ranks[s] for s in eligible)
                winners = tuple(s for s in eligible if ranks[s] == best)
            shares = self._split(amount, winners)
            for w, share in zip(winners, shares):
                awards[w] += share
            pot_results.append(PotResult(amount, eligible, winners, shares))

        final = tuple(self.stacks[s] + awards[s] for s in range(n))
        if sum(final) + rake != sum(self.starting_stacks):
            raise AssertionError("chip conservation violated")
        dealt = self._runout if showdown else self.board
        self.result = HandResult(
            starting_stacks=self.starting_stacks, final_stacks=final,
            net=tuple(f - s for f, s in zip(final, self.starting_stacks)),
            returned=tuple(returned), pots=tuple(pot_results), rake=rake, board=tuple(dealt),
            showdown={s: self.hole_cards[s] for s in live} if showdown else {},
            ranks=ranks)
        if showdown:
            self.street = RIVER
        self.to_act = None

    def _split(self, amount: int, winners: tuple[int, ...]) -> tuple[int, ...]:
        base, odd = divmod(amount, len(winners))
        shares = {w: base for w in winners}
        clockwise = sorted(winners, key=lambda s: (s - self.button - 1) % self.n)
        for w in clockwise[:odd]:
            shares[w] += 1
        return tuple(shares[w] for w in winners)

    def _rake(self, settled_pot: int) -> int:
        rule = self.rules.rake
        if rule is None or rule.percent == 0:
            return 0
        if rule.no_flop_no_drop and self.street == PREFLOP and sum(not f for f in self.folded) == 1:
            return 0
        rake = int(settled_pot * Fraction(str(rule.percent)) / 100)  # exact decimal, floored
        return rake if rule.cap is None else min(rake, rule.cap)

    # ------------------------------------------------------------------ views
    def public_summary(self) -> PublicHandSummary:
        if self.result is None:
            raise ValueError("hand not finished")
        return PublicHandSummary(self.hand_id, self.button, self.starting_stacks, self.result.board,
                                 tuple(self.posts), tuple(self.history), dict(self.result.showdown),
                                 self.result.net)

    def describe(self) -> str:
        holes = " ".join(f"s{s}:{format_cards(h)}" for s, h in enumerate(self.hole_cards))
        return f"hand {self.hand_id} btn={self.button} {holes} board={format_cards(self.board)}"


def _proportional(amounts: list[int], total: int) -> list[int]:
    """Split ``total`` chips across pots in proportion to their size (largest remainder)."""
    size = sum(amounts)
    if total == 0 or size == 0:
        return [0] * len(amounts)
    shares = [total * a // size for a in amounts]
    remainders = sorted(range(len(amounts)), key=lambda k: (-(total * amounts[k] % size), k))
    for k in remainders[:total - sum(shares)]:
        shares[k] += 1
    return shares


def observe(state: HandState, seat: int) -> Observation:
    """Build the acting player's observation; never includes other private cards."""
    if state.to_act != seat:
        raise ValueError(f"seat {seat} is not to act")
    legal = state.legal_actions()
    return Observation(
        seat=seat, hand_id=state.hand_id, num_players=state.n, button=state.button,
        small_blind=state.rules.small_blind, big_blind=state.rules.big_blind, ante=state.rules.ante,
        hole_cards=state.hole_cards[seat], board=state.board, street=state.street,
        starting_stacks=state.starting_stacks, stacks=tuple(state.stacks),
        committed_street=tuple(state.committed_street), committed_total=tuple(state.committed_total),
        folded=tuple(state.folded), pot=state.pot, current_bet=state.current_bet,
        to_call=state._owes(seat), legal=legal, posts=tuple(state.posts), history=tuple(state.history),
        limit_pot=state.limit_pot)


def deal_hand(rules: TableRules, stacks: Sequence[int], button: int, rng: random.Random,
              hand_id: int = 0, preset_holes: dict[int, Sequence[int]] | None = None,
              preset_board: Sequence[int] = ()) -> HandState:
    """Shuffle with ``rng`` and deal; preset cards are validated for conflicts first."""
    preset_holes = dict(preset_holes or {})
    preset_board = tuple(int(c) for c in preset_board)
    if len(preset_board) > 5:
        raise ValueError("preset board has more than 5 cards")
    validate_disjoint(*preset_holes.values(), preset_board)
    used = {c for h in preset_holes.values() for c in h} | set(preset_board)
    deck = [c for c in DECK if c not in used]
    rng.shuffle(deck)
    holes = []
    for seat in range(len(stacks)):
        if seat in preset_holes:
            holes.append(tuple(preset_holes[seat]))
        else:
            holes.append(tuple(deck[:4]))
            del deck[:4]
    board = preset_board + tuple(deck[:5 - len(preset_board)])
    return HandState(rules, stacks, button, holes, board, hand_id=hand_id)
