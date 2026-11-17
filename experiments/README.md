# Experiments

One folder per experiment, all on the point-in-time runner (`so.runner`, `docs/RUNNER_DESIGN.md`):

```
experiments/expNN_<name>/
├── PROTOCOL.md     question, rules, candidates, selection, stopping rule; committed before the first run
├── config.py       EXPERIMENT_NAME, PROTOCOL_VERSION and every experiment constant
├── design.py       the design: candidates, declared sources, engine, decide(view) (daily) or signal(rows, model) (minute)
└── <helpers>.py    experiment-only code the design imports (e.g. a model)
```

A design does not copy replay, selection, baseline, look-ahead or report code; the runner does all of that.
Shared design helpers: `so.features.view_history` (`DailyHistory`, `VixPrevHistory`) and `so.features.rule_design`
(`RuleDesign`, exit / re-entry rules on the trailing-stop engine).

## Registry

Results: `docs/RESULTS_LOG.md` (one row per run). All rows below are protocol 1.0 of the fresh log (2026-10-22).

| Experiment | Question | Mode, engine |
|---|---|---|
| `exp01_minute_entry` | Minute entries with a model-chosen take-profit distance (LightGBM per distance, expected-return policy, weekly refit, 3-10 year windows) | minute, barrier |
| `exp02_stop_reentry` | Invested by default; volatility trailing stop; re-entry when a weekly logistic model says so | daily, trailing-stop engine |
| `exp03_ath_exit` | Sell near the all-time high; buy back after a delay or a dip | daily, trailing-stop engine |
| `exp04_trend_exit` | Exit below the 200-session average with a buffer or confirmation | daily, trailing-stop engine |
| `exp05_vol_scaled_exposure` | Hold a volatility-scaled fraction of the account in SPY | daily, fractional |
| `exp06_capped_regret_reentry` | Trend or near-ATH exit, buy-stop or recovery re-entry with a cooling-off | daily, trailing-stop engine |
| `exp07_warning_lights_exit` | Exit when at least k of 5 warning lights are on | daily, trailing-stop engine |
| `exp12_vix_fear_reentry` | Exits and re-entries modified by VIX fear and term structure (previous-session values) | daily, trailing-stop engine |
| `exp13_e1m1_robustness` | exp12's E1M1 rule alone. Derived from: exp12 candidate E1M1, chosen after exp12's results on the same development data were seen (audit B5); not an independent test | daily, trailing-stop engine |
| `exp14_last_half_hour_exit` | Sell before the last half-hour when the first half-hour or the rest of the day is below −x; buy back at 15:59. Run 2026-11-16: fail (gain disappears after costs) | daily, fractional, one intraday call at 15:30 |

## Adding an experiment

1. Copy `_template/` to `expNN_<name>/` (next free number). The folder name must equal `EXPERIMENT_NAME`.
2. Write `PROTOCOL.md` from the template before looking at any result: question, success criteria, data and sources,
   rules, the complete candidate list, selection rule, baselines, stopping rule, limitations, trial budget, the
   "Derived from:" line and the "Family:" line (`Family: C, idea C1, variant 1 of 5`; a variant is a protocol version,
   at most 5 per idea), about 3-5 candidates, and the prediction line of section 1 (expected direction, the part of
   the verdict most likely to fail). Keep the template's `## ` headings as they are, including `## 3.1 Data
   sources`: the runner looks for `## ` headings only, and a `###` heading crashed exp14 twice. The first run of a
   new version is refused unless these sections and lines exist and the last
   commit of the folder is a `preregister` commit; a changed folder may not rerun an already-run version; at most three
   versions per family, whatever the experiment name (`so/runner/preregistration.py`).
3. Fill `config.py` (`EXPERIMENT_NAME`, `PROTOCOL_VERSION = "1.0"`, every constant; shared constants are read from
   `so.config`, never copied).
