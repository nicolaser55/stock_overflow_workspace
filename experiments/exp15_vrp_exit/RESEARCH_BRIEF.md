# RESEARCH_BRIEF: exp15 variance risk premium exit (idea V1)

*Prepared 2026-11-18 on branch `agent/exp15-vrp-exit`. No market data, prices, caches or
development results were read for this brief. Numbers below are from the cited papers and from
`so/config.py` / `docs/RUNNER_DESIGN.md` / `docs/DATA_SOURCES.md` only. No file under
`D:\stock_overflow\data` was opened.*

Status of idea V1 in `docs/IDEA_LIST.md`: **selected (2026-11-17): exp15_vrp_exit** (family V,
idea V1, variant 1 of 5; the last V slot). Family V closes once exp15 runs
(`docs/STAGE1_RESEARCH_PLAN.md` section 4). This is **step 1 only**: research brief and DRAFT
protocol. `config.py` holds only `EXPERIMENT_NAME`; `design.py` is still the template.
`PROTOCOL.md` carries `DRAFT (step 1, not preregistered)`. Trial budget of this draft version: **4**.

---

## 1. Sources read

| Source | What was read | URL | Access date |
|---|---|---|---|
| Bollerslev, Tauchen & Zhou, “Expected Stock Returns and Variance Risk Premia”, *RFS* 22 (2009) 4463–4492 | Full published PDF (Duke copy) | https://public.econ.duke.edu/~boller/Published_Papers/rfs_09.pdf | 2026-11-18 |
| Bollerslev, Marrone, Xu & Zhou, “Stock Return Predictability and Variance Risk Premia: Statistical Inference and International Evidence”, *JFQA* 49 (2014) 633–661 | Full published PDF (Duke copy) | https://public.econ.duke.edu/~boller/Published_Papers/jfqa_14.pdf | 2026-11-18 |
| Pyun, “Variance Risk in Aggregate Stock Returns and Time-Varying Return Predictability” (working paper; Oct 2016 / Feb 2018 draft on author site) | Full PDF | https://sjpyun.github.io/VRPTS.pdf | 2026-11-18 |
| Goyal, Welch & Zafirov, “A Comprehensive 2022 Look at the Empirical Performance of Equity Premium Prediction”, *RFS* 37 (2024) 3490–3557 | Full journal PDF (Welch copy) | https://www.ivo-welch.org/research/journalcopy/goyal2024comprehensive.pdf | 2026-11-18 |
| Bekaert & Hoerova (JE 2014 / listed in GWZ as related VIX–variance-premium work) | Named only via GWZ’s discussion of BTZ; not read in full | (via GWZ) | 2026-11-18 |

One web search (2026-11-18) for post-publication / OOS evaluations of the variance risk premium.
No SPY, VIX or interest-rate levels were taken from any page.

---

## 2. Bollerslev, Tauchen & Zhou (RFS 2009)

### Sample and instrument
- **Instrument:** S&P 500 excess returns; risk-neutral variance from the CBOE **VIX** (model-free); realized variance from high-frequency S&P 500 returns.
- **Sample:** January 1990 – December 2007 (monthly).
- **Construction:** \(VRP_t = IV_t - RV_t\). \(IV_t\) = squared VIX (monthly units). \(RV_t\) = sum of squared **five-minute** log returns over the month (~22 sessions × 78 five-minute intervals ≈ 1716 returns). High (low) premium → high (low) subsequent returns.

### Horizon and effect size (in-sample)
- Monthly horizon: adj. \(R^2\) **1.07%**, one-sided 5% slope significance.
- **Quarterly (h = 3):** adj. \(R^2\) **6.82%**, Hodrick t-statistic **2.86** (Table 2) — the peak.
- Six-month still significant; effect fades at longer horizons.
- Authors stress model-free IV and high-frequency RV; Black–Scholes / daily-RV versions are weaker (adj. \(R^2\) ~2.16% for the “old” spread vs 6.82% for the model-free one).

### In- or out-of-sample
- **In-sample** predictability regressions on 1990–2007. No rolling OOS exercise in the main tables.

