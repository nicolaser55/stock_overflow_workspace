# Stock Overflow — How the Pipeline Works Today

*Snapshot: 2026-10-01. Covers the data, the derived columns (steps 00, 06, 08), the target matrix (step 12) and the trading simulator. Nothing here is a recommendation. It records what the code does, what the outputs show and what Nicolas has said.*

> **Numbering note.** Sections 0–12 use the step numbers of the **previous** workspace, because they describe that code as it was. The new workspace (§14) restarts the numbering: old step 00 → new **step 01**, old step 06 (TSIND) → **step 02**, old step 08 (TSSEG) → **step 03**, the old step 12 target → superseded by **step 05** (TSBAR). The data quality check is step 00.

**Evidence tags**

- **[code]** — I read it in the source.
- **[run]** — I ran the code on synthetic data and checked it.
- **[output]** — Seen in a saved notebook output.
- **[stated]** — Nicolas said it.
- **[doc]** — From the design document. When the code and the documents disagree, the code wins [stated].
- **[inferred]** — My inference. Not verified.

---

## 0. Status at a glance

| Component | Status | Source |
|---|---|---|
| Raw IBKR 1-minute bars (rawzone) | Current | [output] |
| Step 00: per-day snapshot cache of price-action columns | Current | [code][output] |
| Step 06: TSIND, one indicator row per minute (43 fields + `date`) | Current, generated for all 5,436 sessions | [output] |
| Step 08: `cum_max` + TSSEG, one segment row per minute | Current, generated for all 5,436 sessions | [output] |
| Step 12: `TS_delta_matrix_sell` target matrix | Current target definition | [stated][output] |
| `TradingAgent` + per-strategy loop | Current simulator. Being changed to allow holding across days | [stated] |
| Steps 01–05 (segment data, TSSLTP, TSSLTP score, TSSLTP_BS), 07/09 (scaling), 10 (features), 11 (buy-limit labels), 12 (BS eval), 14, 16, 17, store04 | Run earlier and abandoned ("results were not ideal") | [stated] |
| 14 textbook strategies (strat01–14) | Set aside. The design doc says they underperformed buy-and-hold, but no numbers were reviewed | [stated][doc] |
| Qualitative/text data | Planned, after the quantitative part is finished | [stated] |
| Scaling features to [0, 1] | Planned. The earlier scaling steps were abandoned | [doc][stated] |
| Fees in P&L, a possible `NULL` outcome for zero net profit | Planned | [stated] |

---

## 1. Objective

- Trade one instrument (SPY), long only, one position at a time. Each trade is: decide to buy → buy → set a stop loss (SL) and take profit (TP) → exit at whichever is hit first → repeat [doc].
- Goal: find entries, and SL/TP settings for them, where TP is hit much more often than SL, and the result holds up out of sample [project description].
- Hypothesis as written: technical indicators plus qualitative reports are significantly related to SPY's price direction at the 1-minute level. The qualitative half is deferred [doc][stated].
- Live constraint: nothing after minute t may be used at minute t, because a live model cannot see it [stated].

---

## 2. Data

| Item | Value | Source |
|---|---|---|
| Instrument | SPY | [stated][doc] |
| Source | Interactive Brokers API (`ibkr_ohlcv_data/`) | [code][doc] |
| Adjustment | Not adjusted for splits or dividends | [stated] |
| Bar size and session | 1 minute, regular hours only. The first bar is 09:30 and the last is 15:59 (New York time). Bars are labeled by their start time [inferred, consistent with IBKR] | [output] |
| Span | 2005-01-03 09:30 to 2026-08-13 15:59 | [output] |
| Size | 2,111,791 bars over 5,436 sessions. The calendar expects 5,437; 2007-07-02 could not be pulled from IBKR | [output][stated] |
| Time zone | Parsed as UTC, converted to America/New_York. `date` = New York calendar date | [code] |
| Cleaning | About 7 bars with absurd highs/lows were corrected by hand directly in the raw files. Not to be scrutinized further | [stated][code, commented-out cells in step 08] |
| `created_ts` | Raw column, reserved for live ingestion later | [stated] |
| Minutes per session | **Not verified.** `get_date_ohlcv_DQ_info_pdf` would crash (see Issue 7), and every rolling window counts rows, not clock minutes | [code] |
| Storage | One CSV per day, in rawzone, workzone and goldzone folders under `/Users/nico/Desktop/stock_overflow_data/` (a mounted Google Cloud Storage copy also exists) | [code] |

`format_ohlcv_pdf` does three things [code]:

- It rejects exact duplicate rows. Rows that share a timestamp but differ in values are not checked.
- It converts timestamps to New York time.
- It expects `date` to exist already (the notebooks create it).

