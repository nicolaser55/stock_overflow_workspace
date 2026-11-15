# Stock Overflow: research workspace

Can a long-only, unlevered strategy on **SPY** (1-minute IBKR bars, 2005 onward) beat **buy-and-hold's return**
after realistic costs, out of sample? Returns are total returns on both sides (roadmap R4b, 2026-11-09): SPY dividends
are credited at the ex-date open and cash earns the 3-month T-bill rate, for the strategy, buy-and-hold and every
baseline. The verdict passes only a strategy whose total return is strictly above buy-and-hold's (2026-11-14); whether it
reaches 90% of buy-and-hold with a better Sharpe ratio or drawdown is reported beside it, never as a pass. Every
experiment is a design on one shared point-in-time runner: the runner shows
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
| Queue a run at the current (pushed, clean) commit | `scripts\run_queue.py add experiments\<exp> --note "<why>"` |
| Queue state / retry a failed job | `scripts\run_queue.py status`, `scripts\run_queue.py retry <job id>` |
| Run the queue (so_runner; normally the scheduled task `SO queue runner`) | `scripts\run_queue.py watch` (or `run` for one pass) |
| Append finished runs to `docs/RESULTS_LOG.md` (Nicolas; then a pull request) | `scripts\append_results_log.py` |
| Reset the development records, keeping the count of designs tried (Nicolas, development phase only) | `scripts\reset_records.py --backup-folder <folder> [--confirm]` |
| One development run by hand (so_runner, or Nicolas) | `scripts\run_development.py experiments\<exp> --note "<why>"` |
| Set up the agent / runner accounts (Nicolas, administrator) | `scripts\setup_so_runner.ps1`, `scripts\setup_so_agent.ps1`, then `scripts\check_agent_access.py --make-sample-list <data root>\control\access_samples.txt` (nico) and `--sample-list <that file> [--role runner]` as each account; CI repeats both on Windows (`.github/ci/windows_setup_check.ps1`) |
| Protected files changed by a branch | `scripts\check_protected_paths.py --base main` |
| Modules protected code imports but the list misses | `scripts\check_protected_paths.py --closure` |
| Refresh the development view after a download (Nicolas) | `scripts\refresh_development_view.py` |
| Register or slide the holdout window (Nicolas) | `scripts\holdout_window.py` |
| Evaluate a frozen design on the holdout (Nicolas) | `scripts\holdout_evaluate.py --design experiments\<exp> --token-file <file>` |

Agents (`so_agent`) add jobs; the runner account (`so_runner`) runs each job at its commit in a temporary worktree and
alone writes results. A run writes `store04_experiments/runs/<run id>/` (report.md, report.json, lookahead.json,
manifest.json, and per candidate the decisions and scores; the large pickles are deleted once the manifest exists),
appends its rows to the trial log (`store04_experiments/trial_log.csv`), and the queue appends one row per attempt to
`store04_experiments/run_index.csv`. `docs/RESULTS_LOG.md` gets the finished runs through `scripts/append_results_log.py`.
Agents see only `store04_experiments/visible/`: a grade per run (`grades/`, no numbers), a technical status per job
(`status/`, numbers scrubbed) and `state.json` (identifiers only); roadmap R4.
A run refuses uncommitted changes in `so/` or its experiment folder, and a version that breaks pre-registration.

## Data folders (under `SO_DATA_PATH`)

| Folder | Content | Written by |
|---|---|---|
| `store01_rawzone/` | raw IBKR SPY minute bars (bad ticks corrected once, `records/bad_tick_corrections.csv`) and the VIX family | downloads; never edited |
| `store02_workzone/`, `store03_goldzone/` | pipeline caches: TSIND, TSSEG, TSCTX, TSBAR (barrier labels), TSDAY | pipeline notebooks |
| `store04_experiments/` | `runs/`, `trial_log.csv` (append-only), `run_index.csv` (append-only), `queue/`, `checks/`, `visible/` (`state.json`, `grades/`, `status/`) | so_runner (agents may only add files to `queue/pending/` and read `visible/`) |

The development view stops before the registered holdout window (embargo included). A design reads data only through
the point-in-time layer (`so.core.point_in_time`, `docs/DATA_SOURCES.md`).

## Status

The nine experiments (exp01-exp07, exp12, exp13) were rerun as the final stage-1 baseline on 2026-11-13/14 (judge
`12142ab`, frozen V reference over 80 designs, N = 260 with the pilot): all nine fail the verdict (`docs/RESULTS_LOG.md`,
`docs/STAGE1_RESEARCH_PLAN.md` section 2). Next: a few hand-designed experiments under the same rules (roadmap, after
R4e), then the agents. The verdict's label is `pass` or `fail` since 2026-11-14 (earlier rows say "email-worthy" /
"not email-worthy"). The holdout window is registered and has not been evaluated.