### Overlap with our development span (2005–2024) and the holdout year
- Overlap: **2005–2007** (three calendar years inside BTZ). Those years are a partial replication of data the authors saw.
- Our **2008–2024** years are after BTZ’s sample end → genuinely out of sample for BTZ.
- The registered **holdout year** (12-month window after the development boundary; agents do not read it) is after BTZ’s sample.

---

## 3. Bollerslev, Marrone, Xu & Zhou (JFQA 2014)

### Sample and instrument
- **Markets:** US S&P 500 plus France, Germany, Japan, Switzerland, Netherlands, Belgium, UK (model-free implied variances where liquid).
- **International / crisis sample:** January 2000 – December 2011 (monthly), chosen to span the financial crisis and a common panel start.
- **Monte Carlo block:** daily US returns and VRP Feb 1996 – Dec 2007 (aligned with BTZ’s end) to show finite-sample biases do not explain the hump-shaped \(R^2\) pattern.
- Same broad VRP definition: option-implied variance minus realized variance.

### Horizon and effect size
- Predictability pattern similar to BTZ: strongest around **3–5 months**.
- Country-specific slopes are present but **attenuated** vs the US; a market-cap-weighted **global** VRP predicts more strongly and more uniformly across countries (panel).
- Authors present this as corroboration **through the crisis**, not as a pure holdout of a frozen US rule.

### In- or out-of-sample
- Extends the US evidence into 2008–2011 (crisis) and abroad. Still regression evidence, not a long-only ETF timing backtest with our costs.

### Overlap with our development span
- Overlap: **2005–2011**. Years **2012–2024** are after this paper’s sample → out of sample for BMXZ 2014.
- Holdout year: after 2011 → out of sample for this source.

---

## 4. Pyun (2016 / 2018 draft): plain premium’s out-of-sample weakness

### Sample and instrument
- **Market:** S&P 500 / VIX-based VRP measures; high-frequency RV (five-minute with one-minute subsampling).
- **Sample:** January 1990 – December 2016 (324 months; VIX availability).

### What he finds
- BTZ-style claim: VRP predicts up to about six months **in sample**.
- **Traditional rolling predictive regression (plain VRP):** monthly OOS \(R^2\) roughly **−0.8% to 5.2%**, **not statistically significant** across the VRP variants he considers. He states the plain OOS performance is “comparably weak.”
- His **contemporaneous-beta** method (multiply VRP by a within-month return–variance beta) raises OOS \(R^2\) to about **6–8%** and a Sharpe gain ~0.13 — but that is a **different** design from idea V1’s quantile exit on the plain premium.
- Notes the **large negative VRP spike in September 2008** when RV jumped and mean-reverted faster than VIX (Figure discussion): exactly the crash-then-rebound hazard for a low-premium exit.

### Overlap with our development span
- Overlap: **2005–2016**. Years **2017–2024** are after his sample → out of sample for Pyun.
- Holdout year: after 2016 → out of sample for Pyun.

---

## 5. Goyal, Welch & Zafirov (RFS 2024): post-publication evaluation

### Sample and instrument
- Re-examines 29 post–Goyal–Welch (2008) predictors through **December 2021**, including BTZ’s **`vrp`** (authors’ updated series, 1990:01–2021:12).

### What they find for `vrp`
- Original-sample IS coefficient confirmed (through 2007); extended forward to 2021 the IS t-statistic falls to **0.72** (Table 2).
- Homologous specification: IS coefficient **not significant**; **sign flips** positive → negative in the second half (Table A.1).
- OOSCT \(R^2\) positive but **small and insignificant**.
- **Investment strategies:** about **2.6% to 7.0% per year worse** than all-equity-all-the-time.
- Did well after the Great Recession; **turned poor in early 2020**.
- **Evaluation (authors’ words):** dismiss `vrp` as a useful equity-premium predictor (poor IS first, poor OOS second; investment performance poor too).

### Overlap with our development span
- GWZ already saw **2005–2021** of our development years. Only **2022–2024** (and the holdout year) are after their evaluation window — and even those are few years for a quarterly-horizon signal.
- This is the binding post-publication check under the 2026-11-17 criteria.

---

## 6. Overlap table (summary)

Development span stated in `docs/IDEA_LIST.md` / plan: **2005–2024**. Scored validation quarters depend on `FOLD_TRAIN_WINDOW_YEARS` (proposed **10** → quarters **2015–2024**, same convention as exp14). Holdout = registered 12-month window after the development boundary (not opened here).

