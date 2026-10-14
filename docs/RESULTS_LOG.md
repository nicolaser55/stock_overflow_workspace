# Stock Overflow: Results Log

*The chronological record of experiment outcomes of the reorganized workspace (from 2026-10-05), for the thesis. Each entry
states what was run, under which protocol version and configuration hash, what was observed, and what the evidence does and
does not support. Failures are results. Test windows touched so far: **none** (as of 2026-10-09).*

*Earlier results (v1, v2, the step 13 exploration, the bad tick correction and the audit) are in
`docs/history/RESULTS_LOG_2026-10-05.md`; their 4,089 trials are in `records/legacy/trial_log_legacy_20261005.csv` and
still count.*

## Methodology note (2026-10-11, Nicolas)

The evaluation design is now a rolling 12-month holdout (`so.core.holdout`). It replaces the per-fold 3-month test
windows and the fixed untouched window 2026-05-14 → 2026-08-13. The holdout is the last 12 calendar months of the data,
ending at the latest session present when the window is opened, and it stays frozen after that. Train and validation
boundaries are derived from that window and the experiment's embargo. Sessions after the window's end are forward data
and are refused. Each frozen design may be evaluated once per window, at most 10 designs, then the window is retired.
exp01–exp13 are archived: the entries below are unchanged, and their committed notebook outputs stay the record. No
window was opened on this date, no design was evaluated, and no trial-log row was added. Test windows touched so far:
still none. Calibration re-runs of exp05 and exp06 under the new split, as new versions, are proposed and waiting for
Nicolas.

## Methodology note (2026-10-11, Nicolas): rolling retraining

Nicolas decided on 2026-10-11 that model-based designs are evaluated by walk-forward analysis with a rolling training
window. The model is retrained on a pre-registered schedule using only data available on the retraining day, then
deployed until the next retraining. Decisions are made every session at the decision bar with the latest model, and
the path is judged continuously over time in development and in the holdout.

Retraining frequency is a pre-registered setting of each protocol. The default is weekly (the first session of each
week). Changing it after results is a new version. One optional pre-registered comparison, weekly versus quarterly, is
allowed. The default training-window candidates are 6 months, 2 years and 10 years. Candidate selection, across
training windows or any other protocol dimension, is pooled over the last 4 quarters and re-evaluated quarterly,
prior-only, as in exp02–exp13.

Labels may look forward from their own row. A model trained on day t learns only from rows whose label was complete
before the decision bar of day t. Unfinished labels are dropped, never filled with 0 or any other value. Features use
only information available at or before the decision bar.

The shared module was not built. The task requires `main` to contain `so/core/holdout.py` with the T1–T3 follow-up (an
intraday truncation cut). Observed on 2026-10-11: local `main` and `origin/main` are `11a1322`, which has no
`so/core/holdout.py`. That file exists on `agent/holdout-split` at `80c67a3`. There, `get_truncated_ohlcv_dict` keeps
every bar of the cut session through `session_end_idx` (the session close). That is not a cut at the decision bar.
No experiment was run, no holdout window was opened, and no trial-log row was added. Archived experiments exp01–exp13
are unchanged.

*Correction later on 2026-10-11:* T1–T3 were implemented on `agent/holdout-split`. The truncation test also cuts each
month-end at the decision bar (15:58 on a full day, the second-to-last bar on a half day) and requires that session's
target weight and position change to match the full run. An `invalid_lookahead` evaluation appends one trial-log row
(stage `test`, `test_window_touched` True, note `invalid_lookahead`, no return metrics). The guard-off argument may
appear only in the pipeline, `scripts/check_spy_rename.py`, `scripts/holdout_evaluate.py`, `scripts/smoke_notebook.py`,
`so/core/holdout.py` and `tests/`. Synthetic tests only. The shared trial log was not modified, no window was opened,
and `main` still does not contain the holdout module. Rolling retraining waits for Nicolas to merge that branch.

*Correction later the same day (audit of `a64c1a9`):* cutting the session at the decision bar moved the decision.
`get_session_decision_idx_dict` sets it to `session_end_idx` minus one bar, so a session that ended at 15:58 was
decided at 15:57. That check was replaced by a perturbation: every bar strictly after the cut session's decision bar
is overwritten (price × 1.25 plus seeded noise) and the session structure is left unchanged. The whole-session
truncation is unchanged. No experiment was run, no window was opened, and the shared trial log was not modified.

## Methodology note (2026-10-11, Nicolas): point-in-time data

Nicolas decided on 2026-10-11 that every value of every dataset has an `available_ts`, the moment it could have been
known. A decision at `decision_ts` may use only values with `available_ts <= decision_ts`. All data reaches a strategy
through one point-in-time context (`so.core.point_in_time.DataContext`). In the holdout runner, designs can read data
only through it, so the whole-session cut and the perturbation check cover every source. Every source must be
registered, with its timestamp convention, its availability rule (with evidence) and its revision policy, before a
design can use it. When the evidence is unclear, the later time is the one used. Labels may look forward. A model
trained at time t uses only rows whose `label_known_ts` is before t.

The IBKR 1-minute label is the bar start. Observed: SPY 2005-01-03 has 390 bars from 09:30 through 15:59, and the half
day 2005-11-25 has 210 bars from 09:30 through 12:59. `available_ts` is one minute after the label, so the 15:58 bar is
knowable at 15:59:00. That is the decision moment; the fill is the open of the next bar, as in
`so.features.daily_features`. VIX 2005-10-03 runs 09:31 through 16:14 and VIX3M 2009-08-12 runs 09:31 through 15:59.
The inventory says that convention is not proven, so the same later rule is used. VIX-family daily bars are a midnight
label (observed 2005-10-03) and are knowable at 16:15 New York on that date. A same-day VIX close is therefore after
the 15:58 decision. The previous session's close (`vix_level_prev`) is not.

No experiment was run, no holdout window was opened, and no trial-log row was added. The rolling-retrain module is
still not built. When it is, it will use `available_ts` and `label_known_ts` from this module.

## Methodology note (2026-10-12): rolling retraining built

*Correction, not a replacement, of the 2026-10-11 note above.* On 2026-10-12 the shared module was built on
`agent/rolling-retrain`, branched from `main` `62cad32`. That `main` contains `so/core/holdout.py`
(`get_perturbed_ohlcv_dict`) and `so/core/point_in_time.py` (`DataContext`, `available_ts`, `label_known_ts`).
Nicolas's decisions of 2026-10-11 are the rules the module implements.

A model-based design is a walk-forward with a rolling training window (`so.core.rolling_retrain`). It refits on a
pre-registered schedule. The default is weekly: the first session of each calendar week, so a Monday holiday is a
Tuesday refit, and the first session of the decision span is always a refit. Changing the frequency after a result is
a new version. One optional pre-registered comparison of weekly against quarterly is allowed. The default
training-window candidates are 6 months, 2 years and 10 years (`so.config`). The candidate in force for a quarter is
chosen from the last 4 completed quarters before that quarter, prior-only, as in exp02–exp13. A tie takes the longer
training window.

A row dated after the retraining day is outside the window. A training row must also have `label_known_ts` strictly
before that day's decision bar. When the label source is the registered TSBAR source, that clock comes from
`so.core.point_in_time`. Otherwise a barrier label is knowable at the end of the bar where the target or the stop was
hit, or at the end of the horizon bar, and a fixed-horizon label is knowable at the decision moment of the session
that many sessions later. Unfinished labels are dropped and counted as purged. They are never filled with 0 or any
other value. Features are read through `DataContext` and checked with `check_feature_available_ts`.

`so.core.evaluation` now also reports the path over time: cumulative log excess, rolling 63-session and 252-session
excess return, the drawdown of the strategy and of buy-and-hold, and a per-quarter table; turnover per year (the sum
of absolute weight changes, scaled by 252 / session count), the number of trades, and candidate switches per year with
the share of time each candidate was in force. The refit log reports average rows used, the share purged, and how far
predictions moved between consecutive refits.

The holdout runner's definition is unchanged. The design's own replay calls the walker, and the runner continues the
frozen prior-only path through the holdout. A valid run saves the holdout segment of the refit log next to the daily
paths, under `SO_HOLDOUT_PATH` only. The ledger row adds the retraining frequency, the training-window candidates, the
number of refits in the holdout, the average share purged, turnover per year, and the number of candidate switches.

The template (`experiments/_template`) is an example, not an experiment: a logistic regression on two daily features,
a fixed horizon of 20 sessions, weekly refits, candidates 6M/2Y/10Y, pooled selection over 4 quarters. It does not
pre-register the weekly-versus-quarterly comparison. No experiment was run, no holdout window was opened, and no
trial-log row was added. Archived experiments exp01–exp13 are unchanged. A daily-feature, weekly-retrained version of
exp02's re-entry model is a natural first user; proposed, waiting for Nicolas.

## Methodology note (2026-10-12, Nicolas): replace every experiment under the current rules

Decided by Nicolas on 2026-10-12. Each experiment folder is replaced in place by a version 2.0 that keeps the old
protocol's rules, complete candidate grid, selection rule, tie order, baselines, costs, success criteria and stopping
rules, and changes only the evaluation machinery: the development boundary comes from the registered holdout window;
data is read through the point-in-time `DataContext` with a declared `DATA_SOURCE_LIST`; the design uses the
`so.core.holdout` interface; and the model-based experiments (exp01, exp02) retrain weekly (`so.core.rolling_retrain`)
with their original training-window candidates and label definitions, purging rows whose `label_known_ts` is not yet
known. Nothing is tuned and no rule is added.

The order is exp02, exp03, exp04, exp05, exp06, exp07, exp12, exp13 (as the frozen E1M1 rule), exp01. exp08 is removed
(it is a signal check, not a strategy). exp09–exp11 stay in the registry text as "skipped, never built". The legacy
code and notebook outputs are not kept in the workspace; they stay in git at tag `pre-port-20261012`. The old results
stay in this log. The old saved outputs stay in the data folder. `scripts/reproduce_archived.py` and its test were
removed in the exp02 v2 recording session: the checker read notebooks from the working tree, and those notebooks now
live only at tag `pre-port-20261012`. `records/archived_reproduction_expected.csv` stays. The check is not run.

Every new version is labelled **re-run under the new rules, not new evidence**: the old version already used this
data. No holdout evaluation is run by the agent. The exp05 version is prepared so Nicolas can run an end-to-end
evaluation himself. No further version may follow from these results.

## Port queue, 2026-10-13 (development finished; calibrations and exp01 did not)

The queue in `logs/port_queue_status.csv` ran from 2026-10-13T01:01:15 to 2026-10-13T06:17:33. `logs/port_queue.err` and `logs/port_queue.out` are empty. Trial-log counts below are from `read_trial_log_pdf()` on 2026-10-13. Headline returns of the six finished development notebooks are in those notebooks and are not copied here.

| Experiment | Development | Validation rows | Summary rows | Note rows |
|---|---|---:|---:|---:|
| `exp04_trend_exit_v2` | finished 01:01:15–02:16:52 | 369 | 1 | 0 |
| `exp05_vol_scaled_exposure_v2` | finished 02:17:19–02:49:47 | 164 | 1 | 0 |
| `exp06_capped_regret_reentry_v2` | finished 02:50:14–04:28:41 | 492 | 1 | 0 |
| `exp07_warning_lights_exit_v2` | finished 04:29:07–04:54:09 | 123 | 1 | 0 |
| `exp12_vix_fear_reentry_v2` | finished 04:54:35–05:59:48 | 246 | 1 | 0 |
| `exp13_e1m1_robustness_v2` | finished 06:00:15–06:09:50 | 41 | 1 | 0 |
| `exp01_minute_entry_v2` | failed 06:10:17–06:17:33 | 0 | 0 | 0 |

**Calibrations.** All six failed after about 27 seconds with the same `TypeError: tuple indices must be integers or slices, not str` in `get_replay_return_float` (`row_in["valid_start"]`). `DataFrame.itertuples` returns a named tuple. No calibration reached `log_trial_dict`, so none wrote its note row. Logs: `logs/exp04_trend_exit_calibration_20261013_0216.log`, `logs/exp05_vol_scaled_exposure_calibration_20261013_0249.log`, `logs/exp06_capped_regret_reentry_calibration_20261013_0428.log`, `logs/exp07_warning_lights_exit_calibration_20261013_0454.log`, `logs/exp12_vix_fear_reentry_calibration_20261013_0559.log`, `logs/exp13_e1m1_robustness_calibration_20261013_0609.log`.

A one-quarter probe of exp04 after the tuple fix, fold 0 candidate `0.00|1`, bounds 2015-04-17 → 2015-07-16, called `get_replay_return_float` and did not call `log_trial_dict`. The return was `nan`. The trial log stayed at 6,448 rows and `exp04_trend_exit_v2` still had 0 note rows. The quarter is not a development period. Development periods in that load run 2015-03-19 → 2015-06-18 through 2025-03-19 → 2025-06-18 (41 periods). The archived quarters run 2015-04-17 → 2015-07-16 through 2025-04-17 → 2025-07-16 (41 quarters). Zero start dates coincide. The calibration leaves a non-matching quarter unmatched and does not substitute a fresh window. A re-run will therefore compare 0 rows and then log one note. That note is the script's "run once" lock.

*Correction 2026-10-13, before the queue was relaunched.* The paragraph above describes the shared-bound gate, which is not the old-bounds check. `scripts/calibrate_port_old_bounds.py` now replays each candidate with the version 2.0 code on the archived bounds, as a slice of one continuous path (the same score the archived runs stored). Quarters that end on or after the development end are dropped before the replay. The bars start in 2005, so the moving average, the volatility and the VIX features are known at the first decision; they are read through the point-in-time context. A comparison of 0 rows, or any nan, raises and writes no note row. A one-quarter check of 2015-04-17 → 2015-07-16, with the path continued through the next quarter so that quarter is not liquidated, matched the archived returns and wrote no trial-log row (the log stayed at 6,448). The check is `get_one_quarter_match_dict`. Counts are matches within `NUMERIC_TOLERANCE` (1e-6), and the maximum absolute difference:

| Experiment | Returns matched | Max absolute difference |
|---|---:|---:|
| exp04 | 9/9 | 2.21e-17 |
| exp05 | 4/4 | 3.47e-18 |
| exp06 | 12/12 | 7.29e-17 |
| exp07 | 3/3 | 6.51e-17 |
| exp12 | 6/6 | 2.21e-17 |
| exp13 | 1/1 | 2.21e-17 |

The full old-bounds calibration was not run. No note row was written.

*Correction 2026-10-14.* The second queue (`logs/port_queue_status.csv`, 12:16–17:15) skipped the six finished development runs and finished each old-bounds calibration. Each wrote one note row. Those development notebooks were not run again. exp04 is recorded in `exp04_trend_exit_v2`. exp05 is recorded in `exp05_vol_scaled_exposure_v2`. exp06 is recorded in `exp06_capped_regret_reentry_v2`. exp07 is recorded in `exp07_warning_lights_exit_v2`. exp12 is recorded in `exp12_vix_fear_reentry_v2`. exp13 is recorded in `exp13_e1m1_robustness_v2`.

**exp01.** `logs/exp01_minute_entry_development_20261013_0610.log`. The notebook was saved with the error. Cell 4 calls `run_development_dict()`, which calls `get_development_data_context`, which loads TSBAR. `add_tsbar_label_known_ts_pdf` raised `ValueError: TSBAR needs label_known_ts or exit_ts`. The stored cells are `exit_bar_count|exit_price|exit_reason` plus `entry_ts`. No `exp01_minute_entry_v2` row was logged (0 validation, 0 summary, 0 note). Nothing was deleted. The run was not repeated. The clock is now the end of the latest stored exit bar; an unresolved cell stays unfinished. That does not change the grid, the thresholds, the windows, the costs, the baselines, the selection rule, or the stopping rule. Protocol 2.0 change log, 2026-10-13.

## How to add an entry

For every notebook run: date, experiment and step, protocol version, config hash (printed in the header cell), the trial-log
entries added (stage and count), the headline numbers (copy them from the saved outputs), and what they support. For
walk-forward runs, always report: the best candidate after the fact (labelled optimistic), the **prior-only path** with its
minimum detectable effect, the **information test** (model vs its uninformed baselines), and time in the market.

## Summary

