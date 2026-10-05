# Stock Overflow — Research Protocol

> **Status: STOPPED (2026-10-04).** Experiment `lgbm_ev_policy_v1` failed its stopping rules (signal check STOP; no setting beat buy-and-hold on validation). Its test windows were never evaluated. Results: `docs/RESULTS_LOG.md`. New work follows `docs/RESEARCH_PROTOCOL_v2.md` and later versions. Step numbers below are the current ones (v1 = steps 00–08).

*Version 1 (2026-10-01). Agreed in the design discussion of 2026-10-01. Every result in the thesis is checked against this document. A change to any rule here is a new protocol version: record it in §17 and run it under a new experiment name.*

---

## 1. Research question

Can a model trained on SPY's own minute-level price action, technical indicators and market context:

- pick **long entries**,
- **and an SL/TP distance for each entry**,

so that, **after realistic costs, its total return beats buy-and-hold over the same period**, and keeps doing so on data it has never seen?

The qualitative (text) part of the original hypothesis is deferred until the quantitative part is finished.

## 2. Success definition

| | Definition |
|---|---|
| **Primary metric** | Total return after all costs, compared with buy-and-hold over the same span (`excess_return = total_return − buy_hold_return`) |
| **Secondary metrics** | Annualized Sharpe ratio (daily mark-to-market, risk-free rate 0) and maximum drawdown |
| **Diagnostics** | Number of trades, TP/SL/TL rates, WIN/LOSS/NULL counts, exposure, number of decisions skipped while a position was open |
| **Benchmark** | Buy-and-hold: buy at the first allowed entry (10:00 open), sell at the last close, same slippage and fees |

**Known bias in the benchmark:** dividends are ignored for now. Buy-and-hold is therefore understated by about 1.2–2% a year, which favors the model. A small positive excess return must be read with this in mind.

**Cash between trades** earns 0%.

## 3. Data

- **Source:** SPY 1-minute bars from IBKR, regular hours only (09:30–15:59 New York time), from 2005-01-03 onward. Prices are not adjusted for dividends or splits.
- **Missing data:** 2007-07-02 could not be obtained from IBKR. About 7 bars with absurd values were corrected by hand in the raw files.
- **Step 00** documents the data quality before anything else is built:
  - candlestick consistency;
  - duplicated timestamps;
  - bars per session versus the NYSE schedule;
  - missing sessions.
- **Trading days** are the sessions present in the data (a missing session is not counted).

## 4. Decision and execution rules

Source: `config.py` and `trade_execution.py`. The target matrix and the simulator both call the same functions.

1. **Decision:** the feature row of bar t. Every feature uses only bars ≤ t (snapshot design, steps 01/02/03; the context features of step 04 are tested for look-ahead).
2. **Entry:** at the open of bar t+1 in the same session.
   - The first entry is the 10:00 open (decision 09:59).
   - The last entry is the 15:59 open (decision 15:58).
   - The 15:59 row cannot buy at the next session's open.
3. **Barriers:** set from the entry open.
   - TP = open·(1+d), SL = open·(1−d·rr), with rr = 1. Both are rounded to $0.001.
   - SL and TP become active on the bar **after** the entry bar.
4. **Exit on each active bar, in this order:**
   1. the bar opens at or below SL → exit at the bar's open (SL);
   2. the bar opens at or above TP + 1 tick → exit at the bar's open (TP);
   3. the low reaches SL → exit at SL (SL wins if TP is also hit on the same bar);
   4. the high reaches TP + 1 tick → exit at TP. Merely touching TP does not fill a limit order.
5. **Holding limit:** 10 trading days, counting the entry day as day 1. A time-limit (TL) exit is at the close of the last bar of day 10.
6. **One position at a time.** Buy decisions made while a position is open are skipped. A new decision is allowed on the exit bar.
7. **Sizing:** the whole account is invested in every trade, and the account compounds.

## 5. Costs

