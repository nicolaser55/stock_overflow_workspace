# Point-in-time runner: design (2026-10-20, updated 2026-10-25)

*Written by the assistant for infrastructure step 4 (audit S7 raised to a blocker by Nicolas on 2026-10-19; also S1,
S2, S3, S6, S9, B6). Agreed by Nicolas on 2026-10-21, with the minute mode, the single holdout path and the extra
checks added that day.*

## The rule it enforces

At each decision moment the design is shown only what could have been seen at that moment. This is enforced by how
the design is called, not checked afterwards.

## Three parts

- **Design** (experiment code): turns what it is shown into a decision.
- **Position engine** (shared code, reviewed once): turns decisions into trades, bar by bar. Anything that needs memory
  across minutes (being in a position, the entry price, a trailing high, take-profit and stop-loss levels) lives here,
  not in design code. An engine sees bar t and its own state only.
- **Runner** (shared code): walks time forward, builds the views, calls the design and the engine, and does
  everything around a run (below).

Engines, each ported from the existing simulator and required to reproduce it exactly on tests:

| Engine | Ported from | First user | Status |
|---|---|---|---|
| Fractional weight (costs, dead band, integer shares) | the old fractional simulator (now `tests/fractional_exposure_reference.py`, parity tests only) | exp05 | 4a |
| Barrier trades (take-profit, stop-loss, time exit) | `so.core.trade_execution`, `so.core.backtest_simulation` | exp01 | 4b-2a daily, 4b-2b minute (`BarrierEngine`) |
| Trailing stop and re-entry | `so.core.reentry_simulation` | exp02 | 4b-2a (`TrailingStopEngine`; daily mode with a minute-checked stop) |

The view carries a read-only copy of the engine state as of the decision moment (`in_position`, `share_count`,
`last_exit_session`, `last_exit_reason`, `last_exit_fill_price`, `cash_session_count`). A design learns of a stop-out only at its next
decision. The engine never shows the design anything after that moment. A design module names its engine with
`ENGINE_NAME` (`fractional`, `trailing_stop`, `barrier`).

**Shared design helpers (2026-10-23).** `so.features.view_history.DailyHistory` keeps the `TSDAY` rows a design has
received (one `get_new` per call); `VixPrevHistory` computes `vix_level_prev`, `vix_term_prev` and `vix_pct250_prev`
from `VIX_DAILY` / `VIX3M_DAILY` rows with the definitions of `so.features.vix_features`. `so.features.rule_design.
RuleDesign` is the decide of an exit / re-entry rule on the trailing-stop engine without a stop: a subclass writes the
exit signal and the re-entry rule only. `TSDAY` no longer serves `fill_open` and the complete-session high, low and
close on the feature path: they are computed from bars after the decision bar.