| Source | Sample end | Overlap with 2005–2024 | Years in 2005–2024 genuinely after the source | After holdout start? |
|---|---|---|---|---|
| BTZ 2009 | Dec 2007 | 2005–2007 | **2008–2024** | yes (holdout after BTZ) |
| BMXZ 2014 | Dec 2011 | 2005–2011 | **2012–2024** | yes |
| Pyun 2016/18 | Dec 2016 | 2005–2016 | **2017–2024** | yes |
| GWZ 2024 | Dec 2021 | 2005–2021 | **2022–2024** only | holdout after 2021 → yes for GWZ |

**Plain statement:** for the strongest early papers, most of our span is OOS; for GWZ, almost all of our development span was already in their “extended to 2021” dismissal. A 2015–2024 scored window is mostly post-BTZ but **not** independent of GWZ.

---

## 7. Evidence verdict (2026-11-17 criteria)

Criteria (`docs/STAGE1_RESEARCH_PLAN.md` §1.1 point 9): weight **replicated out-of-sample** evidence heavily; prefer **rare trading**.

| Criterion | Reading |
|---|---|
| Mechanism published | Yes (BTZ equilibrium / volatility-of-volatility story; high VRP → high expected returns). |
| Early replication | Yes across countries and into the crisis (BMXZ 2014). |
| Plain-premium OOS | **Weak** (Pyun); **dismissed** through 2021 with poor investment performance (GWZ 2024). |
| Rare trading | Idea-list sketch (out in lowest q ∈ {5%,10%,20%}) implies ~5–20% time in cash — cost-friendly if switches are few. |
| Fit to our verdict | Long-only unlevered total return vs buy-and-hold after costs. Papers are mostly predictive \(R^2\) / long-short style evidence, not our exact test. |

**Verdict: evidence for the plain VRP as a usable timing signal is now weak.** Recommending **not** to spend the last V slot on V1 would have been reasonable *before* selection. Nicolas already selected V1 on 2026-11-17; this brief therefore treats a small pre-registered grid as an acceptable **clean negative-result test** of the idea-list sketch, while flagging that a pass (or even the lower tier) is unlikely on the published post-2021 record. Parking V1 and freeing the slot is still an option for Nicolas if he prefers another family after this review.

---

## 8. Mechanism and costs survival

**Mechanism (literature).** Investors pay for insurance against variance; implied variance usually exceeds realized. When that gap (the premium) is unusually **low**, expected equity returns are low → a long-only overlay can sit in cash. Strongest published horizon is about a **quarter**, which matches a daily rule that stays out for weeks, not minutes.

**Expected time out (first principles + idea list, not our data).** Idea list: **5–20%** of sessions in cash for q ∈ {5%,10%,20%}. Monthly VRP AR(1) in BTZ is about **0.49** (not extremely persistent), so spells should turn over within a few months rather than years.

**Switches per year (first principles).** If cash spells last on the order of 1–3 months and occupancy is 5–20%, round trips on the order of **roughly 1–6 per year** are the right ballpark — far below exp14’s intraday skip frequency. That is why V1 clears the “rare trading” preference even if the edge is small.

**Why it might still fail after costs.** GWZ’s investment strategies already lost **2.6–7.0% per year** to buy-and-hold *before* mapping to our IBKR fee schedule. Our round trip is about **$0.03/share** when the $1 fee floor does not bind (`ENTRY_SLIPPAGE_PER_SHARE` 0.01 + `MARKET_EXIT_SLIPPAGE_PER_SHARE` 0.01 + `FEE_PER_SHARE_PER_SIDE` 0.005 × 2; `so/config.py`). Rare trading can bear that **if** the skipped sessions lose more than T-bill cash earns by more than costs. The published record does not support that hope after 2008–2021.

---

## 9. Map onto our runner

### Sources (`so.core.point_in_time.SOURCE_SPEC_DICT`)
| Source | Role in this design |
|---|---|
| `SPY_1MIN` | Realized variance: squared log returns of 1-minute or aggregated 5-minute closes in the view |
| `VIX_DAILY` | Implied variance from the **previous** session’s daily VIX close (see clock below) |
| `TSDAY` | Optional session scaffolding / RuleDesign history (same pattern as other daily exits) |

