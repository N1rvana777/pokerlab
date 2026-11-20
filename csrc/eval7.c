/*
 * eval7.c — Fast 7-card poker hand evaluator in C
 *
 * INTERVIEW NOTE — 为什么用C:
 *   Python的fast_eval.py和这个文件做的是完全一样的计算。
 *   区别在于: Python每次函数调用有~1微秒的解释器开销，
 *   C编译成机器码后每次调用只需要~10纳秒。
 *   对于28亿次调用: Python需要~45分钟，C只需要~30秒。
 *   这就是Game Mathematician用C#/C++写simulation engine的原因。
 *
 * Card Encoding (和Python版本完全一致):
 *   card = rank * 4 + suit
 *   rank: 0=2, 1=3, ..., 8=T, 9=J, 10=Q, 11=K, 12=A
 *   suit: 0-3
 *   card >> 2 = rank,  card & 3 = suit
 *
 * Hand Rankings:
 *   0=High Card, 1=One Pair, 2=Two Pair, 3=Three of a Kind,
 *   4=Straight, 5=Flush, 6=Full House, 7=Four of a Kind,
 *   8=Straight Flush, 9=Royal Flush
 *
 * Build:
 *   gcc -O2 -shared -o eval7.dll eval7.c    (Windows)
 *   gcc -O2 -shared -fPIC -o eval7.so eval7.c  (Linux/Mac)
 */

#include <string.h>  /* for memset */

/* ========== 导出宏 ========== */
/* INTERVIEW NOTE: DLL导出需要 __declspec(dllexport)，让Python的ctypes能找到函数 */
#ifdef _WIN32
  #define EXPORT __declspec(dllexport)
#else
  #define EXPORT
#endif

/* ========== 预计算: C(7,5)=21种5张牌组合的索引 ========== */
/* INTERVIEW NOTE: 和Python版的_COMBO_INDICES_7_5完全一样 */
static const int COMBOS_7_5[21][5] = {
    {0,1,2,3,4}, {0,1,2,3,5}, {0,1,2,3,6},
    {0,1,2,4,5}, {0,1,2,4,6}, {0,1,2,5,6},
    {0,1,3,4,5}, {0,1,3,4,6}, {0,1,3,5,6},
    {0,1,4,5,6}, {0,2,3,4,5}, {0,2,3,4,6},
    {0,2,3,5,6}, {0,2,4,5,6}, {0,3,4,5,6},
    {1,2,3,4,5}, {1,2,3,4,6}, {1,2,3,5,6},
    {1,2,4,5,6}, {1,3,4,5,6}, {2,3,4,5,6},
};

/* ========== 5-card evaluator ========== */
/*
 * INTERVIEW NOTE — 这个函数的逻辑和Python的evaluate_5card_fast()完全一样:
 * 1. 提取rank和suit (位运算)
 * 2. 检测flush (花色是否相同)
 * 3. 用bitmask检测straight (5个连续的bit)
 * 4. 统计频率 (数组代替Counter)
 * 5. 根据频率分类
 */
