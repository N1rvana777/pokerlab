"""Independent oracles for small joint turn + river games; never production output.

* ``turn_best_response_reference`` / ``turn_profile_value_reference``: recursion with explicit
  loops over individual opponent hands and explicit river cards; payoffs from the game's scalar
  ``pair_outcome`` (``plo_rank_reference`` on the 5-card board plus set disjointness).  They
  share neither the per-card matrices nor the card-batched traversal with the solver.
* ``solve_turn_sequence_form``: exact equilibrium value of the joint game by the sequence-form
  LP (SciPy HiGHS), with the river deal as explicit chance probabilities, plus behaviour
  strategies for both players.

Both scale as hands x hands x cards x tree and are meant for tiny instances only.
"""
from __future__ import annotations

import numpy as np

from pokerlab.plo.subgame.tree import DECISION, FOLD, SHOWDOWN
from pokerlab.plo.subgame.turn import TurnRiverGame


def _share(game: TurnRiverGame, p: int, i: int, j: int, card: int | None) -> tuple[bool, float]:
    """(compatible, player p's showdown share) for p's hand i vs the opponent's hand j."""
    a, b = (i, j) if p == 0 else (j, i)
    if card is None:
        ok = not (set(game.hands[0][a]) & set(game.hands[1][b]))
        return ok, 0.0
    ok, share0 = game.pair_outcome(a, b, card)
    return ok, (share0 if p == 0 else 1.0 - share0) if ok else 0.0


def _terminal(node, p, pot, offset, mass_share):
    """Utility from the turn start for one (hand, opponent hand) pair."""
    if node.kind == FOLD:
        return (-(node.commit[p]) if node.player == p else pot + node.commit[node.player]) - offset
    c = node.commit[0]
    return (pot + 2 * c) * mass_share - c - offset


def _value(game, profile, p, i, maximise):
    o = 1 - p
    cards = [int(c) for c in game.river_cards]

    def turn(nid, opp):
        node = game.turn_tree.nodes[nid]
        if node.kind == FOLD:
            return sum(r * _terminal(node, p, game.pot, 0, 0.0) for r in opp.values())
        if node.kind == SHOWDOWN:
            leaf = game.leaves[nid]
            total = 0.0
            for k, card in enumerate(cards):
                if card in game.hands[p][i]:
                    continue
                opp_k = {j: r for j, r in opp.items() if card not in game.hands[o][j]}
                if leaf.tree is None:
                    v = sum(r * ((game.pot + 2 * leaf.commit) * _share(game, p, i, j, card)[1] - leaf.commit)
                            for j, r in opp_k.items())
                else:
                    v = river(leaf, k, card, leaf.tree.root, opp_k)
                total += v / game.valid_cards_per_pair
            return total
        if node.player == p:
            values = [turn(c, opp) for c in node.children]
            if maximise:
                return max(values)
            sigma = profile["turn"][nid][i]
            return sum(s * v for s, v in zip(sigma, values))
        sigma = profile["turn"][nid]
        return sum(turn(c, {j: r * sigma[j][a] for j, r in opp.items()}) for a, c in enumerate(node.children))

    def river(leaf, k, card, rid, opp):
        node = leaf.tree.nodes[rid]
        if node.kind != DECISION:
            pot = leaf.tree.config.pot
            return sum(r * _terminal(node, p, pot, leaf.commit, _share(game, p, i, j, card)[1])
                       for j, r in opp.items())
        if node.player == p:
            values = [river(leaf, k, card, c, opp) for c in node.children]
            if maximise:
                return max(values)
            sigma = profile["river"][(leaf.turn_node, rid)][k][i]
            return sum(s * v for s, v in zip(sigma, values))
        sigma = profile["river"][(leaf.turn_node, rid)][k]
        return sum(river(leaf, k, card, c, {j: r * sigma[j][a] for j, r in opp.items()})
                   for a, c in enumerate(node.children))

    opp = {j: float(game.weights[o][j]) for j in range(game.size(o)) if _share(game, p, i, j, None)[0]}
    return turn(game.turn_tree.root, opp), sum(opp.values())


def _root(game, profile, p, maximise):
    total = z = 0.0
    for i in range(game.size(p)):
        value, mass = _value(game, profile, p, i, maximise)
        total += game.weights[p][i] * value
        z += game.weights[p][i] * mass
    return total / z


def turn_best_response_reference(game: TurnRiverGame, profile: dict, p: int) -> float:
    return _root(game, profile, p, True)


def turn_profile_value_reference(game: TurnRiverGame, profile: dict, p: int) -> float:
    return _root(game, profile, p, False)