`SPY_DIVIDENDS` and `TBILL_3M` stay on the runner’s total-return layer; `decide` does not read them. **No `VIX_1MIN` / VIX3M in this version** (plain BTZ proxy).

### Decision time and fill
- **Daily engine**, `trailing_stop` without a stop (`RuleDesign` pattern: invested by default; exit / re-entry flags).
- Decision at end of **15:58** bar; fill at **15:59** open (`docs/DATA_SOURCES.md`, `docs/RUNNER_DESIGN.md`).
- Follow **exp12** for VIX: previous-date daily close via a `VixPrevHistory`-style lag (at most `STALE_MAX_SESSIONS` sessions old). Follow **exp05** only in spirit for “volatility from history in the view”; exp05’s `daily_volatility` is close-to-close stdev — **this design builds RV from minute bars**, as BTZ require.

### Clocks (no look-ahead)
- **`VIX_DAILY`:** `available_ts` = that date at **16:15** New York → **same-session VIX close is not knowable at 15:58**. Use **previous session’s** close only (exp12 rule).
- **`SPY_1MIN`:** bar start; knowable one minute later. Bars through the decision bar are in the view at decision_ts.

### Implied and realized variance (point-in-time)
- **Implied (monthly variance units):** \(IV = (vix\_prev / 100)^2\) (VIX is annualized percent vol; squaring matches BTZ’s use of VIX²).
- **Realized:** sum of squared log returns over the last **22 completed sessions** (exclude the incomplete current session so the window is comparable across days). Sampling: **5-minute** (BTZ) or **1-minute** (idea-list robustness). Rescale to the same annualized / monthly units as \(IV\) before subtracting.
- **Premium:** \(VRP = IV - RV\). Low VRP → exit.

### Point-in-time quantile and warm-up
- Each decision: empirical **q**-quantile of all **prior** VRP values stored on the design (expanding window; never uses today’s VRP in the quantile cutoff that gates today — compute quantile from history strictly before appending today’s value, or equivalently use history up to yesterday).
- **Warm-up:** no exit until at least **252** prior VRP observations (about one year). Below that, stay invested (NaN keep / no flatten). First principles: at q = 5%, 252 points give ~12 left-tail counts; shorter windows make the quantile noisy.

### Missing VIX / early closes
- Missing or stale previous VIX (beyond the max lag): **no exit, no re-entry signal** (keep). Same spirit as exp12 (missing does not fire M3 suppress, and here missing does not move weight).
- Early-close sessions: still one 15:58-mapped decision if the runner maps it; RV for a short session uses whatever minute bars the view has for completed days only (today excluded). If the session cannot form a decision bar, the runner skips the call — position unchanged.
- Too few minute bars in a completed session to form the RV sampling grid: drop that session from the 22-day window and extend further back until 22 valid sessions exist; if still impossible after warm-up rules fail, keep invested.

---

## 10. The known risk (crash → negative premium → miss rebound)

**Fact from the literature.** After crash days, realized variance spikes above implied; VRP goes **negative** (Pyun on Sep 2008; BTZ figure also shows distinct spikes). A “exit when premium is in the left tail” rule therefore tends to go to cash **right when a rebound may start**. GWZ note poor performance in early 2020 fits the same hazard.

**How this draft handles it (fixed in advance, not tuned on our data):**
1. **Symmetric threshold, no delay that lengthens the miss:** exit while \(VRP \le q\)-quantile of history so far; re-enter when \(VRP\) is **strictly above** that same expanding quantile. No minimum time out (a minimum out would worsen rebound misses).
2. **Forced buy-back** after `MAX_CASH_SESSIONS = 60` cash decisions (same order as other daily exits such as exp03’s cap) so a crash-driven exit cannot leave the account in cash indefinitely.
3. **Stated limitation:** the literature implies this failure mode is intrinsic to the plain premium; hysteresis-at-median and “skip exit after a one-day RV jump” are **parked** for a later variant if 1.0 fails for that reason (would be a new protocol version, not a silent tweak).

---

## 11. Candidate grid (4 designs)

Prefer few, well-separated choices from the idea-list sketch (q ∈ {5%,10%,20%}; 1-minute vs 5-minute RV) over a full cross-product. All share: 22 completed sessions, expanding quantile, 252-session warm-up, 60-session max cash, daily trailing-stop engine without a stop.

