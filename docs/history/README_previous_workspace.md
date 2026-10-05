# Stock Overflow — Experiment Workspace

A thesis-style research project. Can a rules-plus-model strategy on **SPY** (1-minute IBKR bars, 2005 onward, long only, no leverage) beat **buy-and-hold** after realistic costs, out of sample?

Every experiment follows a written protocol: the rules are fixed before results are seen, stopping rules are applied, and every trial is logged. Failed experiments are kept as results.

| Document | What it holds |
|---|---|
| `docs/RESULTS_LOG.md` | **Start here.** Every result so far, the trial-log counts and the open verifications |
| `docs/RESEARCH_PROTOCOL.md` | Protocol v1 (steps 05–08). **Stopped** 2026-10-04 |
| `docs/RESEARCH_PROTOCOL_v2.md` | Protocol v2, stop and re-entry (steps 09–12). **Stopped** 2026-10-04 |
| `docs/SO_pipeline_understanding.md` | How the original pipeline worked, the decisions behind the rebuild, and the old → new step numbering (§14) |

## 1. Current status (2026-10-05)

| Experiment | Steps | Status |
|---|---|---|
| Shared data pipeline | 00–04 | Built and run on all 5,436 sessions (2005-01-03 → 2026-08-13) |
| Raw data correction (bad ticks) | 00–13 | Done 2026-10-04/05: 62 wicks (2005–2009) cut by `fix_raw_bad_ticks.py`; v1 rebuilt for the affected dates, v2 and step 13 rerun, all as `*_clean` experiments (§5) |
| v1: minute entries with symmetric SL/TP | 05–08 | Stopped, confirmed on corrected data: no signal beyond market drift; no setting beat buy-and-hold on validation |
| v2: trailing stop + model re-entry | 09–12 | Stopped, confirmed on corrected data: stops sell into dips that revert; 0 signals; no candidate beat buy-and-hold on validation |
| "Sell at strength" (all-time-high exits) | 13 | Exploration on 2005–2014 only: weak and inconsistent (5 of 15 rules beat buy-and-hold, none at the 1% threshold); not evidence of an edge |
| **v3: add VIX information** | — | **Next.** Its protocol will be written and agreed before any VIX data is explored |

**No test window has ever been evaluated** (`test_window_touched = 0` for every trial). The 2015–2026 test windows will be used once, on the final frozen design.

## 2. Machines and workflow

- **The repository** lives on GitHub.
- **Code is edited in Cursor on nicosls**, committed and pushed, then pulled on nicodesktop.
- **Notebooks run on a Jupyter server on nicodesktop.** Cursor on nicosls uses that kernel. So every notebook reads and writes data on **nicodesktop**, at `C:/Users/nico/Desktop/stock_overflow_data/` (`paths.LOCAL_PATH_STR`). That folder is also reachable as a network share (`\\100.123.162.2\stock_overflow_data`).
- **Data never goes into git.** `.gitignore` excludes `*.csv`, `*.parquet`, venvs, caches and credentials. The single exception is `records/` (§7).
- **Restart the notebook kernel before every run that depends on a changed `.py` file.** "Run All" does not reload a module that a still-open kernel already imported (this caused a mislabeled duplicate v2 run on 2026-10-04, see `docs/RESULTS_LOG.md`).
- **Executed notebooks are committed with their outputs.** The saved outputs are part of the evidence for the thesis. Commit them after every run, with a message that says what was run.
- **Before starting a new experiment,** commit everything and tag the commit, e.g. `git tag v2-final`.

## 3. Setup

You need Python 3.12 (the requirements were frozen on 3.12.0). One venv, `venv-main`, on nicodesktop, built from both requirements files:

```
python setup_venv.py --name venv-main --requirements venv_main_requirements.txt venv_market_requirements.txt --kernel
```

- **Both files are needed.** `datetime_utils.py` needs `pandas_market_calendars`, which is in the market file. The two files share no package.
- `--kernel` registers the venv as the Jupyter kernel `venv-main`; select that kernel in the notebooks.
- `python setup_venv.py` with no arguments runs interactively. Requirements files are looked up in this folder and in `requirements/`.

## 4. Data folders (`paths.py`)

All under `C:/Users/nico/Desktop/stock_overflow_data/`. A folder is created when the first file is written. Only folders written by a notebook carry a step number.

