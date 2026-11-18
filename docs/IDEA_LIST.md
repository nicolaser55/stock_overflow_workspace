# Stock Overflow: idea list (v1, agreed 2026-11-16)

*The single source of research ideas for stage 1: the hand-designed experiments now, the agents' planner later
(roadmap R5). Drafted by Claude on 2026-10-29 (it was section 6 of `docs/STAGE1_RESEARCH_PLAN.md`); updated and agreed
by Nicolas on 2026-11-16. Nothing here has been tested on our data: "evidence" means what the cited authors report,
not what we observed. Where a source was not checked, the entry says so.*

## How to use this list

- **Pick only an idea whose status is eligible** and whose family has a slot left (`docs/STAGE1_RESEARCH_PLAN.md`
  section 4). Parked ideas (family closed) and section 3 are not to be run. The dedup key (family + mechanism) marks
  an explored idea: an idea with the same key is not explored again under another name.
- **Before a protocol:** a research brief that reads the idea's sources (point 8 below), states the overlap of their
  samples with ours (point 7), and proposes the rules and the candidate grid. Then `PROTOCOL.md` with the line
  `Family: <letter>, idea <id>, variant <k> of 5` (`experiments/README.md`). No look at our data for the idea before
  the protocol is committed with `preregister`.
- **Status changes:** "selected" in Nicolas's selection pull request, before the agent starts (2026-11-18); "used"
  (with its experiment and result) or "dropped" in the records pull request after the run. Earlier rule: in the pull request
  that brings the experiment's tests, together with the ledger row in section 4 of the plan.
- **Suggested order** among eligible ideas: I1 (used, exp14) → C2 (used, exp15) → R1 → I2 → M2 → X1 → C3 → R2 → M1
  → I3; C1 and V1 deferred (2026-11-17, 2026-11-18). A literature screen of every remaining idea (2026-11-18) found
  none that clearly passes the two criteria below: the published edges are mostly in being invested at good times,
  which buy-and-hold already captures, not in being out at bad times. Re-checked when the next idea is picked.
