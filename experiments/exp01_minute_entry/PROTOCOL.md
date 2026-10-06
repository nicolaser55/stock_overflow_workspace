# exp01_minute_entry: Protocol

*Version 1.0 (2026-10-05). Experiment name `exp01_minute_entry`. Config: `experiments/exp01_minute_entry/config.py` +
`so/config.py`. This is protocol v1 (`docs/history/RESEARCH_PROTOCOL_v1.md`, experiments `signal_check_v1` /
`lgbm_ev_policy_v1`, stopped on 2026-10-04) re-run in the reorganized workspace. **The trading rules, targets, features,
model, policy, schedule and selection are unchanged**; the changes decided by Nicolas on 2026-10-05 concern the signal
check and the reporting (§17). After the first `validation_only` run of step 03, any rule change is a new version with a
new experiment name.*

*Version 1.1 (2026-10-06) adds a diagnostic, the multivariate signal check of step 04 (§13.3), decided by Nicolas after
exp01's results were known. exp01 stays **STOPPED** (step 02, p = 0.10); step 04 can help explain the failure but
cannot reverse the STOP or restart the walk-forward. Only constants were added (no existing rule, constant, function or
notebook changed), so the config hash changes; steps 01-03 remain recorded under hashes `16493e598a` / `15716b01a3`.*

---

## 1. Research question

Can a model trained on SPY's own minute-level price action, technical indicators and market context:

- pick **long entries**,
- **and an SL/TP distance for each entry**,

so that, **after realistic costs, its total return beats buy-and-hold over the same period**, out of sample?

The original aim ("TP reached substantially more often than SL") is tested in its meaningful form by the signal check: the
TP rate **after a signal** must exceed the **unconditional** TP rate at the same distance (the base rate), because a high TP
rate alone can be obtained without skill (audit §4). The qualitative (text) part of the original hypothesis is deferred.

## 2. Success definition

