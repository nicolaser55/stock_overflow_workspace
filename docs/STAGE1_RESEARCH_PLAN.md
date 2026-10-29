# Stock Overflow: stage-1 research plan (ideas, budget ledger, data)

*Written 2026-10-29 by Claude with Nicolas's decisions of the same day. It replaces the draft idea list of
2026-10-29 (`claude/IDEA_LIST_DRAFT_2026-10-29.md`, kept for history). **Nothing in the idea list has been tested on
our data**; "evidence" means what the cited authors report. Use this document when the roadmap reaches step R5
(`docs/AGENTIC_ROADMAP.md`). The agent tooling for that step is proposed separately in
`claude/PROPOSAL_2026-10-29_models_and_setups.md` (decisions pending there).*

**How to resume.** (1) Check that every prerequisite in section 3 is done. (2) Nicolas edits the idea list
(section 6): remove, add or reorder. (3) Collect the data of section 5 for the ideas that stay. (4) The ledger of
section 4 decides which ideas are still allowed; the planner picks among them, most promising first.

---

## 1. Decisions taken (Nicolas, 2026-10-29)

1. **Existing experiments count against their family's budget** (3 ideas per family, 5 variants per idea). They are
   assigned to families in section 4.
2. **Nicolas collects the extra data** (section 5) when the research reaches this stage.
3. **Dividends and T-bill interest are added before any agent runs** (roadmap step R4b), so every grade the planner
   sees is on a total-return basis.
4. **exp13's origin** is documented from the git history (section 7); the results log gets a note row.

Earlier decisions that bind this plan (design 2026-10-28): the planner picks the most promising idea first and sees
only grades; the coder never sees results; budget 5 variants per idea and 3 ideas per family; every variant is counted
in the multiple-testing N; a pass is frozen and paper-traded on data after its freeze date.

---

## 2. Baseline: the nine experiments under the current referee (phase C, 2026-10-28/29)

First valid baseline. Judge hash `ad4a601ec218bc09`, judge commit `cc094bd`, run commit `1685b17`, N = 260 designs
tried. The rows of 2026-10-23..25 in `docs/RESULTS_LOG.md` were withdrawn by the 2026-10-25 audit; these replace them.
Every return reproduced the earlier run exactly; the only change is the new multiple-testing part of the verdict.

