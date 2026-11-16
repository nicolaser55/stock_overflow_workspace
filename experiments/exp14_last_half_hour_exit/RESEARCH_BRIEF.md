# RESEARCH_BRIEF: exp14 last-half-hour exit on weak days (idea I1)

*Prepared 2026-11-16 on branch `agent/exp14-last-half-hour-exit`. No market data, prices, caches or
development results were read for this brief. Numbers below are from the cited papers and from
`so/config.py` / `docs/RUNNER_DESIGN.md` only.*

Status of idea I1 in `docs/IDEA_LIST.md`: **selected (2026-11-16): exp14**. Family I has 3 slots left
(`docs/STAGE1_RESEARCH_PLAN.md` section 4). The 2026-11-16 review decisions are applied below and in
`PROTOCOL.md`. `config.py`, `design.py` and synthetic tests now exist. `PROTOCOL.md` stays a **DRAFT**
(not a `preregister` commit). Trial budget of this version: **6**.

---

## 1. Sources read

| Source | What was read |
|---|---|
| Gao, Han, Li & Zhou, “Market Intraday Momentum”, *JFE* 129 (2018) 394–414 | Full published PDF (courtlistener exhibit / journal text) |
| Baltussen, Da, Lammers & Martens, “Hedging Demand and Market Intraday Momentum”, *JFE* 142 (2021) 377–403 | Full published PDF (Notre Dame working/published text) |
| CXO Advisory, “First and Last Half Hours of Trading Linked?” (Steve LeCompte, 11 Jun 2014) | Full note at the URL listed in `docs/IDEA_LIST.md` Sources |
| Dim, Eraker & Vilkov, “0DTEs: Trading, Gamma Risk and Volatility Propagation”, SSRN 4692190 | Abstract only (one web search, 2026-11-16). No SPY, VIX or rate levels taken from it |
| “Delta-hedging demand and intraday momentum: Evidence from China”, *Physica A* 600 (2022) | Abstract / IDEAS record only (same search). Authors not named in the snippet |
| “Intraday momentum in the VIX futures market”, *Journal of Banking & Finance* 148 (2023) | Abstract / IDEAS record only (same search). VIX futures, not a SPY level |
| Cboe, “Much Ado About 0DTEs: Separating Fact From Fiction” (note circulated 2023; PDF dated in the path 2023/09) | Search snippet of the note. No index, VIX or rate levels copied from it |

No other CXO notes are listed under I1 in `docs/IDEA_LIST.md`. Abstracts on WashU Profiles and Erasmus Pure were checked; effect sizes below come from the full papers / CXO page, not the abstracts alone. The post-2020 rows are one web search (section 7). No SPY, VIX or interest-rate values after 2024-12-31 were looked up.

---

## 2. Gao, Han, Li & Zhou (JFE 2018)

### Sample and instrument
- **Instrument:** SPY (TAQ), half-hour returns. Robustness also on S&P 500 futures / index (appendix) and ten other liquid ETFs.
- **Sample:** 1 Feb 1993 – 31 Dec 2013. Days with fewer than 500 trades dropped.
- **Partition:** 13 half-hours. First half-hour return \(r_1\) = previous close (16:00) → 10:00. Last half-hour \(r_{13}\) = 15:30 → 16:00. Twelfth half-hour \(r_{12}\) = 15:00 → 15:30.

### What predicts what
- \(r_1\) positively predicts \(r_{13}\) (time-series market intraday momentum).
- \(r_{12}\) also predicts \(r_{13}\); jointly complementary (slopes barely change; \(R^2\) roughly adds).
- Overnight-only and other early windows give similar results (authors’ note).

### Reported size of the last-half-hour effect
- In-sample (Table 1): \(\beta_{r_1}\) = 6.94 (scaled by 100), **\(R^2\) = 1.6%**; with \(r_1\) and \(r_{12}\), **\(R^2\) = 2.6%**.
- Out-of-sample recursive \(R^2_{OS}\): **1.4%** (\(r_1\)), **2.0%** (both).
- Market timing \(\eta(r_1)\): long last half-hour if \(r_1 > 0\), short if \(r_1 \le 0\) (Table 6): **+6.67% p.a.** avg return, Sharpe **1.08**, success 54.4%. Always-long last half-hour: **−1.11% p.a.** Buy-and-hold (full day): +6.04% p.a., Sharpe 0.29.
- Certainty-equivalent gain vs historical-average forecast (γ = 5, weights in [−0.5, 1.5]): **6.02% p.a.** (\(r_1\)); **6.18%** (both).
- After bid/ask at 15:30 (post-decimalization, Table 11A): \(\eta(r_1)\) **4.46% p.a.** After Jan 2005 (spread ~**1.2 bp** one-way, Fig. 3): **6.52% p.a.** after spread; implementation-shortfall break-evens ~**1.5–1.6% p.a.** (low/high commission on 1,000 shares).