---

## 3. The snapshot ("prefix") design

- For each session, step 00 builds 390 growing snapshots: bars 0..0, 0..1, …, 0..k [code].
- `add_PA_cols` runs separately on every snapshot. All snapshots are stacked into `ohlcv_data_YYYYMMDD.csv`, with `pdf_id` = k [code].
- Steps 06 and 08 read this cache. If a day's file is missing, they build it [code].
- **Every saved TSIND/TSSEG row for minute t is computed only from snapshot t, which holds bars 0..t of the same session.** The one exception is `cum_max`, which looks back over all history up to t. Nothing from after t is used, assuming the decision is made at the close of bar t [code].
- Every session starts cold. No rolling window carries over from the previous day, except `cum_max` [code].
- Saving and re-reading the cache gives identical values (checked on 2026-02-05) [output].

---

## 4. Step 00 — price-action columns (`add_PA_cols`)

Chain and defaults [code]:
`avg_price → atr(10) → smooth_price(window 4) → extremas(order 3) → extremas_pp → composite_price(weight 0.4) → slope → trend(±0.01) → segment`.

| Column | Definition [code] |
|---|---|
| `avg_price` | `(high + low) / 2`, rounded to 6 decimals |
| `atr` | 10-bar simple average of true range. NaN for the first 9 bars |
| `smooth_price` | 4-bar average of `avg_price`, shifted so that row i holds the mean of bars i−2..i+1. The last row of any snapshot is NaN. Rows 0–1 are filled with a straight line once the snapshot has at least 4 bars |
| `minima` / `maxima` | Bar i is a swing low if `low[i]` is the lowest low in bars i−3..i+3. Swing highs use `high` the same way. Then close-together swings are thinned (below). Row 0 is always forced to be a swing at that bar's low/high |
| `extremas_pp` | `avg_price` at each swing bar, plus row 0 and the last row, with straight lines in between |
| `composite_price` | `0.4·smooth_price + 0.6·extremas_pp`. The 0.4 was chosen by eye [stated] |
| `composite_price_slope` | Change in `composite_price` from the previous bar, in $ per bar |
| `trend` | 1 / 0 / −1. The dead zone is ±$0.01 per bar. Row 0 copies row 1 |
| `segment` | A counter that goes up by one each time `trend` changes |

**Swing detection, in plain terms** (answering your question about "thinning") [code][run]:

- Detection only checks bars 3 .. n−4 of a snapshot, because it needs 3 bars on each side. So a swing at bar i first appears in the snapshot ending at bar i+3.
- **Bars 1 and 2 can never be swings.** The .md says they can sit next to the forced swing at bar 0; that is wrong.
- Two swings 1–3 bars apart can only happen when the bars tie exactly in price. When two swings are 2 bars apart or less, the code deletes the later one.
- The deletion works on the original list of gaps, all at once. So with a chain of ties, every mark after the first is deleted. Checked by running the code:
  - lows tied at bars 5, 6 and 7 → only bar 5 survives;
  - lows tied at bars 5, 7 and 9 → only bar 5 survives, even though bar 9 is 4 bars from bar 5.
  - The .md says "a run of three only drops the second", which is wrong.
- Once a swing is confirmed it never changes or disappears in later snapshots. That follows from the code, and `validate_extremas_ohlcv_pdf_list` passed on 2026-02-05 [output].

**Which columns get revised as new bars arrive (by design)** [code][doc][stated]:

- Stable once known: `avg_price`, `atr`, confirmed swings, and `smooth_price` (after its value stops being NaN).
- Revised: the stretch of `extremas_pp` between the last confirmed swing and the current bar, and therefore `composite_price`, `composite_price_slope`, `trend` and `segment` ids.
- Example from saved output: `extremas_pp` on row 1 of 2026-02-05 was 679.9 → 679.9225 → … → 680.4425 as the snapshot grew [output].
- The full-day frame (the last snapshot) therefore contains values that were revised with hindsight. It is used for plots. It is not used for TSIND/TSSEG rows [code].

---

## 5. Step 06 — TSIND (`get_TSIND_dict`)

On each snapshot t, the code runs `add_SO_cols → add_MACD_cols → add_RSI_col → add_DC_cols → add_BB_cols → add_cs_attribute_cols` and `detect_market_structure`. It keeps one row of fields [code].

**What the five lagged price-action fields really equal**, for snapshots of more than one bar [code]. They are read from the second-to-last row of snapshot t:

- `smooth_price[t]` = mean(`avg_price` over bars t−3..t). This is a plain trailing 4-bar average; the forward shift cancels out. NaN for t < 3.
- `composite_price[t]` = 0.4·`smooth_price[t]` + 0.6·`extremas_pp` at row t−1, *as drawn in snapshot t*.
- `composite_price_slope[t]` = composite at row t−1 minus composite at row t−2, both taken from snapshot t.
- `trend` and `segment` come from that slope. Segment ids are the numbers snapshot t had assigned, which may differ from the full-day numbering.
- `extremas_pp` is taken from the last row, so it equals `avg_price[t]`.

**Columns (43 + `date`)** [code][output]:

| Group | Fields | Notes [code] |
|---|---|---|
| Raw bar | `timestamp, open, high, low, close, volume, avg_price` | Bar t |
| Price action | `smooth_price, extremas_pp, composite_price, composite_price_slope, trend, segment` | As above |
| Volatility / candle shape | `atr, color, span, body_span, bot_wick_pct, body_pct, top_wick_pct` | `color` = 1 if close ≥ open (a doji counts as green). The `*_pct` columns are fractions; when span = 0 they are 0 |
| Stochastic | `stoch_k, stoch_d` | 14-bar %K and 3-bar %D, both computed from bar 1. %K is NaN, not infinity, when the 14-bar range is 0 |
| MACD | `macd, signal, histogram` | Exponential averages of `close` (12/26/9) |
| RSI | `rsi` | Simple-average RSI over 14 bars, not Wilder's version. NaN on bar 0 and on flat windows. 100 or 0 on one-sided windows |
| Bollinger | `bb_width, bb_bot, bb_mid, bb_top, bb_pct` | 20 bars, sample standard deviation, NaN for the first 19 bars. `bb_pct` is %B as a fraction |
| Donchian | `dc_width, dc_bot, dc_mid, dc_top, dc_pct` | 20 bars, NaN for the first 19. The window includes the current bar, so `dc_pct` is always between 0 and 1 (NaN if the width is 0). The .md suggests it can go outside [0, 1]; it can't |
| Market structure | `current_minima, current_maxima, ms_minima_trend, ms_maxima_trend, ms_low_status, ms_high_status, ms_trend` | Each side needs at least 2 swings (row 0 counts as one). The two trend fields compare the last two swing prices; on a tie the code walks further back. `ms_trend` is set only when both sides agree. Break of structure / change of character compare bar t's low/high with the latest confirmed swing, which is at least 3 bars old |

**Other notes**

- Columns in absolute dollars, so their scale grows as the price went from about $120 to about $780 [code]: OHLC, `avg_price`, `smooth_price`, `extremas_pp`, `composite_price`, `composite_price_slope`, `atr`, `span`, `body_span`, `macd`, `signal`, `histogram`, `bb_*` (except `bb_pct`), `dc_*` (except `dc_pct`), `current_minima`, `current_maxima`.
- Columns that are ratios or bounded [code]: the candle `*_pct` columns, `stoch_*`, `rsi`, `bb_pct`, `dc_pct`.
- Categorical columns [code]: `color`, `trend`, `segment` (a counter), and the `ms_*` strings.
- Text columns are saved to CSV. When read back, `""` (meaning "no agreement / not enough swings") becomes NaN, so it can no longer be told apart from the NaN status fields [output].
- Support/resistance levels and trend-line slopes are coded in `tf_ohlcv_tools.py`. The calls are commented out ("sometimes null"), so they are not in TSIND [code].

---

## 6. Step 08 — `cum_max` and TSSEG (`get_date_TSSEG_pdf`)

- `cum_max` = running maximum of `high` over the whole dataset (2005 onward), including bar t. It is stored per year and looked up by timestamp [code][output].
- The loop runs over snapshots. When the count of swing lows or swing highs goes up (a swing confirmed 3 bars after the swing bar), it does three things [code]:
  - It moves the anchor to the latest swing bar.
  - It sets the anchor price to that bar's `avg_price`.
  - It adds 1 to `seg`.
- Because swing bars appear in time order, the newest confirmed swing is always the latest bar [code].

| Column | Definition [code] |
|---|---|
| `minima_count`, `maxima_count` | Number of swing lows/highs in snapshot t, including row 0 |
| `prev_seg_delta` | `avg_price[t]` − anchor price ($) |
| `prev_seg_delta_pct` | The same as a fraction of the anchor price |
| `seg_cs_count` | t − anchor bar. It is 0 at the open, then counts up, and resets to **3** each time a swing is confirmed. It never takes 1 or 2 after a reset |
| `seg` | Number of anchor placements since the open (1 at the open) |

Plus the raw bar columns, `avg_price`, `cum_max` and `date` (15 columns) [output].

---

## 7. Step 12 — the target matrix (`TS_delta_matrix_sell`)