4. Write `design.py`. Declare every source in `DATA_SOURCE_LIST` (registered in `so.core.point_in_time`).
5. Tests and the registry line first, in their own pull request: tests (synthetic data: rule mechanics, no look-ahead
   of new features, the design on a short runner loop) in `tests/test_experiments.py` or a new suite listed in
   `tests/run_all_tests.py`, and its row in the family ledger (`docs/STAGE1_RESEARCH_PLAN.md` section 4). Nicolas merges it
   (`scripts\nico_merge.ps1 -Pr <n>`) and deploys (as so_runner:
   `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_runner.ps1 -ExpectCommit <merge commit>`): a queued
   job may change nothing outside `experiments/`, and a job based on `main` commits that are not deployed is rejected.
   The design folder may sit in the same pull request, or follow in step 6.
6. One commit that touches only `experiments/` (the experiment folder, and its row in the registry above), with a
   subject starting `preregister expNN` (merge commits keep it; a squash merge would rename it, so main allows merge
   commits only). After that commit, `scripts\check_experiment_ready.py experiments\expNN_<name>` must end with no
   FAIL (the checklist below). Push it. Nicolas merges it (`scripts\nico_merge.ps1 -Pr <n>`), deploys
   (`deploy_runner.ps1 -ExpectCommit <merge commit>`), and queues with the wrapper, which refuses unless his clone,
   `origin/main` and the deployed commit agree and the readiness check passes with the trial log:
   `scripts\nico_queue.ps1 -Experiment expNN_<name> -Note "<why>"`.
7. Read the result: the email (verdict `pass` or `fail`, failed parts, grade), `store04_experiments/runs/<run id>/report.md`
   (Nicolas and so_runner), and `docs/RESULTS_LOG.md` after `scripts\append_results_log.py` and its pull request.
   What a result can and cannot show, the lower tier and the holdout rule: `docs/STAGE1_RESEARCH_PLAN.md` section 1.1.

An amendment after a run is a new `PROTOCOL_VERSION` of the same experiment in the same folder: raise the version, rename
every candidate (for example `v1.1|<name>`; a reused name would add nothing to N and is refused), add a change-log row
labelled `bug-fix` or `data-dependent`, update the variant number of the "Family:" line, then steps 5-7 again. A crash
before the first trial row is not a version: fix, note "pre-run fix: <what>" in the change log, commit with
`preregister` again and requeue.

## The checklist before each review (the agent, as so_agent; review 2026-11-17, B5 and B6)

Paste the output of each item into the review request. Run `git fetch origin` first.

1. `scripts\check_experiment_ready.py experiments\expNN_<name>` (add `--draft` while the protocol is still a draft:
   the DRAFT marker, the `preregister` commit and files outside `experiments/` are then PENDING or INFO). It calls the
   runner's own checks (preflight, protocol lint, folder name, versions, candidate names, the `preregister` subject,
   only `experiments/` changed since `origin/main`, `check_preregistration_dict`). Lines marked SKIPPED need the trial
   log, which so_agent cannot read: they are not passed, and Nicolas's queue wrapper runs them. No FAIL line may remain.
2. The candidate table of `PROTOCOL.md` against the HAND line `candidates`: the same names, in the same order, about 3-5.
3. The "Family:" line against the HAND line of section 4: the idea is eligible in that family, and the variant is the
   next free one for the idea (versions already used, across experiments).
4. No DRAFT left in `PROTOCOL.md` (for the `preregister` commit).
5. `tests\run_all_tests.py --fast` and the experiment's own tests (`tests\run_all_tests.py --suite test_experiments.py`).

Reviews (decided 2026-11-17): two Claude reviews per experiment, (1) the brief and the draft protocol, (2) the design,
the config and the tests. The third is not a review: after the `preregister` commit, the agent pastes
`scripts\check_experiment_ready.py experiments\expNN_<name> --reviewed <commit of review 2>`, which adds
`git diff --stat <reviewed>..HEAD` and the folder's diff since that commit; it must show only the DRAFT marker removed
(and the change-log row's status).
