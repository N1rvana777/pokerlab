"""Independent re-implementation of the PLO betting and settlement rules (engine oracle).

Written separately from ``pokerlab.plo.engine`` during the 2026-10-23 code review, with its own
state model (per-player "needs to act" / "may raise" flags and cumulative raise tracking).  The
fuzzer drives both implementations with the same random actions and reports any divergence in
turn order, legal action ranges, hand termination, payouts or rake (rake split in proportion to
pot sizes, as in docs/DECISIONS.md D4).

    python tests/plo_rules_reference.py 60000     # larger run than the pytest smoke test
"""
import random
import sys
from collections import Counter

from pokerlab.plo.engine import (Action, ActionType, HandState, RakeRule, TableRules, deal_hand)
from pokerlab.plo.evaluator import plo_rank_reference


class Ref:
    def __init__(self, rules, stacks, button, holes, runout):
        self.r = rules
        self.n = n = len(stacks)
        self.button = button
        self.stack = list(stacks)
        self.start = list(stacks)
        self.total = [0] * n
        self.bet = [0] * n
        self.folded = [False] * n
        self.holes = holes
        self.runout = runout
        self.street = 0
        self.antes = 0
        # posting
        if rules.ante:
            for s in range(n):
                a = min(rules.ante, self.stack[s])
                self.stack[s] -= a
                self.total[s] += a
                self.antes += a
        sb = button if n == 2 else (button + 1) % n
        bb = (sb + 1) % n
        if rules.small_blind:
            self._put(sb, rules.small_blind)
        self._put(bb, rules.big_blind)
        self.cur = rules.big_blind
        self.lfr = rules.big_blind
        self.needs = [self.active(s) for s in range(n)]
        self.raise_ok = [True] * n
        self.cum = [0] * n
        self.done = False
        self.to_act = None
        self._next(start=(bb + 1) % n)

    def active(self, s):
        return not self.folded[s] and self.stack[s] > 0

    def _put(self, s, amt):
        a = min(amt, self.stack[s])
        self.stack[s] -= a
        self.bet[s] += a
        self.total[s] += a
        return a

    def owes(self, s):
        return max(0, self.cur - self.bet[s])

    def _next(self, start):
        if sum(not f for f in self.folded) == 1:
            self.to_act = None
            self.done = True
            return
        act = [s for s in range(self.n) if self.active(s)]
        if len(act) <= 1 and all(self.owes(s) == 0 for s in act):
            return self._new_street()
        for k in range(self.n):
            s = (start + k) % self.n
            if self.active(s) and (self.needs[s] or self.owes(s) > 0):
                self.to_act = s
                return
        self._new_street()

    def _new_street(self):
        if self.street == 3:
            self.to_act = None
            self.done = True
            return
        self.street += 1
        self.bet = [0] * self.n
        self.cur = 0
        self.lfr = self.r.big_blind
        self.needs = [self.active(s) for s in range(self.n)]
        self.raise_ok = [True] * self.n
        self.cum = [0] * self.n
        self._next(start=(self.button + 1) % self.n)

    def legal(self):
        s = self.to_act
        owe = self.owes(s)
        call = min(owe, self.stack[s])
        allin_to = self.bet[s] + self.stack[s]
        others = any(self.active(o) for o in range(self.n) if o != s)
        rt, lo, hi = None, 0, 0
        if others and self.raise_ok[s] and allin_to > self.cur:
            rt = ActionType.BET if self.cur == 0 else ActionType.RAISE
            pot = sum(self.total) - (0 if self.r.antes_count_for_pot_limit else self.antes)
            # pot-limit: call first, then raise by the pot after the call
            pot_raise_to = self.cur + (pot + owe)
            minimum = self.cur + (self.r.big_blind if self.cur == 0 else self.lfr)
            hi = min(max(pot_raise_to, minimum), allin_to)
            lo = min(minimum, allin_to)
        return (owe > 0, owe == 0, call if owe > 0 else 0, rt, lo, hi)

    def apply(self, a):
        s = self.to_act
        self.needs[s] = False
        self.raise_ok[s] = False
        self.cum[s] = 0
        if a.type is ActionType.FOLD:
            self.folded[s] = True
        elif a.type is ActionType.CALL:
            self._put(s, min(self.owes(s), self.stack[s]))
        elif a.type in (ActionType.BET, ActionType.RAISE):
            self._put(s, a.to - self.bet[s])
            inc = a.to - self.cur
            full = inc >= self.lfr
            if full:
                self.lfr = inc
            self.cur = a.to
            for o in range(self.n):
                if o == s or not self.active(o):
                    continue
                self.cum[o] += inc
                if full or self.cum[o] >= self.lfr:
                    self.raise_ok[o] = True
                if self.bet[o] < self.cur:
                    self.needs[o] = True
        self._next(start=(s + 1) % self.n)

    def settle(self, rake_rule):
        n = self.n
        c = list(self.total)
        live = [s for s in range(n) if not self.folded[s]]
        payout = [0] * n
        # chips nobody live can win (folded players above the top live level) go back
        max_live = max(c[s] for s in live)
        for s in range(n):
            if self.folded[s] and c[s] > max_live:
                payout[s] += c[s] - max_live
                c[s] = max_live
        # uncalled: top contributor above everyone else
        top = max(range(n), key=lambda s: c[s])
        second = max(c[s] for s in range(n) if s != top)
        if c[top] > second:
            payout[top] += c[top] - second
            c[top] = second
        # pots by live contribution levels
        levels = sorted({c[s] for s in live})
        pots = []
        prev = 0
        for lv in levels:
            amt = sum(max(0, min(x, lv) - prev) for x in c)
            elig = [s for s in live if c[s] >= lv]
            pots.append([amt, elig])
            prev = lv
        # chips above the highest live level (from folded players) belong to the top pot
        rest = sum(max(0, x - prev) for x in c)
        if rest:
            pots[-1][0] += rest
        total_pot = sum(p[0] for p in pots)
        rake = 0
        if rake_rule is not None and rake_rule.percent:
            if not (rake_rule.no_flop_no_drop and self.street == 0 and len(live) == 1):
                from fractions import Fraction
                rake = int(Fraction(total_pot) * Fraction(str(rake_rule.percent)) / 100)
                if rake_rule.cap is not None:
                    rake = min(rake, rake_rule.cap)
        if rake:
            from fractions import Fraction
            size = sum(p[0] for p in pots)
            exact = [Fraction(rake * p[0], size) for p in pots]
            base = [int(e) for e in exact]
            order = sorted(range(len(pots)), key=lambda k: (-(exact[k] - base[k]), k))
            for k in order[:rake - sum(base)]:
                base[k] += 1
            for p, t in zip(pots, base):
                p[0] -= t
        if len(live) > 1:
            board = self.runout
            rk = {s: plo_rank_reference(self.holes[s], board) for s in live}
        for amt, elig in pots:
            if not elig:
                raise AssertionError("empty pot")
            if len(live) == 1:
                win = elig
            else:
                b = max(rk[s] for s in elig)
                win = [s for s in elig if rk[s] == b]
            base, odd = divmod(amt, len(win))
            for w in win:
                payout[w] += base
            order = sorted(win, key=lambda s: (s - self.button - 1) % n)
            for w in order[:odd]:
                payout[w] += 1
        final = [self.stack[s] + payout[s] for s in range(n)]
        return final, rake


