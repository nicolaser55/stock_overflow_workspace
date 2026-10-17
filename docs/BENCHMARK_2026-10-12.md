# Benchmark

Started 2026-10-15 with the constant-exposure column. The old span, the calibration, the look-ahead audit and the trial counts are in the table of 2026-10-17. The development spans differ across experiments. A return on one span is not a return on another.

## Constant exposure (2026-10-15)

No new run. No new trial. Each number is computed from the saved development files.

The weight is the prior-only path's time in the market: `in_market_pct` in `summary_data.csv`. For exp01 that is the mean of `in_position` over every row of `prior_only_daily_equity_data.csv` (0.825000, 2,178 of 2,640 sessions). For the other experiments it is the mean excluding the last session, which is the figure the development report saved.

The buy-and-hold equity is rebuilt from `buy_hold_daily_return` in `performance_over_time_data.csv`, starting at 100,000. Compounding those returns reproduces the saved buy-and-hold total return (exp01 2.1735094; the other eight experiments 1.9904416).

Continuous holding of fraction `w` is `(1 − w) × 100,000 + w × buy-and-hold equity`. Cash earns 0%. That blend still contains the terminal exit of the saved buy-and-hold. The exit is added back so the fraction pays one entry.

The full-account exit matches the simulator. exp01: 502 shares, 10:00 open 198.93 on 2015-02-02, last close 631.93 on 2025-07-31, entry slippage 0.01, market-exit slippage 0.01, fee 2.51 a side. Entry cost 7.53 dollars. Exit cost 7.53 dollars. Liquidating with that exit returns 2.1735094. The other experiments share one span, 2015-04-20 → 2025-07-17: 476 shares, 10:00 open 209.80, last close 627.99, entry cost 7.14 dollars, exit cost 7.14 dollars, liquidated return 1.9904416. Those two prices are the first and last sessions already named in the saved equity files.

The reported constant-exposure total return adds `w × exit cost` to the blended final equity and divides by 100,000. The entry stays inside the saved equity, scaled by `w`.

exp05 already records a constant-exposure baseline from its own simulation (integer shares, the protocol dead band, entry and exit). That saved return is 1.701911. The one-entry blend at the same weight is 1.701224, 0.000687 from the saved 1.701911. The stopping rule used the saved simulation. The held-once column below is the one-entry blend, the same object as the other rows.

*2026-10-16.* The held-once blend lets the SPY weight drift up as prices rise, so its average exposure exceeds `w`. The timing comparison is a constant weight `w`, rebalanced every session: growth is the product over the saved `buy_hold_daily_return` rows of `(1 + w × r_t)`. `w` is the same saved average as the held-once column (`in_market_pct`; exp05 `mean_weight`). No cost is added. The saved returns already contain buy-and-hold's entry and exit, and those two sessions are scaled by `w`. No new run. No new trial. Verdicts do not change: the stopping rules compare buy-and-hold and the protocol baselines.

| Experiment | Weight | Prior-only | Buy-and-hold | w held once (exposure drifts up) | w constant (daily rebalanced, exposure-matched) | vs held once | vs daily constant |
|---|---:|---:|---:|---:|---:|---|---|
| `exp01_minute_entry_v2` | 0.825000 | 1.365326 | 2.173509 | 1.793207 | 1.658154 | below | below |
| `exp02_stop_reentry_v2` | 0.735248 | 0.618215 | 1.990442 | 1.463522 | 1.313259 | below | below |
| `exp03_ath_exit_v2` | 0.604037 | 1.111234 | 1.990442 | 1.202344 | 1.018806 | below | above |
| `exp04_trend_exit_v2` | 0.847826 | 0.415088 | 1.990442 | 1.687609 | 1.587718 | below | below |
| `exp05_vol_scaled_exposure_v2` | 0.854666 | 1.425930 | 1.990442 | 1.701224 | 1.605042 | below | below |
| `exp06_capped_regret_reentry_v2` | 0.694876 | 1.322490 | 1.990442 | 1.383159 | 1.219744 | below | above |
| `exp07_warning_lights_exit_v2` | 0.847438 | 0.409472 | 1.990442 | 1.686836 | 1.586737 | below | below |
| `exp12_vix_fear_reentry_v2` | 0.918090 | 1.265069 | 1.990442 | 1.827470 | 1.769182 | below | below |
| `exp13_e1m1_robustness_v2` | 0.939053 | 2.738521 | 1.990442 | 1.869197 | 1.824818 | above | above |

