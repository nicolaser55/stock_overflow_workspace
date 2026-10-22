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
| `exp01_minute_entry` | Minute-level long entries with a model-chosen symmetric SL/TP distance (LightGBM P(TP) + expected-return policy). Weekly refit, windows 3, 5 and 10 years | 01 development replay | 2.0 | **STOP** (2026-10-15), re-run under the new rules, not new evidence (prior-only +136.53% vs +217.35%). Protocol 1.0/1.1 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp02_stop_reentry` | Invested by default; volatility trailing stop; re-entry when a logistic model of the 20-session return says so | 01 development replay | 2.0 | **STOP** (2026-10-12), re-run under the new rules, not new evidence (prior-only +61.82% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp03_ath_exit` | Sell when the close is near the all-time high; buy back after a delay or a dip (15 rules) | 01 development replay | 2.0 | **STOP** (2026-10-12), re-run under the new rules, not new evidence (prior-only +111.12% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp04_trend_exit` | Benchmark of the "stay invested, exit rarely" family: exit below the 200-session average with buffer/confirmation | 01 development replay | 2.0 | **STOP** (2026-10-14), re-run under the new rules, not new evidence (prior-only +41.51% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp05_vol_scaled_exposure` | Hold w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, 20-point dead band (4 candidates) | 01 development replay | 2.0 | **STOP** (2026-10-14), re-run under the new rules, not new evidence (prior-only +142.59% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp06_capped_regret_reentry` | Trend or near-ATH exit + buy-stop at S × (1 + b) with a cooling-off, or recovery above the 200-session average (12 candidates; data-dependent follow-up of exp03) | 01 development replay | 2.0 | **STOP** (2026-10-14), re-run under the new rules, not new evidence (prior-only +132.25% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp07_warning_lights_exit` | Exit when at least k of 5 fixed warning lights are on, buy back when fewer than k − 1 are (k ∈ {3, 4, 5}) | 01 development replay | 2.0 | **STOP** (2026-10-14), re-run under the new rules, not new evidence (prior-only +40.95% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp12_vix_fear_reentry` | Data-dependent follow-up of exp08 (Nicolas, 2026-10-09): exp09's rules (E1, E2 × M1 fear-fade re-entry, M2 term-structure re-entry, M3 no exit into fear), `_prev` timing only (6 candidates) | 01 development replay | 2.0 | **STOP** (2026-10-14), re-run under the new rules, not new evidence (prior-only +126.51% vs +199.04%). Protocol 1.0 stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |
| `exp13_e1m1_robustness` | Frozen E1M1 (exp12's rule), one candidate. Protocol 1.0's robustness steps are not repeated | 01 development replay | 2.0 | **candidate pending review** (2026-10-14), re-run under the new rules, not new evidence (prior-only +273.85% vs +199.04%; 6-month interval contains 0). Not a success claim. Protocol 1.0 (E1M1 IS NOT ROBUST) stays in `docs/RESULTS_LOG.md`; its code and notebooks are at tag `pre-port-20261012` |

*2026-10-16: exp08 and the skipped exp09–exp11 were removed from this tree. Their results stay in `docs/RESULTS_LOG.md`. Their code and notebooks are at tag `pre-port-20261012`. exp09–exp11 were never written.*

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
   sources, rules, target, features, model, walk-forward and selection, baselines (always include the uninformed version of the
   informed component), stopping rules, reporting, limitations. Exploration only on 2005-2014.
3. **Fill `config.py`**: `EXPERIMENT_NAME = "expNN_<name>"`, `PROTOCOL_VERSION = "1.0"`, and every experiment constant.
   Never copy a shared constant: read it from `so.config`. If the experiment needs a NEW shared constant (e.g. a new daily
   feature), add it to `so/config.py` only if it does not change existing values (that would change every experiment's
   hash) and say so in the protocol.
4. **Write `design.py`** on the runner interface (below). Helpers for signals may live next to it. Do not copy replay,
   selection, baseline or report code; `so.runner` does that. If something becomes useful to several experiments, move it
   to `so/core` or `so/features` with tests.
5. **Development run:** `venv-main\Scripts\python.exe scripts\run_development.py experiments\expNN_<name>`. That script
   loads the design, the development bars and the declared sources, calls `run_development_dict`, and prints the report
   path. Do not read the holdout.
6. **Add tests** `tests/test_expNN.py` (synthetic data; at least: no look-ahead of new features, rule mechanics, the
   design's `decide(view)` on a short runner loop) and add the file to `tests/run_all_tests.py`.
7. **Register it** in the table above and in the root `README.md`; add a section to `docs/RESULTS_LOG.md` when it runs.
8. **Commit the protocol, config, code and tests before the first validation run** (message starts with `preregister expNN`).
   Development folds come from `PERIOD_RULE` and `so.core.schedule.get_development_fold_pdf`, anchored on
   `so.core.holdout.get_development_end_date`. Do not hard-code a holdout date.

`design.py` exposes:

- `CANDIDATE_LIST` and `get_candidate_design(candidate)` → a fresh design object with `decide(view)` (daily) or a
  module-level `signal` (minute).
- `PERIOD_RULE`: `embargo_sessions` and `train_years`. Default: the validation quarters of `get_development_fold_pdf`.
- `SELECTION_RULE`: `pooled_periods` and `tie_break`. Optional `CANDIDATE_TIE_VALUE_DICT`.
- `DATA_SOURCE_LIST`: registered sources only (`docs/DATA_SOURCES.md`).
- `ENGINE_NAME`: `fractional`, `trailing_stop` or `barrier`. Optional `DEAD_BAND`, `INITIAL_WEIGHT`, `MAX_CASH_SESSIONS`.
- A model refits inside `decide` on its pre-registered schedule, through `view.get_labels`. Features come from the
  view's bars or `view.get`. The preflight refuses `so.runner`, `so.core.point_in_time`, `so.core.holdout`, file I/O
  and `.base`.

The template (`experiments/_template/design.py`) is that design: a logistic regression on two daily features, a
20-session label (`TSDAY_FWD`), weekly refits, fractional engine.

## Holdout evaluation (new experiments)

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

The holdout is the registered 12-month window (`so.core.holdout`, `records/holdout_windows.csv`). Development stops an
embargo before its start. Validation uses `get_development_fold_pdf` (validation windows only; the archived
`get_walk_forward_fold_pdf` is unchanged). Only Nicolas runs `scripts/holdout_evaluate.py`, once per frozen design per
window. Agents never set `SO_HOLDOUT_PATH` or `SO_HOLDOUT_EVALUATION_TOKEN`, and never
run `scripts/holdout_window.py` or `scripts/holdout_evaluate.py`.

A design with `get_candidate_design` is evaluated through `so.runner.run_holdout_dict`. A design not yet ported keeps
the old replay (`run_candidate_replay_dict`, `run_prior_only_path_dict`, `get_baseline_return_dict`) until it is
ported. The first printed line of the evaluation script says which path ran.

The runner scores every period as the candidate's continuous-slice return minus buy-and-hold, selects for period f
from earlier periods only, builds the prior-only path from the recorded decisions, and reports the holdout sessions
(equity rebased at the window start). Look-ahead is truncation and perturbation at three sampled cuts. Baselines are
buy-and-hold, daily-rebalanced constant exposure, and 100-seed random timing. The report names total return against
buy-and-hold, time in the market, the uninformed baselines, the runner verdict, and the candidate in force in each
holdout period. The never-read tail of the window is labelled a sanity check.

## Changing an experiment after its first validation run

Create a new version: bump `PROTOCOL_VERSION`, change `EXPERIMENT_NAME` (e.g. `exp02_stop_reentry_v1_1`), record the
change in the protocol's change log, and re-run its notebooks. The trial log keeps both versions; the earlier results
stay in `docs/RESULTS_LOG.md`. Delete the old version's data folder in `store04_experiments/` only if it is no longer
needed (its trials stay in the log).
