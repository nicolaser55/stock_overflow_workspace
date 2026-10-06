# Stock Overflow: Results Log

*The chronological record of experiment outcomes of the reorganized workspace (from 2026-10-05), for the thesis. Each entry
states what was run, under which protocol version and configuration hash, what was observed, and what the evidence does and
does not support. Failures are results. Test windows touched so far: **none** (as of 2026-10-06).*

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
| `exp01_minute_entry` | 1.0 | **STOP** (2026-10-06) | Signal check: 2 signal bins vs null max 4, p = 0.10 → STOP. Walk-forward (run before the verdict): prior-only +146.94% vs buy-and-hold +218.48% |
| `exp02_stop_reentry` | 1.0 | **STOP** (2026-10-05) | 0 signals; prior-only +111.66% vs +237.21%; the model's re-entry is worse than all 20 random re-entry runs |
| `exp03_ath_exit` | 1.0 | **STOP** (2026-10-05) | Prior-only +143.05% vs +237.21%; beats random exits (19/20) but loses to random buy-backs (19/20 beat it) |
| `exp04_trend_exit` | 1.0 | **STOP** (2026-10-06) | Continuous replay: prior-only +70.84% vs +229.74%; all 12 exits bought back higher; beats 0/20 random exits and 4/20 random re-entries |
| `exp05_vol_scaled_exposure` | 1.0 | **STOP** (2026-10-06) | Signal check passes (ρ 0.593); prior-only +165.69% vs +229.74% (mean weight 86.3%); constant exposure +198.52%, beats 3/20 random shifts; drawdown −23.20% vs −34.21% |

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
- Selections: floor 50%, q 0.75 governed 28 of 44 periods, floor 50%, q 0.50 9, floor 30%, q 0.50 7.

*Mathematically:* with w_t ≤ 1 the strategy's excess over buy-and-hold is about −Σ (1 − w_t) r_t − costs. Holding less
SPY on average costs about (1 − 0.863) × 11.8% ≈ 1.6% a year in a rising market; the volatility timing had to earn that
back by having (1 − w_t) large when r_t < 0. It did not: relative to the constant-exposure path the timing cost a further
growth factor 2.6569 / 2.9852 ≈ 0.89 over 10.7 years. Volatility predicts volatility (step 01, ρ ≈ 0.59), not the sign of
the return: high-volatility stretches contain the worst and the best sessions (the rebounds of 2020 and 2025 came while
σ̂ was still high and w was at its floor).
*In plain words:* cutting SPY when the market is jumpy made the ride smoother (drawdown −23% instead of −34%) but cost
about 64 points of total return over 10.7 years, more than simply keeping 14% in cash all the time would have.

What this supports: on 2015-2026, unlevered volatility scaling with this σ̂ does not beat buy-and-hold and its timing
adds no return over an uninformed exposure; it does lower the drawdown. What it does not support: anything about levered
volatility management (excluded by the project), about implied volatility (VIX, new data, parked), or about other σ̂.

## Shared code change for exp06 (2026-10-06, agent; no trial)

*Implemented and tested.* `so/core/reentry_simulation.simulate_stop_reentry_dict` gained a backward-compatible
cooling-off: a re-entry rule may set `episode_dict["exit_block_sessions"] = c`, and the exit signal is then ignored for
the c decisions after that re-entry. Without the key (every rule of exp01-exp05) the behaviour is unchanged: the
block ends at the re-entry session itself. Checks: all 7 test suites pass (the new `tests/test_exp06.py` verifies
both cases), and exp04 step 01's numbers were recomputed with the changed simulator on the exploration data (not logged,
not a trial): textbook rule +50.39% with 33 exits, x = 5%, n = 10 +116.85% with 2 exits, identical to the saved outputs.

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