### Where stronger
- High first-half-hour volatility tercile: joint \(R^2\) **3.3%** vs 0.6% low (Table 3).
- High volume tercile: joint \(R^2\) **3.1%**.
- Financial crisis Dec 2007 – Jun 2009: \(r_1\) \(R^2\) **4.1%**, joint **6.9%** (Table 2).
- NBER recessions: joint \(R^2\) **6.6%** vs **1.0%** in expansions (Table 8).
- Macro news days: MCSI / GDP / CPI / FOMC minutes all raise \(R^2\); FOMC minutes days joint \(R^2\) **11.0%**; \(\eta(r_1)\) on FOMC release days **~20% p.a.** annualized (Table 9).
- **Conditional on sign of \(r_1\) (Table 10): stronger when \(r_1 > 0\)** (joint \(R^2\) 4.5%) than when \(r_1 < 0\) (joint \(R^2\) 0.9%). This matters for a long-only *skip on weak days*.

### Decay / later evidence in the paper itself
- Excluding the crisis, \(r_1\) still significant but weaker (\(R^2\) **0.8%**).
- Recursive slopes (Fig. 1): \(r_1\) remains positive through 2013; no disappearance claimed inside-sample.
- Sample ends **2013**: nothing post-2013 in this paper.

### Overlap with our development data (2005–2024)
- Overlap: **2005–2013** (nine calendar years). That slice is partly a replication of data the authors saw.
- Our **2014–2024** years are after Gao’s sample end (cleaner for independence; still not a holdout).

---

## 3. Baltussen, Da, Lammers & Martens (JFE 2021)

### Sample and instrument
- **Instruments:** 60+ futures — 17 equity index (incl. **ES / S&P 500**), 16 bond, 21 commodity, 8 currency. Tick Data LLC, one-minute bars.
- **Sample:** Dec 1974 – May 2020 (~45 years).

### What predicts what
- Last 30 minutes before close \(r_{LH}\) is positively predicted by **rest-of-day** \(r_{ROD}\) = previous close → 30 minutes before close (stronger than Gao’s overnight+first-half \(r_{ONFH}\)).
- When \(r_{ROD}\) and \(r_{ONFH}\) disagree in sign, \(r_{ROD}\) generally wins (Table 3 horse race).
- Mechanism claim: **short-gamma hedging** by option dealers and leveraged ETFs (plus related dynamic hedgers). Predictability of \(r_{LH}\) **reverts over subsequent days** (pressure, not permanent information) — favours hedging over pure late-informed trading.

### Reported size (equity futures, pooled)
- Table 2 Panel A: \(r_{ONFH}\) adj. \(R^2\) **1.49%**, OOS \(R^2\) **−1.71%**; \(r_{ROD}\) adj. \(R^2\) **2.45%**, OOS \(R^2\) **2.88%**. Slope \(\beta_{ROD}\) = 4.18 (×100).
- Timing \(\eta(r_{ROD})\) equity 1/N portfolio (Table 6): **+6.86% p.a.**, Sharpe **1.73**, success 0.55. Always-long last half-hour: **+0.44% p.a.** (sign differs from Gao’s −1.11% on SPY — different instrument/sample). Asset-class Sharpes for \(\eta(r_{ROD})\): **0.87–1.73**.

### Where stronger
- Linked to option market-maker net gamma and LETF hedging demand (section 4): stronger when hedgers are more short gamma / LETF AUM larger.
- Present in both **1974–1999** and **2000–2020** halves (Table 5); authors stress persistence while hedgers exist.
- Large intraday jumps trigger same-direction follow-through (Table 10), with residual last-half-hour predictability if hedges are incomplete.

### Decay
- No disappearance through **May 2020**. Authors note Feb–May 2020 was strong, consistent with hedging anecdotes.
- They **do not** apply retail ETF costs; for ES they say a **one-tick** cost can leave a positive net Sharpe for advanced futures traders. Frequent rebalancing “might not be exploitable to many investors” after costs — open for SPY ETF round-trips.

