# Stock Overflow: roadmap of the agentic system

*The living plan for `docs/AGENTIC_DESIGN.md` (revised 2026-10-28). Anyone continuing the work starts here: find the
first step that is not done, read its "done when", and continue. Update the status in the same pull request that
finishes a step. Status: `[x]` done, `[~]` in progress, `[ ]` not started. Labels as in the design: decided /
proposed / open.*

**Rule for every step** (design 10.1): whenever a run uses real market data, every "protect the results" restriction
is on. A result produced without one is discarded and rerun.

---

## Done before 2026-10-28

- [x] **A0** cleanup (PR #9).
- [x] **A1** judge identity: judge hash in every report, manifest and run-index row (PR #8).
- [x] **A2 / A2b** queue hardening: judge outside `experiments/` from main, validated jobs, claim and resume,
  heartbeat, secrets stripped, run commits kept, Windows fix (PRs #10, #11).
- [x] Audit of the design and of A1-A2b (`claude/AUDIT_2026-10-28_agentic_design.md`, claude.ai project).
- [x] Decisions on the audit (design revision 2026-10-28).
- [x] exp02's removed `import pandas as pd` line restored (`b39bd9b`); its folder fingerprint again equals the one it
  last ran with (`02cbcfe3…`).
- [x] Stage-1 research plan: idea list, family budget ledger, data to collect (`docs/STAGE1_RESEARCH_PLAN.md`,
  2026-10-29). Nicolas edits it before R5.

---

## R1. Apply A3 (notifier and kill switch) and this design revision

- [x] Merge the package (A3 code, tests, documents, this roadmap); `tests\run_all_tests.py --fast` passes (PR #12).
- [x] Create `D:\stock_overflow\data\control` with an ACL where only Nicolas may write (every other account reads).
  Add this to `setup_so_runner.ps1` / `setup_so_agent.ps1` when they are next updated (R7).
- [x] Deploy (`deploy_runner.ps1` as so_runner): runner clone at `cc094bd`.
- [x] `run_queue.py test-email` as so_runner: the email arrived (2026-10-28 17:21; first end-to-end check).
- [x] Create `control\STOP`: `run_queue.py status` shows `"stopped": true`; remove it: `false`.

**Done when** the test email arrived and the STOP file stops and releases the queue. **Done 2026-10-28** (the ACL
was checked: so_agent's write was refused).

## R1b. Pre-check for phase C (read-only, on nicodesktop)

- [x] For each of the nine experiments: the protocol versions and design-folder hashes in `trial_log.csv` against the
  current folder hash. Expected: every one matches a logged 1.0 hash (exp02 matches since `b39bd9b`).
- [x] exp13: do **not** edit its PROTOCOL.md (decided); its origin goes into a results-log note row (from the git
  history; `docs/STAGE1_RESEARCH_PLAN.md` section 7).

**Done when** all nine are confirmed as 1.0 reruns, or a mismatch is reported to Nicolas. **Done 2026-10-28**: all nine
"OK rerun" (Windows hashes; they differ from Linux checkouts because of line endings, as expected).

## C. Rerun the nine existing experiments (first valid baseline)

- [x] Copy `trial_log.csv` aside (`D:\stock_overflow\backup_records\before_phaseC_20261028_173636`; `run_index.csv`
  did not exist yet).
- [x] Queue the eight daily experiments; then exp01 (exp13 re-queued last with a corrected note).
- [x] Read each email and the exp02 report; add the results-log rows and the exp13 origin note.

**Done when** nine runs are in the run index under the current judge hash. **Done 2026-10-29**: judge hash
`ad4a601ec218bc09`, every return identical to the withdrawn rows of 2026-10-23..25; all nine fail the verdict
(exp13 beats buy-and-hold on return, +273.85% vs +199.04%, but fails consistency and multiple testing; it is an
after-the-fact selection). Timing: the eight daily runs took about 3 hours (exp02 54 minutes), exp01 about 11.5 hours.

**Next full rerun:** after R2, R3, R4 and R4b, all nine (exp01 included, since R4b changes every return): about
3 hours plus 11-14 hours. **Done 2026-11-09/10** as the judge v1 baseline (see the judge v1 freeze below): the eight
daily runs took about 3 hours 45 minutes (exp02 55 minutes), exp01 about 11.5 hours.

## R2. The referee is the deployed commit (decided)

- [x] `deploy_runner.ps1` records the deployed commit: ref `refs/deployed` in the runner clone, with a reflog entry
  (time and account).
- [x] `run_queue.py` takes the judge commit from that ref, not from `origin/main`; `status` shows `deployed_commit`;
  without a deployed commit new jobs wait in `pending/`.
- [x] Found while building it: the queue validated a pending job's commit before any fetch, so a commit pushed from
  another clone was rejected as missing on the first pass. Each pass now fetches origin first.
- [x] Tests (a merge to `main` without a deploy changes no judge; no deployed judge: jobs wait; fetch before
  validation); `docs/RUNNER_DESIGN.md`, `AGENTS.md`, design 4.2 updated.
- [x] On nicodesktop: merge, deploy, `status` shows `deployed_commit` equal to `queue_commit` (2026-10-29: both
  `ce4062d`; the first deploy ran the old script, a second deploy set the ref).

**Done when** a merge to `main` without a deploy changes no judge commit.

## R3. Core fixes from the audit (agreed 2026-10-29)

- [x] Judge hash includes `records/legacy/*.csv` and the package lock; the queue hashes the fresh worktree before the
  run process starts and after it ends, and fails a run whose judge changed or whose report shows another hash
  (audit S9).
- [x] Helper hash of the unprotected `so/` files a design imports, recorded in trial rows; a logged version reruns
  only with its own helper hash (audit S2). Decided when built: bookkeeping, not part of the design key (design 4.3).
- [ ] ~~Trial rows and manifests record the model(s) that designed the experiment~~ moved to R5 (decided 2026-10-29:
  every experiment so far was written by Nicolas and Claude).
- [x] Queue on Windows: `os.replace` retried for about 5 seconds on `PermissionError`; a failed watch loop is logged
  and retried (audit S8).
- [x] `scripts/check_random_timing_tail.py` built: reproduces a run's 100 registered random-timing draws, extends them to
  10,000, compares the tail with the normal fit (audit S4).
- [x] On nicodesktop: merged and deployed (2026-11-02, judge `4a43f0e`).
- [x] Fix (2026-11-02): the tail check read `strategy_daily_equity.csv`, which development runs never write (only holdout
  runs do; the audit of 2026-10-28 had said otherwise, corrected in design 6.4). It now rebuilds the prior-only path from
  the run folder (periods, decisions, scores) with the referee's own selection and engine, and checks its return
  against the report. Works for the fractional engine (exp05) too.
- [x] exp04, 10,000 draws (2026-11-02): skewness 0.84, excess kurtosis 1.36; **35 draws above the normal-fit critical
  value where 1.9 were expected**. The normal approximation is too lenient (about 18 times at alpha / N) for this path.
- [x] Fix: the rebuilt return is compared with a 1e-7 tolerance (the engine rounds total_return to 8 decimals; exp02
  differed by 3.5e-9 and was refused). The script also reports the same test on log(1 + return).
- [x] Rerun with the log-scale section (2026-11-02): 6 (exp04) and 5 (exp02) above the critical value, 1.9 expected;
  the log scale removes most of the excess but still lets about 3 times too many through.
- [x] Decided by Nicolas (2026-11-02): the random-timing part of the multiple-testing test counts draws instead of
  fitting a curve: p = (k + 1) / (M + 1); budget M + 1 = ceil(2 N / alpha) (10,400 at N = 260); extra draws in batches
  with early stop as soon as too many draws are at or above the path (`so.runner.baselines.get_random_timing_tail_dict`,
  `so.core.multiple_testing`; tests prove the extra draws equal the one-by-one draws, the stop point, the worker count
  independence and the strict fallbacks). The 95%-of-100-draws baseline part is unchanged. No past verdict changes:
  all nine experiments fail other parts.
- [x] On nicodesktop: merge and deploy (the judge changes): PR #18, `134f716`, deployed as the referee (stated in the
  R4 handoff of 2026-11-03).
- [ ] Moved into the judge v1 freeze (below; decided 2026-11-03): a counted check of the deflated Sharpe ratio, which also rests on a normal-type
  approximation (it corrects for skew and kurtosis, so it is less exposed). Keep the normal approximation only if it is fair or conservative; otherwise a core change follows.

**Done when** the tail check has been read and its consequence decided. **Decided 2026-11-02**; done once deployed.

## R4. Results visible only as grades (decided; before any agent works with real data)

Built 2026-11-03 (branch `core/r4-grades-only`); decisions of Nicolas on 2026-11-03 in design 6.4, 6.5, 6.7 and 4.4.

- [x] Run folders, trial log, run index, queue records, logs, checks and market data readable only by so_runner and
  Nicolas: `scripts/setup_so_agent.ps1` removes so_agent's read of the whole data root and grants only
  `queue\pending`, `visible\` (two reader groups: `so_grade_readers`, `so_status_readers`; so_agent in both for stage
  1) and `control`; it saves the ACLs first and reads them back. The folders next to the data root (`archive`,
  `backup_records`, `move_logs`, `runner_workspace`) were checked on 2026-11-03: closed to so_agent already.
- [x] The runner writes a **graded summary** per run (`visible/grades/<run_id>.json`: grade, reason, audit state,
  identifiers; no numbers) and a **technical status** per job (`visible/status/<job_id>.json`: ran / crashed / timeout
  / rejected, look-ahead status, scrubbed error, retry fields). `state.json` moved into `visible/`, trimmed to
  identifiers; the old one is removed. `retry` reads the status file. The console prints no results row.
- [x] Grade mapping (design 6.5): technical (no verdict, look-ahead) -> not better than buy-and-hold (fails even at
  zero slippage) -> gain disappears after costs -> inconsistent -> could be luck (baselines, multiple testing) -> pass
  (audit pending). The cost-sensitivity rows re-apply the full return check. Rejected jobs: status only.
- [x] `scripts/append_results_log.py` writes grades and identifiers only once the switch `records/agent_phase.txt` says
  `agents` (a protected record, not hashed into the judge); it says `development` until R6.
- [x] Pilot scope (design 6.7): the verdict's N is the trial log; the pre-reset records slimmed into the tried-designs
  ledger `records/legacy/pilot_designs.csv` (family and settings only, 260 designs, same keys; their numbers removed
  from `main`); every report shows the pilot-included view; `scripts/reset_records.py` for development resets.
  **Superseded 2026-11-10:** the verdict's N is the pilot-included count (judge v1 freeze section).
- [x] Tests: `tests/test_grades.py` (every combination of verdict parts, vocabulary without digits, scrubber, trimmed
  state, grade and status files end to end on an allow-list, retry from the status, the switch both ways, the reset);
  additions to `tests/test_runner_protocol.py`, `tests/test_runner_verdict.py`, `tests/test_tools.py`.
- [x] On nicodesktop (2026-11-04): merged (PR #19, then #20 with a deploy-script fix), deployed as so_runner (runner
  clone and `refs/deployed` at `6d71c1c`; `visible\state.json` written, the old zone-root `state.json` gone),
  `setup_so_agent.ps1` run as administrator, `check_agent_access.py` passed as so_agent (53 checks, every denial on
  real files: a report, a manifest, the run index, the trial log, a finished job, a run log, one file per market-data
  zone, the view files) and as so_runner (37 checks). A job so_agent queued with a design outside `experiments/` was
  rejected; so_agent read its status (reason, no digits) and `state.json`, and was refused `queue\rejected`.
- Fixes found while applying it (all merged 2026-11-04): `deploy_runner.ps1` read the running job from the old
  `state.json` (PR #20); a local group description may hold at most 48 characters (PR #21); a plain `(OI)` grant on
  `visible\` reached the files inside `grades\` and `status\`, now `(OI)(NP)` (PR #22, caught by the script's
  read-back); **a deny of icacls `W` holds SYNCHRONIZE and READ_CONTROL**, so so_agent could not open any file in
  Nicolas's workspace or start Python there; this was already true of the earlier script, whose access check only
  listed folders. Denies now name the write rights one by one (PR #23).
- [x] The scrubber on a real crash: `queue\failed` and `queue\rejected` were empty on 2026-11-04, so it has only been
  tested on synthetic tracebacks; read the first real crash's status file. **Real crashes exist now (2026-11-09):** the
  nine status files of the first baseline attempt (a `ValueError` from the pre-registration guard) are in
  `D:\stock_overflow\backup_records\reset_20261109_221644\visible\status`; one still has to be read.
  **Done 2026-11-10** on exp02's status from the first attempt: error type, message and four code locations kept;
  source lines and values dropped. The message carries the runner's absolute worktree path (machine layout, no data);
  left as is.
- [x] The first real grade file read by so_agent (comes with the freeze rerun). **Grade files exist now
  (2026-11-10).** Before the check: the first reset of 2026-11-09 moved `visible\grades` and `visible\status`
  themselves, and the runner recreated them with inherited permissions only, so the `so_grade_readers` and
  `so_status_readers` grants are probably gone; rerun `scripts/setup_so_agent.ps1` once (resets keep the folders since
  PR #34), then read a grade as so_agent.
  **Done 2026-11-10:** `setup_so_agent.ps1` rerun as administrator (every read-back passed, the reader grants on
  `visible\grades` and `visible\status` restored); so_agent read a real grade file (grade, reason code and reason, no
  digit in any); `check_agent_access.py` passed as so_agent (52 checks) and so_runner (36). On 2026-11-04 the counts
  were 53 and 37, probably one sample kind missing this time (a rejected job: `queue\rejected` empty after the
  resets), not confirmed.

**Done when** an agent account can read the grade of a run and nothing else about it.

## Judge v1 freeze (decided 2026-11-03; design 4.4)

- [x] R4 (judge hash changes; no number changes).
- [x] Pilot ledger and pilot scope (judge hash changes; the verdict's N falls from 260 to the trial log's count).
- [x] R4b total returns (every number changes; PR #31, 2026-11-09).
- [x] Counted check of the deflated Sharpe ratio: a diagnostic script first (like `check_random_timing_tail.py`, on
  exp04 and exp02); a core change only if the approximation lets too many designs through; or dropped with a reason.
  **The diagnostic is built (2026-11-09):** `scripts/check_deflated_sharpe_tail.py <run id> --draws 10000` rebuilds the
  run and its registered draws on the report's return basis, recomputes its DSR, and counts no-skill random-timing
  draws (raw and centered per quarter) whose DSR is at least 0.95, against draws x alpha / N.
  **Done 2026-11-09:** on exp04 and exp02 (price-only reports, 10,000 draws) every centered count is at most
  0.24 times the expected count at N = 30, 100 and 260: the approximation is conservative here. Kept as is, no
  core change; the cost is lower power.
  **Confirmed on total returns (2026-11-10)** on the judge v1 baseline runs of exp04 and exp02 (10,000 draws): every
  centered count is below the 3x rule, at most 1.20 times expected (exp02 at N = 100; 1.04 at N = 260; exp04 at most
  0.59). Kept; but on total returns the DSR is about fair, no longer conservative (small counts: 6 against 5
  expected, 2 against 1.9). Reports in `store04_experiments\checks`.
- [x] Reset the development records (`scripts/reset_records.py --confirm`, task stopped), then the full rerun of the
  nine: the baseline. **Done 2026-11-09/10**, judge hash `3b51ca4a3578852a`, judge commit `1b6bd11`; all nine fail
  the verdict (`docs/STAGE1_RESEARCH_PLAN.md` section 2; results-log rows PR #36). What it took:
  - first reset (PR #33) and rerun: all nine crashed in the pre-registration guard, because the reset had moved the
    trial log the guard reads to tell a rerun of a logged version from a new one;
  - fix (PR #34): `records/legacy/registered_versions.csv` (experiment, version, folder hash, helper hash; no
    results), seeded from the moved log; the guard reads it with the trial log, `reset_records.py` fills it before
    each reset and keeps the grade and status folders; a Windows-only order flake in `tests/test_grades.py` fixed;
  - second reset (PR #35) and rerun: nine runs, no crash. The second reset ran with the scheduled task still running
    (`Stop-ScheduledTask` was refused in a non-elevated window and the block's check failed open); no harm (the
    runner was idle with nothing pending, the dry run and the reset moved the same items), but see the next item.
  Baseline run ids for the equivalence check: exp02 `exp02_stop_reentry_20261109221716650764`, exp04
  `exp04_trend_exit_20261109234625241939`.
- [x] **Decided 2026-11-10 (Nicolas):** `reset_records.py` refuses unless the kill switch `control\STOP` is
  confirmed to exist (missing or unreadable refuses; so does `SO_STOP_FLAG_PATH` set in the window), as well as with the
  runner lock or pending jobs; a refused command prints the plan, then the reason, and exits 1. Blocks that stop the
  task also check that the window is elevated and fail closed when the task cannot be read. Limit: with STOP set, the
  runner's idle loop still rewrites `visible\state.json` and recreates empty queue folders about every 60 s (no lock),
  so resets also stop the task. **Done:** PR #38; first used for the reset of 2026-11-10 (PR #39): without STOP the
  dry run refused (exit 1), with STOP it ran (30 items moved, N 260 before and after).
- [x] **Decided 2026-11-10 (Nicolas): the verdict judges at the pilot-included N** (trial log and ledger, 260 at the
  baseline), revisiting the 2026-11-03 rule after the baseline, in the stricter direction, with no verdict depending on
  it (all nine fail at both counts). Why: the pilot designs were tried on the same data and shaped later choices
  (exp13), and a trial-log N restarted after every reset (exp02 was judged at N = 18, exp04 at 42). Reports keep the
  trial log's count as information; the pilot-included side verdict is gone (one N), and so is the runner's second
  draw budget. The random-timing budget was already sized for the pilot N, so runs take no longer. Known limits: N
  still grows as designs are logged; it counts close variants separately (overstates independent tries; a
  correlation-based effective N only if a promising design later fails narrowly on multiple testing); the spread V
  stays from the trial log only (the ledger holds no numbers). Both changes in one PR (a scoring change), then: reset
  (kill switch set, task stopped), one deploy, and a **full rerun of the nine**, which becomes the baseline.
  **Done 2026-11-11:** PR #38 (code) and #39 (reset: 0 ledger rows, 9 registered-version rows, the baseline's first
  helper hashes), deployed at `c0924b9`, judge hash `b7ec40bc1d31be1f`. All nine fail the verdict, at N = 260; every
  total return is identical to the 2026-11-09/10 baseline (`docs/STAGE1_RESEARCH_PLAN.md` section 2). The trial log's
  own count followed the baseline's queue order (18, 33, 42, 46, 58, 61, 67, 68, 80).
  **First real equivalence check** (`scripts/check_equivalence.py`, baseline = the backup copy's full path, since the
  reset moved the old runs): exp02 and exp04 EQUIVALENT, every scoring number and candidate file identical;
  differences only in the multiple-testing part (N 18 -> 260 and 42 -> 260). The spread V was identical for exp02 and
  differed only in the last digit for exp04 (0.00958141648339678 vs ...782, floating-point rounding), so the reset did
  reproduce V. New baseline run ids for the equivalence check: exp02 `exp02_stop_reentry_20261111000527008138`, exp04
  `exp04_trend_exit_20261111013503898732`.
- [x] **Decided 2026-11-11 (Nicolas):** Windows 11 Home pause, renewed by hand (Pick a date, at most 35 days), plus a
  guard in `scripts/run_queue.py` (R4c PR) so no job starts or resumes with less than 3 days of pause left or a restart
  pending; updates installed by hand with STOP set when the queue is empty; active hours as a minor layer; the resume
  limit stays the last net. nicodesktop is on 26H2 (build 26300); the 02:17 restart was TrustedInstaller's version
  upgrade. Original note: **Windows Update restarted nicodesktop twice during the rerun**
  (02:14 and 02:17, "Service pack" and "Upgrade", both planned by the system). exp06 was interrupted twice and resumed
  the same run (attempt 3, the last one before `MAX_RESUME_COUNT_INT` = 2 gives up); its result equals the baseline,
  so the resume worked. A longer run (exp01, about 11.5 h) or a third restart would have failed. Options: Windows
  Update set to download and notify (install by hand when the queue is empty), or paused during long queues.
- [x] `scripts/check_equivalence.py` takes run ids under the live `runs` folder only; after a reset the baseline is in
  `backup_records\reset_<time>\runs\`. A full path works (os.path.join keeps it); say so in its help text. **Done in the R4c PR (2026-11-11).**
- [ ] Open (2026-11-10, not changed): **the trial-Sharpe spread V also follows queue order, and a rerun of an
  unchanged design appends its validation quarters again**, so they count twice in that design's Sharpe ratio. A reset
  before the rerun above avoids it; from R6 (no resets) it needs a fix (count each design and quarter once). The
  equivalence check files any V difference under "explained by N" (it treats the whole multiple-testing part as
  N-dependent); worth narrowing with that fix.
- [ ] From then on: a judge-hash change that touches no scoring code is accepted by an equivalence check (one or two
  fast daily experiments reproduce every number exactly); a scoring change means a full rerun. **The check is built
  (2026-11-05)**: `scripts/check_equivalence.py --baseline <run id> --new <run id>` (Nicolas or so_runner; it prints
  numbers) compares every report value except identities (run ids, commits, hashes, judge, paths, time stamps, trial
  ids, timings) and every candidate's `decisions.pkl` and `scores.pkl`, exactly; differences only in the
  multiple-testing view are reported as explained by N when the count of designs changed. Exit 0 equivalent, 1 not.
- [x] Decided 2026-11-05: **the judge hash stays broad** (every protected `.py` under `so/` and `scripts/`, plus the
  pilot ledger). Narrowing it to scoring code would need a judgement, file by file, of what can change a score; a
  mistake there would let a scoring change through unseen. The equivalence check makes the broad hash cheap instead.
- [~] **R4c, intraday decision times (decided by Nicolas on 2026-11-11):** a daily fractional design may also decide
  at declared times during the session (fill at the next bar's open), for the stage-1 intraday ideas (I1, I2), which
  the runner could not express. Records, replay, pattern-based random timing, bar-weighted constant exposure and
  intraday look-ahead cuts (`docs/RUNNER_DESIGN.md`, "Intraday decision times"). Designs without intraday times take
  the old code path. Same PR: the Windows Update guard in `scripts/run_queue.py` (add refuses and the runner waits
  while the pause ends within 3 days, a restart is pending, or either cannot be read) and the `check_equivalence.py`
  help text. **Done when** the suite passes on nicodesktop, the PR is merged and deployed, and equivalence checks on
  exp02, exp04 and exp05 are EQUIVALENT. Then the audit of both repositories, before the hand-designed experiments.
- [~] **R4d, a frozen V and small fixes (decided by Nicolas on 2026-11-12, before any research run):** the
  equivalence checks on exp02/04/05 after R4c were NOT EQUIVALENT only through V (the live variance followed queue
  order and counted reruns twice); rule (a) had not listed V's inputs, and was not amended. Fix: V from each design's
  latest run, and a frozen reference file built by Nicolas (`scripts/freeze_v_reference.py`, protected) that the
  verdict reads on the real view and refuses without (`docs/RUNNER_DESIGN.md`, "The frozen V"). Same PR: the idle loop
  writes nothing under STOP; `check_equivalence.py` reports V inputs and the values that follow from them separately;
  `tests/run_all_tests.py --suite NAME`; the template shows `INTRADAY_DECISION_TIME_LIST`; done/ran documented.
  **Done when** the suite passes on nicodesktop, the PR is merged and deployed, the reference is frozen under STOP,
  the records are reset and all nine experiments are rerun in baseline order (the final baseline), compared under a
  rule Nicolas states before the rerun.
- [ ] Then, before any agent (decided 2026-11-04): **a few hand-designed experiments** from the stage-1 idea list,
  pre-registered and queued by Nicolas and Claude under the same rules, counted in N and in the family budgets. They
  check in practice that the queue, the grades, the technical status and the reports work before agents rely on them;
  then the agents carry on the work.

## R4b. Total returns: dividends and T-bill interest (decided 2026-10-29; before any agent runs)

- [x] Nicolas supplies SPY dividends (ex-date, pay date, amount) and the daily 3-month T-bill rate from 2005
  (`docs/STAGE1_RESEARCH_PLAN.md` 5.1); both registered in `docs/DATA_SOURCES.md` with their availability clocks.
  Done 2026-11-09: ingested by `stock_overflow_infra` (State Street, cross-checked against Yahoo; FRED/ALFRED DTB3 with
  vintages) and registered as `SPY_DIVIDENDS` and `TBILL_3M` (PR #30).
- [x] Engine and baselines: dividends credited to shares held at the previous close, at the ex-date open; cash earns
  the T-bill rate (first release, 91-day investment yield); buy-and-hold reinvests at the ex-date fill; buy-and-hold,
  constant-exposure and random-timing baselines on the same basis; the report states the basis (PR #31, 2026-11-09).
- [x] Tests on synthetic data (`tests/test_total_return.py`, a minute-mode replay test); `docs/RUNNER_DESIGN.md`
  updated. Sanity check on the development view, 2005-2024: buy-and-hold 8.19% a year price only, 10.24% total return;
  all cash 1.64% a year.
- [x] Then the full rerun of the nine (see C), after the counted check of the deflated Sharpe ratio (judge v1 freeze).
  **Done 2026-11-09/10** (judge v1 baseline).

**Done when** every verdict compares total returns on both sides.

## R5. Stage 1 build: planner and blind coder (decided)

- [ ] **Code-running agents have no general internet** (only GitHub and package mirrors), required before R6 (a
  "protect the results" restriction, decided 2026-11-04, design 10.1): otherwise an agent could download SPY prices
  elsewhere and test designs on them privately, uncounted. Container networking or the agent tool's own tool list,
  decided with the isolation choice above.
- [ ] Plan the training-cutoff evaluation with the model choice (design 11, decided 2026-11-04): every design records
  its model and that model's training cutoff.
- [ ] A numbers-free brief for the planner (review 2026-11-04, point C): the idea list, the family ledger and the
  grades of the baseline runs; `docs/STAGE1_RESEARCH_PLAN.md`, the roadmap and the earlier results-log rows stay
  Nicolas's records.

- [ ] Trial rows and manifests record the model(s) that designed the experiment (moved from R3; design section 1).
- [ ] The planner gets its own Windows account in `so_grade_readers` only; the coder (so_agent, renamed so_code) leaves
  `so_grade_readers` (decided 2026-11-03; only memberships change).
- [ ] A data dictionary for the blind coder: the columns, types and availability clocks of every registered source,
  without values (the coder cannot read the data folder since R4).

- [ ] How agents are isolated, decided with the runtime (decided 2026-11-04): if the chosen agent tool runs in a
  container, agents run in containers with only `visible\` (read-only), `queue\pending` and their own clone mounted,
  and no network beyond GitHub and package mirrors; the Windows accounts and ACLs of R4 stay underneath as a second
  layer. An editor-based tool on the Windows desktop keeps the Windows accounts. Containers stay the first choice for
  the R7 network limits and the design-code sandbox. The agent's Python then needs a Linux copy of the package lock.
- [ ] Choose the agent runtime and model (requirements in design section 12; options and a bake-off in
  `claude/PROPOSAL_2026-10-29_models_and_setups.md`); provider-side monthly spend limit of **USD 25** on the system's
  own key (decided 2026-10-28; revised when the workload is known).
- [~] Idea list: drafted with sources, family ledger and data needs (`docs/STAGE1_RESEARCH_PLAN.md`, 2026-10-29);
  Nicolas edits it; existing experiments count against their family (decided 2026-10-29).
- [ ] File formats: idea entry, plan file, job, technical status, graded summary (design section 12).
- [ ] Planner prompt and rules: most promising first; budget 5 variants per idea, 3 ideas per family; grades only;
  checks STOP before each step.
- [ ] Coder prompt and rules: follow the plan exactly; tests; pull request on `agent/**`; technical status only;
  checks STOP before each step.
- [ ] `AGENTS.md` updated for the two roles.

- [ ] Revisit the size of `scripts/run_queue.py` (about 2,000 lines; decided 2026-11-05 not to split it now: a split
  changes the judge hash and moves code the tests and the setup checks rely on, for no change in behaviour). Split it
  when R5 adds the container or account runner, if that work makes the file harder to review.

## R6. Stage 1 supervised cycles

- [ ] Nicolas reviews and approves every pull request before its job is queued (this replaces the sandbox in stage 1).
- [ ] Nicolas reads every result email and acts as auditor (veto only); a veto is recorded against the graded pass (a
  field or file the planner reads; format to define).
- [ ] Flip `records/agent_phase.txt` to `agents` by a one-line merge just before the first supervised cycle (results
  log in grades only; no more resets). From then on no number of an agent-era run goes into the repository.
- [ ] A pass is frozen (commit + tag), a forward protocol is written for it (design 11), and paper trading starts;
  the rest keeps running. Its duration is set per strategy (about 2-3 months intended): a mechanical and behavioural
  check, not proof of an edge (decided 2026-11-04).

**Done when** several cycles ran with no integrity problem.

## R7. Before stage 2 (unattended); all required

- [ ] **A4 sandbox under so_design** (design 3.2): no network, no data root, no records, no secrets; rows fed point in
  time by the runner; decisions back. Also closes a channel R4 leaves: design code running as so_runner could copy
  numbers into `visible\` (R4, 2026-11-03).
- [ ] Accounts: so_agent renamed so_code; so_web created (no code execution); per-account firewall rules for the
  target roles (the no-internet rule for code-running agents comes earlier, R5); NTFS quotas.
- [x] Setup scripts reproduce the machine. **Rewritten 2026-11-04** to the allow-list model the machine has had since
  it was rebuilt by hand on 2026-10-26 (`claude/STATE_2026-10-26.md`), checked against an inventory of nicodesktop the
  same day: root inheritance removed, no write denies anywhere (a partial deny broke Python twice: 2026-10-26 and
  2026-11-04), full denies only on the quarantine and the holdout, base Python read and run, clone ownership, the
  `control` folder's own list, the batch-logon right; the runner script re-registers the task only with
  `-RegisterTask` and asks for SMTP settings only when given; both scripts read everything back. **Run on nicodesktop
  2026-11-05**: every read-back passed, the agent access check (53 checks) and the runner check (37 checks) passed.
- [x] The queue's own output is written to a log file (decided 2026-11-04; **changed 2026-11-05**: `run_queue.py watch`
  writes its own log, `queue\logs\runner_watch.log`, every line time-stamped, rotated to `.1` past 5 MB, so the
  scheduled task is not changed or re-registered). The agent cannot read `queue\logs\` (the access check samples
  `*.log`).
- [~] Windows CI for the setup scripts (decided 2026-11-05, its own package; **built 2026-11-08**): CI job
  `windows-setup` (`.github/ci/windows_setup_check.ps1`) creates throwaway so_runner and so_agent accounts and a fake
  tree on `windows-latest`, runs each setup script twice (create, then after the first logon, so a rerun is checked
  too), starts the queue task once (state.json and the watch log must appear), and runs the access check as both
  accounts through scheduled tasks; job `windows-tests` runs the fast suite on Windows. The setup scripts gained
  `-AccountPassword` (CI only) and the agent script `-Owner`. The access-check sample list now goes in
  `<data root>\control\access_samples.txt`, outside every clone (it was left in the agent's clone until 2026-11-08), and
  is ignored by git. Still to do: both jobs green on `main`.
- [ ] GitHub machine account and rulesets re-enabled (design 10.3).
- [ ] NAS backups of trial log, run index, manifests, summaries.
- [ ] Base Python moved out of Nicolas's profile.

## R8. Stage 2 and 3

- [ ] Stage 2: unattended with low budgets. Stage 3: budgets raised. Each only after the previous ran cleanly.

## R9. Towards the target system (when needed)

- [ ] Research agents (≤3, web read/search only, no shell) and research orchestrator; idea list becomes the strategy
  registry.
- [ ] Auditor agent (veto only, sees everything).
- [ ] Codifier orchestrator and code reviewer split from the coder.
- [ ] Screening as a flag of the full run (proposed) and daily digest.
- [ ] Source registration with availability clocks and truncation test; then the data agent (postponed).
- [ ] Lessons and failure log.

## Small items carried over

- [ ] Inspect `D:\stock_overflow\archive` (keep, merge into quarantine, or delete).
- [ ] About 10 in-window minute rows in public git history (`7c024ba`).
- [ ] The preflight walks only `experiments/` imports (closed by R7's sandbox).
- [ ] `test_execute_notebook.py` needs the `venv-main` kernel registered where it runs.