`get_date_ts_buy_sell_info_data_pdf(complete_ohlcv_pdf, date, FULL_DELTA_LIST, rr_ratio=1)`, pivoted to one row per bar [code][output].

- **Rows:** every bar of every session, including 09:30 and 15:59: 2,111,791 rows and 36 columns (`buy_ts, buy_price, rr_ratio`, 32 delta columns, `date`) [output].
- **Entry:** `buy_price = open of bar t` (`buy_ts = t`) [code].
- **Barriers per delta d:**
  - `TP = round(buy·(1+d), 3)`
  - `SL = round(buy·(1 − d·rr), 3)`, with `rr = 1`, so the two are symmetric. An rr of 0.5 is present but commented out.
  - Rounding is to $0.001, while prices move in $0.01 steps [code].
- **Deltas:** 32 values in total [code]:
  - 21 "TRAIN" values, log-spaced from 0.10% to 1.00% (`0.001·10^(k/20)`);
  - 5 smaller "diagnostic" values (0.05%–0.09%);
  - 6 larger "diagnostic" values (1.12%–2.00%).
- **Search:** starts at bar **t+1**, so the entry bar's own high and low are never checked. It runs forward through **all later data, across days, with no time limit**, until the dataset ends [code].
  - SL is hit if `low ≤ SL`; TP is hit if `high ≥ TP`.
  - The first hit wins; if both are hit on the same bar, SL wins.
  - The exit price is exactly the SL or TP price, even when the next day opens past it [code].
- **Never resolved:** the trade is closed at the dataset's last open (777.66). It is labeled `D_TP` if that price is above entry, otherwise `D_SL` [code][output].
  - `get_SLTP_regeneration_date` finds the earliest date still unresolved at the largest delta. This is valid because larger deltas strictly contain smaller ones when rr is fixed [code][inferred].
  - Currently that date is 2026-08-04 [output], so rows from 2026-08-04 onward are not final and will change as new data arrives.
- **Cell format:** `"hold_minutes|sell_price|action"`. The hold time is in **clock minutes**, including nights and weekends: for example, 7,105 minutes for 2005-01-28 15:59 at a 2% delta [code][output].
- **Learning target:** the matrix records outcomes. The exact y a model would learn from it (for example, buy/no-buy, a chosen delta, or a TP probability for each delta) is not in code yet [inferred]. See Open question 3.
- **Leftovers in the same notebook:**
  - It still loads abandoned step 03 (TSSLTP, 2015-01-02 → 2025-03-31) and step 11 (buy-limit labels `lim_0.50`–`lim_1.00`, 2015-01-02 10:00 → 2025-04-01) to plot ideal versus predicted buys.
  - `sample_y_pred_arr` is a hand-made 360-minute example array (10:00–15:59).
  - A later cell recomputes `action` from the sign of profit [code][output].

---

## 8. Trading simulator (`TradingAgent` + strategy loop)

How the loop actually behaves (checked with a run in which a dip on the fill bar triggers SL on that same bar) [code][run]:

1. **At bar t, with no position:** the strategy checks for a signal on snapshot t.
   - It builds SL/TP with `generate_SLTP_order_dict`: SL = latest swing low below the bar's midpoint, TP = latest swing high above it. If no swing qualifies, the fallback is the 400-bar min/max.
   - It validates them against `avg_price[t]` with `set_SLTP`. Validation rejects risk/reward ratios (risk ÷ reward) above 5.
   - It places a market buy order with `set_buy_order(t)`.
2. **At bar t+1:**
   - `check_buy` fills at **`avg_price[t+1]`**, the midpoint of the fill bar.
   - In the same step, `check_sell` checks **bar t+1's** low and high against SL and TP. SL wins ties, and the exit is at exactly the level.
   - So the fill bar is checked for exits, while the SL/TP were validated against a different price (`avg_price[t]`).
3. A trade is labeled TP if profit > 0, otherwise SL, so a profit of exactly 0 counts as SL [code]. A `NULL` outcome after fees is being considered [stated].
4. Fees are ignored in profit. `calculate_transaction_fee` exists ($0.005 per share per side, $1 minimum per side, 1% maximum) but is never called [code]. To be fixed [stated].
5. Current intraday rules, which are being removed in favor of holding across days [stated]:
   - forced exit at `avg_price` on **15:57** (the third-to-last bar, not the second-to-last as the .md says) [run];
   - limit buys blocked from 15:48;
   - market buys blocked only from 15:57 [code].

**How the target matrix and the simulator differ** [code]:

