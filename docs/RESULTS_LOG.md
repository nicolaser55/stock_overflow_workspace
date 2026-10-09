# Stock Overflow: Results Log

*The chronological record of experiment outcomes of the reorganized workspace (from 2026-10-05), for the thesis. Each entry
states what was run, under which protocol version and configuration hash, what was observed, and what the evidence does and
does not support. Failures are results. Test windows touched so far: **none** (as of 2026-10-09).*

*Earlier results (v1, v2, the step 13 exploration, the bad tick correction and the audit) are in
`docs/history/RESULTS_LOG_2026-10-05.md`; their 4,089 trials are in `records/legacy/trial_log_legacy_20261005.csv` and
still count.*

## How to add an entry

For every notebook run: date, experiment and step, protocol version, config hash (printed in the header cell), the trial-log
entries added (stage and count), the headline numbers (copy them from the saved outputs), and what they support. For
walk-forward runs, always report: the best candidate after the fact (labelled optimistic), the **prior-only path** with its
minimum detectable effect, the **information test** (model vs its uninformed baselines), and time in the market.

## Summary

| Experiment | Protocol | Status | One-line outcome |
|---|---|---|---|
| `exp01_minute_entry` | 1.0 (1.1: step 04) | **STOP** (2026-10-06) | Signal check: 2 signal bins vs null max 4, p = 0.10 → STOP. Walk-forward (run before the verdict): prior-only +146.94% vs buy-and-hold +218.48%. Step 04 diagnostic (multivariate, added after the results): mean AUC 0.4943 vs null max 0.5282, p = 0.75, no information (Outcome A) |
| `exp02_stop_reentry` | 1.0 | **STOP** (2026-10-05) | 0 signals; prior-only +111.66% vs +237.21%; the model's re-entry is worse than all 20 random re-entry runs |
| `exp03_ath_exit` | 1.0 | **STOP** (2026-10-05) | Prior-only +143.05% vs +237.21%; beats random exits (19/20) but loses to random buy-backs (19/20 beat it) |
| `exp04_trend_exit` | 1.0 | **STOP** (2026-10-06) | Continuous replay: prior-only +70.84% vs +229.74%; all 12 exits bought back higher; beats 0/20 random exits and 4/20 random re-entries |
| `exp05_vol_scaled_exposure` | 1.0 | **STOP** (2026-10-06) | Signal check passes (ρ 0.593); prior-only +165.69% vs +229.74% (mean weight 86.3%); constant exposure +198.52%, beats 3/20 random shifts; drawdown −23.20% vs −34.21% |
| `exp06_capped_regret_reentry` | 1.0 | **STOP** (2026-10-06) | Data-dependent follow-up of exp03. Prior-only +147.38% vs +229.74%; information test passed (beats 19/20 random exits, 15/20 random re-entries) but 37 of 45 exits ended on the buy-stop |
| `exp07_warning_lights_exit` | 1.0 | **STOP** (2026-10-06) | Exploration: k = 5 +136.41% vs +69.02% (one 2008 exit). Validation: every k loses (best k = 4 +115.60% vs +235.39%); prior-only +49.09% vs +229.74%, all 12 exits bought back higher; beats 0/20 random exits, 7/20 random re-entries |
| `exp08_vix_signal_check` | 1.0 | **DONE, VIX line STOP** (2026-10-09) | Gate: G1 0 signal bins (null max 0, p = 1.00); G2 dAUC +0.0359 vs null max +0.0563 (p = 0.15); G3 PASS (D +0.1165 [+0.0441, +0.2227]); G4 FAIL (top VIX quintile mean forward return +1.91% / +2.82%). No gate opens: exp09-exp11 skipped |
| `exp09_vix_reentry`, `exp10_vix_vol_scaled_exposure`, `exp11_vix_model_exit` | — | **SKIPPED** (2026-10-09) | Not run, by exp08's pre-registered gates (exp09 needs G1 or G2, exp10 G3 and G4, exp11 G2) |

