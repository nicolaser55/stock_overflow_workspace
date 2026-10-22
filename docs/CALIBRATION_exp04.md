# exp04 runner calibration (4c-a, 2026-10-22)

Machinery comparison of `exp04_trend_exit_v2_1` on `so.runner` against the saved v2 development files
(`store04_experiments/exp04_trend_exit_v2/step01_development_data/`, written 2026-10-13T02:16:52). Protocol 2.1.
Holdout not read. A match is identical trades (date, side, shares, fill price) and equity within
`so.config.NUMERIC_TOLERANCE` (1e-6). v2 did not save per-candidate decisions or trades; those were reconstructed from
`experiments/exp04_trend_exit/rules.py` and `simulate_stop_reentry_dict`.

Protocol 2.0's STOP (+41.51% vs +199.04%) stays the recorded research result. Protocol 2.1 does not replace it.

## 4c calibration rerun (fixed periods)

Commit `7a38916` (embargo counted on the NYSE calendar). Config hash `02dbb9d999` (trial-log column). Run:
`scripts/run_development.py experiments/exp04_trend_exit --note "4c calibration rerun"`. Run id
`exp04_trend_exit_v2_1_20261022120635892665`. Wall time **484.6 s** (8.1 min; look-ahead 301.3 s). 369 validation
trial rows, note `4c calibration rerun`, `test_window_touched` false. No summary trial.

### What matches

| Check | Result |
|---|---|
| Period bounds | **41 / 41**. Both 2015-04-20 → 2025-07-17, 2,577 sessions, 41 periods. Period 0 is 2015-04-20 → 2015-07-17 (63 sessions). Last period ends **2025-07-17**. |
| Buy-and-hold period scores | **369 / 369**. Maximum absolute difference 8.33e-17. Both columns are continuous slices of one B&H stream. Fold 0 is 0.012543. |
| Decisions | **9 / 9 candidates**, all 2,577 sessions. Target weight 0 / 1 / NaN from `decide(view)` equals the v2 exit / re-entry / keep mapping. |
| Trades, same span | **8 / 9 candidates**. Fill counts equal `simulate_stop_reentry_dict` except `0.00\|5` (below). |
| Component (a) | Saved v2 candidate-period scores into `get_runner_selection_pdf` then `get_governing_candidate_dict`: **41 / 41** equal v2 `selection_data.csv`. |
| Component (b) | Runner engine driven with v2's governing selection and v2's periods: prior-only daily equity **equals v2 within 1e-6** on all 2,577 sessions. |
| Look-ahead | **pass**. Cuts 2015-08-06, 2021-05-05, 2024-05-08. |
| Holdout | Untouched. VIEW.json `window_start` 2025-08-14. |

The period-gap bug is gone: `get_development_run_period_pdf` fills the NYSE sessions between the last priced bar and
the holdout start, so the 20-session embargo lands on 2025-07-17, as in v2. Component (b) shows the fractional engine
plus v2's in-force rules reproduce v2's path. The remaining gaps are not an engine bug.

### Remaining differences (scoring method)

Saved v2 **strategy** scores are fresh windows. The runner scores a **continuous slice** of each candidate's stream
(position carried in). Protocol 2.1 names that change. Evidence: a continuous-slice reconstruction of `0.00|1` on the
saved v2 fold-0 dates is −0.00249865; the saved row is −0.002569; a fresh window on those dates is −0.002569.

**1. Period scores (0 / 369).** Fold 0, `0.00|1`: runner **−0.00249865** vs saved **−0.002569**, abs **7.035e-5**.
Maximum absolute difference **0.126724**. Buy-and-hold on the same rows matches (difference 1 is not a bound shift).
Cause: slice versus fresh window on the same dates.

**2. Selection in force (18 / 41).** First mismatch: period_id **3** (2016-01-19 → 2016-04-15), runner `0.03|5`,
v2 `0.03|1`. Matched period_ids: 0–2, 9–18, 20–23, 40. Period 0 is `0.00|1` in both (first listed candidate).
Cause: pooled prior-only selection on the scores in difference 1. Component (a) shows the selector itself, given v2's
scores, reproduces v2's 41 rows. `SELECTION_RULE` is unchanged.

**3. Prior-only path (same span, different rules in force).** Runner report: **0.454634 vs buy-and-hold 1.990442**
over 2015-04-20 → 2025-07-17 (2,577 sessions). v2 saved: **0.415088 vs 1.990442** on the same dates. Buy-and-hold
matches v2. Equity **levels** and **daily returns** first differ on **2020-03-18** (levels abs 1,033.69; daily-return
abs 0.011579). Cause: from period 3 the governing candidate is not v2's, so the crash week is traded under a different
rule. Component (b) on v2's governing selection matches v2's equity; this gap is the selection in difference 2.

### Other difference (not scoring)

`0.00|5` candidate stream: runner 35 fills vs reconstructed v2 34. First extra fill 2023-03-20, buy 1 share at 393.59
(leftover-cash rebalance in `FractionalWeightEngine`). Decisions for that candidate still match on every session. The
row is not in force on v2's path, and component (b) still matches v2 equity, so this fill does not explain difference 3.

### Runner verdict (this span, not a new research STOP)

From `report.md` / `report.json`: **not email-worthy**. Failed: return, consistency, baselines. Look-ahead: pass.

- Return: 0.454634 vs 1.990442, below the 90% comparable floor (1.791397). Sharpe 0.320043 vs 0.679611. Max drawdown
  −0.323459 vs −0.342106.
- Consistency: ahead of buy-and-hold on 8 of 113 rolling 12-month windows (0.071; need 0.60).
- Baselines: constant exposure weight 0.822673, daily rebalanced, +1.502228 (path not above). Random timing 0 of 100
  seeds (need 0.95).

### Files

- Run folder: `store04_experiments/runs/exp04_trend_exit_v2_1_20261022120635892665/`
- Comparison: `scripts/compare_exp04_calibration.py` (no trial rows; `--components-only` runs (a) and (b) without a run id)
- Log: `logs/exp04_4c_rerun.out` (empty `.err`)

## First run (gapped periods, kept)

Run id `exp04_trend_exit_v2_1_20261022030246710390`, commit `bac7983`, note `4c calibration`, 363.2 s, 369 trials.
Period bounds were 0 / 41 (runner last period ended 2025-06-18) because `get_development_run_period_pdf` counted the
embargo on truncated bars plus the holdout start. Decisions 9 / 9 on the 2,558 overlapping sessions. That period bug
is fixed above; this run is not repeated.
