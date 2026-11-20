# PokerLab

A research workbench for heads-up poker. It solves no-limit hold'em postflop spots to equilibrium, builds a model of the opponent, and computes the exact best response to that model. The question behind it: how far should play deviate from equilibrium when the evidence about an opponent is limited and noisy?

> **Public snapshot / 公开版说明**
>
> This is a public copy of a private working repository; commit history is not included.
> Not included: private hand records and opponent notes, solver and research outputs
> (`outputs/`, about 180 GB), the vendored upstream engine checkout
> (`third_party/postflop-solver/`; check out the revision pinned in `Cargo.toml` and apply
> `third_party/patches/`), and scripts that downloaded third-party video data. A few passages
> in the docs that described real hands were shortened.
>
> PokerLab is licensed under the GNU Affero General Public License v3.0 or later
> (see `LICENSE`), the same license as the upstream engine, b-inary/postflop-solver.
>
> 这是私人工作仓库的公开副本，不含提交历史。没有包含：私人手牌记录与对手信息、求解与研究输出（`outputs/`）、
> 上游引擎源码（按 `Cargo.toml` 固定的版本另行获取并应用 `third_party/patches/`），以及下载第三方视频数据的脚本。
> 文档中涉及真实手牌的段落已删改。本仓库使用 AGPL-3.0-or-later 许可证（见 `LICENSE`），与上游引擎相同。

## Overview