| Experiment | Protocol | Status | One-line outcome |
|---|---|---|---|
| `exp01_minute_entry` | 1.0 (1.1: step 04) | **STOP** (2026-10-06) | Signal check: 2 signal bins vs null max 4, p = 0.10 → STOP. Walk-forward (run before the verdict): prior-only +146.94% vs buy-and-hold +218.48%. Step 04 diagnostic (multivariate, added after the results): mean AUC 0.4943 vs null max 0.5282, p = 0.75, no information (Outcome A) |
| `exp02_stop_reentry` | 1.0 | **STOP** (2026-10-05) | 0 signals; prior-only +111.66% vs +237.21%; the model's re-entry is worse than all 20 random re-entry runs |
| `exp02_stop_reentry_v2` | 2.0 | **STOP** (2026-10-12) | Re-run under the new rules, not new evidence. Prior-only +61.82% vs +199.04% over 41 development periods. Below buy-and-hold and below every saved baseline |
| `exp03_ath_exit` | 1.0 | **STOP** (2026-10-05) | Prior-only +143.05% vs +237.21%; beats random exits (19/20) but loses to random buy-backs (19/20 beat it) |
| `exp03_ath_exit_v2` | 2.0 | **STOP** (2026-10-12) | Re-run under the new rules, not new evidence. Prior-only +111.12% vs +199.04% over 41 development periods. Beats random exits (20/20) and loses to random buy-backs (1/20) |
| `exp04_trend_exit` | 1.0 | **STOP** (2026-10-06) | Continuous replay: prior-only +70.84% vs +229.74%; all 12 exits bought back higher; beats 0/20 random exits and 4/20 random re-entries |
| `exp04_trend_exit_v2` | 2.0 | **STOP** (2026-10-14) | Re-run under the new rules, not new evidence. Prior-only +41.51% vs +199.04% over 41 development periods. Below buy-and-hold and below both random medians |
| `exp05_vol_scaled_exposure` | 1.0 | **STOP** (2026-10-06) | Signal check passes (ρ 0.593); prior-only +165.69% vs +229.74% (mean weight 86.3%); constant exposure +198.52%, beats 3/20 random shifts; drawdown −23.20% vs −34.21% |
| `exp05_vol_scaled_exposure_v2` | 2.0 | **STOP** (2026-10-14) | Re-run under the new rules, not new evidence. Prior-only +142.59% vs +199.04% over 41 development periods. Below buy-and-hold, the constant exposure, and the random-shift median (5 of 20) |
| `exp06_capped_regret_reentry` | 1.0 | **STOP** (2026-10-06) | Data-dependent follow-up of exp03. Prior-only +147.38% vs +229.74%; information test passed (beats 19/20 random exits, 15/20 random re-entries) but 37 of 45 exits ended on the buy-stop |
| `exp06_capped_regret_reentry_v2` | 2.0 | **STOP** (2026-10-14) | Re-run under the new rules, not new evidence. Prior-only +132.25% vs +199.04%. Beats both random medians (18/20 exits, 15/20 re-entries) and loses to buy-and-hold |
| `exp07_warning_lights_exit` | 1.0 | **STOP** (2026-10-06) | Exploration: k = 5 +136.41% vs +69.02% (one 2008 exit). Validation: every k loses (best k = 4 +115.60% vs +235.39%); prior-only +49.09% vs +229.74%, all 12 exits bought back higher; beats 0/20 random exits, 7/20 random re-entries |
| `exp07_warning_lights_exit_v2` | 2.0 | **STOP** (2026-10-14) | Re-run under the new rules, not new evidence. Prior-only +40.95% vs +199.04%. Beats 0/20 random exits and 18/20 random re-entries |
| `exp08_vix_signal_check` | 1.0 | **DONE, VIX line STOP** (2026-10-09) | Gate: G1 0 signal bins (null max 0, p = 1.00); G2 dAUC +0.0359 vs null max +0.0563 (p = 0.15); G3 PASS (D +0.1165 [+0.0441, +0.2227]); G4 FAIL (top VIX quintile mean forward return +1.91% / +2.82%). No gate opens: exp09-exp11 skipped |
| `exp09_vix_reentry`, `exp10_vix_vol_scaled_exposure`, `exp11_vix_model_exit` | — | **SKIPPED** (2026-10-09) | Not run, by exp08's pre-registered gates (exp09 needs G1 or G2, exp10 G3 and G4, exp11 G2) |
| `exp12_vix_fear_reentry` | 1.0 | **STOP** (2026-10-09) | Data-dependent follow-up of exp08 (Nicolas), exp09's rules. Prior-only +119.24% vs +229.74% (log excess −3.77%/yr [−7.95%, −0.37%]); unmodified path +82.88%; beats 0/20 random exits, 13/20 random re-entries. Optimistic best E1M1 +314.80% vs +235.39%. VIX line closed |
| `exp12_vix_fear_reentry_v2` | 2.0 | **STOP** (2026-10-14) | Re-run under the new rules, not new evidence. Prior-only +126.51% vs +199.04%. Beats the unmodified path and loses to the random-exit median (1/20). VIX line stays closed |
| `exp13_e1m1_robustness` | 1.0 | **E1M1 IS NOT ROBUST** (2026-10-09) | Data-dependent robustness of exp12's after-the-fact E1M1. R1–R4 fail, R5 holds. Stress +53.32% vs +73.09%; 11/36 variants beat B&H on DEV, 3/36 on STRESS; p2 = 0.088; without the best episode equity ratio 0.9775. Delayed +306.15% and 5-cent +310.85% still beat +235.39%. VIX line closed |
| `exp13_e1m1_robustness_v2` | 2.0 | **candidate pending review** (2026-10-14) | Re-run under the new rules, not new evidence. Frozen E1M1 prior-only +273.85% vs +199.04%. Beats the printed baselines. The 6-month interval contains 0. Not a success claim. Protocol 1.0 robustness was not re-run |
*Corrections 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`), for the rows above:*
- *exp05 (I3): "constant exposure +198.52%" is not a constant exposure: with the 20-point dead band it never rebalanced,
  so it is "**buy 86.3% and hold**" (mean weight 90.9%). The verdict rests on buy-and-hold and the random shifts (the
  path beats 3/20).*
- *exp06 (I2): "information test passed" holds as the protocol defined it (beat both medians), but beating 19/20 random
  exits (empirical p ≈ (1 + 1) / 21 ≈ 0.10) and 15/20 random re-entries (p ≈ 0.29) is "consistent with weak timing
  information; not statistically supported" (data-dependent design, 12 candidates, about 7,400 trials).*
- *exp07 (I4): "all 12 exits bought back higher" = 11 closed episodes, all bought back higher, plus 1 episode open at
  the end (valued at the last close, also higher).*

## Reproduction checks for the re-run

The trading rules of exp01 and exp02 and the exp03 exploration rules are unchanged, and every run is deterministic, so the
re-run must reproduce these earlier numbers (corrected data). A difference means something changed in the data or the code.

| Notebook | Expected | Nicolas's run (2026-10-05/06) |
|---|---|---|
| exp02 step01 | buy-and-hold 2005-2014 +69.02% (Sharpe 0.36, drawdown −56.44%); k = 4 with a 5-day delay +62.91%; 200-session rule +50.39% | reproduced |
| exp02 step03 | 18 candidates from +53.8% to +229.7% vs +243.4% chained buy-and-hold; mean AUC logistic 0.523 (10y) / 0.470 (all); prior-only path +111.66% vs +237.21%, 20 of 43 quarters | reproduced |
| exp02 step02 | 0 signals (the verdict cannot change with the month minimum: no bin passed training in v2) | reproduced |
| exp03 step01 | buy-and-hold +69.02%; 5 of 15 rules above it; best: within 0.5%, 5% dip, +80.69% (+11.68 pts) | reproduced |
| exp01 step03 | validation candidates identical to `lgbm_ev_policy_v1_clean` (best setting +158% vs +230%; at most 16 of 45 quarters) | reproduced (+158.08% vs +230.36%; at most 16 of 45) |
| exp01 step02 | new result (base-rate check); the old break-even check found 1,339 training passes and 0 signals | new result, below; the first run (hash `16493e598a`) and the re-run show the same real-check counts (5,628 / 174 / 4; confirmed by the agent on 2026-10-06 from commit `da790c1`) |
| exp03 step02 | first official run; the assistant's sandbox run gave +143.05% | identical (+143.05%) |

*SPY raw folder rename check (agent, 2026-10-09; roadmap 2026-10-09 step 0.3; no trial-log entry).* The SPY raw folder
is `store01_rawzone/ibkr_spy_1min/` (`so.paths` on `main`, verified at `a4418d8`; `so/paths.py` last changed in
`1bbb0de`).
`scripts/check_spy_rename.py` (run once, branch `agent/research`) reads it through `so.core.raw_data`, collects the
session dates, then cuts the bars at 2026-04-15 before any computation. Console output: (a) 5,436 sessions,
2005-01-03 → 2026-08-13; (b) buy-and-hold 2005-2014 **+69.02%**, 200-session rule **+50.39%**; (c) exp04 x = 0, n = 1
continuous replay 2015-04-17 → 2026-04-15 **+108.03% with 35 exits**, buy-and-hold **+235.39%**: "RENAME CHECK: PASSED
(6 of 6 checks)", every value equal to the earlier records at 2 decimals of a percent. The repository search for
`ibkr_ohlcv_data` / `ibkr_SPY_ohlcv_data` finds, besides the dated note of `docs/RERUN_GUIDE_2026-10-05.md` and files of
`docs/history/`, only `records/bad_tick_corrections.csv`, whose `backup_path` column records the backup folder created on
2026-10-04 under the old name: a dated record of a past action, left unchanged (no code reads it).

*Verification run by the assistant (2026-10-05).* To test the reorganized code, the assistant executed pipeline steps 00
and 06 and the notebooks of exp02 (steps 01-03) and exp03 (steps 01-02) once, in its sandbox, on a copy of the same
corrected raw data. The exp02 and exp03 exploration numbers above were reproduced exactly. That run also produced the first
exp03 walk-forward and the new validation baselines, so those results were seen by the assistant before Nicolas's official
run; no rule, grid or baseline was changed afterwards. exp01 was smoke-tested on synthetic data only (a 2010-2022 random
walk with random indicator columns, so no real result was seen). That smoke test showed that the exp01 base-rate signal
check, with the uncalibrated rule, returns CONTINUE on data without any signal (2 signals in one bin of 3,255 tests, about
4 expected by chance). The verdict was therefore calibrated on 19 session-shifted null runs
(`experiments/exp01_minute_entry/PROTOCOL.md` §13; decided 2026-10-05, delivered in the second zip of that day).
Nicolas's first real run of step 02 (first zip, config hash `16493e598a`) still used the uncalibrated rule; the calibrated verdict comes from re-running step 02 with the second zip (hash `15716b01a3`), whose real-check part must reproduce the first run's signal table exactly. On the same synthetic data, the null runs found 0-4 distinct signal
bins (15 of 19 runs found at least one), so the real check's 1 bin gives p = 0.80 and the calibrated verdict is STOP, as
it should be. Run time in the sandbox (2 cores): real check 2.0 min, null runs 13.9 min.

## Decisions of 2026-10-05

Taken by Nicolas on 2026-10-05, in reply to the open points of the reorganization, and delivered in the second zip of
that day. Nicolas ran exp01-exp03 with the **first** zip, so those executed notebooks predate the code of these decisions:
the exp02 and exp03 notebooks print both secondary flags (the "either" criterion is read from them; no re-run), and the
exp01 signal check is re-run once to add the null runs (`docs/UPDATE_GUIDE_2026-10-06.md`).

| Decision | Applies to | Why |
|---|---|---|
| The exp01 signal-check verdict is calibrated on 19 session-shifted null runs: CONTINUE only if the real check has more distinct signal bins than every null run | exp01 step 02 | The uncalibrated rule ("at least one signal") passed a synthetic random walk; Nicolas asked for the most reasonable fix, the assistant recommended this one |
| The random exit and 200-session trend baselines are kept | exp03 | Random exit tests the ATH exit signal itself; the trend rule is context only |
| Secondary criterion: higher Sharpe **or** smaller drawdown (either is enough), at a comparable return | all experiments (`so/core/evaluation.py`) | Audit F7 left "and" or "or" open; Nicolas chose "or" |

## Decisions of 2026-10-06

| Decision | Applies to |
|---|---|
| exp01, exp02 and exp03 are stopped under their protocols (results below). No test window is evaluated for them. | exp01-exp03 |
| Next family: "stay invested, exit rarely": strategies that maximize time in the market and exit only on strong evidence, with explicit re-entry rules, on the features that already exist; VIX afterwards, text/qualitative data last | `docs/RESEARCH_STATE_2026-10-06.md` |
| **Primary success criterion of the next family: beat buy-and-hold's total return** (after costs, on the prior-only path; on the test windows once frozen). Nicolas, 2026-10-06 | all new experiments |
| Experiment numbering: the VIX experiment, earlier planned as exp04, moves after the new family | `experiments/README.md` |
| The research continues with a Cursor agent on nicodesktop, under `AGENTS.md` and `.cursor/rules/` | workflow |

## exp01_minute_entry

**Protocol 1.0. Status: STOP at the signal check.**

*Step 01, model dataset* (2026-10-05, hash `16493e598a`). 5,436 daily files (2005-01-03 → 2026-08-13), 33 model
features (absolute-dollar features excluded).

*Step 02, signal check.* First run 2026-10-05 15:17 (hash `16493e598a`, uncalibrated rule: it would have printed
CONTINUE because 4 signals > 0). Re-run with the null calibration 2026-10-06 12:46 (hash `15716b01a3`); both entries are
in the trial log.
- Windows: training 2015-04-16 → 2025-04-15 (60,144 sampled rows); validation = folds 41-44 pooled
  (2025-05-01 → 2026-04-29, 5,964 rows). The latest test window (2026-05-14 → 2026-08-13) was not read.
- Base rates (training): TP-first rate 49.8% at 0.10% rising to 53.3% at 0.50%, then falling to 50.8% at 1.00%; the
  small tilt above 50% is SPY's drift.
- 5,628 tests (33 features × 21 distances × bins); 174 training passes (281 expected by chance at 5%); **4 signals in
  2 distinct bins** (7.0 expected if tests were independent):
  - `intraday_return_pct` in (0.37%, 0.64%], distances 0.13%-0.16%: TP rate 52.9-54.2% vs base 50.1-50.6% on training,
    validation lift +8.6 to +10.1 points (2 of the 3 also above break-even on validation);
  - `prev_day_range_pct` in (1.52%, 2.08%], distance 0.18%: below the base rate (48.9% vs 50.8% on training; validation
    lift −7.3 points).
- **Null calibration:** 19 session-shifted runs found `[1, 0, 0, 1, 0, 1, 1, 1, 0, 4, 0, 0, 1, 1, 0, 1, 1, 0, 1]` distinct
  signal bins (10 of 19 runs ≥ 1). The real 2 bins do not exceed the null maximum of 4: **p = 0.10 → STOP.**
- Reading: the two bins are suggestive (intraday momentum on very tight brackets; fewer TP hits after wide-range days)
  but not established. The validation lift is about three times the training lift, a typical sign of noise in small
  samples (about 600 overlapping rows per validation bin).
- *Reproduction confirmed (agent, 2026-10-06; research state open item 1, closed).* The first run's executed notebook
  (commit `da790c1`, message `first-run-20261006`; there is no git tag of that name, the label is the commit message),
  cell 6 output: `test_count 5628`, `train_pass_count 174`, `signal_count 4`, `signal_bin_count 2`, signal features
  `['intraday_return_pct', 'prev_day_range_pct']`, distances `[0.0013, 0.0014, 0.0016, 0.0018]`, verdict `CONTINUE`
  (uncalibrated rule). The re-run (hash `15716b01a3`, cell 7) prints the same seven values, then the null calibration
  and `STOP`. The two `signal_check` entries of the trial log (2026-10-05T15:17:38 `16493e598a` and 2026-10-06T12:46:46
  `15716b01a3`) hold the same counts. The real-check part is reproduced; the verdict STOP stands. No trial added.

*Step 03, walk-forward* (2026-10-05, hash `16493e598a`; run before the step 02 verdict existed, as the re-run guide ran
every notebook in order: these results are reported as **run past the stopping rule**). 45 folds × 12 candidates = 540
validation trials + 1 summary.
- After the fact (optimistic): best setting 3 years / threshold 0.05%, +158.08% vs +230.36%; no setting beats
  buy-and-hold; at most 16 of 45 quarters won.
- **Prior-only path (44 quarters): +146.94% vs buy-and-hold +218.48%** (8.6%/yr vs 11.1%/yr); 15 of 44 quarters won
  (sign test p = 0.989); mean excess −0.56% per quarter (SD 3.38%, t = −1.11); minimum detectable effect 1.43% per quarter
  (about 5.7% per year).
- Exposure 88.1%; zero-skill reference at that exposure +177.41%. Random entries of matched activity (median of 20)
  +124.55%; the model beats 16 of 20 runs (empirical p ≈ 0.24); fixed 10:00 entry +18.87%.
- Reading: the stop/target machinery with costs loses about 50 points against passive exposure; the model recovers about
  22 of them. Not evidence of an edge over buy-and-hold.

*Step 04, multivariate signal check (diagnostic; protocol 1.1, §13.3; decided by Nicolas 2026-10-06 after exp01's
results).* **exp01 stays STOPPED**: this check was added after the results were known and cannot reverse the STOP or
restart the walk-forward. Pre-registration commit `ae15c20` (2026-10-06 18:21:47 +0300); run once, 2026-10-06 (agent,
nbconvert in the background), config hash `1ea6cfdc0a`; **1 trial added** (stage `multivariate_check`, trial
`20261006182748398278_1ea6cfdc0a`, logged 2026-10-06T18:27:48; trial log 3,292 → 3,293). Source of every number below:
the saved outputs of `experiments/exp01_minute_entry/step04_multivariate_check.ipynb` and the CSV files of
`store04_experiments/exp01_minute_entry/step04_multivariate_check_data/`.
- Windows (asserted identical to the step 02 entry `20261006124646690847_15716b01a3`): training 2015-04-16 → 2025-04-15
  (60,144 rows), validation folds 41-44 pooled 2025-05-01 → 2026-04-29 (5,964 rows). Last row and last bar loaded:
  2026-04-29; the untouched window (from 2026-05-14) was not read. 33 features, 21 distances (0.10%-1.00%), exp01's
  LightGBM (`LGBM_PARAM_DICT`, uniqueness weights, `n_jobs` = 1), one classifier per distance, trained on training only.
- **Primary statistic: mean AUC over the 21 distances = 0.4943.** The 19 null runs (features shifted by whole sessions,
  models retrained): `[0.5050, 0.4960, 0.4876, 0.4959, 0.5058, 0.5259, 0.4989, 0.5049, 0.5047, 0.4869, 0.5282, 0.4851,
  0.5215, 0.5151, 0.5014, 0.5045, 0.4867, 0.4946, 0.4694]` (max 0.5282). 14 of 19 null runs are ≥ the real value:
  **p = (1 + 14) / 20 = 0.75 → no information → Outcome A.** No distance clears break-even (the top-decile lower bound is
  below the top decile's mean break-even TP rate at all 21 distances), so outcome B or C would not have applied either.
- Per distance (descriptive; not part of the verdict and **chosen after the fact** when singled out):
  - Small distances 0.10%-0.14%: AUC 0.516-0.535, above all 19 null runs at each of these 4 distances; top-decile lift
    +1.9 to +6.6 points. The best (optimistic) one, 0.14%: AUC 0.5346 [0.5073, 0.5620], top-decile TP rate 56.7%
    [49.2%, 64.2%] vs a mean break-even of 51.4% (point estimate above break-even, lower bound below: does not clear).
  - 0.16%-0.25%: AUC 0.515-0.520, inside the null range (1-6 null runs ≥ real); no top-decile lower bound above 50%.
  - 0.28%-0.71%: AUC 0.469-0.516, inside the null range.
  - Large distances 0.79%-1.00%: AUC 0.437, 0.428, 0.406, **below all 19 null runs**; the top decile hits TP 36.6%,
    32.1%, 31.2% vs base rates 47.4%, 47.0%, 47.6% (lift −10.9 to −16.4 points; at 0.89% and 1.00% the whole 95% interval
    of the lift is below zero). The models trained on 2015-2025 rank validation rows **in the wrong order** there.
  - 11 of 21 distances have AUC > 0.5; mean top-decile lift −1.4 points (null runs: −4.1 to +6.2).
- Calibration (deciles of predicted P(TP), per distance, pooled over the 21 distances): mean predicted P(TP) rises from
  41.6% (decile 1) to 59.7% (decile 10), the observed TP rate stays flat between 48.2% and 50.8% and is **lowest in the
  top decile** (48.2%). The predicted spread of about 18 points is not realized at all.
- Split-gain importance (mean share of total gain over the 21 models, top 10; descriptive, what the models used):
  `prev_day_return_pct` 9.4%, `overnight_gap_pct` 9.1%, `prev_day_range_pct` 8.2%, `daily_volatility` 8.1%,
  `intraday_return_pct` 7.4%, `ath_drawdown_pct` 7.1%, `prev_day_high_dist_pct` 6.1%, `prev_day_low_dist_pct` 5.4%,
  `prev_seg_delta_pct` 3.9%, `day_of_week` 3.5%. Eight of the ten are daily context features (constant or slowly varying
  within a session).
- *Mathematically.* For each distance d the AUC is P(p̂(x_i) > p̂(x_j) | y_i = TP, y_j = not TP) on the validation rows
  (0.5 = ranking no better than a coin). The statistic is A = (1/21) Σ_d AUC_d. Under the null hypothesis "the features
  carry no information about which barrier is hit first", shifting the feature rows by whole sessions against the labels
  gives exchangeable copies of A that include the model's flexibility and the overlap of minute labels; the real
  A = 0.4943 ranks 15th of 20 (p = 0.75), so the null is not rejected. The rejection rule would have needed A > 0.5282.
  The calibration table shows that the model's probabilities have a spread (standard deviation of the 10 decile means of p̂ = 4.95
  points, computed by the agent from `calibration_data.csv`) that the outcomes do not follow (standard deviation of the
  10 observed TP rates = 0.92 points), i.e. the in-sample relation does not transfer.
- *In plain words.* Giving the model all 33 features at once, so that it can combine them ("A high **and** B high"),
  does not help: on the validation year it ranks future TP-first outcomes no better than models trained on features
  deliberately misaligned in time (it does worse than 14 of those 19). There is a faint ordering at the very tightest
  brackets (0.10%-0.14%), too small to pay the costs, and a clear **reversal** at the widest brackets (what predicted a
  TP hit in 2015-2025 predicted the opposite in 2025-2026). The models lean mostly on day-level context (yesterday's
  return and range, the overnight gap, volatility), so they learn about one value per day; ten years give only about
  2,500 such values, and the day-level regimes they found did not persist.
- **What it supports:** the step 02 STOP was not caused by testing features one at a time; the combination of the 33
  features carries no out-of-sample information on TP-first beyond chance and flexibility, under exp01's model, on these
  windows. The exp01 failure is consistent with "no exploitable signal in these features at minute horizons" rather
  than with "a signal the univariate check could not see".
- **What it does not support:** it does not show that no model or feature set could work (one model, fixed
  hyperparameters, one 10-year training window, no walk-forward); the small-distance AUCs above the null and the
  large-distance reversal are per-distance observations chosen after the fact among 21 (both tails), on reused
  validation quarters, and are not evidence of anything without a new pre-registered test; the reversal is an inference
  about non-stationarity, not tested. The motivation of the check is data-dependent; the conclusion rests on 1 trial of
  this check after 3,292 earlier workspace trials and 4,089 legacy trials.
- Status: **diagnostic complete, Outcome A; exp01 remains STOPPED.** No parked decision (no outcome C).

## exp02_stop_reentry

**Protocol 1.0. Status: STOP.** Run 2026-10-05 14:47-14:50, hash `53a86cd30f` (14 exploration, 1 signal-check, 792
validation and 1 summary trials).
- Step 01 (2005-2014): reproduced (above). Selling at S and buying back at R gives S/R times the shares: the next-day
  buy-back bought back lower in 41% of 150 episodes (k = 4), mean share gain −0.21%; the hindsight oracle +4.79%.
- Step 02: 0 of 80 tests pass even on training (4.0 expected by chance) → STOP.
- Step 03, **prior-only path (43 quarters): +111.66% vs +237.21%** (7.2%/yr vs 12.0%/yr); 20 of 43 quarters won
  (p = 0.729); mean excess −1.13% per quarter (SD 4.20%, t = −1.76); MDE 1.79% per quarter (about 7.2% per year); time in
  cash 21.2%. Comparable return, Sharpe and drawdown flags all False (secondary criterion not met under "and" or "or").
- Baselines on the same quarters: stop + next-day buy-back +245.34%, + 5-day +240.45%, + 20-day +152.14%; random
  re-entry (median of 20) +159.63% — **the model beats none of the 20 random runs**; 200-session trend +106.16%.
- Reading: the stop itself costs little (stop + next-day buy-back ≈ buy-and-hold); the losses come from waiting in cash,
  and the model's waiting is worse than random (consistent with a mean validation AUC of 0.470 for the all-history window).

## exp02_stop_reentry_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Pre-registered in commit `4ff407a`
(2026-10-12 14:05:49 +0300), before any trial of this name. Config hash `5e7f583681`. One development run, 2026-10-12T16:43:23:
738 validation trials and 1 summary (739), note `re-run under new rules`, `test_window_touched` false on every row. The
protocol's budget (protocol §5, `TRIAL_BUDGET`) is 18 × 44 + 1 = **793**. Recounted from `trial_log.csv` on 2026-10-12:
738 rows with stage `validation` and 1 row with stage `summary`, 739 in total, every row `logged_ts`
2026-10-12T16:43:23, `test_window_touched` false. The development span has 41 periods, so 18 × 41 + 1 = 739. The run is
inside the budget. It was not repeated. The signal check and the mechanism check of protocol 1.0 were not re-run.

The executed notebook has no saved outputs. nbconvert stopped at the last cell (`logs/exp02_v2.err` ends with
`TypeError: get_trial_count_pdf() missing 1 required positional argument`) and did not write
`step01_development.ipynb`. The evidence is the CSVs in
`store04_experiments/exp02_stop_reentry_v2/step01_development_data/` (written at 16:43:23, the same timestamp as the
trial rows) and those 739 trial-log rows. The corrected last cell reads the trial log and passes that frame to
`get_trial_count_pdf`. It was not executed. A second execution would append another 739 trials, so the run stays as it is.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** From `summary_data.csv`,
`period_data.csv` and `performance_over_time_data.csv`.
- **Prior-only path: +61.82% vs buy-and-hold +199.04%.** About 4.82% a year vs 11.31% a year, from those two total
  returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market 73.5% (26.5% in cash). 22 of 41 periods beat
  buy-and-hold (sign-test p = 0.378); mean period excess −1.55% (SD 4.70%, t = −2.11); MDE 2.05% per period (8.22% per
  year). Annualized log excess **−5.94%/yr**, 6-month block interval [−11.64%, −0.62%] (124 months). The interval lies
  below 0, so it excludes a gain. The protocol's "supported" flag stays false, because support means the lower bound is
  above 0.
- Sharpe 0.42 vs 0.68; maximum drawdown −21.01% vs −34.21%. These two pairs are `get_success_criteria_dict` applied to
  the saved daily returns (the same function the notebook calls). The drawdown column of the saved performance file has
  the same minima. Comparable return, Sharpe and drawdown flags are all false. Primary success is false. The smaller
  drawdown does not count: the path is not at 90% of buy-and-hold (+179.14% would be required; the path is +61.82%).
- Baselines on the same span, from `summary_data.csv`: fixed delay 1 **+195.30%**, delay 5 **+178.07%**, delay 20
  **+81.54%**; random re-entry median **+122.95%**; 200-session trend **+93.31%**. The path is below every one of them.
  The 20 individual random returns were not written (the save cell drops `random_return_list`) and the notebook print
  was lost with the failed write, so "beats k of 20" is not in the saved files. Being below the median is the information
  comparison the protocol asks for: the model's re-entry does not beat matched random re-entry.
- Optimistic, labelled after the fact: candidate `ALL|4|0.00` chains to **+218.98%**. The same product on the saved
  fresh-window buy-and-hold column is **+198.70%** (`score_data.csv`, the formula in `get_optimistic_dict`). That chain
  is not the prior-only path. The path buy-and-hold is +199.04% because the position is one continuous series; the
  fresh-window chain resets each period. Protocol §8 already says these are not the same object.
- Activity, from `summary_data.csv`: turnover 5.57 per year, 252 trades, 26 candidate switches (2.54 per year).

**Refits, from the code and from `refit_log_data.csv` (539 rows).** The run did use `so.core.rolling_retrain`.
`config.py` sets `RETRAIN_FREQUENCY_STR` to `so.config.RETRAIN_FREQUENCY_DEFAULT_STR`, which is `"weekly"`, and
`TRAIN_WINDOW_CANDIDATE_LIST` to `["10Y", "ALL"]`. `design.get_window_retrain_dict` calls
`run_rolling_retrain_dict` with that frequency and with purging on (`purge_unfinished_label_bool` true).
`get_labelled_row_pdf` sets `label_known_ts` with `get_fixed_horizon_label_known_ts_arr` at the 20-session horizon.
The saved log is the subset `run_prior_only_path_dict` keeps: a model row is written only when that model was used on
a path session. It is not every refit the walker produced. Both windows are in the file (`train_window` and
`candidate` are `10Y` or `ALL` on every row). On each window, the increase in `model_id` between consecutive saved
rows equals the number of ISO weeks between those dates, including the gaps, and no ISO week is repeated. The session
is a Monday, or a Tuesday when that week has no Monday session (10Y: 244 Mondays and 32 Tuesdays; ALL: 239 Mondays
and 24 Tuesdays). That is a weekly schedule. Every row has `rows_purged` = 21, and `last_label_known_ts` is strictly
before `decision_ts`. Each refit drops 21 training rows whose label was not yet knowable.
- Saved refits: **539** (10Y 276, ALL 263). Average rows used **3,163.6**. Mean share purged **0.698%**
  (`rows_purged / (rows_used + rows_purged)`; the pooled share is 0.659%). The same two averages are the
  `summary_data.csv` refit columns (3,163.6 and 0.70% at two decimals). Mean absolute prediction move 0.0037, from
  that summary row.
- First saved refit **2015-04-20** (10Y, `model_id` 477). Last saved refit **2025-07-14** (ALL, `model_id` 1011).
  10Y's saved rows run 2015-04-20 to 2025-04-14 (`model_id` 477 to 998, mean rows used 2,484.3, mean share purged
  0.838%). ALL's saved rows run 2018-01-16 to 2025-07-14 (`model_id` 620 to 1011, mean rows used 3,876.4, mean share
  purged 0.551%). The ids below those first saved values are earlier weekly refits that this path did not use, so
  they are not in the file. 10Y models after 2025-04-14 are in the same position: the path was on ALL, and those
  later 10Y refits were not saved.

**Comparison with the old quarterly exp02, periods that end before the development end.** The development end is
2025-07-17 (`get_development_end_date` for the 20-session embargo). It is the last `valid_end` in v2
`period_data.csv`. Old quarters were read from `exp02_stop_reentry/step03_walk_forward_data/` (`fold_schedule_data.csv`
dates, then `prior_only_data.csv` for the folds that remain). The old schedule has 44 validation quarters. Three of
them end on or after 2025-07-17. Their returns and candidates were not read. Equality of the two paths is not
required: the old number is a fresh window after a quarterly refit, and the v2 number is one slice of the continuous
weekly path (protocol §8).
- v2 period 0, 2015-04-20 to 2015-07-17, ends before the development end. Its continuous-path return is **+1.73%**
  and its candidate is the default `10Y|3|-0.05` (`selection_data.csv`). The old prior-only file has no row for that
  first quarter. The old path starts at the next quarter; the old first quarter was used only to choose it.
- One old prior-only quarter ends on 2025-07-16, before the development end (fold 40, 2025-04-17 to 2025-07-16,
  candidate `all|4|0.00`, fresh-window return **+18.04%**). The v2 period that covers those dates ends on
  2025-07-17, so that pair is not in the table.
- The other 39 quarters overlap on 84 to 91 days, one old fold to one v2 period, no duplicate. The candidate is the
  same window, k and offset on **26 of 39** (letter case ignored: old `10y`, v2 `10Y`). The returns are not equal.
  The same candidate can still diverge, because the position and the refit are not the same object: 2020-07-20 to
  2020-10-16 is `ALL|5|0.05` on both and the returns are −4.53% and +8.68%; 2021-01-19 to 2021-04-16 is `10Y|3|0.05`
  on both and the returns are +6.55% and −0.03%.

v2 return is the continuous path cut by `get_period_return_pdf`'s rule (equity at the period's last session divided
by equity at the previous session, minus 1), from `prior_only_daily_equity_data.csv`. Old return is
`valid_total_return` in `prior_only_data.csv`. Old dates are `valid_start` to `valid_end`. v2 dates are
`period_start` to `period_end`.

| v2 period | v2 candidate | v2 return | old quarter | old candidate | old return | candidate |
|---|---|---:|---|---|---:|---|
| 2015-07-20 to 2015-10-16 | 10Y\|4\|-0.05 | −4.59% | 2015-07-17 to 2015-10-16 | 10y\|4\|-0.05 | −5.18% | same |
| 2015-10-19 to 2016-01-15 | 10Y\|4\|-0.05 | −7.46% | 2015-10-15 to 2016-01-14 | 10y\|4\|-0.05 | −6.32% | same |
| 2016-01-19 to 2016-04-15 | 10Y\|4\|0.05 | −2.54% | 2016-01-19 to 2016-04-15 | 10y\|4\|0.05 | −3.00% | same |
| 2016-04-18 to 2016-07-15 | 10Y\|5\|0.05 | −0.16% | 2016-04-18 to 2016-07-15 | 10y\|5\|-0.05 | +2.94% | different |
| 2016-07-18 to 2016-10-17 | 10Y\|4\|-0.05 | −0.75% | 2016-07-15 to 2016-10-14 | 10y\|5\|0.05 | −1.25% | different |
| 2016-10-18 to 2017-01-17 | 10Y\|5\|0.05 | −0.78% | 2016-10-14 to 2017-01-13 | 10y\|5\|0.05 | +0.49% | same |
| 2017-01-18 to 2017-04-17 | 10Y\|4\|-0.05 | +3.39% | 2017-01-17 to 2017-04-13 | 10y\|4\|-0.05 | +3.84% | same |
| 2017-04-18 to 2017-07-17 | 10Y\|4\|-0.05 | +4.84% | 2017-04-17 to 2017-07-14 | 10y\|4\|-0.05 | +5.44% | same |
| 2017-07-18 to 2017-10-17 | 10Y\|4\|-0.05 | +5.15% | 2017-07-17 to 2017-10-16 | 10y\|4\|-0.05 | +5.01% | same |
| 2017-10-18 to 2018-01-17 | 10Y\|4\|-0.05 | +7.62% | 2017-10-17 to 2018-01-16 | 10y\|4\|-0.05 | +5.89% | same |
| 2018-01-18 to 2018-04-17 | ALL\|4\|-0.05 | −6.44% | 2018-01-16 to 2018-04-13 | all\|4\|-0.05 | −6.57% | same |
| 2018-04-18 to 2018-07-17 | ALL\|3\|-0.05 | +6.27% | 2018-04-17 to 2018-07-16 | all\|3\|-0.05 | +2.77% | same |
| 2018-07-18 to 2018-10-17 | ALL\|3\|-0.05 | +1.16% | 2018-07-17 to 2018-10-16 | all\|3\|-0.05 | +1.67% | same |
| 2018-10-18 to 2019-01-17 | ALL\|3\|-0.05 | −5.74% | 2018-10-16 to 2019-01-15 | all\|3\|-0.05 | −5.53% | same |
| 2019-01-18 to 2019-04-17 | ALL\|3\|0.05 | +5.49% | 2019-01-14 to 2019-04-12 | all\|3\|0.05 | +7.86% | same |
| 2019-04-18 to 2019-07-17 | ALL\|4\|-0.05 | −0.11% | 2019-04-17 to 2019-07-16 | all\|4\|-0.05 | +0.50% | same |
| 2019-07-18 to 2019-10-17 | ALL\|3\|0.05 | +0.61% | 2019-07-17 to 2019-10-16 | all\|3\|0.05 | +0.60% | same |
| 2019-10-18 to 2020-01-17 | ALL\|3\|0.05 | +0.84% | 2019-10-16 to 2020-01-15 | all\|3\|0.05 | +3.84% | same |
| 2020-01-21 to 2020-04-17 | 10Y\|3\|0.05 | −12.34% | 2020-01-16 to 2020-04-15 | 10y\|3\|0.00 | −15.40% | different |
| 2020-04-20 to 2020-07-17 | ALL\|3\|0.00 | −2.39% | 2020-04-17 to 2020-07-16 | all\|5\|0.05 | +6.34% | different |
| 2020-07-20 to 2020-10-16 | ALL\|5\|0.05 | −4.53% | 2020-07-17 to 2020-10-16 | all\|5\|0.05 | +8.68% | same |
| 2020-10-19 to 2021-01-15 | 10Y\|3\|0.05 | +11.70% | 2020-10-15 to 2021-01-14 | 10y\|3\|0.05 | +9.88% | same |
| 2021-01-19 to 2021-04-16 | 10Y\|3\|0.05 | +6.55% | 2021-01-19 to 2021-04-15 | 10y\|3\|0.05 | −0.03% | same |
| 2021-04-19 to 2021-07-16 | 10Y\|5\|0.00 | +4.45% | 2021-04-19 to 2021-07-16 | 10y\|5\|-0.05 | +4.63% | different |
| 2021-07-19 to 2021-10-15 | ALL\|5\|-0.05 | +2.48% | 2021-07-16 to 2021-10-15 | all\|5\|-0.05 | +1.84% | same |
| 2021-10-18 to 2022-01-14 | 10Y\|5\|0.00 | +4.91% | 2021-10-14 to 2022-01-13 | 10y\|5\|-0.05 | +6.36% | different |
| 2022-01-18 to 2022-04-14 | 10Y\|5\|0.00 | −5.36% | 2022-01-18 to 2022-04-14 | 10y\|5\|-0.05 | −4.23% | different |
| 2022-04-18 to 2022-07-15 | 10Y\|5\|0.00 | −9.59% | 2022-04-18 to 2022-07-15 | 10y\|5\|-0.05 | −9.57% | different |
| 2022-07-18 to 2022-10-17 | ALL\|4\|0.00 | +3.91% | 2022-07-15 to 2022-10-14 | all\|3\|0.05 | +9.33% | different |
| 2022-10-18 to 2023-01-17 | ALL\|3\|0.05 | +6.18% | 2022-10-14 to 2023-01-13 | all\|3\|0.05 | +6.24% | same |
| 2023-01-18 to 2023-04-17 | ALL\|4\|0.00 | +6.74% | 2023-01-17 to 2023-04-14 | all\|3\|0.05 | +4.53% | different |
| 2023-04-18 to 2023-07-17 | ALL\|4\|0.00 | +9.17% | 2023-04-17 to 2023-07-14 | all\|4\|0.00 | +9.08% | same |
| 2023-07-18 to 2023-10-17 | ALL\|4\|0.00 | −3.20% | 2023-07-17 to 2023-10-16 | all\|4\|0.00 | −2.96% | same |
| 2023-10-18 to 2024-01-17 | 10Y\|5\|0.00 | +8.89% | 2023-10-17 to 2024-01-16 | 10y\|5\|-0.05 | +9.53% | different |
| 2024-01-18 to 2024-04-17 | ALL\|5\|0.00 | +5.67% | 2024-01-16 to 2024-04-15 | 10y\|5\|0.00 | +6.01% | different |
| 2024-04-18 to 2024-07-17 | ALL\|5\|0.05 | +11.82% | 2024-04-17 to 2024-07-16 | all\|5\|0.05 | +11.73% | same |
| 2024-07-18 to 2024-10-17 | ALL\|5\|0.05 | −3.06% | 2024-07-17 to 2024-10-16 | all\|5\|0.05 | −4.59% | same |
| 2024-10-18 to 2025-01-17 | 10Y\|3\|0.00 | +4.88% | 2024-10-16 to 2025-01-15 | 10y\|5\|0.00 | +2.65% | different |
| 2025-01-21 to 2025-04-17 | 10Y\|3\|0.00 | −16.61% | 2025-01-15 to 2025-04-14 | 10y\|3\|0.00 | −13.80% | same |

**Verdict: STOP.** The stopping rule is CONTINUE only when the prior-only path beats buy-and-hold and every same-stop
fixed delay. It beats none of them. This is not a candidate result. No holdout evaluation was run. No further version
may follow from this result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that sold
on the trailing stop and waited for the model got to +62%. It was in cash about one session in four. Buying back the
next day finished at +195%, close to staying invested. The model's longer waits finished far behind that, and behind
a five-day wait, a twenty-day wait, and the median random wait. The best rule chosen after seeing every period
(`ALL|4|0.00`, +219% against a fresh-window buy-and-hold of +199%) could not have been selected in advance; the path
that could have been is the +62% one.

Mathematically: the prior-only total return is 0.6182 and buy-and-hold is 1.9904, so the difference of total returns
is −1.372. The annualized log excess is −0.0594 per year. Its 6-month block interval [−0.1164, −0.0062] does not
contain 0.

## exp03_ath_exit_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Pre-registered in commit `26700e0`
(2026-10-12 17:52:39 +0300), before any trial of this name. Config hash `d9d257cb6f`. One development run. The notebook
`step01_development.ipynb` was executed by `scripts/execute_notebook.py` and saved with its outputs. 615 validation
trials and 1 summary (616), note `re-run under new rules`, `test_window_touched` false on every row, every row
`logged_ts` 2026-10-12T20:03:46. The first logged row is trial `2026101220034656923500000_d9d257cb6f`, stage
`validation`, fold 0, candidate `0.005|delay_5`, total return +1.42% against buy-and-hold +1.25% on that fresh window.
The protocol's budget (protocol §4, `TRIAL_BUDGET`) is 15 × 44 + 1 = **661**. The development span has 41 periods, so
the run logged 15 × 41 + 1 = 616, inside the budget. The 2005-2014 exploration was not re-run.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** From the saved notebook
outputs and `summary_data.csv`.
- **Prior-only path: +111.12% vs buy-and-hold +199.04%.** About 7.58% a year vs 11.31% a year, from those two total
  returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market 60.4% (39.6% in cash). 18 of 41 periods beat
  buy-and-hold (sign-test p = 0.826); mean period excess −0.95% (SD 3.48%, t = −1.75); MDE 1.52% per period (6.09% per
  year). Annualized log excess **−3.37%/yr**, 6-month block interval [−6.94%, −0.24%] (124 months). The interval lies
  below 0. The protocol's "supported" flag stays false.
- Sharpe 0.52 vs 0.68, from `get_sharpe_ratio` on the saved daily equity and on buy-and-hold's saved daily returns.
  Maximum drawdown −28.83% vs −34.21%, the minima of `performance_over_time_data.csv`. Comparable return, Sharpe and
  drawdown flags are all false. Primary success is false. The smaller drawdown does not count: the path is not at 90%
  of buy-and-hold (+179.14% would be required; the path is +111.12%).
- Baselines on the same span, from the notebook output and `summary_data.csv`: random buy-back median **+168.81%**
  (the path beats 1 of 20), random exit median **+38.19%** (the path beats 20 of 20), 200-session trend **+93.31%**.
  The information test needs both random families. The path beats the exit family and loses to the buy-back family.
  107 exits, 2 forced buy-backs.
- Optimistic, labelled after the fact: candidate `0.010|delay_5` chains to **+170.47%** against a fresh-window
  buy-and-hold of **+198.70%**. That chain resets each period. The path buy-and-hold is +199.04% because the position
  is one continuous series. Protocol §6 already says these are not the same object.
- Activity, from `summary_data.csv`: turnover 20.83 per year, 214 trades, 19 candidate switches (1.86 per year).

**Calibration against the old quarterly exp03, periods that end before the development end.** The development end is
2025-07-17. Old quarters were read from `exp03_ath_exit/step02_walk_forward_data/`. The old schedule has 44 validation
quarters. Three end on or after 2025-07-17. Their returns were not read. Forty of the remaining quarters overlap a v2
period that also ends before the development end. The v2 start is 0 to 6 days later than the old start, and the v2 end
is 0 to 5 days later, because v2 steps back from the development end and the old schedule stepped back from its own
end. Five pairs have the same start and the same end: 2016-01-19 to 2016-04-15, 2016-04-18 to 2016-07-15, 2021-04-19
to 2021-07-16, 2022-01-18 to 2022-04-14, and 2022-04-18 to 2022-07-15. On those five, all 15 rules (75 rows in
`score_data.csv` against `validation_candidate_data.csv`) match. The largest absolute difference of total return is
2.0×10⁻¹⁶, and buy-and-hold matches exactly. The other quarters are not the same windows, so their returns are not the
same object. The rules did not change. The date shift is the cause of every difference outside those five quarters.

**Prior-only selections, same date cut (added 2026-10-12, after `29aec55`).** The rule in force is not a period score.
It is the pooled choice of earlier quarters, applied to the next quarter (`get_governing_selection_pdf`). On the five
shared-bound quarters the fresh-window returns match and the rule in force matches on 2 of 5: 2021-04-19 to 2021-07-16
and 2022-01-18 to 2022-04-14 are `0.005|delay_5` in both files. The other three differ. 2016-01-19 to 2016-04-15 and
2016-04-18 to 2016-07-15 are old `0.020|delay_5` and v2 `0.020|delay_60`. 2022-04-18 to 2022-07-15 is old
`0.020|delay_5` and v2 `0.005|delay_20`. Old names are `ath_within` and `rule` in `prior_only_data.csv`. v2 names are
`candidate` in `selection_data.csv`. Across the 39 old quarters that have a prior-only row and end before 2025-07-17,
aligned by fold index with v2 periods 1 to 39 (those periods also end before 2025-07-17; starts 0 to 6 days later,
ends 0 to 5 days later), 24 candidates match and 15 do not. Fold 0 has no prior-only row; v2 period 0 uses the first
listed rule, `0.005|delay_5`, as protocol §2 states. One old quarter ends on 2025-07-16. The v2 period of the same
index ends on the development end, so that pair is not in the count. Cause: the earlier quarters that the selection
maximizes over do not share bounds with the archived quarters, so the mean excess is not the archived mean. A quarter
can reproduce all 15 fresh-window returns and still be governed by a different rule. The verdict does not change.

**Old-bounds calibration (2026-10-12, one note row, not a second validation run).** `scripts/calibrate_exp03_old_bounds.py` replayed the version 2.0 rules on the archived quarter bounds, and only on quarters that end before 2025-07-17. It finished at 2026-10-12T22:54:26. The log is `logs/exp03_ath_exit_v2_20261012_2051.log`. The summary is `exp03_ath_exit_v2/old_bounds_calibration/summary_data.csv`. One trial-log row, stage `note`, note `old-bounds calibration; diagnostic; informs no decision`. It informs no decision and was not repeated.

41 archived quarters were kept (2015-04-17 to 2025-07-16). 3 quarters end on or after the development end and were not read. **Returns: 615 / 615 matched.** Buy-and-hold matched on the same 615 rows. No row failed to join. The largest absolute difference of total return is 1.80×10⁻¹⁶.

**Prior-only selections: 36 / 40 matched.** The 4 that differ are folds 31, 32, 33 and 34 (`selection_mismatch_data.csv`): the archived rule in force is `0.005|delay_5` and the replay's rule in force is `0.010|delay_60`. Those four quarters are governed by the choices made at folds 30, 31, 32 and 33. On each of those choosing folds the archived pooled excess is exactly 0 for all 15 rules, so the protocol tie-break (tighter threshold, then rule order) selects `0.005|delay_5`. Applying that same function to the archived scores reproduces all 40 archived selections. The replay's returns differ by at most one unit in the last place. On a fold where every pooled excess is exactly 0, that difference makes the scores unequal, the tie-break does not run, and `0.010|delay_60` wins. The next choosing fold (34) has a pooled excess of about 0.005, which is far above that difference, and the selections match again. The rules did not change. The verdict does not change.

**Numeric tolerance (2026-10-13, computation on the saved scores, no new trial).** exp03 v2 is not re-run. Its trials stand. The four affected folds are 31, 32, 33 and 34 (`selection_mismatch_data.csv`). The replay without a tolerance put `0.010|delay_60` in force on each of them. The tolerance rule would have put `0.005|delay_5` in force on each of them.

Those four folds are governed by the choices at folds 30, 31, 32 and 33. On the archived scores in `exp03_ath_exit/step02_walk_forward_data/validation_candidate_data.csv`, all 15 pooled excesses at each of those choosing folds are 0.000000. Applying `get_pooled_selection_pdf` with `NUMERIC_TOLERANCE` of 0.000001 and the protocol tie order (tighter threshold, then rule order) selects `0.005|delay_5` at each choosing fold, so that is the candidate in force for folds 31-34. The replay's candidate scores were not saved row by row. The calibration log records a maximum absolute return difference of 1.8041124150158794e-16 (`logs/exp03_ath_exit_v2_20261012_2051.log`). At 6 decimal places that difference is 0.000000, and it is inside the tolerance, so the same tie order applies to the replay. Fold 34's own pooled excesses are not a tie: the best saved pooled excess is 0.004956, the rule selects `0.010|delay_5`, and that choice governs fold 35, which already matched. The verdict stays STOP.

**Verdict: STOP.** The stopping rule is CONTINUE only when the prior-only path beats buy-and-hold and both random
families. It loses to buy-and-hold (+111.12% vs +199.04%) and to the random buy-back median (+168.81%). It beats
random exits. This is not a candidate result. No holdout evaluation was run. No further version may follow from this
result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that sold
near the all-time high and bought back later got to +111%. It was in the market about three sessions in five. Selling
at a random moment and using the same buy-back finished at +38%, so the decision to sell near the high beat random
sell timing on every one of the 20 draws. Buying back at random after those same sales finished at +169%, ahead of
the rule's own buy-back. The edge from the exit was given away while waiting to buy. That is the same reading as
protocol 1.0. The best rule chosen after seeing every period (`0.010|delay_5`, +170% against a fresh-window
buy-and-hold of +199%) could not have been selected in advance; the path that could have been is the +111% one.

Mathematically: the prior-only total return is 1.1112 and buy-and-hold is 1.9904, so the difference of total returns
is −0.879. The annualized log excess is −0.0337 per year. Its 6-month block interval [−0.0694, −0.0024] does not
contain 0.

## exp03_ath_exit

**Protocol 1.0. Status: STOP.** Run 2026-10-05 14:55-14:56, hash `b8523207d1` (15 exploration, 660 validation and 1
summary trials).
- Step 01 (2005-2014): reproduced (above). Forward returns after near-ATH days are lower than after all days at 1-20
  sessions (e.g. 20 sessions within 0.5%: −0.02% vs +0.43% log return) but every 95% interval includes 0, and they are not
  negative enough: by the S/R identity, selling pays only if prices fall.
- Step 02, after the fact: all 15 rules lose to buy-and-hold over the 44 validation quarters (best: within 0.5%, 20-day
  delay, +216.86% vs +243.38%). No rule exits from early 2022 to late 2023 (SPY below its high).
- **Prior-only path (43 quarters): +143.05% vs +237.21%** (8.6%/yr vs 12.0%/yr); 14 of 43 quarters won (p = 0.993);
  mean excess −0.85% per quarter (SD 3.17%, t = −1.75); MDE 1.35% per quarter (about 5.4% per year); time in cash 38.6%;
  31 quarters with an exit. Comparable return, Sharpe and drawdown flags all False.
- Baselines: random buy-back with the same exits (median) +180.48%, the rule beats 1 of 20 runs; random exit with the same
  buy-back (median) +59.07%, the rule beats 19 of 20 runs (empirical p ≈ 0.10); 200-session trend +106.16%.
- Reading: selling near the high may carry a little timing information relative to random exits (not significant at
  5%), but the buy-back rules lose more than it brings, and the time out of the market is not paid for.

## Step 0: evaluation code for long holding periods (2026-10-06, agent; shared code, no trial)

*Implemented and tested, nothing run on real data.* `so/core/continuous_replay.py` and `so/core/fractional_exposure.py`,
tests `tests/test_continuous_replay.py` (synthetic data): a continuous replay with no exit equals buy-and-hold; one
episode carries across a period boundary and the period returns chain to the total return; the scorecard's S/R equals
the share ratio within 1 share; w = 1 equals buy-and-hold and w = 0 equals cash; the guard refuses any window ending on
or after 2026-05-14. No existing function was modified, so the exp01-exp03 reproduction checks are unaffected (all
previous suites pass). `tests/run_all_tests.py` now forces UTF-8 output (it crashed on a cp1252 pipe before, an output
problem only).

Design choices (the conservative option, documented in each protocol that uses them):
- Replay periods: validation quarter f runs to the session before quarter f + 1 starts (the anchored schedule makes
  some quarters overlap by 1-2 sessions), so each session counts once.
- Interval: annualized log excess = 12 × mean monthly log excess, with a **circular block bootstrap of 6-month blocks**
  as the primary interval (long exits create dependence across months; longer blocks give wider, more honest intervals),
  the 1-month version printed alongside.

## exp04_trend_exit_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Pre-registered in commit `efbae03` (2026-10-12 23:36:41 +0300). The numeric-tolerance amendment `98115f0` (2026-10-13 00:36:32 +0300) is in the code that ran. Config hash `39c1919563`, printed in the header cell of `step01_development.ipynb`. One development run, saved by the queue at 2026-10-13T02:16:52. 369 validation trials and 1 summary (370), note `re-run under new rules`, `test_window_touched` false on every row. The protocol budget is 9 × 44 + 1 = **397**. The development span has 41 periods, so the run logged 9 × 41 + 1 = 370, inside the budget. The 2005-2014 exploration was not re-run. The run was not repeated.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** Development end **2025-07-17**. Last price date loaded before the cut **2025-08-13**. Both are printed in the notebook. The session count is the sum of `session_count` in `period_data.csv`. Numbers below are the notebook's 6-decimal prints unless a file is named.
- **Prior-only path: printed 0.415088 vs buy-and-hold 1.990442** (+41.51% vs +199.04%). About 3.45% a year vs 11.31% a year, from those two printed total returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market printed 0.847826 (84.78%). 12 exits. 11 of 41 periods beat buy-and-hold (sign-test p = 0.999275); mean period excess −0.017709 (SD 0.043552, t = −2.60), from `summary_data.csv`. MDE printed 0.019045 per quarter (0.076178 per year). Annualized log excess printed **−0.072409**, 6-month block interval [−0.140352, −0.017098] (124 months, `summary_data.csv`). The interval lies below 0. The saved `log_supported` flag is false.
- Maximum drawdown −0.346944 vs −0.342106, the minima of `performance_over_time_data.csv`. The printed success flags are all false (`primary_success`, `secondary_success`, `comparable_return`, `all_baselines_beaten`). Comparable return would require 90% of 1.990442, which is 1.791398. The path is 0.415088.
- Baselines on the same span, printed: random-exit median **1.517796**, random-re-entry median **0.553211**. The path beats a printed fraction 0.000000 of the 20 random exits (0 of 20) and 0.100000 of the 20 random re-entries (2 of 20). It is below both medians. The information test fails.
- Optimistic, labelled after the fact: candidate `0.03|1` chains to printed **1.160337** against printed buy-and-hold **1.990442**. That chain is not the prior-only path.
- Activity, printed: turnover 2.444703 per year, 26 trades, 14 candidate switches (1.369034 per year in `summary_data.csv`).

**Calibration (i), shared bounds.** Computation on the saved files only. No replay and no new trial. A quarter is shared when `valid_start` and `valid_end` are equal and the quarter ends before 2025-07-17. v2 dates are `period_data.csv`. Archived dates are `exp04_trend_exit/step02_continuous_replay_data/candidate_period_data.csv`. 40 v2 periods and 41 archived quarters end before that date. Three quarters match on both ends: 2016-01-19 → 2016-04-15, 2021-01-19 → 2021-04-16, 2022-01-18 → 2022-04-14. On those three, all 9 candidates (27 rows) are compared at `NUMERIC_TOLERANCE` 1e-6.

**Returns: 0 / 27 matched.** Maximum absolute difference of total return **0.0159446775694723**. Buy-and-hold on the same 27 rows: 0 / 27 matched, maximum absolute difference 4.771406598820527e-5.

**Prior-only selections: 1 / 3 matched.** The archived `selection_data.csv` row at fold f is the choice made at that fold; the old notebook says it governs fold f + 1. The v2 `selection_data.csv` row is the candidate in force. On the three shared quarters the rule in force is archived `0.03|5` vs v2 `0.03|1` (2016-01-19), both `0.03|1` (2021-01-19), and archived `0.03|1` vs v2 `0.05|10` (2022-01-18).

Cause: the other aligned quarters differ by 0 to 6 sessions. Version 2.0 steps back from the development end 2025-07-17. The archived quarters step back from 2026-04-15. A period score is a slice of one continuous path, so the position carried into a shared quarter was built on earlier quarters that do not share bounds. Those return gaps are far above 1e-6, so the tolerance tie order is not what splits the selections. The rules are the same rules. The schedule is the difference.

**Calibration (ii), old bounds.** `scripts/calibrate_port_old_bounds.py` replayed the version 2.0 rules on the archived bounds. It finished at 2026-10-13T13:28:12. The log is `logs/exp04_trend_exit_calibration_20261013_1216.log`. The summary is `exp04_trend_exit_v2/old_bounds_calibration/summary_data.csv`. One trial-log row, stage `note`, note `old-bounds calibration; diagnostic; informs no decision`, `test_window_touched` false. It was not repeated. The morning run of 2026-10-13T02:17 failed before any note row; that failure is the port-queue note above.

41 archived quarters were kept (warmup 2,588 sessions). **Returns: 369 / 369 matched** within 1e-6. Buy-and-hold matched on the same 369 rows. **Prior-only selections: 41 / 41 matched.** Maximum absolute difference of total return **2.0122792321330962e-16**. That gap is floating-point rounding of the same rules on the same bounds. No selection changed.

**Verdict: STOP.** The stopping rule is STOP when the prior-only path does not beat buy-and-hold, or does not beat the median of both random families. Printed path 0.415088 is below printed buy-and-hold 1.990442 and below both printed medians (1.517796 and 0.553211). This is not a candidate result. No holdout evaluation was run. No further version may follow from this result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that sold below the 200-session average and bought back above it got to +42%. It was in the market about five sessions in six, and it still finished behind a coin-flip exit and behind a coin-flip buy-back. The best rule chosen after seeing every period (`0.03|1`, +116%) could not have been selected in advance; the path that could have been is the +42% one.

Mathematically: the prior-only total return is 0.415088 and buy-and-hold is 1.990442, so the difference of total returns is −1.575354. The annualized log excess is −0.072409 per year. Its 6-month block interval [−0.140352, −0.017098] does not contain 0.

## exp04_trend_exit

*2026-10-14.* The version 2.0 re-run is recorded in `exp04_trend_exit_v2`. This protocol 1.0 entry is unchanged.

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §11). Pre-registered in commit `preregister exp04`
(before any run); config hash `8f4c178319`. Trials: 9 exploration (2026-10-06T14:22:35), 396 validation and 1 summary
(2026-10-06T14:24:31 / 14:25:18), 406 in total against a budget of 410. Numbers below are copied from the saved
outputs of `step01_exploration.ipynb` and `step02_continuous_replay.ipynb`.

Rule: leave SPY when the close has been more than x below its 200-session average for n sessions in a row; buy back
when it is more than x above it. Grid x ∈ {0, 3, 5}%, n ∈ {1, 5, 10} (9 candidates); one continuous replay, no reset.

**Step 01, exploration 2005-01-03 → 2014-12-31 (context only, hindsight-prone).**
- Reproduction: the textbook rule (x = 0, n = 1) gives **+50.39% vs buy-and-hold +69.02%** (33 exits, 1 bought back
  lower, product of S/R 0.8921), matching the exp02 step 01 number (+50.4% vs +69.0%).
- 7 of 9 candidates beat buy-and-hold on this decade, best x = 5%, n = 10: +116.85% (2 exits; the 2008-01-25 → 2009-07-15
  exit has S/R 1.4238, the 2011 one 0.9011). Every 95% log-excess interval includes 0 (e.g. best: +2.49%/yr,
  [−4.54%, +13.00%]). Observed: the whole gain comes from one episode, 2008, which every buffered rule sat out.

**Step 02, continuous replay over the 44 validation periods (2015-04-17 → 2026-04-15, 2,765 sessions).** Schedule
asserted identical to exp03's; bars cut at 2026-04-15 before any simulation.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). Best x = 3%, n = 1: **+131.27%**
  (7 exits, 78.2% in the market, annualized log excess −3.35%/yr [−6.81%, +0.19%]); worst x = 5%, n = 10: +51.63%.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +70.84% vs buy-and-hold +229.74%** (annualized 5.12% vs
  11.77%). 83.0% in the market, 12 exits, mean 38.3 cash decisions per episode. 18 of 43 periods won (sign test
  p = 0.889); mean period excess −1.60% (SD 3.80%, t = −2.76); MDE 1.62% per period (6.50% per year).
- Annualized log excess **−6.07%/yr**, 95% interval with 6-month blocks [−10.54%, −2.14%] (1-month blocks [−11.73%,
  −0.50%]): the loss is significant, the gain is excluded. Sharpe 0.43 vs 0.71; max drawdown −29.24% vs −34.21%
  (comparable return, Sharpe and drawdown flags all False). Costs barely matter: excess −158.69% / −158.90% / −159.13%
  at 0 / 1 / 2 cents slippage.
- Information test: random exits with the same re-entry rule (median of 20) **+164.94%**, the path beats 0 of 20; random
  re-entries after the same exits (median) **+92.67%**, the path beats 4 of 20. Both families beat the path → the
  trend signal carries no exit or re-entry information on this period; the rule is worse than chance at both ends.
- Scorecard: **0 of 12 episodes bought back lower**; product of S/R **0.5182**. Large ones: 2018-12-28 → 2019-03-21
  (S/R 0.8702, SPY +14.91% while out), 2020-03-11 → 2020-06-03 (0.8818, +13.39%), 2022-05-11 → 2023-02-02 (0.9421, 183
  sessions out, +6.14%).

*Mathematically:* each episode multiplies the share count by S/R = exit fill / re-entry fill (minus costs), and at the
end the path holds the same cash-free position as buy-and-hold, so final equity / buy-and-hold equity = Π S/R ≈ 0.518;
indeed 1.7084 / 3.2974 = 0.518. A trend filter needs at least one episode with S/R well above 1 (2008 gave 1.42-1.56)
to pay for the many small losses; 2015-2026 had no such bear market: the declines (2018, 2020, 2022, 2025) were
recovered before the average turned back, so every buy-back price was higher than the sale price.
*In plain words:* waiting for SPY to cross back over its 200-day average meant buying back after the rebound had already
happened, every time. Over 2015-2026 the rule lost about half of the shares buy-and-hold kept. The rule worked in
2005-2014 only because of 2008.

What this supports: on 2015-2026, the 200-session trend exit (with buffers and confirmation) does not beat buy-and-hold,
and its timing is worse than random. What it does not support: a statement about deep, slow bear markets (only one
in the exploration decade, none in the validation decade) or about other trend measures (not tested).

## exp05_vol_scaled_exposure_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Pre-registered in commit `7731824` (2026-10-12 23:40:20 +0300). The numeric-tolerance amendment `98115f0` (2026-10-13 00:36:32 +0300) is in the code that ran. Config hash `dedf424c5a`, printed in the header cell of `step01_development.ipynb`. One development run, saved by the queue at 2026-10-13T02:49:47. 164 validation trials and 1 summary (165), note `re-run under new rules`, `test_window_touched` false on every row. The protocol budget is 4 × 44 + 1 = **177**. The development span has 41 periods, so the run logged 4 × 41 + 1 = 165, inside the budget. The signal check and the 2005-2014 exploration were not re-run. The run was not repeated.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** Development end **2025-07-17**. Last price date loaded before the cut **2025-08-13**. Both are printed in the notebook. The session count is the sum of `session_count` in `period_data.csv`. Numbers below are the notebook's 6-decimal prints unless a file is named.
- **Prior-only path: printed 1.425930 vs buy-and-hold 1.990442** (+142.59% vs +199.04%). About 9.05% a year vs 11.31% a year, from those two printed total returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Mean weight printed 0.854666. 27 rebalances. 8 of 41 periods beat buy-and-hold (sign-test p = 0.999987); mean period excess −0.005887 (SD 0.014285, t = −2.64), from `summary_data.csv`. MDE printed 0.006246 per quarter (0.024986 per year). Annualized log excess printed **−0.020246**, 6-month block interval [−0.036110, −0.002161] (124 months, `summary_data.csv`). The 1-month interval is printed [−0.046115, 0.007598]. The 6-month interval lies below 0. The saved `log_supported` flag is false.
- Maximum drawdown −0.233226 vs −0.342106, the minima of `performance_over_time_data.csv`. The printed success flags are all false. Comparable return would require 90% of 1.990442, which is 1.791398. The path is 1.425930, so the smaller drawdown does not count.
- Baselines on the same span, printed: constant exposure **1.701911** at weight 0.854666; random-shift median **1.575069**. The path beats a printed fraction 0.250000 of the 20 random shifts (5 of 20). It is below buy-and-hold, below the constant exposure, and below the median. Protocol §6 still records that the 20-point band makes this constant baseline close to buying a fraction and holding. The stopping rule also fails on buy-and-hold and on the random shifts, so the verdict does not rest on that baseline alone.
- Optimistic, labelled after the fact: candidate `0.50|0.75` chains to printed **1.580618** against printed buy-and-hold **1.990442**. That chain is not the prior-only path.
- Activity, printed: turnover 0.999446 per year, 28 trades, 9 candidate switches (0.880093 per year in `summary_data.csv`).

**Calibration (i), shared bounds.** Computation on the saved files only. No replay and no new trial. Same date rule as exp04. Three quarters match on both ends: 2016-01-19 → 2016-04-15, 2021-01-19 → 2021-04-16, 2022-01-18 → 2022-04-14. All 4 candidates (12 rows) are compared at `NUMERIC_TOLERANCE` 1e-6.

**Returns: 0 / 12 matched.** Maximum absolute difference of total return **0.020042389090589204**. Buy-and-hold on the same 12 rows: 0 / 12 matched, maximum absolute difference 4.771406598820527e-5.

**Prior-only selections: 2 / 3 matched.** The rule in force is archived `0.50|0.75` vs v2 `0.30|0.50` (2016-01-19), and both `0.50|0.75` on 2021-01-19 and on 2022-01-18. Cause: the same schedule shift as exp04. A period score is a slice of one continuous path, and the earlier quarters that the selection pools do not share bounds. The return gaps are far above 1e-6, so the tolerance tie order is not what splits the 2016 selection.

**Calibration (ii), old bounds.** Finished at 2026-10-13T13:59:59. Log `logs/exp05_vol_scaled_exposure_calibration_20261013_1328.log`. Summary `exp05_vol_scaled_exposure_v2/old_bounds_calibration/summary_data.csv`. One note row, `old-bounds calibration; diagnostic; informs no decision`, `test_window_touched` false. It was not repeated. The morning run failed before any note row.

41 archived quarters were kept (warmup 2,588 sessions). **Returns: 164 / 164 matched** within 1e-6. Buy-and-hold matched on the same 164 rows. **Prior-only selections: 41 / 41 matched.** Maximum absolute difference of total return **1.97758476261356e-16**. That gap is floating-point rounding of the same rules on the same bounds. No selection changed.

**Verdict: STOP.** The stopping rule is STOP when the prior-only path does not beat buy-and-hold, or does not beat the constant exposure, the median random shift, and more than half of the random shifts. Printed path 1.425930 is below printed buy-and-hold 1.990442, below the constant exposure 1.701911, and below the median 1.575069. It beats 5 of 20 shifts. This is not a candidate result. No holdout evaluation was run. No further version may follow from this result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that held about 85% of its money in SPY and moved the weight with recent volatility got to +143%. Holding that same average weight without the volatility timing got to +170%. Shuffling the same target weights beat the rule on 15 of the 20 draws. The smaller loss from the worst peak (−23% against −34%) does not rescue a path that finished well behind staying invested.

Mathematically: the prior-only total return is 1.425930 and buy-and-hold is 1.990442, so the difference of total returns is −0.564512. The annualized log excess is −0.020246 per year. Its 6-month block interval [−0.036110, −0.002161] does not contain 0.

## exp05_vol_scaled_exposure

*2026-10-14.* The version 2.0 re-run is recorded in `exp05_vol_scaled_exposure_v2`. This protocol 1.0 entry is unchanged.

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §9). Pre-registered in commit `5305b83` (`preregister`
exp05`, before any run); config hash `b1763b5981`. Trials: 1 signal check and 4 exploration (2026-10-06T14:34:52 /
14:34:54), 176 validation and 1 summary (step 02, same day), 182 in total against a budget of 185. Numbers below are
copied from the saved outputs of `step01_exploration.ipynb` and `step02_continuous_replay.ipynb`.

