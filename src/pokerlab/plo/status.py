"""What the PLO module implements now, and what is only planned.

Printed by ``python -m pokerlab.plo status``.  Keep this table honest: a module
is "implemented" only if code and tests exist in this repository.
"""
from __future__ import annotations

MODULES: tuple[dict, ...] = (
    {"module": "rules: PLO4 hand ranking (exactly 2 hole + 3 board)", "status": "implemented",
     "where": "pokerlab.plo.evaluator",
     "evidence": "all 2,598,960 five-card hands: 7,462 classes and exact category counts; "
                 "vectorised vs scalar oracle; pair-table ranking vs brute force 2+3; PLO rule cases"},
    {"module": "pot-limit arithmetic (P, h, c) shared by engine and solver trees", "status": "implemented",
     "where": "pokerlab.plo.betting",
     "evidence": "independent expected values (250 / 6 / 700 / BB facing a limp) on the formula, "
                 "the engine and the tree; abstraction filtering and dedup tests"},
    {"module": "engine: 2-8 players, pot limit, min-raise, short all-in reopening, side pots, "
               "split pots, uncalled returns, optional rake", "status": "implemented",
     "where": "pokerlab.plo.engine",
     "evidence": "rule unit tests; randomised conservation tests; 60,000 fuzzed hands match an "
                 "independent re-implementation (turn order, legal ranges, payouts, rake)"},
    {"module": "session: fixed-root reset / stack carry; rebuy, leave, stop on bust",
     "status": "implemented", "where": "pokerlab.plo.session", "evidence": "session tests"},
    {"module": "agent observation boundary (agents see only Observation / PublicHandSummary)",
     "status": "implemented", "where": "pokerlab.plo.engine.observe, pokerlab.plo.public",
     "evidence": "hidden-information resampling tests on observations and on river-agent decisions"},
    {"module": "baseline agents (calling station, random, rule, baseline-v1 policy)",
     "status": "implemented", "where": "pokerlab.plo.agents, pokerlab.plo.baseline",
     "evidence": "functional only; not strength claims"},
    {"module": "HU river subgame solver: CFR, CFR+, LCFR, DCFR, ES-MCCFR; checkpoints; "
               "four exact pot-fraction sizes + boundary actions by default",
     "status": "implemented", "where": "pokerlab.plo.subgame",
     "evidence": "Kuhn value; sequence-form LP and loop-based best response on small PLO rivers, incl. "
                 "non-uniform asymmetric ranges with blockers; bitwise resume test"},
    {"module": "HU turn + river joint subgame solver: one CFR over the turn tree and all 48 river "
               "cards (enumerated, chance 1/40 per valid card); dense or per-card inclusion-exclusion "
               "showdown; worker threads over river cards; checkpoints; average-strategy export",
     "status": "implemented (explicit ranges up to thousands of hands, controlled stacks)",
     "where": "pokerlab.plo.subgame.turn, pokerlab.plo.subgame.turn_reference",
     "evidence": "joint sequence-form LP (primal and dual) on 3x3 (unit test: shared cards, unequal "
                 "weights) and 6x6 hands; loop-based best response with explicit river enumeration and "
                 "brute-force chance normalisation on 3x3; bitwise resume; spliced-river comparison "
                 "measured; inclusion-exclusion vs dense masses 1e-15 and values 5e-13 on weighted "
                 "asymmetric ranges; bitwise-identical CFR state for any worker count"},
    {"module": "HU joint turn + river decision integration: one joint solve per hand at the first turn "
               "decision, the river read from the same solution, logged fallbacks",
     "status": "implemented (first version)", "where": "pokerlab.plo.turn_agent",
     "evidence": "tests: logged probabilities equal the stored joint solution on turn and river, one solve "
                 "per hand, turn re-solve after an off-tree turn action, independent river fallback flagged, "
                 "observation-only; controlled turn-start demo; preflop/flop remain baseline-v1"},
    {"module": "strategy query interface (SubgamePolicy, CLI query)", "status": "implemented",
     "where": "pokerlab.plo.subgame.policy", "evidence": "tests"},
    {"module": "HU decision integration: baseline policy pre-river, solved river strategy in play, "
               "Bayes-derived river ranges with logged provenance and latency",
     "status": "implemented (first version)", "where": "pokerlab.plo.river_agent",
     "evidence": "legality, posterior and observation-only tests; HU duplicate runs"},
    {"module": "local re-solving", "status": "partial",
     "where": "pokerlab.plo.river_agent, pokerlab.plo.subgame.policy.RiverResolver",
     "evidence": "unsafe solves from sampled Bayes ranges: river (river_solver) and joint turn + river "
                 "(turn_river_solver), re-solving after off-tree opponent actions; no safe/nested gadget"},
    {"module": "full-range river terminal evaluation (inclusion-exclusion card removal)",
     "status": "implemented", "where": "pokerlab.plo.subgame.showdown",
     "evidence": "complete comparison with dense sums on random subsets and weighted small ranges; "
                 "sampled rows against all 178,365 opponent hands; uniform count check"},
    {"module": "evaluation harness (duplicate / session matches, river subgame reports, "
               "decision logs, depth labels)", "status": "implemented",
     "where": "pokerlab.plo.evaluate", "evidence": "CLI runs"},
    {"module": "four-street blueprint v0: preflop/flop/turn/river ES-MCCFR, 20bb, limited sizes, coarse "
               "imperfect-recall buckets; policy query and blueprint_v0 agent; joint agent early_policy",
     "status": "implemented (minimal; no full-game exploitability)",
     "where": "pokerlab.plo.blueprint, pokerlab.plo.blueprint_agent",
     "evidence": "identity-bucket ES-MCCFR converges on LP-checked river and turn+river subgames; tree identity "
                 "with the exact turn solver; bitwise resume; vectorised buckets equal per-deal buckets; "
                 "out-of-tree hands fall back to baseline-v1 with a logged reason"},
    {"module": "hand abstraction v1 for subgames (information abstraction with exact payoffs): river "
               "equity x blocker features; turn equity x river-card spread x blocker; river refines turn",
     "status": "implemented (measured in the original reference games)", "where": "pokerlab.plo.abstraction",
     "evidence": "identity buckets reproduce the untied solvers bitwise; perfect recall checked; any-hand "
                 "query equals stored buckets; exploitability measured after expansion to every hand"},
    {"module": "exact flop solving, full-range turn, depth-limited search", "status": "not implemented",
     "where": "-", "evidence": "turn + river joint solving covers explicit ranges of thousands of hands; "
                               "full ranges need a more compact representation and/or abstraction or "
                               "sampling (docs/ARCHITECTURE.md)"},
    {"module": "multiway (3+) strategy training or subgame solving", "status": "not implemented (later)",
     "where": "-", "evidence": "engine supports 2-8 players; strategy work is heads-up only"},
    {"module": "opponent model / few-observation adaptation", "status": "not implemented (later)",
     "where": "-", "evidence": "only PublicHandSummary hooks exist for future use"},
)


def format_table() -> str:
    lines = []
    for m in MODULES:
        lines.append(f"[{m['status']}] {m['module']}")
        lines.append(f"    where: {m['where']}")
        lines.append(f"    evidence: {m['evidence']}")
    return "\n".join(lines)
