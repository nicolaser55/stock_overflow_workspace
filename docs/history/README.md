# History: The Workspace Before 2026-10-05

These are the documents of the previous workspace, kept unchanged as the record of how the project got here. The code is
in git (tag `pre-refactor-20261005`, created before the reorganization), with the executed notebooks and their outputs.

| File | Content |
|---|---|
| `RESULTS_LOG_2026-10-05.md` | Every result of v1, v2 and the step 13 exploration (uncorrected and corrected data), the bad tick correction, and the audit entry |
| `RESEARCH_PROTOCOL_v1.md` | Protocol v1 (minute entries with SL/TP) → now `experiments/exp01_minute_entry/PROTOCOL.md` |
| `RESEARCH_PROTOCOL_v2.md` | Protocol v2 (stop and re-entry) → now `experiments/exp02_stop_reentry/PROTOCOL.md` |
| `SO_pipeline_understanding.md` | How the original pipeline worked, its known issues, the 41 decisions of 2026-10-01 |
| `HANDOVER_2026-10-05.md` | Handover written at the end of the previous working session |
| `AUDIT_2026-10-05.md` | Independent audit of 2026-10-05 (findings F1-F9 are referred to from the new protocols) |
| `README_previous_workspace.md` | The previous workspace guide |

## Name mapping

| Before | After |
|---|---|
| `config.py` (v1 constants + shared) | `so/config.py` (shared) + `experiments/exp01_minute_entry/config.py` |
| `config_v2.py` | `experiments/exp02_stop_reentry/config.py` (daily feature constants moved to `so/config.py`) |
| `paths.py` | `so/paths.py` (experiment outputs now in `store04_experiments/`) |
| `trade_execution.py`, `backtest_simulation.py`, `performance_metrics.py`, `data_quality.py`, `datetime_utils.py`, `local_file_management.py` | `so/core/` (same names) |
| `stop_reentry_simulation.py` | `so/core/reentry_simulation.py` (the forced re-entry is now passed explicitly) |
| `fix_raw_bad_ticks.py` | `so/core/bad_ticks.py` + `scripts/fix_raw_bad_ticks.py` |
| `trial_log.py`, `walk_forward_v2.log_trial_v2_dict` | `so/core/trial_log.py` (one function for every experiment) |
| `walk_forward.get_walk_forward_fold_pdf` | `so/core/schedule.py` |
| `signal_check.py` (bins and bootstrap) | `so/core/signal_bins.py` + `experiments/exp01_minute_entry/signal_check.py` |
| chaining, bootstrap, success criteria of `walk_forward_v2.py` | `so/core/evaluation.py` (+ pooled selection, prior-only path, MDE, baseline summaries) |
| `ohlcv_data_utils.py`, `tf_ohlcv_tools.py`, `plot_ohlcv_utils.py`, `snapshot_features.py`, `context_features.py`, `barrier_labels.py`, `buy_eval_utils.py`, `daily_features.py` | `so/features/` (same names) |
| `model_dataset.py`, `walk_forward.py` | `experiments/exp01_minute_entry/` |
| `signal_check_v2.py`, `walk_forward_v2.py` | `experiments/exp02_stop_reentry/signal_check.py`, `walk_forward.py` |
| `invalidate_bad_tick_dates.py`, `verify_model_dataset.py`, `audit_v2_reproduction.py` | not carried over (one-off tools of the correction and the audit; in git history) |

| Notebook before | Notebook after |
|---|---|
| step00 - step05 | `pipeline/step00` - `step05` (imports changed only) |
| step06 model dataset | `experiments/exp01_minute_entry/step01_model_dataset.ipynb` |
| step07 signal check | `experiments/exp01_minute_entry/step02_signal_check.ipynb` (base-rate version) |
| step08 walk-forward | `experiments/exp01_minute_entry/step03_walk_forward.ipynb` |
| step09 TSDAY | `pipeline/step06_TSDAY_data_collection.ipynb` |
| step10 mechanism check | `experiments/exp02_stop_reentry/step01_mechanism_check.ipynb` |
| step11 daily signal check | `experiments/exp02_stop_reentry/step02_signal_check.ipynb` |
| step12 walk-forward | `experiments/exp02_stop_reentry/step03_walk_forward.ipynb` |
| step13 ATH exploration | `experiments/exp03_ath_exit/step01_exploration.ipynb` (+ new `step02_walk_forward.ipynb`) |

| Trial-log experiment before | After |
|---|---|
| `signal_check_v1(_clean)`, `lgbm_ev_policy_v1(_clean)` | `exp01_minute_entry` |
| `stop_reentry_v2(_clean)` | `exp02_stop_reentry` |
| `ath_exit_exploration(_clean)` | `exp03_ath_exit` |
| `audit_bad_tick_sensitivity_v2` | (audit only; `records/legacy/audit_trials_20261005.csv`) |

The previous trial log (4,089 entries) is kept as `records/legacy/trial_log_legacy_20261005.csv` (copied from
`store03_goldzone/trial_log/trial_log.csv` before that folder was deleted). Its trials count in the thesis.
