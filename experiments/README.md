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
| `exp01_minute_entry` | Minute-level long entries with a model-chosen symmetric SL/TP distance (LightGBM P(TP) + expected-return policy) | 01 model dataset, 02 signal check, 03 walk-forward, 04 multivariate signal check (diagnostic, added 2026-10-06) | 1.0 (steps 01-03), 1.1 (step 04) | **STOP** 2026-10-06 (signal check p = 0.10; prior-only +146.94% vs +218.48%); step 04 diagnostic 2026-10-06: mean AUC 0.4943 vs null max 0.5282, p = 0.75, no information (cannot reverse the STOP) |
| `exp02_stop_reentry` | Invested by default; volatility trailing stop; re-entry when a logistic model of the 20-session return says so | 01 mechanism check, 02 signal check, 03 walk-forward | 1.0 | **STOP** 2026-10-05 (0 signals; prior-only +111.66% vs +237.21%) |
| `exp03_ath_exit` | Sell when the close is near the all-time high; buy back after a delay or a dip (15 rules) | 01 exploration, 02 walk-forward | 1.0 | **STOP** 2026-10-05 (prior-only +143.05% vs +237.21%) |
| `exp04_trend_exit` | Benchmark of the "stay invested, exit rarely" family: exit below the 200-session average with buffer/confirmation | 01 exploration, 02 continuous replay | 1.0 | **STOP** 2026-10-06 (prior-only +70.84% vs +229.74%) |
| `exp05_vol_scaled_exposure` | Hold w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, 20-point dead band (4 candidates) | 01 signal check + exploration, 02 continuous replay | 1.0 | **STOP** 2026-10-06 (prior-only +165.69% vs +229.74%) |
| `exp06_capped_regret_reentry` | Trend or near-ATH exit + buy-stop at S × (1 + b) with a cooling-off, or recovery above the 200-session average (12 candidates; data-dependent follow-up of exp03) | 01 exploration, 02 continuous replay | 1.0 | **STOP** 2026-10-06 (prior-only +147.38% vs +229.74%; beats both random families) |
| `exp07_warning_lights_exit` | Exit when at least k of 5 fixed warning lights are on, buy back when fewer than k − 1 are (k ∈ {3, 4, 5}) | 01 exploration, 02 continuous replay | 1.0 | **STOP** 2026-10-06 (prior-only +49.09% vs +229.74%; beats 0/20 random exits) |
| `exp08_vix_signal_check` | The gate of the VIX line: univariate bins (G1), incremental AUC over the 16 price features (G2), VIX as a volatility forecast (G3), top VIX quintile forward return below 0 (G4) | 01 gate | 1.0 | **DONE** 2026-10-09, the VIX line stops (G1 S1 = 0; G2 dAUC +0.0359 vs null max +0.0563, p = 0.15; G3 PASS; G4 FAIL) |
| `exp09_vix_reentry` | VIX-timed re-entry / exit filter on exp04's trend exit and exp07's lights (6 candidates) | 01 exploration, 02 continuous replay | not written | **SKIPPED** 2026-10-09 by exp08's gate (needs G1 or G2; both fail) |
| `exp10_vix_vol_scaled_exposure` | exp05 with the VIX as the volatility forecast (4 candidates) | 01 exploration, 02 continuous replay | not written | **SKIPPED** 2026-10-09 by exp08's gate (needs G3 and G4; G4 fails) |
| `exp11_vix_model_exit` | Exit / re-entry from the price + VIX logistic model (4 candidates) | 01 continuous replay | not written | **SKIPPED** 2026-10-09 by exp08's gate (needs G2; fails) |
| `exp12_vix_fear_reentry` | Data-dependent follow-up of exp08 (Nicolas, 2026-10-09): exp09's rules (E1, E2 × M1 fear-fade re-entry, M2 term-structure re-entry, M3 no exit into fear), `_prev` timing only (6 candidates) | 01 exploration, 02 continuous replay | 1.0 | **STOP** 2026-10-09 (prior-only +119.24% vs +229.74%; 271 trials; VIX line closed) |
| `exp13_e1m1_robustness` | Data-dependent robustness study of exp12's E1M1, chosen after the fact (Nicolas, 2026-10-09; overrides exp12's "last VIX re-entry test" commitment): stress 2005-2014, parameter neighbourhood, misaligned-VIX placebos, execution and episodes | 01 stress, 02 neighbourhood, 03 placebo, 04 execution and episodes | `PROTOCOL.md` v1.0 | pre-registered (2026-10-09), budget 150 (81 expected) |

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

## Changing an experiment after its first validation run

Create a new version: bump `PROTOCOL_VERSION`, change `EXPERIMENT_NAME` (e.g. `exp02_stop_reentry_v1_1`), record the
change in the protocol's change log, and re-run its notebooks. The trial log keeps both versions; the earlier results
stay in `docs/RESULTS_LOG.md`. Delete the old version's data folder in `store04_experiments/` only if it is no longer
needed (its trials stay in the log).