Total returns are the 6-decimal values of the saved summary fields and of these two calculations. The daily-constant column is the timing comparison. On 2026-10-15 the word "below" referred only to the held-once column. exp03 and exp06 are below that column and above the daily-constant column. exp13 is above both. That is not a success claim: the 6-month interval still contains 0, and protocol 1.0 already recorded E1M1 IS NOT ROBUST.

## Look-ahead audit (2026-10-17)

A future model design builds its scoring rows without labels. Labels are needed only for training. A row that cannot be scored until its label clock exists is not a deployable decision, and a holdout truncation test marks that design `invalid_lookahead`.

exp01's development run did not save a refit table. Its audit compares decision rows only. A decision row is the sampled row on or before the cut. The buy flag, the distance and the expected return are computed from that row. Position changes from a fill or an exit on a bar after the decision bar are not decision differences.

The four exp01 cuts were classified from those datasets (`logs/lookahead_audit/exp01_cut_classify.json`). Every column of every shared row matches. Perturbation drops no row. Truncation drops only rows whose `label_known_ts` is after the cut session's last bar.

| Cut | Perturbation | Truncation rows absent, clock after the cut |
|---|---|---:|
| 2015-02-27 | pass (61,048 rows match) | 216 |
| 2018-07-31 | pass (81,664 rows match) | 216 |
| 2021-11-30 | pass (101,728 rows match) | 45 |
| 2025-04-30 | pass (122,200 rows match) | 79 |

On 2015-02-27 the fitted replay was also compared. All 456 decisions through the cut match (buy flag, distance, expected return). The perturbed path's only extra trade is a take-profit sale at the bar labelled 15:59, the first bar after the decision bar. Truncation fails by construction: scoring needs the row's label clock; development results unaffected (212 rows, last 9 sessions only); not deployable; a holdout evaluation would mark it `invalid_lookahead`. Trial note `20261017222644392171_15ef441ce8`.

The other designs were compared with the saved development path, and with a control replay when a check left that path. Rule designs keep the stricter saved-path pass.

| Experiment | Protocol 1.0 prior-only vs buy-and-hold | Protocol 2.0 prior-only vs buy-and-hold | Shared quarters, returns / selections | Old bounds, returns / selections | Look-ahead | v2 trials |
|---|---|---|---|---|---|---:|
| `exp01_minute_entry_v2` | +146.94% vs +218.48% | +136.53% vs +217.35% | 40 overlap pairs, 0/40 returns | not run | perturbation pass; truncation fails by construction | 505 |
| `exp02_stop_reentry_v2` | +111.66% vs +237.21% | +61.82% vs +199.04% | not run | not run | pass, four cuts | 739 |
| `exp03_ath_exit_v2` | +143.05% vs +237.21% | +111.12% vs +199.04% | not the three-quarter gate | 615/615, 36/40 | pass, four cuts | 616 |
| `exp04_trend_exit_v2` | +70.84% vs +229.74% | +41.51% vs +199.04% | 0/27, 1/3 | 369/369, 41/41 | pass, four cuts | 370 |
| `exp05_vol_scaled_exposure_v2` | +165.69% vs +229.74% | +142.59% vs +199.04% | 0/12, 2/3 | 164/164, 41/41 | pass, four cuts | 165 |
| `exp06_capped_regret_reentry_v2` | +147.38% vs +229.74% | +132.25% vs +199.04% | 0/36, 1/3 | 492/492, 41/41 | pass, four cuts | 493 |
| `exp07_warning_lights_exit_v2` | +49.09% vs +229.74% | +40.95% vs +199.04% | 0/9, 1/3 | 123/123, 41/41 | pass, four cuts | 124 |
| `exp12_vix_fear_reentry_v2` | +119.24% vs +229.74% | +126.51% vs +199.04% | 0/18, 3/3 | 246/246, 41/41 | pass, four cuts | 247 |
| `exp13_e1m1_robustness_v2` | no path; E1M1 IS NOT ROBUST | +273.85% vs +199.04% | 0/3, 3/3 | 41/41, 41/41 | pass, four cuts | 42 |

Protocol 1.0 returns are the summary table of `docs/RESULTS_LOG.md`. Protocol 2.0 returns, the calibration counts and the trial counts are the version 2.0 sections of that log. v2 trials are validation plus the one summary. Each calibration also added one note, which is not in this column. exp02's four-cut pass treats the 2015-04-30 difference from the saved path as an end-of-window artefact: truncation and perturbation match a control stopped on the same cut. The later three cuts do the same. No holdout evaluation was run.
