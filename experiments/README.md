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
| `exp01_minute_entry` | Minute-level long entries with a model-chosen symmetric SL/TP distance (LightGBM P(TP) + expected-return policy) | 01 model dataset, 02 signal check, 03 walk-forward | 1.0 | **STOP** 2026-10-06 (signal check p = 0.10; prior-only +146.94% vs +218.48%) |
| `exp02_stop_reentry` | Invested by default; volatility trailing stop; re-entry when a logistic model of the 20-session return says so | 01 mechanism check, 02 signal check, 03 walk-forward | 1.0 | **STOP** 2026-10-05 (0 signals; prior-only +111.66% vs +237.21%) |
| `exp03_ath_exit` | Sell when the close is near the all-time high; buy back after a delay or a dip (15 rules) | 01 exploration, 02 walk-forward | 1.0 | **STOP** 2026-10-05 (prior-only +143.05% vs +237.21%) |
| `exp04_trend_exit` | Benchmark of the "stay invested, exit rarely" family: exit below the 200-session average with buffer/confirmation | 01 exploration, 02 continuous replay | 1.0 | **STOP** 2026-10-06 (prior-only +70.84% vs +229.74%) |
| `exp05_vol_scaled_exposure` | Hold w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, 20-point dead band (4 candidates) | 01 signal check + exploration, 02 continuous replay | 1.0 | Pre-registered 2026-10-06 |
| `exp05_vol_scaled_exposure` | Fractional exposure scaled down when realized volatility is high | — | to write | Planned |
| `exp06_capped_regret_reentry` | Exits paired with a buy-stop at S × (1 + b) and a recovery trigger | — | to write | Planned (data-dependent follow-up of exp03) |
| `exp07_warning_lights_exit` | Exit only when k of 5 fixed warning conditions agree | — | to write | Planned |
| VIX experiment(s) | exp05/exp07 with VIX; meta-labeling of exits | — | to write | Planned after exp07 (VIX closes at 16:15 ET; VIX3M starts 2007-12-04); needs Nicolas for the data |

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

## Changing an experiment after its first validation run

Create a new version: bump `PROTOCOL_VERSION`, change `EXPERIMENT_NAME` (e.g. `exp02_stop_reentry_v1_1`), record the
change in the protocol's change log, and re-run its notebooks. The trial log keeps both versions; the earlier results
stay in `docs/RESULTS_LOG.md`. Delete the old version's data folder in `store04_experiments/` only if it is no longer
needed (its trials stay in the log).