*Corrections 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`), for the rows above:*
- *exp05 (I3): "constant exposure +198.52%" is not a constant exposure: with the 20-point dead band it never rebalanced,
  so it is "**buy 86.3% and hold**" (mean weight 90.9%). The verdict rests on buy-and-hold and the random shifts (the
  path beats 3/20).*
- *exp06 (I2): "information test passed" holds as the protocol defined it (beat both medians), but beating 19/20 random
  exits (empirical p ≈ (1 + 1) / 21 ≈ 0.10) and 15/20 random re-entries (p ≈ 0.29) is "consistent with weak timing
  information; not statistically supported" (data-dependent design, 12 candidates, about 7,400 trials).*
- *exp07 (I4): "all 12 exits bought back higher" = 11 closed episodes, all bought back higher, plus 1 episode open at
  the end (valued at the last close, also higher).*

## Reproduction checks for the re-run

The trading rules of exp01 and exp02 and the exp03 exploration rules are unchanged, and every run is deterministic, so the
re-run must reproduce these earlier numbers (corrected data). A difference means something changed in the data or the code.

| Notebook | Expected | Nicolas's run (2026-10-05/06) |
|---|---|---|
| exp02 step01 | buy-and-hold 2005-2014 +69.02% (Sharpe 0.36, drawdown −56.44%); k = 4 with a 5-day delay +62.91%; 200-session rule +50.39% | reproduced |
| exp02 step03 | 18 candidates from +53.8% to +229.7% vs +243.4% chained buy-and-hold; mean AUC logistic 0.523 (10y) / 0.470 (all); prior-only path +111.66% vs +237.21%, 20 of 43 quarters | reproduced |
| exp02 step02 | 0 signals (the verdict cannot change with the month minimum: no bin passed training in v2) | reproduced |
| exp03 step01 | buy-and-hold +69.02%; 5 of 15 rules above it; best: within 0.5%, 5% dip, +80.69% (+11.68 pts) | reproduced |
| exp01 step03 | validation candidates identical to `lgbm_ev_policy_v1_clean` (best setting +158% vs +230%; at most 16 of 45 quarters) | reproduced (+158.08% vs +230.36%; at most 16 of 45) |
| exp01 step02 | new result (base-rate check); the old break-even check found 1,339 training passes and 0 signals | new result, below; the first run (hash `16493e598a`) and the re-run show the same real-check counts (5,628 / 174 / 4; confirmed by the agent on 2026-10-06 from commit `da790c1`) |
| exp03 step02 | first official run; the assistant's sandbox run gave +143.05% | identical (+143.05%) |

*SPY raw folder rename check (agent, 2026-10-09; roadmap 2026-10-09 step 0.3; no trial-log entry).* The SPY raw folder
is `store01_rawzone/ibkr_spy_1min/` (`so.paths` on `main`, verified at `a4418d8`; `so/paths.py` last changed in
`1bbb0de`).
`scripts/check_spy_rename.py` (run once, branch `agent/research`) reads it through `so.core.raw_data`, collects the
session dates, then cuts the bars at 2026-04-15 before any computation. Console output: (a) 5,436 sessions,
2005-01-03 → 2026-08-13; (b) buy-and-hold 2005-2014 **+69.02%**, 200-session rule **+50.39%**; (c) exp04 x = 0, n = 1
continuous replay 2015-04-17 → 2026-04-15 **+108.03% with 35 exits**, buy-and-hold **+235.39%**: "RENAME CHECK: PASSED
(6 of 6 checks)", every value equal to the earlier records at 2 decimals of a percent. The repository search for
`ibkr_ohlcv_data` / `ibkr_SPY_ohlcv_data` finds, besides the dated note of `docs/RERUN_GUIDE_2026-10-05.md` and files of
`docs/history/`, only `records/bad_tick_corrections.csv`, whose `backup_path` column records the backup folder created on
2026-10-04 under the old name: a dated record of a past action, left unchanged (no code reads it).

*Verification run by the assistant (2026-10-05).* To test the reorganized code, the assistant executed pipeline steps 00
and 06 and the notebooks of exp02 (steps 01-03) and exp03 (steps 01-02) once, in its sandbox, on a copy of the same
corrected raw data. The exp02 and exp03 exploration numbers above were reproduced exactly. That run also produced the first
exp03 walk-forward and the new validation baselines, so those results were seen by the assistant before Nicolas's official
run; no rule, grid or baseline was changed afterwards. exp01 was smoke-tested on synthetic data only (a 2010-2022 random
walk with random indicator columns, so no real result was seen). That smoke test showed that the exp01 base-rate signal
check, with the uncalibrated rule, returns CONTINUE on data without any signal (2 signals in one bin of 3,255 tests, about
4 expected by chance). The verdict was therefore calibrated on 19 session-shifted null runs
(`experiments/exp01_minute_entry/PROTOCOL.md` §13; decided 2026-10-05, delivered in the second zip of that day).
Nicolas's first real run of step 02 (first zip, config hash `16493e598a`) still used the uncalibrated rule; the calibrated verdict comes from re-running step 02 with the second zip (hash `15716b01a3`), whose real-check part must reproduce the first run's signal table exactly. On the same synthetic data, the null runs found 0-4 distinct signal
bins (15 of 19 runs found at least one), so the real check's 1 bin gives p = 0.80 and the calibrated verdict is STOP, as
it should be. Run time in the sandbox (2 cores): real check 2.0 min, null runs 13.9 min.

## Decisions of 2026-10-05

Taken by Nicolas on 2026-10-05, in reply to the open points of the reorganization, and delivered in the second zip of
that day. Nicolas ran exp01-exp03 with the **first** zip, so those executed notebooks predate the code of these decisions:
the exp02 and exp03 notebooks print both secondary flags (the "either" criterion is read from them; no re-run), and the
exp01 signal check is re-run once to add the null runs (`docs/UPDATE_GUIDE_2026-10-06.md`).

| Decision | Applies to | Why |
|---|---|---|
| The exp01 signal-check verdict is calibrated on 19 session-shifted null runs: CONTINUE only if the real check has more distinct signal bins than every null run | exp01 step 02 | The uncalibrated rule ("at least one signal") passed a synthetic random walk; Nicolas asked for the most reasonable fix, the assistant recommended this one |
| The random exit and 200-session trend baselines are kept | exp03 | Random exit tests the ATH exit signal itself; the trend rule is context only |
| Secondary criterion: higher Sharpe **or** smaller drawdown (either is enough), at a comparable return | all experiments (`so/core/evaluation.py`) | Audit F7 left "and" or "or" open; Nicolas chose "or" |

## Decisions of 2026-10-06

| Decision | Applies to |
|---|---|
| exp01, exp02 and exp03 are stopped under their protocols (results below). No test window is evaluated for them. | exp01-exp03 |
| Next family: "stay invested, exit rarely": strategies that maximize time in the market and exit only on strong evidence, with explicit re-entry rules, on the features that already exist; VIX afterwards, text/qualitative data last | `docs/RESEARCH_STATE_2026-10-06.md` |
| **Primary success criterion of the next family: beat buy-and-hold's total return** (after costs, on the prior-only path; on the test windows once frozen). Nicolas, 2026-10-06 | all new experiments |
| Experiment numbering: the VIX experiment, earlier planned as exp04, moves after the new family | `experiments/README.md` |
| The research continues with a Cursor agent on nicodesktop, under `AGENTS.md` and `.cursor/rules/` | workflow |

## exp01_minute_entry

**Protocol 1.0. Status: STOP at the signal check.**

*Step 01, model dataset* (2026-10-05, hash `16493e598a`). 5,436 daily files (2005-01-03 → 2026-08-13), 33 model
features (absolute-dollar features excluded).

*Step 02, signal check.* First run 2026-10-05 15:17 (hash `16493e598a`, uncalibrated rule: it would have printed
CONTINUE because 4 signals > 0). Re-run with the null calibration 2026-10-06 12:46 (hash `15716b01a3`); both entries are
in the trial log.
- Windows: training 2015-04-16 → 2025-04-15 (60,144 sampled rows); validation = folds 41-44 pooled
  (2025-05-01 → 2026-04-29, 5,964 rows). The latest test window (2026-05-14 → 2026-08-13) was not read.
- Base rates (training): TP-first rate 49.8% at 0.10% rising to 53.3% at 0.50%, then falling to 50.8% at 1.00%; the
  small tilt above 50% is SPY's drift.
- 5,628 tests (33 features × 21 distances × bins); 174 training passes (281 expected by chance at 5%); **4 signals in
  2 distinct bins** (7.0 expected if tests were independent):
  - `intraday_return_pct` in (0.37%, 0.64%], distances 0.13%-0.16%: TP rate 52.9-54.2% vs base 50.1-50.6% on training,
    validation lift +8.6 to +10.1 points (2 of the 3 also above break-even on validation);
  - `prev_day_range_pct` in (1.52%, 2.08%], distance 0.18%: below the base rate (48.9% vs 50.8% on training; validation
    lift −7.3 points).
- **Null calibration:** 19 session-shifted runs found `[1, 0, 0, 1, 0, 1, 1, 1, 0, 4, 0, 0, 1, 1, 0, 1, 1, 0, 1]` distinct
  signal bins (10 of 19 runs ≥ 1). The real 2 bins do not exceed the null maximum of 4: **p = 0.10 → STOP.**
- Reading: the two bins are suggestive (intraday momentum on very tight brackets; fewer TP hits after wide-range days)
  but not established. The validation lift is about three times the training lift, a typical sign of noise in small
  samples (about 600 overlapping rows per validation bin).
- *Reproduction confirmed (agent, 2026-10-06; research state open item 1, closed).* The first run's executed notebook
  (commit `da790c1`, message `first-run-20261006`; there is no git tag of that name, the label is the commit message),
  cell 6 output: `test_count 5628`, `train_pass_count 174`, `signal_count 4`, `signal_bin_count 2`, signal features
  `['intraday_return_pct', 'prev_day_range_pct']`, distances `[0.0013, 0.0014, 0.0016, 0.0018]`, verdict `CONTINUE`
  (uncalibrated rule). The re-run (hash `15716b01a3`, cell 7) prints the same seven values, then the null calibration
  and `STOP`. The two `signal_check` entries of the trial log (2026-10-05T15:17:38 `16493e598a` and 2026-10-06T12:46:46
  `15716b01a3`) hold the same counts. The real-check part is reproduced; the verdict STOP stands. No trial added.

*Step 03, walk-forward* (2026-10-05, hash `16493e598a`; run before the step 02 verdict existed, as the re-run guide ran
every notebook in order: these results are reported as **run past the stopping rule**). 45 folds × 12 candidates = 540
validation trials + 1 summary.
- After the fact (optimistic): best setting 3 years / threshold 0.05%, +158.08% vs +230.36%; no setting beats
  buy-and-hold; at most 16 of 45 quarters won.
- **Prior-only path (44 quarters): +146.94% vs buy-and-hold +218.48%** (8.6%/yr vs 11.1%/yr); 15 of 44 quarters won
  (sign test p = 0.989); mean excess −0.56% per quarter (SD 3.38%, t = −1.11); minimum detectable effect 1.43% per quarter
  (about 5.7% per year).
- Exposure 88.1%; zero-skill reference at that exposure +177.41%. Random entries of matched activity (median of 20)
  +124.55%; the model beats 16 of 20 runs (empirical p ≈ 0.24); fixed 10:00 entry +18.87%.
- Reading: the stop/target machinery with costs loses about 50 points against passive exposure; the model recovers about
  22 of them. Not evidence of an edge over buy-and-hold.

*Step 04, multivariate signal check (diagnostic; protocol 1.1, §13.3; decided by Nicolas 2026-10-06 after exp01's
results).* **exp01 stays STOPPED**: this check was added after the results were known and cannot reverse the STOP or
restart the walk-forward. Pre-registration commit `ae15c20` (2026-10-06 18:21:47 +0300); run once, 2026-10-06 (agent,
nbconvert in the background), config hash `1ea6cfdc0a`; **1 trial added** (stage `multivariate_check`, trial
`20261006182748398278_1ea6cfdc0a`, logged 2026-10-06T18:27:48; trial log 3,292 → 3,293). Source of every number below:
the saved outputs of `experiments/exp01_minute_entry/step04_multivariate_check.ipynb` and the CSV files of
`store04_experiments/exp01_minute_entry/step04_multivariate_check_data/`.
- Windows (asserted identical to the step 02 entry `20261006124646690847_15716b01a3`): training 2015-04-16 → 2025-04-15
  (60,144 rows), validation folds 41-44 pooled 2025-05-01 → 2026-04-29 (5,964 rows). Last row and last bar loaded:
  2026-04-29; the untouched window (from 2026-05-14) was not read. 33 features, 21 distances (0.10%-1.00%), exp01's
  LightGBM (`LGBM_PARAM_DICT`, uniqueness weights, `n_jobs` = 1), one classifier per distance, trained on training only.
- **Primary statistic: mean AUC over the 21 distances = 0.4943.** The 19 null runs (features shifted by whole sessions,
  models retrained): `[0.5050, 0.4960, 0.4876, 0.4959, 0.5058, 0.5259, 0.4989, 0.5049, 0.5047, 0.4869, 0.5282, 0.4851,
  0.5215, 0.5151, 0.5014, 0.5045, 0.4867, 0.4946, 0.4694]` (max 0.5282). 14 of 19 null runs are ≥ the real value:
  **p = (1 + 14) / 20 = 0.75 → no information → Outcome A.** No distance clears break-even (the top-decile lower bound is
  below the top decile's mean break-even TP rate at all 21 distances), so outcome B or C would not have applied either.
- Per distance (descriptive; not part of the verdict and **chosen after the fact** when singled out):
  - Small distances 0.10%-0.14%: AUC 0.516-0.535, above all 19 null runs at each of these 4 distances; top-decile lift
    +1.9 to +6.6 points. The best (optimistic) one, 0.14%: AUC 0.5346 [0.5073, 0.5620], top-decile TP rate 56.7%
    [49.2%, 64.2%] vs a mean break-even of 51.4% (point estimate above break-even, lower bound below: does not clear).
  - 0.16%-0.25%: AUC 0.515-0.520, inside the null range (1-6 null runs ≥ real); no top-decile lower bound above 50%.
  - 0.28%-0.71%: AUC 0.469-0.516, inside the null range.
  - Large distances 0.79%-1.00%: AUC 0.437, 0.428, 0.406, **below all 19 null runs**; the top decile hits TP 36.6%,
    32.1%, 31.2% vs base rates 47.4%, 47.0%, 47.6% (lift −10.9 to −16.4 points; at 0.89% and 1.00% the whole 95% interval
    of the lift is below zero). The models trained on 2015-2025 rank validation rows **in the wrong order** there.
  - 11 of 21 distances have AUC > 0.5; mean top-decile lift −1.4 points (null runs: −4.1 to +6.2).
- Calibration (deciles of predicted P(TP), per distance, pooled over the 21 distances): mean predicted P(TP) rises from
  41.6% (decile 1) to 59.7% (decile 10), the observed TP rate stays flat between 48.2% and 50.8% and is **lowest in the
  top decile** (48.2%). The predicted spread of about 18 points is not realized at all.
- Split-gain importance (mean share of total gain over the 21 models, top 10; descriptive, what the models used):
  `prev_day_return_pct` 9.4%, `overnight_gap_pct` 9.1%, `prev_day_range_pct` 8.2%, `daily_volatility` 8.1%,
  `intraday_return_pct` 7.4%, `ath_drawdown_pct` 7.1%, `prev_day_high_dist_pct` 6.1%, `prev_day_low_dist_pct` 5.4%,
  `prev_seg_delta_pct` 3.9%, `day_of_week` 3.5%. Eight of the ten are daily context features (constant or slowly varying
  within a session).
- *Mathematically.* For each distance d the AUC is P(p̂(x_i) > p̂(x_j) | y_i = TP, y_j = not TP) on the validation rows
  (0.5 = ranking no better than a coin). The statistic is A = (1/21) Σ_d AUC_d. Under the null hypothesis "the features
  carry no information about which barrier is hit first", shifting the feature rows by whole sessions against the labels
  gives exchangeable copies of A that include the model's flexibility and the overlap of minute labels; the real
  A = 0.4943 ranks 15th of 20 (p = 0.75), so the null is not rejected. The rejection rule would have needed A > 0.5282.
  The calibration table shows that the model's probabilities have a spread (standard deviation of the 10 decile means of p̂ = 4.95
  points, computed by the agent from `calibration_data.csv`) that the outcomes do not follow (standard deviation of the
  10 observed TP rates = 0.92 points), i.e. the in-sample relation does not transfer.
- *In plain words.* Giving the model all 33 features at once, so that it can combine them ("A high **and** B high"),
  does not help: on the validation year it ranks future TP-first outcomes no better than models trained on features
  deliberately misaligned in time (it does worse than 14 of those 19). There is a faint ordering at the very tightest
  brackets (0.10%-0.14%), too small to pay the costs, and a clear **reversal** at the widest brackets (what predicted a
  TP hit in 2015-2025 predicted the opposite in 2025-2026). The models lean mostly on day-level context (yesterday's
  return and range, the overnight gap, volatility), so they learn about one value per day; ten years give only about
  2,500 such values, and the day-level regimes they found did not persist.
- **What it supports:** the step 02 STOP was not caused by testing features one at a time; the combination of the 33
  features carries no out-of-sample information on TP-first beyond chance and flexibility, under exp01's model, on these
  windows. The exp01 failure is consistent with "no exploitable signal in these features at minute horizons" rather
  than with "a signal the univariate check could not see".
- **What it does not support:** it does not show that no model or feature set could work (one model, fixed
  hyperparameters, one 10-year training window, no walk-forward); the small-distance AUCs above the null and the
  large-distance reversal are per-distance observations chosen after the fact among 21 (both tails), on reused
  validation quarters, and are not evidence of anything without a new pre-registered test; the reversal is an inference
  about non-stationarity, not tested. The motivation of the check is data-dependent; the conclusion rests on 1 trial of
  this check after 3,292 earlier workspace trials and 4,089 legacy trials.
- Status: **diagnostic complete, Outcome A; exp01 remains STOPPED.** No parked decision (no outcome C).

## exp02_stop_reentry

**Protocol 1.0. Status: STOP.** Run 2026-10-05 14:47-14:50, hash `53a86cd30f` (14 exploration, 1 signal-check, 792
validation and 1 summary trials).
- Step 01 (2005-2014): reproduced (above). Selling at S and buying back at R gives S/R times the shares: the next-day
  buy-back bought back lower in 41% of 150 episodes (k = 4), mean share gain −0.21%; the hindsight oracle +4.79%.
- Step 02: 0 of 80 tests pass even on training (4.0 expected by chance) → STOP.
- Step 03, **prior-only path (43 quarters): +111.66% vs +237.21%** (7.2%/yr vs 12.0%/yr); 20 of 43 quarters won
  (p = 0.729); mean excess −1.13% per quarter (SD 4.20%, t = −1.76); MDE 1.79% per quarter (about 7.2% per year); time in
  cash 21.2%. Comparable return, Sharpe and drawdown flags all False (secondary criterion not met under "and" or "or").
- Baselines on the same quarters: stop + next-day buy-back +245.34%, + 5-day +240.45%, + 20-day +152.14%; random
  re-entry (median of 20) +159.63% — **the model beats none of the 20 random runs**; 200-session trend +106.16%.
- Reading: the stop itself costs little (stop + next-day buy-back ≈ buy-and-hold); the losses come from waiting in cash,
  and the model's waiting is worse than random (consistent with a mean validation AUC of 0.470 for the all-history window).

## exp03_ath_exit

**Protocol 1.0. Status: STOP.** Run 2026-10-05 14:55-14:56, hash `b8523207d1` (15 exploration, 660 validation and 1
summary trials).
- Step 01 (2005-2014): reproduced (above). Forward returns after near-ATH days are lower than after all days at 1-20
  sessions (e.g. 20 sessions within 0.5%: −0.02% vs +0.43% log return) but every 95% interval includes 0, and they are not
  negative enough: by the S/R identity, selling pays only if prices fall.
- Step 02, after the fact: all 15 rules lose to buy-and-hold over the 44 validation quarters (best: within 0.5%, 20-day
  delay, +216.86% vs +243.38%). No rule exits from early 2022 to late 2023 (SPY below its high).
- **Prior-only path (43 quarters): +143.05% vs +237.21%** (8.6%/yr vs 12.0%/yr); 14 of 43 quarters won (p = 0.993);
  mean excess −0.85% per quarter (SD 3.17%, t = −1.75); MDE 1.35% per quarter (about 5.4% per year); time in cash 38.6%;
  31 quarters with an exit. Comparable return, Sharpe and drawdown flags all False.
- Baselines: random buy-back with the same exits (median) +180.48%, the rule beats 1 of 20 runs; random exit with the same
  buy-back (median) +59.07%, the rule beats 19 of 20 runs (empirical p ≈ 0.10); 200-session trend +106.16%.
- Reading: selling near the high may carry a little timing information relative to random exits (not significant at
  5%), but the buy-back rules lose more than it brings, and the time out of the market is not paid for.

## Step 0: evaluation code for long holding periods (2026-10-06, agent; shared code, no trial)

*Implemented and tested, nothing run on real data.* `so/core/continuous_replay.py` and `so/core/fractional_exposure.py`,
tests `tests/test_continuous_replay.py` (synthetic data): a continuous replay with no exit equals buy-and-hold; one
episode carries across a period boundary and the period returns chain to the total return; the scorecard's S/R equals
the share ratio within 1 share; w = 1 equals buy-and-hold and w = 0 equals cash; the guard refuses any window ending on
or after 2026-05-14. No existing function was modified, so the exp01-exp03 reproduction checks are unaffected (all
previous suites pass). `tests/run_all_tests.py` now forces UTF-8 output (it crashed on a cp1252 pipe before, an output
problem only).

Design choices (the conservative option, documented in each protocol that uses them):
- Replay periods: validation quarter f runs to the session before quarter f + 1 starts (the anchored schedule makes
  some quarters overlap by 1-2 sessions), so each session counts once.
- Interval: annualized log excess = 12 × mean monthly log excess, with a **circular block bootstrap of 6-month blocks**
  as the primary interval (long exits create dependence across months; longer blocks give wider, more honest intervals),
  the 1-month version printed alongside.

## exp04_trend_exit

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §11). Pre-registered in commit `preregister exp04`
(before any run); config hash `8f4c178319`. Trials: 9 exploration (2026-10-06T14:22:35), 396 validation and 1 summary
(2026-10-06T14:24:31 / 14:25:18), 406 in total against a budget of 410. Numbers below are copied from the saved
outputs of `step01_exploration.ipynb` and `step02_continuous_replay.ipynb`.

Rule: leave SPY when the close has been more than x below its 200-session average for n sessions in a row; buy back
when it is more than x above it. Grid x ∈ {0, 3, 5}%, n ∈ {1, 5, 10} (9 candidates); one continuous replay, no reset.

**Step 01, exploration 2005-01-03 → 2014-12-31 (context only, hindsight-prone).**
- Reproduction: the textbook rule (x = 0, n = 1) gives **+50.39% vs buy-and-hold +69.02%** (33 exits, 1 bought back
  lower, product of S/R 0.8921), matching the exp02 step 01 number (+50.4% vs +69.0%).
- 7 of 9 candidates beat buy-and-hold on this decade, best x = 5%, n = 10: +116.85% (2 exits; the 2008-01-25 → 2009-07-15
  exit has S/R 1.4238, the 2011 one 0.9011). Every 95% log-excess interval includes 0 (e.g. best: +2.49%/yr,
  [−4.54%, +13.00%]). Observed: the whole gain comes from one episode, 2008, which every buffered rule sat out.

**Step 02, continuous replay over the 44 validation periods (2015-04-17 → 2026-04-15, 2,765 sessions).** Schedule
asserted identical to exp03's; bars cut at 2026-04-15 before any simulation.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). Best x = 3%, n = 1: **+131.27%**
  (7 exits, 78.2% in the market, annualized log excess −3.35%/yr [−6.81%, +0.19%]); worst x = 5%, n = 10: +51.63%.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +70.84% vs buy-and-hold +229.74%** (annualized 5.12% vs
  11.77%). 83.0% in the market, 12 exits, mean 38.3 cash decisions per episode. 18 of 43 periods won (sign test
  p = 0.889); mean period excess −1.60% (SD 3.80%, t = −2.76); MDE 1.62% per period (6.50% per year).
- Annualized log excess **−6.07%/yr**, 95% interval with 6-month blocks [−10.54%, −2.14%] (1-month blocks [−11.73%,
  −0.50%]): the loss is significant, the gain is excluded. Sharpe 0.43 vs 0.71; max drawdown −29.24% vs −34.21%
  (comparable return, Sharpe and drawdown flags all False). Costs barely matter: excess −158.69% / −158.90% / −159.13%
  at 0 / 1 / 2 cents slippage.
- Information test: random exits with the same re-entry rule (median of 20) **+164.94%**, the path beats 0 of 20; random
  re-entries after the same exits (median) **+92.67%**, the path beats 4 of 20. Both families beat the path → the
  trend signal carries no exit or re-entry information on this period; the rule is worse than chance at both ends.
- Scorecard: **0 of 12 episodes bought back lower**; product of S/R **0.5182**. Large ones: 2018-12-28 → 2019-03-21
  (S/R 0.8702, SPY +14.91% while out), 2020-03-11 → 2020-06-03 (0.8818, +13.39%), 2022-05-11 → 2023-02-02 (0.9421, 183
  sessions out, +6.14%).

*Mathematically:* each episode multiplies the share count by S/R = exit fill / re-entry fill (minus costs), and at the
end the path holds the same cash-free position as buy-and-hold, so final equity / buy-and-hold equity = Π S/R ≈ 0.518;
indeed 1.7084 / 3.2974 = 0.518. A trend filter needs at least one episode with S/R well above 1 (2008 gave 1.42-1.56)
to pay for the many small losses; 2015-2026 had no such bear market: the declines (2018, 2020, 2022, 2025) were
recovered before the average turned back, so every buy-back price was higher than the sale price.
*In plain words:* waiting for SPY to cross back over its 200-day average meant buying back after the rebound had already
happened, every time. Over 2015-2026 the rule lost about half of the shares buy-and-hold kept. The rule worked in
2005-2014 only because of 2008.

What this supports: on 2015-2026, the 200-session trend exit (with buffers and confirmation) does not beat buy-and-hold,
and its timing is worse than random. What it does not support: a statement about deep, slow bear markets (only one
in the exploration decade, none in the validation decade) or about other trend measures (not tested).

## exp05_vol_scaled_exposure

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §9). Pre-registered in commit `5305b83` (`preregister
exp05`, before any run); config hash `b1763b5981`. Trials: 1 signal check and 4 exploration (2026-10-06T14:34:52 /
14:34:54), 176 validation and 1 summary (step 02, same day), 182 in total against a budget of 185. Numbers below are
copied from the saved outputs of `step01_exploration.ipynb` and `step02_continuous_replay.ipynb`.

Rule: hold w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, σ̂ = `daily_volatility` (std of the previous 20
daily returns), σ_target = the q-quantile of every earlier σ̂ value (fixed per period); rebalance only if the target is
more than 20 points from the current weight. Grid floor ∈ {30%, 50%} × q ∈ {0.50, 0.75} (4 candidates).

**Step 01 (decisions 2005-01-03 → 2014-12-31, data cut 2015-03-18).**
- **Signal check: PASS.** Spearman correlation between σ̂ and the realized volatility of the next 20 sessions **0.593**,
  95% interval (6-month blocks) **[0.332, 0.754]**; log-log slope 0.686, R² 0.472 (2,495 decisions, 119 months).
  Volatility is predictable, as expected; the pipeline is consistent.
- Descriptive, forward 20-session log return by σ̂ quintile (lowest → highest): +0.72%, −0.35%, +0.86%, +1.32%, −0.47%
  (all decisions +0.42%); share positive 71%, 47%, 70%, 75%, 55%; SD 2.4% → 7.8%. The highest-volatility fifth has a
  slightly negative mean, but so does the second-lowest; there is no monotone pattern, and the spread of outcomes grows
  far faster than the mean falls.
- Exploration (context only, hindsight-prone): all 4 candidates above buy-and-hold (+69.02%) on 2005-2014: +89.84%,
  +107.22%, +88.58%, +97.11%; mean weight 82-90%; every log-excess interval includes 0 (e.g. floor 30%, q 0.75: +2.04%/yr
  [−1.63%, +7.63%]). As in exp04, 2008 carries the decade.
- **Defect found in a descriptive column (recorded, not fixed by a re-run):** the step 01 column
  `constant_exposure_total_return` equals buy-and-hold (+69.02%) for every candidate. Cause: the replay starts at the
  first session of the data, where no earlier decision exists, so `simulate_weight_path_dict` falls back to an initial
  weight of 1; the target (the mean weight, 0.82-0.90) is then within the 20-point band and is never traded. The column
  is invalid and was not used for any decision. Step 02 is not affected (its span starts at session > 0 and the
  constant baseline is assigned to the session before the span; its output shows the intended starting weight).

**Step 02, continuous fractional replay over the 44 validation periods (2015-04-17 → 2026-04-15).** Schedule asserted
identical to exp03's; bars cut at 2026-04-15 before any simulation.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). Best floor 50%, q 0.75: **+187.88%**
  (mean weight 93.3%, 27 rebalances, −1.38%/yr log excess [−2.77%, −0.07%]); worst floor 50%, q 0.50: +166.37%.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +165.69% vs buy-and-hold +229.74%** (annualized 9.54% vs
  11.77%). **Mean weight in SPY 86.3%**, 32 rebalances. 9 of 43 periods won (sign test p = 1.000); mean period excess
  −0.61% (SD 2.39%, t = −1.66); MDE 1.02% per period (4.07% per year).
- Annualized log excess **−1.99%/yr**, 95% interval (6-month blocks) [−4.33%, +0.08%] (1-month blocks [−4.59%, +0.81%]).
  Sharpe 0.73 vs 0.71; max drawdown **−23.20% vs −34.21%**. Comparable return False (165.69 / 229.74 = 72% of buy-and-hold's
  total return, below 90%), so the secondary flags are False by definition. Costs barely matter: excess −63.92% / −64.05% / −64.08% at
  0 / 1 / 2 cents.
- Information test: **constant exposure** started at the path's mean weight (86.3%) **+198.52%**; **random shifts** of the
  path's weights (median of 20) **+192.15%**, the path beats 3 of 20. The volatility timing is worse than holding the
  same average amount of SPY at uninformed times.
- Caveat on the constant baseline (observed): with the 20-point band it never rebalanced (0 trades after the start), so
  its SPY share drifted up as SPY rose (mean weight 90.9%, not 86.3%); it is "buy 86% and hold". A band-free constant 86.3%
  would have earned less than +198.52%. The verdict does not depend on it: the path also loses to buy-and-hold and to 17
  of 20 random shifts (mean weights 84-89%).
- *Correction 2026-10-06, after the independent audit (I3): the bullet above labelled "**constant exposure** started at
  the path's mean weight (86.3%) **+198.52%**" describes a baseline that is not a constant exposure: it is "**buy 86.3%
  and hold**" (no rebalancing, mean weight 90.9%). A band-free constant exposure would need a new version, which is not
  run. The verdict rests on buy-and-hold and the random shifts (the path beats 3/20) and is unchanged.*
- Selections: floor 50%, q 0.75 governed 28 of 44 periods, floor 50%, q 0.50 9, floor 30%, q 0.50 7.

*Mathematically:* with w_t ≤ 1 the strategy's excess over buy-and-hold is about −Σ (1 − w_t) r_t − costs. Holding less
SPY on average costs about (1 − 0.863) × 11.8% ≈ 1.6% a year in a rising market; the volatility timing had to earn that
back by having (1 − w_t) large when r_t < 0. It did not: relative to the constant-exposure path the timing cost a further
growth factor 2.6569 / 2.9852 ≈ 0.89 over 10.7 years. Volatility predicts volatility (step 01, ρ ≈ 0.59), not the sign of
the return: high-volatility stretches contain the worst and the best sessions (the rebounds of 2020 and 2025 came while
σ̂ was still high and w was at its floor).
*In plain words:* cutting SPY when the market is jumpy made the ride smoother (drawdown −23% instead of −34%) but cost
about 64 points of total return over 10.7 years, more than simply keeping 14% in cash all the time would have.
*Correction 2026-10-06, after the independent audit (I3): "relative to the constant-exposure path the timing cost a
further growth factor 2.6569 / 2.9852 ≈ 0.89" and "more than simply keeping 14% in cash all the time would have" compare
the path with a baseline that is "buy 86.3% and hold" (never rebalanced, mean weight 90.9%), not with 14% in cash all
the time. Corrected plain words: it cost about 64 points of total return over 10.7 years, more than buying 86.3% of the
account in SPY at the start and holding it (+198.52%) would have; a true constant 86.3% exposure was not run. The
comparison with uninformed timing rests on the random shifts (the path beats 3 of 20).*

What this supports: on 2015-2026, unlevered volatility scaling with this σ̂ does not beat buy-and-hold and its timing
adds no return over an uninformed exposure; it does lower the drawdown. What it does not support: anything about levered
volatility management (excluded by the project), about implied volatility (VIX, new data, parked), or about other σ̂.

## exp06_capped_regret_reentry

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §9: the primary criterion fails). **Data-dependent
follow-up of exp03** (disclosed in the protocol). Pre-registered in commit `1bac3b4` (`preregister exp06`, before any
run); config hash `5927a03c1d`. Trials: 12 exploration, 528 validation and 1 summary (2026-10-06), 541 in total against a
budget of 545. Numbers below are copied from the saved outputs of `step01_exploration.ipynb` and
`step02_continuous_replay.ipynb` and their CSV files.

Rule: exit on `trend_ma200` (close below the 200-session average) or `ath_1pct` (close within 1% of the all-time high);
buy back at once if the close reaches S × (1 + b) (buy-stop; then no exit for c decisions), or when the close is back
above the average after a close below it (recovery). Grid 2 exits × b ∈ {1, 2, 3}% × c ∈ {0, 20} (12 candidates).

**Step 01, exploration 2005-01-03 → 2014-12-31 (context only).** Buy-and-hold +69.02%. Only 1 of 12 candidates beats it
(trend, b = 2%, c = 20: +78.60%, log excess +0.55%/yr [−7.91%, +12.02%]). Every ATH candidate loses (+20.83% to
+38.59%; drawdowns about −55%, as buy-and-hold's, because the buy-stop puts it back in before 2008): their wrong-exit
share q is 0.69-0.96 and (1 − q) × G < q × |L| in all six. Observed: trend, b = 1%, c = 20 ends at −9.44% with a −66.33%
drawdown: a buy-stop re-entry followed by the 20-decision block kept it invested into the 2008 decline.

**Step 02, continuous replay over the 44 validation periods (2015-04-17 → 2026-04-15).** Schedule asserted identical to
exp03's; bars cut at 2026-04-15.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). Best ATH 1%, b = 1%, c = 20:
  **+200.12%** (70.6% in the market, 45 exits; −1.00%/yr [−4.13%, +2.18%]); worst ATH 1%, b = 1%, c = 0: +68.67% (104
  exits, 43.2% in the market). Trend candidates +101.75% to +144.80%.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +147.38% vs buy-and-hold +229.74%** (annualized 8.81% vs
  11.77%). 69.8% in the market, 45 exits, mean 18.1 cash decisions per episode. 13 of 43 periods won (sign test
  p = 0.997); mean period excess −0.79% (SD 4.25%, t = −1.21); MDE 1.81% per period (7.26% per year).
- Annualized log excess **−2.65%/yr**, 95% interval (6-month blocks) [−6.74%, +1.53%] (1-month blocks [−7.99%, +3.07%]).
  Sharpe 0.66 vs 0.71; max drawdown −28.84% vs −34.21%; comparable, Sharpe and drawdown flags all False. Excess
  −81.70% / −82.36% / −82.98% at 0 / 1 / 2 cents.
- **Information test passed** (first time in this family): random exits with the same re-entry rule (median of 20)
  +124.82%, the path beats **19 of 20**; random re-entries after the same exits (median) +103.08%, the path beats
  **15 of 20**. With 20 runs per family, 19 of 20 is an empirical p of about 0.05-0.10, before any correction for the 12
  candidates, the data-dependent design and the 6,700+ earlier trials.
  *Correction 2026-10-06, after the independent audit (I2): "19 of 20 is an empirical p of about 0.05-0.10" should
  read p ≈ (1 + 1) / 21 ≈ 0.10 (one random run of 20 beat the path); for the random re-entries, 15 of 20 is p ≈ 0.29.
  The information test as defined in the protocol (beat both medians) was met; the evidence for timing information is
  weak, before any correction for 12 candidates, the data-dependent design and about 7,400 trials.*
- Trigger arithmetic of the path (log share gains): 45 episodes, **37 ended by the buy-stop (q = 0.822)**, 8 by the
  recovery; mean gain of the right exits G = +0.0350, mean loss of the wrong ones L = −0.0153; (1 − q) × G = 0.0062 vs
  q × |L| = 0.0126 per episode. 6 of 45 bought back lower; product of S/R 0.7514. Largest right exit: 2022-04-08 →
  2022-11-30, S/R 1.0994 (162 sessions out, SPY −9.05%).
- Selections: ATH 1%, b = 1%, c = 20 governed 15 periods; trend candidates 18 of 44 in total.

*Mathematically:* final equity ÷ buy-and-hold ≈ Π S/R = 0.7514 (2.4738 ÷ 3.2974 = 0.750). In logs, Σ log(S/R) =
45 × (0.0062 − 0.0126) ≈ −0.29 = log 0.75: each wrong exit costs about b + costs (1.5%), each right one earns 3.5%, and
four of five exits were wrong. The buy-stop did its job (it capped every wrong exit near b); what it cannot do is make
right exits frequent enough.
*In plain words:* the rule sells too often for the few times it is right. Its timing is better than chance with the same
activity (it beats random exits and random buy-backs), so the signals are not pure noise, but on 2015-2026 the gains of
the good exits were about half the costs of the bad ones, and the path ended 82 points behind buy-and-hold.
*Correction 2026-10-06, after the independent audit (I2): "Its timing is better than chance with the same activity (it
beats random exits and random buy-backs), so the signals are not pure noise" overstates the evidence. Beating 19 of 20
random exits is an empirical p ≈ (1 + 1) / 21 ≈ 0.10 and beating 15 of 20 random re-entries is p ≈ 0.29, for a
data-dependent design with 12 candidates, after about 7,400 trials. Corrected wording: the timing is "consistent with
weak timing information; not statistically supported". The protocol's information test (beat both medians) was met as
defined.*

What this supports: an exit signal plus a buy-stop carries some timing information over random timing on this span, but
not enough to beat buy-and-hold after its wrong exits. What it does not support: that this information would survive a
correction for the selection (data-dependent design, 12 candidates, 6,700+ trials) or appear on new data.
*Correction 2026-10-06, after the independent audit (I2): "an exit signal plus a buy-stop carries some timing
information over random timing on this span" should read: the result is "consistent with weak timing information; not
statistically supported" (p ≈ 0.10 against random exits, p ≈ 0.29 against random re-entries, data-dependent design,
12 candidates, about 7,400 trials). What it supports is only that the path met the protocol's information test (it beat
the median of both random families) while failing the primary criterion.*

## exp07_warning_lights_exit

**Protocol 1.0. Status: STOP** (stopping rule of PROTOCOL.md §9: the primary criterion and the information test fail).
Pre-registered in commit `f93e77e` (`preregister exp07`, before any run; config, rules and tests in `30c8c96`); config
hash `2965fad3e3`. Trials: 3 exploration, 132 validation and 1 summary (2026-10-06), 136 in total against a budget of
140. Numbers below are copied from the saved outputs of `step01_exploration.ipynb` and `step02_continuous_replay.ipynb`.

*Correction 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`, I1): the line above
says "config, rules and tests in `30c8c96`" without stating that this design commit fixed a **deviation from the
roadmap**: the re-entry rule (below) dropped the roadmap's "or by exp06's buy-stop" option. The commit message of
`30c8c96` says "before reading exp06 step02 outputs"; this cannot be verified: the commit (14:49:13) came 51 s after
exp06 step 02 logged its summary in the trial log (14:48:22), and exp07's protocol motivation cites exp06's result
("wrong four times out of five"). The re-entry choice is therefore **possibly informed by exp06's results (cannot be
verified)**; the direction of its effect on exp07's result is unknown (the buy-stop variant was never run). The light
thresholds and the grid k ∈ {3, 4, 5} came from the roadmap, fixed before exp04-exp06 were run, and are unaffected.*

