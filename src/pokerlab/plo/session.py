"""Cross-hand sessions on top of the single-hand engine.

Two stack modes:
* ``reset`` (fixed root): every hand starts from the configured stacks; the
  button moves one seat per hand.  Hands are independent experiments.
* ``carry``: final stacks carry into the next hand.  A player with 0 chips at
  the start of a hand is handled by ``bust_policy``: ``rebuy`` (top back up to
  the starting stack, counted separately from table winnings), ``leave`` (the
  seat is removed; the session ends when fewer than two remain) or ``stop``.
  The button moves to the next remaining player (simplified moving button: no
  dead-button rule).

Agents only ever receive ``Observation`` objects and post-hand
``PublicHandSummary`` objects.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Sequence

from pokerlab.plo.cards import format_cards
from pokerlab.plo.engine import (
    HandResult, HandState, TableRules, deal_hand, observe,
)

STACK_MODES = ("reset", "carry")
BUST_POLICIES = ("rebuy", "leave", "stop")


@dataclass(frozen=True)
class SessionConfig:
    rules: TableRules
    starting_stacks: tuple[int, ...]
    stack_mode: str = "reset"
    bust_policy: str = "rebuy"
    hands: int = 100
    seed: int = 0
    button_start: int = 0

    def __post_init__(self) -> None:
        if not 2 <= len(self.starting_stacks) <= 8:
            raise ValueError("sessions support 2..8 players")
        if any(int(s) <= 0 for s in self.starting_stacks):
            raise ValueError("starting stacks must be positive")
        if self.stack_mode not in STACK_MODES:
            raise ValueError(f"stack_mode must be one of {STACK_MODES}")
        if self.bust_policy not in BUST_POLICIES:
            raise ValueError(f"bust_policy must be one of {BUST_POLICIES}")
        if self.hands < 0:
            raise ValueError("hands must be non-negative")


@dataclass
class PlayerLedger:
    player: int
    stack: int
    hands_played: int = 0
    net: int = 0              # table result in chips; rebuys are not winnings
    rebuys: int = 0
    rebuy_chips: int = 0
    active: bool = True
    hand_nets: list[int] = field(default_factory=list)


@dataclass
class SessionResult:
    config: SessionConfig
    ledgers: list[PlayerLedger]
    hands_played: int
    stop_reason: str
    rake: int


def hand_seed(seed: int, index: int) -> int:
    """Deterministic per-hand deck seed (independent of agents' decisions)."""
    return (int(seed) * 1_000_003 + int(index) * 7_919 + 17) % (2 ** 63)


def play_hand(state: HandState, seat_agents: Sequence) -> HandResult:
    while state.to_act is not None:
        seat = state.to_act
        state.apply(seat_agents[seat].act(observe(state, seat)))
    assert state.result is not None
    return state.result


def hand_record(state: HandState, players: Sequence[int]) -> dict:
    """Simulator ground-truth record (contains every hole card): for training data, not for agents."""
    r = state.result
    assert r is not None
    return {
        "hand_id": state.hand_id, "button_seat": state.button, "players": list(players),
        "starting_stacks": list(r.starting_stacks),
        "hole_cards": [format_cards(h) for h in state.hole_cards],
        "board": format_cards(r.board),
        "posts": [[p.seat, p.kind, p.amount] for p in state.posts],
        "actions": [[a.street, a.seat, a.type.value, a.added, a.to, a.all_in, a.full_raise]
                    for a in state.history],
        "returned": list(r.returned),
        "pots": [{"amount": p.amount, "eligible": list(p.eligible), "winners": list(p.winners),
                  "shares": list(p.shares)} for p in r.pots],
        "rake": r.rake, "net": list(r.net),
        "showdown": {str(s): format_cards(h) for s, h in r.showdown.items()},
    }


def _next_active(ledgers: list[PlayerLedger], after: int) -> int:
    n = len(ledgers)
    for k in range(1, n + 1):
        p = (after + k) % n
        if ledgers[p].active:
            return p
    raise ValueError("no active player")


def run_session(config: SessionConfig, agents: Sequence,
                on_hand: Callable[[dict], None] | None = None) -> SessionResult:
    n = len(config.starting_stacks)
    if len(agents) != n:
        raise ValueError("need one agent per player")
    ledgers = [PlayerLedger(p, int(config.starting_stacks[p])) for p in range(n)]
    carry = config.stack_mode == "carry"
    button_player = config.button_start % n
    played = 0
    rake = 0
    stop = "hand limit reached"
    for h in range(config.hands):
        if carry:
            stop_now = False
            for lg in ledgers:
                if lg.active and lg.stack == 0:
                    if config.bust_policy == "rebuy":
                        lg.stack = int(config.starting_stacks[lg.player])
                        lg.rebuys += 1
                        lg.rebuy_chips += lg.stack
                    elif config.bust_policy == "leave":
                        lg.active = False
                    else:
                        stop_now = True
            if stop_now:
                stop = "a player busted (bust_policy=stop)"
                break
        seated = [lg for lg in ledgers if lg.active]
        if len(seated) < 2:
            stop = "fewer than two players with chips"
            break
        if h > 0:
            button_player = _next_active(ledgers, button_player)
        seat_of = {lg.player: k for k, lg in enumerate(seated)}
        stacks = [lg.stack if carry else int(config.starting_stacks[lg.player]) for lg in seated]
        state = deal_hand(config.rules, stacks, seat_of[button_player],
                          random.Random(hand_seed(config.seed, h)), hand_id=h)
        players = tuple(lg.player for lg in seated)
        result = play_hand(state, [agents[p] for p in players])
        rake += result.rake
        for k, lg in enumerate(seated):
            lg.hands_played += 1
            lg.net += result.net[k]
            lg.hand_nets.append(result.net[k])
            if carry:
                lg.stack = result.final_stacks[k]
        summary = state.public_summary()
        for k, p in enumerate(players):
            agents[p].end_hand(summary, k, players)
        if on_hand is not None:
            on_hand(hand_record(state, players))
        played += 1
    if carry:
        total = sum(lg.stack for lg in ledgers) + rake
        expected = sum(int(s) for s in config.starting_stacks) + sum(lg.rebuy_chips for lg in ledgers)
        if total != expected:
            raise AssertionError("session chip conservation violated")
    return SessionResult(config, ledgers, played, stop, rake)
