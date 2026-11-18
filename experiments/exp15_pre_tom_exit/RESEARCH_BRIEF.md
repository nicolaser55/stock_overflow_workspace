# RESEARCH_BRIEF: exp15 pre-turn-of-month exit (idea C2)

*Prepared 2026-11-18 on branch `agent/exp15-pre-tom-exit`. No market data, prices, caches or
development results were read for this brief. Numbers below are from the cited papers, regulator
pages, and from `so/config.py` / `docs/RUNNER_DESIGN.md` only. No file under
`D:\stock_overflow\data` was opened.*

Status of idea C2 in `docs/IDEA_LIST.md`: **selected (2026-11-18): exp15_pre_tom_exit** (family C,
idea C2, variant 1 of 5). Direction: **out on the pre-turn-of-month selling days, invested
otherwise.** Idea V1 was deferred the same day; branch `agent/exp15-vrp-exit` is left as the
record. Family C ledger: `docs/STAGE1_RESEARCH_PLAN.md` section 4. This is **step 1 only**:
research brief and DRAFT protocol. `config.py` holds only `EXPERIMENT_NAME` (other constants are
still template placeholders); `design.py` is still the template. `PROTOCOL.md` carries
`DRAFT (step 1, not preregistered)`. Trial budget of this draft version: **4**.

---

## 1. Sources read

| Source | What was read | URL | Access date |
|---|---|---|---|
| Etula, Rinne, Suominen & Vaittinen, “Dash for Cash: Monthly Market Impact of Institutional Liquidity Needs”, *RFS* 33 (2020) 75–111 | Full journal HTML / Aalto PDF | https://academic.oup.com/rfs/article/33/1/75/5494694 ; https://www.aalto.fi/sites/default/files/2021-03/dashforcashpaper_final_complete.pdf | 2026-11-18 |
| McConnell & Xu, “Equity Returns at the Turn of the Month”, *FAJ* 64(2) (2008) 49–64 | Full PDF (Purdue / CFA copy) | https://business.purdue.edu/faculty/mcconnell/publications/Equity-Returns-at-the-Turn-of-the-Month.pdf ; https://docs.lib.purdue.edu/cgi/viewcontent.cgi?article=1042&context=ciberwp | 2026-11-18 |
| Lakonishok & Smidt, “Are Seasonal Anomalies Real? A Ninety-Year Perspective”, *RFS* 1 (1988) 403–425 | Abstract + secondary summaries of effect sizes (Quantpedia; McConnell & Xu’s restatement) | https://doi.org/10.1093/rfs/1.4.403 ; https://ideas.repec.org/a/oup/rfinst/v1y1988i4p403-425.html ; https://quantpedia.com/strategies/turn-of-the-month-in-equity-indexes | 2026-11-18 |
| Gil, Henrique de Oliveira, “Could market efficiency explain the disappearance of the ‘end of month’ effect?” (Universidade Católica Portuguesa MSc thesis, awarded 2025-02-03) | Abstract / repository record | https://ciencia.ucp.pt/pt/studentTheses/could-market-efficiency-explain-the-disappearance-of-the-end-of-m/ ; http://hdl.handle.net/10400.14/55999 | 2026-11-18 |
| Han, Han & Tian, “The disappearing turn-of-month effect”, *Finance Research Letters* 71 (2025) | Abstract / IDEAS record | https://ideas.repec.org/a/eee/finlet/v71y2025ics1544612324014909.html ; DOI 10.1016/j.frl.2024.106461 | 2026-11-18 |
| Aalto MSc thesis, “Does turn-of-the-month (TOM) effect still exist? Fresh evidence from international indices” | Abstract / handle text (international 1983–2022 / 2014–2022 split) | https://aaltodoc.aalto.fi/handle/123456789/121876 | 2026-11-18 |
| Graziani, “Time Series Reversal: An End-of-the-Month Perspective” (Bocconi JMP / working paper, Nov 2024) | Full PDF (CSEF copy) — related, not the design | https://csef.it/wp-content/uploads/JMP_GG_02Nov2024.pdf | 2026-11-18 |
| SEC: T+2 adoption / compliance | Press release and compliance guide | https://www.sec.gov/newsroom/press-releases/2017-68-0 ; https://www.sec.gov/resources-small-businesses/small-business-compliance-guides/amendment-securities-transaction-settlement-cycle-small-entity-compliance-guide | 2026-11-18 |
| SEC / Investor.gov: T+1 compliance | FAQ and investor bulletin | https://www.sec.gov/exams/educationhelpguidesfaqs/t1-faq ; https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins/new-t1-settlement-cycle-what-investors-need-know-investor-bulletin | 2026-11-18 |

