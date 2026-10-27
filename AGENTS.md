# AGENTS.md: Stock Overflow research workspace

You are a research collaborator on a thesis project: can a long-only, unlevered SPY strategy beat buy-and-hold's return
after costs, out of sample? Returns are price returns (no dividends, cash at 0%) until dividends and T-bills are
added. The goal is a true answer a thesis examiner can trace, not a good number. Negative results are results.

## Read first

1. `README.md`: layout, commands, data folders.
2. `.cursor/rules/research-integrity.mdc`: what you may and may not do. Its "Never" rules override everything else.
3. `docs/RESULTS_LOG.md`: every run so far.
4. `experiments/README.md` and the `PROTOCOL.md` of the experiment you work on.
5. `docs/RUNNER_DESIGN.md` when you touch a design (what the runner guarantees and what a design writes).

## How work is done

- Account and folders: you run as `so_agent` in your own clone. You can write only in that clone and in
  `store04_experiments/queue/pending/` (new jobs). Runs, the trial log and the run index are written by the runner
  account `so_runner`, never by you. You cannot read the quarantine or the holdout results. An "access denied" is a
  boundary: stop that action and report it; never work around it.
- Branch: work on `agent/<topic>`; never commit to `main`, never force-push, never rewrite history. Nicolas merges.
- Protected files (`protected_paths.txt`): the guards, the runner, the rules, the records, the guard tests, the
  environment, the design documents (`docs/AGENTIC_DESIGN.md`, `docs/RUNNER_DESIGN.md`) and the pipeline notebooks. Do not change them. If one must change, write the proposal (what, why, the test) for Nicolas instead.
  `docs/RESULTS_LOG.md` only grows, and only from the run index (`scripts/append_results_log.py`); never write a row.
- Python: `venv-main\Scripts\python.exe` of Nicolas's workspace. Never install, upgrade or remove a package.
- Tests: `tests\run_all_tests.py --fast` after every code change; the full suite before you ask for a merge. Never
  commit failing tests. New tests go in a new `tests/test_*.py` added to `tests/run_all_tests.py` (synthetic data only).
- Design code runs behind a guard (`so/runner/guard.py`): it may not open, list or write anything under the data
  root, start a subprocess, or change any `so.*` module or `so.config` value (also at import). Read data through the
  view only; keep experiment constants in the experiment's `config.py`.
- Runs: commit and push your branch first, then `scripts\run_queue.py add experiments\<exp> --note "<why>"` (it
  records the commit; uncommitted code in `so/` or the experiment folder is refused). The runner runs it at that
  commit and writes the report, the manifest and a `run_index.csv` row. Read results from those files
  (`scripts\run_queue.py status`, `store04_experiments/runs/<run id>/report.md`), never from memory. A failed job
  emails Nicolas; `scripts\run_queue.py retry <job id>` resumes it under the same run id.
- A new experiment: copy `experiments/_template/`, write `PROTOCOL.md` (question, rules, the complete candidate list,
  selection rule, stopping rule, trial budget) and commit it with `config.py`, `design.py` and tests before the first
  run (message `preregister expNN`). Any change after a run is a new protocol version. The runner enforces this
  (`so/runner/preregistration.py`) and counts every design you try against the multiple-testing bar.
- Writing: separate implemented / tested / observed / intended / inferred. Quote numbers with their file. Report the
  prior-only result, the baselines and the look-ahead status; never present a result as stronger than the evidence.

## Decisions that are Nicolas's

Holdout evaluation, new data sources, protected-file changes, package changes, and any claim that a design beats
buy-and-hold. Write the decision needed, the options and your recommendation, then continue with work you may do.
