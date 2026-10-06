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
└── records/                     versioned CSV records (bad tick corrections; legacy trial log and audit trials)
```

## 2. Current status (2026-10-06)

| Experiment | Status | Protocol |
|---|---|---|
| Pipeline steps 00-06 | Built and kept (5,436 sessions, 2005-01-03 -> 2026-08-13, bad ticks corrected) | `pipeline/README.md` |
| exp01_minute_entry | **STOP** (signal check p = 0.10; prior-only +146.94% vs buy-and-hold +218.48%) | `experiments/exp01_minute_entry/PROTOCOL.md` |
| exp02_stop_reentry | **STOP** (prior-only +111.66% vs +237.21%) | `experiments/exp02_stop_reentry/PROTOCOL.md` |
| exp03_ath_exit | **STOP** (prior-only +143.05% vs +237.21%) | `experiments/exp03_ath_exit/PROTOCOL.md` |
| exp04_trend_exit | **STOP** (continuous replay: prior-only +70.84% vs +229.74%) | `experiments/exp04_trend_exit/PROTOCOL.md` |
| exp05_vol_scaled_exposure | **STOP** (prior-only +165.69% vs +229.74%; lower drawdown) | `experiments/exp05_vol_scaled_exposure/PROTOCOL.md` |
| exp06_capped_regret_reentry | **STOP** (prior-only +147.38% vs +229.74%; beats its random baselines) | `experiments/exp06_capped_regret_reentry/PROTOCOL.md` |
| exp07, then VIX, then text | Planned: the "stay invested, exit rarely" family | `docs/RESEARCH_STATE_2026-10-06.md` |

**Start here:** `docs/RESEARCH_STATE_2026-10-06.md` (state and roadmap), then `docs/RESULTS_LOG.md`. Agents also read
`AGENTS.md` and `.cursor/rules/`.

Earlier results (stopped v1 and v2, the step 13 exploration) are summarized in `docs/history/RESULTS_LOG_2026-10-05.md`.
**No test window has ever been evaluated.** The 2015-2026 validation quarters have been looked at many times (they are
development data, not out-of-sample data); see `docs/history/AUDIT_2026-10-05.md` §F6.

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
| raw | `store01_rawzone/ibkr_ohlcv_data/` | IBKR download, bad ticks corrected once (`records/bad_tick_corrections.csv`) | always |
| pipeline | `store02_workzone/step00_data_quality_report/` | pipeline step 00 | yes |
| pipeline | `store02_workzone/step01_PA_ohlcv_data/` ... `step04_TSCTX_data/` | pipeline steps 01-04 (per-day caches) | yes |
| pipeline | `store03_goldzone/step05_TSBAR_data/` | pipeline step 05 (barrier targets, per day) | yes |
| pipeline | `store02_workzone/step06_TSDAY_data/` | pipeline step 06 (daily table, one file) | regenerated in seconds |
| experiments | `store04_experiments/<experiment>/<stepNN_..._data>/` | the experiment's notebooks | regenerate by re-running |
| experiments | `store04_experiments/trial_log.csv` | every experiment notebook | **never edit** |

Deleting an experiment's folder never affects the pipeline or another experiment.

## 6. Research discipline

- **One experiment = one folder, one protocol, one config, one name.** The protocol (`PROTOCOL.md`) is written and agreed
  before the experiment's data is explored. Once the first validation run exists, any rule change is a new protocol version
  with a new `EXPERIMENT_NAME` in the experiment's `config.py` (e.g. `exp02_stop_reentry_v1_1`).
- **Exploration is allowed only on 2005-01-03 -> 2014-12-31** (`so.config.EXPLORATION_*`): training data in every fold.
- **Walk-forward notebooks run in `validation_only` mode** until a design is frozen. Test windows are evaluated once.
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

Three suites on synthetic data (a few minutes): shared code + exp01, exp02 (+ daily features, simulator, evaluation,
trial log), exp03. All must end with "passed ✅". Run them after every code change.

## 8. Conventions

- Every code line is preceded by an UPPERCASE `#` comment; each function has a `# FUNCTION:` header and a docstring.
- Suffixes: `_pdf` (DataFrame), `_str`, `_list`, `_dict`, `_arr` (numpy array), `_in` (parameters), `_bool`, `_float`, `_int`.
- Per-day CSV files `{name}_YYYYMMDD.csv` are written by `so.core.local_file_management.generate_func_data_date_list`.
- Timestamps are parsed as UTC and converted to `America/New_York`.
- Notebooks are named `stepNN_<purpose>.ipynb` and start with a docstring cell (objective, prerequisites, outputs), then an
  imports cell. Experiment notebooks write to `store04_experiments/<experiment>/stepNN_<purpose>_data/`.
- Inside a notebook, `config` is the shared configuration and `exp_config` the experiment's configuration.
- `.py` and `.md` files use CRLF line endings.
