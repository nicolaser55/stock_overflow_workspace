# Stock Overflow: research workspace

Can a long-only, unlevered strategy on **SPY** (1-minute IBKR bars, 2005 onward) beat **buy-and-hold's return**
after realistic costs, out of sample? Returns are price returns for now: dividends are not credited and cash earns 0%,
for the strategy and for buy-and-hold alike (dividends and T-bill interest are planned; audit S2, 2026-10-25). Every experiment is a design on one shared point-in-time runner: the runner shows
a design only what was knowable at each decision, scores its candidates, selects with prior data only, compares with
baselines, checks for look-ahead, and writes a report. Failed experiments are results.

## Layout

```
so/                  shared library
  runner/            the point-in-time runner: views, engines, minute mode, candidates, selection, baselines,
                     look-ahead check, verdict, report, holdout evaluation (docs/RUNNER_DESIGN.md)
  core/              data loading and guards (holdout, point-in-time registry), execution and costs, trial log
  features/          indicators, snapshots, barrier labels, daily and VIX features, design helpers
pipeline/            shared data notebooks, steps 00-07 (pipeline/README.md)
experiments/         one folder per experiment: PROTOCOL.md, config.py, design.py (experiments/README.md)
scripts/             command-line tools (below)
tests/               plain-assert suites on synthetic data
docs/                RESULTS_LOG.md (one row per run), RUNNER_DESIGN.md, DATA_SOURCES.md, VIX_DATA_INVENTORY
records/             versioned CSV records: holdout window registry, bad-tick corrections (the ledger is under SO_HOLDOUT_PATH)
protected_paths.txt  files only Nicolas changes (scripts/check_protected_paths.py)
AGENTS.md            instructions for agents; .cursor/rules/ holds the research-integrity and code rules
```

## Setup (once per machine)

Python 3.12, one venv `venv-main` from both requirements files, the workspace installed in editable mode:

```
python setup_venv.py --name venv-main --requirements venv_main_requirements.txt venv_market_requirements.txt --kernel
```

`requirements/venv_main_lock.txt` is `pip freeze` of that venv. A development run refuses to start when an installed
version differs from the lock (`scripts/check_environment.py`). Only Nicolas changes packages, then writes a new lock.

Environment variables: `SO_DATA_PATH` (the data root, required). Nicolas only: `SO_QUARANTINE_PATH`,
`SO_HOLDOUT_PATH`, `SO_HOLDOUT_EVALUATION_TOKEN` (holdout). Optional, for queue emails: `SO_SMTP_HOST`,
`SO_SMTP_PORT`, `SO_SMTP_USER`, `SO_SMTP_PASSWORD`, `SO_EMAIL_TO`.

## Commands (from the workspace root, with `venv-main\Scripts\python.exe`)

| Task | Command |
|---|---|
| Fast tests (after an edit, a few minutes) | `tests\run_all_tests.py --fast` |
| Full tests (before a merge) | `tests\run_all_tests.py` |
| One development run | `scripts\run_development.py experiments\<exp> --note "<why>"` |
| Several runs in a row | `scripts\run_all_development.py --all` (or a list of folders) |
| Queue a run / run the queue / state | `scripts\run_queue.py add experiments\<exp> --note "<why>"`, `scripts\run_queue.py run`, `scripts\run_queue.py status` |
| Resume a stopped run | `scripts\run_development.py experiments\<exp> --run-id <run id>` |
| Protected files changed by a branch | `scripts\check_protected_paths.py --base main` |
| Modules protected code imports but the list misses | `scripts\check_protected_paths.py --closure` |
| Refresh the development view after a download (Nicolas) | `scripts\refresh_development_view.py` |
| Register or slide the holdout window (Nicolas) | `scripts\holdout_window.py` |
| Evaluate a frozen design on the holdout (Nicolas) | `scripts\holdout_evaluate.py --design experiments\<exp> --token-file <file>` |

A development run writes `store04_experiments/runs/<run id>/` (report.md, report.json, lookahead.json, manifest.json),
appends its rows to the trial log (`store04_experiments/trial_log.csv`) and one row to `docs/RESULTS_LOG.md`. A run
refuses uncommitted changes in `so/` or its experiment folder.

## Data folders (under `SO_DATA_PATH`)

| Folder | Content | Written by |
|---|---|---|
| `store01_rawzone/` | raw IBKR SPY minute bars (bad ticks corrected once, `records/bad_tick_corrections.csv`) and the VIX family | downloads; never edited |
| `store02_workzone/`, `store03_goldzone/` | pipeline caches: TSIND, TSSEG, TSCTX, TSBAR (barrier labels), TSDAY | pipeline notebooks |
| `store04_experiments/` | `runs/`, `trial_log.csv` (append-only), `queue/`, `state.json` | runs and the queue |

The development view stops before the registered holdout window (embargo included). A design reads data only through
the point-in-time layer (`so.core.point_in_time`, `docs/DATA_SOURCES.md`).

## Status

All experiments (exp01-exp07, exp12, exp13) run on the runner under protocol 1.0 of the fresh log started 2026-10-22.
Their results were withdrawn by the 2026-10-25 audit (baselines, look-ahead check, consistency rule) and are rerun
once the fixes are merged; see `docs/RESULTS_LOG.md`. The holdout window is registered and has not been evaluated.
