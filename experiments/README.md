# Experiments

One folder per experiment. Everything an experiment needs that is **not** shared lives in its folder:

```
experiments/expNN_<name>/
├── __init__.py          one-line description
├── PROTOCOL.md          the rules, agreed BEFORE the experiment's data is explored (versioned change log at the end)
├── config.py            EXPERIMENT_NAME, PROTOCOL_VERSION and every experiment-specific constant
├── <module>.py          experiment code (signal check, walk-forward, rules, ...)
└── stepNN_<purpose>.ipynb   notebooks, run in order; each writes to store04_experiments/<EXPERIMENT_NAME>/stepNN_<purpose>_data/
```

Shared code is imported from `so` (`so.core`, `so.features`), shared constants from `so.config`. Inside notebooks,
`config` is the shared configuration and `exp_config` the experiment's.

## Registry

| Experiment | Question | Steps | Protocol | Status |
|---|---|---|---|---|
| `exp01_minute_entry` | Minute-level long entries with a model-chosen symmetric SL/TP distance (LightGBM P(TP) + expected-return policy) | 01 model dataset, 02 signal check, 03 walk-forward, 04 multivariate signal check (diagnostic, added 2026-10-06) | 1.0 (steps 01-03), 1.1 (step 04) | **archived** (was STOP) 2026-10-06 (signal check p = 0.10; prior-only +146.94% vs +218.48%); step 04 diagnostic 2026-10-06: mean AUC 0.4943 vs null max 0.5282, p = 0.75, no information (cannot reverse the STOP) |
| `exp02_stop_reentry` | Invested by default; volatility trailing stop; re-entry when a logistic model of the 20-session return says so | 01 development replay | 2.0 | **STOP** (2026-10-12), re-run under the new rules, not new evidence (prior-only +61.82% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp03_ath_exit` | Sell when the close is near the all-time high; buy back after a delay or a dip (15 rules) | 01 exploration, 02 walk-forward | 1.0 | **archived** (was STOP) 2026-10-05 (prior-only +143.05% vs +237.21%) |
| `exp04_trend_exit` | Benchmark of the "stay invested, exit rarely" family: exit below the 200-session average with buffer/confirmation | 01 exploration, 02 continuous replay | 1.0 | **archived** (was STOP) 2026-10-06 (prior-only +70.84% vs +229.74%) |
| `exp05_vol_scaled_exposure` | Hold w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, 20-point dead band (4 candidates) | 01 signal check + exploration, 02 continuous replay | 1.0 | **archived** (was STOP) 2026-10-06 (prior-only +165.69% vs +229.74%) |
| `exp06_capped_regret_reentry` | Trend or near-ATH exit + buy-stop at S × (1 + b) with a cooling-off, or recovery above the 200-session average (12 candidates; data-dependent follow-up of exp03) | 01 exploration, 02 continuous replay | 1.0 | **archived** (was STOP) 2026-10-06 (prior-only +147.38% vs +229.74%; beats both random families) |
| `exp07_warning_lights_exit` | Exit when at least k of 5 fixed warning lights are on, buy back when fewer than k − 1 are (k ∈ {3, 4, 5}) | 01 exploration, 02 continuous replay | 1.0 | **archived** (was STOP) 2026-10-06 (prior-only +49.09% vs +229.74%; beats 0/20 random exits) |
| `exp08_vix_signal_check` | The gate of the VIX line: univariate bins (G1), incremental AUC over the 16 price features (G2), VIX as a volatility forecast (G3), top VIX quintile forward return below 0 (G4) | 01 gate | 1.0 | **archived** (was DONE) 2026-10-09, the VIX line stops (G1 S1 = 0; G2 dAUC +0.0359 vs null max +0.0563, p = 0.15; G3 PASS; G4 FAIL) |
| `exp09_vix_reentry` | VIX-timed re-entry / exit filter on exp04's trend exit and exp07's lights (6 candidates) | 01 exploration, 02 continuous replay | not written | **archived** (was SKIPPED) 2026-10-09 by exp08's gate (needs G1 or G2; both fail) |
| `exp10_vix_vol_scaled_exposure` | exp05 with the VIX as the volatility forecast (4 candidates) | 01 exploration, 02 continuous replay | not written | **archived** (was SKIPPED) 2026-10-09 by exp08's gate (needs G3 and G4; G4 fails) |
| `exp11_vix_model_exit` | Exit / re-entry from the price + VIX logistic model (4 candidates) | 01 continuous replay | not written | **archived** (was SKIPPED) 2026-10-09 by exp08's gate (needs G2; fails) |
| `exp12_vix_fear_reentry` | Data-dependent follow-up of exp08 (Nicolas, 2026-10-09): exp09's rules (E1, E2 × M1 fear-fade re-entry, M2 term-structure re-entry, M3 no exit into fear), `_prev` timing only (6 candidates) | 01 exploration, 02 continuous replay | 1.0 | **archived** (was STOP) 2026-10-09 (prior-only +119.24% vs +229.74%; 271 trials; VIX line closed) |
| `exp13_e1m1_robustness` | Data-dependent robustness study of exp12's E1M1, chosen after the fact (Nicolas, 2026-10-09; overrides exp12's "last VIX re-entry test" commitment): stress 2005-2014, parameter neighbourhood, misaligned-VIX placebos, execution and episodes | 01 stress, 02 neighbourhood, 03 placebo, 04 execution and episodes | `PROTOCOL.md` v1.0 | **archived** (was E1M1 IS NOT ROBUST) 2026-10-09 (R1–R4 fail, R5 holds; 81 trials; VIX line closed) |

*2026-10-11 (Nicolas): exp01–exp13 are archived. The status column keeps the historical outcome. No rule, grid,
threshold or recorded number was changed. They stay pinned to the old untouched window 2026-05-14 and are superseded by
`so.core.holdout`. Re-run only by Nicolas with `SO_ALLOW_LEGACY_REPRODUCTION=1`. exp09–exp11 were skipped and have no
`config.py` or `PROTOCOL.md`; the registry rows above are the archive record.*

*2026-10-12 (Nicolas): each strategy folder is replaced in place by a version 2.0. exp02's folder is that version and
its row above is the new result. The other rows stay the archive record until their own version is pre-registered.
Version 1.0 code and notebook outputs are at tag `pre-port-20261012`.*

*Correction 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`, I2): exp06's "beats
both random families" means it beat the median of each (19/20 random exits, 15/20 random re-entries; empirical p ≈ 0.10
and ≈ 0.29, data-dependent design, 12 candidates, about 7,400 trials): "consistent with weak timing information; not
statistically supported".*

