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
