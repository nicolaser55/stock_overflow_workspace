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
| `exp13_e1m1_robustness` | exp12's E1M1 rule alone | daily, trailing-stop engine |

## Adding an experiment

1. Copy `_template/` to `expNN_<name>/` (next free number).
2. Write `PROTOCOL.md` from the template before looking at any result: question, success criteria, data and sources,
   rules, the complete candidate list, selection rule, baselines, stopping rule, limitations, trial budget.
3. Fill `config.py` (`EXPERIMENT_NAME`, `PROTOCOL_VERSION = "1.0"`, every constant; shared constants are read from
   `so.config`, never copied).
4. Write `design.py`. Declare every source in `DATA_SOURCE_LIST` (registered in `so.core.point_in_time`).
5. Add tests (synthetic data: rule mechanics, no look-ahead of new features, the design on a short runner loop) to
   `tests/test_experiments.py` or a new suite listed in `tests/run_all_tests.py`.
6. Commit everything (`preregister expNN`), then run: `scripts\run_queue.py add experiments\expNN_<name> --note "<why>"`
   and `scripts\run_queue.py run` (or `scripts\run_development.py experiments\expNN_<name>`).
7. Add the experiment to the registry above.