| | Step 12 target | TradingAgent + loop |
|---|---|---|
| Entry price | Open of bar t | Midpoint of bar t+1 (signal at t) |
| Entry bar checked for exit | No (search starts at t+1) | Yes (the fill bar is checked) |
| SL/TP construction | Symmetric % of entry, rr = 1, 32 deltas | Swing-based levels; risk/reward ≤ 5 |
| Rounding | $0.001 | None |
| Time limit | None, across days | Intraday, forced exit at 15:57 (being changed) |
| Same-bar tie | SL | SL |
| Exit price on gaps | Exact level | Exact level |
| Fees | None | None |
| Outcome label | Which level was hit; `D_` by sign at dataset end | Sign of profit |

---

## 9. Supporting modules (verified)

- `datetime_utils`:
  - NYSE calendar via `pandas_market_calendars`; schedule close = official close minus 1 minute.
  - `get_date_pdf` filters by `date`.
  - `find_pdf_ts_idx` picks a snapshot by position or timestamp [code].
- `local_file_management`:
  - Write modes: `I` skip if exists, `W` overwrite, `A` append, `N` don't save.
  - `generate_func_data_date_list` / `_range` run a per-day function, add `date` and save `{name}_YYYYMMDD.csv`.
  - `check_file_exists` returns True for any path without a "/" [code].
- `data_quality`:
  - type and column checks, binning, histograms, `remove_null_rows_pdf`;
  - `get_pdf1_pdf2_diff_list` stops at the first difference it finds (see Issue 13) [code].
- `tf_ohlcv_tools`: the indicators above, plus support/resistance and trend-line functions, which TSIND does not use [code].

---

## 10. Known issues and your decisions on them