### Overlap with our development data (2005–2024)
- Overlap: **2005 – May 2020**. Years **mid-2020 through 2024** are after their sample.
- Instrument gap: their headline equity result is **futures**, not SPY cash ETF (Gao is the SPY paper).

---

## 4. CXO Advisory (11 Jun 2014)

### Sample and instrument
- Summarises the May 2014 working-paper version of Gao et al.: SPY from Jan 1999, QQQ from Mar 1999, through Dec 2012, plus macro release dates.
- **Own check:** SPY Aug 2012 – May 2014 (441 sessions) from CXO’s “Recent Intraday U.S. Stock Market Behavior” data.

### What predicts what / size
- Paper (as summarised): in-sample \(R^2\) ~0.02 for first→last half-hour; OOS \(R^2\) up to **0.018**; first+12th half-hours up to **0.027** OOS. Gross timing (long last half-hour if first positive, cash if negative): **6.3% vs −0.5%** annualized for always holding the last half-hour (Jan 1999–Dec 2012).
- Stronger with volatility, recessions, some news days (matches published Gao).
- **CXO replication:** Pearson corr **0.12**, \(R^2\) **0.014** (still present, weak). Decile chart: **extreme first half-hours drive the anomaly**; average last-half-hour returns in the extreme first-hour deciles are **too small for most investors after trading frictions**.

### Decay
- Explicit caution: authors’ economic tests **ignore frictions**; CXO’s 2012–2014 check finds the link **still there but weak**, and magnitude at extremes **swamped by costs** for typical investors.
- Data-snooping warning on volatility/news overlays.

### Overlap with our development data
- Working-paper sample through 2012 and CXO check **2012–2014** sit inside 2005–2024. Reinforces that the late Gao window already looked thin after costs.

---

## 5. Map onto our runner (R4c, verdict, costs)

### Decision times, prices and fills (`docs/RUNNER_DESIGN.md`, Intraday decision times)
- Engine: **`fractional` only** (required for `INTRADAY_DECISION_TIME_LIST`).
- Declare `INTRADAY_DECISION_TIME_LIST = ["15:30"]`.
- Bars are start-labelled (`SPY_1MIN`). **Previous close** = close of the previous session’s last bar (on a full day, the 15:59 bar, whose close is 16:00).
- **`fh`** = previous close → close of the **09:59** bar (the 10:00 price). Gao’s first half-hour.
- **`rod`** = previous close → close of the **15:30** bar. Baltussen’s rest-of-day through the decision.
- At **15:30**: `decide(view)` with the view ending at that bar; `view.intraday_time_str == "15:30"`. Fill = **next bar’s open** (15:31 open). Target weight only (or NaN = keep).
- At **15:58** (daily call): `intraday_time_str is None`. Target weight **1**. Fill at **15:59** open.
- The cash spell is **15:31 → 15:59**. The last minute (the 15:59 bar) and the close stay held. That is shorter than Gao’s \(r_{13}\) (15:30–16:00), which includes the close.
- Early close (no mappable 15:30 bar, for example a 13:00 close): **no intraday call, and no skip**.
- A missing exact bar (no 09:59 bar for `fh`, no 15:30 bar for `rod`, no previous session): **do not skip** (NaN = keep). A nearby bar is not a substitute. A missing 15:30 minute maps, in the runner, to the previous bar; the design still requires the 15:30 bar’s close for `rod`.
- Same slippage and fees on every fill (decided 2026-11-11).
- **No special intraday cash accrual.** Cash earns the runner’s T-bill credit on cash held at the previous close (`open_session`). The half-hour skip does not get its own interest calculation.

### Long-only overlay (review decision)
- Default: weight **1** (fully invested).
- At 15:30: target weight **0** only when the signal return is **strictly below** \(-x\). A return **equal to** \(-x\) does not skip (weight 1).
- At 15:58: target weight **1** (buy back if the 15:30 call sold; no trade if the account is already at 1).
- **Why the weak side.** Baltussen, Da, Lammers & Martens tie last-half-hour continuation to leveraged-ETF rebalancing and to option dealers who are short gamma: on a down day those hedgers sell into the decline, which extends it into the close. That is the reason to step aside when the day is already down.
- **Limitation, not a flip of the sign.** Gao Table 10: the link is weaker when \(r_1 < 0\) (joint \(R^2\) 0.9%) than when \(r_1 > 0\) (joint \(R^2\) 4.5%). This overlay only uses that weaker side.
- Identity that can beat buy-and-hold after costs: skipped spells must return **less** than cash (T-bill) over those minutes, by more than round-trip costs. The verdict return part needs prior-only **total return strictly above** buy-and-hold (`docs/RUNNER_DESIGN.md`).

