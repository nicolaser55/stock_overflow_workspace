# Stock Overflow — Research Protocol v2: Stop and Re-entry

> **Status: STOPPED (2026-10-04).** All three stopping-rule checks of §11 were negative: the mechanism check (stops sell into dips that revert), the daily signal check (0 signals) and the walk-forward validation (no candidate beat buy-and-hold). The test windows were never evaluated. Results: `docs/RESULTS_LOG.md`.

*Version 2.0 (2026-10-04). Experiment name: `stop_reentry_v2`. Every rule below was agreed with Nicolas on 2026-10-04, before any v2 result existed. This protocol replaces v1 (`docs/RESEARCH_PROTOCOL.md`) for new experiments; v1 stays as the record of the first experiment. After the first `validation_only` run of step 12, any change to a rule is a new version with a new experiment name (§16). The only exception is the exploration rule of §13.*

---

## 1. Why v1 was stopped

v1 (`lgbm_ev_policy_v1`, config hash `ff9d0d7e2e`) picked minute-level long entries, each with a symmetric SL/TP of 0.1–1% and at most 10 days of holding.

- **Signal check (stopping rule): STOP.**
  - 1,339 of 5,691 feature bins passed on training, but 0 also passed on validation.
  - Almost all training passes came from market drift: for distances of about 0.25–0.9%, simply being long already beat break-even. Only 19 bins beat the unconditional base rate.
- **Walk-forward, validation only, 45 quarters from 2015 to 2026:**
  - No setting beat buy-and-hold. The best chained return was about +162%, against about +247%.
  - The best setting beat buy-and-hold in at most 18 of 45 quarters.
  - The model was invested 75–95% of the time and still lagged, because capping winners at +δ costs the large up-moves.
- **Test windows were never evaluated** (`test_window_touched = 0`).
- **Input check (2026-10-04):** 5 random copied TSIND files were identical to files regenerated with the current code.

**Lesson.** A long-only, unleveraged strategy cannot hold more than 100% of SPY. It can beat buy-and-hold only by being **out of the market during declines and back in before the recovery**. v2 tests exactly that.

## 2. Research question

Starting from a fully invested position in SPY:

- an **exit based on a calculated risk tolerance** (a volatility-scaled trailing stop),
- combined with a **re-entry decision based on information** (a model of SPY's 20-session forward return),

can these produce a **higher total return after costs than buy-and-hold** over the same period, out of sample?

**How the strategy can beat buy-and-hold.** While invested, the strategy *is* buy-and-hold. The difference comes only from the out-of-market episodes. An episode that sells at price S and buys back at price R ends with S ÷ R times the shares it had, before costs. The strategy wins exactly when, on average, it **buys back lower than it sold**.

## 3. Success criteria

| Level | Criterion |
|---|---|
| **Primary** | Total return after all costs, chained over all historical test windows, **above buy-and-hold** over the same windows |
| **Secondary** (counted only at comparable return) | A **higher Sharpe ratio** and a **smaller maximum drawdown** than buy-and-hold, on the chained daily returns |
| **Comparable return** | Strategy total return ≥ 90% of buy-and-hold's total return. If buy-and-hold is negative: strategy return ≥ buy-and-hold return − 10% × \|buy-and-hold return\| |

**Required for any claim that the information adds value.** On the primary metric, the strategy must also beat the same-stop baselines of §10 (fixed-delay and random re-entry). Otherwise the stop rule, not the model, is doing the work.

**Statistical support.** Report a block-bootstrap confidence interval for the chained excess return over buy-and-hold, resampling calendar months. Use the words "statistically supported" only if the lower bound of the 95% interval is above 0. Otherwise report the result as "observed, not statistically supported".

**Metrics:** Sharpe ratio annualized from daily returns with a risk-free rate of 0; maximum drawdown is the largest peak-to-trough fall of the daily equity.

## 4. Data

Unchanged from v1: SPY 1-minute bars from IBKR, regular hours, 2005-01-03 to the latest session, unadjusted. 2007-07-02 is missing; 2009-07-27 and 2013-12-23 are partial sessions. Previous sessions are the sessions present in the data.

## 5. Strategy rules (`stop_reentry_simulation.py`)

- **State.** INVESTED (all-in SPY) or CASH. Cash earns 0%. One position at a time; the account compounds.
- **Daily decision.** Once per session, on the 15:58 bar (the second-to-last bar on half days). A trade decided there fills at the open of the next bar (15:59) plus slippage.
- **Start of each evaluated window.** INVESTED from the first allowed entry of the window's first session (the 10:00 open), the same entry as buy-and-hold. A position still open at the window's end is sold at the last close with exit costs, as buy-and-hold is. No entry is made at the last session's decision. The state is **not** carried between windows (§15).
- **Exit: trailing stop, checked intraday on every minute bar.**
  - σ = `daily_volatility` of the session: the standard deviation of the previous 20 daily close-to-close returns. It is known at the open.
  - Stop for bar j = max(previous stop, highest minute close since the entry up to bar j−1 × (1 − k·σ)). The stop only moves up and is active from the bar after the entry.
  - k ∈ **{3, 4, 5}**, selected on validation (§9). Normal noise over a few days is already about 2σ, so k = 2 would trigger on ordinary wobbles. With σ ≈ 1%, the grid means stops roughly 3–5% below the high.
  - Fills use the v1 stop-loss rules: a bar opening at or below the stop exits at its open (gap); otherwise a low at or below the stop exits at the stop. −$0.01 slippage per share and IBKR fees apply.
  - No take profit, no time limit: winners run, as in buy-and-hold.
- **Re-entry: information.**
  - At each decision while in CASH, the model gives P = P(net 20-session forward return > 0) (§6). This includes the decision of the session in which the stop was hit, if the stop was hit at or before the decision bar.
  - The strategy buys at the 15:59 open if P ≥ p\*, where **p\* = training base rate + offset** and offset ∈ **{−0.05, 0, +0.05}** is selected on validation.
  - The base rate is the share of positive labels in the training window. It is used because, with SPY's drift, it is well above 50%: an absolute threshold of 0.50 would make the model buy back almost immediately and copy the next-day baseline. Staying out only makes sense when the model sees below-average conditions.
- **Forced re-entry.** After 60 decisions in CASH, the strategy re-enters at that decision's 15:59 fill, whatever the model says. Forced re-entries are counted and reported separately.

## 6. Target (`daily_features.py`, step 09)

- **One row per session**, evaluated at the decision bar.
- **Label:** y = 1 if buying at the 15:59 open (+$0.01) and selling at the close of the last bar of session t+20 (−$0.01) is profitable after the per-share fees; y = 0 otherwise. The last 20 sessions are unresolved (NaN) until new data arrives.
- **Training rows:** **all** sessions with every feature and a label, not only cash days, to have enough data. Cash days come after declines, so this is a distribution shift (§15). Validation reports the model's AUC on all validation rows.
- **Overlap:** labels 20 sessions long overlap heavily. With nearly uniform overlap, uniqueness weights are almost constant, so the rows are not weighted. Confidence intervals use a monthly block bootstrap.

## 7. Features (`daily_features.py`, step 09)

16 scale-free features, every one using only bars up to the decision bar and complete previous sessions (tested in `tests/run_tests_v2.py`):

| Group | Features |
|---|---|
| Same definitions as TSCTX (tested equal) | `prev_day_return_pct`, `prev_day_range_pct`, `intraday_return_pct`, `daily_volatility`, `ath_drawdown_pct` |
| Past returns | `return_5d`, `return_20d`, `return_60d`, `return_120d`, `return_250d` |
| Trend | `ma50_dist_pct`, `ma200_dist_pct` (distance from the mean close of the previous 50 / 200 sessions) |
| Volatility regime | `volatility_ratio_20_60` |
| Drawdown from recent highs | `high60_dist_pct`, `high250_dist_pct`, `sessions_since_high60` |

- **Minute-level TSIND and TSSEG features are not used.** They describe the last minutes before 15:58 and add overfitting risk at a 20-session horizon with little data.
- **"State" features** (sessions since the stop-out, return since the exit price) were considered. They cannot be defined on the invested days the model is trained on, so they were replaced by their market analogs: `sessions_since_high60` and `high60_dist_pct`.
- **The first session with every feature** is about one year after the start of the data (250-session lookbacks).

## 8. Model (`walk_forward_v2.py`)

- **Primary:** a logistic regression on standardized features with L2 regularization (C = 0.1). Ten years give only about 2,500 daily rows, which is roughly 125 independent 20-session periods. A model with few parameters is the defensible choice, and it is easy to explain.
- **Diagnostic:** a shallow LightGBM (depth 2, 4 leaves, 200 trees, learning rate 0.02, at least 100 rows per leaf). It is fitted in every fold and its validation AUC is reported, but it is never used for decisions. If it clearly beats the logistic regression, that is a finding for a later version.
- Constants are in `config_v2.py`. Any change is a logged trial.

## 9. Walk-forward and selection (`walk_forward_v2.py`, step 12)

- **Windows:** 3-month test windows anchored on the latest session, stepping back 3 months, as in v1. 3-month validation windows.
- **Embargo: 20 sessions** between training, validation and test, which is the label horizon. Up from 10 in v1, so the first test window moves from about 2015-05 to about 2015-08: **44 folds**.
- **Training windows:** **10 years**, or **all** sessions since the start of the data. Declines and recoveries are rare (2008, 2011, 2015–16, 2018, 2020, 2022), so keeping all of them matters. In the first folds the two windows are nearly the same.
- **Candidates per fold:** 2 windows × 3 k × 3 offsets = **18**. Every candidate is logged as a trial.
- **Selection on pooled validation.** Each candidate is scored by its **mean validation excess return over the last 4 validation quarters** (this fold and the 3 before it; fewer for the first folds). All of these quarters lie before the test window. This reduces the single-quarter luck that hurt v1. Ties go to the larger k, then the higher offset, then the 10-year window.
- **Refit and test:** the selected candidate is refit on its window ending at the validation end. The embargo protects the test window. The test window is evaluated once.
- **Run modes:** `validation_only` (all folds, no test), `latest` (validation of the last 4 folds, test of the last one) and `history` (every test window). No test window is evaluated until the design is frozen.

## 10. Baselines (same simulator, same costs, every test window)

1. **Buy-and-hold** over the same window.
2. **Same stop + fixed-delay re-entry:** re-enter at the 1st, 5th or 20th cash decision (three baselines).
3. **Same stop + random re-entry:** 20 runs. Each re-enters at every cash decision with probability 1 ÷ (the model's mean number of cash decisions per episode).
4. **200-session moving-average rule** (textbook trend rule, no stop): invested when the 15:58 close is above the mean close of the previous 200 sessions, in cash otherwise. It trades at the 15:59 open.

The model adds value only if it beats baselines 2–3 on the primary metric. If the 200-session rule does as well, the honest finding is that a simple rule suffices.

## 11. Stopping rules

1. **Daily signal check (step 11), before reading any walk-forward result.**
   - Windows: the 10-year training window of the 4th most recent fold, and the validation windows of the 4 most recent folds pooled together (about one year, after that training window). The latest test window is not read. These validation quarters were test windows of **older** folds, so the go/no-go decision here counts as having seen them (as in v1).
   - For each feature, 5 quantile bins (edges learned on training). Each bin's rate of positive 20-session returns is compared with the **base rate of the same window**, with a monthly block bootstrap interval.
   - **Two-sided:** a bin is a signal if its interval lies entirely above the base rate, or entirely below it, on training **and** on the pooled validation, on the same side.
   - **STOP or pivot if no bin is a signal.** The report also gives the number of training passes expected by chance (5% of the tests).
   - **Known weakness, found after the v2 run.** A bin whose rows fall in only a few calendar months gets a degenerate bootstrap interval (e.g. [1.0, 1.0]), which could create a false pass. It did not affect the v2 verdict (no bin passed training). `signal_check_v2.get_daily_signal_check_pdf` now has `min_month_count_in`. The default `None` reproduces the v2 run; later experiments must set a minimum (e.g. 6 months per bin in each window).
2. **Mechanism check (step 10, exploration, §13).**
   - Over 2005-01-03 to 2014-12-31 as one window: the stop with fixed-delay re-entry for each k, an **oracle** re-entry, and the 200-session rule.
   - The oracle buys back at the lowest 15:59 open before the forced re-entry. It sees the future, so it is a very loose ceiling; it only rules a k out if even the oracle loses.
   - The main evidence is the **post-exit path**: the mean log share gain of re-entering n decisions after each stop, for n = 1…60, compared with the same quantity after any session (the period's drift). If prices tend to keep falling after stops more than drift explains, waiting pays and a model has something to predict.
   - This check informs the design; it is not an automatic STOP.
3. **Walk-forward (step 12).** STOP if, across the historical test windows, the strategy fails to beat buy-and-hold **and** the fixed-delay baselines on the primary metric.

## 12. Reporting

- **Per test window:**
  - total return, Sharpe ratio and maximum drawdown of the strategy and of every baseline;
  - stop-outs, model re-entries and forced re-entries;
  - share of sessions in cash;
  - cost sensitivity at $0.00, $0.01 and $0.02 slippage per share;
  - the model's percentile among the random re-entry runs.
- **Per out-of-market episode:** exit and re-entry times and prices, number of cash decisions, re-entry reason, and **share gain** = S ÷ R − 1 (> 0 means it bought back lower). The episode table is the core evidence.
- **Across test windows:**
  - chained returns and the monthly bootstrap interval of the excess return (§3);
  - the success criteria;
  - same-stop baselines beaten;
  - the number of windows beating buy-and-hold, with a one-sided sign test.
- **Validation (no test window):** for every candidate, chained validation return, number of quarters beating buy-and-hold, mean stops and time in cash, and the mean validation AUC of both models.

## 13. Discipline against luck and leakage

- **Trial log.** The same file as v1 (`trial_log/trial_log.csv`), experiment `stop_reentry_v2`. The v2 config hash covers `config.py` **and** `config_v2.py`. Stages: `exploration`, `signal_check`, `validation`, `test`. The v1 entries and the v1 hash `ff9d0d7e2e` are unchanged (tested).
- **Exploration is allowed only on 2005-01-03 to 2014-12-31.** That period is training data in every fold. Results seen there may change the grids (k, offsets, maximum cash sessions) only **before** the first `validation_only` run of step 12. Each change is recorded in §16.
- **After the first `validation_only` run,** any change is a new version with a new experiment name.
- **Test windows** are evaluated only once the design is frozen. Once evaluated, they count as seen for this line of work.

## 14. Implementation

| Step / file | Content |
|---|---|
| `config_v2.py` | Every v2 constant. Shared constants (costs, fees, capital, bootstrap) are read from `config.py`, never copied |
| `daily_features.py`, step 09 | Daily features and label, one file `step09_TSDAY_data/TSDAY_data.csv` rebuilt from the raw data each time |
| `stop_reentry_simulation.py` | State machine: trailing stop, re-entry rules (model, fixed delay, random, oracle), forced re-entry, trend rule, metrics, episodes, post-exit path |
| step 10 | Mechanism check (exploration only) |
| `signal_check_v2.py`, step 11 | Two-sided base-rate signal check on pooled validation |
| `walk_forward_v2.py`, step 12 | Schedule, models, validation candidates, pooled selection, test with baselines and cost sensitivity, bootstrap, success criteria, v2 trial log |
| `tests/run_tests_v2.py` | Features equal TSCTX; no look-ahead; label by hand; the vectorized simulator equals a bar-by-bar reference implementation; schedule, selection, signal check, criteria; an end-to-end fold |

Steps 01–04 are not needed by v2, which only reads the raw minute bars. Steps 05–08 (the v1 branch) are frozen.

## 15. Known limitations and biases

- **Dividends are ignored.** In reality buy-and-hold collects about 1.2–2% a year and the strategy collects nothing while in cash, so ignoring dividends **favors the strategy** in proportion to its time in cash.
- **Cash earns 0%.** In reality, cash earned interest (about 4–5% a year in 2023–2025), so this **disfavors the strategy**.
- **State resets to invested** at the start of each 3-month window, adding re-entries the model did not choose.
- **Few large declines** in 2015–2026 mean low statistical power for the primary criterion.
- **Distribution shift:** the model is trained on all days but used only on cash days.
- **Costs** are the v1 assumptions, informal rather than measured.
- **The signal check's validation quarters** are test windows of older folds (§11.1).

## 16. Change log

| Version | Date | Change |
|---|---|---|
| 2.0 (draft) | 2026-10-04 | Pivot after the v1 STOP. Decided: primary criterion total return above buy-and-hold; secondary criteria Sharpe ratio and maximum drawdown at ≥ 90% of buy-and-hold's return; daily decision 15:58 with the 15:59 fill; intraday trailing stop sized by volatility; re-entry on P(net 20-session forward return > 0); forced re-entry after 60 sessions |
| 2.0 | 2026-10-04 | Defaults agreed: k ∈ {3, 4, 5}; threshold = training base rate + {−0.05, 0, +0.05}; training windows 10 years or all history; logistic regression primary, LightGBM diagnostic; 16 daily features (state features replaced by market analogs); each window starts invested; 20-session embargo (44 folds); pooled 4-quarter selection; two-sided base-rate signal check; mechanism check with post-exit path. Implemented and tested on synthetic data; no v2 result on real data exists yet |
| 2.0.1 | 2026-10-04 | Editorial only, after the v2 run: status line (stopped); the known weakness of the daily signal check and the optional month minimum added to the code (default off, so the v2 result is reproducible) |
| 2.0.2 | 2026-10-04 | Data correction, no rule changed. 62 bad wicks (2005–2009) in the raw minute bars are cut to the bar body by `fix_raw_bad_ticks.py` (rule in its docstring, fixed before its effect on any result was looked at). The v2 steps are rerun on the corrected data under the experiment name `stop_reentry_v2_clean` (config hash `34455c40ce`; the name is the only constant that changed). The `stop_reentry_v2` runs (hash `f661934b1a`) stay in the trial log as runs on uncorrected data. The status STOPPED is re-examined only through the rerun's own stopping-rule results. **Done 2026-10-05:** signal check 0 signals (identical), mechanism check negative, all 18 candidates below buy-and-hold on validation: STOPPED confirmed. A first rerun was logged under the old name by stale notebook kernels; its results are identical to the `stop_reentry_v2_clean` run (`docs/RESULTS_LOG.md`) |