def random_action(legal, rng, stack_left, committed):
    opts = []
    if legal.can_fold:
        opts.append(("fold", 1.0))
    opts.append(("passive", 2.0))
    if legal.can_raise:
        opts.append(("aggr", 1.5))
    kind = rng.choices([o for o, _ in opts], [w for _, w in opts])[0]
    if kind == "fold":
        return Action.fold()
    if kind == "passive":
        return Action.check() if legal.can_check else Action.call()
    choices = [legal.min_to, legal.max_to, rng.randint(legal.min_to, legal.max_to)]
    return Action(legal.raise_type, rng.choice(choices))


def run(trials, seed):
    rng = random.Random(seed)
    mismatches = Counter()
    examples = {}
    for trial in range(trials):
        n = rng.randint(2, 8)
        bb = 100
        sb = rng.choice([0, 25, 50, 50, 100])
        ante = rng.choice([0, 0, 0, 5, 10, 50])
        rake = rng.choice([None, None, RakeRule(5.0, None), RakeRule(4.1, 300), RakeRule(3.3, None, False)])
        counted = rng.random() < 0.7
        rules = TableRules(sb, bb, ante, rake, counted)
        stacks = [rng.choice([1, 5, 10, 30, 49, 50, 60, 99, 100, 101, 150, 199, 200, 250, 640, 1000, 5000, 20000])
                  for _ in range(n)]
        button = rng.randrange(n)
        st = deal_hand(rules, stacks, button, random.Random(trial * 7919 + seed), hand_id=trial)
        ref = Ref(rules, stacks, button, st.hole_cards, st._runout)
        step = 0
        while True:
            if (st.to_act is None) != ref.done and not (st.to_act is None and ref.to_act is None):
                mismatches["termination"] += 1
                examples.setdefault("termination", (trial, rules, stacks, button, [h.type for h in st.history]))
                break
            if st.to_act is None:
                break
            if st.to_act != ref.to_act:
                mismatches["to_act"] += 1
                examples.setdefault("to_act", (trial, rules, stacks, button, st.history, st.to_act, ref.to_act))
                break
            L = st.legal_actions()
            mine = (L.can_fold, L.can_check, L.call_amount, L.raise_type, L.min_to, L.max_to)
            theirs = ref.legal()
            if mine != theirs:
                mismatches["legal"] += 1
                examples.setdefault("legal", (trial, rules, stacks, button, st.history, mine, theirs))
                break
            a = random_action(L, rng, None, None)
            ref.apply(a)
            try:
                st.apply(a)
            except AssertionError as e:
                mismatches["engine_assertion:" + str(e)] += 1
                examples.setdefault("engine_assertion", (trial, rules, stacks, button))
                st = None
                break
            step += 1
        else:
            pass
        if st is not None and st.result is not None and ref.done:
            final, rk = ref.settle(rules.rake)
            if tuple(final) != st.result.final_stacks or rk != st.result.rake:
                key = "settle_rake" if rk != st.result.rake else "settle"
                mismatches[key] += 1
                examples.setdefault(key, (trial, rules, stacks, button, st.result, final, rk))
    return mismatches, examples


if __name__ == "__main__":
    trials = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    m, ex = run(trials, 1)
    print("mismatches:", dict(m))
    for k, v in ex.items():
        print("==", k)
        for x in v:
            print("   ", x)
