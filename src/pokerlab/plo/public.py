"""Reconstruct the public betting context of a hand from one player's observation.

The betting state (pot, amounts to call, raise rights) depends only on public
information, so it can be replayed with placeholder cards for everything the observer
cannot see.  The placeholders never influence a decision context or a range: they only
satisfy the engine's card-conflict checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pokerlab.plo.cards import DECK
from pokerlab.plo.engine import RIVER, Action, ActionType, HandState, Observation, TableRules


@dataclass(frozen=True)
class PublicDecision:
    """One past decision as every player saw it."""
    street: int
    seat: int
    action: ActionType
    to: int
    facing_bet: bool
    can_raise: bool
    pot: int
    to_call: int


@dataclass
class PublicReplay:
    decisions: list[PublicDecision]
    state: HandState                     # replayed up to the observer's current decision
    river_pot: int | None = None         # pot when the river betting started (None: not reached)
    river_stacks: tuple[int, ...] | None = None
    street_start: dict = field(default_factory=dict)   # street -> (pot, stacks) when its betting started


def rules_from_observation(obs: Observation) -> TableRules:
    counted = obs.ante == 0 or obs.limit_pot == obs.pot
    return TableRules(obs.small_blind, obs.big_blind, obs.ante, None, counted)


def replay(obs: Observation) -> PublicReplay:
    used = set(obs.hole_cards) | set(obs.board)
    spare = [c for c in DECK if c not in used]
    holes = []
    for seat in range(obs.num_players):
        if seat == obs.seat:
            holes.append(tuple(obs.hole_cards))
        else:
            holes.append(tuple(spare[:4]))
            del spare[:4]
    runout = tuple(obs.board) + tuple(spare[:5 - len(obs.board)])
    state = HandState(rules_from_observation(obs), obs.starting_stacks, obs.button, holes, runout,
                      hand_id=obs.hand_id)
    out = PublicReplay([], state)
    for record in obs.history:
        out.street_start.setdefault(state.street, (state.pot, tuple(state.stacks)))
        if state.street == RIVER and out.river_pot is None:
            out.river_pot, out.river_stacks = state.pot, tuple(state.stacks)
        legal = state.legal_actions()
        out.decisions.append(PublicDecision(record.street, record.seat, record.type, record.to,
                                            legal.can_fold, legal.can_raise, state.pot,
                                            state._owes(record.seat)))
        state.apply(Action(record.type, record.to))
    out.street_start.setdefault(state.street, (state.pot, tuple(state.stacks)))
    if state.street == RIVER and out.river_pot is None:
        out.river_pot, out.river_stacks = state.pot, tuple(state.stacks)
    if state.to_act != obs.seat or state.pot != obs.pot or tuple(state.stacks) != obs.stacks:
        raise AssertionError("public replay diverged from the observation")
    return out