| | Definition |
|---|---|
| **Primary metric** | Total return after all costs vs buy-and-hold over the same span (`excess_return = total_return − buy_hold_return`) |
| **Secondary metrics** | A higher annualized Sharpe ratio (daily mark-to-market, risk-free 0) **or** a smaller maximum drawdown than buy-and-hold, at a comparable return (≥ 90% of buy-and-hold's); either is enough (Nicolas, 2026-10-05) |
| **Information** | The model must beat the random-entry baseline of matched activity (§11) |
| **Diagnostics** | Trades, TP/SL/TL rates, WIN/LOSS/NULL counts, exposure, decisions skipped while a position was open |
| **Benchmark** | Buy-and-hold: buy at the first allowed entry (10:00 open), sell at the last close (or at the strategy's last exit if later), same slippage and fees |

Dividends are ignored (favours time in cash); cash earns 0%.

## 3. Data

SPY 1-minute bars from IBKR, regular hours, 2005-01-03 onward, unadjusted, bad ticks corrected by the 3% rule. Pipeline
steps 00-05 (kept, see `pipeline/README.md`) provide the features (TSIND, TSSEG, TSCTX) and targets (TSBAR).

## 4. Decision and execution rules (`so/core/trade_execution.py`, `so/core/backtest_simulation.py`)

1. **Decision:** the feature row of bar t (every feature uses only bars ≤ t: snapshot design, tested).
2. **Entry:** the open of bar t+1 in the same session; first entry 10:00 (decision 09:59), last entry 15:59 (decision 15:58).
3. **Barriers:** TP = open·(1+d), SL = open·(1−d·rr), rr = 1, rounded to $0.001; active from the bar after the entry.
4. **Exit on each active bar, in this order:** open ≤ SL → exit at the open (SL); open ≥ TP + 1 tick → exit at the open (TP);
   low reaches SL → exit at SL (SL wins if TP is also hit); high reaches TP + 1 tick → exit at TP.
5. **Holding limit:** 10 trading days (entry day = day 1); time-limit exit at the close of the last bar of day 10.
6. **One position at a time**; buy decisions made while a position is open are skipped.
7. **Sizing:** the whole account in every trade, compounding.

## 5. Costs (`so/config.py`)

Entry +$0.01/share; SL, time-limit and end exits −$0.01/share; TP limit exits no slippage; IBKR fixed fees $0.005/share,
min $1, max 1% per side; sensitivity $0.00 / $0.01 / $0.02. Informal assumptions, not measured fills.

## 6. Target (pipeline step 05, TSBAR)

One row per decision bar and one cell per SL/TP distance (`exit_bar_count|exit_price|exit_reason`, reason TP/SL/TL/NA).
32 distances 0.05%–2.00%; the 21 distances 0.10%–1.00% are modelled (`MODEL_DELTA_LIST`). `y_tp` = 1 for TP, 0 for SL or
TL; NA rows excluded. `net_return` is computed with §5 when the dataset is read.

## 7. Features

TSIND (43 fields), TSSEG, TSCTX, registered with a scale type in `so.config.FEATURE_REGISTRY_DICT`. Absolute-dollar
features are excluded from the model (they encode the price level, i.e. the year). Constants keep their original values.

## 8. Sampling and weights

Training rows every 15 minutes from 10:00 (`SAMPLING_MODE = "interval"`), uniqueness weights. Validation and test simulate
**every** eligible minute.

## 9. Splits and walk-forward (`so/core/schedule.py`, `walk_forward.py`)

```
|---- train (L years) ----| 10 sessions |-- validation (3 months) --| 10 sessions |-- test (3 months) --|
```

Anchored on the last session, stepping back 3 months; embargo 10 sessions (≥ the holding limit); about 45 folds.
L ∈ {3, 5, 10} years and the expected-return threshold ∈ {0, 0.02%, 0.05%, 0.10%} are selected by the validation total
return of the quarter (ties: shorter L, higher threshold). Test: refit on the L years ending at the validation end,
evaluated once.

## 10. Model and decision policy (proposal, never formally agreed)

One LightGBM classifier per distance predicting P(TP first). At each eligible minute: expected net return of every distance
from P(TP) and the decision bar's close (time-limit exits counted as losses), best distance, buy if above the threshold.

## 11. Baselines (same simulator, same costs)

1. Buy-and-hold over the same span.
2. **Random entry:** 20 runs; each eligible minute buys with the model's buy rate, at a distance drawn from the model's
   chosen distances (matched activity).
3. **Fixed time:** buy at the 10:00 open every session when flat, with a 0.50% distance.

## 12. Statistics and reporting (honest reporting added 2026-10-05)

- **Every candidate chained** over the validation quarters (after the fact: optimistic for the best one), with exposure and
  the **zero-skill reference** (1 + buy-and-hold)^exposure − 1: what a strategy without skill, invested that share of the
  time, is expected to return (audit F3).
- **Prior-only path:** the setting selected at fold f − 1, with its decisions on fold f's validation quarter, together with
  the baselines of §11 on the same quarter (the information test); chained return vs buy-and-hold, quarters won with a
  one-sided sign test, mean/SD/t of the quarterly excess return and the **minimum detectable effect**, mean exposure.
  Positions can extend past a quarter's end (up to 10 sessions), so the path is summarized per quarter (no daily bootstrap).
- **Per test window** (test modes only): model and baseline metrics, the model's percentile among the random runs, cost
  sensitivity; across folds: chained returns, folds beating buy-and-hold with a sign test, Sharpe, worst drawdown, trades.
- One **summary** trial-log entry per walk-forward run records the prior-only estimate that was seen.

## 13. Stopping rules

1. **Signal check (step 02), base-rate version.**
   - Windows: training = the 10-year window of the 4th most recent fold; validation = the 4 most recent validation quarters
     pooled (all after that training window; they were test windows of older folds). The latest test window is not read.
   - Per (feature, distance): 10 quantile bins (edges from training; one bin per level for categoricals). Per bin: TP rate
     with a block-bootstrap interval (whole ISO weeks), the window's **base rate** (unconditional TP rate at that distance),
     the break-even TP rate, the number of distinct months.
   - A bin is tested if it has ≥ 200 training rows and covers ≥ 6 calendar months in training; its validation pass counts
     only if it covers ≥ 6 months in the pooled validation.
   - **Two-sided:** a bin is a signal if its interval lies entirely above (or entirely below) the base rate on training and
     on validation, on the same side. Signals above the base rate whose validation lower bound is also above break-even are
     counted separately (tradable after costs).
   - **Statistic:** the number of **distinct feature bins** with at least one signal (one bin usually passes at several
     neighbouring distances). The report also gives the training passes expected by chance (5% of the tests) and the
     signals expected by chance if the tests were independent (tests × 2 × 2.5%²; about 4 for ~3,250 tests).
   - **Null calibration:** the same check is run **19 times** with the feature columns shifted, together, by a random
     number of whole sessions (25%-75% of each window, circularly; training and validation shifted independently) against
     the unchanged outcomes. This breaks any feature → outcome link and keeps each series' own structure, the correlation
     between features and the correlation between the tests.
   - **CONTINUE only if the real check has more distinct signal bins than every null run** (p ≤ 1/20 = 0.05; ties stop);
     otherwise **STOP or pivot**.
   - *Why (found 2026-10-05):* in the assistant's smoke run on a synthetic random walk (no signal by
     construction), the uncalibrated rule ("at least one signal") found 2 signals (one bin of `prev_day_range_pct` at 0.89%
     and 1.00%) and returned CONTINUE. Nicolas asked for the most reasonable fix; the assistant recommended the null
     calibration and it was adopted the same day. Nicolas's first real run of step 02 (first zip, config hash `16493e598a`) still used the uncalibrated rule; the calibrated verdict comes from re-running step 02 with the second zip (hash `15716b01a3`), whose real-check part must reproduce the first run's signal table exactly. Shifting slowly varying
     features by months may leave part of a regime link in the null, which makes the rule conservative.
2. **Walk-forward (step 03).** On validation: STOP if the prior-only path fails to beat buy-and-hold and the random-entry
   baseline. On test (after freezing): the success definition of §2.
3. **Multivariate signal check (step 04, diagnostic, added 2026-10-06 by Nicolas after exp01's results).**
   *Status.* exp01 is STOPPED (step 02: 2 distinct signal bins vs a null maximum of 4, p = 0.10). This check was added **after**
   the results were known. It can help explain the failure; **it cannot reverse the STOP or restart the walk-forward**,
   whatever its outcome. Pre-registered (protocol, config, code, tests and output-free notebook committed) before the run on
   real data; budget **1 trial**, one run.
   - *Question.* (a) Does the **combination** of the 33 features predict TP-first better than the base rate, out of sample,
     beyond chance and beyond what the model's flexibility produces on unrelated features? (b) If so, does the edge clear
     break-even after costs? Step 02 tested each feature bin alone; a model can use interactions (A high **and** B high)
     that no single bin shows.
   - *Windows and data (identical to step 02).* Fold schedule `get_fold_pdf(..., [10])`; the 4 most recent validation
     quarters pooled (folds 41-44, 2025-05-01 → 2026-04-29); training = the 10-year window of fold 41 (2015-04-16 →
     2025-04-15); 15-minute interval sampling; the 33 model features (absolute features excluded); the 21 distances of step
     02. Rows are read with step 02's code (`read_model_dataset_pdf`, duplicates dropped). The notebook asserts that the
     windows equal those logged by the step 02 entry (hash `15716b01a3`). Raw bars (for uniqueness weights) are read with
     `get_complete_ohlcv_pdf(cutoff_date_str_in = last validation date)`; `check_last_date_bool` raises if any row, bar or
     the last date is dated after the last validation date or on/after 2026-05-14 (the untouched window is never read).
   - *Model (exactly exp01's, `walk_forward.py`, unchanged).* `fit_tp_model_dict` / `predict_tp_proba_pdf`,
     `LGBM_PARAM_DICT`, uniqueness weights, one classifier per distance, fit on training only, `random_state` =
     `RANDOM_SEED`. The only addition: `n_jobs = MULTIVARIATE_CHECK_LGBM_THREAD_COUNT = 1` for the real and every null
     model (a computational setting so that the 19 null runs can run in parallel processes; a test checks parallel =
     sequential).
   - *Measures per distance (resolved validation rows, i.e. rows with a TP or not-TP label).* AUC of the predicted P(TP);
     top decile = the 10% of rows with the highest P(TP) (`max(1, round(0.1 n))`, stable sort); its TP rate, its **lift**
     over the window's base rate and the **mean break-even TP rate** of those rows (`get_breakeven_tp_rate_arr`, costs of
     `so/config.py`). 95% intervals by week-block bootstrap (whole ISO weeks, `BOOTSTRAP_ITERATION_COUNT` = 1,000,
     `RANDOM_SEED`; the same weight draws as `so.core.signal_bins`), because minute-level labels overlap.
   - *Primary statistic.* The **mean AUC over the 21 distances**.
   - *Null (calibration of flexibility and chance).* The step 02 shift `get_session_shifted_feature_pdf`: feature columns
     shifted together by a random number of whole sessions (25-75% of each window, circularly; training and validation
     shifted independently) against the unchanged labels, then the models are **retrained** on the shifted training rows
     and the same mean AUC is computed on the shifted validation rows. **19 runs**, seeds `default_rng([RANDOM_SEED,
     run_id])`, run_id 0-18 (deterministic). No bootstrap in the null runs.
   - *Verdict.* **INFORMATION only if the real mean AUC is strictly above every null run** (a tie means no information);
     p = (1 + #{null ≥ real}) / 20.
   - *Outcomes.* **A**: no information. **B**: information, but at no distance is the top decile's TP-rate 95% lower bound
     above that decile's mean break-even TP rate (a statistical edge that does not pay the costs). **C**: information and
     at least one distance clears break-even. Outcome C is recorded as a **candidate pending review**; the decision to look
     at the untouched window is parked for Nicolas, and **no trading experiment is built** from it in this session.
   - *Descriptive reports (not part of the verdict).* AUC and lift per distance, real vs the null runs; split-gain
     importance (mean share of total gain over the 21 models, top 10: what the models used, not evidence of information);
     calibration table by decile of predicted P(TP) (deciles per distance, pooled over distances).
   - *Trial log.* **One** entry, stage `multivariate_check`: setting = windows, features, distances, model parameters, null
     settings; metric = real mean AUC, the 19 null mean AUCs, p, verdict, per-distance summaries.
   - *Planted-interaction test (`tests/test_exp01_step04.py`).* Synthetic rows where P(TP) = 0.45 + c when features A and
     B are both in their top quarter, lowered when exactly one of them is (compensated so that each feature alone has
     almost no marginal effect: TP rate 0.45 in its top 25%, about 0.42 below), c = 0.40. The multivariate check must
     find information (outcome C) while step 02's univariate check on the same data stops; both results are printed. Pure
     noise must give outcome A; the null shift must keep labels and feature rows intact; parallel = sequential; the
     untouched assertion must raise on a row dated 2026-05-14. The compensation is deliberate: without it, a one-sided
     raise leaks into each feature's marginal and step 02 also finds it, so the test would not show what only the
     multivariate check can see.
   - *Conservative choices.* Windows reused exactly from step 02 (no new window can be picked after seeing results); ties
     count as no information; one primary statistic (mean AUC over all 21 distances, no best distance); the same fixed
     model (no tuning); the break-even comparison uses the lower bound of the interval.
   - *Rejected alternative.* Searching feature pairs or triples one by one (33 features → 528 pairs, × bins × 21
     distances = hundreds of thousands of tests, more with triples) is rejected: the multiple-testing burden would swamp
     any real effect and invite selection after the fact. A single model with a single null-calibrated statistic tests
     all interactions at once in **one** trial.
   - *Limitations.* The validation quarters are reused development data (they were seen in step 02 and as test windows
     of older folds); the motivation is data-dependent (added because exp01 failed); a single 10-year training window
     (no walk-forward); minute-level labels overlap (handled by the week-block bootstrap, but neighbouring weeks are still
     correlated); shifting slowly varying features by months may leave part of a regime link in the null (conservative);
     a positive verdict would be one diagnostic after about 7,400 earlier trials (3,292 in this workspace's trial log plus
     4,089 legacy trials), not a strategy.

## 14. Discipline against luck and leakage

- Shared trial log; experiment `exp01_minute_entry`; hash covers `so/config.py` + this `config.py`.
- `validation_only` until the design is frozen; any change after the first validation run = new version.
- Look-ahead tests (`tests/test_shared_and_exp01.py`): context features identical on truncated data; target cells equal
  simulated trades; embargo gaps; snapshot k contains bars 0..k only; drift-only data is not a signal; month minimum; the null shift keeps outcomes and
  feature rows, a planted signal beats every null run, noise stops, ties stop.

## 15. Implementation

| Step / file | Content |
|---|---|
| `config.py` | Every exp01 constant |
| `model_dataset.py`, `step01_model_dataset.ipynb` | Join of pipeline features and targets per day → `step01_model_dataset_data/` |
| `signal_check.py`, `step02_signal_check.ipynb` | Base-rate signal check → `step02_signal_check_data/` |
| `walk_forward.py`, `step03_walk_forward.ipynb` | Model, policy, fold runner, baselines, prior-only path, test → `step03_walk_forward_data/` |
| `multivariate_check.py`, `step04_multivariate_check.ipynb` | Diagnostic multivariate signal check (§13.3, protocol 1.1) → `step04_multivariate_check_data/` |

## 16. Known limitations

Dividends ignored; costs informal; break-even assumes exits at the barriers; per-share fee in labels assumes ≥ 200 shares
(the simulator uses exact fees); SL/TP rounded to $0.001 while prices move in $0.01; absolute features excluded; the
price-action constants were chosen visually; the 3% bad tick rule leaves smaller wicks that can trigger small SL distances;
ex-dividend overnight drops trigger small SL distances on overnight holds.

## 17. Change log

| Version | Date | Change |
|---|---|---|
| (v1 1 – 1.2) | 2026-10-01 → 10-04 | Protocol v1 (`signal_check_v1`, `lgbm_ev_policy_v1`, `*_clean`): see `docs/history/RESEARCH_PROTOCOL_v1.md` |
| 1.0 | 2026-10-05 | Re-run in the reorganized workspace as `exp01_minute_entry`. Trading rules, targets, features, model, policy, schedule and selection unchanged. Changed (decided by Nicolas, 2026-10-05): the signal check compares bins with the window's **base rate** instead of the break-even rate, is two-sided, pools the 4 most recent validation quarters (training = the 10-year window of the first pooled fold) and requires ≥ 6 months per bin in each window; the verdict counts distinct signal bins and must beat 19 session-shifted null runs (adopted 2026-10-05 after a synthetic random walk passed the uncalibrated rule; the first real run of step 02 used the uncalibrated rule and step 02 is re-run once with the null); secondary criterion = Sharpe **or** drawdown; honest reporting of §12 (prior-only path with baselines on validation, exposure and the zero-skill reference, MDE, summary trial entry) |
| 1.1 | 2026-10-06 | Added (decided by Nicolas, 2026-10-06, **after** exp01's results were known; data-dependent motivation): the diagnostic multivariate signal check of step 04 (§13.3; `multivariate_check.py`, `step04_multivariate_check.ipynb`, `MULTIVARIATE_CHECK_*` constants, `tests/test_exp01_step04.py`). No existing rule, constant, function or notebook of exp01 changed; `EXPERIMENT_NAME` unchanged. The config hash changes only because constants were **added** (step 04 runs under the new hash); steps 01-03 stay recorded under `16493e598a` (step 02, first run) / `15716b01a3` (steps 01-03). exp01 stays STOPPED whatever step 04 finds. |