Rule: hold w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, σ̂ = `daily_volatility` (std of the previous 20
daily returns), σ_target = the q-quantile of every earlier σ̂ value (fixed per period); rebalance only if the target is
more than 20 points from the current weight. Grid floor ∈ {30%, 50%} × q ∈ {0.50, 0.75} (4 candidates).

**Step 01 (decisions 2005-01-03 → 2014-12-31, data cut 2015-03-18).**
- **Signal check: PASS.** Spearman correlation between σ̂ and the realized volatility of the next 20 sessions **0.593**,
  95% interval (6-month blocks) **[0.332, 0.754]**; log-log slope 0.686, R² 0.472 (2,495 decisions, 119 months).
  Volatility is predictable, as expected; the pipeline is consistent.
- Descriptive, forward 20-session log return by σ̂ quintile (lowest → highest): +0.72%, −0.35%, +0.86%, +1.32%, −0.47%
  (all decisions +0.42%); share positive 71%, 47%, 70%, 75%, 55%; SD 2.4% → 7.8%. The highest-volatility fifth has a
  slightly negative mean, but so does the second-lowest; there is no monotone pattern, and the spread of outcomes grows
  far faster than the mean falls.
- Exploration (context only, hindsight-prone): all 4 candidates above buy-and-hold (+69.02%) on 2005-2014: +89.84%,
  +107.22%, +88.58%, +97.11%; mean weight 82-90%; every log-excess interval includes 0 (e.g. floor 30%, q 0.75: +2.04%/yr
  [−1.63%, +7.63%]). As in exp04, 2008 carries the decade.