Rule: 5 fixed warning lights (close below the 200-session average; negative 250-session return; 20/60-session
volatility ratio > 1.2; more than 10% below the all-time high; 60-session high older than 20 sessions). Exit when at
least k are on, buy back when fewer than k − 1 are on. Grid k ∈ {3, 4, 5}.

**Step 01, exploration 2005-01-03 → 2014-12-31 (context only).** Share of decisions with at least 3 / 4 / 5 lights on:
24.9% / 14.1% / 2.7%. Buy-and-hold +69.02% (drawdown −56.44%). k = 3: +42.71% (14 exits); k = 4: **+74.56%** (11 exits);
k = 5: **+136.41%** (2 exits, 90.7% in the market, drawdown −21.93%; log excess +3.36%/yr [−2.56%, +12.70%]). Observed:
every winning candidate wins through one 2008 episode (k = 5: exit 2008-06-27 at 127.69, buy-back 2009-04-29 at 87.27,
S/R 1.4632; k = 4: S/R 1.4168); all its other exits, but one, bought back higher.

**Step 02, continuous replay over the 44 validation periods (2015-04-17 → 2026-04-15).** Schedule asserted identical to
exp03's; bars cut at 2026-04-15.
- After the fact (optimistic): every candidate loses to buy-and-hold (+235.39%). k = 3 +95.07% (18 exits), **k = 4
  +115.60%** (12 exits, 84.1% in the market; −3.99%/yr [−7.65%, −0.83%]), k = 5 +101.90% (8 exits, 0 bought back lower).
  All three log-excess intervals lie below 0.