| Item | Value |
|---|---|
| Entry | +$0.01 per share (spread and slippage) |
| SL, time-limit and end-of-data exits (market orders) | −$0.01 per share |
| TP exits (limit orders) | no slippage |
| Fees | IBKR fixed, per side: $0.005 per share, minimum $1, maximum 1% of trade value |
| Sensitivity on test | slippage of $0.00, $0.01 and $0.02 per share, with the same decisions |

Higher slippage on macro-event days (CPI, FOMC) is ignored for now. The source figures for the spread and slippage are informal (trading guides, a broker page, forum threads). They are **assumptions**, not measurements.

## 6. Target

The target is the TSBAR matrix (step 05).

- **Rows and cells:** one row per decision bar and one cell per SL/TP distance. Each cell holds `exit_bar_count|exit_price|exit_reason`, with exit reason TP, SL, TL or NA.
- **Distances:** 32 values from 0.05% to 2.00%. The 21 values from 0.10% to 1.00% are the training set (`TRAIN_DELTA_LIST`); the others are diagnostic.
- **NA:** the data ended before the holding window. NA rows are excluded from labels and regenerated when new data arrives.
- **Labels:** `y_tp` = 1 for TP and 0 for SL or TL. `net_return` is computed with the cost rules of §5 when the matrix is read, so the cost assumptions can change without regenerating step 05.

## 7. Features

- **Sources:**
  - TSIND (step 02, 43 columns);
  - TSSEG (step 03);
  - TSCTX (step 04): time of day, day of week, overnight gap, previous-day return and range, distance to the previous day's high and low, intraday return, 20-day volatility, relative volume, distance from the all-time high.
- **Feature registry:** every feature has a scale type (`config.FEATURE_REGISTRY_DICT`).
- **Absolute-dollar features are excluded from the model until the scaling design is done.** Their value grows with the price level ($120 → $780), so a model would use them to tell years apart.
- **Constants stay at their original values** (ATR 10, smoothing 4, swing order 3, weight 0.4, trend ±$0.01, indicators 14/3/12/26/9/20) and are set in `config.py`. Tuning any of them is a trial and must be logged.

## 8. Sampling and weights

- **Training rows** are sampled every 15 minutes from 10:00 (`SAMPLING_MODE`). An event-based mode (a new swing is confirmed) is also available.
- **Training weights** use average uniqueness, so trades that overlap many others weigh less.
- **Validation and test simulations** use **every** eligible minute, as a live model would.
- Every result reports its number of non-overlapping trades.

## 9. Splits and walk-forward

```
|---- train (L years) ----| 10 sessions |-- validation (3 months) --| 10 sessions |-- test (3 months) --|
```

- **Anchor:** the most recent fold ends on the last session of the data. This is the moving test window, tracked over time. Earlier folds step back 3 months at a time (history replay).
- **Gap:** 10 sessions between windows, which is at least the 10-day holding limit, so no training label reaches into the next window.
- **Selection on validation:** the training window length L ∈ {3, 5, 10} years and the expected-return threshold ∈ {0, 0.02%, 0.05%, 0.10%} are chosen by validation total return. On ties, the shorter L and the higher threshold win.
- **Refit:** the selected setup is retrained on the L years ending just before the test gap, then evaluated **once** on the test window.
- **First fold:** with a 10-year maximum window and data from 2005, the first test window starts around 2015-05. That gives about 45 historical folds.

## 10. Model and decision policy (proposal, pending agreement)

- **Model:** one LightGBM classifier per SL/TP distance, predicting P(TP first).
- **Decision at each eligible minute:**
  1. Compute the expected net return of every distance from P(TP), using the **decision bar's close**. The entry open is not known yet.
  2. Pick the best distance.
  3. Buy if its expected return is above the threshold.
- **Time-limit exits** are treated as losses in this expected return, which is conservative.
- **This output format was not formally agreed.** It is isolated in `walk_forward.fit_tp_model_dict` and `get_policy_decision_pdf`, so it can be replaced.

## 11. Baselines (same simulator, same costs, every test window)