One web search (2026-11-18) for post-2013 TOM decay and for Graziani / SEC dates. No SPY levels or day-of-month return tables were taken from any page.

---

## 2. Etula, Rinne, Suominen & Vaittinen (RFS 2020)

### Sample and market
- **Market:** CRSP value-weighted US equities (also S&P 500 in Table 1); international developed indices; bonds and money markets for mechanism support.
- **US equity sample under T+3:** **July 1995 – December 2013** (start of the 3-day settlement convention in US equity / corporate bond markets through sample end). Broader figures sometimes extend to 1980; the settlement-timed selling window is argued under T+3.
- **Institutional trades:** ANcerno **1999–2013**.

### Window and day numbering
- Day **T = 0** = **last trading day of the month**.
- Under **T+3**, cash needed on the **morning of T** requires a sale no later than the close of **T−4**.
- Authors label **T−8 to T−4** “**selling pressure**” (low average returns) and **T−3 to T−1** “**positive reversal**”, with T and **T+1..T+3** the classical buying-pressure / TOM window (Ogden 1990; McConnell & Xu).
- Rebound therefore **starts at T−3** in their US equity narrative (after peak selling around T−4).

### Effect size (in-sample)
- Table 1 (US CRSP VW, Jul 1995–): average daily return **T−8..T−4 ≈ −0.03%** per day; **T−3..T−1 ≈ +0.12%**; **T+1..T+3 ≈ +0.12%**.
- Last decade of sample (2003–2013): cumulative excess return in positive-reversal windows **+103%** (≈73% of total US equity excess return over that decade); selling-pressure windows **−31%**; correlation of T−3..T−1 with T−8..T−4 returns **−0.54**.
- ANcerno: institutions are net sellers into T−4 (strongest) and into T−3 morning; a 1-sd increase in net selling over T−8..T−4 predicts **+0.32 to +0.67** percentage points higher T−3..T−1 market returns (Table 5).

### In- or out-of-sample
- **In-sample** documentation of the payment-cycle / settlement mechanism through **2013**. International quasi-experiment around a European settlement-rule change supports causality of settlement timing. Not a long-only SPY ETF costed backtest.

---

## 3. Settlement eras inside our span (mechanism, before any data)

| Era | Settlement | Dates (SEC compliance) | Cash for morning of T requires sale by close of | Implied Etula-width window if shifted |
|---|---|---|---|---|
| 1 | T+3 | development start → **2017-09-04** | **T−4** | T−8..T−4 (Etula as written) |
| 2 | T+2 | **2017-09-05** → **2024-05-27** | **T−3** | T−7..T−3 (+1 trading day later) |
| 3 | T+1 | **2024-05-28** onward | **T−2** | T−6..T−2 (+1 further) |

**Citations:** SEC press release 2017-68 (T+2 compliance **Sept. 5, 2017**); SEC T+1 FAQ / Investor.gov bulletin (T+1 compliance **May 28, 2024**). Access date 2026-11-18.

**Candidate dimension (literature does not settle it for post-2017 US equities):**
- **`fix`:** keep Etula’s T−8..T−4 (or the narrower core) in every era — institutions may still sell early out of habit or risk management.
- **`shift`:** move the inclusive window **one trading day later** for each one-day shortening of settlement, matching the T−s close rule above.

Both enter the grid (section 11). No return series was used to choose the dates or the shift rule.

---

## 4. McConnell & Xu (FAJ 2008)