static int evaluate_5card(int c0, int c1, int c2, int c3, int c4) {
    /* Step 1: 提取rank和suit */
    int r0 = c0 >> 2, r1 = c1 >> 2, r2 = c2 >> 2, r3 = c3 >> 2, r4 = c4 >> 2;
    int s0 = c0 & 3,  s1 = c1 & 3,  s2 = c2 & 3,  s3 = c3 & 3,  s4 = c4 & 3;

    /* Step 2: Flush检测 — 5张牌花色是否全部相同 */
    int is_flush = (s0 == s1) && (s1 == s2) && (s2 == s3) && (s3 == s4);

    /* Step 3: 构建rank bitmask */
    /* 每个rank对应一个bit位，用OR合并 */
    int rank_mask = (1 << r0) | (1 << r1) | (1 << r2) | (1 << r3) | (1 << r4);

    /* Step 4: Straight检测 */
    /* __builtin_popcount 计算一个整数中有多少个bit是1 (内置函数，非常快) */
    /* 如果有5个不同的rank，检查是否形成连续序列 */
    int num_unique = __builtin_popcount(rank_mask);
    int is_straight = 0;

    if (num_unique == 5) {
        /* 检查普通顺子: 5个连续bit = 0b11111 << n */
        /* 方法: 如果 mask / (mask & -mask) 等于 31 (0b11111)，就是顺子 */
        /* mask & -mask 取出最低位的1 (即最小的rank) */
        /* 除以它等于把mask右移到最低位 */
        int lowest_bit = rank_mask & (-rank_mask);
        if (rank_mask / lowest_bit == 31) {
            is_straight = 1;
        }
        /* Wheel: A-2-3-4-5 = bits 0,1,2,3,12 = 0x100F */
        if (rank_mask == 0x100F) {
            is_straight = 1;
        }
    }

    /* Step 5: Straight Flush / Royal Flush */
    if (is_straight && is_flush) {
        /* Royal = T-J-Q-K-A = bits 8,9,10,11,12 = 0x1F00 */
        if (rank_mask == 0x1F00) return 9;  /* ROYAL_FLUSH */
        return 8;  /* STRAIGHT_FLUSH */
    }

    /* Step 6: 频率统计 */
    int freq[13];
    memset(freq, 0, sizeof(freq));  /* 全部初始化为0 */
    freq[r0]++; freq[r1]++; freq[r2]++; freq[r3]++; freq[r4]++;

    /* 找最大和第二大频率 */
    int max_f = 0, second_f = 0;
    for (int i = 0; i < 13; i++) {
        if (freq[i] > max_f) {
            second_f = max_f;
            max_f = freq[i];
        } else if (freq[i] > second_f) {
            second_f = freq[i];
        }
    }

    /* Step 7: 分类 */
    if (max_f == 4) return 7;                       /* FOUR_OF_A_KIND */
    if (max_f == 3 && second_f == 2) return 6;      /* FULL_HOUSE */
    if (is_flush) return 5;                          /* FLUSH */
    if (is_straight) return 4;                       /* STRAIGHT */
    if (max_f == 3) return 3;                        /* THREE_OF_A_KIND */
    if (max_f == 2 && second_f == 2) return 2;       /* TWO_PAIR */
    if (max_f == 2) return 1;                        /* ONE_PAIR */
    return 0;                                        /* HIGH_CARD */
}

/* ========== 7-card evaluator ========== */
/*
 * INTERVIEW NOTE:
 * 检查所有C(7,5)=21种5张牌组合，返回最强的hand rank。
 * 如果发现Royal Flush就立即返回（不可能更好了）。
 */
static int evaluate_7card(const int cards[7]) {
    int best = 0;
    for (int i = 0; i < 21; i++) {
        int rank = evaluate_5card(
            cards[COMBOS_7_5[i][0]], cards[COMBOS_7_5[i][1]],
            cards[COMBOS_7_5[i][2]], cards[COMBOS_7_5[i][3]],
            cards[COMBOS_7_5[i][4]]
        );
        if (rank > best) {
            best = rank;
            if (best == 9) return 9;  /* Royal Flush, 不可能更好 */
        }
    }
    return best;
}

/* ========== 主函数: 枚举所有C(52,7)手牌 ========== */
/*
 * INTERVIEW NOTE:
 * 7层嵌套循环枚举所有C(52,7) = 133,784,560种7张牌组合。
 * 这是最笨但最可靠的方法。每个组合调用evaluate_7card()。
 * counts[0..9]记录每种hand rank出现的次数。
 *
 * 为什么用7层循环而不是递归?
 * 因为循环在CPU层面更高效: 没有函数调用开销，循环变量在寄存器里。
 * 对于2.81亿次调用，每个纳秒的节省都有意义。
 */
EXPORT void count_all_7card(long long counts[10]) {
    int cards[7];
    memset(counts, 0, 10 * sizeof(long long));

    /* 7层嵌套循环: c0 < c1 < c2 < c3 < c4 < c5 < c6 */
    /* 这保证了每种组合恰好被枚举一次 */
    for (cards[0] = 0; cards[0] < 46; cards[0]++)
    for (cards[1] = cards[0]+1; cards[1] < 47; cards[1]++)
    for (cards[2] = cards[1]+1; cards[2] < 48; cards[2]++)
    for (cards[3] = cards[2]+1; cards[3] < 49; cards[3]++)
    for (cards[4] = cards[3]+1; cards[4] < 50; cards[4]++)
    for (cards[5] = cards[4]+1; cards[5] < 51; cards[5]++)
    for (cards[6] = cards[5]+1; cards[6] < 52; cards[6]++) {
        int rank = evaluate_7card(cards);
        counts[rank]++;
    }
}

/* ========== 辅助: 评估单手牌 (供Python调用) ========== */
EXPORT int eval_7card_hand(int c0, int c1, int c2, int c3, int c4, int c5, int c6) {
    int cards[7] = {c0, c1, c2, c3, c4, c5, c6};
    return evaluate_7card(cards);
}