- **Choosing among eligible ideas (decided by Nicolas on 2026-11-17):** prefer ideas that trade rarely and stay
  invested most of the time (costs removed exp14's small gross gain), and ideas whose effect was replicated out of
  sample (other periods, other markets) over a single large reported effect. Re-check the suggested order against
  these two criteria when the next idea is picked. About 3-5 candidates per version.
- **This file is protected** (`protected_paths.txt`): an agent proposes a change in its report; Nicolas merges it.
- **Statuses:** eligible · selected (an experiment is being prepared) · used (expNN, result) · deferred (kept for
  later; the evidence or the data is not there now) · parked (family closed)
  · drop candidate (weak; keep only if a slot is spare) · needs data (eligible once Nicolas supplies and registers it).

## 1. What the constraints imply

Our question is narrow: **a long-only, unlevered SPY strategy must beat buy-and-hold's total return after costs**
(total returns since R4b, 2026-11-09: dividends reinvested and interest on cash, on both sides). That shapes which ideas can work at all:

1. **A strategy that is out of the market must be out at bad times, on net.** With no leverage, the only way to beat
   buy-and-hold's total return is that the time skipped returned less than the T-bill interest the cash earned
   instead. Lower risk does not count: the verdict passes only a total return strictly above buy-and-hold's
   (decided 2026-11-14; the 90% band with a better Sharpe ratio or drawdown is reported, never a pass).
2. **So many famous ideas improve risk, not return.** Trend-following and volatility targeting mostly cut drawdowns
   and raise the Sharpe ratio (Zakamulin 2015; Harvey et al. 2018). Our own runs agree: exp04 (200-day trend exit)
   +86.10%, exp05 (volatility-scaled exposure) +196.47%, both against +256.72% for buy-and-hold over the same span
   (judge v1 baseline on total returns, 2026-11-10; on price returns +45.46% and +148.95% against +199.04%).
3. **The ideas with a real chance are those that stay invested most of the time** and step aside only in narrow
   windows that, according to the literature, earn little or lose: calendar windows, intraday windows, specific
   risk states.
4. **Published effects shrink.** Anomaly portfolio returns were 26% lower out of sample and 58% lower after
   publication (McLean & Pontiff, *Journal of Finance* 2016). Most market-level predictors fail out of sample (Goyal, Welch & Zafirov 2024).
   Several entries below have documented decay; they are marked.
5. **Every variant tested raises the bar for all later ones** (multiple testing; 260 designs counted so far). An
   idea that the evidence already says is dead still costs budget. Those are in section 3, "considered, not
   recommended", rather than in the list.
6. **The bar is high.** exp13 returned +344.27% against +256.72% for buy-and-hold and still failed: its edge was not
   consistent year to year, and its deflated Sharpe probability was 0.08 against the 0.95 needed at N = 260. A pass
   needs a large edge that shows up in most years. Ideas that trade a few times in 20 years (C4, M1) can almost never
   clear it.
7. **Our data overlaps many published samples.** The development data runs 2005-2024. Where a paper's sample overlaps
   it (for example Gao et al. 1993-2013 for I1), our test is partly a replication on data the authors saw, not an
   independent test; the protocol must say so, and only the holdout and the live test are fully out of sample.
8. **"Not re-checked" sources are verified before use.** The research brief of the experiment that uses an idea reads
   its sources first and corrects this list if they say something else.


**Data we have** (registered sources; "Data: none new" in an entry means it uses only these): SPY 1-minute bars from 2005, VIX and VIX3M (1-minute and daily; VIX3M
starts later than VIX, check the date), and the daily feature set `TSDAY`. **Data Nicolas would have to supply**
(non-price, so it needs registration with an availability clock first): the FOMC meeting calendar, macro release
dates, unemployment vintages (`docs/STAGE1_RESEARCH_PLAN.md` section 5). Each entry says which it needs; a new source must be registered in
`so.core.point_in_time` with its availability clock before any design reads it (code work, a protected change).

**Budget** (decided): 3 ideas per family (the ledger, `docs/STAGE1_RESEARCH_PLAN.md` section 4; existing experiments
count) and 5 variants per idea, a variant being a protocol version (decided 2026-11-14), with about 3-5 candidates
per version (2026-11-17; was about 3-15). Every candidate is a design in N.

**"Promise"** is Claude's suggestion for the order (Nicolas decides; the hand-designed phase takes two or three ideas,
later the agents' planner continues from this list). It weighs: the time spent out of the
market (less is better here), how recent and independent the evidence is, a mechanism that could persist, cost
sensitivity, and whether our data supports it today.

## 2. The ideas

Format: **dedup key** = family + mechanism. "Time out" = rough share of days not fully invested.

#### Calendar and event windows (C)

**C1. FOMC-cycle even weeks** · key `C:fomc_cycle_week_parity` · **Promise: high-medium**
- *Status (2026-11-17):* **deferred** (kept for later, not dropped). An independent check finds the even-week effect
  significant in 1994-2003 but not in 2004-2013, 2014-2023 or 2017-2023, and not robust to two outlier days (Uppal,
  Imperial College working paper, March 2025, "Does the FOMC Cycle Still Drive Stock Returns?"; a Stockholm School of
  Economics thesis, Holst & von der Esch, finds the same for 2017-2022): almost exactly our development span. It also
  needs data 5.2 registered as a new source (a judge change). Revisit if new evidence appears or when 5.2 is registered
  for C3. (Was: eligible, needs data 5.2, 2026-10-29.)
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
- *Status:* **used (2026-11-18): exp15 v1.0, fail** (run `exp15_pre_tom_exit_20261118170138683759`, judge
  edaa1c6): +203.68% vs buy-and-hold +256.72% over 2015-2024, still behind at zero slippage (+206.48% vs +256.64%),
  so the shortfall is the equity return given up on the days out, not costs; above constant exposure (+201.35%) but
  above only 54 of 100 random-timing draws (the median: the window dates carried no information); failed return,
  consistency, baselines and multiple testing; look-ahead pass. Variant 1 of 5 spent; **no further variant
  recommended** (a change chosen now would be `data-dependent`, and the random-timing count leaves nothing to refine).
  Direction run: out on the pre-turn-of-month selling days (T-8..T-4 or T-5..T-4, fixed or shifted one session per
  shorter settlement cycle), invested otherwise; mechanism Etula, Rinne, Suominen & Vaittinen (*Review of Financial
  Studies* 2020, 1995-2013). Prediction (fail on the return part) met; the expected direction (those days below cash)
  was not. (Was: selected 2026-11-18; eligible 2026-10-29.)
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
- *Status:* **used (2026-11-16): exp14 v1.0, fail** (run `exp14_last_half_hour_exit_20261116224736406552`, judge
  2e9cfb0): +256.24% vs buy-and-hold +256.72% over 2015-2024; ahead at zero slippage, behind at the standard $0.01;
  failed return, consistency, baselines and multiple testing; look-ahead pass. Variant 1 of 5 spent; no second
  variant planned (any change chosen after this result would be data-dependent). Was selected 2026-11-16 as the first
  hand-designed experiment. Fits the runner's intraday decision
  times (roadmap R4c: a 15:30 call on the fractional-weight engine, the 15:58 daily call buys back at 15:59).
  Overlap: Gao et al.'s sample (1993-2013) covers 2005-2013 of our development data.
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
- *Status (2026-11-18):* **deferred** (kept for later; not run, no design counted). The step-1 brief (agent branch
  `agent/exp15-vrp-exit`, commit `29ac47d`, not merged) found the post-publication evaluation negative: Goyal, Welch &
  Zafirov (*Review of Financial Studies* 2024) dismiss the variance risk premium as a predictor through 2021 (in-sample
  t falls to 0.72, the sign flips in the second half, timing strategies 2.6-7.0% a year below all-equity), and Pyun
  (2016) finds the plain premium weak out of sample. Their samples cover almost all of our development span. (Was:
  selected for exp15 on 2026-11-17; eligible, recommended for the last V slot, 2026-10-29.)
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
  Our exp03 sold near the all-time high and lost (+173.08% vs +256.72% on total returns; +134.86% vs +199.04% on
  price returns), consistent only with the second half failing to pay.
- *Rule sketch:* stay invested while SPY is within y of its 52-week high or the 52-week high is far below the
  all-time high; out when far below the 52-week high. Variants: y.
- *Caveats:* close to drawdown-from-high lights in exp07.

---


## 3. Considered, not recommended (evidence says the effect is gone or unusable)

| Idea | Why not | Source |
|---|---|---|
| **Pre-FOMC drift** (hold the day before the announcement) | The 24h pre-announcement return was 0.49% in 1994-2011, but **fell to 0.09% in 2016-2019**, indistinguishable from other days | Lucca & Moench, *JF* 2015; Kurov, Wolfe & Gilbert, *Finance Research Letters* 2021 |
| **Overnight-only holding** (buy close, sell open) | SPY 1993-2020: 717% gross, **−32% after spread and $0.01 commission**; most of the excess was before 2000 | Bartolini (SSGA) on Alpha Architect, 2020; Lou, Polk & Skouras, *JFE* 2019 |
| **Overnight drift** (S&P futures, 2-3 a.m. ET) | Needs futures we don't have; and it **averaged close to zero in 2021-2025** after ~3.7%/year in 1998-2020 | Boyarchenko, Larsen & Whelan (NY Fed staff report); Liberty Street Economics, July 2026 |
| **Opening-range breakout** (first 5-minute candle) | An independent replication on 5 index CFDs, 2015-2026: gross results reproduced, **net of spread and slippage zero or negative** | Zarattini & Aziz 2023; replication on MQL5 blog, Sept 2026 |
| **Pure volatility targeting** | Raises Sharpe, not unlevered return; real-time versions do not beat the market factor; our exp05 failed | Harvey et al. 2018; Cederburg et al. 2020 |
| **Daily 200-day trend exit** | Already exp04 (+86.10% vs +256.72% on total returns; +45.46% on price returns) | judge v1 baseline, 2026-11-10 |
| **Pre-holiday effect** | I could not access a recent study; not checked | — |
| **Day-of-week (Monday) effect** | Not researched; generally reported to have weakened | — |

---

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
