"""Fast integer-based poker hand evaluator.

INTERVIEW NOTE — 为什么需要这个文件:
    原来的evaluator.py用Card对象 + sorted() + Counter()，代码清晰但慢。
    每次evaluate_5card()调用都要:
      1. 创建list和set对象 (内存分配)
      2. sorted()排序 (O(n log n) 比较)
      3. Counter()哈希表操作
    这些在Python里每次耗时~微秒级别。当你要做28亿次调用时，就变成了几个小时。

    解决方案: 把Card对象替换成整数 0-51，用位运算(bitmask)代替排序和集合操作。
    同样的算法，但数据表示更紧凑，CPU缓存更友好。

Card Encoding (卡牌整数编码):
    card = rank * 4 + suit
    rank: 0=2, 1=3, ..., 8=T, 9=J, 10=Q, 11=K, 12=A
    suit: 0=c, 1=d, 2=h, 3=s

    所以: 2c=0, 2d=1, 2h=2, 2s=3, 3c=4, ..., Ac=48, Ad=49, Ah=50, As=51

    获取rank: card >> 2  (等价于 card // 4, 但位运算更快)
    获取suit: card & 3   (等价于 card % 4, 但位运算更快)

Hand Rankings (same as evaluator.py):
    0=High Card, 1=One Pair, 2=Two Pair, 3=Three of a Kind,
    4=Straight, 5=Flush, 6=Full House, 7=Four of a Kind,
    8=Straight Flush, 9=Royal Flush
"""

# INTERVIEW NOTE: 预计算所有C(7,5)=21种5张牌组合的索引
# 这样在evaluate_best5_fast()里就不需要每次都调用itertools.combinations()
# 直接用索引访问数组，零开销
_COMBO_INDICES_7_5: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4), (0, 1, 2, 3, 5), (0, 1, 2, 3, 6),
    (0, 1, 2, 4, 5), (0, 1, 2, 4, 6), (0, 1, 2, 5, 6),
    (0, 1, 3, 4, 5), (0, 1, 3, 4, 6), (0, 1, 3, 5, 6),
    (0, 1, 4, 5, 6), (0, 2, 3, 4, 5), (0, 2, 3, 4, 6),
    (0, 2, 3, 5, 6), (0, 2, 4, 5, 6), (0, 3, 4, 5, 6),
    (1, 2, 3, 4, 5), (1, 2, 3, 4, 6), (1, 2, 3, 5, 6),
    (1, 2, 4, 5, 6), (1, 3, 4, 5, 6), (2, 3, 4, 5, 6),
)

# INTERVIEW NOTE: 顺子的bitmask模式
# 一个顺子就是5个连续的bit被设为1
# 比如 6-7-8-9-T 在bitmask里是 0b0000111110000 (bit 4-8)
# 我们预计算所有10种顺子模式 (A-low到A-high)
_STRAIGHT_MASKS: tuple[int, ...] = tuple(
    0b11111 << i for i in range(9)  # 2-6, 3-7, ..., T-A
) + (
    0b1000000001111,  # A-2-3-4-5 (wheel): bit 0-3 + bit 12
)

# INTERVIEW NOTE: Royal flush的bitmask = T-J-Q-K-A = 最高5个bit
_ROYAL_MASK: int = 0b1111100000000