- **Defect found in a descriptive column (recorded, not fixed by a re-run):** the step 01 column
  `constant_exposure_total_return` equals buy-and-hold (+69.02%) for every candidate. Cause: the replay starts at the
  first session of the data, where no earlier decision exists, so `simulate_weight_path_dict` falls back to an initial
  weight of 1; the target (the mean weight, 0.82-0.90) is then within the 20-point band and is never traded. The column
  is invalid and was not used for any decision. Step 02 is not affected (its span starts at session > 0 and the
  constant baseline is assigned to the session before the span; its output shows the intended starting weight).

**Step 02, continuous fractional replay over the 44 validation periods (2015-04-17 → 2026-04-15).** Schedule asserted
identical to exp03's; bars cut at 2026-04-15 before any simulation.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). Best floor 50%, q 0.75: **+187.88%**
  (mean weight 93.3%, 27 rebalances, −1.38%/yr log excess [−2.77%, −0.07%]); worst floor 50%, q 0.50: +166.37%.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +165.69% vs buy-and-hold +229.74%** (annualized 9.54% vs
  11.77%). **Mean weight in SPY 86.3%**, 32 rebalances. 9 of 43 periods won (sign test p = 1.000); mean period excess
  −0.61% (SD 2.39%, t = −1.66); MDE 1.02% per period (4.07% per year).
