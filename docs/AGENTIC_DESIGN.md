# Stock Overflow: agentic research system design

*Agreed 2026-10-27 between Nicolas and Claude (design conversation of 2026-10-26/27). This is a design, not a
description of built software: nothing in it is implemented unless section 12 says so. It builds on the code at `main`
`74e483d` and the machine state verified on nicodesktop on 2026-10-26. Labels: **decided** (Nicolas agreed),
**open** (still to decide, listed in section 13).*

---

## 1. Purpose and principle

The system researches, implements and tests long-only, unlevered SPY strategies autonomously, without Nicolas in the
loop, and tells him when something survives. Nicolas then evaluates it himself, outside the system, on data the
agents have never seen.

Principle: **agents may be wrong, careless or adversarial by accident, and the system must still produce honest
results.** Agents can be as free and creative as possible everywhere except at three trust boundaries, which are
enforced by code, Windows permissions, firewall rules and GitHub rules, never by instructions alone:

| Boundary | Meaning | Enforced by |
|---|---|---|
| **Who decides success** | A pass or fail comes from fixed code that no agent can change | The protected core (section 4); the runner runs the core from a commit Nicolas deployed, never from the job's commit |
| **What gets counted** | Every design any agent tests on market data is recorded and raises the multiple-testing bar | Agents read market data only through the logged path (section 6.3); code-running agents have no general internet |
| **What agents can see and change** | Agents never see reserved or evaluation data, never write records, never change the core | Three Windows accounts with allow-list ACLs and firewall rules (section 3); GitHub rulesets (section 10) |

---

## 2. Roles

| Role | Kind | Account | Job |
|---|---|---|---|
| **Main orchestrator** | agent | so_web (no code on market data) | Holds the system's state; picks the next strategy from the strategy registry; writes a simple plan; decides variants within the family budget; delegates; marks strategies explored |
| **Research orchestrator** | agent | so_web | Runs up to **3** research agents in parallel on different strategies (no two on the same one); ranks results into the strategy registry; says when a strategy deserves more variants or is done |
| **Research agents (1-3)** | agents | so_web | Search literature and the web; understand, evaluate and rank strategies. When they need evidence from our data they submit **screening tests** through the logged path (never run code on market data themselves) |
| **Codifier orchestrator** | agent | so_code | Turns a plan into a detailed, repository-adapted plan and pre-registered protocol; runs the coding agent; **queues runs and watches them** (the former deployment agent role is merged here) |
| **Coding agent** | agent (exactly one) | so_code | Writes experiment code and new or improved shared modules outside the core; checks existing modules before writing new ones; one writer avoids conflicts |
| **Code reviewer** | agent | so_code | Reviews pull requests for quality and correctness; may approve and merge changes outside the core. Integrity never depends on it (the core does) |
| **Auditor** | agent | so_web (read-only on results) | **Veto only**: looks for leaks, bugs and implausible numbers in a run that passed and may downgrade a pass; can never upgrade a fail |
| **Data agent** | agent | so_web | Downloads **non-price public data** (macro series, calendars, filings, ...) into a staging area and proposes each source with its availability clock. Never downloads market prices (section 7) |
| **Runner (judge)** | code, not an agent | so_runner | Executes queued runs and screening tests on the development view; computes the verdict; writes all records. Part of the core |
| **Nicolas** | owner | nico | Changes the core; supplies all market price data from IBKR; deploys the judge; holds the kill switch; evaluates alerts on unseen data. Otherwise not involved |

Decided: the deployment agent merges into the codifier; the auditor is veto-only; a data agent is added; one coding
agent; about three research agents.

---

## 3. Accounts and capabilities

Three Windows accounts for agents and the runner, one per distinct permission set (decided). `so_agent` is renamed
`so_code`; `so_web` is new.

| | so_web | so_code | so_runner | nico |
|---|---|---|---|---|
| Internet | **yes** (web research, non-price data) | **GitHub and package mirrors only** (firewall) | GitHub only | yes |
| Run code on market data | **no** (screening requests only) | **no** direct read; through the runner only | yes (the judge) | yes |
| Read development view (`data`) | no | no | yes | yes |
| Write | own working folder; data staging area; strategy registry, lessons, notes | own clone; `agent/*` branches; job and screening request folders | records (`store04_experiments`), run folders | everything |
| Read results (reports, run index) | yes | yes | yes | yes |
| Quarantine, holdout, reserved data, evaluation results | no | no | no | yes |

Design code executes in a **separate low-privilege sandbox process** started by the runner: it receives the view's
data and returns decisions only. The engine, scoring, trial-log writes and report run in the trusted runner process.
The sandbox has no network, no access to the data root or records, and no secrets in its environment (decided:
"design code does not run with the rights to write records"; mechanism detail is open).

Disk: agents may use the 1 TB SSD freely, but under an NTFS quota per agent account so they can never fill the disk
that holds the records.

---

## 4. The protected core

