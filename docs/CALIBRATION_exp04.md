# exp04 runner calibration (4c-a, 2026-10-22)

Machinery-only comparison of `exp04_trend_exit_v2_1` on `so.runner` against the saved v2 development files
(`store04_experiments/exp04_trend_exit_v2/step01_development_data/`, written 2026-10-13T02:16:52). Protocol 2.1, commit
`bac7983081d5305942a8cc57adb0a88b51bbb216`, config hash `02dbb9d999`. No rule was changed to make numbers match. The
holdout was not read.

A match is identical trades (date, side, shares, fill price) and equity within `so.config.NUMERIC_TOLERANCE` (1e-6).
v2 did not save per-candidate decisions or trades. Those were reconstructed from `experiments/exp04_trend_exit/rules.py`
and `simulate_stop_reentry_dict` on the runner's development bars (`ohlcv.pkl` of this run: 2005-01-03 → 2025-07-17,
5,166 sessions). The reconstruction of a **fresh** window on the saved v2 fold-0 bounds matches the saved fold-0 score
of `0.00|1` exactly (−0.002569), so those bars have not been rewritten since v2.

Run: `scripts/run_development.py experiments/exp04_trend_exit --note "4c calibration"`. Run id
`exp04_trend_exit_v2_1_20261022030246710390`. Wall time **363.2 s** (6.1 min; streams ~1 min, look-ahead 229.1 s).
369 validation trial rows, note `4c calibration`, `test_window_touched` false. No summary trial (the runner logs
candidate-periods only).

## What matched

| Check | Result |
|---|---|
| Candidate names | The same 9: `0.00\|1` … `0.05\|10` |
| Decisions, overlapping sessions | **9 / 9 candidates**, 2,558 sessions 2015-04-20 → 2025-06-18. Target weight 0 / 1 / NaN from `decide(view)` equals the v2 exit / re-entry / keep mapping from current `ma200_dist_pct`. Last session of each span is NaN in both engines. |
| Trades, same span as the runner | **9 / 9 candidates**. Fractional engine fills equal `simulate_stop_reentry_dict` fills (date, side, shares, price) when both start 2015-03-19 and end 2025-06-18. Fill counts: `0.00\|1` 70, `0.00\|5` 34, `0.00\|10` 24, `0.03\|1` 14, `0.03\|5` 14, `0.03\|10` 12, `0.05\|1` 10, `0.05\|5` 10, `0.05\|10` 10. |
| Fresh-window fold 0 on v2 bounds | `0.00\|1` last/initial **−0.002569**, equal to the saved `score_data.csv` row. Buy-and-hold on that fresh window is 0.012471; the saved B&H column is 0.012543 (see difference 3). |
| Look-ahead | **pass**. Cuts 2015-07-08, 2021-04-07, 2024-04-10; every candidate, truncation and perturbation. |
| Holdout | Untouched. `test_window_touched` false on all 369 rows. VIEW.json `window_start` 2025-08-14. |

The 200-session distance in `decide(view)` is the same number as `so.features.daily_features.ma200_dist_pct`: decision
close (15:58) over the mean of the previous 200 complete session closes (15:59). Complete closes are taken as
`close[start_idx[i+1] − 1]`, because `session_end_idx` on the view is filled only for the immediate previous session.

## Differences

### 1. Period bounds (all 41)

First date: runner period 0 is **2015-03-19 → 2015-06-18** (64 sessions); v2 period 0 is **2015-04-20 → 2015-07-17**
(63 sessions). Last period: runner **2025-03-19 → 2025-06-18**; v2 **2025-04-21 → 2025-07-17**. Zero of 41 share both
ends. Runner span 2,579 sessions; v2 span 2,577. Overlap 2015-04-20 → 2025-06-18 (2,558 sessions).

Cause, in code: `so.runner.periods.get_development_run_period_pdf` builds the fold anchor as the **truncated** price
sessions (ending 2025-07-17) plus the holdout start 2025-08-14. The ~20 sessions between development end and the window
start are missing, so `get_development_end_date` counts the 20-session embargo on a gapped calendar and lands on
**2025-06-18**. v2 called `get_development_period_pdf(span_dict["anchor_session_list"], …)`. That list still has the
intervening dates (`so.core.development_span.get_development_ohlcv_dict`), so the last validation window ended on
development end **2025-07-17**. Price bars in this run still go to 2025-07-17; they are just not scored.