| Experiment | Family (sec. 4) | Prior-only vs buy-and-hold | Failed parts | Look-ahead |
|---|---|---|---|---|
| exp01_minute_entry | L | +101.73% vs +217.35% | return, consistency, baselines, multiple-testing | pass |
| exp02_stop_reentry | L | +148.41% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp03_ath_exit | X | +134.86% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp04_trend_exit | T | +45.46% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp05_vol_scaled_exposure | V | +148.95% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp06_capped_regret_reentry | T | +104.12% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp07_warning_lights_exit | T | +50.43% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp12_vix_fear_reentry | V | +128.78% vs +199.04% | return, consistency, baselines, multiple-testing | pass |
| exp13_e1m1_robustness | V (part of exp12's idea) | +273.85% vs +199.04% | consistency, multiple-testing | pass |

Notes: exp01's buy-and-hold differs because minute mode scores a different span. Returns are price returns with cash
at 0% (R4b changes this). exp13 beats buy-and-hold on return only because its rule was selected after seeing the data
(section 7); the verdict fails it.

What the exp02 report shows in detail (read 2026-10-29): Sharpe 0.686 vs 0.680, maximum drawdown −22.9% vs −34.2%,
about 77% average exposure, above 58 of 100 random-timing draws (needed 95), deflated Sharpe probability 0.003
(needed 0.95). Typical of the family: less risk, less return, no timing skill shown.

---

## 3. Prerequisites before the first agent cycle (roadmap)

- **R2** referee = the deployed commit; **R3** core fixes from the audit; **R4** results visible only as grades.
- **R4b** total returns: SPY dividends and T-bill interest on cash in the engine and the baselines (decided
  2026-10-29). Needs the data of section 5.1.
- **Full rerun of the nine experiments** after R2-R4b (one batch, exp01 included because its returns change too:
  about 3 hours for the eight daily ones plus 11-14 hours for exp01). The ledger of section 4 and section 2 are then
  updated with the new numbers.
- **R5** agent runtime chosen (proposal of 2026-10-29), file formats, planner and coder prompts.

---

## 4. Family budget ledger (decided: existing experiments count)

Assignment by each experiment's primary mechanism (proposed by Claude 2026-10-29; Nicolas may move any). Variants
spent before the budget existed are not refunded or charged; they are already in N.

| Family | Ideas used | Slots left | Experiments | Eligible new ideas (section 6) |
|---|---|---|---|---|
| **T** Trend / time-series momentum | 3 | **0 (closed)** | exp04 (200-day exit), exp06 (trend or near-high exit + buy-stop re-entry), exp07 (warning lights) | none; T1-T4 parked |
| **V** Volatility and risk state | 2 | 1 | exp05 (realized-volatility scaling); exp12 + exp13 (VIX-based re-entry; exp08, the pre-reset VIX signal gate, belongs to the same idea) | V1 (recommended), or V2 / V3 |
| **L** Learned models | 2 | 1 | exp01 (minute take-profit model), exp02 (trailing stop + model re-entry) | none proposed |
| **X** Anchors and highs | 1 | 2 | exp03 (sell near the all-time high) | X1 |
| **C** Calendar and event windows | 0 | 3 | — | C1-C5 (choose 3; recommended C1, C2, C3) |
| **I** Intraday | 0 | 3 | — | I1, I2, I3 |
| **R** Short-term reversal | 0 | 3 | — | R1, R2 |
| **M** Macro and valuation | 0 | 3 | — | M1, M2 (T3 could move here as a macro idea) |

Points to settle when resuming:
- exp12 + exp13 used 7 variants under one idea (6 candidates + 1); this predates the 5-variant budget.
- If Nicolas prefers T3 ("trend gate with unemployment confirmation") it can be filed under M (its new element is the
  macro signal), using an M slot.
- Pre-reset experiments exp09-exp11 were planned but never run; they use no budget.

---

## 5. Data to collect (Nicolas, when the stage is reached)

Every new source is registered first (`docs/DATA_SOURCES.md`: loader, time zone, timestamp convention, availability
rule, revision policy). The availability clock is what keeps a rule from seeing a value before it was public.

| # | Data | Needed for | Availability to record | Notes |
|---|---|---|---|---|
| 5.1a | SPY dividends: ex-date, pay date, amount, 2005 → today | **R4b (before agents)** | ex-date open | Price data stays IBKR's; dividends are corporate-action data |
| 5.1b | 3-month T-bill rate, daily, 2005 → today | **R4b (before agents)** | next business day | The rate earned on cash |
| 5.2 | FOMC meeting and statement dates, scheduled **and unscheduled**, 2005 → today | C1, C3 | scheduled: when the calendar was published; unscheduled: the announcement time | |
| 5.3 | Macro release calendar (CPI, Employment Situation; date and time) | C3 | release time | |
| 5.4 | Unemployment rate **first releases** (vintages, e.g. ALFRED UNRATE) | M2 (T3) | release date | The revised series leaks future information |
| 5.5 | Shiller CAPE, monthly | M1 | with its publication lag | Low power in 20 years; lowest priority |

Data we already have: SPY 1-minute bars from 2005, VIX and VIX3M (1-minute and daily; VIX3M starts later), the daily
feature set `TSDAY`. Ideas I1-I3, V1, X1, R1, R2, C2, C4, C5 need nothing new.

---

## 6. The idea list (draft of 2026-10-29, unchanged except the status line)

Status lines added 2026-10-29: **eligible** (family has a slot), **parked** (family closed), **needs data** (section 5).
Suggested starting order among eligible ideas: **I1 → C1 → V1 → C2 → I2 → X1 → C3 → R1 → M2 → R2 → M1 → I3.**
The first five spend little time out of the market, state a mechanism, and (except C1) need no new data.

### 6.0 What the constraints imply

Our question is narrow: **a long-only, unlevered SPY strategy must beat buy-and-hold's total return after costs**
(price returns only and cash at 0% today; R4b adds dividends and T-bill interest before agents run). That shapes which ideas can work at all:

1. **A strategy that is out of the market must be out at bad times, on net.** With no leverage, the only way to beat
   buy-and-hold's return is that the days skipped had a negative total return. Lower risk does not count.
2. **So many famous ideas improve risk, not return.** Trend-following and volatility targeting mostly cut drawdowns
   and raise the Sharpe ratio (Zakamulin 2015; Harvey et al. 2018). Our own runs agree: exp04 (200-day trend exit)
   +45.46%, exp05 (volatility-scaled exposure) +148.95%, both against +199.04% for buy-and-hold over the same span
   (phase C reruns, 2026-10-28).
3. **The ideas with a real chance are those that stay invested most of the time** and step aside only in narrow
   windows that, according to the literature, earn little or lose: calendar windows, intraday windows, specific
   risk states.
4. **Published effects shrink.** Anomaly portfolio returns were 26% lower out of sample and 58% lower after
   publication (McLean & Pontiff, *Journal of Finance* 2016). Most market-level predictors fail out of sample (Goyal, Welch & Zafirov 2024).
   Several entries below have documented decay; they are marked.
5. **Every variant tested raises the bar for all later ones** (multiple testing; 260 designs counted so far). An
   idea that the evidence already says is dead still costs budget. Those are in section 6.x, "considered, not
   recommended", rather than in the list.

**Data we have** (registered sources): SPY 1-minute bars from 2005, VIX and VIX3M (1-minute and daily; VIX3M
starts later than VIX, check the date), and the daily feature set `TSDAY`. **Data Nicolas would have to supply**
(non-price, so it needs registration with an availability clock first): the FOMC meeting calendar, macro release
dates, unemployment vintages (section 5). Each entry says which it needs.

**Budget** (decided): 5 variants per idea, 3 ideas per broad family; existing experiments count (ledger, section 4).

**"Promise"** is my starting suggestion for the planner's ordering (it decides). It weighs: the time spent out of the
market (less is better here), how recent and independent the evidence is, a mechanism that could persist, cost
sensitivity, and whether our data supports it today.

### 6.1 The ideas

Format: **dedup key** = family + mechanism. "Time out" = rough share of days not fully invested.

#### Calendar and event windows (C)

**C1. FOMC-cycle even weeks** · key `C:fomc_cycle_week_parity` · **Promise: high-medium**
- *Status (2026-10-29):* **eligible, needs data 5.2**
- *Mechanism:* the equity premium since 1994 was earned almost entirely in even weeks counted from the last FOMC
  meeting (weeks 0, 2, 4, 6); the authors link it to Fed information flow (Cieslak, Morse & Vissing-Jorgensen,
  *Journal of Finance*; SSRN 2015, revised 2019).
- *Rule sketch:* invested by default; out (or reduced) in odd weeks of the FOMC cycle. Variants: out in all odd weeks;
  out only in odd weeks when the 200-day trend is down; week counted from meeting day vs announcement day.
- *Time out:* up to ~50% (fewer in the conditional variant).
- *Data:* FOMC meeting and announcement dates 2005-today, including unscheduled meetings (Nicolas; known at the
  announcement time, scheduled dates known in advance).
- *Caveats:* post-publication evidence not checked by me; one regime (one central bank's communication practice).

**C2. Turn of the month** · key `C:turn_of_month` · **Promise: medium**
- *Status (2026-10-29):* **eligible**
- *Mechanism:* returns concentrate in the last trading day and first three of the next month (Lakonishok & Smidt
  1988; McConnell & Xu, *Financial Analysts Journal* 2008, who call it "a puzzle in search of an answer"); flows from
  month-end payments are the usual story. A related older finding: returns were positive only in the first half of
  the month (Ariel, *Journal of Financial Economics* 1987; not re-checked).
- *Rule sketch:* in only at turn-of-month (−1..+3) vs invested except days +4..+10 vs except the second half.
  Variants: window edges.
- *Time out:* 50-80%.
- *Data:* none new.
- *Caveats:* calendar effects can move or vanish (Quantpedia's own warning); a short window must carry almost all of
  the 20-year return for the "in only" version to win.

**C3. Scheduled macro announcement days** · key `C:macro_announcement_days` · **Promise: medium-low**
- *Status (2026-10-29):* **eligible, needs data 5.2-5.3**
- *Mechanism:* 1958-2009, the average excess return was 11.4 bp on days with CPI, employment or FOMC news vs 1.1 bp
  otherwise; over 60% of the premium earned on those days (Savor & Wilson, *JFQA* 2013).
- *Rule sketch:* invested by default; out on the day before announcements, or in only around them. Variants: which
  releases count.
- *Time out:* 10-80% depending on direction.
- *Data:* release calendars (BLS, FOMC) with times (Nicolas).
- *Caveats:* the related pre-FOMC drift **disappeared after 2015** (see section 3); sample ends 2009.

**C4. Halloween ("sell in May")** · key `C:halloween_season` · **Promise: low-medium**
- *Status (2026-10-29):* **eligible only if chosen over C1-C3**
- *Mechanism:* after 1998 the November-April advantage appears in all 37 markets of the original study (15
  significant); but the **US** estimate after 1998 (4.90 points) is **not statistically significant** (Jacobsen &
  Zhang, working paper with references to 2012).
- *Rule sketch:* in Nov-Apr, out May-Oct; variant: out in May-Oct only when trend is down.
- *Time out:* ~50% (unconditional).
- *Data:* none new.
- *Caveats:* only ~20 independent observations in our span: very low statistical power; cheap to run (2 trades a year).

**C5. Option-expiration week** · key `C:opex_week` · **Promise: low**
- *Status (2026-10-29):* **eligible only if chosen over C1-C3**
- *Mechanism:* S&P 500 returns in the third-Friday week were relatively high 1983-2008 and not unusual before index
  options existed (Stivers & Sun, 2010 working paper as summarized by CXO).
- *Rule sketch:* invested by default; out in the week after expiration (reported reversal). One variant.
- *Data:* none new (third Fridays are computable; holiday shifts need care).
- *Caveats:* no evidence after 2008 found; weekly options since then may have changed the pattern.

#### Intraday (I): uses the minute data we already have

**I1. Last-half-hour exit on weak days (market intraday momentum)** · key `I:last_half_hour_momentum` ·
**Promise: high-medium**
- *Status (2026-10-29):* **eligible**
- *Mechanism:* the first half-hour return (from the previous close) predicts the last half-hour return
  (Gao, Han, Li & Zhou, *JFE* 2018; S&P 500 ETF 1993-2013; stronger on volatile, high-volume, recession and macro-news
  days). The rest-of-day return predicts the last 30 minutes across 60+ futures 1974-2020; the authors tie it to
  gamma hedging by option dealers and leveraged ETFs (Baltussen, Da, Lammers & Martens, *JFE* 2021). That is a
  structural reason that persists while those hedgers exist.
- *Rule sketch (long-only overlay):* hold SPY; at 15:30, if the return since the previous close is below −x, sell and
  buy back at 15:59. Variants: x ∈ {0.5%, 1%, 1.5%}; only when VIX is above its median; signal from first half-hour
  only.
- *Time out:* tiny (30 minutes on signal days only), which is the attraction.
- *Data:* none new.
- *Caveats:* the edge per trade is small (CXO: last-hour returns after extreme first hours are small); our cost model
  ($0.01/share slippage plus fees) decides it. CXO's own check (2012-2014) found the correlation still present but weak.

**I2. Intraday "noise-area" exit overlay** · key `I:noise_area_breakout` · **Promise: medium**
- *Status (2026-10-29):* **eligible**
- *Mechanism:* moves beyond an intraday "noise area" (the average absolute move from the open at that time of day,
  last 14 days, around the open and previous close) tend to continue; SPY 2007-2024, net Sharpe 1.33 with long and
  short legs, sized to a 2% daily volatility target **with up to 4x leverage** (Zarattini, Aziz & Barbon, 2024
  working paper). The long leg contributed slightly more than the short (no separate numbers given).
- *Rule sketch (long-only, unlevered):* hold SPY; sell at a half-hour mark when price breaks below the lower boundary;
  buy back at the close, or when price is back above max(lower boundary, VWAP). Variants: boundary multiplier
  {1, 1.5}; exit only vs exit and buy-back intraday.
- *Time out:* small (only the remaining hours on break-down days).
- *Data:* none new (VWAP needs volume; check the SPY minute bars carry volume).
- *Caveats:* authors' own backtest, recent, no independent replication found; our version removes leverage and the
  short leg, so the paper's numbers do not transfer.

**I3. Overnight-gap fade** · key `I:gap_reversal` · **Promise: low**
- *Status (2026-10-29):* **eligible (weakest; candidate to drop)**
- *Mechanism:* index-level short-horizon reversal (see R1). Rule: after a large gap down at the open, stay invested;
  after a large gap up, sell at the open and buy back at the close. One or two variants.
- *Caveats:* no specific published source checked; included only as a cheap intraday reversal test. Candidate to drop.

#### Volatility and risk state (V)

**V1. Variance risk premium exit** · key `V:variance_risk_premium` · **Promise: medium**
- *Status (2026-10-29):* **eligible (recommended for the last V slot)**
- *Mechanism:* implied minus realized variance (VIX² vs recent realized variance) predicts aggregate returns, strongest
  at the quarterly horizon; high premium → high returns, low → low (Bollerslev, Tauchen & Zhou, *RFS* 2009; post-1990
  data).
- *Rule sketch:* invested by default; out when the premium is in its lowest q of history so far (point-in-time
  quantile); back in when above. Variants: q ∈ {5%, 10%, 20%}; realized variance from 1-minute vs 5-minute returns over
  22 sessions.
- *Time out:* 5-20%.
- *Data:* none new (VIX daily + SPY minutes).
- *Caveats:* post-publication evidence not checked by me; overlaps in spirit with exp12 (VIX), but a different signal.

**V2. VIX term-structure inversion exit** · key `V:vix_term_inversion` · **Promise: low-medium**
- *Status (2026-10-29):* **parked unless chosen over V1**
- *Mechanism:* VIX above VIX3M (backwardation) marks stress. Evidence that it predicts returns is weak (Fassas 2012,
  as summarized by CXO: "may" show a negative relation, in-sample, crisis-dominated sample).
- *Rule sketch:* out after n days with VIX/VIX3M ≥ 1, back when < 1. Variants: n ∈ {1, 3, 5}.
- *Data:* none new; VIX3M history starts later than 2005.
- *Caveats:* close to exp12's M3 (used there only to suppress exits). Could be dropped as a near-duplicate.

**V3. Volatility-target + trend combination** · key `V:vol_target_trend_gate` · **Promise: low**
- *Status (2026-10-29):* **parked unless chosen over V1**
- *Mechanism:* volatility scaling raises the equity Sharpe ratio (US equities 1927-2017: 0.40 → 0.48-0.51) and cuts
  both tails (Harvey et al., *Journal of Portfolio Management* 2018), but real-time volatility-managed portfolios do not
  beat their unmanaged versions in general, the market factor included (Cederburg, O'Doherty, Wang & Yan, *JFE*).
- *Rule sketch:* reduce exposure only when both volatility is high and trend is down.
- *Caveats:* without leverage it cannot add return unless high-volatility periods lose money on net; exp05 already
  failed. Listed so the family is complete; candidate to drop.

#### Trend (T): family closed (3 of 3 ideas used)

**T1. Monthly 10-month moving average (Faber)** · key `T:sma_monthly_check` · **Promise: low-medium**
- *Status (2026-10-29):* **parked (family T closed)**
- *Mechanism:* the same idea as exp04 but checked only at month-end, which cuts whipsaw trades (Faber, "A Quantitative
  Approach to Tactical Asset Allocation", 2007).
- *Rule sketch:* at the last close of the month: in if above the 10-month average, else out. Variants: 8, 10, 12
  months.
- *Caveats:* the edge of moving-average timing comes from bear markets and is not statistically significant in the
  second half of 155 years (Zakamulin 2015). Our daily version (exp04) lost badly.

**T2. 12-month absolute momentum** · key `T:tsmom_12m` · **Promise: low-medium**
- *Status (2026-10-29):* **parked (family T closed)**
- *Mechanism:* time-series momentum: hold an asset when its trailing 12-month return is positive (Moskowitz, Ooi &
  Pedersen, *JFE* 2012; Antonacci, "Absolute Momentum", 2013; Hurst, Ooi & Pedersen, AQR "A Century of Evidence on
  Trend-Following", 1880-2013, long/short across 67 markets). None of these test a single long-only equity index.
- *Rule sketch:* monthly: in if the 12-month return (optionally excluding the last month) is positive. Variants:
  lookback {6, 12}; skip-month on/off.
- *Caveats:* a close cousin of exp07's "250-session return negative" light.

**T3. Trend gate with economic confirmation ("Either")** · key `T:trend_plus_unemployment` · **Promise: medium-low**
- *Status (2026-10-29):* **parked (family T closed; can move to M)**
- *Mechanism:* be out only when **both** the price trend (10-month average) and the unemployment trend (rate above its
  12-month average) are bad. CXO's test 1948-2019: beats buy-and-hold in 7 of 11 lookbacks, 10.7% vs 10.0% a year,
  but only in 2 of 7 decades; most of the gain is 2001-2010 (CXO Advisory).
- *Rule sketch:* monthly; variants: unemployment lookback {12, 18}.
- *Data:* **unemployment vintages** (ALFRED first prints with release dates) from Nicolas; the revised series would
  leak future information.
- *Caveats:* few switches in 2005-2025; our span contains the 2008 episode that drives the result.

**T4. Trend exit with fast re-entry** · key `T:trend_exit_fast_reentry` · **Promise: low**
- *Status (2026-10-29):* **parked (family T closed)**
- *Mechanism:* the typical trend loss is buying back late after V-shaped recoveries (2020). Re-enter on a short-term
  signal (close above the 20-day average) instead of the 200-day.
- *Caveats:* exp06 and exp12/13 already explored re-entry rules. Candidate to drop if the family budget counts existing
  experiments.

#### Short-term reversal (R)

**R1. Short-term overbought step-aside** · key `R:index_reversal` · **Promise: low-medium**
- *Status (2026-10-29):* **eligible**
- *Mechanism:* as index products grew, daily index autocorrelation turned from positive to negative (−0.040 in the last
  five years to 2013; Baltussen, van Bekkum & Da, 2016 working paper as summarized by CXO). For SPY 1993-2026, lag-1 autocorrelation is −0.081, but
  the paper finds it is about the size of moves, not their direction; a small directional reversal appears at lag 3
  (Portnaya, arXiv preprint, 2026).
- *Rule sketch:* invested by default; out for 1-3 days after k consecutive up days or a large 3-day rise. Variants: k,
  holding days.
- *Caveats:* direction-based evidence is weak; costs per trade matter.

**R2. RSI(2) dip-buying (Connors)** · key `R:rsi2_dip` · **Promise: low**
- *Status (2026-10-29):* **eligible**
- *Mechanism:* buy short-term oversold dips in an uptrend (Connors & Alvarez, *Short Term Trading Strategies That Work*,
  2008; tests 1995-2007, no out-of-sample testing per CXO's review).
- *Rule sketch:* invested when RSI(2) < 10 and above the 200-day average; out when RSI(2) > 70.
- *Caveats:* in the market a small share of days, so it must earn a lot per day; popular and probably arbitraged.

#### Macro and valuation (M): needs data from Nicolas

**M1. Valuation tilt (CAPE)** · key `M:valuation_cape` · **Promise: low**
- *Status (2026-10-29):* **eligible, needs data 5.5**
- *Mechanism:* value and momentum "have something to add" to timing, but timing one asset is "very hard"; advice:
  "sin a little" (Asness, AQR, 2015). Long-horizon signal, few switches in 20 years: very low power for our test.
- *Data:* Shiller CAPE with publication lags (Nicolas).

**M2. Recession-risk gate (unemployment trend alone)** · key `M:unemployment_trend` · **Promise: low**
- *Status (2026-10-29):* **eligible, needs data 5.4**
- *Mechanism:* out when unemployment rises above its trend. Overlaps T3; listed as the single-signal control.
- *Data:* unemployment vintages (Nicolas).

#### Anchors (X)

**X1. Nearness to the 52-week high** · key `X:near_52w_high` · **Promise: medium-low**
- *Status (2026-10-29):* **eligible**
- *Mechanism:* nearness to the Dow's **52-week high predicts higher** future market returns (underreaction), while
  nearness to the **historical high predicts lower** returns (overreaction) (Li & Yu, *JFE* 2012; G7 evidence).
  Our exp03 sold near the all-time high and lost (+134.86%), consistent only with the second half failing to pay.
- *Rule sketch:* stay invested while SPY is within y of its 52-week high or the 52-week high is far below the
  all-time high; out when far below the 52-week high. Variants: y.
- *Caveats:* close to drawdown-from-high lights in exp07.

---


### 6.x Considered, not recommended (evidence says the effect is gone or unusable)

| Idea | Why not | Source |
|---|---|---|
| **Pre-FOMC drift** (hold the day before the announcement) | The 24h pre-announcement return was 0.49% in 1994-2011, but **fell to 0.09% in 2016-2019**, indistinguishable from other days | Lucca & Moench, *JF* 2015; Kurov, Wolfe & Gilbert, *Finance Research Letters* 2021 |
| **Overnight-only holding** (buy close, sell open) | SPY 1993-2020: 717% gross, **−32% after spread and $0.01 commission**; most of the excess was before 2000 | Bartolini (SSGA) on Alpha Architect, 2020; Lou, Polk & Skouras, *JFE* 2019 |
| **Overnight drift** (S&P futures, 2-3 a.m. ET) | Needs futures we don't have; and it **averaged close to zero in 2021-2025** after ~3.7%/year in 1998-2020 | Boyarchenko, Larsen & Whelan (NY Fed staff report); Liberty Street Economics, July 2026 |
| **Opening-range breakout** (first 5-minute candle) | An independent replication on 5 index CFDs, 2015-2026: gross results reproduced, **net of spread and slippage zero or negative** | Zarattini & Aziz 2023; replication on MQL5 blog, Sept 2026 |
| **Pure volatility targeting** | Raises Sharpe, not unlevered return; real-time versions do not beat the market factor; our exp05 failed | Harvey et al. 2018; Cederburg et al. 2020 |
| **Daily 200-day trend exit** | Already exp04 (+45.46%) | phase C rerun |
| **Pre-holiday effect** | I could not access a recent study; not checked | — |
| **Day-of-week (Monday) effect** | Not researched; generally reported to have weakened | — |

---


---

## 7. exp13's origin (from the git history, 2026-10-09)

- exp12 (VIX fear re-entry, 2026-10-09) tested six rules. Its honest prior-only path lost to buy-and-hold and exp12
  stopped. Looking back at the six rules, **E1M1** (exit below the 200-day average; also re-enter when VIX has fallen 15%
  from its peak since the exit) was the best: +314.80% vs +235.39% on 2015-2026, labelled "optimistic, best of 6".
- Nicolas then commissioned exp13 (2026-10-09) as a **data-dependent robustness study** of E1M1, overriding exp12's own
  "last VIX test" commitment. Its protocol discloses this (commit `afe6b42`).
- Its verdict (commits `c79e7b4` → `05ac8c3`, audited 2026-10-09): **E1M1 IS NOT ROBUST.** On 2005-2014 it made
  +53.32% vs +73.09% (the VIX re-entry bought into the 2008 crash); only 11 of 36 neighbouring variants beat
  buy-and-hold (E1M1 ranked 1 of 36, "a spike"); a selection-aware placebo gave p = 0.088; without its single best
  episode (2020-03-16) it falls below buy-and-hold.
- On 2026-10-23 the rule was ported to the new runner as a one-candidate experiment (exp13 v1.0). Its +273.85% vs
  +199.04% is the same after-the-fact selection; the runner's consistency and multiple-testing parts reject it.
- **For the thesis:** exp13 is a worked example of selection bias: a rule chosen because it looked best can beat
  buy-and-hold on return and still be noise. The results log gets a note row saying so.

---

## 8. Open questions for later

- Which 3 of C1-C5; which idea takes the last V slot (V1 recommended); keep or drop I3.
- Move T3 to family M or leave it parked.
- Whether a parked idea may replace a used idea's slot (proposed: no; a family closes for good).
- The agent setup decisions in `claude/PROPOSAL_2026-10-29_models_and_setups.md`.

---

## Sources

Read in this session (pages or PDFs fetched). **Not re-checked in this session**, cited from general knowledge:
Faber 2007, Moskowitz-Ooi-Pedersen 2012, Antonacci 2013, Ariel 1987, Lucca & Moench 2015 (its numbers come from the
Kurov et al. paper below), Lakonishok & Smidt 1988 (via Quantpedia).


- Zakamulin, "A Comprehensive Look at the Empirical Performance of Moving Average Trading Strategies", SSRN 2015 — https://papers.ssrn.com/abstract=2677212
- Kurov, Halova Wolfe & Gilbert, "The Disappearing Pre-FOMC Announcement Drift" (2020 draft) — https://www.skidmore.edu/economics/documents/KurovWolfeGilbert-TheDisappearingPre-FOMC-Announce-Drift-200914.pdf
- Bartolini, "Trading costs wipe out the overnight return anomaly", Alpha Architect 2020 — https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/
- Gao, Han, Li & Zhou, "Market Intraday Momentum", JFE 2018 — https://profiles.wustl.edu/en/publications/market-intraday-momentum/
- CXO Advisory, first and last half-hours linked — https://cxoadvisory.com/calendar-effects/first-and-last-half-hours-of-trading-linked
- Baltussen, Da, Lammers & Martens, "Hedging Demand and Market Intraday Momentum", JFE 2021 — https://pure.eur.nl/en/publications/hedging-demand-and-market-intraday-momentum/
- Zarattini, Aziz & Barbon, "Beat the Market: An Effective Intraday Momentum Strategy for SPY", 2024 — https://concretumgroup.com/beat-the-market-an-effective-intraday-momentum-strategy-for-sp500-etf-spy/ and https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content
- Opening-range breakout replication, MQL5 blog, Sept 2026 — https://www.mql5.com/en/blogs/post/776235 ; original: https://papers.ssrn.com/abstract=4416622
- Cederburg, O'Doherty, Wang & Yan, volatility-managed portfolios (summary) — https://alphaarchitect.com/does-portfolio-timing-based-on-volatility-signals-outperform-buy-and-hold/
- Harvey et al., "The Impact of Volatility Targeting", JPM 2018 — https://people.duke.edu/~charvey/Research/Published_Papers/P135_The_impact_of.pdf
- Turn of the month (Lakonishok & Smidt; McConnell & Xu) — https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes ; https://ideas.repec.org/a/taf/ufajxx/v64y2008i2p49-64.html
- Jacobsen & Zhang, "The Halloween Indicator: Everywhere and All the Time" — https://www.bnains.org/backtest/periode/The_Halloween_Indicator_everywhere_and_all_the_time_-_Ben_Jacobsen_%26_Cherry_Y._Zhang.pdf
- Goyal, Welch & Zafirov, RFS 2024 — https://www.sfi.ch/en/publications/a-comprehensive-2022-look-at-the-empirical-performance-of-equity-premium-prediction
- McLean & Pontiff, JF 2016 — https://Www.Gwern.net/doc/economics/2016-mclean.pdf
- Fassas on VIX term structure (CXO summary) — https://cxoadvisory.com/volatility-effects/change-in-vix-futures-term-structure-as-stock-market-return-predictor
- Connors' short-term strategies (CXO review) — https://cxoadvisory.com/technical-trading/a-few-notes-on-short-term-trading-strategies-that-work
- Li & Yu, JFE 2012 — https://academicnewsletter.sufe.edu.cn/info/356820
- Hurst, Ooi & Pedersen, "A Century of Evidence on Trend-Following Investing" — https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf
- Bollerslev, Tauchen & Zhou, RFS 2009 — https://scholars.duke.edu/publication/732839
- Lou, Polk & Skouras, JFE 2019 — https://personal.lse.ac.uk/polk/research/TugOfWar.pdf
- Cieslak, Morse & Vissing-Jorgensen, "Stock Returns over the FOMC Cycle" — https://papers.ssrn.com/abstract=2687614
- Savor & Wilson, JFQA 2013 — https://ideas.repec.org/a/cup/jfinqa/v48y2013i02p343-375_00.html
- Portnaya, "The Bounce Has No Direction", arXiv 2026 — https://arxiv.org/pdf/2606.29591
- Baltussen, van Bekkum & Da on indexing and serial dependence (CXO summary) — https://www.cxoadvisory.com/technical-trading/effect-of-tracking-products-on-short-term-equity-index-trendingreversal
- CXO, combining market trend and economic trend — https://www.cxoadvisory.com/economic-indicators/combine-market-trend-and-economic-trend-signals/
- Stivers & Sun on option-expiration weeks (CXO summary) — https://cxoadvisory.com/calendar-effects/option-expiration-week-stock-return-drill-down
- Asness, "Sin a Little", AQR 2015 — https://www.aqr.com/insights/perspectives/sin-a-little
- Boyarchenko, Larsen & Whelan; "The Disappearing Overnight Drift" — https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/
