"""Exclusive hand, draw and equity classes for the node filters.

Classes are a display layer: nothing is merged while solving. Each combo gets one
made-hand class, one draw class and two equity buckets, judged by what its hole
cards add to the board, so a pair on the board alone counts for nobody.

The definitions follow GTO Wizard's filters. On 9h8h2c the shares of its BB range
matched for every class (2026-11-01, outputs/gtow-compare). Its panel states the
simple buckets; BDSD was read off the hands its filter selects.
"""

RANKS = '23456789TJQKA'
HAND_CLASSES = (('straight_flush', 'Straight flush'), ('quads', 'Quads'), ('full_house', 'Full house'),
                ('flush', 'Flush'), ('straight', 'Straight'), ('set', 'Set'), ('trips', 'Trips'),
                ('two_pair', 'Two pair'), ('overpair', 'Overpair'), ('top_pair', 'Top pair'),
                ('second_pair', 'Second pair'), ('third_pair', 'Third pair'), ('fourth_pair', 'Fourth pair'),
                ('fifth_pair', 'Fifth pair'),
                ('ace_high', 'Ace high'), ('king_high', 'King high'), ('no_made_hand', 'No made hand'))
DRAW_CLASSES = (('combo_draw', 'Combo draw'), ('flush_draw_nuts', 'Flush draw nuts'), ('flush_draw', 'Flush draw'),
                ('oesd', 'OESD'), ('gutshot', 'Gutshot'), ('bdfd_2', 'BDFD 2 cards'), ('bdfd_1', 'BDFD 1 card'),
                ('bdsd', 'BDSD'), ('no_draw', 'No draw'))
# Lower equity bound of each bucket, best first.
EQUITY_SIMPLE = (('best', 'Best hands', .75), ('good', 'Good hands', .5), ('weak', 'Weak hands', .33), ('trash', 'Trash hands', 0))
EQUITY_ADVANCED = (('eq90', 'Equity 90-100', .9), ('eq80', 'Equity 80-90', .8), ('eq70', 'Equity 70-80', .7),
                   ('eq60', 'Equity 60-70', .6), ('eq50', 'Equity 50-60', .5), ('eq25', 'Equity 25-50', .25),
                   ('eq0', 'Equity 0-25', 0))
ACE_LOW_WINDOWS = tuple(frozenset(({12} | set(range(4))) if low < 0 else range(low, low + 5)) for low in range(-1, 9))


def parse(card):
    return RANKS.index(card[0]), card[1]


def split_combo(combo):
    return parse(combo[:2]), parse(combo[2:])


def straight_top(ranks):
    """Index of the highest five-card window inside ``ranks``, or -1."""
    return max((top for top, window in enumerate(ACE_LOW_WINDOWS) if window <= ranks), default=-1)


def plays_flush(hole, board):
    """Hole cards that reach the five highest cards of a made flush."""
    for suit in 'cdhs':
        mine = [rank for rank, s in hole if s == suit]
        table = [rank for rank, s in board if s == suit]
        if mine and len(mine) + len(table) >= 5:
            best = sorted(mine + table, reverse=True)[:5]
            if any(rank in best for rank in mine):
                return True
    return False


def pair_class(rank, board_ranks, pocket):
    """Class of a pair of ``rank``; ``board_ranks`` are the distinct board ranks, highest first."""
    above = sum(card > rank for card in board_ranks)
    if pocket and above == 0:
        return 'overpair'
    return ('top_pair', 'second_pair', 'third_pair', 'fourth_pair', 'fifth_pair')[min(above, 4)]


def hand_class(hole, board):
    (rank_a, _), (rank_b, _) = hole
    table = [rank for rank, _ in board]
    held = {rank_a, rank_b}
    counts = {rank: table.count(rank) + (rank == rank_a) + (rank == rank_b) for rank in set(table) | held}
    for suit in 'cdhs':
        mine = frozenset(rank for rank, s in hole if s == suit)
        suited = frozenset(rank for rank, s in board if s == suit)
        if mine and straight_top(suited | mine) > straight_top(suited):
            return 'straight_flush'
    if any(counts[rank] == 4 for rank in held):
        return 'quads'
    trips = sorted((rank for rank in counts if counts[rank] >= 3), reverse=True)
    if trips:
        pairs = sorted((rank for rank in counts if rank != trips[0] and counts[rank] >= 2), reverse=True)
        if pairs and {trips[0], pairs[0]} & held:
            return 'full_house'
    flush = plays_flush(hole, board)
    straight = straight_top(frozenset(counts)) > straight_top(frozenset(table))
    if flush:
        return 'flush'
    if straight:
        return 'straight'
    distinct = sorted(set(table), reverse=True)
    if rank_a == rank_b:
        if counts[rank_a] == 3:
            return 'set'
        return pair_class(rank_a, distinct, True)
    if any(counts[rank] == 3 for rank in held):
        return 'trips'
    paired = sorted((rank for rank in held if rank in table), reverse=True)
    if len(paired) == 2:
        return 'two_pair'
    if paired:
        return pair_class(paired[0], distinct, False)
    if 12 in held:
        return 'ace_high'
    return 'king_high' if 11 in held else 'no_made_hand'