- Annualized log excess **−1.99%/yr**, 95% interval (6-month blocks) [−4.33%, +0.08%] (1-month blocks [−4.59%, +0.81%]).
  Sharpe 0.73 vs 0.71; max drawdown **−23.20% vs −34.21%**. Comparable return False (165.69 / 229.74 = 72% of buy-and-hold's
  total return, below 90%), so the secondary flags are False by definition. Costs barely matter: excess −63.92% / −64.05% / −64.08% at
  0 / 1 / 2 cents.
- Information test: **constant exposure** started at the path's mean weight (86.3%) **+198.52%**; **random shifts** of the
  path's weights (median of 20) **+192.15%**, the path beats 3 of 20. The volatility timing is worse than holding the
  same average amount of SPY at uninformed times.
- Caveat on the constant baseline (observed): with the 20-point band it never rebalanced (0 trades after the start), so
  its SPY share drifted up as SPY rose (mean weight 90.9%, not 86.3%); it is "buy 86% and hold". A band-free constant 86.3%
  would have earned less than +198.52%. The verdict does not depend on it: the path also loses to buy-and-hold and to 17
  of 20 random shifts (mean weights 84-89%).
- *Correction 2026-10-06, after the independent audit (I3): the bullet above labelled "**constant exposure** started at
  the path's mean weight (86.3%) **+198.52%**" describes a baseline that is not a constant exposure: it is "**buy 86.3%
  and hold**" (no rebalancing, mean weight 90.9%). A band-free constant exposure would need a new version, which is not
  run. The verdict rests on buy-and-hold and the random shifts (the path beats 3/20) and is unchanged.*
- Selections: floor 50%, q 0.75 governed 28 of 44 periods, floor 50%, q 0.50 9, floor 30%, q 0.50 7.

*Mathematically:* with w_t ≤ 1 the strategy's excess over buy-and-hold is about −Σ (1 − w_t) r_t − costs. Holding less
SPY on average costs about (1 − 0.863) × 11.8% ≈ 1.6% a year in a rising market; the volatility timing had to earn that
back by having (1 − w_t) large when r_t < 0. It did not: relative to the constant-exposure path the timing cost a further
growth factor 2.6569 / 2.9852 ≈ 0.89 over 10.7 years. Volatility predicts volatility (step 01, ρ ≈ 0.59), not the sign of
the return: high-volatility stretches contain the worst and the best sessions (the rebounds of 2020 and 2025 came while
σ̂ was still high and w was at its floor).
*In plain words:* cutting SPY when the market is jumpy made the ride smoother (drawdown −23% instead of −34%) but cost
about 64 points of total return over 10.7 years, more than simply keeping 14% in cash all the time would have.
*Correction 2026-10-06, after the independent audit (I3): "relative to the constant-exposure path the timing cost a
further growth factor 2.6569 / 2.9852 ≈ 0.89" and "more than simply keeping 14% in cash all the time would have" compare
the path with a baseline that is "buy 86.3% and hold" (never rebalanced, mean weight 90.9%), not with 14% in cash all
the time. Corrected plain words: it cost about 64 points of total return over 10.7 years, more than buying 86.3% of the
account in SPY at the start and holding it (+198.52%) would have; a true constant 86.3% exposure was not run. The
comparison with uninformed timing rests on the random shifts (the path beats 3 of 20).*

What this supports: on 2015-2026, unlevered volatility scaling with this σ̂ does not beat buy-and-hold and its timing
adds no return over an uninformed exposure; it does lower the drawdown. What it does not support: anything about levered
volatility management (excluded by the project), about implied volatility (VIX, new data, parked), or about other σ̂.

## exp06_capped_regret_reentry_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Data-dependent follow-up of exp03, as protocol 1.0. Pre-registered in commit `2f98edd` (2026-10-12 23:45:15 +0300). The numeric-tolerance amendment `98115f0` (2026-10-13 00:36:32 +0300) is in the code that ran. Config hash `ffca9e30e1`, printed in the header cell of `step01_development.ipynb`. One development run, saved by the queue at 2026-10-13T04:28:40. 492 validation trials and 1 summary (493), note `re-run under new rules`, `test_window_touched` false on every row. The protocol budget is 12 × 44 + 1 = **529**. The development span has 41 periods, so the run logged 12 × 41 + 1 = 493, inside the budget. The 2005-2014 exploration was not re-run. The run was not repeated.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** Development end **2025-07-17**. Last price date loaded before the cut **2025-08-13**. Both are printed in the notebook. The session count is the sum of `session_count` in `period_data.csv`. Numbers below are the notebook's 6-decimal prints unless a file is named.
- **Prior-only path: printed 1.322490 vs buy-and-hold 1.990442** (+132.25% vs +199.04%). About 8.59% a year vs 11.31% a year, from those two printed total returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market printed 0.694876 (69.49%). 36 exits. 15 of 41 periods beat buy-and-hold (sign-test p = 0.970208); mean period excess −0.007286 (SD 0.042152, t = −1.11), from `summary_data.csv`. MDE printed 0.018432 per quarter (0.073729 per year). Annualized log excess printed **−0.024463**, 6-month block interval [−0.063152, 0.018654] (124 months, `summary_data.csv`). The 1-month interval is printed [−0.083492, 0.036033]. The 6-month interval contains 0 and extends below 0. The saved `log_supported` flag is false.
- Maximum drawdown −0.288505 vs −0.342106, the minima of `performance_over_time_data.csv`. Printed flags: `primary_success` false, `secondary_success` false, `comparable_return` false, `all_baselines_beaten` true. Comparable return would require 1.791398. The path is 1.322490, so the smaller drawdown does not count. `all_baselines_beaten` here is the two random medians.
- Baselines on the same span, printed: random-exit median **0.980501**, random-re-entry median **1.137882**. The path beats a printed fraction 0.900000 of the 20 random exits (18 of 20) and 0.750000 of the 20 random re-entries (15 of 20). It beats both medians. The same reading as protocol 1.0 applies: beating 18 of 20 and 15 of 20, on a data-dependent design with 12 candidates, is consistent with weak timing information and is not statistical support.
- Optimistic, labelled after the fact: candidate `ath_1pct|0.01|20` chains to printed **1.435236** against printed buy-and-hold **1.990442**. That chain is not the prior-only path, and it is also below buy-and-hold.
- Activity, printed: turnover 7.138533 per year, 74 trades, 16 candidate switches (1.564610 per year in `summary_data.csv`).

**Calibration (i), shared bounds.** Computation on the saved files only. No replay and no new trial. Three quarters match on both ends: 2016-01-19 → 2016-04-15, 2021-01-19 → 2021-04-16, 2022-01-18 → 2022-04-14. All 12 candidates (36 rows) are compared at `NUMERIC_TOLERANCE` 1e-6.

**Returns: 0 / 36 matched.** Maximum absolute difference of total return **0.0430891693241582**. Buy-and-hold on the same 36 rows: 0 / 36 matched, maximum absolute difference 4.771406598820527e-5.

**Prior-only selections: 1 / 3 matched.** Both `ath_1pct|0.02|20` on 2016-01-19. Archived `ath_1pct|0.01|20` vs v2 `ath_1pct|0.01|0` on 2021-01-19. Archived `trend_ma200|0.01|0` vs v2 `trend_ma200|0.01|20` on 2022-01-18. Cause: the same schedule shift as exp04. The return gaps are far above 1e-6, so the tolerance tie order is not what splits the selections.

**Calibration (ii), old bounds.** Finished at 2026-10-13T15:36:55. Log `logs/exp06_capped_regret_reentry_calibration_20261013_1359.log`. Summary `exp06_capped_regret_reentry_v2/old_bounds_calibration/summary_data.csv`. One note row, `old-bounds calibration; diagnostic; informs no decision`, `test_window_touched` false. It was not repeated.

41 archived quarters were kept (warmup 2,588 sessions). **Returns: 492 / 492 matched** within 1e-6. Buy-and-hold matched on the same 492 rows. **Prior-only selections: 41 / 41 matched.** Maximum absolute difference of total return **2.0816681711721685e-16**. That gap is floating-point rounding of the same rules on the same bounds. No selection changed.

**Verdict: STOP.** The stopping rule is STOP when the prior-only path does not beat buy-and-hold, or does not beat the median of both random families. It beats both medians. Printed path 1.322490 is below printed buy-and-hold 1.990442, so the primary criterion fails. This is not a candidate result. No holdout evaluation was run. No further version may follow from this result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that sold on a trend break or near the high and bought back on a capped rise got to +132%. Selling at a random moment and using the same buy-back finished at +98%, so the decision to sell beat random sell timing on 18 of the 20 draws. Buying back at random after those same sales finished at +114%, and the rule beat 15 of those 20. The timing comparison is the same shape as protocol 1.0, and it still does not pay for the time in cash. The best rule chosen after seeing every period (`ath_1pct|0.01|20`, +144%) is also behind staying invested.

Mathematically: the prior-only total return is 1.322490 and buy-and-hold is 1.990442, so the difference of total returns is −0.667952. The annualized log excess is −0.024463 per year. Its 6-month block interval [−0.063152, 0.018654] contains 0.

## exp06_capped_regret_reentry

*2026-10-14.* The version 2.0 re-run is recorded in `exp06_capped_regret_reentry_v2`. This protocol 1.0 entry is unchanged.

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §9: the primary criterion fails). **Data-dependent
follow-up of exp03** (disclosed in the protocol). Pre-registered in commit `1bac3b4` (`preregister exp06`, before any
run); config hash `5927a03c1d`. Trials: 12 exploration, 528 validation and 1 summary (2026-10-06), 541 in total against a
budget of 545. Numbers below are copied from the saved outputs of `step01_exploration.ipynb` and
`step02_continuous_replay.ipynb` and their CSV files.

Rule: exit on `trend_ma200` (close below the 200-session average) or `ath_1pct` (close within 1% of the all-time high);
buy back at once if the close reaches S × (1 + b) (buy-stop; then no exit for c decisions), or when the close is back
above the average after a close below it (recovery). Grid 2 exits × b ∈ {1, 2, 3}% × c ∈ {0, 20} (12 candidates).

**Step 01, exploration 2005-01-03 → 2014-12-31 (context only).** Buy-and-hold +69.02%. Only 1 of 12 candidates beats it
(trend, b = 2%, c = 20: +78.60%, log excess +0.55%/yr [−7.91%, +12.02%]). Every ATH candidate loses (+20.83% to
+38.59%; drawdowns about −55%, as buy-and-hold's, because the buy-stop puts it back in before 2008): their wrong-exit
share q is 0.69-0.96 and (1 − q) × G < q × |L| in all six. Observed: trend, b = 1%, c = 20 ends at −9.44% with a −66.33%
drawdown: a buy-stop re-entry followed by the 20-decision block kept it invested into the 2008 decline.

**Step 02, continuous replay over the 44 validation periods (2015-04-17 → 2026-04-15).** Schedule asserted identical to
exp03's; bars cut at 2026-04-15.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). Best ATH 1%, b = 1%, c = 20:
  **+200.12%** (70.6% in the market, 45 exits; −1.00%/yr [−4.13%, +2.18%]); worst ATH 1%, b = 1%, c = 0: +68.67% (104
  exits, 43.2% in the market). Trend candidates +101.75% to +144.80%.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +147.38% vs buy-and-hold +229.74%** (annualized 8.81% vs
  11.77%). 69.8% in the market, 45 exits, mean 18.1 cash decisions per episode. 13 of 43 periods won (sign test
  p = 0.997); mean period excess −0.79% (SD 4.25%, t = −1.21); MDE 1.81% per period (7.26% per year).
- Annualized log excess **−2.65%/yr**, 95% interval (6-month blocks) [−6.74%, +1.53%] (1-month blocks [−7.99%, +3.07%]).
  Sharpe 0.66 vs 0.71; max drawdown −28.84% vs −34.21%; comparable, Sharpe and drawdown flags all False. Excess
  −81.70% / −82.36% / −82.98% at 0 / 1 / 2 cents.
- **Information test passed** (first time in this family): random exits with the same re-entry rule (median of 20)
  +124.82%, the path beats **19 of 20**; random re-entries after the same exits (median) +103.08%, the path beats
  **15 of 20**. With 20 runs per family, 19 of 20 is an empirical p of about 0.05-0.10, before any correction for the 12
  candidates, the data-dependent design and the 6,700+ earlier trials.
  *Correction 2026-10-06, after the independent audit (I2): "19 of 20 is an empirical p of about 0.05-0.10" should
  read p ≈ (1 + 1) / 21 ≈ 0.10 (one random run of 20 beat the path); for the random re-entries, 15 of 20 is p ≈ 0.29.
  The information test as defined in the protocol (beat both medians) was met; the evidence for timing information is
  weak, before any correction for 12 candidates, the data-dependent design and about 7,400 trials.*
- Trigger arithmetic of the path (log share gains): 45 episodes, **37 ended by the buy-stop (q = 0.822)**, 8 by the
  recovery; mean gain of the right exits G = +0.0350, mean loss of the wrong ones L = −0.0153; (1 − q) × G = 0.0062 vs
  q × |L| = 0.0126 per episode. 6 of 45 bought back lower; product of S/R 0.7514. Largest right exit: 2022-04-08 →
  2022-11-30, S/R 1.0994 (162 sessions out, SPY −9.05%).
- Selections: ATH 1%, b = 1%, c = 20 governed 15 periods; trend candidates 18 of 44 in total.

*Mathematically:* final equity ÷ buy-and-hold ≈ Π S/R = 0.7514 (2.4738 ÷ 3.2974 = 0.750). In logs, Σ log(S/R) =
45 × (0.0062 − 0.0126) ≈ −0.29 = log 0.75: each wrong exit costs about b + costs (1.5%), each right one earns 3.5%, and
four of five exits were wrong. The buy-stop did its job (it capped every wrong exit near b); what it cannot do is make
right exits frequent enough.
*In plain words:* the rule sells too often for the few times it is right. Its timing is better than chance with the same
activity (it beats random exits and random buy-backs), so the signals are not pure noise, but on 2015-2026 the gains of
the good exits were about half the costs of the bad ones, and the path ended 82 points behind buy-and-hold.
*Correction 2026-10-06, after the independent audit (I2): "Its timing is better than chance with the same activity (it
beats random exits and random buy-backs), so the signals are not pure noise" overstates the evidence. Beating 19 of 20
random exits is an empirical p ≈ (1 + 1) / 21 ≈ 0.10 and beating 15 of 20 random re-entries is p ≈ 0.29, for a
data-dependent design with 12 candidates, after about 7,400 trials. Corrected wording: the timing is "consistent with
weak timing information; not statistically supported". The protocol's information test (beat both medians) was met as
defined.*

What this supports: an exit signal plus a buy-stop carries some timing information over random timing on this span, but
not enough to beat buy-and-hold after its wrong exits. What it does not support: that this information would survive a
correction for the selection (data-dependent design, 12 candidates, 6,700+ trials) or appear on new data.
*Correction 2026-10-06, after the independent audit (I2): "an exit signal plus a buy-stop carries some timing
information over random timing on this span" should read: the result is "consistent with weak timing information; not
statistically supported" (p ≈ 0.10 against random exits, p ≈ 0.29 against random re-entries, data-dependent design,
12 candidates, about 7,400 trials). What it supports is only that the path met the protocol's information test (it beat
the median of both random families) while failing the primary criterion.*

## exp07_warning_lights_exit_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Pre-registered in commit `aeb8de5` (2026-10-12 23:45:31 +0300). The numeric-tolerance amendment `98115f0` (2026-10-13 00:36:32 +0300) is in the code that ran. Config hash `d9446bf08f`, printed in the header cell of `step01_development.ipynb`. One development run, saved by the queue at 2026-10-13T04:54:08. 123 validation trials and 1 summary (124), note `re-run under new rules`, `test_window_touched` false on every row. The protocol budget is 3 × 44 + 1 = **133**. The development span has 41 periods, so the run logged 3 × 41 + 1 = 124, inside the budget. The 2005-2014 exploration was not re-run. The run was not repeated.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** Development end **2025-07-17**. Last price date loaded before the cut **2025-08-13**. Both are printed in the notebook. The session count is the sum of `session_count` in `period_data.csv`. Numbers below are the notebook's 6-decimal prints unless a file is named.
- **Prior-only path: printed 0.409471 vs buy-and-hold 1.990442** (+40.95% vs +199.04%). About 3.41% a year vs 11.31% a year, from those two printed total returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market printed 0.847438 (84.74%). 9 exits. 7 of 41 periods beat buy-and-hold (sign-test p = 0.999998); mean period excess −0.018026 (SD 0.036355, t = −3.17), from `summary_data.csv`. MDE printed 0.015897 per quarter (0.063590 per year). Annualized log excess printed **−0.072794**, 6-month block interval [−0.126870, −0.028487] (124 months, `summary_data.csv`). The 1-month interval is printed [−0.126744, −0.023709]. Both intervals lie below 0. The saved `log_supported` flag is false.
- Maximum drawdown −0.299767 vs −0.342106, the minima of `performance_over_time_data.csv`. The printed success flags are all false. Comparable return would require 1.791398. The path is 0.409471.
- Baselines on the same span, printed: random-exit median **1.653326**, random-re-entry median **0.274653**. The path beats a printed fraction 0.000000 of the 20 random exits (0 of 20) and 0.900000 of the 20 random re-entries (18 of 20). It is below the exit median and above the re-entry median. The information test needs both families. It fails.
- Optimistic, labelled after the fact: candidate `k5` chains to printed **1.146789** against printed buy-and-hold **1.990442**. That chain is not the prior-only path.
- Activity, printed: turnover 1.857974 per year, 20 trades, 13 candidate switches (1.271246 per year in `summary_data.csv`).

**Calibration (i), shared bounds.** Computation on the saved files only. No replay and no new trial. Three quarters match on both ends: 2016-01-19 → 2016-04-15, 2021-01-19 → 2021-04-16, 2022-01-18 → 2022-04-14. All 3 candidates (9 rows) are compared at `NUMERIC_TOLERANCE` 1e-6.

**Returns: 0 / 9 matched.** Maximum absolute difference of total return **0.013465901489074797**. Buy-and-hold on the same 9 rows: 0 / 9 matched, maximum absolute difference 4.771406598820527e-5.

**Prior-only selections: 1 / 3 matched.** Archived `k4` vs v2 `k3` on 2016-01-19. Both `k3` on 2021-01-19. Archived `k4` vs v2 `k5` on 2022-01-18. Cause: the same schedule shift as exp04. The return gaps are far above 1e-6, so the tolerance tie order is not what splits the selections.

**Calibration (ii), old bounds.** Finished at 2026-10-13T16:01:12. Log `logs/exp07_warning_lights_exit_calibration_20261013_1536.log`. Summary `exp07_warning_lights_exit_v2/old_bounds_calibration/summary_data.csv`. One note row, `old-bounds calibration; diagnostic; informs no decision`, `test_window_touched` false. It was not repeated.

41 archived quarters were kept (warmup 2,588 sessions). **Returns: 123 / 123 matched** within 1e-6. Buy-and-hold matched on the same 123 rows. **Prior-only selections: 41 / 41 matched.** Maximum absolute difference of total return **1.6653345369377348e-16**. That gap is floating-point rounding of the same rules on the same bounds. No selection changed.

**Verdict: STOP.** The stopping rule is STOP when the prior-only path does not beat buy-and-hold, or does not beat the median of both random families. Printed path 0.409471 is below printed buy-and-hold 1.990442 and below the random-exit median 1.653326. This is not a candidate result. No holdout evaluation was run. No further version may follow from this result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that sold when enough warning lights were on got to +41%. It was in the market about five sessions in six. A random exit with the same buy-back finished at +165%, ahead of the lights on every one of the 20 draws. Buying back at random after the lights' own sales finished at +27%, and the rule beat 18 of those 20. The lights did not improve the sale. They mostly sat through the declines and then gave ground while waiting to buy back.