A small set of files only Nicolas can change (decided). Its purpose is that **no merge can make a failure look like
a success**; it does not prevent wasted runs (CI and the code reviewer limit those).

Contents (categories; the exact file list is the first deliverable of phase A):

- the runner: point-in-time view, label clocks, engines, selection, baselines, look-ahead check, **verdict rules**,
  cost assumptions, report and manifest;
- multiple testing and the **trial-log writer**; the logged screening path;
- data registration and availability clocks; the truncation test for new sources; the reserved list;
- holdout, quarantine and path guards; queue and job validation; the sandbox;
- the rules for agents (`AGENTS.md`, rule files), this design document, `protected_paths.txt`, CI and GitHub
  configuration, the package lock;
- the tests of all of the above.

**Judge versioning.** Every core change gets a judge version. Each run and screening test records the judge version
that scored it. When the judge changes, earlier results are marked "judged by version n", and the orchestrator
reruns the ones that matter, so the record never mixes standards silently.

**Deployment.** The runner runs the core from a `main` commit Nicolas deployed (a deploy script fast-forwards the
runner's clone and restarts the task). A job supplies only `experiments/**` from its own commit; a job commit that
changes anything outside `experiments/` relative to `main` is refused. Manifests record both commits: judge and
design.

---

## 5. Strategy lifecycle

**Strategy registry** (written by research and main orchestrators). Each entry has:
- a **deduplication key** by family and mechanism (not name), so "MA crossover" and "trend filter 50/200" are the
  same idea;
- a state: proposed → ranked → in progress (claimed by one agent) → explored;
- links to every trial id and run that tested it, so "explored" is backed by evidence.

Claiming a strategy is atomic, so no two research agents work on the same one.

**Variants.** The main orchestrator chooses variants; the research orchestrator may ask for more when results look
interesting and declares the strategy done when satisfied (decided). Two rules bound this:
- a **budget of designs per strategy family** (decided);
- variants are **pre-registered** before they run, either as candidates inside a declared grid or as a new protocol
  version (decided; the runner already enforces at most 3 protocol versions per experiment).

**Outcome.** Every full run's verdict comes from the runner. A pass goes to the auditor, which may veto it. An
unvetoed pass alerts Nicolas (section 9). Negative results are recorded, Nicolas is informed (one email per full
run), and the strategy is marked explored when the research orchestrator is done with it.

---

## 6. Testing and records

### 6.1 Full runs
As today: a pre-registered experiment queued at a pushed commit, run by so_runner on the development view, scored by
the verdict (return, consistency, baselines, look-ahead, multiple testing), reported with cost sensitivity.

### 6.2 Queue (hardened)
Jobs are validated (schema, safe ids; `run_id` only from runner-written records); bad jobs move to `rejected/`; jobs
are claimed into `running/` and resumed after a crash or reboot; a heartbeat thread runs during jobs; secrets are
stripped from child environments; each design commit is kept locally (`refs/runs/<id>`) so a deleted branch never
makes a result unreproducible.

### 6.3 The logged screening path
The only way agents get answers from market data (decided). An agent submits a screening request (a design and its
candidates); the runner runs it in a fast daily-bar screening mode on the development view, writes **a trial row for
every variant**, and returns summary numbers (return, drawdown, comparison with buy-and-hold). Every idea tested is
therefore counted in the multiple-testing N, however the search is organized. Screening never produces a "positive
result"; only a full run can.

### 6.4 Records
| Record | Written by | Authority |
|---|---|---|
| Trial log, run index, run folders, manifests | so_runner only | authoritative; backed up to the NAS |
| Results log (`docs/RESULTS_LOG.md`) | **generated from the run index**, no longer agent-writable | derived |
| Strategy registry, lessons, failure log | agents | working knowledge, every entry evidence-linked |
| Orchestrator state | orchestrators | on the NAS, survives restarts; a NAS outage stalls agents but never touches the records |

---

## 7. Data

**Market price data** (any instrument's prices, indexes and VIX included) comes **only from Nicolas via IBKR**
(decided). Agents never download prices: public prices do not match IBKR exactly, and reserved data must stay
unseen. When an agent needs price data it files a **data request**; Nicolas downloads it and places it on the data
path. Later an automated ingest pipeline (built by Nicolas) will serve those requests and enforce the reserved list
itself.

**Non-price public data** is fetched by the data agent into a staging area other agents cannot read. A source enters
the development view only after the core has registered it with its **availability clock** (when each value was
knowable) and a **truncation test** has passed (recomputing values with later data removed changes nothing).
New sources may then become runner input without Nicolas (decided).

**Reserved data** (decided): instruments and periods kept for Nicolas's own evaluation, never fetched by agents and
refused by the core's source registration:
- SPY data after each alert date (forward data, added by Nicolas over time);
- the registered holdout window (secondary check only, since agents can see that period elsewhere);
- candidates for out-of-market evidence: QQQ, IWM and other indexes; possibly pre-2005 SPY.

The quarantine folder holds reserved data; no agent account and no runner job can read it.

---

## 8. Learning

The system should become more efficient over time (decided). Four rules keep learning honest:
1. **Every lesson cites evidence**: trial ids or runs, and a confidence. Lessons come from runner records, not agent
   memory, so a wrong lesson can be traced and removed.
2. **Failures record why**: costs, no edge, overfitting, look-ahead caught, data problem. A failure log blocks
   specific failed designs and failure reasons, not whole ideas forever.
3. **Lessons are revisited** when the judge, the data or the costs change, against the current judge version.
4. **Evaluation results never flow back to agents.** Nicolas's results on forward or reserved data stay outside the
   agents' knowledge, at least in detail; otherwise that data is no longer unseen.

Every search, however clever, still goes through the logged path, so learning cannot hide selection.

---

## 9. Notifications

- **One email per full run**, positive or negative (decided), with the run id, verdict, failed parts and the report path.
- **A daily screening digest**, sent once a day only on days screening ran (decided).
- **Failure emails** for failed or timed-out jobs (as today).
- **An alert** when a full run passes and the auditor does not veto it.

---

## 10. Controls

- **Budgets**: one per role, plus a hard global stop on API spend (decided).
- **Kill switch**: one flag file that the orchestrators, agents and the runner check before each step; Nicolas sets it
  from his laptop to stop the whole system cleanly (decided; location open).
- **Staged autonomy** (decided): (1) single supervised cycles, every step read by Nicolas; (2) unattended with low
  budgets; (3) budgets raised. Each stage is entered only after the previous one ran without integrity problems.

GitHub (decided; free plan, public repository):
- one free **machine account** for agents, Write role, not a code owner, not on any bypass list; a fine-grained token
  for this repository only, stored only for so_code;
- ruleset on `main`: pull request required, **0 approvals**, **code-owner review on core paths only** (Nicolas),
  required checks `tests` and `protected-paths` from GitHub Actions, no deletion, no force push, Admin bypass for pull
  requests only;
- second ruleset: non-admins may create and update only `agent/**` branches.

The code reviewer may therefore merge agent changes outside the core; a core change cannot merge without Nicolas.

---

## 11. Final evaluation (Nicolas, outside the system)

After an alert, Nicolas evaluates the frozen design independently, with his own agent and workspace, on data the
system has never seen: forward SPY data after the alert date, and optionally reserved markets (QQQ, IWM, ...) or
periods. The language of a successful evaluation is **"not rejected"**, not "proven": a few months of forward data
can reject a strategy but rarely confirm one strongly. Regime evidence on the development data comes from the
runner's existing walk-forward and 12-month consistency windows (a per-regime breakdown in the report is planned).

Expected outcome, stated in advance: as autonomous search reaches hundreds of designs, the multiple-testing bar rises
steeply, and the likeliest honest result is many well-documented negatives. That is a valid thesis result.

---

## 12. Order of work

Status today: none of sections 2-11 is built. Built and verified: the runner, verdict, multiple testing,
pre-registration, queue (unhardened), so_runner and so_agent accounts with allow-list ACLs, the scheduled runner task,
the `main` ruleset (with 0 approvals and no `agent/**` ruleset).

| Phase | Content |
|---|---|
| **A. Core** | Exact core list; judge versioning; judge pinned to a deployed commit and job commits limited to `experiments/`; sandbox process for design code; queue hardening (6.2); logged screening path (6.3); source registration with clocks, truncation test and reserved list; kill-switch checks in the runner |
| **B. Platform** | Accounts so_web / so_code / so_runner with allow-list ACLs, firewall rules and quotas; setup scripts that reproduce the machine; deploy script; GitHub machine account and rulesets; results log generated from the run index; **NAS backups before any unattended run**; base Python moved out of Nicolas's profile; inspect `D:\stock_overflow\archive` |
| **C. Baseline** | Rerun the nine existing experiments on the hardened runner (end-to-end test; first valid results) |
| **D. Orchestrator** | Registries, lessons and failure log; roles and prompts; budgets; then staged autonomy (section 10) |

Each phase is delivered as reviewed pull requests; core changes are Nicolas's to merge.

---

## 13. Open items

- Orchestrator runtime and models (Claude Code, API, other) and their costs; how agents are launched under each account.
- Sandbox mechanism on Windows for design code (separate account and process; exact IPC).
- Screening mode specification (speed target, what it returns, how it counts candidates).
- Budget sizes per role and per strategy family; global spend stop.
- Kill-switch location (readable by all accounts, writable only by Nicolas, reachable from his laptop).
- After an alert: does the whole system halt, or only that strategy line while research continues?
- Data request channel format (file plus email) until the ingest pipeline exists.
- NAS layout for orchestrator state and backups.
- Contents of `D:\stock_overflow\archive` (keep, merge into quarantine, or delete).
- Small audit items carried over: exp13 `Derived from:` line; preflight walking beyond `experiments/`; about 10
  in-window minute rows in public git history (`7c024ba`).
