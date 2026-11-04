# Stock Overflow: agentic research system design

*Agreed 2026-10-27 between Nicolas and Claude; **revised 2026-10-28** after the audit
(`claude/AUDIT_2026-10-28_agentic_design.md` in the claude.ai project) and Nicolas's decisions on it. This is a
design, not a description of built software: nothing in it is built unless the roadmap
(`docs/AGENTIC_ROADMAP.md`) marks it done. Labels: **decided** (Nicolas agreed), **proposed** (recommended in the
audit, to be confirmed when built), **open** (still to decide, section 14). **Updated 2026-11-03 (roadmap R4):** grades
and technical status built (6.4, 6.5), the pilot scope of the multiple-testing count (6.7), the judge v1 freeze and
equivalence checks (4.4).*

**Two horizons.** Sections 2 to 11 describe the **target system** (the end goal, unchanged in purpose). Section 12
describes **stage 1, the small version** that is built first. Every stage-1 part is a subset of the target and talks
through the same files, so the target grows by adding roles, never by rebuilding (decided).

---

## 1. Purpose and principle

The system researches, implements and tests long-only, unlevered SPY strategies autonomously and tells Nicolas when
something survives. **The goal is a total return above buy-and-hold** (after costs, out of sample); a high ratio of
take-profit to stop-loss exits is not a goal in itself (decided by Nicolas, 2026-11-04). "Thesis" in these documents
means a standard of rigour (referenced, traceable, honest), not a publication (Nicolas, 2026-11-04). Nicolas then freezes it and evaluates it himself, outside the system, on data that did not exist
when it was frozen (paper trading, section 11), before any money is used.

Principle: **agents may be wrong, careless or adversarial by accident, and the system must still produce honest
results.** Agents can be free and creative everywhere except at three trust boundaries, enforced by code, Windows
permissions, firewall rules and GitHub rules, never by instructions alone:

| Boundary | Meaning | Enforced by |
|---|---|---|
| **Who decides success** | A pass or fail comes from fixed code that no agent can change, and design code cannot reach that code | The protected core (section 4); the referee is the commit Nicolas deployed (4.2); design code runs under its own account (3.2) |
| **What gets counted** | Every design tested on market data is recorded; from the judge v1 freeze on, every design raises the multiple-testing bar (the pilot before the freeze is shown in a reported view, 6.7) | Market data is read only by the runner; agents never see run folders or price files (6.4); no agent that reads the web can run code (3.1) |
| **What agents can see and change** | Agents never see reserved data or detailed results they should not see, never write records, never change the core | Windows accounts with allow-list ACLs (section 3); results visible only as grades (6.5); GitHub rulesets (10.3) |

**A known limit, accepted (decided 2026-10-28).** The models that power the agents were trained on text that covers
the development period and most of the registered holdout window (2025-08-14 → 2026-08-13). No permission can make
them unsee it: their choice of ideas may lean towards what they remember worked. Nicolas chose to use the best
available models anyway. Consequences, all recorded in the thesis:
- development and holdout results are "subject to model-knowledge selection" and may be optimistic;
- the registered holdout is a secondary check, labelled as known to the models;
- only data after a strategy's **freeze date** is clean evidence; that is the paper-trading test (section 11), which
  carries the final weight;
- each trial row and manifest records the model(s) that designed it (proposed, roadmap R3).

---

## 2. Roles (target system)

**Doers and judges are separate (decided 2026-10-28).** The one who does a piece of work does not grade it. Agents
that write code never see whether a strategy made money; the agent that chooses what to try next sees grades only;
detailed results are seen only by the runner (which produces them), the auditor and Nicolas.