- **Equilibrium solving.** Discounted CFR (DCFR) on full flop, turn and river trees, with every turn and river card and no card abstraction. The core engine is the open-source [b-inary/postflop-solver](https://github.com/b-inary/postflop-solver) (Rust), extended with a patch and an adapter.
- **Opponent models and exploitation.** Stackable behavioural traits, node locks and player profiles define the opponent's strategy at every information set. That strategy is frozen, and an exact best response is computed against it.
- **Opponent evidence.** A replay-checked hand-history format, a PokerStars/GG parser, and Beta-binomial posteriors with 90% intervals for 18 opponent statistics.
- **Review assistant.** An LLM assistant (Claude or OpenAI models) that may quote only numbers produced by the solver and statistics tools. Its private knowledge base, built from about 200 public strategy videos, is not included.
- **Heads-up pot-limit Omaha (paused).** A Libratus-style research prototype in `src/pokerlab/plo/`: an exact rules engine and hand evaluator, hand abstraction, a 20 bb Monte Carlo CFR blueprint, and agents that re-solve turn-and-river subgames at decision time.

## Checks and results

- Solver results agree with an independent linear program, closed-form test games and GTO Wizard, a commercial solver.
- A full flop tree with three bet sizes per street (11.1 million nodes, 3.46 billion action entries) was solved to 0.092% of the pot in about 2.6 hours on a 32 GB desktop PC, with a 13.9 GiB memory peak.
- In the Omaha prototype, solving turn and river jointly cut exploitability from 1.108% to 0.026% of the pot compared with solving each river separately. On a small game, a linear program matched the joint solve.
- These figures measure solution quality. They are not claims about playing strength.

## Status

The hold'em workbench and the review assistant are in active development. The Omaha line has been paused since October 2026. To start the workbench, run `python -m pokerlab.solver.server` and open http://127.0.0.1:8765; setup details are in the full README below.

AI coding agents (Claude Code, OpenAI Codex) wrote much of the code under my direction. `CLAUDE.md` and `AGENTS.md` are their instructions, and `docs/DECISIONS.md` records which decisions were mine. The full README follows, first in English and then in the original Chinese; the documents in `docs/` are in Chinese.

---

## Full README in English

*This section is an English translation of the Chinese README further down. The interface is in Chinese, so UI labels are quoted in Chinese with an English gloss. Paths under `outputs/` point to local files that are not in this public copy.*

This is a runnable phase-1 research workbench: heads-up flop, turn and river spots, stackable opponent traits, a frozen full opponent strategy, the hero's information-set best response, and views of individual combos and later nodes. The full requirements are in the [original prompt](Codex_Poker_Solver_Prompt.md) and the measured numbers and limits in the [progress log](docs/PROGRESS.md) (both in Chinese). The earlier math code and phase-0 documents are kept.

### Running locally

Run one command in **PowerShell** from the project root:

```powershell
python -m pokerlab.solver.server
```

Open **<http://127.0.0.1:8765>** in a browser. Solves call the prebuilt Rust engine in Ubuntu under WSL automatically; the web service does not need to run inside WSL. The service listens on localhost only, and Ctrl+C exits and cancels its running jobs.

Two desktop shortcuts, `Pokerstudio.lnk` and `Pokerlab Solver.lnk`, are installed on the local machine; their targets, arguments, working directories and icons were read back and checked. The installer is `powershell -ExecutionPolicy Bypass -File pokerstudio/install-desktop.ps1`. A cold start, a second launch that reuses the running backend, and stopping a backend the launcher started have all been tested; the address-bar-free view in a real standalone Windows window has not been accepted yet. Closing the window keeps the service and its jobs running. Port conflicts, logs and explicit shutdown are covered in [desktop launch](pokerstudio/docs/DESKTOP.md); the command-line entry point still works.

2026-10-08: the local backend on port 8765 was updated. The interface works in bb (big blinds); at that point the pot and remaining stacks took whole numbers of bb (decimal input came later; see "Inputs, units and limits"). 16-bit compression, automatic safe suit isomorphism and 8 threads by default are kept. The front end turns on automatic memory by default, including for old examples that do not set `memory_auto`, so they are no longer held to their 4096 MiB manual cap. It shows live available memory for Windows and WSL and the safe budget, and measures again once a solve holds the serial lock. The manual cap applies only when automatic mode is turned off. On the backend, old saved requests without `memory_auto` and CLI runs are still treated as manual budgets, and explicit caps are never raised silently. Export configuration sits at the top of the sidebar.

The historical study "SPR20 multi-size memory optimisation check, baseline short of 0.1%" is kept. Its original measurement used compression and automatic isomorphism, 16 threads, an 1,800-second limit and an automatic budget; 500 iterations did not reach 0.1%. A cold start took about 11 min 33 s, and the full frozen-opponent pipeline reusing that baseline about 3 min 50 s. Ordinary jobs no longer have an automatic timeout, so this is kept only as the original measurement. New strategy snapshots store the 16-bit data directly, so reopening does not quantise again; the old format is still readable, and the bb interface did not recompute or rewrite historical reports.

2026-10-13: the full large tree from this run is saved as "**完整Flop 三街三尺寸3x · 0.1%达标 · 2026-10-13**" (full flop tree, three streets, three sizes, 3x raises, 0.1% reached; study ID `f79af0c4219441a284f16d34a7da9d39`). Open the desktop Pokerlab or the browser address above, refresh the page, pick that name under "已保存研究" (Saved studies) and click "打开" (Open). It was reopened in a real headless Edge browser in 45.281 s, keeping the original 0.1% target, 9h8h2c, 203/449 combos and all three full strategies, and showing 169 strategy cells and 4 legal actions with no JS errors or stale markers. One real root-node query on the saved model completed; the native process exited with code 0 and was reaped, and no CFR or best response was rerun. The test only simulated the external assistant's state and session, with an isolated assistant configuration. Evidence: `outputs/performance-20261013-v2/completed-workbench-acceptance.json` and the screenshot `outputs/performance-20261013-v2/completed-workbench.png`. The current whole-bb engine rounds the root bets to 3, 5 and 8 bb, which is 37.5%, 62.5% and 100% of the pot; the 33/66/100% inputs in the configuration are kept, and they do not mean fractional-bb bets are supported.

Walkthrough:

2026-10-13: the user chose to favour everyday exploration. The equilibrium baseline for a new spot now defaults to **0.5% of the starting pot**, and this can be changed. "新建日常局面" (New everyday spot) in the sidebar builds that default configuration from the selected example; "载入示例" (Load example), imports and opening a saved study keep their explicit precision. Persisted assistant state is not rewritten by refreshing the page. This target applies only to the equilibrium baseline; the response gap of the best response to a frozen opponent is still measured separately. The full large tree in this run kept its original 0.1% target and reached it. Edits or imports made during start-up take priority over a late-arriving default configuration, and nothing is written back before the first backend version has been read.

1. Keep the default "Flop 实际范围 + All-in Raise" (flop, real ranges, all-in raise) example: 9h8h2c, a 100 bb pot and 200 bb effective stacks.
   The **OOP range / IP range** tables on the left are fully expanded by default, with IP below OOP; "定位 IP 范围" (Go to IP range) jumps straight to IP. Click a cell to select it and click again to clear it; the mouse wheel over a cell changes it by 5 percentage points, or by 1 with Shift, within 0–100%. By default each of the 169 hand classes spreads its weight evenly over its suit combinations; "查看具体花色" (Show suits) allows advanced asymmetric ranges. Text and grid stay in sync and support import and export; combos that conflict with the board are kept but do not count toward the effective range.
   The "翻前总范围 %" (Preflop range %) slider selects the top X% of the 1,326 combos by weight, counting 6 per pair, 4 per suited hand and 12 per offsuit hand; the boundary hand class gets a mixed weight that is equal across all its suits. 70% corresponds to 928.2 weighted raw combos. The ordering uses the preflop heuristic template described on the page, not current-street GTO or measured equity, and is not re-sorted by board. Changing the total rebuilds a suit-uniform template and can be undone; the percentage includes board-conflicting combos.
   Bet sizes for each street can be multi-selected by clicking (blue means selected); the input box below accepts custom sizes, at most three.
2. Click "求均衡基线" (Solve equilibrium baseline). Check the target precision, the precision reached and the stop reason.
3. Pick a combined trait preset, or set light, medium or heavy strength and the streets for Station, Overbluff and giving up after barrelling. Generate the opponent preview, then freeze it and compute the best response. Advanced parameters 1/2/3 correspond to those strengths; they are not percentages or calibrated population statistics. To compare only river give-ups, tick only River for the third trait and leave the other inputs unchanged.
4. The result grid is coloured by the actual action probabilities, with a legend and range-weighted overall frequencies above it. Click AA to see its suit combos, action probabilities, equity and per-action EV. Hover over a cell for its frequency; hatching means zero reach. Use the action buttons and board cards to move to later nodes, and switch between the baseline, the opponent model and the best response. At an opponent node you can see the actual frequency change from baseline to frozen model; both columns use the same conditional range weights of the current model.
5. Save the study and reopen it from the saved list. Changing inputs marks old results as stale. A save contains the final strategy for the whole tree, not CFR regrets or resumable state.

Node locking: go to a decision node (turn and river included) → click a row in the combo table, or choose the current grid hand group, the combos selected by the current Filters, or all legal combos → enter a full action distribution, click "100% <action>", or use "按总频率锁定" (lock by total frequency) to fill in a target frequency → keep the node lock → either freeze the opponent in step 3 and optimise only the hero, or in step 4 lock only these nodes and re-solve for both players. Step 4 shows frequencies and EV before and after locking; locks on hero nodes take effect only in step 4. The lock list can locate and delete locks, and restoring the range template clears them in bulk; undo and redo cover the last 100 input edits. Changing model traits does not delete locks; after the spot or the sizes change, old locks are explicitly rejected, and you must restore the spot or remove them.

The "命名范围库／玩家特质库" (named range library / player trait library) saves local profiles. The player library keeps only traits that carry across spots, and node locks are saved with the study. Configurations can be exported and imported as JSON to copy a model. Node analysis shows the equity distribution, and the combo table sorts and filters by EV, equity and change in value. "模型敏感性" (Model sensitivity) runs three frozen models, light, central and heavy, one after another, and reports for each the gain against that same model and any flips in the hero's root action; the three results do not share one opponent.

The flow above, including cancelling a job, was run end to end in a headless local Edge browser driven by Playwright; this is not a manual browser acceptance. Screenshot: `outputs/workbench-flop.png`.

Rebuild: `powershell -ExecutionPolicy Bypass -File scripts/build.ps1`. To install the Python package in a new environment: `python -m pip install -e '.[dev,solver]'`; browser tests also need `.[browser-test]`. The toolchain is Rust 1.75 on Ubuntu under WSL. The engine is pinned to b-inary/postflop-solver commit `9d1509fe5077d019825f833eed04b16d342dfda1` (AGPL-3.0-or-later), plus a documented [full suit-branch patch](third_party/patches/README.md). The build script checks the whole patch, and the original source can be restored from the pinned commit. When this was written the project root had no Git repository, and nothing is committed or pushed automatically.

The original CLI still works: `python -m pokerlab.solver examples/river.json --output outputs/my-river.json`. Existing outputs are never overwritten. The CLI saves the configuration and the report by default; the workbench also saves the full strategy.

### Pokerstudio: local video editing and agent

See [Pokerstudio](pokerstudio/README.md). From the repository root, run `python -X utf8 -m pokerstudio.server` and open <http://127.0.0.1:8770>. It supports hand, subtitle and animated overlays, real MP4 export, an adapter to the existing solver, and an agent on a subscription or an API; its own documents state what has actually been accepted and the limits. A separate analysis page is at `/analysis`, and the workbench runs as before.

### Assistant inside the solver workbench

The assistant is built directly into the original solver workbench on port 8765. It has its own configuration, sessions, authentication and solver tools, and at run time it does not depend on the 8770 service or a Pokerstudio instance; it reuses the two-provider protocol implementation. Subscription access uses the official Sign in with ChatGPT, or an explicitly chosen existing CLI login. The API needs its own key and explicit permission to pay, and hitting a subscription limit never falls back to the API.

The assistant only works with solver configurations, real jobs, results, node queries and cancellation. Configuration changes are version-checked, so late replies and tool events cannot roll back a spot that has already been synced; on a concurrent conflict the form edits are kept and must be confirmed with "同步当前局面" (Sync current spot). Finished numbers come from real reports, and results are marked stale when inputs change. Data is stored in `outputs/agent/` by default, and the app's own authentication in `%LOCALAPPDATA%\Pokerlab\agent` (set `POKERLAB_AUTH_HOME` to change it); API keys and payment permission are not persisted.

On 2026-10-08 a real subscription acceptance passed through this entry point. `existing_cli` / `gpt-6.1-sol` changed the pot of the public small river example from 25 to 20 bb by actually calling the tools to read the configuration, change it, start the job, query it and read the report, and the job completed. Root EVs were 13.3332891464 / 6.6667108536 bb, and measured exploitability was 0.00932455063 bb (0.0466227531% of the pot), meeting the 0.05% target. It reused a cached baseline, so the 530 recorded iterations were not new in this run. The native process exited with code 0 and was reaped, and the API was neither configured nor called. Evidence: `outputs/solver-agent-acceptance-20261008/acceptance.json`. The report and the assistant's answer were read in Firefox, and the units, login state and both players' 169 cells on the main 8765 page were checked; the local `existing_cli` setting is persisted. A first-time Sign in with ChatGPT authorisation by the user and the paid API have not had a real acceptance yet.

### Off-table review assistant (main task since 2026-10-29, phase 1)

Start it the same way: run `python -m pokerlab.solver.server` in an ordinary PowerShell window and open <http://127.0.0.1:8765>.

- **Claude subscription** (the assistant's default):
  - Before first use, install the dependency: `python -m pip install "claude-agent-sdk>=0.2.174"`.
  - Run `claude` in a terminal and sign in to your claude.ai subscription with `/login`.
  - The app never reads or stores credentials. Each turn first checks where the credentials come from, which must be a subscription login. It stops when the quota runs out or extra charges would start, and never switches to pay-per-use billing.
  - If the service process's environment contains variables such as `ANTHROPIC_API_KEY` or `ANTHROPIC_BASE_URL`, it refuses to send requests. Do not start the service from inside a Claude Code session.
- **"手牌与对手" (Hands and opponents) panel**:
  - Paste hands in PokerStars or GG format; code parses them and checks them by replay, and hands that pass are added to the statistics.
  - Describe live hands to the assistant in plain text; it turns them into the common format and submits them, and you check them in the panel and click "确认计入统计" (Confirm and count).
  - Player profiles list, for each of 18 statistics, the sample size, raw rate, posterior mean, 90% interval and tendency score (0–10, the posterior probability of being above the population level × 10), plus tags, showdown records and notes. Aliases can be merged and the hero's name set.
- **Data**: in `outputs/coach/`, not in Git; set `POKERLAB_COACH_HOME` to move it. Hand revisions only add new files, and confirmations and notes go to an append-only log.
- **HHP video material**:
  - For private use, stored in `outputs/knowledge/hhp/`, not in Git; set `POKERLAB_KNOWLEDGE_HOME` to move it.
  - The assistant searches the captions of 200 videos with `search_hhp` and reads the text with `read_hhp`, together with hand records transcribed from the video frames and checked by replay (currently 408 hands from 24 videos).
  - With `find_hhp_hands` the assistant looks up these hands by hand type, position, stack depth, pot type, board and action line, and it can also find the video hands closest to a hand you recorded.
  - Video hands include teaching scenarios and real hands analysed by the presenter (marked at the start of their notes); none of them count toward opponent statistics.
- **Current limits**:
  - The population priors are uncalibrated placeholders.
  - Calibrating the statistics into opponent traits and node locks is a later phase.
  - The PokerStars/GG parser has only been checked on synthetic hands, not on real exports.
  - For off-table review only.

Tests and real acceptance:

```powershell
python -m pytest tests/test_coach_hands.py tests/test_coach_store.py tests/test_claude_provider.py tests/test_solver_agent.py tests/test_instructions_consistency.py -q
python scripts/coach_claude_acceptance.py
```

The real acceptance uses your Claude subscription quota for two short requests and writes the result to `outputs/coach-acceptance/<time>/acceptance.json`.

### Inputs, units and limits

Out-of-memory diagnosis (build the latest engine first, as above): in PowerShell, run `python scripts/diagnose_tree.py "path/to/config.json" --storage --output outputs/storage-diagnostic.json`. The output file must not exist yet. This mode keeps the game configuration, compares four storage schemes (isomorphism and compression on or off), and counts the real array structures without allocating the full tree; the peak headroom is still an estimate and is not presented as a measurement. Without `--storage` it shows the old rough estimate and a clearly labelled reduced-tree comparison, for diagnosis only, without changing the original configuration. WSL diagnostic subprocesses are capped at 2 GiB and 60 seconds each.

Ordinary solves, the CLI and node reads no longer have an automatic timeout, and the 600 seconds in old configurations no longer stops a job. A job runs until it reaches the target precision or an explicit iteration cap, or until it is cancelled; the memory budget and process clean-up protections still apply. Explicit tests and diagnostics can set their own time limits, which is not the workbench default.

2026-10-16: sparse storage of legal combos is wired in for compressed jobs without hard locks, keeping the original 16-bit quantisation and the full logical hand order. For the current tree (203/449 combos, SPR 12.5, three bet sizes on each street plus 3x raises), the exact pre-check fell from 14.253 to 13.231 GiB, about 1.022 GiB less array memory; this is an allocation plan, not a measured peak for the new version. Sparse expansion costs some speed (see the small same-spot comparison in the [progress log](docs/PROGRESS.md)), and no speed-up is claimed for this change. Hard locks still use the original dense path; old strategies and CFR states remain readable, and file sizes on disk are not optimised. The desktop Pokerlab launcher is unchanged.

The user confirmed that this round's full acceptance uses **0.5% of the pot** (0.04 bb for an 8 bb starting pot). The new copy is `outputs/performance-20261016-sparse/config.json`, and the original 0.1% file and study are kept. Ranges, SPR, sizes per street, 16 threads and unlimited wall-clock time are unchanged. After the user later freed resources, the full tree was actually attempted, but its 13.231 GiB requirement was still above the 11.073 GiB safe budget at the time, so it was refused before allocation and cleaned up; there is still no full time, RSS or measured precision for the new version. Temporary copies in the sparse path were also reduced; 57 engine, 22 adapter and 72 real native integration tests pass, the small-case speed changed by about 1%, and no speed-up is claimed for wide trees. When resources allow, run the following in PowerShell from the project root (the output directory must not exist yet):

```powershell
python -X utf8 scripts/benchmark_config.py outputs/performance-20261016-sparse/config.json --cold --output outputs/performance-20261016-sparse/full-cold-02
```

2026-10-15: the engine now reuses DCFR scratch buffers, and the desktop and PowerShell launchers are unchanged. Bit-for-bit regression against the old implementation and 72 real native integration tests pass. On the historical SPR20 tree, 30 fixed iterations went from 151.95 to 19.28 seconds, and the baseline including precision measurement from 166.00 to 33.39 seconds, with only 4.8 MiB more diagnostic peak memory. That historical tree is not the current target tree (203/449 combos, three sizes per street), and 30 iterations did not reach the target precision. Acceptance of the new engine on the current target tree has not been done for lack of available memory, so the 7.9x iteration speed-up on the historical tree is not extrapolated into a guarantee for the full pipeline. The full configuration, test commands and evidence are in the latest [progress log](docs/PROGRESS.md).

The same day, after the user closed a running game, a retry of the original tree was again stopped before allocation (14.253 GiB required against an 11.149 GiB safe budget), so there is no new full solve. Resource probing now uses Windows available memory after WSL has started, with the same reserve. On a generic error, cancellation keeps the serial lock until the supervisor has finished cleaning up, and waiting for cancellation is not a solve timeout. 57 budget and clean-up tests and 4 real native regressions pass; see the progress log.

2026-10-13: the controlled pre-check for the full three-street, three-size configuration fell from 16.264 to 14.253 GiB, mainly by explicitly limiting allocator and thread overhead and calibrating the headroom, and by turning the model's visited set into a bitmap; this does not mean measured memory dropped by 2 GiB. Snapshots are also read and written in chunks, and best-response subtrees run in parallel, keeping the original strategy precision and summation order. Job `4c8e056088c848b7bc7d573d7df67aa8` ran to completion with 203/449 combos, SPR 12.5, three bet sizes on each street and ordinary 3x raises, with no timeout and no lowering of the original 0.1% target. The cold-start full pipeline took **2 h 34 min 54 s**, native RSS peaked at **13.8494 GiB**, and 1,060 iterations reached a measured **0.0921778381% of the pot**. It stopped because it reached the target, and the native process exited normally and was reaped. Memory acceptance passed; the five-minute speed target was not met. In the same run the baseline first went below 0.5% after 41 min 57 s; that is not the time of a separate full run at 0.5%. Commands, per-stage timings and numerical checks are in the latest [progress log](docs/PROGRESS.md).

A baseline that has not converged and stops normally at its iteration cap also saves a `PLCFR001` cumulative strategy and regret state. After the maximum iterations are raised, the same tree continues from the saved iterations, and the interface separates earlier iterations from new ones. Old `PLPOL002/003` final strategies cannot be resumed. State in progress is not yet saved on cancellation or a crash, and an old converged baseline may need to be recomputed for a stricter target. CFR state takes extra disk space, so save time should not be read as iteration speed.

The graphical card picker next to the board shows all 52 cards arranged by suit and sets the starting flop, turn or river board; after solving, chance nodes show the same card grid, with only legal branches clickable. The strategy grid shows actual frequencies: fold blue, check or call green, bet or raise red, and aggression above pot size purple; exactly 100% of the pot is still red. Within one node and one colour family, larger sizes are darker and equal sizes share a colour; sizes are ordered by their real value, not by the order of the actions. The legend, grid, action buttons and per-combo frequency bars share the palette: shade shows size and bar width shows probability. A raise's ratio is the extra raise amount divided by the pot after calling, and all-ins are judged by their actual ratio. A best response may be a pure strategy, and mixed frequencies are never faked for the sake of colour.

- Entering 3, 4 or 5 board cards picks the starting street automatically. Ranges are listed OOP then IP and accept `AA,AKs`, specific combos with weights, and text import. The hero can be either player, and OOP always acts first at the root.
- In the original solver workbench, pot is the current pot and stack is both players' effective remaining stack. The new UI takes amounts in bb and accepts decimals (to 0.01 bb, `chip_scale`=100); EV and precision are also in bb. Configurations saved by the new UI and the standalone assistant may record the metadata `amount_unit="bb"`, where one native unit equals 1 bb. This display field is stripped before native execution, and the computation and the compatibility field `target_unit="chips"` keep the original protocol. Old reports without this metadata show "原筹码单位" (original chip units) and are not relabelled as bb or converted. Loading an old study keeps its original numbers; check the unit basis before deciding the current input unit. Pokerstudio hands in chips or USD are still validated by their own adapter rules. There is no support for future rake, side pots with unequal stacks, or three players.
- Bet and raise sizes are set for each street and shared by both players by default; "按位置配置尺寸／Donk" (sizes by position / donk) gives IP its own sizes and OOP turn and river donk bets. Bets accept `33%`, `10c` (10 bb in bb mode, 10 chips in the original chip mode) and `a`; raises accept `2x` and larger multiples, `60%` (raise amount ÷ pot after calling, as in GTO Wizard) and `a`. Each type allows at most 3 sizes per street and position, and SPR is capped at 20 (40 when a per-street raise limit is set); anything beyond is rejected rather than silently shrinking the tree. Raises are reported as raise-to; arbitrary absolute raise-to inputs are not supported yet.
- Preflop action lines: when files exist under `outputs/gtow-preflop/`, the top of the page lets you pick a depth (100, 150, 200 or 400 bb, default 150 bb, because $800 = 160 bb is closest to 150 bb; the model is 8-max with a straddle, cEV, 7 bb opens) and click actions seat by seat. The hand grid and cards show every action and frequency for the current seat (raise, call, check, all-in, fold). Once the line reaches a two-player pot, both ranges, the pot and the effective stack are filled in; pick the board and solve, and adjust ranges and parameters on the left first if needed. All-in lines, pots with three or more players and lines that end preflop show only a note, and grey buttons are lines that were not recorded. The range box also accepts text copied from the GTO Wizard Ranges page. These files are not in Git.
- Node page: the hand grid switches between Strategy, EV, Equity, EQR, range height and EV comparison, and can merge sizes. The right side has Hands, Summary, Filters, an equity chart, Ranges, Breakdown and Blockers, and the top shows overall action frequencies. A chance node can produce a report on that street's cards, and the workspace has a multi-board report below. Frequencies count combos, while EV and equity averages use blocker-adjusted weights, as in GTO Wizard (DECISIONS D34).
- Bet-tree templates: Quick (1 size per street), Standard (2), Full (3) and Full low-memory (3 sizes, no river raises), all with at most 2 raises per street. Measurements and memory estimates are in `docs/PROJECT_STATE.md` A2e–A2g. WSL uses only half the memory by default; this machine sets `memory=28GB` in `%USERPROFILE%\.wslconfig`. When memory is short you can tick "允许占用闲置后台程序的内存" (allow using memory held by idle background programs), though the computer may become sluggish.
- The chosen tree keeps every legal board card and later decision, with no future-value truncation. On 2026-10-06 the original configuration (240/290 combos, SPR 20, multiple sizes and ordinary raises) ran end to end in about 11 min 33 s on 16 threads, with a peak RSS of 7.15 GiB. After 500 iterations the actual exploitability was 0.4542% of the pot, short of the 0.1% target; this does not mean every wide, multi-size tree performs well enough. Per-stage results are in the progress log.
- Root EV = the original pot plus the opponent's new money won back, minus your own new money. Earlier contributions are sunk, and without rake the two root EVs sum to the pot. Equity is the share won at showdown, counting ties, and is not EV. Values that are undefined at zero posterior probability are left blank.
- Trait strength 0–6 is a logit bias, not percentage points or the share of weak hands in a betting range. Traits stack by rule and are then normalised within action categories and sizes; Neutral keeps the baseline. The templates are research assumptions with coarse hand-strength classes, not calibrated on real game data.
- Opponent nodes on the flop, turn and river all support locking specific combos and full distributions in bulk. With `auto_suits=true` and no manual locks, the engine uses suit isomorphism it can prove; with manual locks, `expand_suits=true` keeps every board branch so that suits are not mixed. Adding a lock may require rebuilding a larger baseline. 16-bit storage does not merge bet sizes but has quantisation error, and the native re-evaluation tolerance was not loosened. Queries on snapshots with hard locks use f32 to keep the saved probability precision, so query memory can exceed that of the compressed solve.
- Player profiles (Fish, Calling Station and others) are virtual incentives (% of the pot) on each of the opponent's decisions; they affect decisions only and are not counted in EV, and they are a different model from opponent traits. The default numbers were checked against the text on GTO Wizard's pages. River solutions match GTO Wizard's. On the flop and turn our incentives apply to all streets by default, while GTO Wizard's apply only to the current street; this can be switched under "作用范围" (Scope).
- When re-solving after a lock you can choose what is locked upstream: nothing (the default), everything, or only that player. These are the same three options as GTO Wizard, whose default is to lock everything.
- Not implemented yet: a free editor for adding and removing branches, roots with any player to act, finer draw and blocker features, an aggregate report over all flops, CFR checkpoints on cancellation or a crash, MCP, and three players. The current wide tree with three sizes per street and ordinary raises has passed full-pipeline memory acceptance but not the five-minute speed target; the next step is to verify iteration speed-ups such as scratch-buffer reuse (see the latest progress log).

### Verification and resources

```powershell
python -m pytest -q
$env:POKERLAB_NATIVE='1'
python -m pytest tests/test_solver_native.py tests/test_workbench_native.py tests/test_action_sizes_native.py tests/test_solver_continuation.py pokerstudio/tests/test_solver_native.py -q
$env:POKERLAB_BROWSER='1'
python -m pytest tests/test_workbench_browser.py -q
wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release
python scripts/benchmark_flop.py --allin-raises --combined-only
```

Native tests and the existing full-solve browser integration are turned on explicitly with the switches above. The newer range, usability and configuration-race tests use the local Edge directly once the browser-test dependencies are installed, and need no real model. On 2026-10-08 the default regression gave 147 passed and 32 skipped (55.07 s; the new race files were not collected then). The race, usability, desktop and memory set then gave 51 passed (11.23 s), the three native test files 34 passed (45.90 s) and the full workbench browser loop 1 passed (46.70 s), and all JS syntax checks passed. Detailed evidence and scope are in the [progress log](docs/PROGRESS.md).

2026-10-13 regression for the everyday defaults and start-up races: `python -m pytest tests/test_workbench_usability_browser.py tests/test_solver_agent_races_browser.py tests/test_solver_startup_browser.py -q` gave **11 passed in 24.15 s** (6 start-up, 4 configuration-race and 1 usability test). The existing assistant tests gave 5 passed, and the JS and Python syntax checks passed. The browser configuration regression uses real Edge with an isolated configuration service and does not re-solve the large tree; the full native benchmark and an audit of 26 saved results are in the progress log.

Windows with 32 GB; the measured WSL limit is about 15.47 GiB. In automatic mode the safe budget is the smallest of Windows available memory minus 2 GiB, WSL available memory minus 512 MiB, and a 24 GiB cap; manual mode also includes the explicit cap in the minimum. The page's measurement is for display. The actual launch measures again inside a cross-process serial lock, and the WSL supervisor process checks again and sets an address-space limit; ordinary jobs have no automatic wall-clock limit. Failures to read resources are reported as errors. Windows total memory is never used in place of WSL available memory, and the system reserve, ranges, sizes and the native array pre-check are never cut. Cancelling, or an explicit diagnostic timeout, terminates and reaps the native process group and removes unfinished temporary snapshots without deleting finished results. Reported peaks are the RSS of the native Linux process, not the peak of the whole Windows and WSL system.

Historical resource diagnosis (2026-10-08): a pot-20 copy of a saved wide-range configuration kept the full ranges and sizes, and both launches were refused by the safe pre-check before allocation. The estimates then were a 5.65 GiB peak, 4.66 GiB of engine arrays and a 3.99 GiB job budget, with exit code 1 and the process reaped. The tree was not shrunk and the system reserve was not cut. That copy differs from the 5.37 GiB estimate in a screenshot from the time, so it is not called an exact reproduction of the screenshot, and it is not the measured SPR 12.5 three-street, three-size run either. Historical evidence: `outputs/jobs/3538b9c4cc0847f89856ea11d1de99cb/usability-acceptance.json` and `outputs/memory-budget-diagnosis-20261008.json`.

The baseline cache is keyed to the engine, adapter, branch-expansion options, spot, ranges, both players' sizes, donk settings and solver parameters. Changing only traits or compatible locks reuses the baseline, but never an old model's EV. The first node query still rebuilds the evaluation; repeated queries use a cache keyed to the final strategy and the input identity, up to 256 entries or 128 MiB. Named libraries are in `outputs/library` and studies in `outputs/studies`. After upgrading to this static routing, stop the old service with Ctrl+C and start it again with the launch command.

### Heads-up PLO4 AI (from 2026-10-23, paused since 2026-10-29; separate from the hold'em workbench above)

The goal of this line is a trainable, evaluable strategy baseline near equilibrium that covers a complete hand of heads-up PLO4; its scope and acceptance criteria are in the shared section of AGENTS.md / CLAUDE.md. When it was paused, the milestone was a controlled joint turn + river solve. The code is in `src/pokerlab/plo/`. Status, real verification results and next steps are in [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md), decisions in [docs/DECISIONS.md](docs/DECISIONS.md), and the mapping from papers to code in [docs/RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md) (all in Chinese).

Run these in PowerShell from the project root. No output directory or file may exist yet; the programs never overwrite existing outputs:

```powershell
python -m pokerlab.plo status
python -m pytest tests/test_plo_betting.py tests/test_plo_blockers.py tests/test_plo_evaluator.py tests/test_plo_engine.py tests/test_plo_engine_fuzz.py tests/test_plo_session.py tests/test_plo_subgame.py tests/test_plo_turn.py tests/test_plo_evaluate.py tests/test_plo_cli.py tests/test_plo_river_agent.py tests/test_instructions_consistency.py -q
python -m pokerlab.plo solve-river examples/plo/river_small.json --output outputs/plo/run/river-small
python -m pokerlab.plo query examples/plo/river_small.json outputs/plo/run/river-small/checkpoint.npz --history check
python -m pokerlab.plo evaluate examples/plo/hu_river_solver_vs_baseline.json --output outputs/plo/run/hu-river-solver.json --decision-log outputs/plo/run/hu-river-solver.decisions.jsonl
python -m pokerlab.plo evaluate examples/plo/hu_baseline_vs_baseline.json --output outputs/plo/run/hu-baseline-control.json
python scripts/plo_verify_showdown.py --rows 2000 --output outputs/plo/run/showdown-rows.json
python -m pokerlab.plo solve-turn examples/plo/turn_tiny_lp.json --output outputs/plo/run/turn-tiny --eval-every 50 --lp-limit 6 --spliced-baseline
python -m pokerlab.plo solve-turn examples/plo/turn_small.json --output outputs/plo/run/turn-small --eval-every 30 --spliced-baseline
python scripts/plo_budget_diagnostics.py --output outputs/plo/run/budget.json
python scripts/plo_resource_profile.py --output outputs/plo/run/resources.json
python scripts/plo_reference_error_control.py --output outputs/plo/run/refctl
python -m pokerlab.plo solve-turn examples/plo/turn_sample600.json --output outputs/plo/run/turn-600 --iterations 20 --eval-every 10 --workers 4
python scripts/plo_turn_agent_demo.py --output outputs/plo/run/turn-agent-controlled
python scripts/output_manifest.py outputs/plo/run --output manifests/outputs-run.json
python scripts/plo_agent_reference_eval.py --output outputs/plo/run/agent-reference
python scripts/plo_abstraction_eval.py river --board paired_flush --output outputs/plo/run/abs-river-paired_flush
python scripts/plo_abstraction_eval.py turn --config examples/plo/turn_sample1500.json --mode v1 --iterations 200 --workers 4 --output outputs/plo/run/abs-turn1500-v1
python scripts/plo_blueprint_validate.py --output outputs/plo/run/blueprint-validate
python scripts/plo_blueprint_train.py --iterations 150000 --max-minutes 40 --output outputs/plo/run/blueprint-v0
python -m pokerlab.plo evaluate examples/plo/hu_blueprint_vs_baseline.json --output outputs/plo/run/hu-blueprint.json
```

- **Bet abstraction**: by default four exact pot fractions (1/3, 1/2, 2/3 and 1), plus the minimum legal bet or raise and two boundary actions, a pot-size bet or a short-stack all-in, with at most 2 raises. The pot-limit formula h + P + 2c is shared by the engine and the solver tree.
- **River subgame**: reports give exploitability = NashConv/2 as a share of the starting pot, evaluated on the average strategy; it holds only for that range and size tree.
- **Joint turn + river subgame** (`solve-turn`): with the 4 turn board cards and explicit ranges fixed, one CFR run optimises the turn strategy together with the river strategies under all 48 river cards; for each pair of disjoint hands, each river card has probability 1/40. Small instances are checked against a joint LP, and `--spliced-baseline` also reports the exploitability of the spliced approach (each river solved separately, then joined) for comparison. Showdowns are computed either densely (the reference for small instances) or by inclusion–exclusion per river card (memory linear in range size, up to several thousand hands per player), and `--workers N` runs blocks of river cards in parallel threads. Only controlled stacks (SPR ≤ 2) were tested, and the conclusions apply only to that subgame.
- **Diagnostic scripts**: `plo_budget_diagnostics.py` reports exploitability within the sampled range separately from the error against the reference range; `plo_resource_profile.py` measures time, the CPU-to-wall-clock ratio and peak memory for each stage.
- **HU playing agent `river_solver`**:
  - Uses the fixed baseline `baseline-v1` on the first three streets.
  - On the river it infers both ranges from the public actions with Bayes' rule, then solves and acts by the solved strategy. The decision log records where the ranges came from, the solver configuration and the latency.
  - This is an independent river solve, not global safe re-solving, and it does not claim to reach a PLO equilibrium.
- **HU playing agent `turn_river_solver`** (2026-10-25): uses baseline-v1 (a temporary baseline) preflop and on the flop. At its first turn decision it solves one joint turn + river game, and on the river it reads the same solution instead of re-solving. The handling of off-tree actions and every fallback are written to the decision log.
- **Hand abstraction v1** (2026-10-25, `pokerlab.plo.abstraction`): abstracts information while keeping payoffs exact. River hands are bucketed by equity × blocker features, and turn hands by equity × how their value changes across river cards × blockers. River buckets refine turn buckets, which keeps perfect recall. Quality is evaluated by best response in the original reference game.
- **Four-street blueprint v0** (2026-10-25, `pokerlab.plo.blueprint`): external-sampling MCCFR at 20 bb with limited sizes and a coarse abstraction (without perfect recall), trained on all four streets. The agent `blueprint_v0` uses the blueprint on all four streets; with `early_policy`, `turn_river_solver` also uses it preflop, on the flop and for its range model.
- **Match results**: for functional checks and baseline comparison only; they do not show professional strength or real-game profit.
- **Versions**: a local Git repository (created 2026-10-25), and reports record the commit. Large outputs are not in Git; `manifests/` records their paths and SHA-256 hashes.

---

## 中文说明：本地翻后 Solver

当前为可运行的阶段 1 研究工作台：两人 Flop/Turn/River、可叠加特质、冻结完整对手策略、导出 Hero 信息集最佳回应，并查看组合与后续节点。完整需求见 [原文](Codex_Poker_Solver_Prompt.md)，实际数值与限制见 [进度](docs/PROGRESS.md)。原有数学代码与阶段 0 文档均保留。

## 本机启动

在当前项目根目录的 **PowerShell** 运行一条命令：

```powershell
python -m pokerlab.solver.server
```

浏览器打开 **<http://127.0.0.1:8765>**。计算自动调用已构建的 Ubuntu WSL Rust 引擎，不需要在 WSL 中启动网页服务。服务只监听本机；Ctrl+C 退出并取消所属计算任务。

本机已在 `C:\Users\n1rva\OneDrive\Desktop` 安装 `Pokerstudio.lnk` 和 `Pokerlab Solver.lnk`，目标、参数、工作目录及图标已读回核对，本轮再次确认两个文件存在。安装入口为 `powershell -ExecutionPolicy Bypass -File pokerstudio/install-desktop.ps1`；冷启动、重复启动复用后台及停止自有后台已有实测，实际 Windows 独立窗口的无地址栏视图尚未验收。关闭窗口保留服务和任务；端口占用、日志及显式关停说明见 [桌面启动](pokerstudio/docs/DESKTOP.md)，原命令行入口继续可用。

2026-10-08 本机8765后台已更新。界面使用 bb（大盲），目前底池和剩余筹码支持整数 bb；16 位压缩、自动安全花色同构和默认8线程保留。前端默认启用自动内存，旧示例未指定 `memory_auto` 时也启用，不再受其4096 MiB手动上限限制。显示 Windows / WSL 实时可用内存及安全预算；计算获得串行锁后再次测量。取消自动模式才使用手动上限。后端缺少 `memory_auto` 的旧保存请求与 CLI 仍按手动预算处理，不静默提高显式上限。导出配置位于侧栏顶部。

历史研究“SPR20 多尺寸内存优化验证 - 基线未达0.1%”仍保留。其原测量使用压缩／自动同构、16线程、1800秒时限和自动预算；500次迭代未达到0.1%。冷启动约11分33秒，复用该基线后的完整固定对手流程约3分50秒。当前普通任务已取消自动超时，这里只保留原实测记录。新策略快照直接保存16位数据，避免重开时再次量化；旧格式仍兼容，bb界面没有重算或改写历史报告。

2026-10-13 已保存本次完整大树“**完整Flop 三街三尺寸3x · 0.1%达标 · 2026-10-13**”（研究ID `f79af0c4219441a284f16d34a7da9d39`）。打开桌面Pokerlab或上述浏览器地址，刷新页面，在“已保存研究”中选择该名称并点“打开”。已用真实Edge无头浏览器重开，耗时45.281秒：保留原0.1%目标、9h8h2c、203/449组合及三份完整策略，显示169个策略格、4个合法动作，无JS错误或过期标记。一次真实模型根节点查询完成，原生退出码0且已回收，没有重新CFR／BR；测试仅模拟外部助手状态／会话，使用隔离助手配置。证据见 [重开验收](outputs/performance-20261013-v2/completed-workbench-acceptance.json) 与 [实测截图](outputs/performance-20261013-v2/completed-workbench.png)。当前整数bb引擎把根下注取整为3／5／8bb，实际为底池37.5／62.5／100%；配置中的33／66／100%输入仍保留，不表示支持小数bb下注。

操作示例：

2026-10-13 用户选择日常探索优先：新建局面的均衡基线默认 **0.5% 起始底池**，可自定义。点击侧栏“新建日常局面”会以所选示例建立该默认配置；“载入示例”、导入和打开已保存研究仍保留其显式精度。已有助手持久化状态不会因刷新页面而改写。该目标只用于均衡基线，固定对手最佳回应的 response gap 仍单独测量；本次完整大树保持原定0.1%目标并已达标完成。启动期间的编辑／导入优先于迟到的默认配置，首次后台版本尚未读取时不会写回。

1. 保留默认“Flop 实际范围 + All-in Raise”案例：9h8h2c、底池100 bb、剩余有效筹码200 bb。
   左侧 **OOP 范围／IP 范围** 两份表格默认全部展开，IP 在 OOP 下方；点击“定位 IP 范围”可直接跳到 IP。单击一格选中，再点取消；悬停滚轮每次调5个百分点，按Shift调1个百分点，范围0–100%。默认按169种牌类均匀赋予各具体花色权重；“查看具体花色”可保留高级非对称范围。文本与网格同步，支持导入和导出；公共牌冲突组合保留但不计入有效范围。
   “翻前总范围 %”滑杆按1326个组合加权选择前X%，对子6个、同花4个、非同花12个；边界牌类使用所有花色相同的混合权重。70%对应928.2个加权原始组合；排序使用页面公开说明的翻前启发式模板，不是当前街GTO或实测Equity，不按公共牌重排。调整总范围会重建花色均匀的模板，可撤销；百分比包含公共牌冲突组合。
   三街尺寸可直接点击多选，蓝色按钮表示已选；下方输入框允许自定义，最多三个尺寸。
2. 点击“求均衡基线”。查看目标精度、实际精度与停止原因。
3. 选择组合特质预设或调整 Station、Overbluff、连打后放弃的轻／中／重强度和适用街道，生成对手预览，再冻结并计算最佳回应。高级参数 1／2／3 对应上述强度，不是百分比或已校准人群统计。只比较 River give-up 时，第三项只勾 River，其他输入保持不变。
4. 结果网格按真实动作概率分色，上方显示图例与全范围加权频率；点击 AA 查看具体花色组合、行动概率、Equity、逐行动 EV。鼠标悬停网格可看该格频率；斜纹表示零到达。通过动作按钮和公共牌进入后续节点，切换基线／对手模型／最佳回应。进入对手节点可看“基线 → 固定模型”实际频率变化，两列使用当前模型相同的条件范围权重。
5. 保存研究，再从已保存列表重新打开。修改输入会标记旧结果过期。保存包含全树最终策略；不包含 CFR regret 或断点续算状态。

Node Lock 操作：进入决策节点（包括 Turn/River）→ 在具体组合表中点一行或选择“当前网格手牌组／当前 Filters 选中的组合／全部合法组合” → 输入完整动作分布、点“100% 某动作”，或用“按总频率锁定”填目标频率 → 保留节点锁 → 第 3 步冻结对手只优化 Hero，或第 4 步只锁这些节点、双方重新求解。第 4 步会显示锁定前后的频率和 EV，Hero 节点的锁只在第 4 步生效。锁列表可定位、删除，范围恢复模板可批量解除；撤销／重做支持最近 100 步输入编辑。模型特质改变不会删除锁；改变局面或尺寸后旧锁会明确拒绝，须恢复局面或主动移除旧锁。

“命名范围库／玩家特质库”可保存本机档案；玩家库只保存可跨局面复用的特质，节点锁随研究保存。可导出／导入配置 JSON 复制模型。节点分析提供 Equity 分布，组合表支持按 EV、Equity、收益变化排序／筛选。“模型敏感性”串行运行轻／中心／重三个冻结模型，分别报告同模型提升和根 Hero 行动反转；不是三份结果共用一个对手。

已用本机 Edge 的 Playwright 无头浏览器实际走通上述流程及取消任务；不是人工浏览器验收。截图：`outputs/workbench-flop.png`。

重新构建：`powershell -ExecutionPolicy Bypass -File scripts/build.ps1`。新环境安装 Python 包：`python -m pip install -e '.[dev,solver]'`；浏览器测试另装 `.[browser-test]`。当前使用 Rust 1.75 / Ubuntu WSL；引擎固定为 b-inary/postflop-solver commit `9d1509fe5077d019825f833eed04b16d342dfda1`，AGPL-3.0-or-later，另有已记录的 [完整花色分支补丁](third_party/patches/README.md)。构建脚本核对整个补丁；原始源码可由固定 commit 恢复。项目根目录没有 Git 仓库，没有自动提交或推送。

原 CLI 仍可用：`python -m pokerlab.solver examples/river.json --output outputs/my-river.json`；已存在输出不会覆盖。CLI 默认保存配置和报告；工作台另保存完整策略。

## Pokerstudio 本地剪辑与 Agent

详见 [Pokerstudio](pokerstudio/README.md)。在仓库根目录运行 `python -X utf8 -m pokerstudio.server`，打开 http://127.0.0.1:8770 。支持手牌/字幕/动态叠加、真实 MP4 导出、现有 solver 适配和订阅/API agent；实际验收和限制以其文档为准。独立分析入口为 `/analysis`，原工作台运行方式保留。

## 原 Solver 工作台内的助手

助手已直接接入8765的原 Solver 工作台。它有自己的配置、会话、认证及Solver业务工具，运行时不依赖8770服务或Pokerstudio实例；复用双provider协议实现。订阅入口为正式 Sign in with ChatGPT，也可明确选择现有CLI认证；API需单独配置key并明确允许付费，订阅限额不会自动回退到API。

助手只操作Solver配置、真实任务、结果、节点查询和取消。配置修改检查版本，迟到的回复和工具事件不能回退已同步的局面；并发冲突时保留表单编辑，需点击“同步当前局面”确认。完成的数值来自真实报告；输入改变后结果标记过期。数据默认保存于 `outputs/agent/`，独立应用认证位于 `%LOCALAPPDATA%\Pokerlab\agent`（可用 `POKERLAB_AUTH_HOME` 指定）；API key与付费授权不持久化。

本轮已通过此独立入口的真实订阅验收：`existing_cli` / `gpt-6.1-sol` 将公开小型River底池从25改为20 bb，实际调用读取配置、修改、启动、查询任务和读取报告，任务完成。双方根EV为13.3332891464 / 6.6667108536 bb，实测exploitability为0.00932455063 bb（底池0.0466227531%），达到0.05%目标；复用缓存基线，记录的530次迭代不是本次新迭代。原生退出码0且已回收，API未配置也未调用；证据见 [真实验收](outputs/solver-agent-acceptance-20261008/acceptance.json)。Firefox中已实际读取报告和助手回答，主8765页面的单位、登录状态与双方169格已查看；本机 `existing_cli` 配置已持久化。首次SIWC本人授权和收费API仍无本轮真实验收。

## 离桌复盘助手（2026-10-29 起的主任务，第 1 阶段）

启动方式不变：在普通 PowerShell 里运行 `python -m pokerlab.solver.server`，打开 http://127.0.0.1:8765 。

- **Claude 订阅**（助手默认）：
  - 第一次使用前安装依赖：`python -m pip install "claude-agent-sdk>=0.2.174"`。
  - 在终端运行 `claude`，用 `/login` 登录你的 claude.ai 订阅账号。
  - 本应用不读取、不保存凭据。每轮先检查凭据来源，必须是订阅登录；额度用完或进入额外付费时停止，不会改为按量计费。
  - 服务进程的环境里如果有 `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` 等变量，会拒绝发起请求。不要在 Claude Code 会话内部启动服务。
- **"手牌与对手"面板**：
  - 粘贴 PokerStars/GG 格式手牌，代码解析并重放校验，通过即计入统计。
  - 现场手牌直接在助手里用文字描述，助手整理成统一格式提交，你在面板里核对后点"确认计入统计"。
  - 玩家档案列出 18 项统计的样本数、原始比例、后验均值、90% 区间和倾向分（0–10，即高于人群水平的后验概率 × 10），以及标签、摊牌记录和备注。可以合并别名、设置 Hero 名字。
- **数据**：在 `outputs/coach/`，不进 Git；可用 `POKERLAB_COACH_HOME` 改位置。手牌修订只新增文件，确认和备注写入追加日志。
- **HHP 视频资料**：
  - 私人使用，放在 `outputs/knowledge/hhp/`，不进 Git；可用 `POKERLAB_KNOWLEDGE_HOME` 改位置。
  - 助手用 `search_hhp` 检索 200 个视频的字幕，用 `read_hhp` 读取原文，以及这段时间里从画面整理、通过重放校验的手牌记录（目前 24 个视频共 408 手）。
  - 助手用 `find_hhp_hands` 按牌型、位置、筹码深度、底池类型、牌面和行动线查这些手牌，也能用你记录的手牌找最接近的视频手牌。
  - 视频手牌有教学场景，也有讲解人分析的真实牌局（notes 开头写明），都不计入对手统计。
- **当前限制**：
  - 人群先验是未校准的占位值。
  - 统计到对手特质和 Node Lock 的校准是后续阶段。
  - PokerStars/GG 解析只用合成手牌验证过，还没用真实导出验证。
  - 只用于离桌复盘。

测试与真实验收：

```powershell
python -m pytest tests/test_coach_hands.py tests/test_coach_store.py tests/test_claude_provider.py tests/test_solver_agent.py tests/test_instructions_consistency.py -q
python scripts/coach_claude_acceptance.py
```

真实验收会用你的 Claude 订阅额度跑两轮短请求，结果写到 `outputs/coach-acceptance/<时间>/acceptance.json`。

## 输入、计价与边界

内存超限诊断（先按上文构建最新引擎）：在 PowerShell 运行 `python scripts/diagnose_tree.py "配置文件路径.json" --storage --output outputs/storage-diagnostic.json`。输出文件必须尚不存在。该模式保留游戏配置，比较同构／压缩四种存储方案，使用真实数组结构计数，不分配完整树；峰值余量仍是估计，不冒充实测。不加 `--storage` 则显示旧粗估及明确标注的缩树对照，仅用于诊断，不修改原配置。WSL 诊断子进程上限为 2GiB、每项 60 秒。

普通求解、CLI 和节点读取不再设置自动超时，旧配置中的 600 秒也不会终止任务。任务持续到精度达到目标、明确的迭代上限或主动取消；内存预算与进程回收保护仍然有效。显式测试／诊断可单独设置时限，不是工作台默认行为。

2026-10-16：已接通无硬锁压缩任务的合法组合稀疏存储，保留原16位量化及完整逻辑手牌顺序。当前203/449组合、SPR12.5、三街三个Bet＋3x树的精确预检从14.253降为13.231GiB，减少约1.022GiB数组；这是分配计划，尚非新版完整峰值。稀疏展开有速度开销，小型同案例对照见[进度](docs/PROGRESS.md)，不宣称此次同时提速。硬锁仍走原稠密路径，旧策略和CFR状态可读取，磁盘文件大小未优化。桌面Pokerlab启动入口不变。

用户确认本轮完整验收改用 **0.5% pot**（8bb起始底池对应0.04bb），新副本是 `outputs/performance-20261016-sparse/config.json`，原0.1%文件及研究保留。范围、SPR、每街尺寸、16线程和无限墙钟不变。后续用户释放资源后已实际尝试完整树，但13.231GiB需求仍高于当时11.073GiB安全预算，在分配前拒绝并回收，仍无新版完整耗时／RSS／实际精度。另减少稀疏临时复制，57项引擎、22项适配器与72项真实原生集成通过，小型速度变化约1%，不宣称宽树提速；资源充足后在项目根目录PowerShell执行以下命令，输出目录须尚不存在：

```powershell
python -X utf8 scripts/benchmark_config.py outputs/performance-20261016-sparse/config.json --cold --output outputs/performance-20261016-sparse/full-cold-02
```

2026-10-15当前引擎已启用DCFR临时缓冲复用，现有桌面／PowerShell启动入口不变。旧实现逐位回归和72项真实原生集成通过；SPR20历史树固定30次的迭代时间151.95→19.28秒，含精度测量的基线166.00→33.39秒，诊断峰值仅增加4.8MiB。该历史树不是当前203/449组合、每街三尺寸的目标树，30次也未达到目标精度。当前目标树新引擎验收因可用内存不足尚未完成，不将历史树的7.9倍迭代加速外推成全流程保证。完整配置、测试命令和证据见最新[进度](docs/PROGRESS.md)。

同日用户关闭游戏后，原树重试仍在分配前被14.253GiB需求／11.149GiB安全预算拦下，没有新的完整求解结果。资源探测现用WSL启动后的Windows可用内存，预留不变；通用异常取消保持串行锁直到监督器完成回收，取消等待不是求解超时。57项预算／回收测试和4项真实原生回归通过，详见上述进度。

2026-10-13完整三街三尺寸配置的受控预检由16.264降为14.253GiB：主要是明确限制分配器／线程开销并校准余量，同时将模型访问集合改成位图；不是实测内存已减少2GiB。另有快照分块读写与BR子树并行，保持原策略精度与求和顺序。任务 `4c8e056088c848b7bc7d573d7df67aa8` 已完整跑完：保留203/449组合、SPR12.5、三街各三个Bet尺寸和3x普通Raise，未设超时或降低原0.1%目标。冷启动全流程 **2小时34分54秒**，原生RSS峰值 **13.8494GiB**，1060次迭代实测 **0.0921778381% pot**；停止原因为达到目标，原生进程正常退出并回收。内存验收通过，五分钟速度目标未达到。同轮基线首次低于0.5%耗时41分57秒，这不是另跑0.5%的全流程时间。命令、分阶段耗时及数值核验见最新[进度](docs/PROGRESS.md)。

未收敛且正常到达迭代上限的基线会另存 `PLCFR001` 累积策略／regret 状态；提高最大迭代数后，同一树可从已保存迭代继续，界面区分历史迭代与本次新增。旧 `PLPOL002/003` 最终策略不能续算；主动取消、进程崩溃时尚不保存正在进行的状态，已收敛的旧基线要求更严格目标也可能需要重算。CFR 状态会额外占用磁盘，不能把保存耗时当作迭代速度。

公共牌旁的“图形选牌”打开按四种花色排列的 52 张牌，支持选择 Flop／Turn／River 初始牌面；求解后的发牌节点同样显示图形牌阵，只有合法分支可点击。策略网格按真实频率显示：Fold 蓝、Check/Call 绿、Bet/Raise 红、超过底池的进攻紫；恰好 100% 仍为红。同一节点、同一色系内，尺寸越大颜色越深，相同尺寸同色；按真实尺寸排序，不依赖动作排列顺序。图例、网格、动作按钮及具体组合频率条共用配色；颜色深浅表示尺寸，色块宽度表示概率。Raise 的比例为额外加注额除以跟注后的底池，All-in 按实际比例判断。最佳回应可能是纯策略，不会为彩色效果伪造混合频率。

- 输入 3/4/5 张公共牌自动选择起始街道；范围按 OOP、IP 排列，支持 `AA,AKs`、具体组合及权重、文本导入。Hero 可选双方，根节点始终 OOP 先行动。
- 原Solver工作台的pot是当前底池，stack是双方有效剩余筹码，新UI输入单位为bb，可以填小数（精确到0.01 bb，`chip_scale`=100）；EV和精度同为bb。新UI及独立助手的配置记录可选metadata `amount_unit="bb"`，一个原生数值单位对应1 bb；native执行前剥离此展示字段，计算和兼容字段 `target_unit="chips"` 保持原协议。旧报告没有该metadata时显示“原筹码单位”，不自动贴bb或换算金额。载入旧研究保留原始数字，须核对计价基准后再明确当前输入单位。Pokerstudio手牌的chips/USD仍按其独立适配规则验证。没有未来抽水、非等筹码边池或三人支持。
- 三街分别设置下注与加注尺寸，默认双方共用；“按位置配置尺寸／Donk”可给 IP 独立尺寸及 OOP Turn/River Donk。下注支持 `33%`、`10c`（bb模式为10 bb，原筹码模式为10筹码）、`a`；加注支持 `2x` 及更大倍数、`60%`（加注额 ÷ 跟注后底池，与 GTO Wizard 相同）、`a`。每类每街每位置最多3个尺寸，SPR上限20（设了每街加注次数时为40），超限拒绝，不静默缩树。加注报告为Raise-to，尚不支持任意绝对Raise-to输入。
- Preflop 行动线：`outputs/gtow-preflop/` 下有文件时，页面顶部可以选深度（100bb、150bb、200bb、400bb，默认 150bb；$800 = 160bb，最接近 150bb。模型是 8max straddle、cEV、7bb 开池），按座位点 action。手牌格和卡片显示当前座位的全部动作和频率（Raise、Call、Check、Allin、Fold）；走到两人底池后自动填双方范围、底池和有效筹码，选公共牌后解算，解算前可以在左侧改范围和参数。全下、三人以上和翻前结束的线只显示说明，灰色按钮是没有记录的线。范围框也可以直接粘贴 GTO Wizard Ranges 页 Copy 的内容。这些文件不进 Git。
- 节点页：手牌格可切换 Strategy / EV / Equity / EQR / 范围高度 / 比较 EV，可合并尺寸，右侧有手牌、汇总、Filters、Equity chart、Ranges、Breakdown、Blockers，顶部显示整体动作频率。发牌节点可以生成这一街的发牌报告。工作区下方有多牌面报告。频率按组合数算，EV / Equity 平均按阻断调整后的权重算，与 GTO Wizard 相同（DECISIONS D34）。
- 下注树模板：快速（每街 1 个尺寸）、标准（每街 2 个尺寸）、完整（每街 3 个尺寸）、完整省内存（3 个尺寸，河牌不加注），都限制每街最多加注 2 次。实测和内存估算见 `docs/PROJECT_STATE.md` A2e–A2g。WSL 默认只用一半内存；本机已在 `%USERPROFILE%\.wslconfig` 写 `memory=28GB`。内存不够时可以勾选“允许占用闲置后台程序的内存”，电脑可能变卡。
- 完整保留所选树的合法公共牌与后续决策，无未来价值截断。2026-10-06 已跑通 240/290 组合、SPR20、多尺寸和普通加注的原配置：16 线程约 11 分 33 秒、峰值 RSS 7.15GiB。500 次迭代实际 exploitability 为底池的 0.4542%，未达到 0.1% 目标；不代表所有宽范围、多尺寸树性能达标。详细分阶段结果见进度文档。
- 根 EV = 回收原底池及对手新投入 − 自己新投入；旧投入为沉没成本，无抽水时双方根 EV 和为 pot。Equity 是摊牌胜率／平局份额，不是 EV。零后验概率下未定义值显示为空。
- 特质强度 0–6 是 logit 偏置，不是百分点或下注范围弱牌占比。按规则叠加后在动作类别及尺寸内归一化；Neutral 保留基线。模板均为研究假设，牌力分类较粗，未经真实对局数据校准。
- Flop/Turn/River 的对手节点均支持具体组合及批量完整分布锁定。`auto_suits=true` 且无手动锁时使用引擎可证明的花色同构；有手动锁时 `expand_suits=true` 保留所有公共牌分支，不串花色。加新锁后可能需要重建更大的基线。16 位存储不合并下注尺寸，有数值量化误差；原生重评容差未放宽。含硬锁快照查询使用 f32 保留保存的概率精度，查询内存可能高于压缩求解。
- Player Profile（Fish、Calling Station 等）是对手每个决策上的虚拟激励（% 底池），只影响决策，不计入 EV；和“对手特质”是两种模型。默认数字已按 GTO Wizard 的页面文字核对。河牌的解和它一致；翻牌和转牌默认激励作用所有街，它只作用当前街，可在“作用范围”切换。
- 锁定后重解可以选上游：不锁（默认）、锁全部、只锁该玩家，和 GTO Wizard 的三个选项相同，它默认锁全部。
- 仍未实现自由分支增删编辑器、任意当前行动者根节点、细化听牌／阻断牌特征、全部翻牌汇总报告、取消／崩溃时CFR检查点、MCP或三人。每街三尺寸与普通加注的当前宽树已通过完整流程内存验收，尚未达到五分钟速度目标；下一步验证临时缓冲复用等迭代加速，见最新进度。

## 验证与资源

```powershell
python -m pytest -q
$env:POKERLAB_NATIVE='1'
python -m pytest tests/test_solver_native.py tests/test_workbench_native.py tests/test_action_sizes_native.py tests/test_solver_continuation.py pokerstudio/tests/test_solver_native.py -q
$env:POKERLAB_BROWSER='1'
python -m pytest tests/test_workbench_browser.py -q
wsl -d Ubuntu --cd /mnt/c/Users/n1rva/projects/pokerlab -- cargo test --release
python scripts/benchmark_flop.py --allin-raises --combined-only
```

原生与既有完整求解浏览器集成使用上述开关显式启用；新增范围、可用性和配置竞态测试在安装浏览器测试依赖后直接使用本机 Edge，无需启动真实模型。2026-10-08 默认回归147 passed / 32 skipped（55.07秒，当时未收集新增竞态文件）；随后竞态／可用性／桌面／内存合集51 passed（11.23秒），原生三个测试文件34 passed（45.90秒），完整工作台浏览器闭环1 passed（46.70秒），JS语法检查全部通过。详细证据和范围见 [进度](docs/PROGRESS.md)。

2026-10-13 日常默认值与启动竞态回归：`python -m pytest tests/test_workbench_usability_browser.py tests/test_solver_agent_races_browser.py tests/test_solver_startup_browser.py -q`，**11 passed，24.15秒**（6项启动、4项配置竞态、1项可用性）；既有助手测试5 passed，JS／Python语法检查通过。浏览器配置回归使用真实Edge及隔离配置服务，不重新求解大树；完整原生基准与26项保存结果审计另见进度文档。

Windows 32GB；实测WSL上限约15.47GiB。自动模式的安全预算是Windows当前可用内存减2GiB、WSL当前可用内存减512MiB及24GiB上限三者的最小值；手动模式再取显式上限的最小值。页面测量用于显示，实际启动在跨进程串行锁内重新测量，WSL监督进程再检查并设置地址空间上限，普通任务无自动墙钟时限。读取资源失败如实报错；不会用Windows总内存代替WSL可用内存，也不削减系统余量、范围、尺寸或原生数组预检。主动取消或显式诊断超时会终止并回收原生进程组，清理未完成临时快照，不删除已完成结果。报告峰值为原生Linux进程RSS，非整台Windows／WSL峰值。

历史资源诊断（2026-10-08）：宽范围保存配置的pot20副本保留完整范围和尺寸，两次启动均在分配前被安全预检拒绝；当时峰值估计5.65GiB、引擎数组4.66GiB、任务预算3.99GiB，退出码1且进程已回收。当时未缩树或削减系统预留。该副本与当时截图5.37GiB估计不同，不称为截图的精确复现；这也不是本次SPR12.5三街三尺寸实测的结果。历史证据见 [拒绝记录](outputs/jobs/3538b9c4cc0847f89856ea11d1de99cb/usability-acceptance.json) 与 [内存诊断](outputs/memory-budget-diagnosis-20261008.json)。

基线缓存绑定引擎、适配器、展开分支选项、局面、范围、双方尺寸、Donk 及求解参数；只改特质／兼容的锁复用基线，不复用旧模型 EV。首次节点查询仍需重建评估；重复查询使用最终策略与输入标识绑定的缓存，最多 256 项或 128MiB。命名库位于 outputs/library，研究位于 outputs/studies。升级这次静态路由后请先 Ctrl+C 停止旧服务，再按启动命令重开。

## Heads-up PLO4 AI（主任务，2026-10-23 起；与上面的 Hold'em 工作台相互独立）

当前主任务是建立覆盖完整一手 HU PLO4、接近均衡的可训练、可评估策略基线，范围和验收标准见 AGENTS.md / CLAUDE.md 的共用段。当前里程碑是受控的 turn + river 联合求解。代码在 `src/pokerlab/plo/`。状态、真实验证结果和下一步见 [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md)，决策见 [docs/DECISIONS.md](docs/DECISIONS.md)，论文与实现的对应见 [docs/RESEARCH_NOTES.md](docs/RESEARCH_NOTES.md)。

在项目根目录的 PowerShell 中运行。所有输出目录或文件必须尚不存在，程序不会覆盖已有输出：

```powershell
python -m pokerlab.plo status
python -m pytest tests/test_plo_betting.py tests/test_plo_blockers.py tests/test_plo_evaluator.py tests/test_plo_engine.py tests/test_plo_engine_fuzz.py tests/test_plo_session.py tests/test_plo_subgame.py tests/test_plo_turn.py tests/test_plo_evaluate.py tests/test_plo_cli.py tests/test_plo_river_agent.py tests/test_instructions_consistency.py -q
python -m pokerlab.plo solve-river examples/plo/river_small.json --output outputs/plo/run/river-small
python -m pokerlab.plo query examples/plo/river_small.json outputs/plo/run/river-small/checkpoint.npz --history check
python -m pokerlab.plo evaluate examples/plo/hu_river_solver_vs_baseline.json --output outputs/plo/run/hu-river-solver.json --decision-log outputs/plo/run/hu-river-solver.decisions.jsonl
python -m pokerlab.plo evaluate examples/plo/hu_baseline_vs_baseline.json --output outputs/plo/run/hu-baseline-control.json
python scripts/plo_verify_showdown.py --rows 2000 --output outputs/plo/run/showdown-rows.json
python -m pokerlab.plo solve-turn examples/plo/turn_tiny_lp.json --output outputs/plo/run/turn-tiny --eval-every 50 --lp-limit 6 --spliced-baseline
python -m pokerlab.plo solve-turn examples/plo/turn_small.json --output outputs/plo/run/turn-small --eval-every 30 --spliced-baseline
python scripts/plo_budget_diagnostics.py --output outputs/plo/run/budget.json
python scripts/plo_resource_profile.py --output outputs/plo/run/resources.json
python scripts/plo_reference_error_control.py --output outputs/plo/run/refctl
python -m pokerlab.plo solve-turn examples/plo/turn_sample600.json --output outputs/plo/run/turn-600 --iterations 20 --eval-every 10 --workers 4
python scripts/plo_turn_agent_demo.py --output outputs/plo/run/turn-agent-controlled
python scripts/output_manifest.py outputs/plo/run --output manifests/outputs-run.json
python scripts/plo_agent_reference_eval.py --output outputs/plo/run/agent-reference
python scripts/plo_abstraction_eval.py river --board paired_flush --output outputs/plo/run/abs-river-paired_flush
python scripts/plo_abstraction_eval.py turn --config examples/plo/turn_sample1500.json --mode v1 --iterations 200 --workers 4 --output outputs/plo/run/abs-turn1500-v1
python scripts/plo_blueprint_validate.py --output outputs/plo/run/blueprint-validate
python scripts/plo_blueprint_train.py --iterations 150000 --max-minutes 40 --output outputs/plo/run/blueprint-v0
python -m pokerlab.plo evaluate examples/plo/hu_blueprint_vs_baseline.json --output outputs/plo/run/hu-blueprint.json
```

- **下注抽象**：默认 1/3、1/2、2/3、1 pot 四档精确比例，另加最小合法下注/加注，以及 pot 尺寸或短码 all-in 两个边界动作，最多 2 次加注。pot-limit 公式 h + P + 2c 由引擎和求解树共用。
- **河牌子博弈**：报告给出 exploitability = NashConv/2，分母是起始底池，评估平均策略，只对该范围和尺寸树成立。
- **turn + river 联合子博弈**（`solve-turn`）：固定 4 张 turn 公共牌和显式 range，一次 CFR 同时优化 turn 和全部 48 张河牌下的 river 策略，每对不相交手牌的河牌概率为 1/40。小实例与联合 LP 核对；`--spliced-baseline` 另报拼接法（各 river 单独求解后拼接）的 exploitability 作对照。摊牌计算有稠密（小实例参照）和按河牌容斥（内存线性，可到每方数千手）两种，`--workers N` 按河牌分块用线程并行；只测了受控筹码（SPR ≤ 2），结论只代表该子博弈。
- **诊断脚本**：`plo_budget_diagnostics.py` 分开报告抽样 range 内的 exploitability 与对参考 range 的误差；`plo_resource_profile.py` 分阶段测时间、CPU/墙钟比和峰值内存。
- **HU 对局 agent `river_solver`**：
  - 前三街用固定基线 `baseline-v1`。
  - 河牌先由公开动作用 Bayes 推出双方 range，再求解并按求解策略行动。决策日志记录 range 来源、求解配置和延迟。
  - 这是独立河牌求解，不是全局安全重解，也不宣称达到 PLO 均衡。
- **HU 对局 agent `turn_river_solver`**（2026-10-25）：翻前、翻牌用 baseline-v1（临时基线）；第一次 turn 决策时求解一个联合 turn + river 博弈，river 直接读同一个解，不独立重解；树外动作的处理和所有 fallback 都写入决策日志。
- **手牌抽象 v1**（2026-10-25，`pokerlab.plo.abstraction`）：信息抽象、收益精确。river 按胜率 × 阻断牌特征分桶；turn 按胜率 × 各河牌下价值变化 × 阻断牌分桶，river 桶细化 turn 桶，保持 perfect recall。效果在原参考游戏里用最佳回应评估。
- **四街蓝图 v0**（2026-10-25，`pokerlab.plo.blueprint`）：20bb、有限尺寸、粗抽象（不保持 perfect recall）的外部采样 MCCFR，四街都参与训练。agent `blueprint_v0` 四街都用蓝图；`turn_river_solver` 加 `early_policy` 后，翻前、翻牌和 range 模型也改用蓝图。
- **对局结果**：只用于功能验证和基线比较，不代表职业水平或实战盈利。
- **版本**：本地 Git 仓库（2026-10-25 建立），报告记录 commit；大型输出不进 Git，`manifests/` 记录路径与 SHA-256。
