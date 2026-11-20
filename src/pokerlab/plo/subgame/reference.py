"""Independent oracles for small subgames; never used as production solver output.

* ``best_response_reference`` / ``profile_value_reference``: plain recursion over
  the tree with explicit loops over individual opponent hands, payoffs from the
  instance's scalar ``pair_outcome`` (for PLO: ``plo_rank_reference`` plus set
  disjointness), so they share neither the vectorised evaluator nor the
  showdown matrices / inclusion-exclusion code with the solver.
* ``solve_sequence_form``: the exact equilibrium value via the sequence-form
  linear program (Koller, Megiddo & von Stengel) solved with SciPy HiGHS, plus
  behaviour strategies for both players.

Both scale as (hands x hands x tree) and are meant for tiny instances.
"""
from __future__ import annotations

import numpy as np

from pokerlab.plo.subgame.instance import SubgameInstance
from pokerlab.plo.subgame.tree import DECISION, FOLD


def _share(inst: SubgameInstance, p: int, i: int, j: int) -> tuple[bool, float]:
    """(compatible, player p's showdown share) for p's hand i against the opponent's hand j."""
    if p == 0:
        return inst.pair_outcome(i, j)
    ok, share0 = inst.pair_outcome(j, i)
    return ok, (1.0 - share0) if ok else 0.0


def _value(inst, nid, p, i, opp, profile, maximise):
    node = inst.tree.nodes[nid]
    if node.kind == FOLD:
        mass = sum(opp.values())
        if node.player == p:
            return -node.commit[p] * mass
        return (inst.pot + node.commit[node.player]) * mass
    if node.kind != DECISION:
        c = node.commit[0]
        return sum(r * ((inst.pot + 2 * c) * _share(inst, p, i, j)[1] - c) for j, r in opp.items())
    if node.player == p:
        values = [_value(inst, child, p, i, opp, profile, maximise) for child in node.children]
        if maximise:
            return max(values)
        sigma = profile[nid][i]
        return sum(sigma[a] * v for a, v in enumerate(values))
    sigma = profile[nid]
    return sum(_value(inst, child, p, i, {j: r * sigma[j][a] for j, r in opp.items()}, profile, maximise)
               for a, child in enumerate(node.children))


def _root(inst: SubgameInstance, profile, p: int, maximise: bool) -> float:
    o = 1 - p
    total = z = 0.0
    for i in range(inst.size(p)):
        opp = {j: float(inst.weights[o][j]) for j in range(inst.size(o)) if _share(inst, p, i, j)[0]}
        mass = sum(opp.values())
        if mass == 0.0:
            continue
        total += inst.weights[p][i] * _value(inst, inst.tree.root, p, i, opp, profile, maximise)
        z += inst.weights[p][i] * mass
    return total / z


def best_response_reference(inst: SubgameInstance, profile: dict, p: int) -> float:
    """Normalised value of player p's information-set best response to the profile."""
    return _root(inst, profile, p, maximise=True)


def profile_value_reference(inst: SubgameInstance, profile: dict, p: int) -> float:
    return _root(inst, profile, p, maximise=False)


def exploitability_reference(inst: SubgameInstance, profile: dict) -> float:
    return (best_response_reference(inst, profile, 0) + best_response_reference(inst, profile, 1)
            - inst.pot) / 2.0


