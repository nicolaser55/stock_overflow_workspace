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
| `exp14_last_half_hour_exit` | Sell before the last half-hour when the first half-hour or the rest of the day is below −x; buy back at 15:59. Draft, not yet run | daily, fractional, one intraday call at 15:30 |

## Adding an experiment

1. Copy `_template/` to `expNN_<name>/` (next free number). The folder name must equal `EXPERIMENT_NAME`.
2. Write `PROTOCOL.md` from the template before looking at any result: question, success criteria, data and sources,
   rules, the complete candidate list, selection rule, baselines, stopping rule, limitations, trial budget, the
   "Derived from:" line and the "Family:" line (`Family: C, idea C1, variant 1 of 5`; a variant is a protocol version,
   at most 5 per idea). The first run of a new version is refused unless these sections and lines exist and the last
   commit of the folder is a `preregister` commit; a changed folder may not rerun an already-run version; at most three
   versions per family, whatever the experiment name (`so/runner/preregistration.py`).
3. Fill `config.py` (`EXPERIMENT_NAME`, `PROTOCOL_VERSION = "1.0"`, every constant; shared constants are read from
   `so.config`, never copied).
4. Write `design.py`. Declare every source in `DATA_SOURCE_LIST` (registered in `so.core.point_in_time`).
5. Tests and the registry line first, in their own pull request: tests (synthetic data: rule mechanics, no look-ahead
   of new features, the design on a short runner loop) in `tests/test_experiments.py` or a new suite listed in
   `tests/run_all_tests.py`, and its row in the family ledger (`docs/STAGE1_RESEARCH_PLAN.md` section 4). Nicolas merges it and deploys (as so_runner:
   `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_runner.ps1`): a queued
   job may change nothing outside `experiments/`, and a job based on `main` commits that are not deployed is rejected.
   The design folder may sit in the same pull request, or follow in step 6.
6. One commit that touches only `experiments/` (the experiment folder, and its row in the registry above), with a
   subject starting `preregister expNN` (merge commits keep it; a squash merge would rename it, so main allows merge
   commits only). Push it, then queue that commit:
   `scripts\run_queue.py add experiments\expNN_<name> --note "<why>"` (from a clean clone at that commit).
7. Read the result: the email (verdict `pass` or `fail`, failed parts, grade), `store04_experiments/runs/<run id>/report.md`
   (Nicolas and so_runner), and `docs/RESULTS_LOG.md` after `scripts\append_results_log.py` and its pull request.

An amendment after a run is a new `PROTOCOL_VERSION` of the same experiment in the same folder: raise the version, rename
every candidate (for example `v1.1|<name>`; a reused name would add nothing to N and is refused), add a change-log row
labelled `bug-fix` or `data-dependent`, update the variant number of the "Family:" line, then steps 5-7 again. A crash
before the first trial row is not a version: fix, note "pre-run fix: <what>" in the change log, commit with
`preregister` again and requeue.