**Stop parameters (2026-10-22).** The `trail_multiple` and `volatility` of a decision take effect at that decision's
fill and stay in force until the next decision's fill, including the next session's morning. The last session of a
window (no decision) keeps the previous ones; before the first decision the engine uses the design module's
`TRAIL_MULTIPLE` / `VOLATILITY` (none: no stop). The candidate stream (`DailyLoop`) and the replay of recorded
decisions (`run_engine_decisions_dict`, used for the prior-only path) follow the same rule, so a one-candidate replay
reproduces that candidate's stream. Until 2026-10-22 the replay applied a session's recorded parameters to its own
morning as well (the old simulator's timing); that was inconsistent with the stream and, for a design whose
parameters use intraday data, would apply them to bars before the decision. The old simulator's timing survives only
in `tests/trailing_timing_reference.py`, for the engine parity tests.

An idea that needs new stateful logic gets a new engine (an infrastructure change, reviewed like any other) or runs
in the slow strict daily mode.

## Daily mode (default)

- The runner walks forward one decision moment at a time (default: every session at the end of the 15:58 bar; fill at
  the 15:59 open, the existing convention).
- At each moment it calls the design with a **view** that ends at that moment:
  - SPY bars up to the end of the decision bar;
  - every declared source with `available_ts` at or before that moment (registered sources only);
  - labels only with `label_known_ts` before that moment, and only through a separate door, for training.
  A read past the end of the view does not exist: the view is a slice that stops there. The design never receives the
  full bar arrays.
- The design may keep any state between calls (running averages, a fitted model). Because the calls come in time
  order and each view stops at its moment, that state cannot contain the future.
- The design returns a decision for its engine (for the fractional engine: a target weight, 0 = cash, 1 = fully
  invested, NaN = keep). Retraining happens inside the design on its pre-registered schedule, through the label door.

## Intraday decision times (R4c, decided 2026-11-11)

For designs that stay invested and step aside for part of a day (stage-1 ideas I1, I2). Code: `so/runner/intraday.py`
plus the daily loop, the replay, the baselines and the look-ahead check. Design note:
`claude/ENGINE_DESIGN_2026-11-11_intraday.md` (project).

- **Interface.** A daily-mode design may declare `INTRADAY_DECISION_TIME_LIST` on the module and on its `Design` class
  (equal; a mismatch is refused), for example `["15:30"]`. Each entry is a bar start in New York time, sorted and
  unique, from `10:00` through `15:57`, at most 32. At each time the runner calls the same `decide(view)` with a view
  that ends at that bar (bars through it, sources advanced to its end, the engine state as of that moment);
  `view.intraday_time_str` is the time, and `None` at the 15:58 call. The fill is the next bar's open (the rule of
  15:58 and 15:59). Only a target weight (or NaN / None = keep) is allowed at an intraday call.
- **Fractional engine only.** Trailing-stop, barrier and minute-mode designs with intraday times are refused.
- **Mapping.** A time maps to the last bar of the session that starts at or before it, strictly before the 15:58
  decision bar, whose fill bar is at or after the session's first-entry bar (10:00); live calls also need a bar after
  the previous call's bar. No such bar, no call that session: a missing minute maps to the bar before it, an early
  close (13:00) has no 15:30 call. The last session of a window has no design call at all (unchanged).
- **Costs.** The same slippage and fees as every fill (decided 2026-11-11).
- **Records and replay.** Each session's recorded decision of an intraday design carries `intraday_list`: one
  (time, target weight) pair per call (NaN = keep). Only the loop writes it. Every replay (prior-only path, cost
  sensitivity, holdout) fills the recorded entries at the same bars before the 15:59 fill; an entry that does not map
  stops the run. A design without intraday times records exactly the old keys and takes the old code path.
- **Baselines.** Buy-and-hold is unchanged. Random timing uses each session's pattern (the weight after each time and
  after 15:59) in place of its weight: spells of non-base sessions keep their time of day and are placed at random with
  the same gap rule; an entry moved to a session where it does not map is skipped and counted
  (`random_timing_intraday_skip_count`). Constant exposure uses the bar-weighted mean weight (the weight held through
  each minute bar). The report says so (`exposure_basis_str`, `constant_exposure_weight_basis_str`).
