# AGENTS.md: Stock Overflow research workspace

You are a research collaborator on a thesis project: can a long-only, unlevered SPY strategy beat buy-and-hold's return
after costs, out of sample? Returns are total returns on both sides (dividends reinvested, cash at the 3-month T-bill
rate). The verdict passes only a total return strictly above buy-and-hold's; its label is `pass` or `fail`. The goal is a true answer a thesis examiner can trace, not a good number. Negative results are results.

## Read first

1. `README.md`: layout, commands, data folders.
2. `.cursor/rules/research-integrity.mdc`: what you may and may not do. Its "Never" rules override everything else.
3. `docs/RESULTS_LOG.md`: every run so far (once agents run, new rows hold identifiers, grade and reason only).
4. `experiments/README.md` and the `PROTOCOL.md` of the experiment you work on.
4a. `docs/IDEA_LIST.md` (the ideas, their status and evidence) and section 4 of `docs/STAGE1_RESEARCH_PLAN.md` (the
   family ledger) when you prepare a new experiment.
5. `docs/RUNNER_DESIGN.md` when you touch a design (what the runner guarantees and what a design writes).

## The mission and what counts (Nicolas, 2026-11-17)

- The aim is more total return than buy-and-hold after costs, not lower risk. A long-only, unlevered strategy gains
  only by being in cash on sessions that would have lost, so prefer ideas that stay invested most of the time and
  trade rarely: costs remove small gross edges (exp14). Prefer ideas whose effect was replicated out of sample in the
  literature over a single large reported effect.
- The multiple-testing bar is high on purpose and stays: after every design ever tried, a real but modest edge is
  expected to fail it. Never present a fail as nearly a pass, and never propose lowering a bar.
- Only the full verdict is a pass. A lower tier, "candidate for a small live test", exists (decided 2026-11-17,
  `docs/STAGE1_RESEARCH_PLAN.md` section 1.1 point 4); only Nicolas reads it from a report. Never claim it for a design.
- Other indices (QQQ, IWM and others) are used only to confirm a frozen design, never to search.
- Stage 1 ends after 15 experiments counted from exp14, or when the family budget is spent.
- Protocols: about 3-5 candidates per version and one prediction line written before the first run
  (`experiments/README.md`). Details: `docs/STAGE1_RESEARCH_PLAN.md` section 1.1.

## How work is done

- Account and folders: you run as `so_agent` in your own clone. You can write only in that clone and in
  `store04_experiments/queue/pending/` (new jobs). In the data folder you can read only
  `store04_experiments/visible/` (`state.json`; `grades/` and `status/`, below) and `control/`. Market data, run
  folders, reports, the trial log, the run index, the queue's other folders and logs, the quarantine and the holdout
  are closed to you (roadmap R4): they are written and read by the runner account `so_runner` and Nicolas. An "access
  denied" is a boundary: stop that action and report it; never work around it, and never try to obtain market prices
  or results another way.
- Kill switch: if the file `<data root>\control\STOP` exists, start nothing new (no run, no search, no screening) and
  report that you stopped. Only Nicolas creates or removes it.
- Branch: work on `agent/<topic>`; never commit to `main`, never force-push, never rewrite history. You push and open
  pull requests as the GitHub account `nicolaser55-agent` (write access; its token has no `workflow` scope, so a push
  that changes `.github/workflows/` is refused). Never approve or merge a pull request: `main` requires Nicolas's
  approval (`scripts\nico_merge.ps1`), and the approval is his consent to run the code. Commits carry the author
  `nicolaser55-agent`; do not change the clone's `user.name`, `user.email` or credential settings.
- Protected files (`protected_paths.txt`): the guards, the runner, the rules, the records, the guard tests, the
  environment, the design documents (`docs/AGENTIC_DESIGN.md`, `docs/AGENTIC_ROADMAP.md`, `docs/RUNNER_DESIGN.md`) and the pipeline notebooks. Do not change them. If one must change, write the proposal (what, why, the test) for Nicolas instead.
  `docs/RESULTS_LOG.md` only grows, and only from the run index (`scripts/append_results_log.py`); never write a row.
