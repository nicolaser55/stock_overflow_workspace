# Results log

One row per development run on the point-in-time runner, appended by `scripts/run_development.py` (newest last).
Started fresh on 2026-10-22: earlier results, protocols and the old trial log were deleted (Nicolas). An experiment's
result is whatever its current code produces when run. The run folder (`store04_experiments/runs/<run id>/`) holds
`report.md`, `report.json` and `manifest.json`.

| Date | Experiment | Protocol | Run id | Verdict | Prior-only vs buy-and-hold | Failed | Look-ahead | Note |
|---|---|---|---|---|---|---|---|---|
| 2026-10-23 | exp02_stop_reentry | 1.0 | exp02_stop_reentry_20261023154308910279 | not email-worthy | +148.41% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp03_ath_exit | 1.0 | exp03_ath_exit_20261023160107439211 | not email-worthy | +134.86% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp04_trend_exit | 1.0 | exp04_trend_exit_20261023161037246802 | not email-worthy | +45.46% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp05_vol_scaled_exposure | 1.0 | exp05_vol_scaled_exposure_20261023161713783335 | not email-worthy | +148.95% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp06_capped_regret_reentry | 1.0 | exp06_capped_regret_reentry_20261023162151833894 | not email-worthy | +104.12% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp07_warning_lights_exit | 1.0 | exp07_warning_lights_exit_20261023163040210756 | not email-worthy | +50.43% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp12_vix_fear_reentry | 1.0 | exp12_vix_fear_reentry_20261023163525011773 | not email-worthy | +128.78% vs +199.04% | return, consistency, baselines | pass | protocol 1.0 first run |
| 2026-10-23 | exp13_e1m1_robustness | 1.0 | exp13_e1m1_robustness_20261023164503182503 | not email-worthy | +273.85% vs +199.04% | consistency | pass | protocol 1.0 first run |
| 2026-10-24 | exp01_minute_entry | 1.0 | exp01_minute_entry_20261023182310533311 | not email-worthy | +101.73% vs +217.35% | return, consistency, baselines, look-ahead | fail | protocol 1.0 first run |
| 2026-10-25 | exp01_minute_entry | 1.0 | exp01_minute_entry_20261024153137940592 | not email-worthy | +101.73% vs +217.35% | return, consistency, baselines | pass | protocol 1.0, look-ahead cut-moment fix |
| 2026-10-25 | all rows above | 1.0 | n/a | withdrawn | n/a | n/a | n/a | audit 2026-10-25 (claude/AUDIT_2026-10-25_foundation.md): baselines wrong for the trailing-stop rows (B1), look-ahead check weaker than reported (B3), consistency counted tied windows (S1); every experiment reruns after the fixes |
| 2026-10-28 | exp02_stop_reentry | 1.0 | exp02_stop_reentry_20261028173701310796 | not email-worthy | +148.41% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-28 | exp03_ath_exit | 1.0 | exp03_ath_exit_20261028183143547561 | not email-worthy | +134.86% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-28 | exp04_trend_exit | 1.0 | exp04_trend_exit_20261028190530034569 | not email-worthy | +45.46% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-28 | exp05_vol_scaled_exposure | 1.0 | exp05_vol_scaled_exposure_20261028192620680007 | not email-worthy | +148.95% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-28 | exp06_capped_regret_reentry | 1.0 | exp06_capped_regret_reentry_20261028194215864254 | not email-worthy | +104.12% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-28 | exp07_warning_lights_exit | 1.0 | exp07_warning_lights_exit_20261028201101453930 | not email-worthy | +50.43% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-28 | exp12_vix_fear_reentry | 1.0 | exp12_vix_fear_reentry_20261028202524065156 | not email-worthy | +128.78% vs +199.04% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-29 | exp01_minute_entry | 1.0 | exp01_minute_entry_20261028205533884714 | not email-worthy | +101.73% vs +217.35% | return, consistency, baselines, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged |
| 2026-10-29 | exp13_e1m1_robustness | 1.0 | exp13_e1m1_robustness_20261029082739951249 | not email-worthy | +273.85% vs +199.04% | consistency, multiple-testing | pass | phase C rerun, judge cc094bd (A3), v1.0 unchanged; origin to be documented |
| 2026-10-29 | phase C rows above (9) | 1.0 | n/a | note | n/a | n/a | n/a | first valid baseline: judge hash ad4a601ec218bc09, judge commit cc094bd; replaces the rows of 2026-10-23..25 withdrawn by the 2026-10-25 audit; every return identical to them |
| 2026-10-29 | exp13_e1m1_robustness | 1.0 | n/a | note | n/a | n/a | n/a | origin: exp12 candidate E1M1, chosen after the fact as the best of exp12's six rules (2026-10-09); the pre-reset robustness study judged it NOT ROBUST (commits afe6b42..05ac8c3); its +273.85% is a selected result, not evidence (docs/STAGE1_RESEARCH_PLAN.md section 7) |
