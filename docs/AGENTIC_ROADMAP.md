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
3 hours plus 11-14 hours.

## R2. The referee is the deployed commit (decided)

- [ ] `deploy_runner.ps1` records the deployed commit (for example a ref `refs/deployed` in the runner clone).
- [ ] `run_queue.py` takes the judge commit from that ref, not from `origin/main`; `status` shows it.
- [ ] Tests; `docs/RUNNER_DESIGN.md` and `AGENTS.md` updated.

**Done when** a merge to `main` without a deploy changes no judge commit.

## R3. Core fixes from the audit (proposed; confirm each when built)

- [ ] Judge hash from the run commit's git tree, computed before any design code runs; includes
  `records/legacy/*.csv` and the package lock (audit S9).
- [ ] Design fingerprint and design key include the design's non-core import closure (audit S2).
- [ ] Trial rows and manifests record the model(s) that designed the experiment (design section 1).
- [ ] Queue on Windows: retry `os.replace` briefly on `PermissionError`; catch and log per watch loop (audit S8).
- [ ] One-off check: 10,000 random-timing draws for one design against the normal approximation; keep it only if
  conservative (audit S4).

## R4. Results visible only as grades (decided; before any agent works with real data)

- [ ] Run folders, trial log and run index readable only by so_runner and Nicolas (ACLs).
- [ ] The runner writes a **graded summary** per run (grade and reason, design 6.5; identifiers; no numbers) into a
  folder the planner may read, and a **technical status** (ran / crashed + cleaned error / rejected + reason) the coder
  may read.
- [ ] Grade mapping for verdicts with several failed parts (open, decide when built).
- [ ] `scripts/append_results_log.py` writes grades and identifiers only, no returns, once agents run (decided
  2026-10-28).

**Done when** an agent account can read the grade of a run and nothing else about it.

## R4b. Total returns: dividends and T-bill interest (decided 2026-10-29; before any agent runs)

- [ ] Nicolas supplies SPY dividends (ex-date, pay date, amount) and the daily 3-month T-bill rate from 2005
  (`docs/STAGE1_RESEARCH_PLAN.md` 5.1); both registered in `docs/DATA_SOURCES.md` with their availability clocks.
- [ ] Engine and baselines: dividends credited to shares held at the ex-date open; cash earns the T-bill rate; buy-and-
  hold, constant-exposure and random-timing baselines on the same basis; the report says "total return".
- [ ] Tests on synthetic data; `docs/RUNNER_DESIGN.md` updated.
- [ ] Then the full rerun of the nine (see C).

**Done when** every verdict compares total returns on both sides.

## R5. Stage 1 build: planner and blind coder (decided)

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

## R6. Stage 1 supervised cycles

- [ ] Nicolas reviews and approves every pull request before its job is queued (this replaces the sandbox in stage 1).
- [ ] Nicolas reads every result email and acts as auditor (veto only).
- [ ] A pass is frozen (commit + tag), a forward protocol is written for it (design 11), and paper trading starts;
  the rest keeps running.

**Done when** several cycles ran with no integrity problem.

## R7. Before stage 2 (unattended); all required

- [ ] **A4 sandbox under so_design** (design 3.2): no network, no data root, no records, no secrets; rows fed point in
  time by the runner; decisions back.
- [ ] Accounts: so_agent renamed so_code; so_web created (no code execution); firewall rules; NTFS quotas.
- [ ] Setup scripts reproduce the machine (accounts, ACLs including `control` and the run folders, tasks).
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
