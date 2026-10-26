# Point-in-time runner: design (2026-10-20, updated 2026-10-25)

*Written by the assistant for infrastructure step 4 (audit S7 raised to a blocker by Nicolas on 2026-10-19; also S1,
S2, S3, S6, S9, B6). Agreed by Nicolas on 2026-10-21, with the minute mode, the single holdout path and the extra
checks added that day.*

## The rule it enforces

At each decision moment the design is shown only what could have been seen at that moment. This is enforced by how
the design is called, not checked afterwards.

## Three parts

- **Design** (experiment code): turns what it is shown into a decision.
- **Position engine** (shared code, reviewed once): turns decisions into trades, bar by bar. Anything that needs memory
  across minutes (being in a position, the entry price, a trailing high, take-profit and stop-loss levels) lives here,
  not in design code. An engine sees bar t and its own state only.
- **Runner** (shared code): walks time forward, builds the views, calls the design and the engine, and does
  everything around a run (below).

Engines, each ported from the existing simulator and required to reproduce it exactly on tests:

| Engine | Ported from | First user | Status |
|---|---|---|---|
| Fractional weight (costs, dead band, integer shares) | the old fractional simulator (now `tests/fractional_exposure_reference.py`, parity tests only) | exp05 | 4a |
| Barrier trades (take-profit, stop-loss, time exit) | `so.core.trade_execution`, `so.core.backtest_simulation` | exp01 | 4b-2a daily, 4b-2b minute (`BarrierEngine`) |
| Trailing stop and re-entry | `so.core.reentry_simulation` | exp02 | 4b-2a (`TrailingStopEngine`; daily mode with a minute-checked stop) |

The view carries a read-only copy of the engine state as of the decision moment (`in_position`, `share_count`,
`last_exit_session`, `last_exit_reason`, `last_exit_fill_price`, `cash_session_count`). A design learns of a stop-out only at its next
decision. The engine never shows the design anything after that moment. A design module names its engine with
`ENGINE_NAME` (`fractional`, `trailing_stop`, `barrier`).

**Shared design helpers (2026-10-23).** `so.features.view_history.DailyHistory` keeps the `TSDAY` rows a design has
received (one `get_new` per call); `VixPrevHistory` computes `vix_level_prev`, `vix_term_prev` and `vix_pct250_prev`
from `VIX_DAILY` / `VIX3M_DAILY` rows with the definitions of `so.features.vix_features`. `so.features.rule_design.
RuleDesign` is the decide of an exit / re-entry rule on the trailing-stop engine without a stop: a subclass writes the
exit signal and the re-entry rule only. `TSDAY` no longer serves `fill_open` and the complete-session high, low and
close on the feature path: they are computed from bars after the decision bar.