| # | Name | q | RV sampling | Why in the grid |
|---|---|---|---|---|
| 1 | `q05\|rv5m` | 5% | 5-minute | Rarest exit; closest to “only extreme low premium”; BTZ sampling |
| 2 | `q10\|rv5m` | 10% | 5-minute | Middle of the idea-list range; default reference |
| 3 | `q20\|rv5m` | 20% | 5-minute | Most time out (~idea-list upper end); stress costs vs coverage |
| 4 | `q10\|rv1m` | 10% | 1-minute | Same q as #2; isolates microstructure / sampling sensitivity |

**Not in this version:** full 3×2 cross-product; Pyun’s contemporaneous-beta overlay; VIX3M term structure; expected-RV forecasts (EVRP); median hysteresis re-entry.

**Folds (proposal).** `FOLD_TRAIN_WINDOW_YEARS = 10` → validation quarters **2015–2024** (after BTZ; same scored span convention as exp14 / frozen V). Open question: whether to shorten folds to keep 2008–2009 in scored windows (see §13).

**Trial budget:** 4 candidates (= 4 designs in N). Family V idea V1 variant **1 of 5**; this experiment may still use two further versions (family cap three versions).

---

## 12. Costs and lower tier

From `so/config.py` and plan §1.1 point 4:

| Setting | Value | Role |
|---|---|---|
| Entry / market-exit slippage | $0.01 / share each | Standard path and verdict costs |
| Fee | $0.005 / share / side; $1 minimum / side; 1% cap | Standard |
| `COST_SENSITIVITY_SLIPPAGE_LIST` | 0.00, 0.01, **0.02** | Report; lower tier needs beat B&H at **$0.02** |
| `CASH_RATE_SENSITIVITY_SPREAD` | 0.005 (T-bill **minus 0.5%**) | Lower tier must still beat B&H |

**Inference:** with ~1–6 round trips/year the dollar costs are small relative to GWZ’s multi-percent annual shortfall. **Expected turnover can bear our costs; the published edge likely cannot.** Lower-tier eligibility also needs Derived from: none (yes), version 1.0 or bug-fix (yes if unchanged), and the idea’s OOS evidence recorded before the run (this brief) — but GWZ already undermines point (c)’s spirit even if the paperwork passes.

---

## 13. Open questions for the review (Nicolas / Claude)

1. **Run or park?** Given GWZ 2024’s dismissal, should exp15 proceed as a cheap negative test of the selected idea, or should V1 be parked and the last V slot left unused / reassigned?
2. **Folds:** keep `FOLD_TRAIN_WINDOW_YEARS = 10` (scored 2015–2024, cleaner vs BTZ, gives up 2008) or use a shorter fold length so crisis years enter scored quarters?
3. **RV window:** confirm **22 completed sessions, exclude today**, vs include today’s bars through 15:58.
4. **IV units:** confirm \((vix\_prev/100)^2\) annualized decimal variance, with RV rescaled to match, vs any other BTZ unit convention the implementer must match exactly.
5. **Forced buy-back:** is **60** cash sessions acceptable, or should there be **no** forced buy-back (closer to a pure signal, longer crash-miss risk)?
6. **Warm-up:** is **252** prior VRP points enough, or require **504** for a stabler 5% tail?
7. **Hysteresis in 1.0?** Keep symmetric q / re-enter above q (this draft), or add one hysteresis candidate (re-enter above expanding median) at the cost of a 5th design in N?
8. **Engine:** confirm `trailing_stop` + `RuleDesign` (exit/re-entry) rather than `fractional` weights in {0,1}.

---

## 14. Bottom line

Early BTZ / BMXZ evidence for the variance risk premium was strong in sample and internationally through the crisis. **Pyun shows the plain premium is weak out of sample; Goyal, Welch & Zafirov (2024) dismiss it through 2021 with investment strategies that lose to buy-and-hold.** Under the 2026-11-17 bar, V1’s evidence is **weak**. A 4-candidate rare-trading grid remains a coherent pre-registered test of the idea Nicolas selected; expectation: **fail the return part and/or lower tier**, with the crash-rebound hazard as a named limitation. No SPY, VIX or rate series was read to write this brief.