Mathematically: the prior-only total return is 0.409471 and buy-and-hold is 1.990442, so the difference of total returns is −1.580971. The annualized log excess is −0.072794 per year. Its 6-month block interval [−0.126870, −0.028487] does not contain 0.

## exp07_warning_lights_exit

*2026-10-14.* The version 2.0 re-run is recorded in `exp07_warning_lights_exit_v2`. This protocol 1.0 entry is unchanged.

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §9: the primary criterion and the information test fail).
Pre-registered in commit `f93e77e` (`preregister exp07`, before any run; config, rules and tests in `30c8c96`); config
hash `2965fad3e3`. Trials: 3 exploration, 132 validation and 1 summary (2026-10-06), 136 in total against a budget of
140. Numbers below are copied from the saved outputs of `step01_exploration.ipynb` and `step02_continuous_replay.ipynb`.

*Correction 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`, I1): the line above
says "config, rules and tests in `30c8c96`" without stating that this design commit fixed a **deviation from the
roadmap**: the re-entry rule (below) dropped the roadmap's "or by exp06's buy-stop" option. The commit message of
`30c8c96` says "before reading exp06 step02 outputs"; this cannot be verified: the commit (14:49:13) came 51 s after
exp06 step 02 logged its summary in the trial log (14:48:22), and exp07's protocol motivation cites exp06's result
("wrong four times out of five"). The re-entry choice is therefore **possibly informed by exp06's results (cannot be
verified)**; the direction of its effect on exp07's result is unknown (the buy-stop variant was never run). The light
thresholds and the grid k ∈ {3, 4, 5} came from the roadmap, fixed before exp04-exp06 were run, and are unaffected.*

Rule: 5 fixed warning lights (close below the 200-session average; negative 250-session return; 20/60-session
volatility ratio > 1.2; more than 10% below the all-time high; 60-session high older than 20 sessions). Exit when at
least k are on, buy back when fewer than k − 1 are on. Grid k ∈ {3, 4, 5}.

**Step 01, exploration 2005-01-03 → 2014-12-31 (context only).** Share of decisions with at least 3 / 4 / 5 lights on:
24.9% / 14.1% / 2.7%. Buy-and-hold +69.02% (drawdown −56.44%). k = 3: +42.71% (14 exits); k = 4: **+74.56%** (11 exits);
k = 5: **+136.41%** (2 exits, 90.7% in the market, drawdown −21.93%; log excess +3.36%/yr [−2.56%, +12.70%]). Observed:
every winning candidate wins through one 2008 episode (k = 5: exit 2008-06-27 at 127.69, buy-back 2009-04-29 at 87.27,
S/R 1.4632; k = 4: S/R 1.4168); all its other exits, but one, bought back higher.

**Step 02, continuous replay over the 44 validation periods (2015-04-17 → 2026-04-15).** Schedule asserted identical to
exp03's; bars cut at 2026-04-15.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). k = 3 +95.07% (18 exits), **k = 4
  +115.60%** (12 exits, 84.1% in the market; −3.99%/yr [−7.65%, −0.83%]), k = 5 +101.90% (8 exits, 0 bought back lower).
  All three log-excess intervals lie below 0.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +49.09% vs buy-and-hold +229.74%** (annualized 3.79% vs
  11.77%), below every candidate after the fact, because switching k at period boundaries added exits. 84.4% in the
  market, 12 exits, mean 37.5 cash decisions per episode. 18 of 43 periods won (sign test p = 0.889); mean period excess
  −1.85% (SD 3.73%, t = −3.25); MDE 1.59% per period (6.37% per year).
- Annualized log excess **−7.33%/yr**, 95% interval (6-month blocks) [−12.55%, −3.49%] (1-month blocks [−12.28%,
  −2.46%]): the loss is statistically supported. Sharpe 0.33 vs 0.71; max drawdown −31.44% vs −34.21%; comparable,
  Sharpe and drawdown flags all False. Excess −180.58% / −180.65% / −180.82% at 0 / 1 / 2 cents.
- Information test failed: random exits with the same re-entry rule (median of 20) +183.31%, the path beats **0 of 20**;
  random re-entries after the same exits (median) +52.66%, the path beats **7 of 20** (35%).
- Scorecard: 12 episodes, **0 bought back lower**, product of S/R 0.4521. Largest loss: exit 2020-03-19 at 240.99,
  buy-back 2020-05-27 at 303.50 (S/R 0.7940; SPY +25.93% while out). The 2022 bear market gave three exits, all bought
  back higher (S/R 0.9478, 0.9670, 0.9055). The last episode (exit 2026-04-01) is open at the end and valued at the last
  close. Selections: k = 3 governed 12 periods, k = 4 17, k = 5 15.
  *Clarification 2026-10-06, after the independent audit (I4): "12 episodes, 0 bought back lower" means **11 closed
  episodes, all bought back higher, plus 1 episode open at the end** (exit 2026-04-01 at 655.35, valued at the last
  close 699.85, also above the sale price). The summary table's "all 12 exits bought back higher" should be read the
  same way.*

*Mathematically:* final equity ÷ buy-and-hold = 1.4909 ÷ 3.2974 = 0.452 = Π S/R (0.4521). Every factor is below 1:
Σ log(S/R) = log 0.452 = −0.79, about −0.066 per episode. A k-of-5 vote of lagging lights turns on after much of a fall
and turns off after much of the rebound, so with fast (V-shaped) declines the buy-back price is above the sale price.
*In plain words:* the warning lights worked in 2008, a slow bear market, and that one exit made the 2005-2014 result.
On 2015-2026 the declines were fast (2018, 2020, 2022, 2025): the lights agreed near the bottoms and cleared only after
the recovery, so each of the 12 exits lost money, and random exits at the same frequency did better every time.

What this supports: on the validation span, requiring several lagging warnings at once does not fix the problem of
exp04; the exits are late and the buy-backs later. What it does not support: any statement about slow bear markets in
general (one episode, 2008, in the exploration span only).

## Shared code change for exp06 (2026-10-06, agent; no trial)

*Implemented and tested.* `so/core/reentry_simulation.simulate_stop_reentry_dict` gained a backward-compatible
cooling-off: a re-entry rule may set `episode_dict["exit_block_sessions"] = c`, and the exit signal is then ignored for
the c decisions after that re-entry. Without the key (every rule of exp01-exp05) the behaviour is unchanged: the
block ends at the re-entry session itself. Checks: all 7 test suites pass (the new `tests/test_exp06.py` verifies
both cases), and exp04 step 01's numbers were recomputed with the changed simulator on the exploration data (not logged,
not a trial): textbook rule +50.39% with 33 exits, x = 5%, n = 10 +116.85% with 2 exits, identical to the saved outputs.

## Shared code change for exp12 (2026-10-09, agent; no trial)

*Implemented and tested.* `so/core/reentry_simulation.simulate_stop_reentry_dict` gained a backward-compatible
fresh-exit option for exp12's M1 / M2 rules: a re-entry rule may set `episode_dict["require_fresh_exit"] = True`; if the
exit signal is on at that re-entry decision, the simulator ignores it until it has been off on at least one decision
(a state flag, cleared by the first decision with the signal off; causal). Without the key (every rule of exp01-exp08)
the behaviour is unchanged. Checks: all 12 test suites pass (`tests/test_exp12.py` verifies the option with and without
the key, and that unmodified E1 / E2 replays equal exp04 / exp07 exactly); exp12 step 02 asserts the real-data
reproduction of exp04 (+108.03%, 35 exits) and exp07 (+115.60%, 12 exits) before printing any exp12 number.

## VIX data layer (2026-10-09, agent; shared code, no trial)

*Implemented and tested* (roadmap 2026-10-09, step 0.4): `so/paths.py` (the four raw folders of
`store01_rawzone/ibkr_vix_family/`), `so/vix_config.py` (every VIX constant; `so/config.py` unchanged),
`so/features/vix_features.py` (loaders with a required cutoff that refuse 2026-05-14 and later, the per-session table of
the `_prev` and `_intraday` values, the six features), `tests/test_vix_features.py` (added to `tests/run_all_tests.py`;
10 suites pass). The staging folder and the three backup folders next to the raw folders are never read.

*Observed* (`pipeline/step07_VIX_data_check.ipynb`, run once on 2026-10-09, every load cut at 2026-04-15; last SPY,
VIX and VIX3M dates loaded: 2026-04-15 for all four series):

- Rows read: VIX daily 5,148 (2005-10-03 → 2026-04-15), VIX 1-minute 2,996,586 on 5,145 dates; VIX3M daily 4,193
  (2009-08-12 → 2026-04-15), VIX3M 1-minute 1,675,264 on 4,190 dates. SPY sessions 5,353 (2005-01-03 → 2026-04-15).
- **Missing vs known gaps:** every missing date is in the known-gap list of the inventory (VIX daily 17 = the 15
  sessions of 2006-05-01 → 2006-05-19, 2006-11-24, 2011-09-12; VIX3M daily 1 = 2011-09-12; VIX3M 1-minute 4 =
  2011-09-12, 2017-10-20, 2017-10-23, 2017-10-24), except the 4 half days left in staging for VIX 1-minute (2020-11-27,
  2020-12-24, 2024-07-03, 2024-12-24), as expected. One VIX date (2007-07-02, daily and 1-minute) has no SPY session (the
  SPY session is missing in the IBKR data).
- **`_prev` (primary) per series, sessions to 2026-04-15:** VIX: 5,151 usable (5 of them with a lag of 1-3 sessions:
  2006-11-27 after the missing 2006-11-24, 2011-09-13, and three in the 2006-05 gap), **12 stale** (2006-05-05 →
  2006-05-22, NaN), 0 missing, 190 before the first date. VIX3M: 4,193 usable (1 lagged, 2011-09-13), 0 stale, 0 missing,
  1,160 before 2009-08-12 (or on it).
- **`_intraday` (secondary) fallbacks to `_prev`:** VIX 20 (the 15 sessions of 2006-05, 2011-09-12 and the 4 staged half
  days); VIX3M 4 (2011-09-12 and 2017-10-20/23/24). Where a bar exists, the chosen bar is always exactly the allowed one
  (decision − 1 minute: 15:57, or 12:57 on half days): 5,144 VIX and 4,190 VIX3M sessions at distance 0, none earlier.
- **Daily close vs last 1-minute close** (agreement = within 0.005 points): VIX 5,010 of 5,144 dates (97.4%), VIX3M
  3,745 of 4,190 (89.4%); median absolute difference 0.00, 99th percentile 0.02 (VIX) and 0.03 (VIX3M). The disagreements
  cluster in 2021-2022 for VIX (48 and 58) and 2022-2026 for VIX3M (71 to 124 a year). A few are large: VIX 2026-01-16
  (daily 18.84 vs 15.86), 2025-06-18 (22.17 vs 20.14), 2025-05-23 (20.57 vs 22.29); VIX3M 2014-07-17 (14.97 vs 12.63).
  Cause unknown (not investigated; the IBKR data was not compared with Cboe's values). The primary timing uses the daily
  close, so these dates enter the primary features.
- **Session window per era (most frequent first / last bar label):** VIX 09:31-15:59 (2005-2011), 09:31-16:14
  (2012-2015), 03:15-16:14 (2016-2021), 03:15-16:59 (2022-2026); VIX3M 09:31-15:59 (2009-2011), 09:31-16:14 (2012-2026).
- **Features:** `vix_level_prev` from 2005-10-04 (median 17.07, 1%-99% 9.90-55.86, max 82.69); `vix_pct250_prev` from
  2007-05-22 (the 2006-05 gap blocks the 250-value window for a year, as specified); `vix_term_prev` from 2009-08-13
  (median 0.886, 99th percentile 1.144, max 1.344); `vix_fade` is never positive, `vix_pct250` lies in [0, 1] (asserted).
  Correlation between the two timings of the same feature: level 0.976, pct250 0.949, chg5 0.744, fade 0.878, term 0.911,
  vrp 0.946.

What this supports: the data layer reads only what it should, the timings behave as specified, and the gaps are the
known ones. What it does not support: that the IBKR index values equal Cboe's official values, or that the 1-minute bar
labels are start-of-minute labels (the convention is unproven; the 1-minute lag is a margin). Tables saved in
`store04_experiments/vix_data_layer/step07_VIX_data_check/`.

## exp08_vix_signal_check

**Protocol 1.0. Status: DONE; the gates close the VIX line** (PROTOCOL.md §5 and §7). Pre-registered in commit
`2c810d1` (2026-10-09 12:52:51, `preregister exp08`, protocol, config, code, tests and the notebook without outputs);
run once with `step01_vix_gate.ipynb` (first trial logged 2026-10-09T12:55:00); config hash `43e86ccb06`. Trials: 6
(stage `signal_check`: G1, G2, G3, G4, G1 intraday, G2 intraday; budget 10), all with `test_window_touched` False.
Numbers below are copied from the saved notebook outputs and from the CSV files in
`store04_experiments/exp08_vix_signal_check/step01_gate_data/`.

*Windows and data.* Schedule asserted: 44 folds, first train_end 2015-03-18, first valid_start 2015-04-17, last
valid_end 2026-04-15, latest test_start 2026-05-14 (never read). SPY bars and every VIX loader cut at 2026-05-13: last
SPY date loaded 2026-05-13 (5,373 sessions from 2005-01-03); last VIX daily, VIX3M daily, VIX 1-minute and VIX3M
1-minute dates loaded 2026-05-13. Largest session used by any label or forward volatility: 2026-05-13 (asserted).
Analysis rows (`_prev`): 4,193 sessions 2009-08-13 → 2026-04-15 (the first `vix_term_prev` needs a VIX3M close dated
before the session, so the rows start one session after 2009-08-12; the `_intraday` rows start on 2009-08-12, 4,194);
training 1,408 rows (2009-08-13 → 2015-03-18, share of positive labels 0.686); validation 2,765 rows (the 44 replay
periods 2015-04-17 → 2026-04-15, share 0.671).

*Observed (primary, `_prev`).*
- **G1 univariate: FAIL.** 30 bins tested (6 features × 5), **S1 = 0** signal pairs. On training, 2 bins were above
  the base rate (`vix_term_prev` (0.908, 0.946]: 0.786, interval low 0.698; `vrp_prev` above 0.0245: 0.816, low 0.731);
  on validation none was above or below (0.686 and 0.732 against 0.671, intervals include it). Null: all 19 shifted
  runs give S1 = 0; max 0, p = (1 + 19) / 20 = 1.00. S1 = 0 never passes.
- **G2 incremental AUC: FAIL.** Pooled out-of-sample AUC on 2,765 predictions: BASE (16 price features) **0.4233**
  [0.3648, 0.4829], AUGMENTED (16 + 6 VIX) **0.4592** [0.3995, 0.5174] (1-month blocks); **dAUC +0.0359**
  [−0.0025, +0.0709]; mean per-period dAUC +0.0714 (AUGMENTED better in 28 of 43 periods; period 34 has only positive
  labels, so its AUC is undefined). Training rows 1,408 (first fold) to 4,112 (last fold). Null dAUC of the 19 runs:
  +0.0043 to **+0.0563** (2 runs ≥ the real value: +0.0408, +0.0563); **p = 0.15**; the real value is not above the
  null maximum.
- **G3 volatility forecast: PASS.** 2,765 validation decisions, 133 months: Spearman(`vix_level_prev`, realized
  volatility of the next 20 sessions) 0.6357, Spearman(`daily_volatility`, same) 0.5193; **D = +0.1165**, 95% interval
  (circular 6-month blocks, 2,000 iterations) [+0.0441, +0.2227]; lower bound > 0.
- **G4 plausibility of unlevered volatility scaling: FAIL.** Top VIX quintile = `vix_level_prev` ≥ 22.94 (training
  80th percentile). Mean `fwd_net_return_20d`: training 282 rows (27 months) **+1.91%** [+0.89%, +2.94%]; validation 538
  rows (56 months) **+2.82%** [+1.60%, +3.90%]. Both means are above 0 (the gate needs both below 0), with intervals
  above 0.

*Observed (secondary, `_intraday`; reported, never a gate).* G1: S1 = 0 of 30 (1 training bin above the base rate,
`vrp_intraday` above 0.0246), null max 0, p = 1.00, would not pass. G2: BASE 0.4230, AUGMENTED 0.4521, dAUC +0.0291
[−0.0053, +0.0609], null max +0.0628, p = 0.25, would not pass. No "candidate pending review (secondary timing)".

*Gate decisions (as pre-registered, primary results only):* exp09 needs G1 or G2: **not run**. exp10 needs G3 and G4:
**not run** (G3 passes, G4 fails). exp11 needs G2: **not run**. **"No usable VIX information under the pre-registered
gates": the VIX line stops.**

*Descriptive (no gate, no trial).* Mean 20-session forward return by `vix_level_prev` quintile (training edges 13.87,
16.26, 18.56, 22.94), lowest to highest: training +0.44%, +0.31%, +1.11%, +1.57%, +1.91%; validation +0.49%, +0.47%,
+0.80%, +0.51%, +2.82%. By term structure: `vix_term_prev` ≥ 1 (inverted) training +2.43% (106 rows), validation +3.07%
(220 rows); < 1 training +0.96%, validation +0.81%. 106 inverted episodes (326 sessions) from 2009-10-29 to 2026-04-08
(table `term_episode_data.csv`).

*Mathematically.* G2: AUC is the probability that a random positive-label session gets a higher predicted probability
than a random negative one. The BASE model scores 0.423 out of sample, i.e. worse than a coin (0.5): its training
relations reverse on validation. Adding six columns with no real link to the label (the null: VIX columns shifted by
1,347 to 3,118 sessions) raises the AUC in **all 19 runs** (+0.004 to +0.056), because with the same regularization
(C = 0.1) the extra columns dilute the BASE model's (wrong-signed) weights and pull its predictions towards chance. The
real VIX columns give +0.036, inside that range (rank 3 of 20), so the improvement is what noise columns also produce.
G4: an unlevered exposure w ≤ 1 can only beat buy-and-hold if the sessions where w < 1 earn less than cash (0% here);
E[r | VIX in the top quintile] = +1.91% and +2.82% per 20 sessions, more than the unconditional means, so lowering
exposure when the VIX is high gives up the best 20-session returns of both windows. G3 holds (the VIX forecasts
volatility better than trailing volatility, ρ 0.636 vs 0.519), but a better volatility forecast only helps if high
volatility comes with low returns, and G4 shows the opposite.
*In plain words.* The VIX does not tell us when SPY will rise or fall over the next month, on its own (G1) or on top of
the price features (G2: the small gain is the same as adding random columns to a model that was already worse than
guessing). The VIX is a good forecast of how bumpy the next month will be (G3), but bumpy months after a high VIX were,
on average, good months to own SPY (G4): selling or holding less when fear is high would have missed the rebounds.
This is the same lesson as exp04-exp07, now with option-market data.

What this supports: under the pre-registered gates, the VIX and VIX3M features (as built, `_prev` timing) add no usable
information about the 20-session direction of SPY on 2009-2026, and high-VIX periods did not have returns below cash,
so none of exp09-exp11 can run. What it does not support: that the VIX carries no information at any horizon or in any
model (only the six features, one horizon, 5-bin checks and one regularized logistic were tested); anything about
leverage (not allowed here); anything about the untouched window. The descriptive pattern (higher forward returns after
a high or inverted VIX) is not tested and is not a trading result: it rests on few episodes (2011, 2015-16, 2018, 2020,
2022, 2025) and is the kind of pattern the gates were designed not to chase.

*Corrections 2026-10-09, after the independent audit of 2026-10-09 (the text above is unchanged):*
- *A2: in "Mathematically", the sentence "because with the same regularization (C = 0.1) the extra columns dilute the
  BASE model's (wrong-signed) weights and pull its predictions towards chance" is an inference, not a tested result.
  Read instead: "consistent with the extra columns diluting the BASE model's wrong-signed weights (an inference, not
  tested)".*
- *A1: exp09's gates (G1: share of positive 20-session returns per bin; G2: ranking of their sign) tested the sign of
  forward returns, while exp09's mechanism concerns their size after fear peaks; G1 also had little power (1,408
  overlapping training sessions, every null run S1 = 0). The descriptive pattern (higher mean returns after a high or
  inverted VIX) was not tested by exp08.*

## exp12_vix_fear_reentry_v2

**Protocol 2.0. Status: STOP.** Label: re-run under the new rules, not new evidence. Data-dependent follow-up of exp08, as protocol 1.0. Pre-registered in commit `f5eb885` (2026-10-12 23:50:19 +0300). The numeric-tolerance amendment `98115f0` (2026-10-13 00:36:32 +0300) is in the code that ran. Config hash `ce0c36109b`, printed in the header cell of `step01_development.ipynb`. One development run, saved by the queue at 2026-10-13T05:59:47. 246 validation trials and 1 summary (247), note `re-run under new rules`, `test_window_touched` false on every row. The protocol budget is 6 × 44 + 1 = **265**. The development span has 41 periods, so the run logged 6 × 41 + 1 = 247, inside the budget. The 2009-2014 exploration was not re-run. The run was not repeated.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** Development end **2025-07-17**. Last price date loaded before the cut **2025-08-13**. Both are printed in the notebook. The session count is the sum of `session_count` in `period_data.csv`. Numbers below are the notebook's 6-decimal prints unless a file is named.
- **Prior-only path: printed 1.265069 vs buy-and-hold 1.990442** (+126.51% vs +199.04%). About 8.32% a year vs 11.31% a year, from those two printed total returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market printed 0.918090 (91.81%). 25 exits. 16 of 41 periods beat buy-and-hold (sign-test p = 0.941362); mean period excess −0.007683 (SD 0.034024, t = −1.45), from `summary_data.csv`. MDE printed 0.014878 per quarter (0.059514 per year). Annualized log excess printed **−0.026885**, 6-month block interval [−0.070945, 0.018952] (124 months, `summary_data.csv`). The 1-month interval is printed [−0.068653, 0.020902]. The 6-month interval contains 0 and extends below 0. The saved `log_supported` flag is false.
- Maximum drawdown −0.256088 vs −0.342106, the minima of `performance_over_time_data.csv`. The printed success flags are all false. Comparable return would require 1.791398. The path is 1.265069.
- Baselines on the same span, printed: unmodified path **0.687545**; random-exit median **1.702518**; random-re-entry median **0.805662**. The path beats a printed fraction 0.050000 of the 20 random exits (1 of 20) and 0.850000 of the 20 random re-entries (17 of 20). Printed information test **False**. The path is above the unmodified path and above the re-entry median, and below the exit median. Printed equity ratio 0.757436 over 25 episodes.
- Optimistic, labelled after the fact: candidate `E1M1` chains to printed **2.225343** against printed buy-and-hold **1.990442**. That chain is not the prior-only path. It is the same after-the-fact reading protocol 1.0 already recorded, on the shorter development span.
- Activity, printed: turnover 4.987194 per year, 52 trades, 17 candidate switches (1.662398 per year in `summary_data.csv`).

**Calibration (i), shared bounds.** Computation on the saved files only. No replay and no new trial. Three quarters match on both ends: 2016-01-19 → 2016-04-15, 2021-01-19 → 2021-04-16, 2022-01-18 → 2022-04-14. All 6 candidates (18 rows) are compared at `NUMERIC_TOLERANCE` 1e-6.

**Returns: 0 / 18 matched.** Maximum absolute difference of total return **0.013568205204357399**. Buy-and-hold on the same 18 rows: 0 / 18 matched, maximum absolute difference 4.771406598820527e-5.

**Prior-only selections: 3 / 3 matched.** The rule in force is `E2M3` on 2016-01-19, `E1M1` on 2021-01-19, and `E2M3` on 2022-01-18, in both the archived file and the v2 file. The candidate returns on those quarters still differ. Cause of the return gap: the same schedule shift as exp04. A period score is a slice of one continuous path, and the earlier quarters do not share bounds. The selection happened to agree on these three quarters. The return gaps are far above 1e-6.

**Calibration (ii), old bounds.** Finished at 2026-10-13T16:48:49. Log `logs/exp12_vix_fear_reentry_calibration_20261013_1601.log`. Summary `exp12_vix_fear_reentry_v2/old_bounds_calibration/summary_data.csv`. One note row, `old-bounds calibration; diagnostic; informs no decision`, `test_window_touched` false. It was not repeated.

41 archived quarters were kept (warmup 2,588 sessions). **Returns: 246 / 246 matched** within 1e-6. Buy-and-hold matched on the same 246 rows. **Prior-only selections: 41 / 41 matched.** Maximum absolute difference of total return **1.97758476261356e-16**. That gap is floating-point rounding of the same rules on the same bounds. No selection changed.

**Verdict: STOP.** The protocol says: if the prior-only path does not beat buy-and-hold, STOP, and the VIX line stays closed. Printed path 1.265069 is below printed buy-and-hold 1.990442. This is not a candidate result. No holdout evaluation was run. No further version may follow from this result.

In plain words: over these ten years the account that stayed in SPY almost tripled (+199%), and the account that sold on the trend or the warning lights and bought back when the previous session's VIX had fallen got to +127%. The same exits without the VIX modifications got to +69%, so the VIX rules added something on this span. A random exit with the same buy-back finished at +170%, ahead of the VIX path on 19 of the 20 draws. The VIX modification did not beat chance at choosing when to sell. The rule chosen after seeing every period, E1M1 at +223% against +199%, could not have been selected in advance. The path that could have been is the +127% one. The VIX line stays closed.

Mathematically: the prior-only total return is 1.265069 and buy-and-hold is 1.990442, so the difference of total returns is −0.725373. The annualized log excess is −0.026885 per year. Its 6-month block interval [−0.070945, 0.018952] contains 0.

## exp12_vix_fear_reentry

*2026-10-14.* The version 2.0 re-run is recorded in `exp12_vix_fear_reentry_v2`. This protocol 1.0 entry is unchanged.

**2026-10-09, protocol 1.0, config hash `eec3977199`, agent (autonomous mode). Status: STOP; the VIX line is closed
definitively.**

*Disclosure (read first).* exp12 is a **data-dependent** follow-up of exp08: Nicolas decided to run it on 2026-10-09
after seeing exp08's descriptive table (top-quintile VIX forward return +2.82% vs about +1%; inverted term structure
+3.07% vs +0.81%), **overriding exp08's pre-registered gate** (G1 S1 = 0, p = 1.00; G2 dAUC +0.0359 vs null max +0.0563,
p = 0.15), partly on audit point A1 (the gates tested the sign of forward returns, the mechanism concerns their size).
The **rules are not data-dependent on exp08**: they are exp09's rules, sent before exp08 ran (roadmap commit `5131de7`
at 12:20:21; exp08's first trial 12:55:00), with one change made before any exp12 run: the `_intraday` variant was
dropped (6 candidates, `_prev` only). They carry **hindsight** of the 2018, 2020, 2022 and 2025 declines. 2015-2026 is
development data, reused here for the **ninth** time. This was declared the **last** VIX re-entry test.

*Pre-registration:* commit `1e6a2e6` (2026-10-09 14:30:48 +0300); first exp12 trial logged at 14:31:19. Roadmap commit
`6bfd642` (14:15:21), audit corrections `ca86bd0` (14:15:58). Shared code: the backward-compatible fresh-exit option of
the simulator (section "Shared code change for exp12").

*Windows and data (observed, notebook outputs).* Step 01: SPY and VIX cut at 2015-03-18 (last SPY, VIX and VIX3M dates
loaded 2015-03-18), continuous paths 2009-08-13 → 2014-12-31 (1,356 sessions). Step 02: 44 periods asserted (first
valid_start 2015-04-17, last valid_end 2026-04-15, latest test_start 2026-05-14, never read); SPY cut at 2026-04-15,
VIX cutoff 2026-04-15 (last SPY, VIX and VIX3M dates loaded 2026-04-15); no missing VIX feature on either span.
`test_window_touched` is False on all 271 rows.

*Reproduction asserts (step 02, before any exp12 number): PASSED.* Unmodified E1 +108.03% with 35 exits; unmodified E2
+115.60% with 12 exits; buy-and-hold +235.39% (full span) and +229.74% (prior-only span from 2015-07-17).

*Step 01, exploration (6 trials, stage `exploration`), 2009-08-13 → 2014-12-31, buy-and-hold +104.57%:*

| Candidate | Total return | vs unmodified exit | Exits | VIX buy-backs | Product S/R | In market |
|---|---|---|---|---|---|---|
| E1M1 | +104.51% | +55.51 pts (E1 +49.00%) | 16 | 9 | 1.0008 | 94.5% |
| E1M2 | +71.25% | +22.25 pts | 16 | 5 | 0.8381 | 91.5% |
| E1M3 | +51.98% | +2.98 pts | 14 | 0 | 0.7437 | 90.2% |
| E2M1 | +84.25% | +23.12 pts (E2 +61.14%) | 10 | 6 | 0.9013 | 96.9% |
| E2M2 | +66.38% | +5.25 pts | 11 | 5 | 0.8141 | 94.8% |
| E2M3 | +74.76% | +13.62 pts | 7 | 0 | 0.8546 | 96.5% |

Every candidate beats its unmodified exit and none beats buy-and-hold (E1M1 is 0.07 points short).

*Step 02, validation (264 candidate-period trials + 1 summary), copied from `step02_continuous_replay.ipynb`:*
- **Optimistic best after the fact:** E1M1 +314.80% vs buy-and-hold +235.39%, annualized log excess +1.92%
  [−1.13%, +6.03%] (6-month blocks), in market 94.0%, 35 exits. E2M1 +235.60% (≈ buy-and-hold); E1M2 +195.83%, E2M3
  +168.95%, E2M2 +167.51%, E1M3 +132.68%. **Optimistic**: chosen after seeing all six, and its interval includes 0.
- **Prior-only path (the honest estimate):** **+119.24% vs buy-and-hold +229.74%** (2015-07-17 → 2026-04-15, 10.72
  years; annualized 7.60% vs 11.77%). Annualized log excess **−3.77% [−7.95%, −0.37%]** (6-month blocks; 1-month blocks
  [−7.80%, +0.30%]). Periods won 7 of 43 (sign test p = 1.000); mean period excess −1.00% (t = −2.38); MDE 1.18% per
  period (4.72% per year). Time in market 89.5%; 29 exits. Sharpe 0.60 vs 0.71; max drawdown −27.86% vs −34.21%.
  Costs at 0 / 1 / 2 cents: +119.88% / +119.24% / +118.79%.
- **Baselines:** unmodified prior-only path over {E1, E2} +82.88% (in market 83.7%, 24 exits, log excess −5.44%
  [−9.64%, −1.78%]): exp12's path beats it. Random exits (same re-entry rule): median +187.43%, the path beats **0 of
  20**. Random re-entries (same exits): median +90.60%, the path beats 13 of 20 (65%).
- **Verdict (pre-registered): PRIMARY FAILS → STOP.** The information test also fails (it beats the unmodified path and
  the random re-entries, not the random exits).
- Selections (periods chosen): E1M1 20, E2M1 7, E2M2 7, E2M3 5, E1M2 3, E1M3 2. Many pooled scores are exactly 0
  (ties, decided by the fixed tie order).

*Concentration (pre-registered reports).*
- (a) Final equity / buy-and-hold 0.6649 = product of the 29 S/R 0.6661 (the difference is costs and cash residues).
  Without the episode with the largest log(S/R): 0.6258; without the two largest: 0.5915; neither beats buy-and-hold.
- (b) Log excess per calendar year: 2015 −0.0870, 2016 −0.0457, 2017 −0.0002, 2018 −0.0049, 2019 −0.0506, 2020
  −0.0337, 2021 −0.0001, 2022 −0.0132, 2023 **−0.1855**, 2024 −0.0001, 2025 **+0.0237**, 2026 −0.0108. Only 2025 is
  positive.
- (c) 4 episodes overlap 2020-02-01 → 2020-06-30; their log(S/R) sum −0.0335 = 8% of the total log excess −0.4081
  (2020 did not carry the result, in either direction).

*Prior-only scorecard (29 episodes; exit → buy-back, S → R, S/R, sessions out, reason, VIX at exit → at buy-back):*
2015-09-22 → 10-05 194.15 → 198.51 0.9780 9 original 20.14 → 20.94; 2015-10-15 → 10-23 0.9743 6 original; 2015-11-12 →
11-18 0.9808 4 original; 2015-12-03 → 12-04 0.9806 1 original; 2015-12-09 → 12-15 1.0018 4 **M2**; 2015-12-17 → 12-29
0.9887 7 original; 2015-12-30 → 2016-01-12 1.0625 8 **M2** 16.08 → 24.30; 2016-01-25 → 03-11 0.9245 33 original;
2016-06-27 → 06-28 0.9825 1 original; 2018-04-02 → 04-03 0.9880 1 original; 2018-10-29 → 11-02 0.9698 4 **M2**;
2018-11-20 → 11-23 1.0033 2 **M2**; 2018-12-07 → 12-13 0.9937 4 **M2**; 2018-12-14 → 2019-01-07 1.0239 14 **M2** 20.65 →
21.38; 2019-03-08 → 03-11 0.9855 1 original; 2019-05-31 → 06-04 0.9816 2 original; 2020-02-27 → 03-02 0.9670 2 original
27.56 → 40.11; 2020-03-03 → 03-04 0.9589 1 original; 2020-03-05 → 04-17 302.65 → 286.55 1.0562 30 **M1** 31.99 → 40.11;
2020-06-26 → 06-29 0.9874 1 original; 2022-04-18 → 05-05 437.43 → 413.50 1.0579 13 **M1** 22.70 → 25.42; 2022-09-29 →
11-30 362.99 → 406.72 **0.8925** 43 original 30.18 → 21.89; 2022-12-05 → 2023-01-13 1.0028 27 original; 2023-01-18 →
02-01 0.9534 10 original; 2023-03-09 → 04-28 0.9423 35 original; 2023-10-20 → 10-24 0.9940 2 original; 2023-10-25 →
11-02 0.9696 6 original; 2025-04-03 → 04-10 537.72 → 524.85 1.0245 5 **M1** 21.51 → 33.62; 2026-03-20 → 04-01 0.9892 8
**M1** 24.06 → 25.25. (Full table with fills, buy-and-hold return out and costs:
`step02_continuous_replay_data/prior_only_scorecard_data.csv`.)

*Mathematically.* Final equity / buy-and-hold ≈ Π S/R = 0.6661 (29 episodes), so log excess ≈ Σ log(S/R) = −0.41. By
re-entry reason (computed from the saved scorecard, not a notebook output): the 4 M1 buy-backs multiply to 1.1324 (3
above 1), the 6 M2 buy-backs to 1.0538 (4 above 1), the 19 original-rule buy-backs to 0.5582 (1 above 1). The VIX
re-entries did what they were meant to do, and that was a gain of about +0.17 in log, while the episodes where the VIX
never fired before the price rule lost about −0.58. The random-exit baseline (median +187.43%, path beats 0/20): with
the same re-entry rule, exits at random dates with the same frequency did better in every run, which is consistent with
the exits' timing being the cost (an inference, not separately tested).
*In plain words.* Buying back when fear fades does buy back lower more often (10 VIX buy-backs, 7 below the sale
price), and it rescues 2020 and 2025. But the trend and lights exits still sell often in calm pullbacks where the VIX
never spikes or fades (2015-16, 2019, the autumn of 2022, 2023); those episodes wait for the price rule and buy back
higher, and they cost more than the VIX re-entries earn. The best candidate after the fact (E1M1, +314.80%) shows that
a good-looking path exists among six; the walk-forward selection could not find it in advance, because the candidate
that led recently was not the one that led next.

What this supports: on 2015-2026, under the pre-registered prior-only selection, exp09's VIX re-entry and exit-filter
rules on E1 and E2 do not beat buy-and-hold (−3.77%/yr, interval entirely below 0), and they lose to random exits with
the same re-entry rule. They do improve on the unmodified exits (+119.24% vs +82.88%) and beat 13 of 20 random
re-entries, which is consistent with some re-entry timing value in the VIX that is too small to pay for the exits.
What it does not support: anything about E1M1 alone (optimistic, interval includes 0, one of six chosen after the fact,
on data used nine times); anything about the untouched window (not read); other exits, horizons or VIX rules (none
may be tried: this was the last VIX re-entry test). Biases: dividends ignored (favours the path, which is out 10.5% of
the time), cash at 0% (penalizes it), informal costs. Trials the conclusion rests on: 271 exp12, 3,570 workspace,
7,659 with the 4,089 legacy trials.

*Override 2026-10-09 (Nicolas; the text above is unchanged):* Nicolas explicitly overrides exp12's pre-registered
commitment that it was "the last VIX re-entry test; no later version may be motivated by its results", to run
`exp13_e1m1_robustness`, a data-dependent robustness study of E1M1 (exp12's best candidate after the fact, +314.80% vs
+235.39%, optimistic). exp12's verdict stays STOP; "the VIX line is closed definitively" above is suspended until exp13
ends.

*Audit notes 2026-10-09 (documentation only; the text above is unchanged):*
- *B1: the prior-only log-excess interval is [−7.95%, −0.37%] with 6-month blocks and [−7.80%, +0.30%] with 1-month
  blocks (the latter includes 0).*
- *B3: in several periods all pooled scores were exactly 0 and the pre-registered tie order chose the candidate; the
  prior-only path partly reflects that order.*
- *B4: the split of the product of S/R by re-entry reason (M1 1.1324, M2 1.0538, original 0.5582) was computed after
  the run from the saved scorecard.*

## exp13_e1m1_robustness_v2

**Protocol 2.0. Status: candidate result pending review.** Label: re-run under the new rules, not new evidence. This is the frozen rule E1M1 as one candidate. Pre-registered in commit `a670d65` (2026-10-12 23:53:16 +0300). The numeric-tolerance amendment `98115f0` (2026-10-13 00:36:32 +0300) is in the code that ran. Config hash `01e19d8ab2`, printed in the header cell of `step01_development.ipynb`. One development run, saved by the queue at 2026-10-13T06:09:50. 41 validation trials and 1 summary (42), note `re-run under new rules`, `test_window_touched` false on every row. The protocol budget is 1 × 44 + 1 = **45**. The development span has 41 periods, so the run logged 1 × 41 + 1 = 42, inside the budget. Protocol 1.0 steps 01 to 04 (stress, neighbourhood, placebo, execution) were not re-run. The run was not repeated. There is no success claim.

**Step 01, development replay, 41 periods, 2015-04-20 → 2025-07-17 (2,577 sessions).** Development end **2025-07-17**. Last price date loaded before the cut **2025-08-13**. Both are printed in the notebook. The session count is the sum of `session_count` in `period_data.csv`. Numbers below are the notebook's 6-decimal prints unless a file is named. One candidate, so every period is E1M1.
- **Prior-only path: printed 2.738521 vs buy-and-hold 1.990442** (+273.85% vs +199.04%). About 13.76% a year vs 11.31% a year, from those two printed total returns and 2,577 sessions: (1 + R)^(252 / 2577) − 1. Time in the market printed 0.939053 (93.91%). 34 exits. 17 of 41 periods beat buy-and-hold (sign-test p = 0.894488); mean period excess +0.004878 (SD 0.033977, t = 0.92), from `summary_data.csv`. MDE printed 0.014858 per quarter (0.059430 per year). Annualized log excess printed **+0.021607**, 6-month block interval [−0.010373, 0.061984] (124 months, `summary_data.csv`). The 1-month interval is printed [−0.014278, 0.069471]. Both intervals contain 0 and extend below 0. The saved `log_supported` flag is false. The gain is not statistically supported.
- Maximum drawdown −0.247178 vs −0.342106, the minima of `performance_over_time_data.csv`. Printed flags: `primary_success` true, `secondary_success` true, `comparable_return` true, `all_baselines_beaten` true. 90% of buy-and-hold is 1.791398. The path is 2.738521, so the smaller drawdown is inside the secondary rule. These flags are the development comparison. They are not a success claim.
- Baselines on the same span, printed: unmodified E1 **0.933103**; random-exit median **1.757992**; random-re-entry median **1.218622**. The path beats a printed fraction 1.000000 of the 20 random exits (20 of 20) and 1.000000 of the 20 random re-entries (20 of 20). Printed information test **True**. Printed equity ratio 1.250157 over 34 episodes.
- The printed optimistic chain of the same candidate is **2.225343** against printed buy-and-hold **1.990442**. With one candidate there is nothing to choose. The chain multiplies period slices. The prior-only figure is one continuous path that carries the position. Protocol §4 already treats those as different objects. The chain is the same E1M1 slice product exp12 printed as its after-the-fact candidate.
- Activity, printed: turnover 6.747381 per year, 70 trades, 0 candidate switches.

**Calibration (i), shared bounds.** Computation on the saved files only. No replay and no new trial. The archived return rows are exp12's saved E1M1 quarters (`exp12_vix_fear_reentry/step02_continuous_replay_data/candidate_period_data.csv`), the same archive the old-bounds script uses. Three quarters match on both ends: 2016-01-19 → 2016-04-15, 2021-01-19 → 2021-04-16, 2022-01-18 → 2022-04-14.

**Returns: 0 / 3 matched** within `NUMERIC_TOLERANCE` 1e-6. Maximum absolute difference of total return **0.013568205204357399**. Buy-and-hold on the same 3 rows: 0 / 3 matched, maximum absolute difference 4.771406598820527e-5.

**Prior-only selections: 3 / 3.** E1M1 is the only candidate. `selection_data.csv` has E1M1 on all 41 periods, including these three. There is no other rule this experiment could have put in force. Cause of the return gap: the same schedule shift as exp04. A period score is a slice of one continuous path, and the earlier quarters do not share bounds. The gap is far above 1e-6. It is not a tie.

**Calibration (ii), old bounds.** Finished at 2026-10-13T16:57:09. Log `logs/exp13_e1m1_robustness_calibration_20261013_1648.log`. Summary `exp13_e1m1_robustness_v2/old_bounds_calibration/summary_data.csv`. One note row, `old-bounds calibration; diagnostic; informs no decision`, `test_window_touched` false. It was not repeated.

41 archived E1M1 quarters were kept (warmup 2,588 sessions). **Returns: 41 / 41 matched** within 1e-6. Buy-and-hold matched on the same 41 rows. **Prior-only selections: 41 / 41 matched.** Both sides are E1M1 on every quarter. Maximum absolute difference of total return **1.1796119636642288e-16**. That gap is floating-point rounding of the same rule on the same bounds.

**Verdict: the development stopping rule did not fire.** The protocol says STOP if E1M1 does not beat buy-and-hold, and that beating it is a candidate result pending review, not a robustness claim and not a success claim. Printed path 2.738521 is above printed buy-and-hold 1.990442. The notebook printed `CONTINUE`. Recorded status: **candidate result pending review**. Protocol 1.0's verdict, E1M1 IS NOT ROBUST, stands. Those steps were not re-run. The 6-month interval contains losses. Dividends are ignored and cash earns 0%. No holdout evaluation was run. That evaluation is parked for Nicolas. No further version may follow from this result.

In plain words: on this shorter span the frozen rule, sell on the textbook trend break and buy back when the previous session's VIX has fallen from its high since the sale, finished at +274% while staying in SPY finished at +199%. The same sale without the VIX buy-back finished at +93%. Random sales and random buy-backs both finished behind the rule on all 20 draws of each. The average year still cannot be separated from noise: the 6-month interval runs from about −1.0% a year to about +6.2% a year. The earlier robustness study, which this run did not repeat, already found that this rule fails when the window, the neighbours, and the placebos move. A higher number on the development span does not undo that study, and it is not a claim that the rule works.

Mathematically: the prior-only total return is 2.738521 and buy-and-hold is 1.990442, so the difference of total returns is +0.748079. The annualized log excess is +0.021607 per year. Its 6-month block interval [−0.010373, 0.061984] contains 0.

## exp13_e1m1_robustness

*2026-10-14.* The version 2.0 re-run is recorded in `exp13_e1m1_robustness_v2`. This protocol 1.0 entry is unchanged. Its verdict remains E1M1 IS NOT ROBUST.

**2026-10-09, protocol 1.0, config hash `c2e293d595`, agent (autonomous mode). Verdict: E1M1 IS NOT ROBUST. The VIX
line is closed.**

*Disclosure (read first).* This study is **data-dependent**. E1M1 was chosen **after the fact**: it is the best of
exp12's six candidates on 2015-04-17 → 2026-04-15 (optimistic, +314.80% vs buy-and-hold +235.39%, log excess +1.92%/yr
[−1.13%, +6.03%]). exp12's honest prior-only path made +119.24% vs +229.74% and STOPPED. **Nicolas explicitly overrides**
exp12's commitment that it was "the last VIX re-entry test" (2026-10-09), to run this robustness study of that one
frozen rule. Nothing here can turn E1M1 into out-of-sample evidence: 2015-2026 is development data reused for the
**ninth** time; 2005-2014 was explored by exp04-exp08. The rules carry **hindsight** of 2008, 2018, 2020, 2022 and 2025.
There is **no prior-only path**: every path is one continuous replay of a fixed rule. There is **no success claim**.

*Pre-registration:* commit `afe6b42` (2026-10-09 19:57:17 +0300); first exp13 trial logged at 19:57:49. Roadmap
`ce2df27` (19:38:34), audit notes B1/B3/B4 `cc243d6` (19:38:45). E1M1 is imported from exp12's code, never re-implemented.

*Reproduction asserts (observed, notebook outputs):* PASSED in steps 02, 03 and 04: frozen E1M1 +314.80% with 35
exits, unmodified E1 +108.03% with 35 exits, buy-and-hold +235.39%. Step 01 reproduced exp12 step 01 on 2009-08-13 →
2014-12-31: E1M1 +104.51%, E1 +49.00%, buy-and-hold +104.57%. Last dates loaded: step 01 SPY/VIX/VIX3M **2015-03-18**;
steps 02-04 DEV cutoff SPY/VIX/VIX3M **2026-04-15** (step 02 also loaded STRESS at 2015-03-18). `test_window_touched`
False on all 81 rows.

### Step 01 — stress 2005-2014 (`step01_stress_2005_2014.ipynb`)

STRESS window 2005-10-18 → 2014-12-31 (2,316 sessions; first session with both the 200-session average and
`vix_level_prev`). Numbers from the saved notebook outputs / `stress_path_data.csv`:

| Window | E1M1 | E1 (unmodified) | E2M1 | Buy-and-hold |
|---|---|---|---|---|
| STRESS 2005-10-18 → 2014-12-31 | **+53.32%** (33 exits, 93.5% in market, Π S/R 0.8881, log excess −1.31%/yr [−4.18%, +2.03%]) | +54.00% (33, 73.4%, 0.8921) | +58.26% (13, 96.4%, 0.9152) | **+73.09%** |
| Bear 2007-10-01 → 2009-08-12 | **−34.57%** (6 exits, 91.1% in market, Π S/R 0.9946) | **−5.65%** (6, **16.8%** in market, Π S/R 1.4348) | −33.18% (3, 91.1%, 1.0154) | **−34.16%** |
| exp12 exploration 2009-08-13 → 2014-12-31 | +104.51% (16, 94.5%, 1.0008) | +49.00% (16, 86.9%, 0.7291) | +84.25% (10, 96.9%, 0.9013) | +104.57% |

E1M1's STRESS scorecard: 33 episodes, 15 M1 and 18 original-rule buy-backs, 8 bought back lower. Episodes with an
exit in 2007-2009 (from the notebook print; one line each: exit → buy-back, S → R, S/R, sessions out, reason, VIX at
exit / max / re-entry; for M1, lowest close after the buy-back and drawdown from R):
2007-08-03 → 08-06 143.40 → 146.71 0.9774 1 original 21.43 / 25.31 / 25.31;
2007-08-14 → 08-21 143.05 → 144.96 0.9868 5 **M1** 26.40 / 31.65 / 26.36, low 143.66 (−0.90%);
2007-08-28 → 08-29 143.59 → 146.66 0.9791 1 original 22.66 / 26.39 / 26.39;
2007-09-07 → 09-11 145.85 → 147.60 0.9881 2 original 23.93 / 27.51 / 27.51;
2007-11-07 → 11-14 147.64 → 147.18 1.0031 5 **M1** 21.43 / 30.76 / 23.98, low 140.80 (−4.33%);
2007-12-11 → 12-12 148.30 → 149.14 0.9944 1 original 20.76 / 23.47 / 23.47;
2007-12-14 → 12-21 147.20 → 148.27 0.9928 5 **M1** 22.45 / 24.61 / 20.66, low 147.52 (−0.51%);
**2007-12-27 → 2008-02-01 147.39 → 139.35 1.0577 24 M1 18.73 / 30.86 / 26.14, lowest close 68.07 (−51.15%)**;
2009-06-22 → 06-25 89.35 → 92.03 0.9709 3 original 27.79 / 31.22 / 29.16;
2009-07-07 → 07-13 88.09 → 90.07 0.9780 4 original 29.19 / 30.94 / 28.98.

*Mathematically / in plain words.* On 2008 the unmodified trend exit stayed in cash (16.8% invested) and lost 5.65%
while buy-and-hold lost 34%. E1M1's M1 fade fired on 2008-02-01 (VIX 26.14 ≤ 0.85 × 30.86) and bought back at 139.35;
SPY then fell to 68.07 (−51%) before the next exit in June 2009. The fear-fade bought the crash, not the bottom. Over
the whole STRESS span E1M1 (+53.32%) is below buy-and-hold (+73.09%) and no better than unmodified E1 (+54.00%).
**R1 fails.** What this does not support: that M1 never helps (it matched buy-and-hold on 2009-2014); that E2M1 is a
candidate (reported alongside, not selected).

### Step 02 — neighbourhood (`step02_neighbourhood.ipynb`; descriptive, nothing selected)

72 paths in 67 s; the grid point 0.85 / 200 / on equals frozen E1M1 (+314.80%, 35 exits). Excess of total return over
buy-and-hold, percentage points (from `neighbourhood_path_data.csv`):

**DEV (buy-and-hold +235.39%), fresh-signal on / off:**

| fade \ MA | 150 on | 200 on | 250 on | 150 off | 200 off | 250 off |
|---|---|---|---|---|---|---|
| 0.70 | −57.61 | +0.47 | −5.73 | −162.64 | −137.41 | −133.29 |
| 0.75 | −27.73 | +19.00 | +1.05 | −149.57 | −120.76 | −119.32 |
| 0.80 | −5.97 | +50.27 | +21.53 | −129.72 | −103.49 | −93.56 |
| 0.85 | +7.93 | **+79.41 (E1M1)** | +59.77 | −113.26 | −96.40 | −89.58 |
| 0.90 | −28.83 | +15.75 | +3.48 | −148.35 | −129.57 | −115.14 |
| 0.95 | −39.62 | +12.83 | −0.37 | −122.04 | −112.18 | −84.15 |

**STRESS (buy-and-hold +73.09%), fresh-signal on / off:**

| fade \ MA | 150 on | 200 on | 250 on | 150 off | 200 off | 250 off |
|---|---|---|---|---|---|---|
| 0.70 | −42.41 | −51.30 | −34.01 | −40.15 | −44.51 | −25.72 |
| 0.75 | −39.46 | −51.69 | −36.31 | −27.26 | −35.98 | −15.45 |
| 0.80 | −34.31 | −22.59 | −26.43 | −3.42 | −3.04 | **+14.68** |
| 0.85 | −24.86 | **−19.77 (E1M1)** | −25.50 | −27.22 | −26.24 | −0.37 |
| 0.90 | −18.77 | +1.26 | +5.55 | −46.27 | −48.57 | −22.83 |
| 0.95 | −26.09 | −12.21 | −9.20 | −76.45 | −70.56 | −60.54 |

Variants beating buy-and-hold: **DEV 11 of 36, STRESS 3 of 36, both 2 of 36.** E1M1's rank on DEV: **1 of 36.** Median
excess DEV −70.88%, STRESS −26.34%. Every one of the 18 variants with the fresh-signal rule off loses on DEV (by 84 to
163 points). **R2 fails** (need 24 on DEV and 18 on STRESS). The surface is a **spike** at 0.85 / 200 / on, not a
plateau; the three STRESS winners are different parameters (0.90 / 200 / on, 0.90 / 250 / on, 0.80 / 250 / off) and
are not used. No variant is picked.

### Step 03 — placebo (`step03_placebo.ipynb`; 999 runs each)

Real E1M1 total 3.148 (+314.80%). The six real totals match exp12 (E1M1 314.80, E1M2 195.83, E1M3 132.68, E2M1 235.60,
E2M2 167.51, E2M3 168.95). Shift range 1,340 → 4,014 sessions. From the notebook / `placebo_summary_data.csv`:

| Test | Real | Null median | 5th / 95th | Rank | p |
|---|---|---|---|---|---|
| P1 misaligned VIX, E1M1 alone | 314.80% | 251.56% | 185.77% / 331.64% | 88 of 1000 | **0.0880** |
| P2 selection-aware max of six (primary) | 314.80% | 254.35% | 192.50% / 331.64% | 88 of 1000 | **0.0880** |
| P3 random re-entry after E1M1's exits | 314.80% | 125.88% | 66.23% / 209.69% | 1 of 1000 | 0.0010 |
| P4 random exits with E1M1's re-entry | 314.80% | 212.04% | 162.53% / 280.54% | 13 of 1000 | 0.0130 |

The candidate giving the shifted maximum: E1M1 860, E2M1 126, E1M2 13 of 999 runs (so P1 and P2 almost coincide).
**R3 fails** (need p2 ≤ 0.05). What this supports: E1M1's re-entries beat random re-entries (p3 = 0.001) and its exits
beat random exits with the same re-entry (p4 = 0.013) on this span. What it does not support: that the aligned VIX is
unlikely under a selection-aware null (87 of 999 shifted best-of-six paths reached ≥ +314.80%). A joblib
`resource_tracker` KeyError printed on stderr after the parallel runs (loky temp-folder cleanup); the notebook wrote
its outputs and logged 4 trials, so it is recorded as a non-fatal deviation.

### Step 04 — execution and episodes (`step04_execution_and_episodes.ipynb`)

From the notebook / `execution_path_data.csv` (buy-and-hold under exp12's costs +235.39%): delayed one session
**+306.15%** (Π S/R 1.2128, 35 exits, 94.0% in market); slippage 0 / 1 / 2 / 5 cents **+315.88% / +314.80% / +313.76% /
+310.85%**. **R5 holds.** Same-slippage buy-and-hold at 5 cents is +235.35%.

Episodes (`concentration_data.csv`, `reason_split_data.csv`, `half_log_excess_data.csv`, `yearly_log_excess_data.csv`):
35 episodes, product of S/R **1.2383**, equity / buy-and-hold **1.2368**. Without the best episode (2020-03-05 →
2020-03-16, S/R **1.2652**, M1): equity ratio **0.9775**, product 0.9788, **does not beat buy-and-hold**. Without the
two best (that one and 2018-12-04 → 2018-12-27, S/R 1.0928, M1): 0.8945. **R4 fails.** Split by reason: 13 M1 buy-backs
product **1.8188** (10 bought back lower); 22 original-rule product **0.6808** (0 bought back lower). 4 episodes overlap
2020-02-01 → 2020-06-30: their log(S/R) sum 0.1470 = **69%** of total log excess 0.2125. Halves: 2015-04-17 → 2020-12-31
log excess +0.2018 (+3.53%/yr); 2021-01-01 → 2026-04-15 log excess +0.0107 (+0.20%/yr). Yearly log excess: 2015 −0.0363,
2016 +0.0577, 2017 +0.0002, 2018 +0.0665, 2019 −0.0332, 2020 **+0.1469**, 2021 −0.0000, 2022 +0.0341, 2023 −0.0807, 2024
−0.0001, 2025 +0.0684, 2026 −0.0109.

*In plain words.* Almost all of E1M1's after-the-fact edge is a handful of M1 buy-backs in 2018, 2020 and 2025. Remove
the single best (the March 2020 fade that bought 239 after selling 303) and the path no longer beats buy-and-hold. The
original-rule buy-backs still lose (Π S/R 0.68), as in exp04. Delay and extra costs do not destroy the number, because
the 2020 episode is large enough to survive a one-session lag.

### Verdict (pre-registered §8, applied once)

| | Criterion | Number | Hold? |
|---|---|---|---|
| R1 | STRESS total ≥ buy-and-hold | +53.32% vs +73.09% | **FAIL** |
| R2 | ≥ 24/36 beat B&H on DEV and ≥ 18/36 on STRESS | 11 and 3 | **FAIL** |
| R3 | p2 ≤ 0.05 | 0.0880 | **FAIL** |
| R4 | still beats B&H without the best episode | equity ratio 0.9775 | **FAIL** |
| R5 | delayed and 5-cent each beat B&H +235.39% | +306.15% and +310.85% | PASS |

**E1M1 IS NOT ROBUST.** The after-the-fact +314.80% is a spike at one parameter triple, concentrated in 2020 (and 2018),
absent on 2005-2014 (where the same fade bought the 2008 crash), and not rare under a selection-aware shifted-VIX null.
No new version or variant of E1M1 may follow. The VIX line is closed. Biases unchanged (dividends ignored, cash at 0%,
informal costs); ninth reuse of 2015-2026; after-the-fact choice. Trials: 81 exp13, workspace **3,651**, **7,740** with
the 4,089 legacy trials.

## Cross-experiment notes (2026-10-06)

- The common failure is time out of the market: at about 12% a year, every session in cash costs about 0.045% of
  expected return, so an exit must be followed by a fall larger than that rent plus costs.
- exp01's buy-and-hold (+218.48%) differs from exp02/exp03's (+237.21%) because its schedule (10-session embargo) gives
  different quarters; compare each strategy only with its own buy-and-hold.
- The monthly-bootstrap intervals printed for exp02 and exp03 ([−454.82%, +1.21%] and [−400.79%, +12.44%]) are intervals
  of the difference in total compounded return over about 11 years; compounding stretches the lower tail. An interval on
  the annualized log excess would be easier to read (reporting change, not yet made).
- Trials added by this round: exp01 2 signal-check + 540 validation + 1 summary; exp02 14 + 1 + 792 + 1; exp03 15 + 660 +
  1 (2,027 in total), on top of the 4,089 legacy trials.
- Trials added by the "stay invested, exit rarely" family (2026-10-06): exp04 406, exp05 182, exp06 541, exp07 136
  (1,265 in total). Workspace total 3,292, plus the 4,089 legacy trials (7,381). No prior-only path of exp01-exp07 beats
  buy-and-hold; no candidate result is pending review.
- *Added 2026-10-06 (exp01 step 04 diagnostic): 1 `multivariate_check` trial. Workspace total 3,293, plus the 4,089
  legacy trials (7,382). Outcome A (no information); still no candidate result pending review.*
- Observed while running notebooks: `venv-main\Scripts\jupyter.exe` starts its host process from a system Python 3.14
  install, while the notebook kernel (`venv-main`) is the venv's own interpreter; the computations run in the kernel.
  Recorded for traceability, no action taken.
- *Added 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`, I5): annualized log excess
  of the prior-only path over buy-and-hold, 95% interval with 6-month blocks, copied from the saved outputs of each
  `step02_continuous_replay.ipynb`:*
  - *exp04_trend_exit: −6.07%/yr [−10.54%, −2.14%]: the underperformance is statistically supported (interval
    entirely below 0).*
  - *exp05_vol_scaled_exposure: −1.99%/yr [−4.33%, +0.08%]: the interval includes 0.*
  - *exp06_capped_regret_reentry: −2.65%/yr [−6.74%, +1.53%]: the interval includes 0.*
  - *exp07_warning_lights_exit: −7.33%/yr [−12.55%, −3.49%]: the underperformance is statistically supported
    (interval entirely below 0).*
  - *The notebooks' `supported` flag (False for all four) tests only a positive excess (lower bound > 0); it says
    nothing about whether a loss is significant.*