- **Prior-only path (43 periods, 2015-07-17 → 2026-04-15): +49.09% vs buy-and-hold +229.74%** (annualized 3.79% vs
  11.77%), below every candidate after the fact, because switching k at period boundaries added exits. 84.4% in the
  market, 12 exits, mean 37.5 cash decisions per episode. 18 of 43 periods won (sign test p = 0.889); mean period excess
  −1.85% (SD 3.73%, t = −3.25); MDE 1.59% per period (6.37% per year).
- Annualized log excess **−7.33%/yr**, 95% interval (6-month blocks) [−12.55%, −3.49%] (1-month blocks [−12.28%,
  −2.46%]): the loss is statistically supported. Sharpe 0.33 vs 0.71; max drawdown −31.44% vs −34.21%; comparable,
  Sharpe and drawdown flags all False. Excess −180.58% / −180.65% / −180.82% at 0 / 1 / 2 cents.
- Information test failed: random exits with the same re-entry rule (median of 20) +183.31%, the path beats **0 of 20**;
  random re-entries after the same exits (median) +52.66%, the path beats **7 of 20** (35%).
- Scorecard: 12 episodes, **0 bought back lower**, product of S/R 0.4521. Largest loss: exit 2020-03-19 at 240.99,
  buy-back 2020-05-27 at 303.50 (S/R 0.7940; SPY +25.93% while out). The 2022 bear market gave three exits, all bought
  back higher (S/R 0.9478, 0.9670, 0.9055). The last episode (exit 2026-04-01) is open at the end and valued at the last
  close. Selections: k = 3 governed 12 periods, k = 4 17, k = 5 15.
  *Clarification 2026-10-06, after the independent audit (I4): "12 episodes, 0 bought back lower" means **11 closed
  episodes, all bought back higher, plus 1 episode open at the end** (exit 2026-04-01 at 655.35, valued at the last
  close 699.85, also above the sale price). The summary table's "all 12 exits bought back higher" should be read the
  same way.*