- **Look-ahead check.** Session cuts as before (their comparison also covers the intraday records). In addition, for
  each candidate, intraday cuts: the first call of each random cut session and up to 10 calls where it acted. At each,
  `intraday_truncation` (every later bar flat at the cut bar's close, later source rows dropped) and
  `intraday_perturbation` (every later bar rebuilt from shuffled returns, later source rows permuted and rescaled).
  Decisions before the cut session, and the cut session's intraday decisions at or before the cut time, must match.
- **Limits.** Fixed per-share slippage on intraday fills (fast markets can be worse); more calls make runs slower (about
  2x for one time, about 13x for twelve) and add look-ahead jobs; random timing keeps each spell's time of day, so the
  choice of time is tested only through the variants counted in N.

## Total returns (R4b, decided 2026-10-29; rules 2026-11-08 and 2026-11-09)

Every return the referee compares is a total return: the strategy, buy-and-hold, the constant-exposure and
random-timing baselines, the period scores, the cost sensitivity and the holdout report.

- **The schedule.** `so.runner.total_return` adds two numbers per session to the price bundle (`ohlcv_array_dict`),
  built from the registered sources `SPY_DIVIDENDS` and `TBILL_3M` through the same loaders and cutoffs as the prices
  (`so.core.development_span` in development, `scripts/holdout_evaluate.py` in the holdout evaluation):
  - `dividend_per_share_arr`: the distribution whose ex-date is that session (or, if the data has no session on the
    ex-date, the next one);
  - `cash_growth_arr`: the interest one dollar of cash earns from the previous close to this close.
- **The credits.** Every engine has `open_session`, which every loop calls before the first fill or bar of each session
  except the window's first:
  - the dividend goes to the shares held at the previous close (shares bought on the ex-date get none; shares sold at
    its fill still do);
  - the interest goes to the cash held at the previous close.
  Both land in cash. An engine never reinvests them on its own: the design's next decision does. Each engine reports
  the totals in `income_dict`.
- **The rate.** The investment yield of the day's DTB3 discount rate for a 91-day bill, `y = 365 d / (360 - 91 d)`,
  accrued over the calendar days between the two closes. A day with no value carries the last one.
  - The **first release** of each value is used, so a later FRED revision never changes a past result.
  - Day t's rate pays the night t to t+1 although FRED posts it on t+1 at 16:30. This is accounting, not a decision
    input; designs read the two sources only through the DataContext, with their feature clocks.
- **Buy-and-hold** is the fractional engine at weight 1, rebalanced at every fill. A dividend is therefore reinvested
  at its ex-date's 15:59 fill, with the normal costs. `get_buy_and_hold_result_dict` runs the same engine, so the
  verdict, the period scores and the holdout report use one buy-and-hold.
- **The basis.**
  - A bundle built without the sources (synthetic tests) has a zero schedule and `total_return_basis_str`
    `"price_only"`; its results equal the earlier price-return results exactly.
  - Real development and holdout bundles always load the sources, and a missing file raises.
  - The report and the manifest state the basis.

## Minute mode (agreed 2026-10-21)

For decisions at minute level (exp01's entries, about 2 million minutes x 12 candidates), where calling Python once per
minute is too slow. It keeps the rule structural:

- **Rows.** Each minute row is built only from data available at the end of that minute (the existing per-session
  caches, stamped with `available_ts`). Before the design sees them, the runner checks every row's `available_ts`
  against its decision moment; one failing row stops the run.
- **Row-local signal.** The design writes one module-level function: rows (plus a model fitted earlier) in, one value
  per row out, where each output may depend only on its own row. The runner enforces this: it passes all rows of one
  refit block together, shuffled, puts the outputs back in order, and calls twice with different shuffles. Identical
  outputs are required or the run stops and names the design. A function that looks at neighbouring rows (shift,
  rolling, cumulative sums) or that keeps state across calls fails. The preflight refuses a method or a closure.
  (4b-2b shuffles a whole refit block, not one session at a time: a session-sized shuffle would miss a signal that
  only looks across sessions inside the same fitted model.)
- **Models.** Fitted on the pre-registered `so.core.rolling_retrain` schedule through the label door
  (`label_known_ts` strictly before the refit moment; unfinished labels dropped). The runner applies each model only
  to rows at or after its refit moment and before the next refit; the design does not choose which rows a model
  scores.
- **Fill.** A signal at the end of minute t fills at the open of minute t + 1 (same session). The last minute of a
  session has no next-bar fill.
- **Engines** turn the signals into trades. Their loops are compiled (numba, added to the locked package list). A 4-year
  synthetic minute run with a small LightGBM, 12 candidates, weekly refits and `n_jobs=8` took 412 s. The real exp01
  run takes 11-14 hours (denser rows, 21 models per refit); Nicolas accepted that on 2026-10-25.

Intraday stops driven by daily decisions (exp02) use daily mode with the trailing-stop engine.

## What the runner does around a run

- **Candidates and selection:** each candidate is its own stream; periods, pooled prior-only selection and the
  carried position are done once in shared code (no copies per experiment). Candidate-period scores are slices of
  each candidate's continuous stream (result over the period's dates, including any position carried in), minus
  buy-and-hold sliced the same way.
- **Run guards:** a run refuses uncommitted changes in the code it uses, a missing or stale `VIEW.json`, and the
  quarantine root; a resume refuses a checkpoint from a different commit or code hash. (Decided 2026-10-21.)
- **Design-code guard (audit B2, 2026-10-25):** every call into design code (module import, `get_candidate_design`,
  `decide`, `fit`, `fit_shared`, `finish_fit`, `signal`) runs behind `so.runner.guard`: an audit hook refuses any
  open, listing, rename or delete under the data root, the quarantine or the holdout folder, and any subprocess or
  network connection; a snapshot of every `so.*` module (functions by identity, UPPERCASE constants by value) is
  compared after the import, after each period and at the end of each stream. The preflight also refuses writes into
  imported names (`config.X = ...`) and `setattr`.
- **Baselines:** buy-and-hold, constant exposure at the same average weight (daily rebalanced), and random timing
  that places the path's non-base spells at random (same time at each weight; switch count may differ from the
  path only at the two window edges). The exposure is the decision target for the fractional engine and the position
  actually held at each close for the trailing-stop and barrier engines, whose exits happen inside the engine (audit
  B1, 2026-10-25: the targets hid every stop and exit). Random timing uses 100 fixed seeds; to count as ahead of it, a design must
  beat at least 95% of the draws. Placing switches independently does not preserve exposure; shuffling run lengths
  in place does not move a one-exit path. Neither is the baseline.
