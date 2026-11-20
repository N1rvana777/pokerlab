"""Small independent oracles; never used as production solver output.

River normal-form enumeration deliberately includes only one bet, no raises.
The LP mixes complete contingent plans, so it cannot peek at the other hand.
"""
from collections import Counter
from functools import lru_cache
from itertools import combinations, product
from math import isfinite

from pokerlab.core.card import card_from_str


def cards(text: str) -> tuple:
    """Parse explicit cards using the retained project card representation."""
    compact = text.replace(" ", "")
    if len(compact) % 2:
        raise ValueError("cards must have two characters each")
    result = tuple(card_from_str(compact[i:i+2]) for i in range(0, len(compact), 2))
    if len(set(result)) != len(result):
        raise ValueError("duplicate cards")
    return result


def rank_five(hand: tuple) -> tuple:
    """Full ordering including every kicker, independent of the native evaluator."""
    counts = Counter(c.rank for c in hand)
    groups = sorted(((n, r) for r, n in counts.items()), reverse=True)
    descending = sorted(counts, reverse=True)
    flush = len({c.suit for c in hand}) == 1
    straight = (max(counts) if len(counts) == 5 and max(counts)-min(counts) == 4
                else 5 if set(counts) == {14, 2, 3, 4, 5} else 0)
    if flush and straight:
        return (8, straight)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if [n for n, _ in groups] == [3, 2]:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *descending)
    if straight:
        return (4, straight)
    if groups[0][0] == 3:
        return (3, *(r for _, r in groups))
    if [n for n, _ in groups[:2]] == [2, 2]:
        return (2, *(r for _, r in groups))
    if groups[0][0] == 2:
        return (1, *(r for _, r in groups))
    return (0, *descending)


def rank(hand: tuple) -> tuple:
    if not 5 <= len(hand) <= 7 or len(set(hand)) != len(hand):
        raise ValueError("need 5..7 distinct cards")
    return max(rank_five(c) for c in combinations(hand, 5))


def river_matrix(board: str, ranges: list[list[tuple[str, float]]], pot: float, bet: float):
    """Return payoff matrix over pure information-set strategies, weighted legally."""
    import numpy as np
    b = cards(board)
    if len(b) != 5 or pot <= 0 or bet <= 0 or len(ranges) != 2:
        raise ValueError("reference requires a river board, two ranges and positive amounts")
    holes = [[cards(h) for h, _ in r] for r in ranges]
    if any(len(h) != 2 for r in holes for h in r):
        raise ValueError("explicit two-card combos required")
    if any(not isfinite(w) or w < 0 for r in ranges for _, w in r):
        raise ValueError("invalid range weights")
    if any(len(r)>4 for r in ranges):
        raise ValueError("reference oracle only supports tiny ranges")
    plans = [list(product([0, 1], repeat=2*len(r))) for r in ranges]
    matrix = np.zeros((len(plans[0]), len(plans[1])))
    mass = 0.0
    for i, h0 in enumerate(holes[0]):
        for j, h1 in enumerate(holes[1]):
            if len(set(b+h0+h1)) != 9:
                continue
            w = ranges[0][i][1]*ranges[1][j][1]
            mass += w
            r0, r1 = rank(b+h0), rank(b+h1)
            win = float(r0 > r1) + 0.5*float(r0 == r1)
            showdown = win*pot
            called = win*(pot+2*bet)-bet
            for x, p0 in enumerate(plans[0]):
                for y, p1 in enumerate(plans[1]):
                    # OOP bits: root bet, call facing bet. IP bits: bet after check, call.
                    if p0[2*i]:
                        value = called if p1[2*j+1] else pot
                    elif p1[2*j]:
                        value = called if p0[2*i+1] else 0.0
                    else:
                        value = showdown
                    matrix[x, y] += w*value
    if mass == 0:
        raise ValueError("no compatible joint hands")
    return matrix/mass


def equilibrium_value(matrix) -> float:
    """Independent normal-form minimax via SciPy HiGHS linear programming."""
    import numpy as np
    from scipy.optimize import linprog
    rows, cols = matrix.shape
    result = linprog(np.r_[np.zeros(rows), -1.0],
                     A_ub=np.c_[-matrix.T, np.ones(cols)], b_ub=np.zeros(cols),
                     A_eq=[np.r_[np.ones(rows), 0.0]], b_eq=[1.0],
                     bounds=[(0, None)]*rows+[(None, None)], method="highs")
    if not result.success:
        raise RuntimeError(result.message)
    return float(result.x[-1])


def quads_barrel_reference(start_street: int, river_bet: float, pot=20, stack=30, bet=10) -> dict:
    """Analytic complete-street oracle: AsAh vs KcKd on AcAd2h.

    Hero wins on all 45*44 ordered runouts. Villain calls bets 1/2,
    bets after a check with probability 1 on flop/turn and q on river.
    No future cards are known by decisions. They cannot change the payoff ordering.
    """
    if start_street not in (3, 4, 5) or not 0 <= river_bet <= 1:
        raise ValueError("invalid street/probability")

    @lru_cache(None)
    def values(street, p, s):
        if street > 5 or s == 0:
            return {"showdown": float(p)}
        amount = min(bet, s)
        next_check = max(values(street+1, p, s).values())
        next_called = max(values(street+1, p+2*amount, s-amount).values())-amount
        q = river_bet if street == 5 else 1.0
        return {"Check": (1-q)*next_check+q*max(0.0, next_called),
                f"Bet({amount})": 0.5*p+0.5*next_called}

    action_ev = values(start_street, pot, stack)
    return {"ev": max(action_ev.values()), "action_ev": action_ev}