| Constant | Folder | Written by |
|---|---|---|
| `LOCAL_OHLCV_DATA_FILE_PATH_STR` | `store01_rawzone/ibkr_ohlcv_data/` | IBKR download (yearly files); bad ticks corrected once by `fix_raw_bad_ticks.py` |
| `LOCAL_DQ_REPORT_DATA_FILE_PATH_STR` | `store02_workzone/step00_data_quality_report/` | step 00 |
| `LOCAL_PA_OHLCV_DATA_FILE_PATH_STR` | `store02_workzone/step01_PA_ohlcv_data/` | step 01 (cache from the previous workspace, renamed) |
| `LOCAL_TSIND_DATA_FILE_PATH_STR` | `store02_workzone/step02_TSIND_data/` | step 02 (files copied from the previous workspace's step 06) |
| `LOCAL_TSSEG_DATA_FILE_PATH_STR` | `store02_workzone/step03_TSSEG_data/` | step 03 (files copied from the previous workspace's step 08) |
| `LOCAL_TSCTX_DATA_FILE_PATH_STR` | `store02_workzone/step04_TSCTX_data/` | step 04 |
| `LOCAL_TSBAR_DATA_FILE_PATH_STR` | `store03_goldzone/step05_TSBAR_data/` | step 05 |
| `LOCAL_MODEL_DATASET_DATA_FILE_PATH_STR` | `store03_goldzone/step06_model_dataset_data/` | step 06 |
| `LOCAL_SIGNAL_CHECK_DATA_FILE_PATH_STR` | `store03_goldzone/step07_signal_check_data/` | step 07 |
| `LOCAL_WALK_FORWARD_DATA_FILE_PATH_STR` | `store03_goldzone/step08_walk_forward_data/<experiment>/` | step 08 |
| `LOCAL_TSDAY_DATA_FILE_PATH_STR` | `store02_workzone/step09_TSDAY_data/` | step 09 (one file, `TSDAY_data.csv`) |
| `LOCAL_MECHANISM_CHECK_DATA_FILE_PATH_STR` | `store03_goldzone/step10_mechanism_check_data/` | steps 10 and 13 |
| `LOCAL_DAILY_SIGNAL_CHECK_DATA_FILE_PATH_STR` | `store03_goldzone/step11_daily_signal_check_data/` | step 11 |
| `LOCAL_STOP_REENTRY_WALK_FORWARD_DATA_FILE_PATH_STR` | `store03_goldzone/step12_stop_reentry_walk_forward_data/<experiment>/` | step 12 |
| `LOCAL_TRIAL_LOG_FILE_PATH_STR` | `store03_goldzone/trial_log/trial_log.csv` | steps 07, 08 and 10–13 (one shared file) |
| `STRAT01…14_DATA_FILE_PATH_STR` | `store02_workzone/strat01…14_transaction_data/` | legacy, read-only |
| *(commented out)* `LOCAL_LEGACY_TS_DELTA_MATRIX_SELL_DATA_FILE_PATH_STR` | `store03_goldzone/step12_TS_delta_matrix_sell_data/` | legacy target of the previous workspace; nothing reads it |

## 5. Notebooks

| Step | Notebook | Branch | Output / purpose |
|---|---|---|---|
| 00 | `step00_data_quality_check.ipynb` | shared | Candlestick sanity, bad ticks (`fix_raw_bad_ticks.py` rule; 0 expected after the fix), bars per session against the NYSE schedule, missing sessions. Run first and whenever raw data changes |
| 01 | `step01_PA_ohlcv_data_collection.ipynb` | shared | Per-minute price-action snapshots (cache) |
| 02 | `step02_TSIND_data_collection.ipynb` | shared (v1) | 43 indicator fields per minute, each from its own snapshot. Last cell: spot check of the copied files |
| 03 | `step03_TSSEG_data_collection.ipynb` | shared (v1) | `cum_max` and the segment fields. Last cell: spot check of the copied files (4/5 identical; 2021-08-24 differs, see `docs/RESULTS_LOG.md`) |
| 04 | `step04_TSCTX_data_collection.ipynb` | shared | Context features per minute; tested for look-ahead |
| 05 | `step05_TSBAR_data_collection.ipynb` | v1 | Barrier target matrix (32 SL/TP distances) |
| 06 | `step06_model_dataset_generation.ipynb` | v1 | Joins features and targets |
| 07 | `step07_signal_check.ipynb` | v1 | v1 stopping rule |
| 08 | `step08_walk_forward_evaluation.ipynb` | v1 | v1 walk-forward (`RUN_MODE_STR`) |
| 09 | `step09_TSDAY_data_collection.ipynb` | v2 | One row per session at 15:58: 16 daily features and the 20-session label |
| 10 | `step10_mechanism_check.ipynb` | v2 | Exploration (2005–2014): the stop without information, the oracle, the post-exit path |
| 11 | `step11_daily_signal_check.ipynb` | v2 | v2 stopping rule: two-sided signal check against the base rate |
| 12 | `step12_stop_reentry_walk_forward.ipynb` | v2 | v2 walk-forward (`RUN_MODE_STR`) |
| 13 | `step13_ath_exit_exploration.ipynb` | exploration | "Sell at strength": forward returns after all-time highs, and 15 simple rules (2005–2014) |

- **Steps 09–13 read only the raw minute bars.** They don't need steps 01–08.
- **Walk-forward notebooks (08, 12)** run in three modes:
  - `validation_only` — no test window is read; this is the only mode used so far;
  - `latest` — the most recent test window;
  - `history` — every test window.

  Never switch to `latest` or `history` before a design is frozen.
- **When new raw data arrives:**
  1. Run step 00.
  2. Run steps 01 → 04 for the missing dates (ignore mode `"I"`).
  3. Run step 05: regenerate the incomplete dates (mode `"W"`), then the missing ones.
  4. Run step 06: the 30 most recent dates, then the missing ones.

  Steps 09–13 rebuild their tables from the raw data each time.
- **Raw data correction of 2026-10-04 (one-off, bad ticks):**
  1. Commit everything and tag it: `git tag v2-final`. The committed notebook outputs are the record of the pre-fix runs (steps 09, 10 and 13 overwrite their CSV files).
  2. `python fix_raw_bad_ticks.py` — dry run: lists the 62 wicks it would cut, writes nothing.
  3. `python fix_raw_bad_ticks.py --apply` — backs up the 5 changed yearly files to `store01_rawzone/ibkr_ohlcv_data_backup_<timestamp>/`, corrects them, verifies that only the flagged cells changed, writes `records/bad_tick_corrections.csv` and ends with "Remaining bad ticks after the fix: 0".
  4. Commit `records/bad_tick_corrections.csv`.
  5. Rerun step 00 (bad ticks = 0), then steps 09 → 10 → 11 → 12 (`validation_only`) → 13. They log as `stop_reentry_v2_clean` and `ath_exit_exploration_clean`.
  6. Copy the trial log to `records/`, commit the executed notebooks, and send the outputs for `docs/RESULTS_LOG.md`.

  7. v1 (steps 01–08), targeted rebuild: `python invalidate_bad_tick_dates.py` (dry run), then `--apply`. It moves the per-day files of steps 01–06 that can depend on a corrected cell to `stock_overflow_data/archive_bad_tick_invalidated_<timestamp>/` and writes `records/bad_tick_invalidated_dates.csv`. Then run steps 01 → 06 (they regenerate the missing dates) and steps 07 → 08 in full (`signal_check_v1_clean`, `lgbm_ev_policy_v1_clean`).
  8. `python verify_model_dataset.py`: rebuilds every step 06 day in memory and compares it with the saved file (`records/model_dataset_verification.csv`). Must report 0 differences; `--apply` moves stale files so step 06 regenerates them.

  All of this was done on 2026-10-04/05; the results are in `docs/RESULTS_LOG.md`.

## 6. Code

| File | Purpose |
|---|---|
| `config.py` | v1 constants: features, targets, costs, splits, sampling, model, feature registry. **Do not add v2+ constants here:** that would change the v1 config hash (`ff9d0d7e2e`) |
| `config_v2.py` | v2 constants. Shared constants (costs, fees, capital, bootstrap) are read from `config.py`. Its hash covers both files: `f661934b1a` for `stop_reentry_v2` (uncorrected data), `34455c40ce` for `stop_reentry_v2_clean` (same rules, corrected data; only the name changed) |
| `paths.py` | Data folders (§4) |
| `fix_raw_bad_ticks.py` | One-off raw data correction (2026-10-04): the bad tick rule (`get_bad_tick_pdf`, also used by step 00), backup, overwrite, verification and correction log. Dry run by default; `--apply` to write. Rule and steps in its docstring |
| `invalidate_bad_tick_dates.py` | Targeted v1 rebuild after the correction: which per-day files of steps 01–06 depend on a corrected cell (bad days, `cum_max` days, next sessions, holding windows); moves them to an archive. Dry run by default |
| `verify_model_dataset.py` | Consistency check: every saved step 06 day equals a rebuild from the current step 02–05 files. Read only by default |
| `datetime_utils.py`, `data_quality.py`, `local_file_management.py` | NYSE calendar, data checks, per-day CSV helpers (`generate_func_data_date_list`, modes `I` / `W`) |
| `ohlcv_data_utils.py`, `tf_ohlcv_tools.py` | Price-action columns and indicators (defaults read from `config.py`) |
| `snapshot_features.py` | Steps 01–03: snapshots, TSIND row, TSSEG rows (moved from the previous notebooks, logic unchanged) |
| `context_features.py` | Step 04: TSCTX context features |
| `trade_execution.py` | **The single source of truth for execution:** arrays, holding window, barrier fills, fees, net return, break-even rate |
| `barrier_labels.py`, `model_dataset.py`, `signal_check.py`, `walk_forward.py` | v1: steps 05–08 |
| `backtest_simulation.py`, `performance_metrics.py` | Simulator, daily equity, buy-and-hold and baselines; total return, Sharpe ratio, max drawdown |
| `daily_features.py` | v2 step 09: daily features and label |
| `stop_reentry_simulation.py` | v2: trailing stop, re-entry rules (model, fixed delay, random, oracle), forced re-entry, trend rule, episodes, post-exit path. Also used by step 13 |
| `signal_check_v2.py` | v2 step 11: two-sided base-rate signal check. `min_month_count_in` guards against degenerate intervals (default off, to reproduce v2; set it in new experiments) |
| `walk_forward_v2.py` | v2 step 12: schedule (20-session embargo), models, pooled selection, test, bootstrap, success criteria, v2 trial-log function (accepts any experiment name) |
| `trial_log.py` | Trial log file, v1 hash |
| `plot_ohlcv_utils.py`, `buy_eval_utils.py` | Plotly charts; ideal vs predicted buys on TSBAR |
| `setup_venv.py`, `requirements/` | Environment |
| `tests/` | `run_tests.py` (v1 and shared), `run_tests_v2.py` (v2), `synthetic_data.py` |

**Known open issues**, kept as they are because nothing current depends on them:
- `validate_der_price_ohlcv_pdf_list` never actually compares values.
- `get_pdf1_pdf2_diff_list` returns at the first difference.
- The `ms_*` columns lose `""` to NaN on a CSV round trip.

The changes made to the original modules during the rebuild are listed in `docs/SO_pipeline_understanding.md` §13–14.

## 7. Research discipline

- **A new experiment means a new protocol version**, a new config file (`config_v3.py`, …) and a new experiment name. All of these are agreed before its data is explored.
- **Exploration is allowed only on 2005-01-03 → 2014-12-31.** That period is training data in every walk-forward fold.
- **Every exploration, signal check, validation candidate and test is logged** in the trial log.
- **The trial log is the record of how many things were tried.** It lives in the data folder, outside git. After each session, copy it to `records/trial_log_snapshot.csv` and commit it. `records/` is the one folder whose CSV files git keeps.
- **Results go into `docs/RESULTS_LOG.md` the same day**, including failures.

## 8. Tests

Run from the workspace folder with `venv-main` active (either machine: they use synthetic data only):

```
python tests/run_tests.py       # v1 and shared code: execution rules, targets, no look-ahead, schedule, signal check, snapshot features, plots, bad tick rule
python tests/run_tests_v2.py    # v2: daily features vs TSCTX, no look-ahead, label, simulator vs a bar-by-bar reference, selection, signal check (incl. the month minimum), success criteria, end-to-end fold
```

Both must end with "All … tests passed ✅". Run them after every code change.

## 9. Conventions

- Every code line is preceded by an UPPERCASE `#` comment.
- Each function has a `# FUNCTION:` header and a docstring.
- Suffixes: `_pdf` (DataFrame), `_str`, `_list`, `_dict`, `_arr` (numpy array), `_in` (parameters), `_bool`, `_float`, `_int`.
- Per-day CSV files `{name}_YYYYMMDD.csv` are written by `generate_func_data_date_list`.
- Timestamps are parsed as UTC and converted to `America/New_York`.
- Notebooks are named `stepNN_<purpose>.ipynb` and start with a docstring cell (objective, prerequisites), then an imports cell.
- `.py` and `.md` files use CRLF line endings.