### Our costs per round trip (`so/config.py`)
One skip = one sell fill + one buy fill:
- Slippage: `MARKET_EXIT_SLIPPAGE_PER_SHARE` **$0.01** on the sell + `ENTRY_SLIPPAGE_PER_SHARE` **$0.01** on the buy → **$0.02 / share**.
- Fees: `FEE_PER_SHARE_PER_SIDE` **$0.005** × 2 sides → **$0.01 / share**, subject to `FEE_MINIMUM_PER_SIDE` **$1** per side and `FEE_MAXIMUM_PCT_PER_SIDE` **1%** of trade value.
- When the $1 floor does not bind (typical full-account rebalance at `INITIAL_CAPITAL` = $100k): **≈ $0.03 / share** round trip.
- Cost sensitivity in the report (not verdict): slippage 0.00 / 0.01 / 0.02 with fees always on.

### Rough break-even move per trade (papers’ numbers only + our $/share cost)
- Express break-even as **dollars per share**, then as a fraction of price \(P\): need about **$0.03 / P** adverse last-half-hour move avoided (or ~**3 bp at \(P = \$100\)**, **2 bp at \$150**, **1 bp at \$300**). No SPY price series was read for this brief.
- From Gao: unconditional always-long last half-hour is **−1.11% p.a.** ≈ **−0.44 bp per session** if spread evenly over 252 days — **below** our round-trip cost at any plausible \(P\) unless skips are selective.
- Timed edge Gao quotes is long/short of the last half-hour every day (~**6.7% p.a.** gross; ~**6.5% p.a.** after ~1.2 bp entry spread post-2005). Our design only **skips** on weak days (half the edge at best, and Gao Table 10 says the **down** side of \(r_1\) is the weaker half). CXO: extreme-decile last-half-hour averages are **already too small after frictions**.
- Baltussen equity \(\eta(r_{ROD})\) **6.86% p.a.** is also a every-day long/short of \(r_{LH}\) on futures; they warn ETF-style costs may kill it for many investors.
- **Inference (not a data result):** break-even is tight; the experiment is largely a **cost test** of a selective skip. Thresholds that fire rarely (larger \(x\)) trade less often but need a larger conditional last-half-hour decline when they do.

---

## 6. Candidate grid (6 designs)

The VIX gate is **out** of this version. A large \(|\mathrm{signal}|\) already selects high-volatility days; the gate would halve the trade count and add 6 designs to N. `DATA_SOURCE_LIST = ["SPY_1MIN"]` only. Dividends and T-bills stay on the runner’s total-return path; `decide` does not read them.

| Dimension | Levels | Reason |
|---|---|---|
| **Signal** | `fh` = previous close → 09:59 close; `rod` = previous close → 15:30 close | Gao’s primary predictor vs Baltussen’s stronger \(r_{ROD}\). Both are knowable at the 15:30 call from SPY bars in the view. |
| **Threshold \(x\)** | 0.5%, 1.0%, 1.5% | IDEA_LIST sketch; CXO says extremes drive the mean effect. A flat “any negative” skip would trade too often for our costs. |

Complete list (6 = 2 × 3), every name a design in N:

1. `fh|x050`
2. `fh|x100`
3. `fh|x150`
4. `rod|x050`
5. `rod|x100`
6. `rod|x150`

Rule (all candidates): weight 1 by default; at 15:30 set weight 0 iff the signal return is strictly below \(-x\); at 15:58 set weight 1. Exactly \(-x\) does not skip. Missing bars: NaN (keep).

**Not in this version (park for later variants):** VIX or other stress gates; twelfth-half-hour confirmation; recession/news calendars; continuous regression weights; shorting the last half-hour.

**Baselines.** Runner shared baselines, same engine, same costs: buy-and-hold; daily-rebalanced constant exposure; 100-seed random timing. The information test is that **intraday-aware random-timing baseline** (`docs/RUNNER_DESIGN.md`, R4c): each non-base spell keeps its time of day, so a 15:30-to-15:59 cash spell is the rate-matched comparison. There is **no** always-skip baseline.

**Folds.** `FOLD_TRAIN_WINDOW_YEARS = 10`, the template’s fold-schedule name, set to the 10 years exp03 and exp04 store as `FIXED_TRAIN_WINDOW_YEARS`. Validation quarters are then **2015–2024**: after Gao’s sample end, and the same span the frozen V was built on. This **gives up 2008**, where Gao finds the effect strongest (crisis \(R^2\) 4.1% for \(r_1\), joint 6.9%).