def solve_turn_sequence_form(game: TurnRiverGame) -> dict:
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix, hstack

    sizes = (game.size(0), game.size(1))
    cards = [int(c) for c in game.river_cards]
    seq = [dict(), dict()]
    infosets = [[], []]
    count = [1, 1]
    terminals = []          # (node, pot, offset, card or None, last0, last1)

    def own_parent(p, i, last):
        return seq[p][(i, *last[p])] if last[p] else 0

    def open_infoset(p, key, n_actions, last, hands):
        for i in hands:
            parent = own_parent(p, i, last)
            cols = []
            for a in range(n_actions):
                seq[p][(i, *key, a)] = count[p]
                cols.append(count[p])
                count[p] += 1
            infosets[p].append((i, key, parent, cols))

    def walk_turn(nid, last):
        node = game.turn_tree.nodes[nid]
        if node.kind == FOLD:
            terminals.append((node, game.pot, 0, None, last))
            return
        if node.kind == SHOWDOWN:
            leaf = game.leaves[nid]
            for k, card in enumerate(cards):
                if leaf.tree is None:
                    terminals.append((node, game.pot, 0, card, last))
                else:
                    walk_river(leaf, k, card, leaf.tree.root, last)
            return
        p = node.player
        open_infoset(p, ("t", nid), len(node.children), last, range(sizes[p]))
        for a, child in enumerate(node.children):
            new = list(last)
            new[p] = ("t", nid, a)
            walk_turn(child, tuple(new))

    def walk_river(leaf, k, card, rid, last):
        node = leaf.tree.nodes[rid]
        if node.kind != DECISION:
            terminals.append((node, leaf.tree.config.pot, leaf.commit, card, last))
            return
        p = node.player
        live = [i for i in range(sizes[p]) if card not in game.hands[p][i]]
        open_infoset(p, ("r", leaf.turn_node, k, rid), len(node.children), last, live)
        for a, child in enumerate(node.children):
            new = list(last)
            new[p] = ("r", leaf.turn_node, k, rid, a)
            walk_river(leaf, k, card, child, tuple(new))

    walk_turn(game.turn_tree.root, (None, None))

    def constraints(p):
        rows, cols, vals = [0], [0], [1.0]
        for r, (_, _, parent, children) in enumerate(infosets[p], start=1):
            rows += [r] * (len(children) + 1)
            cols += children + [parent]
            vals += [1.0] * len(children) + [-1.0]
        rhs = np.zeros(len(infosets[p]) + 1)
        rhs[0] = 1.0
        return coo_matrix((vals, (rows, cols)), shape=(len(infosets[p]) + 1, count[p])).tocsr(), rhs

    E, e = constraints(0)
    F, f = constraints(1)
    z = sum(game.weights[0][i] * game.weights[1][j] for i in range(sizes[0]) for j in range(sizes[1])
            if _share(game, 0, i, j, None)[0])
    rows, cols, vals = [], [], []
    for node, pot, offset, card, last in terminals:
        for i in range(sizes[0]):
            for j in range(sizes[1]):
                if card is None:
                    ok, share = _share(game, 0, i, j, None)
                    prob = 1.0
                else:
                    ok, share = _share(game, 0, i, j, card)
                    prob = 1.0 / game.valid_cards_per_pair
                if not ok:
                    continue
                u0 = _terminal(node, 0, pot, offset, share)
                rows.append(seq[0][(i, *last[0])] if last[0] else 0)
                cols.append(seq[1][(j, *last[1])] if last[1] else 0)
                vals.append(game.weights[0][i] * game.weights[1][j] * prob * u0 / z)
    A = coo_matrix((vals, (rows, cols)), shape=(count[0], count[1])).tocsr()
    m_f, m_e = F.shape[0], E.shape[0]
    res0 = linprog(np.r_[np.zeros(count[0]), -f], A_ub=hstack([-A.T, F.T]).tocsr(),
                   b_ub=np.zeros(count[1]), A_eq=hstack([E, coo_matrix((m_e, m_f))]).tocsr(), b_eq=e,
                   bounds=[(0, None)] * count[0] + [(None, None)] * m_f, method="highs")
    res1 = linprog(np.r_[np.zeros(count[1]), e], A_ub=hstack([A, -E.T]).tocsr(),
                   b_ub=np.zeros(count[0]), A_eq=hstack([F, coo_matrix((m_f, m_e))]).tocsr(), b_eq=f,
                   bounds=[(0, None)] * count[1] + [(None, None)] * m_e, method="highs")
    if not (res0.success and res1.success):
        raise RuntimeError(f"LP failed: {res0.message} / {res1.message}")

    profile = {"turn": {}, "river": {}}
    for nid in game.turn_tree.decision_nodes():
        node = game.turn_tree.nodes[nid]
        profile["turn"][nid] = np.full((sizes[node.player], len(node.children)), 1.0 / len(node.children))
    for leaf in game.leaves.values():
        if leaf.tree is None:
            continue
        for rid in leaf.tree.decision_nodes():
            node = leaf.tree.nodes[rid]
            profile["river"][(leaf.turn_node, rid)] = np.full(
                (len(cards), sizes[node.player], len(node.children)), 1.0 / len(node.children))
    for p, plan in ((0, res0.x[:count[0]]), (1, res1.x[:count[1]])):
        for i, key, parent, children in infosets[p]:
            mass = plan[parent]
            probs = plan[children] / mass if mass > 1e-12 else np.full(len(children), 1.0 / len(children))
            probs = np.clip(probs, 0.0, None)
            probs = probs / probs.sum()
            if key[0] == "t":
                profile["turn"][key[1]][i] = probs
            else:
                _, leaf_id, k, rid = key
                profile["river"][(leaf_id, rid)][k][i] = probs
    return {"value0": float(-res0.fun), "value0_dual": float(res1.fun), "profile": profile,
            "variables": [count[0], count[1]], "nonzeros": int(A.nnz)}