def solve_sequence_form(inst: SubgameInstance) -> dict:
    """Exact equilibrium value (player 0, constant-sum utilities) and behaviour strategies."""
    from scipy.optimize import linprog
    from scipy.sparse import coo_matrix, hstack, vstack

    tree = inst.tree
    sizes = (inst.size(0), inst.size(1))
    seq = [dict(), dict()]         # (hand, node, action) -> column
    infosets = [[], []]            # (hand, node, parent column, [child columns])
    count = [1, 1]                 # column 0 is the empty sequence
    terminals = []

    def walk(nid: int, last: tuple) -> None:
        node = tree.nodes[nid]
        if node.kind != DECISION:
            terminals.append((node, last))
            return
        p = node.player
        for i in range(sizes[p]):
            parent = seq[p][(i, *last[p])] if last[p] else 0
            cols = []
            for a in range(len(node.children)):
                seq[p][(i, nid, a)] = count[p]
                cols.append(count[p])
                count[p] += 1
            infosets[p].append((i, nid, parent, cols))
        for a, child in enumerate(node.children):
            new_last = list(last)
            new_last[p] = (nid, a)
            walk(child, tuple(new_last))

    walk(tree.root, (None, None))

    def constraints(p: int):
        rows, cols, vals = [0], [0], [1.0]
        for r, (_, _, parent, children) in enumerate(infosets[p], start=1):
            rows += [r] * (len(children) + 1)
            cols += children + [parent]
            vals += [1.0] * len(children) + [-1.0]
        shape = (len(infosets[p]) + 1, count[p])
        rhs = np.zeros(shape[0])
        rhs[0] = 1.0
        return coo_matrix((vals, (rows, cols)), shape=shape).tocsr(), rhs

    E, e = constraints(0)
    F, f = constraints(1)
    z = 0.0
    rows, cols, vals = [], [], []
    for i in range(sizes[0]):
        for j in range(sizes[1]):
            ok, share = inst.pair_outcome(i, j)
            if not ok:
                continue
            prob = inst.weights[0][i] * inst.weights[1][j]
            z += prob
            for node, last in terminals:
                if node.kind == FOLD:
                    u0 = -node.commit[0] if node.player == 0 else inst.pot + node.commit[1]
                else:
                    c = node.commit[0]
                    u0 = (inst.pot + 2 * c) * share - c
                rows.append(seq[0][(i, *last[0])] if last[0] else 0)
                cols.append(seq[1][(j, *last[1])] if last[1] else 0)
                vals.append(prob * u0)
    A = coo_matrix((np.array(vals) / z, (rows, cols)), shape=(count[0], count[1])).tocsr()

    # Player 0: max f.q  s.t.  F^T q - A^T x <= 0,  E x = e,  x >= 0
    m_f = F.shape[0]
    res0 = linprog(np.r_[np.zeros(count[0]), -f],
                   A_ub=hstack([-A.T, F.T]).tocsr(), b_ub=np.zeros(count[1]),
                   A_eq=hstack([E, coo_matrix((E.shape[0], m_f))]).tocsr(), b_eq=e,
                   bounds=[(0, None)] * count[0] + [(None, None)] * m_f, method="highs")
    # Player 1: min e.p  s.t.  A y - E^T p <= 0,  F y = f,  y >= 0
    m_e = E.shape[0]
    res1 = linprog(np.r_[np.zeros(count[1]), e],
                   A_ub=hstack([A, -E.T]).tocsr(), b_ub=np.zeros(count[0]),
                   A_eq=hstack([F, coo_matrix((F.shape[0], m_e))]).tocsr(), b_eq=f,
                   bounds=[(0, None)] * count[1] + [(None, None)] * m_e, method="highs")
    if not (res0.success and res1.success):
        raise RuntimeError(f"LP failed: {res0.message} / {res1.message}")

    profile: dict[int, np.ndarray] = {}
    for p, plan in ((0, res0.x[:count[0]]), (1, res1.x[:count[1]])):
        for i, nid, parent, children in infosets[p]:
            node = tree.nodes[nid]
            if nid not in profile:
                profile[nid] = np.zeros((sizes[p], len(node.children)))
            mass = plan[parent]
            probs = plan[children] / mass if mass > 1e-12 else np.full(len(children), 1.0 / len(children))
            probs = np.clip(probs, 0.0, None)
            profile[nid][i] = probs / probs.sum()
    return {"value0": float(-res0.fun), "value0_dual": float(res1.fun), "profile": profile,
            "variables": [count[0], count[1]], "nonzeros": int(A.nnz)}