### Sample and window
- **Market:** CRSP daily US equities; international check in 35 countries.
- **Sample:** **1926–2005** (with a post-discovery slice **1987–2005**).
- **Window:** classical TOM = **last trading day + first three** of the next month (Lakonishok & Smidt −1..+3).

### Effect size
- Average daily value-weighted return on the four TOM days **0.15%** vs **−0.001%** on other days (1926–2005). Authors: on average, investors received no reward for bearing market risk **except** at turns of the month; effect in 31 of 35 countries; **not** explained by volume or equity-fund flows in their tests. They call it “a puzzle in search of an answer.”

### In- or out-of-sample
- In-sample through **2005**. Our development years **2006–2024** are after their sample end (except the single year 2005).

---

## 5. Lakonishok & Smidt (RFS 1988)

### Sample and window
- **Instrument:** DJIA daily returns.
- **Sample:** **1897–1986**.
- **Window:** four trading days from the **last day of the month through the third day of the next** (−1..+3).

### Effect size (as restated by McConnell & Xu / Quantpedia)
- Cumulative average return over the four TOM days **0.473%** vs **0.349%** for the full month — implying **negative** average returns on the other days. All of the DJIA’s positive return over 1897–1986 sat in that four-day window on their reading.

### In- or out-of-sample
- Entirely before our development span. Foundational definition of classical TOM; **not** the pre-TOM selling window this experiment exits.

---

## 6. Decay evidence (post-2013 / post-publication)

### Gil (Católica Portuguesa MSc, 2025) — 2006–2023
- Compares McConnell & Xu’s **1987–2005** presence of the end-of-month effect with **2006–2023** CRSP value- and equal-weighted indexes.
- Finds the end-of-month anomaly **vanished** in 2006–2023. Event-study abnormal / cumulative abnormal returns; market-efficiency explanation **not conclusively** supported.
- **Overlap with us:** almost the entire development span. Binding for classical TOM on our years.

### Han, Han & Tian (FRL 2025)
- Classical TOM **disappears entirely after 2001** in their sample; Ogden (1990) liquidity story no longer holds over the past two decades; they point to lower transaction costs enabling arbitrage and less concentrated month-end trading.
- **Overlap:** if TOM is gone after 2001, essentially **all** of 2005–2024 is in their “disappeared” regime.

### Aalto international thesis (handle 123456789/121876)
- 15 international indices: TOM present in 14/15 for **1983–2013**; for **2014–2022** the effect has **almost completely faded** (New Zealand the main exception after seasonal controls).
- Supports a post-2013 international fade of classical TOM, not a US SPY pre-TOM exit test.

**Implication for C2’s selected direction.** Decay evidence targets the **classical TOM premium** (−1..+3), not always Etula’s **T−8..T−4** selling pressure. Etula’s US sample still ends **2013**. A long-only **exit** on selling days needs those days to keep losing after 2013; the published decay record does not establish that. A fail is expected (`docs/IDEA_LIST.md`).

---

## 7. Graziani (Bocconi JMP 2024) — related only

### What it is
- Aggregate **time-series reversal**: S&P 500 **end-of-month week** return negatively predicts the **next month’s** return; pension month-end liquidity selling (ANcerno; cites Etula et al.). Main sample often **1975–2019**, with robustness into **2023**.
- Trading sketch is **month-scale** long/flat (or long/short) after observing the month-end week — **not** “out on T−8..T−4 every month.”

### Role here
- Corroborates that **pension payment-cycle selling** remains a live research mechanism after Etula.
- **Not** a candidate in this version (different horizon and signal). Parked for a later idea / variant if ever selected.

---

## 8. Overlap table

Development span stated in the plan / idea list: **2005–2024**. Scored validation quarters with `FOLD_TRAIN_WINDOW_YEARS = 10` → **2015–2024** (same convention as exp14). Holdout = registered 12-month window after the development boundary (**not opened** here).