## Adding an experiment

1. **Copy `_template/`** to `expNN_<name>/` (next free number, short snake_case name).
2. **Write `PROTOCOL.md`** from the template and agree it before exploring any data: question, success criteria, data,
   rules, target, features, model, walk-forward and selection, baselines (always include the uninformed version of the
   informed component), stopping rules, reporting, limitations. Exploration only on 2005-2014.
3. **Fill `config.py`**: `EXPERIMENT_NAME = "expNN_<name>"`, `PROTOCOL_VERSION = "1.0"`, and every experiment constant.
   Never copy a shared constant: read it from `so.config`. If the experiment needs a NEW shared constant (e.g. a new daily
   feature), add it to `so/config.py` only if it does not change existing values (that would change every experiment's
   hash) and say so in the protocol.
4. **Write the code** in the folder, reusing `so.core` (schedule, simulators, evaluation, trial log, signal-check blocks).
   If something becomes useful to several experiments, move it to `so/core` or `so/features` with tests.
5. **Write the notebooks** `step01_...`, `step02_...` with the standard cells (see `_template/step01_template.ipynb`):
   docstring, imports, header (name, version, hash, output folder, earlier-trial warning), data, work, save, **log**,
   trial count. Walk-forward notebooks follow exp02 step 03 (candidates → pooled selection → prior-only path with
   baselines → summary entry → test only in `latest` / `history`).
6. **Add tests** `tests/test_expNN.py` (synthetic data; at least: no look-ahead of new features, rule mechanics, the
   prior-only runner reproduces the validation candidates) and add the file to `tests/run_all_tests.py`.
7. **Register it** in the table above and in the root `README.md`; add a section to `docs/RESULTS_LOG.md` when it runs.
8. **Expose a design module** `design.py` for the rolling holdout (below). Development folds come from
   `so.core.schedule.get_development_fold_pdf`, anchored on `so.core.holdout.get_development_end_date`. Do not hard-code
   a holdout date.

## Holdout evaluation (new experiments)

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