*Mathematically:* final equity ÷ buy-and-hold = 1.4909 ÷ 3.2974 = 0.452 = Π S/R (0.4521). Every factor is below 1:
Σ log(S/R) = log 0.452 = −0.79, about −0.066 per episode. A k-of-5 vote of lagging lights turns on after much of a fall
and turns off after much of the rebound, so with fast (V-shaped) declines the buy-back price is above the sale price.
*In plain words:* the warning lights worked in 2008, a slow bear market, and that one exit made the 2005-2014 result.
On 2015-2026 the declines were fast (2018, 2020, 2022, 2025): the lights agreed near the bottoms and cleared only after
the recovery, so each of the 12 exits lost money, and random exits at the same frequency did better every time.

What this supports: on the validation span, requiring several lagging warnings at once does not fix the problem of
exp04; the exits are late and the buy-backs later. What it does not support: any statement about slow bear markets in
general (one episode, 2008, in the exploration span only).

## Shared code change for exp06 (2026-10-06, agent; no trial)

*Implemented and tested.* `so/core/reentry_simulation.simulate_stop_reentry_dict` gained a backward-compatible
cooling-off: a re-entry rule may set `episode_dict["exit_block_sessions"] = c`, and the exit signal is then ignored for
the c decisions after that re-entry. Without the key (every rule of exp01-exp05) the behaviour is unchanged: the
block ends at the re-entry session itself. Checks: all 7 test suites pass (the new `tests/test_exp06.py` verifies
both cases), and exp04 step 01's numbers were recomputed with the changed simulator on the exploration data (not logged,
not a trial): textbook rule +50.39% with 33 exits, x = 5%, n = 10 +116.85% with 2 exits, identical to the saved outputs.