- **Trial log:** rows are written as each candidate-period is scored, before any summary is shown. Trial ids are
  stable (built from the run, candidate and period), so a resumed run never logs the same trial twice. Tested with
  several processes writing at once.
- **Checkpoints:** after each period, so a crash resumes instead of restarting.
- **Parallel:** candidates run in separate processes (8 cores).
- **Verdict parts (2026-10-25):** return; consistency (ahead in at least 60% of the decisive rolling 12-month
  windows; a window within +/-0.5 percentage points of buy-and-hold is a tie and is not counted; at least 24 decisive
  windows; audit S1, a data-dependent amendment because exp13 failed only the old rule); baselines (constant exposure
  with a 0.05 dead band, random timing on the realized exposure); look-ahead; multiple testing (deflated Sharpe
  ratio of quarterly excess returns at 0.95 or more, and random-timing p-value at most 0.05 / N, N = designs tried on
  the development data; `so.core.multiple_testing`, audit B5). **N counts the pilot (decided 2026-11-10):** the
  distinct designs of the trial log and of the tried-designs ledger `records/legacy/pilot_designs.csv` (the pilot
  phase before the judge v1 freeze, family and settings only), 260 at the judge v1 baseline; the report also gives the
  trial log's own count. From 2026-11-03 to 2026-11-10 N was the trial log only and the pilot-included part was a
  reported view; the change revisits that rule after the baseline, in the stricter direction, with no verdict depending
  on it. A reset keeps N; a rerun of an unchanged design adds nothing; N still grows as new designs are logged.
  **The frozen V (R4d, decided 2026-11-12):** V, the variance of the per-design Sharpe ratios of quarterly
  validation excess returns, sets the expected maximum Sharpe of the deflated test. Read live, it depended on the
  order the queue ran designs in, and reruns counted twice, so rerunning the same nine designs in another order
  changed every verdict's V. Now (1) the live V keeps only each design's latest run; (2) on the real development view
  the verdict uses a frozen reference, `<SO_DATA_PATH>/store04_experiments/judge/v_reference.json` (schema, variance,
  design count, the experiments and runs it came from, the trial log's SHA-256 and row count, built time and
  account, a content hash), and refuses to run when the file is missing, edited, unreadable or below
  `MT_MIN_DESIGN_COUNT` designs; synthetic test views keep the live V. Only Nicolas builds it, with
  `scripts/freeze_v_reference.py` (dry run; `--confirm --note`), which refuses unless the kill switch is confirmed,
  no job is running and the quarantine root is not set (`so.paths.check_quarantine_refused`); it keeps the previous file as `v_reference_<built time>.json`
  and appends every build to `judge/v_reference_log.csv`. In stage 1 it is built only at a reset, under STOP and
  just before `reset_records.py`, from the trial log about to be moved (each design's latest run); the reset leaves
  it in place, so the rerun that follows uses the same V throughout. From R6, rebuilds at milestones Nicolas sets. The report gives the source (`"reference"`), the reference's hash and built time, and the
  live V and design count next to it. `holdout_evaluate.py` passes the same reference. A reset does not move
  `judge/`. Limitation: the reference is a judgement frozen at one moment; designs added later do not change V until
  the next rebuild, by design.
  **The random-timing
  p-value is counted, not fitted (R3, 2026-11-02):** p = (k + 1) / (M + 1), k = draws at or above the path; the runner
  extends the 100 registered draws (same seed sequence, same code, 4 worker processes, batches of 1,000) up to the
  budget M + 1 = ceil(2 N / 0.05) (10,400 draws at N = 260; at most 1 draw at or above the path passes) and stops as
  soon as k exceeds what the budget allows, which cannot change the outcome. A typical failing path stops after the
  registered draws. A budget above 200,000 draws, a reduced seed count (tests) or other seeds draw nothing extra and
  cannot pass. The normal fit used before was too lenient: 35 and 37 of 10,000 draws above its critical value where
  1.9 were expected (exp04, exp02; `scripts/check_random_timing_tail.py`). The report also shows
  the prior-only path and buy-and-hold at slippage 0.00 / 0.01 / 0.02 (not part of the verdict), each with the return
  check re-applied (R4: the grade uses the 0.00 row; fees are charged at every level).
- **Grade (R4, 2026-11-03):** `so.runner.grade` turns the verdict into one of the six grades of design 6.5 with one
  reason from a fixed list (first failing check: look-ahead, return even at zero slippage, return only at the standard
  slippage, consistency, baselines or multiple testing; a run without a verdict is a technical problem). The run writes
  it into `report.json` (`grade_dict`), `report.md` and the manifest's verdict (`grade`, `grade_reason_code`).
- **Pre-registration (audit S5):** `so.runner.preregistration` refuses a development run whose version already ran
  with different design-folder code, a first run of a new version without a `preregister` last commit or without the
  required protocol sections and "Derived from:" line, and a fourth version of an experiment. **Shared helpers (R3,
  2026-10-29):** every run also records a helper hash (the unprotected `so/` files the design imports, followed
  transitively, LF-normalized) in each trial row; a version whose rows carry helper hashes may rerun only with one of
  them, so a changed helper needs a new protocol version. Rows from before R3 have none; the first run records it. The
  helper hash is bookkeeping in the multiple-testing design key (a rerun of an unchanged design is not a new design).
  **Across resets (2026-11-09):** "logged" means in the trial log or in `records/legacy/registered_versions.csv`
  (experiment, version, folder hash, helper hash; no results), which `scripts/reset_records.py` fills before it moves
  the trial log and checks to cover it. The file is in the judge hash; the runner reads the deployed copy.
- **Queue and runner account (audit S3 / S4, 2026-10-26; hardened A2, 2026-10-27):** `scripts/run_queue.py`. A job
  names a design commit. The runner account `so_runner` (scheduled task `SO queue runner`, `run_queue.py watch`)
  fetches origin once per pass (before it validates pending files) and builds the run commit from two sources:
  everything except `experiments/` from the **deployed commit** (the judge: the ref `refs/deployed` in the runner's
  clone, set only by `scripts/deploy_runner.ps1`; `SO_QUEUE_JUDGE_REF` overrides the ref; R2, 2026-10-29), and
  `experiments/` from the job's commit. A merge to `main` changes no judge until it is deployed; without a deployed
  commit no new job starts (the jobs wait in `pending/`). The run
  commit has both as parents, a fixed author and date (the same pair always gives the same hash, which a resumed run
  needs) and is kept by `refs/runs/<run id>`. A job commit that changes any other file, holds a symbolic link or a
  submodule under `experiments/`, or has no `experiments/` is rejected, not failed, and nothing is emailed. The runner
  runs `scripts/run_development.py` from a detached worktree at the run commit, under a time limit (default 24 h, the
  whole process tree is killed), with an environment that lacks SMTP settings, tokens and keys, appends one
  `run_index.csv` row per attempt (`judge_commit`, `run_commit` included) and removes the worktree. A pending file is
  untrusted input: only the fields of a job with pattern-checked values are accepted, and a run id, a judge commit or
  a retry marker only when it matches the runner's record of the failed job; anything else is moved to
  `queue/rejected/` with the reason. A claimed job lives in `queue/running/` with its run id and judge commit; after a
  crash or reboot it is resumed under the same run id and judge (at most twice, then filed as failed). A thread
  refreshes `state.json` every 60 s while a job runs; `state.json` also shows the commit of the queue script
  (`queue_commit`) and the judge new jobs would get (`deployed_commit`, empty when nothing is deployed). **Agent view
  (R4, 2026-11-03):** `state.json` lives in `store04_experiments/visible/` and holds identifiers only (the running job's
  job id, design, commits, run id, attempt and times; the last 20 jobs as job id, run id and status `ran` / `crashed` /
  `timeout` / `rejected`); the full-result `state.json` of earlier versions at the zone root is removed on the first
  write. Each filed job also gets `visible/status/<job_id>.json` (the coder's technical status: status, look-ahead
  status of a run that ran, the scrubbed error or rejection reason, the retry fields) and each run
  `visible/grades/<run_id>.json` (the planner's grade). A rejected job gets a status, no grade. `retry` reads the status
  file; the runner still checks a retry against `queue/failed/`. The console prints no results row. Only `visible/`,
  `queue/pending/` and `control/` are open to agents (`scripts/setup_so_agent.ps1`).
  `run_index.csv` is rewritten with the current columns (a copy is kept) when it only lacks columns. A failed job is
  emailed and can be retried under the same run id and judge (it resumes from the checkpoints). On Windows a reader
  that holds `state.json` open blocks its replacement for a moment: the write is retried for about 5 seconds, and a
  failed watch loop is logged and retried after the pause instead of stopping the task (R3). The watch writes its own
  output, time-stamped, to `queue/logs/runner_watch.log` (rotated to `.1` past 5 MB; 2026-11-05), next to the job
  logs; agents cannot read `queue/logs/`. A stale lock from a
  dead process is replaced. Agents can only add job files. **Email (A3):** one email per finished run, positive or
  negative (verdict, failed parts, the grade the planner sees and its reason code, returns, N and the
  multiple-testing result with the pilot designs included (R4), judge hash, commits, paths; "PASS, audit pending" when
  every part passed), one per failed, timed-out or abandoned job, none for a rejected job. **Kill switch (A3):** while
  `<SO_DATA_PATH>/control/STOP` exists (or the file named by `SO_STOP_FLAG_PATH`) the runner starts and resumes
  nothing; a running job finishes; an unreadable flag counts as set. While STOP is set the idle loop writes nothing
  (R4d, 2026-11-12): no `state.json`, no recreated queue folders, so a reset under STOP stays clean; `state.json`
  keeps the last value written before STOP (or is absent after a reset), and `run_queue.py status` adds
  `stopped_now`, the live flag. A deploy right after a reset under STOP therefore finds no `state.json`; read the
  queue folders instead. **Words:** `run_index.csv` and `queue/done/` say `"done"`, and the files agents read
  (`visible/state.json`, `visible/status/`) say `"ran"` (`run_queue.TECHNICAL_STATUS_DICT`), for the same thing: the job ran to the end and produced a verdict (positive or negative); a job in
  `queue/failed/` did not produce one. Both words stay (written records are not rewritten). `scripts/deploy_runner.ps1` (the deploy button) moves the runner clone (the
  queue script itself) to `origin/main`, sets `refs/deployed` to that commit with a reflog entry (time and account;
  `git reflog refs/deployed`), and restarts the task when no job is running. PowerShell reads a script before running
  it, so when a merge changes `deploy_runner.ps1` itself, run it twice (the first run still uses the old script). A job whose commit holds core changes
  that are on `main` but not deployed is rejected with that reason. A finished run deletes its bar and source pickles, checkpoints
  and fit cache; decisions, scores, reports and the manifest stay (audit S11).
- **Report and verdict:** one shared decision rule (the agreed "consistently match or beat" rule) and one run
  manifest (status, commit, `VIEW.json` stamp, trial ids, outputs, verdict) that the orchestrator reads. The stamp
  makes an old run reproducible after the view's edge has moved.
- **Judge identity (design 2026-10-27, `docs/AGENTIC_DESIGN.md`):** `so.runner.judge_identity` hashes every protected
  `.py` file under `so/` and `scripts/`, plus `records/legacy/*.csv` (the tried-designs ledger; part of the verdict's N since 2026-11-10) and the package
  lock `requirements/venv_main_lock.txt` (R3, 2026-10-29), as paths and LF-normalized contents. The report
  (`judge_hash_str`), the manifest (`judge_hash`) and the run index (`judge_hash`) record it. Runs with the same judge
  hash were scored by identical rules; a core change changes the hash, so results judged by different rules are never
  mixed silently. **Checked around every queued run (R3):** the queue hashes the fresh worktree before the run process
  starts and again after it ends; when the two differ, or the report shows another value, the run is filed as failed
  ("judge changed during the run"): design code ran in between. This catches a judge file changed and left changed; a
  change undone before the end is out of reach until design code runs in its own account (roadmap R7, A4). After the judge v1 freeze a hash change that touches no scoring code is accepted when
  `scripts/check_equivalence.py --baseline <run id> --new <run id>` finds every report value (identities aside) and
  every candidate's decisions and scores identical (design 4.4; 2026-11-05).
- **Look-ahead check on every run:** truncation and perturbation at `RUNNER_LOOKAHEAD_CUT_COUNT` (3) random cut dates
  (one from each third of the span, fixed seed), plus, for each candidate, up to `RUNNER_LOOKAHEAD_CHANGE_CUT_MAX` (10)
  sessions where its own decision changed (`RUNNER_LOOKAHEAD_CHANGE_CUT_MAX_MINUTE`, 2, in minute mode), spread
  evenly. For each cut the stream is re-run on bars and sources truncated after the cut (the one extra session that
  gives the cut its call is flat at the cut's last close), and again with every bar after the cut's decision bar
  rebuilt from shuffled returns starting 3% higher (`get_perturbed_ohlcv_dict`) and the declared feature / label rows
  after the cut permuted among themselves and rescaled (`get_perturbed_feature_pdf`). Every decision up to and
  including the cut must match the full run (minute mode, perturbation: every decision made at or before the end of
  the cut session's decision bar). A failure fails the verdict. The re-runs write no trial-log rows. Results go to
  `lookahead.json`. Audit B3 (2026-10-25): with three random cuts and a x1.25 level shift, a one-day leak of a rare
  sign feature passed in 7 of 13 synthetic years; with these cuts and perturbations it fails in 13 of 13
  (`tests/test_runner_lookahead.py`). The check cannot see a future value baked into a cached row or a read around
  the view: the cache audit and the design-code guard cover those.

## Holdout evaluation uses the same runner (agreed 2026-10-21)

Nicolas's holdout evaluation calls the same runner function with the quarantine root and the evaluation token. The run
starts at the development start (warm-up, models, selection history and position carried through), and only the
holdout sessions are reported. The report's result on the never-read part of the window (after 2026-04-15) is labelled
a sanity check: about 80 sessions are too few to pass or fail a design.

Implemented 2026-10-21: `so.runner.run_holdout_dict`. The old replay path in `so.core.holdout`
(`run_holdout_evaluation`, `get_prior_only_result_dict`) was deleted on 2026-10-25 (drop 4):
`scripts/holdout_evaluate.py` evaluates runner designs only, so the development result and the holdout result always
come from one code path.

## What a new experiment writes

`PROTOCOL.md`, `config.py`, and one `design.py` with: the candidate list, the declared sources, the engine and its
parameters, and the decision function (daily) or row-local signal function (minute), plus fit, for a model. A daily
fractional design may add `INTRADAY_DECISION_TIME_LIST` (section "Intraday decision times"). No copied
replay, selection, baseline or report code.