**Trial budget:** 6 candidates this version; family I idea I1 **variant 1 of 5**; this experiment may still use two further versions (three in the family). N rises by 6 if this grid runs.

---

## 7. Post-2020 evidence (one web search, 2026-11-16)

One search for post-2020 evidence on market intraday momentum, including the growth of 0DTE options and dealer gamma since 2022. No SPY, VIX or rate values after 2024-12-31 were looked up. Snippets and titles only; the papers were not downloaded.

**A post-2020 replication of Gao’s SPY first-half-hour → last-half-hour result through 2024: none found.**

What the search did return:

- **Dim, Eraker & Vilkov (SSRN 4692190), “0DTEs: Trading, Gamma Risk and Volatility Propagation.”** They study the growth of same-day S&P 500 options. Market-makers’ inventory gamma is on average positive and negatively related to later intraday volatility. Positive inventory gamma strengthens intraday **reversal**; negative inventory gamma strengthens intraday **momentum**. They read that as delta-hedging, not as informed trading. https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190
- **Cboe, “Much Ado About 0DTEs: Separating Fact From Fiction” (2023).** On their reading, SPX 0DTE customer flow is balanced, so market-maker net gamma stays small relative to S&P futures liquidity and is not a one-sided short-gamma overhang. They report no rise in last-hour gap-move frequency in the year they studied, after 0DTE volume had grown. https://spotgamma.com/wp-content/uploads/2023/09/cboeqqq.pdf
- **“Delta-hedging demand and intraday momentum: Evidence from China”, *Physica A* 600 (2022).** Rest-of-day return predicts the last 30 minutes of the SSE 50 ETF; the authors link that to short-gamma hedging and say the predictability decays over the next three days. Not SPY. https://ideas.repec.org/a/eee/phsmap/v600y2022ics0378437122003624.html
- **“Intraday momentum in the VIX futures market”, *Journal of Banking & Finance* 148 (2023).** Intraday momentum in VIX futures shows up when net gamma is negative and fades when it is not. VIX futures, not the SPY cash ETF. https://ideas.repec.org/a/eee/jbfina/v148y2023ics0378426622003260.html

**Implication for this version (inference, not a data result).** Growth of 0DTE since 2022 does not, on this search, show that the weak-day last-half-hour decline got larger. If dealer gamma is often positive, hedging dampens moves (reversal) rather than extending a down day the way Baltussen’s short-gamma story does. That is a limitation on expecting the pre-2020 effect to be stronger now. The pre-registered test is still the weak-day skip.

---

## 8. Review decisions (2026-11-16)

The open questions in the step-1 draft are closed as follows. Nicolas and Claude reviewed; this revision applies their decisions.

1. **Weak-day skip stays.** Reason: Baltussen’s leveraged-ETF and short-gamma flow on down days. Gao’s weaker \(r_1 < 0\) evidence is a limitation, not a reason to skip strong days instead.
2. **VIX gate dropped.** Six candidates. A large \(|\mathrm{signal}|\) already selects high-volatility days; the gate would cut the trade count about in half and add six designs to N.
3. **Prices** are the 09:59 close (`fh`) and the 15:30 close (`rod`), each over the previous session’s last-bar close. The skip is 15:31 → 15:59; the last minute and the close stay held.
4. **No special intraday cash accrual.** Early close: no call, no skip.
5. **No always-skip baseline.** The runner’s intraday-aware random-timing baseline (R4c) is the rate-matched information test.
6. **Folds:** 10 training years (`FOLD_TRAIN_WINDOW_YEARS`, the template name; exp03/exp04 call the same length `FIXED_TRAIN_WINDOW_YEARS`). Validation quarters 2015–2024. This gives up 2008.
7. **Family ledger / `docs/IDEA_LIST.md`:** still Nicolas’s. Both files are protected; this revision does not edit them.
8. **Step 2** is this revision: brief, draft protocol, `config.py`, `design.py`, synthetic tests. Still not a `preregister` commit and not queued.

---

## 9. Bottom line

The literature supports a small positive link from earlier-day returns into the last half-hour, with a hedging story that is conditional on dealers being short gamma. CXO and Gao’s own cost section say the per-trade move is small; our round trip of about $0.03/share is the binding constraint. This version tests two signal definitions and three thresholds (6 designs), on validation quarters after Gao’s sample, and leaves 2008 out of the scored windows. No SPY, VIX or rate series was read to write it.