**Stop parameters (2026-10-22).** The `trail_multiple` and `volatility` of a decision take effect at that decision's
fill and stay in force until the next decision's fill, including the next session's morning. The last session of a
window (no decision) keeps the previous ones; before the first decision the engine uses the design module's
`TRAIL_MULTIPLE` / `VOLATILITY` (none: no stop). The candidate stream (`DailyLoop`) and the replay of recorded
decisions (`run_engine_decisions_dict`, used for the prior-only path) follow the same rule, so a one-candidate replay
reproduces that candidate's stream. Until 2026-10-22 the replay applied a session's recorded parameters to its own
morning as well (the old simulator's timing); that was inconsistent with the stream and, for a design whose
parameters use intraday data, would apply them to bars before the decision. The old simulator's timing survives only
in `tests/trailing_timing_reference.py`, for the engine parity tests.

An idea that needs new stateful logic gets a new engine (an infrastructure change, reviewed like any other) or runs
in the slow strict daily mode.

## Daily mode (default)

- The runner walks forward one decision moment at a time (default: every session at the end of the 15:58 bar; fill at
  the 15:59 open, the existing convention).
- At each moment it calls the design with a **view** that ends at that moment:
  - SPY bars up to the end of the decision bar;
  - every declared source with `available_ts` at or before that moment (registered sources only);
  - labels only with `label_known_ts` before that moment, and only through a separate door, for training.
  A read past the end of the view does not exist: the view is a slice that stops there. The design never receives the
  full bar arrays.
- The design may keep any state between calls (running averages, a fitted model). Because the calls come in time
  order and each view stops at its moment, that state cannot contain the future.
- The design returns a decision for its engine (for the fractional engine: a target weight, 0 = cash, 1 = fully
  invested, NaN = keep). Retraining happens inside the design on its pre-registered schedule, through the label door.

## Minute mode (agreed 2026-10-21)

For decisions at minute level (exp01's entries, about 2 million minutes x 12 candidates), where calling Python once per
minute is too slow. It keeps the rule structural:

- **Rows.** Each minute row is built only from data available at the end of that minute (the existing per-session
  caches, stamped with `available_ts`). Before the design sees them, the runner checks every row's `available_ts`
  against its decision moment; one failing row stops the run.
- **Row-local signal.** The design writes one module-level function: rows (plus a model fitted earlier) in, one value
  per row out, where each output may depend only on its own row. The runner enforces this: it passes all rows of one
  refit block together, shuffled, puts the outputs back in order, and calls twice with different shuffles. Identical
  outputs are required or the run stops and names the design. A function that looks at neighbouring rows (shift,
  rolling, cumulative sums) or that keeps state across calls fails. The preflight refuses a method or a closure.
  (4b-2b shuffles a whole refit block, not one session at a time: a session-sized shuffle would miss a signal that
  only looks across sessions inside the same fitted model.)
- **Models.** Fitted on the pre-registered `so.core.rolling_retrain` schedule through the label door
  (`label_known_ts` strictly before the refit moment; unfinished labels dropped). The runner applies each model only
  to rows at or after its refit moment and before the next refit; the design does not choose which rows a model
  scores.
- **Fill.** A signal at the end of minute t fills at the open of minute t + 1 (same session). The last minute of a
  session has no next-bar fill.
- **Engines** turn the signals into trades. Their loops are compiled (numba, added to the locked package list). A 4-year
  synthetic minute run with a small LightGBM, 12 candidates, weekly refits and `n_jobs=8` took 412 s. The real exp01
  run takes 11-14 hours (denser rows, 21 models per refit); Nicolas accepted that on 2026-10-25.

Intraday stops driven by daily decisions (exp02) use daily mode with the trailing-stop engine.

## What the runner does around a run

- **Candidates and selection:** each candidate is its own stream; periods, pooled prior-only selection and the
  carried position are done once in shared code (no copies per experiment). Candidate-period scores are slices of
  each candidate's continuous stream (result over the period's dates, including any position carried in), minus
  buy-and-hold sliced the same way.
- **Run guards:** a run refuses uncommitted changes in the code it uses, a missing or stale `VIEW.json`, and the
  quarantine root; a resume refuses a checkpoint from a different commit or code hash. (Decided 2026-10-21.)
- **Design-code guard (audit B2, 2026-10-25):** every call into design code (module import, `get_candidate_design`,
  `decide`, `fit`, `fit_shared`, `finish_fit`, `signal`) runs behind `so.runner.guard`: an audit hook refuses any
  open, listing, rename or delete under the data root, the quarantine or the holdout folder, and any subprocess or
  network connection; a snapshot of every `so.*` module (functions by identity, UPPERCASE constants by value) is
  compared after the import, after each period and at the end of each stream. The preflight also refuses writes into
  imported names (`config.X = ...`) and `setattr`.
- **Baselines:** buy-and-hold, constant exposure at the same average weight (daily rebalanced), and random timing
  that places the path's non-base spells at random (same time at each weight; switch count may differ from the
  path only at the two window edges). The exposure is the decision target for the fractional engine and the position
  actually held at each close for the trailing-stop and barrier engines, whose exits happen inside the engine (audit
  B1, 2026-10-25: the targets hid every stop and exit). Random timing uses 100 fixed seeds; to count as ahead of it, a design must
  beat at least 95% of the draws. Placing switches independently does not preserve exposure; shuffling run lengths
  in place does not move a one-exit path. Neither is the baseline.
