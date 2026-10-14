# Stock Overflow: Research Workspace

A thesis-style research project. Can a rules-plus-model strategy on **SPY** (1-minute IBKR bars, 2005 onward, long only,
no leverage) beat **buy-and-hold** after realistic costs, out of sample?

Every experiment follows a written protocol: its rules are fixed before its results are seen, stopping rules are applied,
every trial is logged, and failed experiments are kept as results.

**This workspace was reorganized on 2026-10-05** so that every experiment is self-contained and re-runnable from a clean
state. Everything before that date (code, results, the 4,089-entry trial log, the audit) is kept in `docs/history/`,
`records/legacy/` and the git tag `pre-refactor-20261005`.

## 1. Layout

```
stock_overflow_workspace/
├── README.md                    this guide
├── pyproject.toml               makes so/ and experiments/ importable from any folder (pip install -e .)
├── setup_venv.py, requirements/ environment
├── so/                          SHARED LIBRARY (never experiment-specific)
│   ├── config.py                shared constants: features, execution and costs, statistics, walk-forward conventions
│   ├── paths.py                 data folders (override the root with the environment variable SO_DATA_PATH)
│   ├── core/                    raw data loading, data quality, bad ticks, execution, simulators, schedule,
│   │                            signal-check building blocks, evaluation (honest reporting), trial log
│   └── features/                price action, indicators, snapshots, context, barrier targets, daily features
├── pipeline/                    SHARED DATA notebooks, steps 00-06 (kept across experiments)
├── experiments/                 ONE FOLDER PER EXPERIMENT: PROTOCOL.md, config.py, code, notebooks
│   ├── README.md                registry of experiments + how to add one
│   ├── _template/               starting point for a new experiment
│   ├── exp01_minute_entry/      minute entries with a model-chosen SL/TP distance (formerly v1)
│   ├── exp02_stop_reentry/      trailing stop + model re-entry (formerly v2)
│   └── exp03_ath_exit/          sell near the all-time high, buy back later (formerly the step 13 exploration)
├── scripts/                     command line tools (bad tick correction)
├── tests/                       plain-assert test suites on synthetic data (python tests/run_all_tests.py)
├── docs/
│   ├── RESULTS_LOG.md           every result of the reorganized workspace (start here)
│   ├── RERUN_GUIDE_2026-10-05.md  what to delete and what to run, in order, for the clean re-execution
│   └── history/                 the documents of the previous workspace (results, protocols v1/v2, audit, handover)
└── records/                     versioned CSV records (bad tick corrections; legacy trial log; holdout registry and ledger)
```

## 2. Current status (2026-10-12)

