# Benchmark

Started 2026-10-15 with the constant-exposure column. The other columns of the benchmark table (old span, calibration, look-ahead audit, trials) are filled when that write-up is done. The development spans differ across experiments. A return on one span is not a return on another.

## Constant exposure (2026-10-15)

No new run. No new trial. Each number is computed from the saved development files.

The weight is the prior-only path's time in the market: `in_market_pct` in `summary_data.csv`. For exp01 that is the mean of `in_position` over every row of `prior_only_daily_equity_data.csv` (0.825000, 2,178 of 2,640 sessions). For the other experiments it is the mean excluding the last session, which is the figure the development report saved.

The buy-and-hold equity is rebuilt from `buy_hold_daily_return` in `performance_over_time_data.csv`, starting at 100,000. Compounding those returns reproduces the saved buy-and-hold total return (exp01 2.1735094; the other eight experiments 1.9904416).

Continuous holding of fraction `w` is `(1 − w) × 100,000 + w × buy-and-hold equity`. Cash earns 0%. That blend still contains the terminal exit of the saved buy-and-hold. The exit is added back so the fraction pays one entry.

The full-account exit matches the simulator. exp01: 502 shares, 10:00 open 198.93 on 2015-02-02, last close 631.93 on 2025-07-31, entry slippage 0.01, market-exit slippage 0.01, fee 2.51 a side. Entry cost 7.53 dollars. Exit cost 7.53 dollars. Liquidating with that exit returns 2.1735094. The other experiments share one span, 2015-04-20 → 2025-07-17: 476 shares, 10:00 open 209.80, last close 627.99, entry cost 7.14 dollars, exit cost 7.14 dollars, liquidated return 1.9904416. Those two prices are the first and last sessions already named in the saved equity files.

The reported constant-exposure total return adds `w × exit cost` to the blended final equity and divides by 100,000. The entry stays inside the saved equity, scaled by `w`.

exp05 already records a constant-exposure baseline from its own simulation (integer shares, the protocol dead band, entry and exit). That saved return is the column below. The one-entry blend at the same weight is 1.701224, 0.000687 from the saved 1.701911. The stopping rule used the saved simulation.

| Experiment | Weight | Prior-only | Buy-and-hold | Constant exposure | Path minus constant | vs constant exposure |
|---|---:|---:|---:|---:|---:|---|
| `exp01_minute_entry_v2` | 0.825000 | 1.365326 | 2.173509 | 1.793207 | −0.427882 | below |
| `exp02_stop_reentry_v2` | 0.735248 | 0.618215 | 1.990442 | 1.463522 | −0.845307 | below |
| `exp03_ath_exit_v2` | 0.604037 | 1.111234 | 1.990442 | 1.202344 | −0.091110 | below |
| `exp04_trend_exit_v2` | 0.847826 | 0.415088 | 1.990442 | 1.687609 | −1.272521 | below |
| `exp05_vol_scaled_exposure_v2` | 0.854666 | 1.425930 | 1.990442 | 1.701911 | −0.275981 | below (saved protocol baseline) |
| `exp06_capped_regret_reentry_v2` | 0.694876 | 1.322490 | 1.990442 | 1.383159 | −0.060669 | below |
| `exp07_warning_lights_exit_v2` | 0.847438 | 0.409472 | 1.990442 | 1.686836 | −1.277365 | below |
| `exp12_vix_fear_reentry_v2` | 0.918090 | 1.265069 | 1.990442 | 1.827470 | −0.562401 | below |
| `exp13_e1m1_robustness_v2` | 0.939053 | 2.738521 | 1.990442 | 1.869197 | +0.869324 | above |

Total returns are the 6-decimal values of the saved summary fields and of this calculation. The weight is `in_market_pct` (exp05: `mean_weight`) at 6 decimals. exp13 is the only path above its constant-exposure hold. That comparison is not a success claim: the 6-month interval still contains 0, and protocol 1.0 already recorded E1M1 IS NOT ROBUST.