Size: one calendar month of embargo miscount (~20 sessions). Not a leak. Not a rule change.

### 2. Period scores (0 / 369 by `fold_id`)

First cell: fold 0, `0.00|1`, runner **+0.013066** vs saved **−0.002569**, abs diff **0.015635**.

Cause: (a) the bounds in difference 1, so fold 0 is a different month; (b) v2's saved **strategy** column is a
**fresh window** on those dates (`get_equity_total_return_float` of `run_candidate_replay_dict` after
`get_bar_period_pdf` failed to match the report's periods — that helper used the same gapped anchor, so the continuous
slice was not selected); (c) the runner scores a **continuous slice** of one stream, including the position carried in.
A fresh window of `0.00|1` on the saved v2 fold-0 dates, on these bars, is −0.002569 and matches the saved strategy
column. The saved buy-and-hold column on that row is the continuous B&H slice (0.012543), not the fresh-window B&H
(0.012471). That mix is in the v2 report (`get_period_return_pdf` for B&H, `get_equity_total_return_float` for the
candidate). It is not reproduced, and it is not changed.

### 3. Selection in force (15 / 41)

First mismatch: period_id **3**, runner `0.03|5`, v2 `0.03|1`. Matched period_ids: 0, 1, 2, 15–18, 20–23, 25–28.

Cause: pooled prior-only selection on the scores in difference 2. Period 0 is `0.00|1` in both (first listed candidate).
The later splits are the different quarters, not a different tie-break. `SELECTION_RULE` is the same (last 4, larger
buffer then larger confirmation).

### 4. Prior-only daily equity and total return

Runner (report.json): **+0.517088 vs buy-and-hold +1.844214** over 2015-03-19 → 2025-06-18 (2,579 sessions).
v2 saved: **+0.415088 vs +1.990442** over 2015-04-20 → 2025-07-17 (2,577 sessions).

On the 2,558 overlapping dates, equity **levels** first differ on **2015-04-20**: runner 99,926.22 vs v2 100,016.66
(abs **90.44**). Daily **returns** first differ on **2015-04-22** (abs **4.40e-6**, just above 1e-6).

Cause: the runner path opened on 2015-03-19 (first 10:00 fill of the gapped schedule). v2 opened on 2015-04-20. Same
0/1/NaN decisions on the overlap do not imply the same share count: the buy was on a different day at a different
price. Compounding from a different start is the 90-dollar gap on 2015-04-20. The 4.4e-6 daily-return gap on 2015-04-22
is that share-count difference, not a different signal.

The runner's recorded-decision prior-only path (decide() not called again) is the path in report.json. That is the
honest path for protocol 2.1. It is not comparable to v2's +41.51% as a research number: the scored sessions differ.

## Unexplained differences

None after the traces above. Decisions match on every overlapping session. Trades match when the two engines are given
the same span. Score, selection, equity and total-return gaps are the gapped embargo calendar and v2's fresh-window
scores. Labels blanked near the holdout start are not involved (the distance uses prices only; the last scored runner
session is 2025-06-18, 20 sessions before 2025-07-17).

## Runner verdict (this span, not a new research STOP)

From `report.md` / `manifest.json`: **not email-worthy**. Failed: return, consistency, baselines. Look-ahead: pass.

- Return: 0.517088 vs 1.844214, below the 90% comparable floor (1.659793). Sharpe 0.350425 vs 0.651900. Max drawdown
  −0.323222 vs −0.342298.
- Consistency: ahead of buy-and-hold on 6 of 113 rolling 12-month windows (0.053; need 0.60).
- Baselines: constant exposure weight 0.829562, daily rebalanced, +1.414475 (path not above). Random timing 1 of 100
  seeds (need 0.95).

Protocol 2.0's STOP (+41.51% vs +199.04% on 2015-04-20 → 2025-07-17) stays the recorded research result. Protocol 2.1
does not replace it. No holdout evaluation.

## Files

- Run folder: `store04_experiments/runs/exp04_trend_exit_v2_1_20261022030246710390/` (`report.md`, `report.json`,
  `lookahead.json`, `manifest.json`).
- Comparison: `scripts/compare_exp04_calibration.py` (no trial rows).
- Logs: `logs/exp04_4c.out` (PowerShell UTF-16), empty `logs/exp04_4c.err`.