| Role | Kind | Account | Job | Sees results |
|---|---|---|---|---|
| **Main orchestrator (planner)** | agent | so_code in stage 1 (target account open) | Holds state; picks the next idea, most promising first; writes the plan; chooses variants within the budget; marks ideas explored | **Grades only** (6.5) |
| **Research orchestrator** | agent | so_web | Runs up to 3 research agents on different strategies; ranks them into the strategy registry | Grades only |
| **Research agents (1-3)** | agents | so_web | Read and search literature and the web; describe and rank strategies. **No shell, no code execution** (decided); evidence from our data only by asking the runner | Grades only |
| **Codifier orchestrator** | agent | so_code | Turns a plan into a repository-adapted plan and pre-registered protocol; runs the coding agent; queues runs and watches their technical status | **None**: ran / crashed (with the error) / tests passed / rejected (with the reason) |
| **Coding agent** | agent (exactly one) | so_code | Writes experiment code, tests and non-core shared modules honestly to the plan; fixes crashes | **None** (as codifier) |
| **Code reviewer** | agent | so_code | Reviews pull requests for quality; may merge non-core changes (integrity never depends on it) | None |
| **Auditor** | agent (Nicolas in stage 1) | target account open | **Veto only**: hunts leaks, bugs, implausible numbers in a run that passed; may downgrade a pass, never upgrade a fail; never suggests improvements | **Everything** |
| **Data agent** | agent | so_web | **Postponed (decided 2026-10-28)**: until it exists, new non-price data comes from Nicolas | none |
| **Runner (judge)** | code, not an agent | so_runner | Executes runs on the development view, computes verdict and grade, writes all records | produces them |
| **Design sandbox** | code, not an agent | so_design | Executes design code (import, candidate design, decide, fit, signal) and returns decisions only (3.2) | none |
| **Nicolas** | owner | nico | Changes and deploys the core; supplies market prices from IBKR; holds the kill switch; auditor in stage 1; freezes and paper-trades alerted strategies | everything |

Unchanged decisions from 2026-10-27: the deployment agent is merged into the codifier; the auditor is veto-only; one
coding agent; about three research agents.

---

## 3. Accounts and capabilities

Windows accounts, one per permission set. `so_agent` is renamed `so_code`; `so_web` and `so_design` are new.

| | so_web | so_code | so_runner | so_design | nico |
|---|---|---|---|---|---|
| Internet | yes, **web read/search tools only** | GitHub and package mirrors only (firewall) | GitHub only | **none** | yes |
| Run code | **no** (decided) | yes, never on market data | yes (the judge) | design code only | yes |
| Read development view (`data`) | no | no | yes | **no**: receives rows from the runner | yes |
| Read run folders (equity curves, decisions, reports) | no | no | yes | no | yes |
| Read graded summaries (6.5) | yes | planner: yes; coder and codifier: technical status only | writes them | no | yes |
| Write | own folder; registry, notes | own clone; `agent/*` branches; `queue\pending` | records, run folders, summaries | a temporary folder per run | everything |
| Quarantine, holdout, evaluation results | no | no | no | no | yes |
| Kill switch `data\control\STOP` | read | read | read | read | read and write |

### 3.1 Agents that read the web cannot run code (decided 2026-10-28)
Enforced by the agent runtime's tool list (web search and fetch, file read and write in their own folder, nothing that
executes) and by the account. A research agent that wants evidence from our data asks the runner (6.3).

