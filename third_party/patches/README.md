# PokerLab engine extension

Base: b-inary/postflop-solver commit 9d1509fe5077d019825f833eed04b16d342dfda1.
License remains AGPL-3.0-or-later; upstream notices and LICENSE are unchanged.

`expanded-suits.patch` adds `PostFlopGame::with_config_unmerged`. It clears suit
isomorphism mappings before allocating/building the public-card tree. Original
constructors retain their original behavior. Card ranges, weights, terminal
evaluation and chance denominators are unchanged. This permits asymmetric locks
without perturbing ranges or tying distinct public-card branches together.

From a clean pinned checkout, apply this recorded patch before building:
`git -C third_party/postflop-solver apply ../patches/expanded-suits.patch`.
`python scripts/verify_engine.py` verifies the entire tracked diff against it.

2026-10-06: the same cumulative patch also exposes a preparation stage and
`memory_plan` (exact native storage counts before expanded-node allocation), plus
canonical node identity and suit-aware in-place strategy replacement. The latter
is used only after equilibrium finishes: Hero BR modifies Hero nodes only, and
the opponent policy digest is checked afterward. No CFR runs on an in-place frozen
model. Explicit manual locks retain the upstream locking map. Compressed storage
uses upstream 16-bit encoding; terminal evaluation and chance probabilities are
unchanged. `expanded-suits-v1.patch` preserves the previous recorded extension.
Original code remains recoverable from the pinned Git commit; do not reset
unrelated work. No upstream commit or push was made.

2026-10-13: `checkpoint_interpreter` / `restore_interpreter` preserve the cursor,
actual-card suit mappings, conditional reach, bet totals and value/normalization
caches without copying tree storage or reverting descendant policy edits. The
model compiler captures after editing the current node, then restores after each
child instead of replaying all ancestors. A checkpoint must not cross an ancestor
strategy change, tree rebuild, allocation or finalize. Three new tests cover
compressed/uncompressed and canonical/expanded trees, noncanonical Turn/River
cards, zero reach, descendant edits, full replay equality, foreign-game rejection
and nonzero solved-value caches. The full native-CPU upstream library suite passed
40 tests with 4 existing ignored tests (2026-10-13); this is correctness evidence,
not a wide-tree speed benchmark. `expanded-suits-v2-memory.patch` preserves the
previous cumulative memory extension before this change.

2026-10-13 (performance follow-up): `compute_player_mes_ev` exposes one player's
existing best-response traversal and weighted summation without computing the
other player's unused result. The original two-player API remains unchanged as
the test reference. Turn/River, both storage modes, locks/zero-reach branches,
and pre/post-finalize outputs match bit-for-bit. The prior cumulative patch is
preserved in `expanded-suits-v3-interpreter.patch`. Solver rules and DCFR are unchanged.

2026-10-15: the stable allocator DCFR path now borrows owned temporary vectors
from bounded thread-local pools (`solver_scratch.rs`). A checkout releases the
pool borrow before recursion/Rayon work; exact-capacity matching avoids inflating
active buffers. Idle f32/f64 capacities total at most 1 MiB per thread, plus small
metadata, within the existing 256 MiB transient allowance. Every uninitialized
output is sliced to its exact logical length. Arithmetic order, compression,
discount schedule, chance handling and the optional nightly allocator path are
unchanged. `solver_reference.rs` is a frozen pre-change implementation compiled
only by the bitwise regression tests, not by the production binary. The previous
cumulative patch is preserved in `expanded-suits-v4-single-player-mes.patch`.
All new source files are included in the cumulative patch; verification also
rejects unrecorded source files. See `docs/PROGRESS.md` for measured performance
and the distinction between historical-tree diagnostics and current-tree acceptance.

2026-10-16: `sparse_storage.rs` packs legal private hands for each canonical board,
plus one invalid-hand ghost per row to preserve unlocked CFR quantization. Shared
card-table indices avoid adding per-node metadata. Logical callers use `dense_*`
views; raw GameNode slices describe physical storage. Owned view buffers use a
separate bounded 1 MiB/thread pool and fully overwrite reused initialized data.
The preallocation plan, allocation and line-removal counts use the packed width.
PokerLab enables this for compressed games without hard locks. Hard-lock APIs,
bunching and upstream bincode reject sparse mode. Native policy and CFR files keep
their existing dense logical formats; they are not disk-size optimizations.
The preceding patch is preserved in `expanded-suits-v5-dcfr-scratch.patch`.

2026-10-16 follow-up: sparse compressed regret-matching initializes its required
logical f32 strategy directly from packed i16 words and the ghost. It avoids an
intermediate dense i16 view; ordered normalization and quantization are unchanged.
The nightly custom allocator keeps its established path. The preceding source
and cumulative patch are in outputs/performance-20261016-sparse/hotpath-before.

2026-11-01: `PostFlopGame::set_incentive` and `Game::apply_incentive` add a virtual
per-action bonus for one player, as a fraction of the current pot, to that player's
action values during DCFR. Expected values and best responses never see it. With no
incentive the code path returns at once and results stay bit-exact, which the scratch
regression tests confirm. The preceding patch is `expanded-suits-v6-sparse.patch`.

2026-11-02: `Incentive.streets` limits the bonus to flop, turn or river. A street left out
returns before any work, and a game without an incentive never reaches that check. The
preceding patch is `expanded-suits-v7-incentives.patch`.