| Source | Sample end (relevant) | Overlap with 2005–2024 | Years in 2005–2024 after the source | After holdout start? |
|---|---|---|---|---|
| Lakonishok & Smidt 1988 | 1986 | none | all 2005–2024 | yes |
| McConnell & Xu 2008 | 2005 | 2005 only | **2006–2024** | yes |
| Etula et al. 2020 | Dec 2013 | **2005–2013** | **2014–2024** | yes |
| Graziani 2024 (related) | ~2019 / 2023 robustness | most of 2005–2019(+) | residual late years | holdout after his main end → largely yes |
| Gil 2025 | 2023 | **2006–2023** | 2024 (+ holdout) | holdout after 2023 → yes for Gil |
| Han et al. 2025 | post-2001 “gone” claim | effectively **2005–2024** inside claim | none under their claim | holdout also inside claim |
| Aalto thesis | 2022 (fade subsample 2014–2022) | international; 2014–2022 fade years | 2023–2024 | yes |

**Plain statement:** for Etula, **2014–2024** (and all scored 2015–2024 quarters) are out of sample. For classical-TOM decay studies, almost all of our development span is **inside** their “effect gone” window — the binding caution for expecting a pass.

---

## 9. Evidence verdict (2026-11-17 criteria)

Criteria (`docs/STAGE1_RESEARCH_PLAN.md` §1.1 point 9): weight **replicated out-of-sample** evidence; prefer **rare trading**.

| Criterion | Reading |
|---|---|
| Mechanism published | Yes — payment cycle + settlement lag (Etula); classical TOM (Lakonishok & Smidt; McConnell & Xu). |
| Early replication | Classical TOM replicated across decades and countries through ~2005; Etula’s settlement/payment story international + ANcerno. |
| Post-2013 / OOS | Classical TOM **faded** (Gil 2006–2023; Han et al. after 2001; Aalto 2014–2022). Etula’s selling window **not** cleanly re-established on post-2013 US data in these sources. |
| Rare trading | ~5 sessions/month out → ~**25%** time in cash, ~**12** round trips/year (first principles) — cost-friendlier than exp14’s intraday skips, costlier than a 1–2 trade/year idea. |
| Fit to our verdict | Long-only unlevered total return vs buy-and-hold after costs. Papers are mostly day-of-month average returns / mechanism tests, not our exact costed overlay. |

**Verdict: evidence for a usable long-only pre-TOM exit on our span is weak-to-medium at best; a fail is the expected outcome.** What would **surprise**: a prior-only path that still clears the return part (and especially the lower tier’s $0.02 / T-bill−0.5% checks) on **2015–2024** scored quarters despite the decay literature — that would be news relative to Gil / Han, not a confirmation of Etula’s 1995–2013 sample alone.

---

## 10. Mechanics on our runner

### Decision time and fill (`docs/RUNNER_DESIGN.md`)
- **Daily** engine; proposed `trailing_stop` without a stop (`RuleDesign`: invested by default; exit / re-entry).
- Decision at end of **15:58** bar; fill at **15:59** open.
- To be out for the session returns of trading days **a..b** inclusive: sell at the **15:59** fill of the session **before** a; buy at the **15:59** fill of day **b**.

### Calendar: two options

**(a) Rule-coded NYSE holiday calendar inside the design.** Scheduled holidays are published well in advance. Unscheduled closures (Hurricane Sandy 2012, national days of mourning, etc.) are **treated as trading days** in the day count, matching what a trader would have assumed in real time before the closure was announced.

**(b) `so.core.datetime_utils`** (wraps `pandas_market_calendars` NYSE). `so.runner.preflight` does **not** ban `so.core.datetime_utils` (banned set is `so.runner`, `so.core.point_in_time`, `so.core.holdout`, I/O, etc.). That calendar **already knows** historical unscheduled closures, so counting “trading days to month end” with it embeds a **small look-ahead** relative to a 2005–2024 real-time trader.

**Recommendation: (a).** Implement a frozen list / rule of scheduled NYSE holidays in the experiment package; document that unscheduled closures stay in the day count. **Test (synthetic only):** assert day indices around a known scheduled holiday month; assert that a known unscheduled-closure date is still counted as a session in the design’s calendar even though `pandas_market_calendars` would omit it.

---

## 11. Expected time out, switches, and costs