The holdout is the registered 12-month window (`so.core.holdout`, `records/holdout_windows.csv`). Development stops an
embargo before its start. Validation uses `get_development_fold_pdf` (validation windows only; the archived
`get_walk_forward_fold_pdf` is unchanged). Only Nicolas runs `scripts/holdout_evaluate.py`, once per frozen design per
window. Agents never set `SO_HOLDOUT_PATH`, `SO_HOLDOUT_EVALUATION_TOKEN` or `SO_ALLOW_LEGACY_REPRODUCTION`, and never
run `scripts/holdout_window.py` or `scripts/holdout_evaluate.py`.

`design.py` (it imports the experiment's own code) exposes:

- `PERIOD_RULE`: how candidate periods are formed. Default: the validation quarters of `get_development_fold_pdf`, extended through the holdout with the same step and made non-overlapping by `get_replay_period_pdf`.
- `CANDIDATE_LIST` and `SELECTION_RULE` (the protocol's rule, for example the mean period score over the last 4 periods and its tie order), or a single candidate.
- `run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in)` → the dict the development replay returns (`daily_equity_pdf` at least). Features (volatility, VIX, ...) are loaded through the guarded loaders. Inside the runner the boundary is the day after the window end.
- `run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in)` → the continuous prior-only path, with the position carried across periods. An exit-family design calls `so.core.replay_walk_forward.run_prior_only_replay_dict`. The template uses `simulate_fractional_exposure_dict`.
- `get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in)` → the uninformed baselines the protocol names, over the span the runner passes (the holdout only), with fixed seeds.

A model-based design calls `so.core.rolling_retrain.run_rolling_retrain_dict` inside `run_candidate_replay_dict` and `run_prior_only_path_dict`. The default is a weekly refit (the first session of each week; a Monday holiday is a Tuesday refit) on the candidates `6M`, `2Y` and `10Y`. The first session of the decision span is always a refit. The frequency and the windows are pre-registered; changing either after a result is a new version. One optional pre-registered comparison of weekly against quarterly is allowed. A training row must have `label_known_ts` strictly before the retraining decision. Rows that fail are dropped and counted as purged, never filled with 0 or any other value. Features go through `DataContext` and `check_feature_available_ts`. The candidate in force for a quarter is chosen from the last 4 completed quarters before it, prior-only; a tie takes the longer window. `so.core.evaluation.get_performance_over_time_pdf` reports the cumulative log excess, the rolling 63-session and 252-session excess, and both drawdowns, with a per-quarter table; turnover per year, trades, and candidate switches are reported beside it, and the refit log reports rows used, the share purged, and how far predictions moved between refits. The template (`experiments/_template/design.py`) is that design: a logistic regression on two daily features, a 20-session label, weekly refits, on the fractional-exposure family.

The runner scores every period as the candidate's return minus buy-and-hold, selects for period f from earlier periods only, replays from the first period through the window end, and reports the holdout sessions (equity rebased at the window start). Before writing a result it checks each of 12 month-ends twice: the sessions after the cut are dropped (the cut session stays whole), and every bar strictly after that session's decision bar is perturbed while the session structure stays. Target weights and signals through the cut must match; fills on the cut session are not compared. Ledger status is `valid` or `invalid_lookahead`. An `invalid_lookahead` row writes no daily paths and counts against the budget of 10. The design hash is the sha256 of `git rev-parse HEAD:<design folder>`, `git rev-parse HEAD:so`, and the config hash.

The report uses the same honest numbers as `so.core.evaluation`: total return against buy-and-hold, annualized log excess
with a 6-month block-bootstrap interval, time in the market, Sharpe, maximum drawdown, the uninformed baselines,
the minimum detectable effect of the window, the success criteria (primary: total return above buy-and-hold;
secondary: higher Sharpe or a smaller drawdown with at least 90% of buy-and-hold's return), and the candidate in force
in each holdout period.

## Changing an experiment after its first validation run

Create a new version: bump `PROTOCOL_VERSION`, change `EXPERIMENT_NAME` (e.g. `exp02_stop_reentry_v1_1`), record the
change in the protocol's change log, and re-run its notebooks. The trial log keeps both versions; the earlier results
stay in `docs/RESULTS_LOG.md`. Delete the old version's data folder in `store04_experiments/` only if it is no longer
needed (its trials stay in the log).