1. **Buy-and-hold** over the same span.
2. **Random entry:** 20 runs. Each eligible minute buys with the model's buy rate, at a distance drawn from the model's chosen distances. This matches the model's activity.
3. **Fixed time:** buy at the 10:00 open every session when flat, with a 0.50% distance.

## 12. Statistics and reporting

- **Per fold:** model and baseline metrics, the model's percentile among the random runs, and the cost sensitivity.
- **Across folds:**
  - chained test-window returns, compared with chained buy-and-hold;
  - the number of folds beating buy-and-hold, with a one-sided sign-test p-value;
  - mean Sharpe ratio and worst drawdown;
  - total number of trades.
- **Signal check:** per (feature, distance, bin), TP-rate confidence intervals from a block bootstrap (whole weeks resampled together). The report also gives the number of training passes expected by chance.
- Results are reported as observed, including negative results.

## 13. Stopping rules

1. **Signal check (step 07).** STOP or pivot if no bin passes both conditions below, at any affordable training distance:
   - its training TP rate's lower 95% bound is above that distance's break-even TP rate;
   - it passes the same test on validation, using the same bin edges.

   The break-even rate is the TP rate needed to break even after costs (§5).
2. **Walk-forward (step 08).** STOP or pivot if the model fails to beat both buy-and-hold and the random-entry baseline across the historical folds.

   Possible pivots, each a new protocol version:
   - a coarser bar size;
   - different SL/TP distances or risk/reward ratio;
   - a different holding limit;
   - new features.

## 14. Discipline against luck and leakage

- **Trial log.** Every signal check, validation candidate and test evaluation is appended to `store03_goldzone/trial_log/trial_log.csv`. Each entry records the config hash, the windows, the settings, the metrics, and whether the test window was looked at.
- **Use `validation_only` mode while changing the design.** Test windows are evaluated (`latest` or `history`) only once a design is frozen under its experiment name.
- **Any design change after seeing test results means a new experiment name.** The previous test windows then count as seen for that line of work.
- **Only data arriving after the last design change is truly unseen.** The moving latest window provides it.
- **Look-ahead tests** (`tests/run_tests.py`):
  - context features are identical on truncated data;
  - target cells equal simulated trades;
  - gaps between windows hold.

  A sandbox run also showed that features computed on whole days (rather than per-minute snapshots) fabricate large profits on a random walk. Keep that in mind when adding features.

## 15. Known limitations

- Dividends are ignored in both the model and the benchmark (this favors the model).
- The cost figures are informal assumptions; there is no measured fill data yet.
- The break-even TP rate assumes exits exactly at the barriers. Gaps through the stop loss make real losses larger, so it is optimistic.
- The labels' per-share fee assumes orders of at least 200 shares. The simulator uses exact order fees.
- SL/TP are rounded to $0.001 (kept from the previous step 12 target code) while prices move in $0.01 steps.
- Trading days are counted on the sessions in the data (2007-07-02 is missing).
- Absolute-dollar features are excluded until scaling is designed.
- VIX is not included.
- The parameter values of the price-action pipeline were chosen visually.

## 16. Open decisions

- The model output format (§10 is a proposal).
- The scaling design (ATR-relative and similar transforms) for absolute features.
- Dividends: avoid ex-dates, or hold through them and collect the dividend.
- Risk/reward ratios other than 1, and pivots of bar size or holding limit.
- Higher slippage on event days.
- VIX and other external context.

## 17. Change log

| Version | Date | Change |
|---|---|---|
| 1 | 2026-10-01 | Initial protocol from the design discussion |
| 1.1 | 2026-10-01 | Editorial only, no rule changed: new workspace with restarted step numbers (00 PA snapshots, 01 TSIND, 02 TSSEG, 03 TSCTX, 04 TSBAR, 05 model dataset, 06 signal check, 07 walk-forward) and new data paths (see README). Results produced under version 1 remain comparable |
| 1.2 | 2026-10-04 | Editorial only: step numbers updated to the final numbering (data quality check = step 00, so every later step +1); status line added (stopped 2026-10-04, see `docs/RESULTS_LOG.md`) |
