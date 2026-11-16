# RESEARCH_BRIEF: exp14 last-half-hour exit on weak days (idea I1)

*Prepared 2026-11-16 on branch `agent/exp14-last-half-hour-exit`. No market data, prices, caches or
development results were read for this brief. Numbers below are from the cited papers and from
`so/config.py` / `docs/RUNNER_DESIGN.md` only.*

Status of idea I1 in `docs/IDEA_LIST.md`: **selected (2026-11-16): exp14**. Family I has 3 slots left
(`docs/STAGE1_RESEARCH_PLAN.md` section 4). This brief is step 1 of 3; `PROTOCOL.md` here is a **DRAFT**
only (not a `preregister` commit).

---

## 1. Sources read

| Source | What was read |
|---|---|
| Gao, Han, Li & Zhou, “Market Intraday Momentum”, *JFE* 129 (2018) 394–414 | Full published PDF (courtlistener exhibit / journal text) |
| Baltussen, Da, Lammers & Martens, “Hedging Demand and Market Intraday Momentum”, *JFE* 142 (2021) 377–403 | Full published PDF (Notre Dame working/published text) |
| CXO Advisory, “First and Last Half Hours of Trading Linked?” (Steve LeCompte, 11 Jun 2014) | Full note at the URL listed in `docs/IDEA_LIST.md` Sources |

No other CXO notes are listed under I1 in `docs/IDEA_LIST.md`. Abstracts on WashU Profiles and Erasmus Pure were checked; effect sizes below come from the full papers / CXO page, not the abstracts alone.

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

### Decision times and fills (`docs/RUNNER_DESIGN.md`, Intraday decision times)
- Engine: **`fractional` only** (required for `INTRADAY_DECISION_TIME_LIST`).
- Declare `INTRADAY_DECISION_TIME_LIST = ["15:30"]`.
- At **15:30**: `decide(view)` with view ending at that bar; `view.intraday_time_str == "15:30"`. Fill = **next bar’s open** (15:31 open). Target weight only (or NaN = keep).
- At **15:58** (daily call): `intraday_time_str is None`. Fill at **15:59** open (unchanged convention).
- Early closes without a mappable 15:30 bar: **no intraday call** that session.
- Same slippage and fees on every fill (decided 2026-11-11).

### Intended long-only overlay (idea sketch)
- Default: weight **1** (fully invested).
- At 15:30: if the chosen “weak day” signal is true, target weight **0** (sell into cash for the last ~half hour).
- At 15:58: target weight **1** (buy back; fill 15:59).
- Identity that can beat buy-and-hold after costs: skipped last-half-hour spells must return **less** than cash (T-bill) over those minutes, by more than round-trip costs — verdict return part needs prior-only **total return strictly above** buy-and-hold (`docs/RUNNER_DESIGN.md`).

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

## 6. Proposed candidate grid (12 designs)

Dimensions and why each exists (literature, not our data):

| Dimension | Levels | Reason |
|---|---|---|
| **Signal** | `fh` = first half-hour (prev close → 10:00); `rod` = rest-of-day (prev close → 15:30 decision close) | Gao’s primary predictor vs Baltussen’s stronger \(r_{ROD}\). Both are knowable at the 15:30 call from SPY bars. |
| **Threshold \(x\)** | 0.5%, 1.0%, 1.5% | IDEA_LIST sketch; CXO says extremes drive the mean effect — a flat “any negative” skip would trade too often for our costs. |
| **VIX gate** | `off`; `vixmed` = previous-session VIX above its expanding median so far | Gao: effect stronger on volatile / crisis / recession days. Point-in-time previous close only (`VIX_DAILY`). |

Complete list (12 = 2 × 3 × 2), every name a design in N:

1. `fh|x050|off`
2. `fh|x100|off`
3. `fh|x150|off`
4. `fh|x050|vixmed`
5. `fh|x100|vixmed`
6. `fh|x150|vixmed`
7. `rod|x050|off`
8. `rod|x100|off`
9. `rod|x150|off`
10. `rod|x050|vixmed`
11. `rod|x100|vixmed`
12. `rod|x150|vixmed`

Rule (all candidates): weight 1 by default; at 15:30 set weight 0 iff signal return \(< -x\) (and VIX gate passes when on); at 15:58 set weight 1. Missing bars / missing VIX: keep (NaN) or stay at 1 — to be fixed in `design.py` with Nicolas if needed.

**Not in this version (park for later variants):** twelfth-half-hour confirmation; recession/news calendars (need registered calendars); continuous regression weights; shorting the last half-hour.

**Uninformed baselines to name in the protocol:** (1) runner shared baselines; (2) **always skip** last half-hour (weight 0 at every 15:30, 1 at 15:58) — information in the signal must beat indiscriminate skipping; (3) buy-and-hold.

**Trial budget:** 12 candidates this version; family I idea I1 **variant 1 of 5**; experiment may use at most three versions in the family; N today starts from the judge v1 baseline (260 with pilot) and will rise by 12 if this grid runs.

---

## 7. Open questions for Nicolas

1. **Sign asymmetry:** Gao Table 10 finds much weaker predictability when \(r_1 < 0\). Our long-only skip only uses the weak side. Accept that as the hypothesis, or should variant 1 instead skip when the signal is *positive* (avoid continuing strength — not the IDEA_LIST sketch)? Recommendation: keep weak-day skip as in IDEA_LIST; record the asymmetry as a limitation.
2. **VIX in variant 1:** include the 6 `vixmed` candidates (12 total) or drop VIX to keep a 6-candidate grid and save N? Recommendation: keep 12; volatile-day concentration is central in Gao.
3. **Signal at 15:30 for `fh`:** confirm first half-hour ends at **10:00** bar close (Gao) using view bars only — no new source.
4. **Cash during the skip:** total-return path credits T-bill on cash (R4b). For ~30 minutes that is tiny; confirm we do **not** need a special intraday cash accrual beyond the engine.
5. **Early closes / missing 15:30:** treat as “no skip” (no call) per runner — acceptable for the protocol?
6. **Uninformed baseline:** is “always skip last half-hour” the right information test, or random skips matched to each candidate’s skip rate (path-dependent; harder to pre-register)?
7. **Selection / folds:** follow template (development quarters, last 4 pooled, ties by name) with **no** rolling model — pure rules. Confirm no train-window candidates.
8. **Family ledger / IDEA_LIST status:** when tests land, mark idea I1 used and add exp14 to family I in section 4 (Nicolas merges protected docs).
9. **Post-2020 decay:** Baltussen ends May 2020; any published post-2020 replication you want cited before preregister, or is CXO 2012–2014 + McLean–Pontiff enough caution?
10. **Step 2 scope:** approve this grid and draft protocol before `config.py` / `design.py` / tests?

---

## 8. Bottom line for step 1

The literature supports a small positive link from early-day (esp. rest-of-day) weakness/strength into the last half-hour, stronger in stress, with a structural hedging story that need not have died by 2020. CXO and Gao’s own cost section say the **per-trade last-half-hour move is small**; our ~$0.03/share round trip is the binding constraint. The proposed 12-candidate grid tests signal definition, threshold rarity, and a VIX stress gate — without reading our SPY/VIX series until a `preregister` protocol is committed.