## VIX data layer (2026-10-09, agent; shared code, no trial)

*Implemented and tested* (roadmap 2026-10-09, step 0.4): `so/paths.py` (the four raw folders of
`store01_rawzone/ibkr_vix_family/`), `so/vix_config.py` (every VIX constant; `so/config.py` unchanged),
`so/features/vix_features.py` (loaders with a required cutoff that refuse 2026-05-14 and later, the per-session table of
the `_prev` and `_intraday` values, the six features), `tests/test_vix_features.py` (added to `tests/run_all_tests.py`;
10 suites pass). The staging folder and the three backup folders next to the raw folders are never read.

*Observed* (`pipeline/step07_VIX_data_check.ipynb`, run once on 2026-10-09, every load cut at 2026-04-15; last SPY,
VIX and VIX3M dates loaded: 2026-04-15 for all four series):

- Rows read: VIX daily 5,148 (2005-10-03 → 2026-04-15), VIX 1-minute 2,996,586 on 5,145 dates; VIX3M daily 4,193
  (2009-08-12 → 2026-04-15), VIX3M 1-minute 1,675,264 on 4,190 dates. SPY sessions 5,353 (2005-01-03 → 2026-04-15).
- **Missing vs known gaps:** every missing date is in the known-gap list of the inventory (VIX daily 17 = the 15
  sessions of 2006-05-01 → 2006-05-19, 2006-11-24, 2011-09-12; VIX3M daily 1 = 2011-09-12; VIX3M 1-minute 4 =
  2011-09-12, 2017-10-20, 2017-10-23, 2017-10-24), except the 4 half days left in staging for VIX 1-minute (2020-11-27,
  2020-12-24, 2024-07-03, 2024-12-24), as expected. One VIX date (2007-07-02, daily and 1-minute) has no SPY session (the
  SPY session is missing in the IBKR data).
