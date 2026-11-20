"""Two-player single-street betting tree with pot-limit sizing (river subgames).

Player 0 is out of position and acts first; player 1 is in position.  Amounts
are integer chips committed on this street.  ``pot`` is what was already in the
pot when the street started (sunk for both players).  The effective stack caps
every commitment, because unmatched chips would be returned anyway.

Sizing uses ``pokerlab.plo.betting`` -- the same functions as the engine -- with
P = pot + both street commitments, h = the actor's commitment and c = its amount
to call.  Each bet/raise node offers the configured exact pot fractions that are
legal, plus the window's boundaries (minimum legal bet/raise; pot-size raise or a
short all-in below the pot limit) unless switched off; duplicates collapse.  The
tree is an action abstraction: other sizes are not represented.

A tree normally starts at the beginning of the street, but ``RootState`` can place
the root at any later point (for re-solving after an opponent action).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Sequence

from pokerlab.plo.betting import DEFAULT_SIZES, abstract_targets, parse_sizes, raise_window

DECISION, FOLD, SHOWDOWN = "decision", "fold", "showdown"


@dataclass(frozen=True)
class BettingConfig:
    pot: int
    stacks: tuple[int, int]
    bet_sizes: tuple[Fraction, ...] = DEFAULT_SIZES     # pot fractions for opening bets
    raise_sizes: tuple[Fraction, ...] = DEFAULT_SIZES   # f in h + c + f(P + c)
    include_min_raise: bool = True    # minimum legal bet/raise (or short all-in below it)
    include_max_raise: bool = True    # pot-size raise, or short all-in when stack < pot limit
    max_raises: int = 2               # raises allowed after the opening bet
    min_bet: int = 1                  # normally the big blind in chips

    def __post_init__(self) -> None:
        if int(self.pot) <= 0 or len(self.stacks) != 2 or min(self.stacks) <= 0:
            raise ValueError("need a positive pot and two positive stacks")
        object.__setattr__(self, "bet_sizes", parse_sizes(self.bet_sizes))
        object.__setattr__(self, "raise_sizes", parse_sizes(self.raise_sizes))
        if self.max_raises < 0 or self.min_bet < 1:
            raise ValueError("max_raises must be >= 0 and min_bet >= 1")

    @property
    def effective_stack(self) -> int:
        return int(min(self.stacks))

    def describe(self) -> dict:
        return {"pot": self.pot, "stacks": list(self.stacks), "effective_stack": self.effective_stack,
                "bet_sizes_pot_fraction": [str(f) for f in self.bet_sizes],
                "raise_sizes_pot_fraction": [str(f) for f in self.raise_sizes],
                "include_min_raise": self.include_min_raise,
                "include_max_raise": self.include_max_raise,
                "max_raises": self.max_raises, "min_bet": self.min_bet,
                "rounding": "nearest chip, halves up, exact rational arithmetic"}


@dataclass(frozen=True)
class RootState:
    """Where the tree starts: street commitments, actor, and the betting state at that point."""
    commit: tuple[int, int] = (0, 0)
    actor: int = 0
    current_bet: int = 0
    last_increment: int = 0     # 0 means "the minimum bet" (min_bet)
    raises: int = 0
    checked: bool = False       # player 0 has checked (player 1 checking ends the street)

    def describe(self) -> dict:
        return {"commit": list(self.commit), "actor": self.actor, "current_bet": self.current_bet,
                "last_increment": self.last_increment, "raises": self.raises, "checked": self.checked}


@dataclass
class Node:
    id: int
    kind: str
    player: int                      # actor (decision), folder (fold), -1 (showdown)
    commit: tuple[int, int]          # chips each player committed on this street
    history: tuple[str, ...]
    actions: tuple[str, ...] = ()
    children: tuple[int, ...] = ()
    all_in: tuple[bool, ...] = ()
    current_bet: int = 0
    raises: int = 0


@dataclass
class BettingTree:
    config: BettingConfig
    root_state: RootState = field(default_factory=RootState)
    nodes: list[Node] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.nodes:
            r = self.root_state
            if max(r.commit) > self.config.effective_stack or r.current_bet != max(r.commit):
                raise ValueError("root commitments must be within the effective stack and match the bet")
            self._build(tuple(r.commit), r.actor, r.current_bet,
                        r.last_increment or self.config.min_bet, r.raises, (), r.checked)

    @property
    def root(self) -> int:
        return 0

    def decision_nodes(self, player: int | None = None) -> list[int]:
        return [n.id for n in self.nodes
                if n.kind == DECISION and (player is None or n.player == player)]

    def find(self, history: Sequence[str]) -> int:
        node = self.nodes[0]
        for label in history:
            if node.kind != DECISION or label not in node.actions:
                raise KeyError(f"history {list(history)} is not in the tree")
            node = self.nodes[node.children[node.actions.index(label)]]
        return node.id

    def summary(self) -> dict:
        kinds = [n.kind for n in self.nodes]
        return {"nodes": len(self.nodes), "decision": kinds.count(DECISION),
                "fold_terminals": kinds.count(FOLD), "showdown_terminals": kinds.count(SHOWDOWN),
                "max_actions": max((len(n.actions) for n in self.nodes), default=0),
                "root": self.root_state.describe()}

    # ----------------------------------------------------------------- build
    def _new(self, **kwargs) -> Node:
        node = Node(id=len(self.nodes), **kwargs)
        self.nodes.append(node)
        return node

    def targets(self, commit: tuple[int, int], actor: int, current_bet: int,
                last_increment: int) -> list[int]:
        """Abstract raise-to amounts for ``actor`` (empty when it cannot raise)."""
        cfg = self.config
        h = commit[actor]
        c = current_bet - h
        window = raise_window(cfg.pot + commit[0] + commit[1], h, c, cfg.effective_stack - h,
                              last_increment, cfg.min_bet)
        if window is None:
            return []
        sizes = cfg.bet_sizes if current_bet == 0 else cfg.raise_sizes
        return abstract_targets(cfg.pot + commit[0] + commit[1], h, c, window, sizes,
                                cfg.include_min_raise, cfg.include_max_raise)

    def _build(self, commit: tuple[int, int], actor: int, current_bet: int, last_increment: int,
               raises: int, history: tuple[str, ...], checked: bool) -> int:
        cfg = self.config
        node = self._new(kind=DECISION, player=actor, commit=commit, history=history,
                         current_bet=current_bet, raises=raises)
        other = 1 - actor
        to_call = current_bet - commit[actor]
        stack = cfg.effective_stack
        labels: list[str] = []
        children: list[int] = []
        all_in: list[bool] = []

        def add(label: str, child: int, shove: bool) -> None:
            labels.append(label)
            children.append(child)
            all_in.append(shove)

        if to_call == 0:
            if actor == 0 and not checked:
                child = self._build(commit, 1, 0, cfg.min_bet, 0, history + ("check",), True)
            else:
                child = self._new(kind=SHOWDOWN, player=-1, commit=commit,
                                  history=history + ("check",)).id
            add("check", child, False)
            for amount in self.targets(commit, actor, current_bet, last_increment):
                new = list(commit)
                new[actor] = amount
                label = f"bet:{amount}"
                increment = amount if amount >= cfg.min_bet else last_increment  # short all-in bet
                add(label, self._build(tuple(new), other, amount, increment, 0, history + (label,),
                                       checked), amount == stack)
        else:
            add("fold", self._new(kind=FOLD, player=actor, commit=commit,
                                  history=history + ("fold",)).id, False)
            called = (current_bet, current_bet)
            add("call", self._new(kind=SHOWDOWN, player=-1, commit=called,
                                  history=history + ("call",)).id, False)
            if raises < cfg.max_raises:
                for to in self.targets(commit, actor, current_bet, last_increment):
                    new = list(commit)
                    new[actor] = to
                    label = f"raise:{to}"
                    increment = max(to - current_bet, last_increment)
                    add(label, self._build(tuple(new), other, to, increment, raises + 1,
                                           history + (label,), checked), to == stack)
        node.actions = tuple(labels)
        node.children = tuple(children)
        node.all_in = tuple(all_in)
        return node.id