def flush_draw_suit(hole, board):
    """(suit, nut draw) for four cards to a flush with a hole card, else None."""
    for suit in 'cdhs':
        mine = [rank for rank, s in hole if s == suit]
        table = [rank for rank, s in board if s == suit]
        if mine and len(mine) + len(table) == 4:
            top_free = max(rank for rank in range(13) if rank not in table)
            return suit, top_free in mine
    return None


def straight_outs(hole, board):
    """Ranks that complete a straight only the hole cards can reach."""
    table = {rank for rank, _ in board}
    mine = {rank for rank, _ in hole} - table
    ranks = table | mine
    if straight_top(frozenset(ranks)) > straight_top(frozenset(table)):
        return set()
    return {next(iter(window - ranks)) for window in ACE_LOW_WINDOWS if len(window - ranks) == 1 and window & mine}


def backdoor_flush(hole, board):
    """2 when both hole cards share a suit with one board card, 1 for one hole card and two board cards."""
    best = 0
    for suit in 'cdhs':
        mine = sum(s == suit for _, s in hole)
        if mine and mine + sum(s == suit for _, s in board) == 3:
            best = max(best, mine)
    return best


def backdoor_straight(hole, board):
    """At least three five-card windows that use both hole cards and need two more cards."""
    table = {rank for rank, _ in board}
    mine = {rank for rank, _ in hole} - table
    return len(mine) == 2 and sum(mine <= window and len(window - (table | mine)) == 2 for window in ACE_LOW_WINDOWS) >= 3


def draw_class(hole, board):
    if len(board) == 5:
        return 'no_draw'
    flush_made = plays_flush(hole, board)
    flush = None if flush_made else flush_draw_suit(hole, board)
    outs = straight_outs(hole, board)
    if flush and outs:
        return 'combo_draw'
    if flush:
        return 'flush_draw_nuts' if flush[1] else 'flush_draw'
    if len(outs) >= 2:
        return 'oesd'
    if outs:
        return 'gutshot'
    if len(board) == 3:
        if not flush_made:
            backdoor = backdoor_flush(hole, board)
            if backdoor:
                return f'bdfd_{backdoor}'
        if backdoor_straight(hole, board):
            return 'bdsd'
    return 'no_draw'


def bucket(equity, levels):
    """The last level also takes a hand with no equity, which float rounding can leave a hair below zero."""
    return next((index for index, level in enumerate(levels) if equity >= level[2]), len(levels) - 1)


def classify(combos, board, equities):
    """Class indices per combo into the tables above."""
    table = [parse(card) for card in board]
    made = {key: i for i, (key, _) in enumerate(HAND_CLASSES)}
    draws = {key: i for i, (key, _) in enumerate(DRAW_CLASSES)}
    out = {'hand': [], 'draw': [], 'equity_simple': [], 'equity_advanced': []}
    for combo, equity in zip(combos, equities):
        hole = split_combo(combo)
        if any(card in table for card in hole):
            for values in out.values():
                values.append(None)
            continue
        out['hand'].append(made[hand_class(hole, table)])
        out['draw'].append(draws[draw_class(hole, table)])
        out['equity_simple'].append(bucket(equity, EQUITY_SIMPLE))
        out['equity_advanced'].append(bucket(equity, EQUITY_ADVANCED))
    return out


def annotate(node):
    """Add class labels and each player's class indices to a decision node."""
    if node.get('terminal') or node.get('chance') or 'players' not in node:
        return node
    node['class_labels'] = {'hand': [label for _, label in HAND_CLASSES], 'draw': [label for _, label in DRAW_CLASSES],
                            'equity_simple': [row[1] for row in EQUITY_SIMPLE],
                            'equity_advanced': [row[1] for row in EQUITY_ADVANCED]}
    for player in node['players']:
        player['classes'] = classify(player['combos'], node['board'], player['equity'])
    return node