| # | Issue | Evidence | Your decision |
|---|---|---|---|
| 1 | The .md describes swing thinning wrongly (§4) | [run] | Fix the doc |
| 2 | The .md says bars 1–2 can be swings; they can't | [code] | Fix the doc |
| 3 | Forced exit at 15:57, not the second-to-last bar | [run] | Behavior being removed |
| 4 | The final-buy cutoff only applies to limit orders | [code] | Matters less once holding across days |
| 5 | `validate_der_price_ohlcv_pdf_list` never compares anything (it stores NaN first, then skips NaN) | [code] | Noted |
| 6 | `""` becomes NaN after the CSV round trip in the `ms_*` text columns | [output] | Noted |
| 7 | `get_date_ohlcv_DQ_info_pdf` calls the wrong aggregation function (no `ts_count`), so minutes per session were never checked | [code] | Noted |
| 8 | Fees not included in profit | [code] | To fix |
| 9 | A profit of exactly 0 is labeled SL | [code] | Maybe add a `NULL` outcome after fees |
| 10 | The design doc's TSIND list (41 columns, missing `high` and `extremas_pp`) and its step numbering don't match the code | [doc][code] | Later |
| 11 | The step 08 notebook output shows old column names (`s1_ma4`, `der_price`). TSSEG only uses `minima`, `maxima` and `avg_price` | [output] | Fix later |
| 12 | `generate_SLTP_order_dict` never writes the adjusted SL back (that branch currently can't run) | [code] | Keep in mind |
| 13 | `get_pdf1_pdf2_diff_list` returns after the first difference. Step 00 cell 36 indexes `diff_list[3]` | [code] | New |
| 14 | The .md says Stochastic can be "infinity" and that `dc_pct` can leave [0, 1]; neither can happen | [code] | New (doc) |
| 15 | The agent validates SL/TP against `avg_price[t]` but fills at `avg_price[t+1]` | [code][run] | New |
| 16 | Target SL/TP are rounded to $0.001; prices move in $0.01 steps | [code] | New |
| 17 | Target hold time counts clock minutes, including nights and weekends | [code][output] | New |
| 18 | The target buys at the open of bar t but never checks bar t itself for SL/TP | [code] | **Intended**: SL/TP become active one bar after the buy (§11.4) |
| 19 | Target rows from 2026-08-04 onward are unresolved at the largest delta and will change | [output] | New |

---

## 11. Decisions recorded on 2026-10-01 [stated]

1. **The code is the reference**, not the .md or the design document (this includes swing detection and thinning).
2. **Feature/target alignment:** feature row t (snapshot ending at bar t) pairs with target row **t+1**. Example: the signal comes from the 12:41 features, and the buy is at the open of the 12:42 bar.
3. **Simulator entry:** the simulator will buy at the **open of the next bar** after the decision, the same as the step 12 target.
4. **SL/TP become active one bar after the buy.** They are not checked on the entry bar, so one large entry candle can't trigger an exit immediately. This is exactly what step 12 already does, because its search starts at t+1. **Issue 18 is therefore intended, not a defect.**
5. **What the model decides:** buy or don't buy, and if it buys, the SL/TP setting chosen at the time of the buy. The exact shape of the output is still open, as long as it carries that information.
6. **Risk/reward:** only rr = 1 (symmetric) for now. Other ratios may be tested later.
7. **Holding across days is allowed.** The intraday forced exit is being removed.

### Further decisions recorded on 2026-10-01 [stated]

8. **Fills past a level:** if a bar opens already beyond a level (an overnight gap, or a move during the entry bar), the exit is at **that bar's open**, not at the level. (This differs from the current step 12 code and simulator, which always exit at the level.) I am assuming this applies to TP as well as SL.
9. **No overnight carry of signals:** the 15:59 feature row cannot trigger a buy at the next session's 09:30 open.
10. **Maximum holding time: 10 days.** (Step 12 currently has no limit.)
11. **Dividends:** handled by not trading near known ex-dividend dates.
12. **Position size:** evaluation assumes the share count that maximizes profitability (which also changes the fee per trade).
13. **Final test set:** the most recent dates are held out.
14. **Trading window:** the model only starts making decisions 30 minutes after the open.
15. **Model output format:** to be chosen together at the design stage.

### Decisions recorded on 2026-10-01, third round [stated]

16. **Maximum hold:** 10 **trading** days. When the limit is reached, the position is sold at the **close of the last bar**.
17. **Dividends:**
    - Ex-dividend dates will come from IBKR or another source.
    - Whether to stop buying before ex-dates or to deliberately hold through them to collect the dividend depends on which gives better performance. This is still undecided, and testing it requires the simulator to credit dividends.
18. **Account:** the size doesn't matter yet; the goal for now is to show the idea is viable. The account compounds, growing and shrinking with past trades.
19. **Fills at the open** include a spread or slippage cost. The amount is still to be chosen.
20. **Data splits:** a validation period, plus a final test period taken from the most recent data ("the last 6–3 months"; the exact boundaries are open question 1).
21. **First possible buy:** the 10:00 open, decided from the 09:59 feature row.

### Decisions recorded on 2026-10-01, fourth round [stated]

22. **Splits:** final test = the last 3 months; validation = the 3 months before that; training = everything before validation.
23. **Holding limit:** the buy day counts as day 1 of the 10 trading days.
24. **Dividends:** ignored for now, to be revisited later. This replaces decisions 11 and 17 for the time being.
25. **Spread and slippage assumptions** come from the figures Nicolas supplied. His cited sources are a mix of trading guides, a broker page and forum threads. These are assumptions, not measurements on this dataset.
    - Typical SPY bid/ask spread: $0.01.
    - Slippage for orders under 1,000 shares: $0.00–$0.01 per share.
    - Slippage for orders over 5,000 shares: $0.01–$0.02 per share.
    - Around major macro events (CPI, FOMC): $0.05–$0.15 or more.
    - Note [inferred]: the quoted "0.0015–0.0020% of price" only matches recent prices. $0.01 is about 0.0013% at $777, but about 0.008% at $120 (2005).

### Decisions recorded on 2026-10-01, fifth round [stated]

26. **Cost rule:**
    - entry at the open pays +$0.01 per share;
    - SL exits and expiry exits receive −$0.01 per share;
    - TP limit orders fill at the TP price, but only if price trades at least $0.01 beyond TP;
    - IBKR fees as in `calculate_transaction_fee`.
27. **The splits move with the data.** Test = the most recent 3 months and validation = the 3 months before, always relative to the latest available data. The aim is for the model to keep working as new data arrives, because it will run live.
28. **Macro-event slippage** (CPI, FOMC) is ignored for now.
29. **IBKR's Adaptive algorithm** may be used live. For now, backtests keep the $0.01 cost rule; see §12.
    - Checked against IBKR's own pages on 2026-10-01: the Adaptive algo page says it aims for "a fast fill at the best all-in price" and that "on average" it gives "better fill prices than using regular market or limit orders". It notes it is "most useful … when the spread is wide, but can also be helpful when the spread is only one tick". Neither page claims slippage is eliminated or that fills are guaranteed.
    - The SmartRouting page reports net trading costs of 0.021% of trade value (August 2026) measured against VWAP. That is a broker-wide average and is not comparable to the per-share SPY spread assumption.
30. **Purpose of the moving test window:** to track how the model performs on new data over time in a simulated environment, before and alongside live use.

### Design decisions recorded on 2026-10-01 [stated]

31. **Definition of success:** a higher total return than buy-and-hold over the same period, after costs. (No tax applies in Nicolas's jurisdiction, Qatar.)
32. **Stopping rule:** stop or pivot if the single-feature signal check finds nothing at any SL/TP distance that is affordable after costs.
33. **Sampling and splits:** 10-trading-day gaps between train, validation and test; entries sampled every N minutes or on events, or overlapping labels down-weighted; uncertainty measured by resampling whole days or weeks; the number of non-overlapping trades reported with every result.
34. **Scaling** (ATR-relative for distances and other choices) is postponed until the general design is settled.
35. **Training window:** the most recent 10 years before validation, rolling forward with the current date.
36. **A trial log** records every experiment.
37. **The benchmark ignores dividends** for now, because dividend data isn't available yet. *Known limitation:* SPY yields about 1.2–2% a year, so a price-only buy-and-hold benchmark understates what a real investor earned. That makes the comparison lean in the model's favor, and the thesis must say so.
38. **Cash earns no interest** between trades.
39. **Secondary results:** Sharpe ratio and maximum drawdown, reported alongside total return.
40. **Walk-forward over history is required.** The full procedure (train, validate, test) is replayed through past years as if running live at the time.
41. **The training-window length is a setting to tune.** This replaces decision 35, which fixed it at 10 years.

## To do

- Add context features: minutes since the open, day of week, overnight gap, previous day's return and range, distance to the previous day's high and low, return since today's open, multi-day volatility, and possibly VIX (external data).
- Design the scaling (deferred, see 34).
- Regenerate the step 12 target matrix with the new rules: exit at the bar's open when price has gapped past a level, a 10-trading-day limit with exit at the close, and the cost rule.
- Update the simulator: next-bar-open entries, SL/TP active from the bar after entry, multi-day holding, fees, the cost rule, and a NULL outcome.
- Fix the known code and documentation issues as needed (§10).
- Write the research protocol.

## 12. Open questions

None at the understanding stage.

**Notes carried into design** [inferred]:

- **Moving splits mean a test window is used up once it has been looked at.** If design choices are adjusted after seeing results on a test window, that window has effectively become validation. Only data that arrives *after* the last design change is truly unseen, which is what forward or paper trading provides.
- **Adaptive algo orders are patient and may not fill at the bar's open.** Fills can come later, at a different price, or not at all. Patient orders also tend to fill more often when price moves against the order (adverse selection). For a stop loss, waiting means more risk. Treat zero cost as the best case and $0.01 as the base case. A sensitivity run at $0.00, $0.01 and $0.02 would cover the range.

## 13. Implementation (2026-10-01)

The decisions in §11 were first implemented as steps 18–23 appended to the previous workspace (`README.md`, `docs/RESEARCH_PROTOCOL.md`). Two notes:

- **Superseded by the new modules.** The §8 simulator behaviour (midpoint fills, the fill bar checked for exits, intraday dumping at 15:57) and the §7 target rules (exit at the level after gaps, no time limit) are replaced by `trade_execution.py`, `barrier_labels.py` and `backtest_simulation.py`. The step 12 matrix stays on disk for reference (`paths.LOCAL_LEGACY_TS_DELTA_MATRIX_SELL_DATA_FILE_PATH_STR`).
- **Issue 7 (`get_date_ohlcv_DQ_info_pdf`) is fixed.** The other issues in §10 are still open.

## 14. New workspace — fresh start (2026-10-01) [stated]

Nicolas asked for a new workspace with its own data folder (`C:/Users/nico/Desktop/stock_overflow_data/`), only the paths that are still relevant, and step numbers restarted from 00 instead of continuing at 18. A first renumbering left the data quality check unnumbered; Nicolas then made it step 00 and shifted every later step by one, renaming the notebooks, the data folders and `paths.py` accordingly. The table shows the final numbering.

| New | Notebook | Previous equivalent | Output folder |
|---|---|---|---|
| 00 | `step00_data_quality_check.ipynb` | step 18 | `store02_workzone/step00_data_quality_report/` |
| 01 | `step01_PA_ohlcv_data_collection.ipynb` | step 00 (`step00_label_ohlcv_data`) | `store02_workzone/step01_PA_ohlcv_data/` (existing cache, renamed) |
| 02 | `step02_TSIND_data_collection.ipynb` | step 06 | `store02_workzone/step02_TSIND_data/` (files copied from the old step 06) |
| 03 | `step03_TSSEG_data_collection.ipynb` | step 08 (`cum_max` now computed in memory) | `store02_workzone/step03_TSSEG_data/` (files copied from the old step 08) |
| 04 | `step04_TSCTX_data_collection.ipynb` | step 19 | `store02_workzone/step04_TSCTX_data/` |
| 05 | `step05_TSBAR_data_collection.ipynb` | step 20 (replaces the step 12 target) | `store03_goldzone/step05_TSBAR_data/` |
| 06 | `step06_model_dataset_generation.ipynb` | step 21 | `store03_goldzone/step06_model_dataset_data/` |
| 07 | `step07_signal_check.ipynb` | step 22 | `store03_goldzone/step07_signal_check_data/` |
| 08 | `step08_walk_forward_evaluation.ipynb` | step 23 | `store03_goldzone/step08_walk_forward_data/` |
| 09–12 | protocol v2 (stop and re-entry) | — | see `docs/RESEARCH_PROTOCOL_v2.md` |
| 13 | `step13_ath_exit_exploration.ipynb` | — | exploration, see `docs/RESULTS_LOG.md` |

What changed in the code (and what did not):

- **Snapshot functions moved, logic unchanged [run].** `generate_date_PA_tf_ohlcv_pdf`, `validate_extremas_ohlcv_pdf_list`, `get_TSIND_dict`, `get_date_TSIND_pdf` and `get_date_TSSEG_pdf` moved from the step 00/06/08 notebooks into `snapshot_features.py`. The notebook globals became arguments. On three synthetic sessions, the extracted original notebook functions and the module produce identical DataFrames (exact comparison). So existing TSIND/TSSEG files can be copied into the new step02/step03 folders instead of being regenerated. They were copied. Spot check on 2026-10-04: 5 random TSIND files were identical to files regenerated with the current code. The TSSEG check is still to be run (last cell of `step03_TSSEG_data_collection.ipynb`).
- **`buy_eval_utils.py` rewritten [code].** The previous version read the abandoned TSSLTP (old step 03) and buy-limit (old step 11) tables and drew buys at the decision bar's average price. It now reads TSBAR, draws buys at the entry (next open) and draws SL/TP lines to the resolved exit.
- **`plot_ohlcv_utils.py` fixed [run].** The subplot helper tested `"grid" in fig.layout`, which is always true in Plotly, so it never routed traces to subplot rows. It now uses the figure's subplot grid. The time-limit exit got its own marker. The import of the legacy `trading_simulation.py` was removed, and `trading_simulation.py` is no longer part of the workspace.
- **Paths [stated].** The GCS paths and every path of abandoned steps were removed. The textbook-strategy folders (strat01–14) and the step 12 target folder stay as read-only legacy references.
- **Other changes to the original modules [code].**
  - *Config wiring:* the default arguments of `ohlcv_data_utils.py` and `tf_ohlcv_tools.py` now read `config.py`, with identical values (tested). The hard-coded `bias_float = 0.4` of `add_composite_price_col` became the parameter `bias_float_in`; the MACD spans and the Bollinger multiplier became parameters.
  - *Fix:* `get_date_ohlcv_DQ_info_pdf` called `get_date_ohlcv_agg_pdf` (no `ts_count` column). It now calls `get_date_ohlcv_agg_info_pdf`.
  - *Additions:* `get_ohlcv_sanity_issue_pdf`; in `local_file_management.py`, `get_date_range_file_path_list`, `read_date_range_csv_files_from_path` and `get_missing_date_list` (moved from the notebooks).
  - *`plot_ohlcv_utils.py` details:* `get_row_col_tup` was replaced by `get_row_col_dict`; every `fig_add_*` function except `fig_add_buy_order_line` accepts `row_in` / `col_in`; `fig_add_transaction` accepts an exit reason; `plot_ohlcv` resolves SL/TP with `trade_execution.resolve_barrier_exit_dict`; new `plot_transaction_ohlcv`.
  - *`setup_venv.py`:* lists the requirements files by number, takes `--name` / `--requirements` / `--kernel`, upgrades pip, refuses a non-3.12 venv, and can register a Jupyter kernel.
  - *`.cursorignore` / `.gitignore`:* venvs, caches, data files, credentials (`GCS_key.json`) and OS files are excluded.

## 15. After the rebuild

The experiments run in this workspace, their protocols and their results are recorded in:

- `docs/RESEARCH_PROTOCOL.md`: v1, steps 05–08, **stopped**;
- `docs/RESEARCH_PROTOCOL_v2.md`: v2 stop and re-entry, steps 09–12, **stopped**;
- `docs/RESULTS_LOG.md`: every result, including the step 13 "sell at strength" exploration.

The raw minute bars themselves were corrected once, on 2026-10-04: 62 bad wicks (2005–2009) were cut to the bar body by `fix_raw_bad_ticks.py`. Steps 09–13 were rerun, and the v1 tables (steps 01–06) were regenerated for every date that can depend on a corrected cell, then checked against a full rebuild of the model dataset (5,436 of 5,436 days identical); see `docs/RESULTS_LOG.md`, "Data corrections".