**First principles (not our data):**
- ~**21** sessions per month; Etula width 5 → about **5/21 ≈ 24%** of sessions in cash; narrower core 2 → ~**10%**.
- One exit and one re-entry per month → about **12 round trips per year** (24 fills).

**Our costs (`so/config.py`):**
- Slippage: entry **$0.01** + market exit **$0.01** per share → **$0.02**/share round trip before fees.
- Fees: **$0.005**/share/side, **$1** minimum/side, 1% cap → about **$0.01**/share when the floor does not bind → **≈ $0.03**/share round trip.
- Lower tier also requires beating buy-and-hold at **$0.02** slippage (`COST_SENSITIVITY_SLIPPAGE_LIST`) and cash at T-bill **minus 0.5%** (`CASH_RATE_SENSITIVITY_SPREAD = 0.005`).

**Inference:** twelve round trips/year can bear dollar costs **if** the skipped sessions lose more than T-bill cash by more than ~$0.03/share each month on average. Etula’s mild −0.03%/day on five days is order **−15 bp** per month gross in-sample — in the same ballpark as costs at plausible SPY prices, with **no** allowance for decay. Costs are therefore a first-order risk even before the fade evidence.

`docs/RESULTS_LOG.md` (allowed): exp14 failed after costs on a higher-turnover intraday skip — reinforces preferring rare trading, not evidence about TOM days.

---

## 12. Candidate grid (4 designs)

Not a full cross-product. Dimensions: **window edges** (Etula −8..−4 vs narrower −5..−4 core near peak ANcerno selling) × **fixed vs settlement-shifted**.

| # | Name | Window | Settlement | Why |
|---|---|---|---|---|
| 1 | `w84\|fix` | T−8..T−4 | fixed | Etula headline selling-pressure window |
| 2 | `w84\|shift` | width 5, shifted per era | shift | Mechanism-consistent settlement update |
| 3 | `w54\|fix` | T−5..T−4 | fixed | Narrower core; fewer days out / fewer cost days |
| 4 | `w54\|shift` | width 2, shifted per era | shift | Narrow core + settlement update |

**Not in this version:** classical in-only −1..+3; out on T+4..+10; Graziani month-scale reversal; Friday-month-end interaction (Etula’s amplification); international confirmation search.

**Folds:** `FOLD_TRAIN_WINDOW_YEARS = 10` → validation quarters **2015–2024**.

**Trial budget:** 4 (= 4 designs in N). Family C idea C2 variant **1 of 5**; up to two further versions of this experiment.

---

## 13. Open questions for the review

1. **Calendar:** confirm recommendation **(a)** rule-coded scheduled holidays (vs allowing `datetime_utils` with an explicit look-ahead waiver)?
2. **Shift rule:** is “+1 trading day later per shorter settlement step” the right pre-registered mapping, or should T+1 use a different width?
3. **Core window:** is T−5..T−4 the right narrow alternative, or prefer T−6..T−4 / T−4 alone?
4. **Engine:** confirm `trailing_stop` + `RuleDesign` vs `fractional` weights in {0,1}.
5. **Sources list:** is `TSDAY` required beside `SPY_1MIN` for RuleDesign, or bars alone?
6. **Folds:** keep 10-year folds (scored 2015–2024, cleaner vs Etula) or shorten to keep crisis years in scored quarters?
7. **Friday T amplification** (Etula): park for a later variant, or add a 5th candidate now?
8. **Graziani:** stay related-only for this experiment (recommended)?

---

## 14. Bottom line

Etula et al. give a clear, settlement-timed **pre-TOM selling** window (T−8..T−4 under T+3) that fits a rare long-only exit. Classical TOM papers motivate staying **invested** through T−3..T+3. Post-2013 decay evidence (Gil; Han et al.; Aalto international) makes a **fail** the expected outcome on our scored years. Settlement must be fixed per SEC era in advance; day counts should use a **scheduled-holiday** calendar without unscheduled-closure look-ahead. A 4-candidate grid (width × fixed/shift) is the proposed pre-registered test. No SPY or rate series was read to write this brief.