def evaluate_5card_fast(c0: int, c1: int, c2: int, c3: int, c4: int) -> int:
    """Evaluate a 5-card hand using integer encoding.

    INTERVIEW NOTE — 逐步解释:
    这个函数和evaluator.py里的evaluate_5card()做完全一样的事情，
    但用整数运算代替了对象操作。

    Parameters
    ----------
    c0-c4 : int
        Five card integers (0-51).

    Returns
    -------
    int
        Hand ranking 0-9 (same as HandRank enum values).
    """
    # Step 1: 提取5张牌的rank和suit
    # card >> 2 等价于 card // 4，取出rank (0-12)
    # card & 3 等价于 card % 4，取出suit (0-3)
    r0 = c0 >> 2
    r1 = c1 >> 2
    r2 = c2 >> 2
    r3 = c3 >> 2
    r4 = c4 >> 2

    s0 = c0 & 3
    s1 = c1 & 3
    s2 = c2 & 3
    s3 = c3 & 3
    s4 = c4 & 3

    # Step 2: 检测Flush
    # INTERVIEW NOTE: 如果5张牌花色相同，s0==s1==s2==s3==s4
    # 这比 len(set(suits)) == 1 快很多，因为不需要创建set对象
    is_flush = (s0 == s1 == s2 == s3 == s4)

    # Step 3: 构建rank bitmask，用于检测顺子
    # INTERVIEW NOTE: bitmask是一个13位的整数，每个bit代表一个rank是否出现
    # 比如手牌有 2, 5, 8, J, A → bitmask = 1001001001001 (bit 0,3,6,9,12)
    # 用 1 << rank 把对应bit设为1，然后用 | (OR) 合并
    rank_mask = (1 << r0) | (1 << r1) | (1 << r2) | (1 << r3) | (1 << r4)

    # Step 4: 检测顺子
    # INTERVIEW NOTE: 如果bitmask匹配任何一个预计算的顺子模式，就是顺子
    # 同时要确保有5个不同的rank (排除比如 [2,2,3,4,5] 这种情况)
    is_straight = False
    if bin(rank_mask).count('1') == 5:  # 5个不同的rank
        for mask in _STRAIGHT_MASKS:
            if rank_mask == mask:
                is_straight = True
                break

    # Step 5: Straight Flush / Royal Flush
    if is_straight and is_flush:
        if rank_mask == _ROYAL_MASK:
            return 9  # ROYAL_FLUSH
        return 8  # STRAIGHT_FLUSH

    # Step 6: 统计rank频率 (代替Counter)
    # INTERVIEW NOTE: 用一个13元素的数组代替Python的Counter字典
    # 数组访问是O(1)，比哈希表快得多
    freq = [0] * 13
    freq[r0] += 1
    freq[r1] += 1
    freq[r2] += 1
    freq[r3] += 1
    freq[r4] += 1

    # 找出最大和第二大的频率
    # INTERVIEW NOTE: 不需要排序，只需要找max和second_max
    max_freq = 0
    second_freq = 0
    for f in freq:
        if f > max_freq:
            second_freq = max_freq
            max_freq = f
        elif f > second_freq:
            second_freq = f

    # Step 7: 根据频率分类
    if max_freq == 4:
        return 7  # FOUR_OF_A_KIND
    if max_freq == 3 and second_freq == 2:
        return 6  # FULL_HOUSE
    if is_flush:
        return 5  # FLUSH
    if is_straight:
        return 4  # STRAIGHT
    if max_freq == 3:
        return 3  # THREE_OF_A_KIND
    if max_freq == 2 and second_freq == 2:
        return 2  # TWO_PAIR
    if max_freq == 2:
        return 1  # ONE_PAIR
    return 0  # HIGH_CARD


def evaluate_best5_fast(cards: list[int] | tuple[int, ...]) -> int:
    """Find best 5-card hand from 7 cards using integer encoding.

    INTERVIEW NOTE:
    对每个7张牌的组合，我们需要检查C(7,5)=21种5张牌的选择。
    用预计算的索引元组直接访问，避免itertools.combinations()的开销。
    如果提前发现Royal Flush，立即返回（不可能更好了）。

    Parameters
    ----------
    cards : list or tuple of int
        7 card integers (0-51).

    Returns
    -------
    int
        Best hand ranking 0-9.
    """
    best = 0
    for idx in _COMBO_INDICES_7_5:
        rank = evaluate_5card_fast(
            cards[idx[0]], cards[idx[1]], cards[idx[2]],
            cards[idx[3]], cards[idx[4]]
        )
        if rank > best:
            best = rank
            if best == 9:  # ROYAL_FLUSH — can't beat this
                return 9
    return best


def count_7card_by_rank_fast() -> dict[int, int]:
    """Enumerate all C(52,7) = 133,784,560 hands using fast integer evaluator.

    INTERVIEW NOTE:
    这和combinatorics.py里的count_7card_by_rank()做完全一样的计算，
    但用整数编码代替Card对象。预期快20-50倍。

    Returns
    -------
    dict[int, int]
        Mapping from hand rank (0-9) to count.
    """
    from itertools import combinations

    counts = [0] * 10  # index 0-9 for each HandRank
    all_cards = list(range(52))  # 整数0-51代替Card对象

    for combo in combinations(all_cards, 7):
        rank = evaluate_best5_fast(combo)
        counts[rank] += 1

    return {i: counts[i] for i in range(10)}


def count_5card_by_rank_fast() -> dict[int, int]:
    """Enumerate all C(52,5) = 2,598,960 hands using fast integer evaluator.

    Returns
    -------
    dict[int, int]
        Mapping from hand rank (0-9) to count.
    """
    from itertools import combinations

    counts = [0] * 10
    all_cards = list(range(52))

    for combo in combinations(all_cards, 5):
        rank = evaluate_5card_fast(combo[0], combo[1], combo[2], combo[3], combo[4])
        counts[rank] += 1

    return {i: counts[i] for i in range(10)}