- *Added 2026-10-09, after the independent audit of 2026-10-09 (A4): BASE AUC 0.4233 [0.3648, 0.4829]: the price
  features' relations reverse out of sample. This is the third observation of a reversal (exp02 mean validation AUC
  0.470; exp01 step 04 at 0.79%-1.00%). It is evidence of non-stationarity, not a tradable result.*
- *Added 2026-10-09 (trial totals after exp12): exp08 6 + exp12 271 (6 exploration, 264 validation, 1 summary).
  Workspace total 3,570, plus the 4,089 legacy trials 7,659. No prior-only path of exp01-exp08 or exp12 beats
  buy-and-hold; no candidate result is pending review.*
- *Added 2026-10-09 (trial totals after exp13): exp13 81 (2 exploration, 74 robustness, 4 placebo, 1 summary).
  Workspace total 3,651, plus the 4,089 legacy trials 7,740. No candidate result is pending review. The VIX line is
  closed (exp13 verdict: E1M1 IS NOT ROBUST).*

### Limitations of the exp04-exp07 session (added 2026-10-06, after the independent audit, I6)

- exp04-exp07 were built, pre-registered, run and documented by the agent in 56 minutes (commits 14:02 → 14:58),
  without human review before running. Their integrity rested on the roadmap fixed beforehand (rules, grids,
  thresholds), which held; the one deviation from it (exp07's re-entry) is recorded in the exp07 section (I1).
- 2015-2026 has now been used by seven experiments (exp01-exp07; about 7,400 trials including the 4,089 legacy trials):
  it is development data, not out-of-sample evidence.
- exp04-exp07 were designed with knowledge of famous episodes (2008, 2020).
- In 2005-2014 the designs that looked good (exp04, exp05, exp07) did so through 2008 alone, and all of them lost on
  2015-2026.
- Any future positive result needs the untouched window (2026-05-14 → 2026-08-13, a parked decision) or new data.

### The VIX line (added 2026-10-09, agent)

- Roadmap exp08-exp11 (Nicolas, 2026-10-08, revised 2026-10-09). Setup: the SPY folder-rename check reproduced every
  number (see "Reproduction checks"); the shared VIX data layer was built and checked (section "VIX data layer").
- exp08 (the gate) ran once: G1, G2 and G4 fail, G3 passes; under the pre-registered gate decisions **exp09, exp10 and
  exp11 were not run**. Result: **no usable VIX information under the pre-registered gates**. No candidate result is
  pending review, primary or secondary timing.
- Limitations that apply to the whole line: VIX3M starts 2009-08-12 in the IBKR data, so the training span of the gate
  is 2009-08-13 → 2015-03-18 (1,408 sessions, shorter than exp02's 2005 start); the IBKR index data was not compared with
  Cboe's official values (the daily close and the last 1-minute close disagree on 2.6% of VIX and 10.6% of VIX3M dates);
  the 1-minute bar-label convention is unproven (the `_intraday` timing keeps a 1-minute margin and is secondary); 2015-2026
  is development data, reused here for the eighth time; the untouched window 2026-05-14 → 2026-08-13 was **not read**
  (every loader refuses dates from 2026-05-14; the last date loaded by any VIX notebook is 2026-05-13).
- Trials of the VIX line: exp08 6 (`signal_check`); exp09, exp10, exp11 0. Workspace total **3,299**, plus the 4,089
  legacy trials **7,388**.
- *Correction 2026-10-09, after the independent audit of 2026-10-09 (A1, A2): "no usable VIX information under the
  pre-registered gates" holds for what the gates tested. exp09's gates (G1: share of positive 20-session returns per
  bin; G2: ranking of their sign) tested the sign of forward returns, while exp09's mechanism concerns their size after
  fear peaks; G1 also had little power (1,408 overlapping training sessions, every null run S1 = 0). The descriptive
  pattern (higher mean returns after a high or inverted VIX) was not tested by exp08. The G2 explanation in the exp08
  entry ("the extra columns dilute the BASE model's (wrong-signed) weights") is "consistent with the extra columns
  diluting the BASE model's wrong-signed weights (an inference, not tested)" (A2).*
- *Added 2026-10-09 (exp12):* Nicolas answered the parked decision "VIX line closed" with (b): one data-dependent
  follow-up, exp12_vix_fear_reentry (exp09's rules, `_prev` only, 6 candidates), overriding exp08's gate. It ran once and
  **STOPS**: prior-only +119.24% vs buy-and-hold +229.74% (log excess −3.77%/yr [−7.95%, −0.37%]); it beats the
  unmodified exits (+82.88%) and 13/20 random re-entries but 0/20 random exits. **The VIX line is closed definitively**
  (no later version may be motivated by these results). No candidate result is pending review. Trials of the VIX line:
  exp08 6, exp12 271 (277). Workspace total **3,570**, plus the 4,089 legacy trials **7,659**. 2015-2026 is now used
  nine times.
- *Added 2026-10-09 (exp13):* Nicolas overrode exp12's "last VIX re-entry test" commitment to run a robustness study of
  E1M1. It ran once: **E1M1 IS NOT ROBUST** (R1–R4 fail, R5 holds). **The VIX line is closed.** Trials of the VIX line:
  exp08 6 + exp12 271 + exp13 81 = 358. Workspace total **3,651**, plus the 4,089 legacy trials **7,740**. No candidate
  result is pending review. The untouched window was not read (last date loaded by any exp13 notebook: 2026-04-15).