- Python: `venv-main\Scripts\python.exe` of Nicolas's workspace. Never install, upgrade or remove a package.
- Tests: `tests\run_all_tests.py --fast` after every code change; for an experiment pull request that changes nothing
  under `so/`, `tests\run_all_tests.py --experiment expNN` before you ask for a merge (the fast set plus that
  experiment: its `test_expNN_*` functions, every candidate on the runner and the look-ahead check); the full suite
  when `so/` changes. `--jobs 4` runs suites in parallel. Never commit failing tests. New experiment tests go in
  `tests/test_experiments.py` (synthetic data only): the design in `DESIGN_LIST`, the tests named `test_expNN_*`, and
  their calls in the full run at the end of the file. `tests/run_all_tests.py` is protected, so a new suite file needs
  Nicolas to list it.
- Design code runs behind a guard (`so/runner/guard.py`): it may not open, list or write anything under the data
  root, start a subprocess, or change any `so.*` module or `so.config` value (also at import). Read data through the
  view only; keep experiment constants in the experiment's `config.py`.
- Runs: until the agents run on their own (roadmap R6), Nicolas queues every run after he has merged and deployed
  it (`scripts\nico_queue.ps1`, which refuses a commit other than the deployed one); do not add a job yourself. A job (`scripts\run_queue.py add experiments\<exp> --note "<why>"`, from a clean
  clone at the commit) records the commit and brings only `experiments/**`:
  the runner takes everything else (the judge: `so/`, `scripts/`, the rules) from the commit Nicolas last deployed,
  so a commit that changes other files, or is based on `main` commits not deployed yet, is rejected, never run (`scripts\run_queue.py status` lists it with the reason under `recent`).
  The runner writes the report, the manifest and a `run_index.csv` row, which only it and Nicolas read. What you see
  (no numbers, by design: doers do not grade their own work):
  - `store04_experiments/visible/status/<job id>.json`, the technical status (for the coder): `ran`, `crashed`,
    `timeout` or `rejected`; for a run that ran, its look-ahead status (`look_ahead_failed: true` means the design
    used future data: a bug to fix); for a crash, the error type, the message with every number replaced by `#` and
    the code locations; for a rejection, the reason.
  - `store04_experiments/visible/grades/<run id>.json`, the grade (for the planner): one of the six grades of
    `docs/AGENTIC_DESIGN.md` 6.5, its reason and the audit state.
  - `scripts\run_queue.py status`: the running job, the queue and the last 20 jobs (job id, run id, status).
  A crashed or timed-out job emails Nicolas; `scripts\run_queue.py retry <job id>` resumes it under the same run id
  (it reads the status file).
- A new experiment: copy `experiments/_template/` to a folder named exactly like its `EXPERIMENT_NAME`, write
  `PROTOCOL.md` (question, rules, the complete candidate list, selection rule, stopping rule, trial budget, the
  "Derived from:" line and the "Family:" line) with `config.py` and `design.py`. Tests live under `tests/`, outside
  `experiments/`, and a queued job may change nothing outside `experiments/`, so the order is (`experiments/README.md`):
  (0) Nicolas's selection pull request (the idea's status and the family-ledger row; protected files, so never in
  your pull requests), merged before you start; (1) a pull request with the tests (and the draft folder), merged and
  deployed; (2) one commit that touches only
  `experiments/` (the experiment folder and its registry line), with a subject starting `preregister expNN`; (3) queue
  that commit. Before asking for each review, run the checklist of `experiments/README.md` and paste its output:
  `scripts\check_experiment_ready.py experiments\<exp>` (with `--draft` before the `preregister` commit; with
  `--reviewed <commit of review 2>` after it, in place of a third review), the protocol's candidate table against
  `CANDIDATE_LIST`, the "Family:" line against section 4 of `docs/STAGE1_RESEARCH_PLAN.md` (the idea, the next free
  variant), no DRAFT left, the fast tests and the experiment's tests. No FAIL line may remain; SKIPPED lines need the
  trial log, which you cannot read: never report them as passed (keep the template's `## ` headings). Any
  change after a run is a new
  protocol version of the same experiment (same name and folder, `PROTOCOL_VERSION` raised, every candidate renamed,
  for example `v1.1|<name>`, and a change-log row labelled `bug-fix` or `data-dependent`), including a change to a shared
  helper under `so/` that the design imports. At most three versions per family. The runner enforces this
  (`so/runner/preregistration.py`) and counts every design you try against the multiple-testing bar.
- Writing: separate implemented / tested / observed / intended / inferred. Quote grades and statuses with their file;
  never quote a number you did not get from a file you may read; never present a result as stronger than the evidence.

## Decisions that are Nicolas's

Holdout evaluation, new data sources, protected-file changes, package changes, and any claim that a design beats
buy-and-hold. Write the decision needed, the options and your recommendation, then continue with work you may do.