| Experiment | Status | Protocol |
|---|---|---|
| Pipeline steps 00-06 | Built and kept (5,436 sessions, 2005-01-03 -> 2026-08-13, bad ticks corrected) | `pipeline/README.md` |
| exp01_minute_entry | **running** (development notebook launched 2026-10-14 18:29, protocol 2.0, not finished). Protocol 1.0/1.1 (signal check p = 0.10) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp01_minute_entry/PROTOCOL.md` |
| exp02_stop_reentry | **STOP** (2026-10-12, protocol 2.0, re-run under the new rules: prior-only +61.82% vs +199.04%). Protocol 1.0 (+111.66% vs +237.21%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp02_stop_reentry/PROTOCOL.md` |
| exp03_ath_exit | **STOP** (2026-10-12, protocol 2.0, re-run under the new rules: prior-only +111.12% vs +199.04%). Protocol 1.0 (+143.05% vs +237.21%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp03_ath_exit/PROTOCOL.md` |
| exp04_trend_exit | **STOP** (2026-10-14, protocol 2.0, re-run under the new rules: prior-only +41.51% vs +199.04%). Protocol 1.0 (+70.84% vs +229.74%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp04_trend_exit/PROTOCOL.md` |
| exp05_vol_scaled_exposure | **STOP** (2026-10-14, protocol 2.0, re-run under the new rules: prior-only +142.59% vs +199.04%). Protocol 1.0 (+165.69% vs +229.74%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp05_vol_scaled_exposure/PROTOCOL.md` |
| exp06_capped_regret_reentry | **STOP** (2026-10-14, protocol 2.0, re-run under the new rules: prior-only +132.25% vs +199.04%). Protocol 1.0 (+147.38% vs +229.74%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp06_capped_regret_reentry/PROTOCOL.md` |
| exp07_warning_lights_exit | **STOP** (2026-10-14, protocol 2.0, re-run under the new rules: prior-only +40.95% vs +199.04%). Protocol 1.0 (+49.09% vs +229.74%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp07_warning_lights_exit/PROTOCOL.md` |
| exp08_vix_signal_check | **archived** (was DONE, VIX line STOP; no gate opens: G1, G2, G4 fail; G3 passes) | `experiments/exp08_vix_signal_check/PROTOCOL.md` |
| exp09-exp11 (VIX) | **archived** (was SKIPPED by exp08's pre-registered gates) | `docs/RESEARCH_STATE_2026-10-11.md` §6 |
| exp12_vix_fear_reentry | **STOP** (2026-10-14, protocol 2.0, re-run under the new rules: prior-only +126.51% vs +199.04%). Protocol 1.0 (+119.24% vs +229.74%) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp12_vix_fear_reentry/PROTOCOL.md` |
| exp13_e1m1_robustness | **candidate pending review** (2026-10-14, protocol 2.0, re-run under the new rules: prior-only +273.85% vs +199.04%; 6-month interval contains 0). Not a success claim. Holdout evaluation is parked. Protocol 1.0 (E1M1 IS NOT ROBUST) stays in the results log; its code is at tag `pre-port-20261012` | `experiments/exp13_e1m1_robustness/PROTOCOL.md` |
| Rolling holdout | Infrastructure in place. A window is registered. The agent does not read it and does not evaluate it | `so/core/holdout.py` |
| Text / qualitative data | Blocked: new data source (parked decision for Nicolas) | `docs/RESEARCH_STATE_2026-10-11.md` |

*Corrections 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`): exp06's "beats its
random baselines" means it beat the median of each random family (19/20, 15/20; empirical p ≈ 0.10 and ≈ 0.29):
"consistent with weak timing information; not statistically supported" (I2). exp07's "all 12 exits bought back higher"
= 11 closed episodes, all bought back higher, plus 1 episode open at the end (I4).*

**Start here:** `docs/RESEARCH_STATE_2026-10-11.md` (state and roadmap), then `docs/RESULTS_LOG.md`. Agents also read
`AGENTS.md` and `.cursor/rules/`.

Earlier results (stopped v1 and v2, the step 13 exploration) are summarized in `docs/history/RESULTS_LOG_2026-10-05.md`.
**A holdout window is registered. It has not been evaluated, and no archived test window was evaluated as a holdout.** The 2015-2026 validation quarters have
been looked at many times (they are development data, not out-of-sample data); see `docs/history/AUDIT_2026-10-05.md` §F6.
exp01's development run has not finished. exp02–exp07, exp12 and exp13 are protocol 2.0. The evaluation design from 2026-10-11 is the
rolling 12-month holdout (`so.core.holdout`).

## 3. Setup (once per machine)

You need Python 3.12. One venv, `venv-main`, built from both requirements files; the script also installs this workspace
in editable mode (`pip install -e .`), so `so` and `experiments` import from any notebook folder:

```
python setup_venv.py --name venv-main --requirements venv_main_requirements.txt venv_market_requirements.txt --kernel
```

If `venv-main` already exists, the same command reuses it. To add only the editable install to an existing venv:
`venv-main\Scripts\python -m pip install -e .` from the workspace folder.

## 4. Machines and workflow

- Code is edited in Cursor on **nicosls**, committed and pushed, then pulled on **nicodesktop**. From 2026-10-06 the
  research is also continued by a Cursor agent working directly on **nicodesktop** (`AGENTS.md`, `.cursor/rules/`).
- Notebooks run on the Jupyter server of **nicodesktop** (kernel `venv-main`); data lives there, in
  `C:/Users/nico/Desktop/stock_overflow_data/` (`so.paths.LOCAL_PATH_STR`).
- **Restart the kernel before running a notebook** after any `.py` change ("Run All" keeps old imports in memory).
- **Commit executed notebooks with their outputs** after every run: the saved outputs are evidence for the thesis.
- **Data never goes into git** (`.gitignore`), except `records/`.
- Before starting a new experiment version: commit everything and tag the commit.

## 5. Data folders (`so/paths.py`)

| Zone | Folder | Written by | Kept? |
|---|---|---|---|
| raw | `store01_rawzone/ibkr_spy_1min/` | IBKR download, bad ticks corrected once (`records/bad_tick_corrections.csv`) | always |
| pipeline | `store02_workzone/step00_data_quality_report/` | pipeline step 00 | yes |
| pipeline | `store02_workzone/step01_PA_ohlcv_data/` ... `step04_TSCTX_data/` | pipeline steps 01-04 (per-day caches) | yes |
| pipeline | `store03_goldzone/step05_TSBAR_data/` | pipeline step 05 (barrier targets, per day) | yes |
| pipeline | `store02_workzone/step06_TSDAY_data/` | pipeline step 06 (daily table, one file) | regenerated in seconds |
| experiments | `store04_experiments/<experiment>/<stepNN_..._data>/` | the experiment's notebooks | regenerate by re-running |
| experiments | `store04_experiments/trial_log.csv` | every experiment notebook | **never edit** |

`SO_EXPERIMENT_ZONE_PATH`, when set in the process, replaces `store04_experiments` for that process. The trial log moves with it. Unset, the path is unchanged.
| records | `records/holdout_windows.csv` | `scripts/holdout_window.py` (Nicolas only) | append-only; a retired row is filled once |
| records | `records/holdout_evaluations.csv` | `scripts/holdout_evaluate.py` (Nicolas only) | append-only summary metrics; `status` is `valid` or `invalid_lookahead` |
| holdout results | `SO_HOLDOUT_PATH` (no default) | the holdout evaluation | daily paths; not in git |

A strategy does not read these folders itself. Every series is registered in `so.core.point_in_time` (timestamp
convention, availability rule, revision policy) and is read through `DataContext`. How to register a source, including
sources the project may add later, is `docs/DATA_SOURCES.md`.

Deleting an experiment's folder never affects the pipeline or another experiment. `SO_HOLDOUT_PATH` is an environment
variable with no default: when it is unset, holdout results cannot be written. Agents never set it.

## 6. Research discipline

- **One experiment = one folder, one protocol, one config, one name.** The protocol (`PROTOCOL.md`) is written and agreed
  before the experiment's data is explored. Once the first validation run exists, any rule change is a new protocol version
  with a new `EXPERIMENT_NAME` in the experiment's `config.py` (e.g. `exp02_stop_reentry_v1_1`).
- **Exploration is allowed only on 2005-01-03 -> 2014-12-31** (`so.config.EXPLORATION_*`): training data in every fold.
- **Development** runs up to the session an embargo before the active holdout start
  (`so.core.holdout.get_development_end_date`). Validation folds come from `so.core.schedule.get_development_fold_pdf`.
  If no holdout window is registered, development notebooks must refuse to run.
- **The holdout** is the last 12 calendar months of the data when Nicolas opens the window
  (`scripts/holdout_window.py`). Once opened it is frozen. Sessions after its end are forward data and are refused.
  The result is the design's frozen prior-only path from its development start, continued through the window: same
  code, same 15:58 decision and 15:59 fill, same costs, dead band and selection rule, with selection history and
  position carried over. Only the holdout sessions are reported. Before a result is written, the runner checks each of
  12 month-ends in the window twice: it drops the sessions after the cut (the cut session stays whole, so its decision
  bar does not move), and it overwrites every bar strictly after that session's decision bar, from the fill bar through
  the end of the data, with price × 1.25 plus seeded noise, leaving the session structure unchanged. Target weights and
  signals through the cut session must match, as must positions, weights and trades strictly before the cut, and the
  candidate for periods that end before the cut. The same two checks apply to every other registered source through
  `so.core.point_in_time.DataContext`: rows with `available_ts` after the cut session's last bar are dropped, and feature
  values with `available_ts` after the decision are perturbed (labels are not). The ledger row lists the sources the
  design read (`sources_read`). Fills on the cut session are not compared. A difference is ledger
  status `invalid_lookahead` (no daily paths, and the row counts against the budget). Each frozen design may be
  evaluated once per window, at most 10 designs, and only by Nicolas (`scripts/holdout_evaluate.py`). Agents never set
  `SO_HOLDOUT_PATH`, `SO_HOLDOUT_EVALUATION_TOKEN` or `SO_ALLOW_LEGACY_REPRODUCTION`, and never run those scripts.
- **A model-based design is a walk-forward with a rolling training window** (`so.core.rolling_retrain`, Nicolas 2026-10-11). It refits on a pre-registered schedule, default weekly (the first session of each week), using only rows whose label was complete before that day's decision bar. Unfinished labels are dropped, never filled. The default training-window candidates are 6 months, 2 years and 10 years. The candidate for a quarter is chosen from the last 4 completed quarters, prior-only. Development notebooks and the holdout report share `so.core.evaluation.get_performance_over_time_pdf` (cumulative log excess, rolling 63- and 252-session excess, drawdowns, and the quarter table), plus turnover, candidate switches, and the refit log (rows used, share purged, prediction move). Changing the frequency or the windows after a result is a new version. Archived experiments are not refit this way.
- **Archived experiments** (exp01–exp13) keep their recorded numbers and stay pinned to the old boundary 2026-05-14.
  Nicolas re-runs them only with `SO_ALLOW_LEGACY_REPRODUCTION=1`, which cannot extend past that date.
- **Every exploration, signal check, validation candidate, summary and test is logged** in the shared trial log, with the
  experiment name, protocol version and a configuration hash covering `so/config.py` + the experiment's `config.py`.
  Each notebook warns when the trial log already holds entries of the same stage: running it again adds trials.
- **Honest reporting** in every walk-forward (`so/core/evaluation.py`): the best candidate after the fact (optimistic),
  the prior-only path (the honest validation estimate), the uninformed baselines on the same quarters (the information
  test), time in the market and the minimum detectable effect.
- **Results go into `docs/RESULTS_LOG.md` the same day**, including failures.

## 7. Tests

```
python tests/run_all_tests.py
```

Sixteen suites on synthetic data (a few minutes). All must end with "passed ✅". Run them after every code change.
The list is the header of `tests/run_all_tests.py`.

### Reproduction

`scripts/reproduce_archived.py` was dropped on 2026-10-12 (Nicolas: replace each experiment in place). It read the
archived notebooks from the working tree. Those notebooks stay at tag `pre-port-20261012`. The headline numbers copied
from them stay in `records/archived_reproduction_expected.csv`. The check is not run.

## 8. Conventions

- Every code line is preceded by an UPPERCASE `#` comment; each function has a `# FUNCTION:` header and a docstring.
- Suffixes: `_pdf` (DataFrame), `_str`, `_list`, `_dict`, `_arr` (numpy array), `_in` (parameters), `_bool`, `_float`, `_int`.
- Per-day CSV files `{name}_YYYYMMDD.csv` are written by `so.core.local_file_management.generate_func_data_date_list`.
- Timestamps are parsed as UTC and converted to `America/New_York`.
- Notebooks are named `stepNN_<purpose>.ipynb` and start with a docstring cell (objective, prerequisites, outputs), then an
  imports cell. Experiment notebooks write to `store04_experiments/<experiment>/stepNN_<purpose>_data/`.
- Inside a notebook, `config` is the shared configuration and `exp_config` the experiment's configuration.
- `.py` and `.md` files use CRLF line endings.