- **`_prev` (primary) per series, sessions to 2026-04-15:** VIX: 5,151 usable (5 of them with a lag of 1-3 sessions:
  2006-11-27 after the missing 2006-11-24, 2011-09-13, and three in the 2006-05 gap), **12 stale** (2006-05-05 →
  2006-05-22, NaN), 0 missing, 190 before the first date. VIX3M: 4,193 usable (1 lagged, 2011-09-13), 0 stale, 0 missing,
  1,160 before 2009-08-12 (or on it).
- **`_intraday` (secondary) fallbacks to `_prev`:** VIX 20 (the 15 sessions of 2006-05, 2011-09-12 and the 4 staged half
  days); VIX3M 4 (2011-09-12 and 2017-10-20/23/24). Where a bar exists, the chosen bar is always exactly the allowed one
  (decision − 1 minute: 15:57, or 12:57 on half days): 5,144 VIX and 4,190 VIX3M sessions at distance 0, none earlier.
- **Daily close vs last 1-minute close** (agreement = within 0.005 points): VIX 5,010 of 5,144 dates (97.4%), VIX3M
  3,745 of 4,190 (89.4%); median absolute difference 0.00, 99th percentile 0.02 (VIX) and 0.03 (VIX3M). The disagreements
  cluster in 2021-2022 for VIX (48 and 58) and 2022-2026 for VIX3M (71 to 124 a year). A few are large: VIX 2026-01-16
  (daily 18.84 vs 15.86), 2025-06-18 (22.17 vs 20.14), 2025-05-23 (20.57 vs 22.29); VIX3M 2014-07-17 (14.97 vs 12.63).
  Cause unknown (not investigated; the IBKR data was not compared with Cboe's values). The primary timing uses the daily
  close, so these dates enter the primary features.
- **Session window per era (most frequent first / last bar label):** VIX 09:31-15:59 (2005-2011), 09:31-16:14
  (2012-2015), 03:15-16:14 (2016-2021), 03:15-16:59 (2022-2026); VIX3M 09:31-15:59 (2009-2011), 09:31-16:14 (2012-2026).
- **Features:** `vix_level_prev` from 2005-10-04 (median 17.07, 1%-99% 9.90-55.86, max 82.69); `vix_pct250_prev` from
  2007-05-22 (the 2006-05 gap blocks the 250-value window for a year, as specified); `vix_term_prev` from 2009-08-13
  (median 0.886, 99th percentile 1.144, max 1.344); `vix_fade` is never positive, `vix_pct250` lies in [0, 1] (asserted).
  Correlation between the two timings of the same feature: level 0.976, pct250 0.949, chg5 0.744, fade 0.878, term 0.911,
  vrp 0.946.

What this supports: the data layer reads only what it should, the timings behave as specified, and the gaps are the
known ones. What it does not support: that the IBKR index values equal Cboe's official values, or that the 1-minute bar
labels are start-of-minute labels (the convention is unproven; the 1-minute lag is a margin). Tables saved in
`store04_experiments/vix_data_layer/step07_VIX_data_check/`.

## exp08_vix_signal_check

**Protocol 1.0. Status: DONE; the gates close the VIX line** (PROTOCOL.md §5 and §7). Pre-registered in commit
`2c810d1` (2026-10-09 12:52:51, `preregister exp08`, protocol, config, code, tests and the notebook without outputs);
run once with `step01_vix_gate.ipynb` (first trial logged 2026-10-09T12:55:00); config hash `43e86ccb06`. Trials: 6
(stage `signal_check`: G1, G2, G3, G4, G1 intraday, G2 intraday; budget 10), all with `test_window_touched` False.
Numbers below are copied from the saved notebook outputs and from the CSV files in
`store04_experiments/exp08_vix_signal_check/step01_gate_data/`.

*Windows and data.* Schedule asserted: 44 folds, first train_end 2015-03-18, first valid_start 2015-04-17, last
valid_end 2026-04-15, latest test_start 2026-05-14 (never read). SPY bars and every VIX loader cut at 2026-05-13: last
SPY date loaded 2026-05-13 (5,373 sessions from 2005-01-03); last VIX daily, VIX3M daily, VIX 1-minute and VIX3M
1-minute dates loaded 2026-05-13. Largest session used by any label or forward volatility: 2026-05-13 (asserted).
Analysis rows (`_prev`): 4,193 sessions 2009-08-13 → 2026-04-15 (the first `vix_term_prev` needs a VIX3M close dated
before the session, so the rows start one session after 2009-08-12; the `_intraday` rows start on 2009-08-12, 4,194);
training 1,408 rows (2009-08-13 → 2015-03-18, share of positive labels 0.686); validation 2,765 rows (the 44 replay
periods 2015-04-17 → 2026-04-15, share 0.671).

*Observed (primary, `_prev`).*
- **G1 univariate: FAIL.** 30 bins tested (6 features × 5), **S1 = 0** signal pairs. On training, 2 bins were above
  the base rate (`vix_term_prev` (0.908, 0.946]: 0.786, interval low 0.698; `vrp_prev` above 0.0245: 0.816, low 0.731);
  on validation none was above or below (0.686 and 0.732 against 0.671, intervals include it). Null: all 19 shifted
  runs give S1 = 0; max 0, p = (1 + 19) / 20 = 1.00. S1 = 0 never passes.
- **G2 incremental AUC: FAIL.** Pooled out-of-sample AUC on 2,765 predictions: BASE (16 price features) **0.4233**
  [0.3648, 0.4829], AUGMENTED (16 + 6 VIX) **0.4592** [0.3995, 0.5174] (1-month blocks); **dAUC +0.0359**
  [−0.0025, +0.0709]; mean per-period dAUC +0.0714 (AUGMENTED better in 28 of 43 periods; period 34 has only positive
  labels, so its AUC is undefined). Training rows 1,408 (first fold) to 4,112 (last fold). Null dAUC of the 19 runs:
  +0.0043 to **+0.0563** (2 runs ≥ the real value: +0.0408, +0.0563); **p = 0.15**; the real value is not above the
  null maximum.
- **G3 volatility forecast: PASS.** 2,765 validation decisions, 133 months: Spearman(`vix_level_prev`, realized
  volatility of the next 20 sessions) 0.6357, Spearman(`daily_volatility`, same) 0.5193; **D = +0.1165**, 95% interval
  (circular 6-month blocks, 2,000 iterations) [+0.0441, +0.2227]; lower bound > 0.
- **G4 plausibility of unlevered volatility scaling: FAIL.** Top VIX quintile = `vix_level_prev` ≥ 22.94 (training
  80th percentile). Mean `fwd_net_return_20d`: training 282 rows (27 months) **+1.91%** [+0.89%, +2.94%]; validation 538
  rows (56 months) **+2.82%** [+1.60%, +3.90%]. Both means are above 0 (the gate needs both below 0), with intervals
  above 0.

*Observed (secondary, `_intraday`; reported, never a gate).* G1: S1 = 0 of 30 (1 training bin above the base rate,
`vrp_intraday` above 0.0246), null max 0, p = 1.00, would not pass. G2: BASE 0.4230, AUGMENTED 0.4521, dAUC +0.0291
[−0.0053, +0.0609], null max +0.0628, p = 0.25, would not pass. No "candidate pending review (secondary timing)".

*Gate decisions (as pre-registered, primary results only):* exp09 needs G1 or G2: **not run**. exp10 needs G3 and G4:
**not run** (G3 passes, G4 fails). exp11 needs G2: **not run**. **"No usable VIX information under the pre-registered
gates": the VIX line stops.**

*Descriptive (no gate, no trial).* Mean 20-session forward return by `vix_level_prev` quintile (training edges 13.87,
16.26, 18.56, 22.94), lowest to highest: training +0.44%, +0.31%, +1.11%, +1.57%, +1.91%; validation +0.49%, +0.47%,
+0.80%, +0.51%, +2.82%. By term structure: `vix_term_prev` ≥ 1 (inverted) training +2.43% (106 rows), validation +3.07%
(220 rows); < 1 training +0.96%, validation +0.81%. 106 inverted episodes (326 sessions) from 2009-10-29 to 2026-04-08
(table `term_episode_data.csv`).

*Mathematically.* G2: AUC is the probability that a random positive-label session gets a higher predicted probability
than a random negative one. The BASE model scores 0.423 out of sample, i.e. worse than a coin (0.5): its training
relations reverse on validation. Adding six columns with no real link to the label (the null: VIX columns shifted by
1,347 to 3,118 sessions) raises the AUC in **all 19 runs** (+0.004 to +0.056), because with the same regularization
(C = 0.1) the extra columns dilute the BASE model's (wrong-signed) weights and pull its predictions towards chance. The
real VIX columns give +0.036, inside that range (rank 3 of 20), so the improvement is what noise columns also produce.
G4: an unlevered exposure w ≤ 1 can only beat buy-and-hold if the sessions where w < 1 earn less than cash (0% here);
E[r | VIX in the top quintile] = +1.91% and +2.82% per 20 sessions, more than the unconditional means, so lowering
exposure when the VIX is high gives up the best 20-session returns of both windows. G3 holds (the VIX forecasts
volatility better than trailing volatility, ρ 0.636 vs 0.519), but a better volatility forecast only helps if high
volatility comes with low returns, and G4 shows the opposite.
*In plain words.* The VIX does not tell us when SPY will rise or fall over the next month, on its own (G1) or on top of
the price features (G2: the small gain is the same as adding random columns to a model that was already worse than
guessing). The VIX is a good forecast of how bumpy the next month will be (G3), but bumpy months after a high VIX were,
on average, good months to own SPY (G4): selling or holding less when fear is high would have missed the rebounds.
This is the same lesson as exp04-exp07, now with option-market data.

What this supports: under the pre-registered gates, the VIX and VIX3M features (as built, `_prev` timing) add no usable
information about the 20-session direction of SPY on 2009-2026, and high-VIX periods did not have returns below cash,
so none of exp09-exp11 can run. What it does not support: that the VIX carries no information at any horizon or in any
model (only the six features, one horizon, 5-bin checks and one regularized logistic were tested); anything about
leverage (not allowed here); anything about the untouched window. The descriptive pattern (higher forward returns after
a high or inverted VIX) is not tested and is not a trading result: it rests on few episodes (2011, 2015-16, 2018, 2020,
2022, 2025) and is the kind of pattern the gates were designed not to chase.

## Cross-experiment notes (2026-10-06)

- The common failure is time out of the market: at about 12% a year, every session in cash costs about 0.045% of
  expected return, so an exit must be followed by a fall larger than that rent plus costs.
- exp01's buy-and-hold (+218.48%) differs from exp02/exp03's (+237.21%) because its schedule (10-session embargo) gives
  different quarters; compare each strategy only with its own buy-and-hold.
- The monthly-bootstrap intervals printed for exp02 and exp03 ([−454.82%, +1.21%] and [−400.79%, +12.44%]) are intervals
  of the difference in total compounded return over about 11 years; compounding stretches the lower tail. An interval on
  the annualized log excess would be easier to read (reporting change, not yet made).
- Trials added by this round: exp01 2 signal-check + 540 validation + 1 summary; exp02 14 + 1 + 792 + 1; exp03 15 + 660 +
  1 (2,027 in total), on top of the 4,089 legacy trials.
- Trials added by the "stay invested, exit rarely" family (2026-10-06): exp04 406, exp05 182, exp06 541, exp07 136
  (1,265 in total). Workspace total 3,292, plus the 4,089 legacy trials (7,381). No prior-only path of exp01-exp07 beats
  buy-and-hold; no candidate result is pending review.
- *Added 2026-10-06 (exp01 step 04 diagnostic): 1 `multivariate_check` trial. Workspace total 3,293, plus the 4,089
  legacy trials (7,382). Outcome A (no information); still no candidate result pending review.*
- Observed while running notebooks: `venv-main\Scripts\jupyter.exe` starts its host process from a system Python 3.14
  install, while the notebook kernel (`venv-main`) is the venv's own interpreter; the computations run in the kernel.
  Recorded for traceability, no action taken.
- *Added 2026-10-06, after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`, I5): annualized log excess
  of the prior-only path over buy-and-hold, 95% interval with 6-month blocks, copied from the saved outputs of each
  `step02_continuous_replay.ipynb`:*
  - *exp04_trend_exit: −6.07%/yr [−10.54%, −2.14%]: the underperformance is statistically supported (interval
    entirely below 0).*
  - *exp05_vol_scaled_exposure: −1.99%/yr [−4.33%, +0.08%]: the interval includes 0.*
  - *exp06_capped_regret_reentry: −2.65%/yr [−6.74%, +1.53%]: the interval includes 0.*
  - *exp07_warning_lights_exit: −7.33%/yr [−12.55%, −3.49%]: the underperformance is statistically supported
    (interval entirely below 0).*
  - *The notebooks' `supported` flag (False for all four) tests only a positive excess (lower bound > 0); it says
    nothing about whether a loss is significant.*

### Limitations of the exp04-exp07 session (added 2026-10-06, after the independent audit, I6)

- exp04-exp07 were built, pre-registered, run and documented by the agent in 56 minutes (commits 14:02 → 14:58),
  without human review before running. Their integrity rested on the roadmap fixed beforehand (rules, grids,
  thresholds), which held; the one deviation from it (exp07's re-entry) is recorded in the exp07 section (I1).
- 2015-2026 has now been used by seven experiments (exp01-exp07; about 7,400 trials including the 4,089 legacy trials):
  it is development data, not out-of-sample evidence.
- exp04-exp07 were designed with knowledge of famous episodes (2008, 2020).
- In 2005-2014 the designs that looked good (exp04, exp05, exp07) did so through 2008 alone, and all of them lost on
  2015-2026.
- Any future positive result needs the untouched window (2026-05-14 → 2026-08-13, a parked decision) or new data.

### The VIX line (added 2026-10-09, agent)

- Roadmap exp08-exp11 (Nicolas, 2026-10-08, revised 2026-10-09). Setup: the SPY folder-rename check reproduced every
  number (see "Reproduction checks"); the shared VIX data layer was built and checked (section "VIX data layer").
- exp08 (the gate) ran once: G1, G2 and G4 fail, G3 passes; under the pre-registered gate decisions **exp09, exp10 and
  exp11 were not run**. Result: **no usable VIX information under the pre-registered gates**. No candidate result is
  pending review, primary or secondary timing.
- Limitations that apply to the whole line: VIX3M starts 2009-08-12 in the IBKR data, so the training span of the gate
  is 2009-08-13 → 2015-03-18 (1,408 sessions, shorter than exp02's 2005 start); the IBKR index data was not compared with
  Cboe's official values (the daily close and the last 1-minute close disagree on 2.6% of VIX and 10.6% of VIX3M dates);
  the 1-minute bar-label convention is unproven (the `_intraday` timing keeps a 1-minute margin and is secondary); 2015-2026
  is development data, reused here for the eighth time; the untouched window 2026-05-14 → 2026-08-13 was **not read**
  (every loader refuses dates from 2026-05-14; the last date loaded by any VIX notebook is 2026-05-13).
- Trials of the VIX line: exp08 6 (`signal_check`); exp09, exp10, exp11 0. Workspace total **3,299**, plus the 4,089
  legacy trials **7,388**.