### 3.2 Design code runs under its own account (decided 2026-10-28; required before stage 2)
The audit reproduced that the in-process guard (`so/runner/guard.py`) can be bypassed by design code (resetting its
private counter, a spawned worker process, rewriting a function's code, Windows path forms such as `\\?\`), and that
design code running as so_runner can write the runner's clone and records. Target: the runner never imports design
code; a separate process under **so_design** runs it, with no network, no read access to the data root, no write
access except a temporary folder, and no secrets; the runner feeds it rows only as they become known (point-in-time
enforcement stays in the runner) and receives decisions. The guard stays as a tripwire.

**In stage 1** this boundary is held by Nicolas instead: he reads and approves every pull request before its run is
queued, so no design code that he has not read touches real data.

Disk: agents may use the 1 TB SSD under an NTFS quota per agent account (before stage 2).

---

## 4. The protected core

A small set of files only Nicolas can change (`protected_paths.txt`). Its purpose is that **no merge can make a
failure look like a success**.

Contents: the runner (point-in-time view, label clocks, engines, selection, baselines, look-ahead check, verdict,
**grades**, cost assumptions, report and manifest); multiple testing and the trial-log writer; data registration and
availability clocks; holdout, quarantine and path guards; the queue and job validation; the sandbox; the agents' rules
(`AGENTS.md`, rule files), this design, the roadmap, `protected_paths.txt`, CI and GitHub configuration, the package
lock; the tests of all of the above.

### 4.1 Judge versioning
Every run records the hash of the judge that scored it (built, A1). Results by different judges are never mixed
silently; when the judge changes, the runs that matter are rerun. **Built (R3, 2026-10-29):** the hash includes
`records/legacy/*.csv` and the package lock (both change verdicts), and the queue takes it from the fresh checkout
before any design code runs and again after the run; a difference fails the run. A change that design code undoes
before the run ends is only closed by the so_design account (3.2).

### 4.2 The referee is the commit Nicolas deployed (decided 2026-10-28)
The runner scores runs only with the commit Nicolas last deployed with `scripts/deploy_runner.ps1` (the "deploy
button"), not with whatever is newest on GitHub. A merge to `main` changes nothing until Nicolas deploys. **Built
(R2, 2026-10-29):** the deploy script sets the ref `refs/deployed` in the runner's clone (with a reflog entry), and the
queue takes the judge of every new job from it; without a deployed commit no new job starts. A job supplies only `experiments/**` from its own commit; a job commit that changes anything else is refused
(built, A2). Manifests record judge, design and run commits.

### 4.3 Shared helpers used by designs (built, R3, 2026-10-29)
Unprotected modules that designs import (`so/features/rule_design.py`, `view_history.py`, `barrier_labels.py`) could
change a pre-registered design without a new protocol version. Every run now records a helper hash of the unprotected
`so/` files its design imports (transitively), and a logged version reruns only with its own helper hash: a changed
helper needs a new protocol version. The helper hash is **not** part of the multiple-testing design key (decided when
built): including it would count every rerun of an unchanged design as a new design; the forced new version records the
change instead. A changed helper under a new version keeps the same design key, so N undercounts it; the 3-version
limit bounds this.

### 4.4 The judge v1 freeze and equivalence checks (decided 2026-11-03)
Every change to a protected `.py` file under `so/` or `scripts/` changes the judge hash, including changes that cannot
affect a score (the queue, the agent view). To keep full reruns of the nine experiments (about 3 hours plus 11-14
hours) to one, every change that can change a score is batched into the **judge v1 freeze**: R4 (grades, hash only),
the pilot ledger (hash only), R4b (total returns: every number changes), and the counted check of the deflated Sharpe
ratio (built, or dropped with a recorded reason). The freeze ends with a reset of the development records (6.7) and one
full rerun of the nine, the baseline. After the freeze, a judge-hash change that touches no scoring code is accepted
by an **equivalence check**: one or two fast daily experiments rerun under the new judge and must reproduce every
number of their baseline run exactly; a change to scoring code means a full rerun.

---

## 5. Strategy lifecycle

**Idea list (stage 1) and strategy registry (target).** Stage 1 starts from a fixed list of 20-30 well-known SPY
timing ideas from the literature, drafted by Claude and edited by Nicolas **after this design is final** (decided).
In the target system research agents add to it; it becomes the strategy registry. Each entry has:
- a **deduplication key** by family and mechanism (not name), so "MA crossover" and "trend filter 50/200" are the same
  idea;
- a state: proposed → in progress → explored;
- links to every trial id and run that tested it.

**Order.** The planner picks the **most promising** idea next, by its own judgment (decided). The order is recorded.

**Budget (decided 2026-10-28).** At most **5 variants per idea** and **3 ideas per broad family** (for example "trend-
following exits"). When the budget is spent the idea is explored, whatever its results. Every variant counts in the
multiple-testing N, inside the budget or not.

**Pre-registration.** Variants are written down before they run, as candidates of a declared grid or a new protocol
version (built: at most 3 protocol versions per experiment).

**Outcome.** The runner's verdict decides. A pass goes to the auditor (Nicolas in stage 1), who may veto it. An
unvetoed pass is **frozen** and goes to paper trading (section 11); **the rest of the system keeps running** (decided).
Negative results are kept, with their reason (section 8).

---

## 6. Testing and records

### 6.1 Full runs
A pre-registered experiment queued at a pushed commit, run by so_runner on the development view, scored by the verdict
(return, consistency, baselines, look-ahead, multiple testing), reported with cost sensitivity.

### 6.2 Queue (built, A2/A2b; A3 adds email and the kill switch)
Validated jobs; bad jobs to `rejected/`; claim into `running/` and resume after a crash; heartbeat; secrets stripped
from the child environment; each run commit kept as `refs/runs/<id>`.

### 6.3 How the system tests ideas (the logged path)
The only way any agent gets answers from market data is a job the runner executes and records (decided). Every
variant writes a trial row. Screening never produces a positive result; only a full run can. **Proposed** (open,
section 14): screening is a flag of the full run (daily bars, no look-ahead check, no email, same scoring and trial
log) rather than a separate subsystem. Not needed for stage 1.

### 6.4 Records and who sees them (decided 2026-10-28)
| Record | Written by | Readable by |
|---|---|---|
| Trial log, run index, run folders (equity curves, decisions, reports, manifests) | so_runner only | so_runner, Nicolas (auditor agent later) |
| **Graded summaries** (6.5): `store04_experiments/visible/grades/<run_id>.json` | so_runner only | planner, research agents, Nicolas (Windows group `so_grade_readers`) |
| **Technical status** (ran / crashed + error / timeout / rejected + reason), without performance numbers: `store04_experiments/visible/status/<job_id>.json` | so_runner only | codifier, coder (group `so_status_readers`) |
| **Queue state** `store04_experiments/visible/state.json` (running job, pending count, last 20 jobs as job id, run id, status) | so_runner only | every agent, Nicolas |
| Results log (`docs/RESULTS_LOG.md`) | generated from the run index; grades only once agents run | everyone (it is in git) |
| Idea list / strategy registry, lessons, failure log | planner (research agents later) | agents |

Reason: a run folder holds every candidate's daily decisions, the per-period returns of the strategy and of
buy-and-hold (`scores.pkl`), and the report's numbers; from these an agent could learn about the market without a
trial row. (Correction 2026-11-02: the audit of 2026-10-28 said development run folders hold `buy_hold_daily_equity.csv`;
only holdout runs write the daily equity files.) Run folders become runner-only before the first agent works with real
data (roadmap R4). Error messages passed to the coder are cleaned of performance numbers.

**`docs/RESULTS_LOG.md`** is public in git and agents can read it, so once agents run it holds grades and identifiers
only, not returns (decided 2026-10-28); the numbers stay in the run index and reports. **Built (R4, 2026-11-03):** the
switch `records/agent_phase.txt` (`development` / `agents`; a protected record, not a `.py` file, so flipping it changes
no judge) decides the row format of `scripts/append_results_log.py`; it is flipped in R6. Rows already written stay;
Nicolas accepted that agents can read the earlier rows of the nine baseline experiments.

**Built (R4, 2026-11-03): what an agent account can read in the data folder.** `store04_experiments\queue\pending`
(list and create), `store04_experiments\visible` (`state.json`; `grades\` through `so_grade_readers`, `status\`
through `so_status_readers`) and `control` (the kill switch). Nothing else: no market data (store01-03), no run folders,
reports, trial log, run index, queue folders, logs, checks or view files (`scripts/setup_so_agent.ps1`, checked by
`scripts/check_agent_access.py` against real files). The finished-run email keeps every number and goes only to Nicolas.
- **The coder's status** says `ran` for a run that has a verdict, with its look-ahead status only: a failed look-ahead
  check is a code bug the coder must fix and says nothing about performance (decided 2026-11-03). A crash carries the
  exception type, the message with every digit outside identifiers replaced by `#`, and the code locations; source
  lines and printed values are dropped. It also carries what a retry needs, so `run_queue.py retry` reads it.
- **A rejected job** (never run, no run id, not counted) gets a status for the coder and no grade (built 2026-11-03,
  confirmed by Nicolas 2026-11-04): a grade describes a run; a refused submission is the coder's to fix.
- **Stage 1: one account for planner and coder** (decided 2026-11-03). `so_agent` is in both reader groups, so in
  stage 1 the coder could read grades (no numbers). R5 gives the planner its own account; only the group memberships
  change.
- **Leaks R4 does not close** (recorded, not hidden): the public git history (the nine baselines' rows, numbers quoted in
  the design documents and commit messages, the pre-reset trial records removed from `main` on 2026-11-03); design code
  runs as so_runner and could copy numbers into `visible\` (stage 1: Nicolas reads every pull request; target: the
  so_design sandbox, 3.2); an agent with internet access could download prices elsewhere and test designs on them uncounted (closed before R6:
  code-running agents get no general internet, roadmap R5, 10.1); the run's
  duration hints at the outcome (a strong path draws more random-timing samples). From R6, no number of an agent-era
  run goes into the repository (documents, commit messages, pull-request text).

### 6.5 Grades (decided 2026-10-28)
The planner never sees numbers. Each finished run gets one grade with its main reason:
- **Passed all checks**
- **Failed: not better than buy-and-hold**
- **Failed: gain disappears after costs**
- **Failed: inconsistent over time**
- **Failed: could be luck (too many attempts)**
- **Failed: technical problem**

The runner computes the grade from the verdict (core code). **Built (R4, decided by Nicolas on 2026-11-03):** the first
failing check in this order gives the grade (`so/runner/grade.py`):

| Order | Situation | Grade |
|---|---|---|
| 1 | No verdict: crashed, timed out, the judge changed during the run, the runner gave up after interruptions | Failed: technical problem |
| 2 | Look-ahead check failed (the design used future data) or did not run | Failed: technical problem |
| 3 | Return check fails even with zero slippage | Failed: not better than buy-and-hold |
| 4 | Return check fails at the standard slippage but passes with zero slippage | Failed: gain disappears after costs |
| 5 | Return passes, consistency fails | Failed: inconsistent over time |
| 6 | Return and consistency pass; baselines (constant exposure, random timing) or multiple testing fail | Failed: could be luck (too many attempts) |
| 7 | Every check passed | Passed all checks (audit pending) |

"Zero slippage" is the cost-sensitivity replay at 0.00 dollars per share with buy-and-hold replayed the same way, and
the full return check (including the comparable band with a better Sharpe ratio or drawdown) re-applied to it; broker
fees are charged in both, so "after costs" here means after slippage. A rejected job is not a run and gets no grade.
Each grade carries one reason from a fixed list (code and sentence, no digits) that names the check, for example
"not above holding the same average exposure without any timing" or "the look-ahead check failed: the design used
future data". A pass has the audit state "pending" until Nicolas (later the auditor agent) vetoes it or not; a veto is
recorded in R6 and never upgrades a fail.

**Format (R4):** one JSON per run, `visible/grades/<run_id>.json`: run_id, job_id, design, design_commit,
judge_commit, attempt, finished_ts, grade, reason_code, reason, audit. A retry of the same run rewrites it. The folder
listing is the index (no separate index file). The grade is also in `report.json`, `report.md`, the manifest's verdict
and the email.

### 6.6 Backups
Trial log, run index, manifests and summaries are copied to the NAS before any unattended run (before stage 2). Until
the NAS exists, Nicolas copies `trial_log.csv` and `run_index.csv` by hand after each batch.

### 6.7 Pilot scope, the tried-designs ledger and resets (decided 2026-11-03)
Everything tried before the judge v1 freeze (4.4) is a **pilot phase** run with earlier, less robust code; its results
were discarded. The verdict's multiple-testing N counts the trial log only; reruns of the same design add nothing.
Every report and email also shows the multiple-testing part with the pilot designs included (reported, not part of the
verdict), so the effect of this scope choice is visible; the thesis states the pilot count (260 designs) and this rule,
and current settings chosen from pilot results are labelled data-dependent (exp13). The **tried-designs ledger**
`records/legacy/pilot_designs.csv` holds the pilot's designs as family and settings only (made from the two pre-reset
records, whose numbers were removed from `main`); it only grows. **Resets:** until R6, `scripts/reset_records.py`
(Nicolas, development phase only) adds the trial log's designs to the ledger, checks that the pilot-included N is
unchanged, moves the trial log, run index, run folders, queue records and agent view to a backup folder outside the data
root, and appends a "withdrawn" note row to the results log. The first reset is at the freeze, before the rerun of the
nine. Pilot variants do not use up the planner's budgets (section 5); the protocol-version limit starts again after a
reset. From R6, nothing is reset and everything counts.

---

## 7. Data

**Market price data** (any instrument, indexes and VIX included) comes **only from Nicolas via IBKR** (decided).
Agents never download prices. When the planner needs price data it files a data request; Nicolas places the data.

**Non-price public data**: until the data agent exists (postponed), Nicolas supplies it. A source enters the
development view only after the core has registered it with its availability clock and a truncation test has passed
(roadmap, later).

**Reserved data** (quarantine; no agent account and no runner job can read it):
- SPY data after each strategy's freeze date (the paper-trading period);
- the registered holdout window (secondary check, known to the models, section 1);
- other indexes (QQQ, IWM, ...) and pre-2005 SPY, as **robustness checks**, not as unseen evidence: they move with SPY
  and their history is also known to the models.

---

## 8. Learning

The system should get more efficient over time (decided). Rules:
1. **Every lesson cites evidence**: trial ids or runs and a confidence. Lessons come from runner records (grades), not
   from agent memory.
2. **Failures record why**, using the grade reasons (6.5). The failure log blocks specific failed designs and reasons,
   not whole ideas forever.
3. **Lessons are revisited** when the judge, the data or the costs change.
4. **Evaluation results never flow back to agents.** Paper-trading and reserved-data results stay with Nicolas and are
   **never committed to the public repository** (future models could learn them).

---

## 9. Notifications

- **One email per full run**, positive or negative (decided; built in A3): verdict, failed parts, returns, N, judge
  hash, commits, paths. A run that passes every part has the subject **"PASS, audit pending"**: Nicolas is the
  auditor in stage 1.
- **Failure emails** for failed, timed-out or abandoned jobs (built). Rejected jobs send nothing.
- **A daily screening digest** once screening exists (later).
- **An alert** when a pass is not vetoed by the auditor agent (later; in stage 1 the "PASS" email is the alert).

---

## 10. Controls

### 10.1 Two kinds of restrictions (decided 2026-10-28)
| Kind | Examples | When |
|---|---|---|
| **Protect the results** | only the runner writes records; every attempt counted (from the freeze on; the pilot, 6.7); deployed referee; agents never see run folders, prices, reserved data or detailed results; **agents that run code have no general internet** (GitHub and package mirrors only), since otherwise they could download prices and test designs privately, uncounted (moved here 2026-11-04); pre-registration; kill switch | **Always on whenever a run uses real market data**, stage 1 included. A result produced while one was off is discarded and rerun |
| **Protect the system from a mess** | firewall rules beyond that (per-account limits for the target roles), disk quotas, GitHub rulesets and machine account, so_design sandbox, separate so_web account, provider-side spend limit | Before stage 2 (unattended). Relaxed while building and testing on synthetic data |

### 10.2 Budgets and the kill switch
- Budgets: per role, plus a **hard monthly spend limit set at the model provider** on the system's own API key (an
  agent-readable budget file is advisory only). Amount: **USD 25 per month** for now (decided 2026-10-28), revised
  when the agents are chosen and the workload is known.
- **Kill switch** (decided): the file `<data root>\control\STOP` (`D:\stock_overflow\data\control\STOP`). Every account
  reads it, only Nicolas writes the `control` folder. The runner starts and resumes nothing while it exists; a running
  job finishes; an unreadable flag counts as set (built, A3). Agents check it before each step (stage-1 build).

### 10.3 GitHub (decided 2026-10-27; re-enabled before any agent credential exists)
- one free machine account for agents, Write role, not a code owner, not on any bypass list; a fine-grained token for
  this repository only, stored only for so_code;
- ruleset on `main`: pull request required, 0 approvals, code-owner review on core paths (Nicolas), required checks
  `tests` and `protected-paths`, no deletion, no force push, Admin bypass for pull requests only;
- second ruleset: non-admins may create and update only `agent/**` branches;
- no secrets in GitHub Actions (a Write account can run any workflow on its branch).

### 10.4 Staged autonomy (decided)
1. **Stage 1, supervised**: the small version (section 12). Nicolas reads and approves every pull request before it
   runs and reads every result email.
2. **Stage 2, unattended, low budgets**: only after every "before stage 2" item in the roadmap is done.
3. **Stage 3, budgets raised.**
Each stage starts only after the previous one ran without integrity problems.

---

## 11. Final evaluation (Nicolas, outside the system)

**Paper trading from the freeze date (decided 2026-10-28).** When a strategy passes and is not vetoed, its code is
frozen that day (a commit and a tag). It is evaluated on SPY data **after its freeze date**, which by construction no
model has seen. There is no fixed calendar start date: the clock starts at the freeze.

**A protocol per strategy, written before its evaluation starts (decided).** Minimum duration and/or a minimum number
of days on which the strategy and buy-and-hold actually differ (a strategy invested 95% of the time may track
buy-and-hold for months), the test used, and three possible outcomes:
- **rejected**;
- **not rejected** (never "proven");
- **not enough evidence yet**.

**What the live test can show (decided 2026-11-04).** Nicolas intends about 2-3 months of live data before deciding
on money; the duration is set per strategy, depending on the model and how it trades. That span is a mechanical and
behavioural check (data and fills work; time in the market, trade frequency and the gaps from buy-and-hold match the
backtest), not proof of an edge: a few months can only detect an edge far larger than a realistic one. The evidence
for an edge comes from the development verdict and from data after the designing model's training cutoff (below).

Paper-trading results stay outside the system and the public repository (section 8). The registered holdout window
and other markets are secondary and robustness checks (section 7). Only after a "not rejected" does Nicolas consider
real money.

**Training-cutoff evaluation (planned, decided 2026-11-04; built with the model choice in R5):** a strategy designed by
a model whose training ended before a date D can also be evaluated honestly on data after D, without waiting. The run
records the designing model and its training cutoff, so this window is known for every design.

Expected outcome, stated in advance: as search reaches hundreds of designs the multiple-testing bar rises steeply, and
the likeliest honest result is many well-documented negatives. That is a valid thesis result.

---

## 12. Stage 1: the small version (decided 2026-10-28)

Built first; the target system (sections 2-11) is reached by adding roles that read and write the same files.

| Part | Stage 1 | Target |
|---|---|---|
| Planner | one agent (so_code), picks from the idea list, most promising first; sees grades only | main orchestrator, fed by research agents |
| Coder | one agent (so_code), blind to results; plan → protocol, code, tests, pull request, queue job | codifier orchestrator + coding agent + code reviewer |
| Ideas | fixed list of 20-30, drafted with Nicolas | strategy registry fed by research agents (web, no shell) |
| Auditor | Nicolas, from the run emails | auditor agent (veto only) + Nicolas |
| Review before a run | Nicolas approves every pull request | code reviewer for non-core; so_design sandbox holds the boundary |
| Data | Nicolas | Nicolas for prices; data agent for non-price |
| Screening | none: full daily runs | screening flag (6.3) |

**Hand-offs are files with a fixed format** (so that later roles plug in): idea list entry → plan file (planner) →
pull request + job file (coder) → run → technical status (to coder) and graded summary (to planner) → email (to
Nicolas). Formats are defined in the stage-1 build (roadmap R5).

**What the coding agent must be good at** (the tool is chosen later, roadmap R5): follow a written plan exactly
without "improving" the strategy; work inside this codebase (reuse helpers, follow the rules and style); write tests
and run them before finishing; fix crashes from a short technical report without seeing results; use git (own branch,
commits, pull requests, never protected files); run unattended on Windows under a spending limit with only GitHub and
package access; stop and report when blocked or refused instead of working around it.

---

## 13. Order of work

The living plan with status is `docs/AGENTIC_ROADMAP.md`. In short: apply A3 → phase C (rerun the nine experiments)
→ referee from the deploy button → run folders hidden and grades → stage-1 planner and coder → supervised cycles →
"before stage 2" items → stage 2 → target roles.

---

## 14. Open items

- Coding/planning agent runtime and model (requirements in section 12; spend limit USD 25 per month for now).
- Exact file formats of plan and job (technical status and graded summary: built, R4, 6.4 / 6.5).
- The counted check of the deflated Sharpe ratio: a diagnostic first, a core change only if the approximation is too
  lenient; inside the judge v1 freeze (4.4).
- How an auditor's veto is recorded against a graded pass (R6).
- How agents are isolated: containers (only the allowed folders mounted, network limited) or Windows accounts; decided
  with the agent runtime in R5 (roadmap R5, 2026-11-04). The R4 ACLs stay either way.
- Screening design (flag of the full run, proposed), when research agents need it.
- Accounts for the planner and auditor in the target (own accounts, or roles within existing ones).
- Data request channel format (file plus email) until an ingest pipeline exists.
- NAS layout for orchestrator state and backups.
- Contents of `D:\stock_overflow\archive` (keep, merge into quarantine, or delete).
- Audit items in the roadmap marked "proposed" (judge hash inputs, shared-helper fingerprint, random-timing tail
  check, queue robustness on Windows).