- **Trial log:** rows are written as each candidate-period is scored, before any summary is shown. Trial ids are
  stable (built from the run, candidate and period), so a resumed run never logs the same trial twice. Tested with
  several processes writing at once.
- **Checkpoints:** after each period, so a crash resumes instead of restarting.
- **Parallel:** candidates run in separate processes (8 cores).
- **Verdict parts (2026-10-25):** return; consistency (ahead in at least 60% of the decisive rolling 12-month
  windows; a window within +/-0.5 percentage points of buy-and-hold is a tie and is not counted; at least 24 decisive
  windows; audit S1, a data-dependent amendment because exp13 failed only the old rule); baselines (constant exposure
  with a 0.05 dead band, random timing on the realized exposure); look-ahead; multiple testing (deflated Sharpe
  ratio of quarterly excess returns at 0.95 or more, and random-timing p-value at most 0.05 / N, N = designs tried on
  the development data including the pre-reset records; `so.core.multiple_testing`, audit B5). The report also shows
  the prior-only path and buy-and-hold at slippage 0.00 / 0.01 / 0.02 (not part of the verdict).
- **Pre-registration (audit S5):** `so.runner.preregistration` refuses a development run whose version already ran
  with different design-folder code, a first run of a new version without a `preregister` last commit or without the
  required protocol sections and "Derived from:" line, and a fourth version of an experiment.
- **Report and verdict:** one shared decision rule (the agreed "consistently match or beat" rule) and one run
  manifest (status, commit, `VIEW.json` stamp, trial ids, outputs, verdict) that the orchestrator reads. The stamp
  makes an old run reproducible after the view's edge has moved.
- **Look-ahead check on every run:** truncation and perturbation at `RUNNER_LOOKAHEAD_CUT_COUNT` (3) random cut dates
  (one from each third of the span, fixed seed), plus, for each candidate, up to `RUNNER_LOOKAHEAD_CHANGE_CUT_MAX` (10)
  sessions where its own decision changed (`RUNNER_LOOKAHEAD_CHANGE_CUT_MAX_MINUTE`, 2, in minute mode), spread
  evenly. For each cut the stream is re-run on bars and sources truncated after the cut (the one extra session that
  gives the cut its call is flat at the cut's last close), and again with every bar after the cut's decision bar
  rebuilt from shuffled returns starting 3% higher (`get_perturbed_ohlcv_dict`) and the declared feature / label rows
  after the cut permuted among themselves and rescaled (`get_perturbed_feature_pdf`). Every decision up to and
  including the cut must match the full run (minute mode, perturbation: every decision made at or before the end of
  the cut session's decision bar). A failure fails the verdict. The re-runs write no trial-log rows. Results go to
  `lookahead.json`. Audit B3 (2026-10-25): with three random cuts and a x1.25 level shift, a one-day leak of a rare
  sign feature passed in 7 of 13 synthetic years; with these cuts and perturbations it fails in 13 of 13
  (`tests/test_runner_lookahead.py`). The check cannot see a future value baked into a cached row or a read around
  the view: the cache audit and the design-code guard cover those.

## Holdout evaluation uses the same runner (agreed 2026-10-21)

Nicolas's holdout evaluation calls the same runner function with the quarantine root and the evaluation token. The run
starts at the development start (warm-up, models, selection history and position carried through), and only the
holdout sessions are reported. The report's result on the never-read part of the window (after 2026-04-15) is labelled
a sanity check: about 80 sessions are too few to pass or fail a design.

Implemented 2026-10-21: `so.runner.run_holdout_dict`. The old replay path in `so.core.holdout`
(`run_holdout_evaluation`, `get_prior_only_result_dict`) was deleted on 2026-10-25 (drop 4):
`scripts/holdout_evaluate.py` evaluates runner designs only, so the development result and the holdout result always
come from one code path.

## What a new experiment writes

`PROTOCOL.md`, `config.py`, and one `design.py` with: the candidate list, the declared sources, the engine and its
parameters, and the decision function (daily) or row-local signal function (minute), plus fit, for a model. No copied
replay, selection, baseline or report code.
