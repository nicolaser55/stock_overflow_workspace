# Stock Overflow: stage-1 research plan (ideas, budget ledger, data)

*Written 2026-10-29 by Claude with Nicolas's decisions of the same day. It replaces the draft idea list of
2026-10-29 (`claude/IDEA_LIST_DRAFT_2026-10-29.md`, kept for history). **Nothing in the idea list has been tested on
our data**; "evidence" means what the cited authors report. Use this document when the roadmap reaches step R5
(`docs/AGENTIC_ROADMAP.md`). The agent tooling for that step is proposed separately in
`claude/PROPOSAL_2026-10-29_models_and_setups.md` (decisions pending there).*

**How to resume.** (1) Check that every prerequisite in section 3 is done. (2) Nicolas edits the idea list
(`docs/IDEA_LIST.md`): remove, add or reorder. (3) Collect the data of section 5 for the ideas that stay. (4) The ledger of
section 4 decides which ideas are still allowed; the planner picks among them, most promising first.

**Note (2026-11-04).** Written before the pilot scope (design 6.7): the verdict's N then counted the trial log only,
from the judge v1 freeze on (**since 2026-11-10 it counts the pilot designs again**: trial log and ledger together, 260
at the baseline); "existing experiments" in the family ledger means the nine as rerun at
the freeze, not their pilot versions. **Update (2026-11-10):** section 2 now gives the judge v1 baseline on total
returns (R4b); the earlier price-only numbers (cash at 0%) are kept in section 2.1 and marked as such where sections 6
and 7 quote them. All these numbers are Nicolas's records: the planner gets a numbers-free brief instead (roadmap R5). After the freeze, a few ideas from
this list are run by hand before the agents (roadmap, judge v1 freeze).

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

## 1.1 Decisions taken (Nicolas, 2026-11-17, after the codebase and pipeline review)

Taken before any design has passed the verdict. They are not amended after a result.

1. **Goal.** More total return than buy-and-hold after costs. Lower risk is not the aim (Nicolas already holds SPY
   and similar ETFs long term); the 90% band stays reported only. A long-only, unlevered strategy gains only by being
   in cash on sessions that would have lost, so a realistic edge is a few points a year at most.
2. **The multiple-testing bar stays as it is** (N with the pilot included, V frozen; no counting of "independent"
   designs). What it means: with N = 266, the frozen V and 42 scored quarters, a path needs a quarterly excess Sharpe
   ratio of about 0.58 over buy-and-hold, about 1.2 a year. A single untuned design would need about 0.5 a year on
   this span. Published timing effects, where they hold, are around 0.3-0.5 a year. **A fail on multiple testing
   alone is expected for a real but modest edge; it is not evidence that the edge is absent.** Each result is read by
   the parts that carry information: the return at zero and at standard slippage, the constant-exposure baseline, the
   plain random-timing count (draws at or above the path, of the registered draws) and consistency.
3. **A reported-only distance to the bar** in every report: the path's quarterly excess Sharpe ratio, the bar it was
   compared with, and the plain random-timing count. It changes no verdict and no grade; the grade file keeps its
   no-digits rule. Not built yet (roadmap: the judge pull request before the agents).
4. **A lower tier, "candidate for a small live test"** (decided 2026-11-17, before any result reached it; project doc
   `claude/RULE_2026-11-17_lower_tier.md`). Never called a pass; the full verdict stays the only pass; not part of the
   judge, not in the grades and not shown to agents. Nicolas reads it from `report.md` / `report.json`. A frozen design
   reaches it when all of these hold on its development run:
   (a) every verdict part passes except multiple testing: return strictly above buy-and-hold after standard costs;
   consistency; baselines (strictly above constant exposure and above at least 95 of the 100 registered random-timing
   draws, `random_timing_beaten_count`); look-ahead;
   (b) still strictly above buy-and-hold at $0.02 slippage (`cost_sensitivity_list`) and with cash at the T-bill yield
   minus 0.5% (`cash_rate_sensitivity_dict`);
   (c) the idea is in `docs/IDEA_LIST.md` with a published mechanism and out-of-sample evidence, recorded in the
   protocol before the first run; the version is 1.0 or a `bug-fix` amendment (not `data-dependent`), and "Derived
   from:" is `none`.
   Then: at most **two** such designs go to the holdout in stage 1, in the order they reach the tier (a third waits for
   stage 2); a holdout confirmation (point 5) allows a live test whose amount, length (about 2-3 months) and stop rule
   are written per strategy before it starts. What it means: (a) needs roughly an annual information ratio of 0.5; a
   no-edge design meets the random-timing condition about 5% of the time, so over the remaining experiments one may
   reach the tier by luck, and the holdout confirms a no-edge design about half the time. The tier is a small, bounded
   bet on weak evidence, not evidence of an edge. Checked on 2026-11-17 against every current result: none reaches it
   (exp13 fails consistency and is derived from exp12's results; exp14 is below buy-and-hold after costs).
5. **Holdout rule.** A holdout evaluation (12 months, once per design, run only by Nicolas) **confirms** a design when
   all three hold on the window: (a) the run is valid (the look-ahead check passes, no undeclared source was read);
   (b) its total return after costs (standard slippage and fees, dividends and T-bill interest on both sides) is
   strictly above buy-and-hold's; (c) it is strictly above the constant-exposure baseline's. Random timing,
   consistency and multiple testing are reported, not decisive: one year cannot support them. A design that fails is
   dropped; there is no second evaluation of it, or of a version derived from it after the result. A design with no
   edge beats buy-and-hold in a given year about half the time, so a confirmation means "not contradicted by new
   data"; a failure is the more informative outcome. The holdout report still applies the development verdict, which
   cannot pass on one year (consistency needs 24 decisive windows); its own label is to be built (roadmap).
6. **Other indices confirm; they do not search.** A design that reaches the lower tier or passes is tested frozen,
   without re-tuning, on similar indices (QQQ, IWM and others). No "any stock" support is built until a second symbol
   is actually needed; experiments come first.
7. **End of stage 1:** after **15 experiments** or when the family budget (section 4) is spent, whichever comes first.
   Counted from exp14 (experiment 1 of 15), hand-designed and agent experiments together. Reruns, pre-run fixes and
   amended versions of an experiment do not count as new experiments. If nothing reaches even the lower tier, that is
   the stage-1 result, recorded as a negative result.
8. **Forward data.** Nicolas keeps downloading new data into the quarantine. The development view and the holdout
   window stay frozen (no `refresh_development_view.py`) until a deliberate refresh, so results stay comparable and
   the new months stay untouched by any experiment.
9. **Research practice.**
   - Prefer ideas that trade rarely and stay invested most of the time: costs removed exp14's small gross gain.
   - Rank eligible ideas by expected turnover and by out-of-sample evidence (replications across periods and
     markets), not only by the size of the reported effect.
   - About 3-5 candidates per version (was about 3-15), so the plain random-timing count stays readable.
   - One prediction line in each protocol, written before the first run: the expected direction of the effect and
     the part of the verdict most likely to fail.
   - Two Claude reviews per experiment (brief and protocol; design and tests). The third is replaced by the
     readiness check and a diff showing that only the DRAFT marker changed.

---

## 2. Baseline: the nine experiments under judge v1 (total returns, 2026-11-11)

**Reference baseline from 2026-11-16 (roadmap R4f):** judge commit `e4da312` (PR #47, R4e + R4f), N = 260, V frozen
(0.013139771685914705 over 80 designs). Reran 2026-11-15 in the order exp02, exp03, exp04, exp05, exp06, exp07, exp12,
exp13, exp01, no reset, under the rule `claude/RULE_2026-11-15_R4f_rerun_of_the_nine.md`: all nine EQUIVALENT to the
R4d final runs below. Every total return and failed part in the table is unchanged; all nine fail. Run ids:
`exp02_stop_reentry_20261115155747854506`, `exp03_ath_exit_20261115165249676430`,
`exp04_trend_exit_20261115172619121900`, `exp05_vol_scaled_exposure_20261115174711595785`,
`exp06_capped_regret_reentry_20261115180350301944`, `exp07_warning_lights_exit_20261115183241505900`,
`exp12_vix_fear_reentry_20261115184734993576`, `exp13_e1m1_robustness_20261115191757428426`,
`exp01_minute_entry_20261115193823172094`.

**R4d final baseline (2026-11-13/14), for the record:** judge `12142ab` (PR #42), V read from the frozen reference
`store04_experiments/judge/v_reference.json` (built under STOP just before the reset of 2026-11-13, backup
`reset_20261113_131212`). Rule stated 2026-11-13 before the rerun: each rerun equivalent to its previous run (decisions
and scoring numbers identical; other differences explained by N or V; the V inputs differing only in source, reference
hash and design count), and the reference rebuilt from the new trial log reproducing (80 designs, variance within
1e-12). Result: 9 of 9 equivalent, the reference reproduced exactly (difference 0.0); the deflated Sharpe probability
moved with V and stays far from a pass (largest exp13, 0.081, before 0.071).

**Superseded as the reference by the R4d final baseline (2026-11-13/14):** judge `12142ab` (PR #42), frozen V
reference `judge/v_reference.json` (V 0.013139771685914705 over 80 designs), N = 260 with the pilot, records reset
2026-11-13. Under the rule stated before that rerun, all nine are equivalent to the rows below (differences only through
V), so every total return and failed part in the table below still holds; the results-log rows of 2026-11-13/14 are the
current ones. From 2026-11-14 the verdict label is `pass` / `fail` and the return part passes only strictly above
buy-and-hold (roadmap R4e); none of the nine changes (none is in the 90-100% band).

Judge hash `b7ec40bc1d31be1f`, judge commit `c0924b9` (deployed), the verdict's N = 260 (pilot included, decided
2026-11-10), development records reset on 2026-11-10 with the kill switch set (PR #39). Total returns on both sides:
SPY dividends reinvested and T-bill interest on cash, for the strategy, buy-and-hold and the baselines (R4b).
Results-log rows of 2026-11-11. This rerun supersedes the 2026-11-09/10 one (judge `3b51ca4a3578852a`, N in queue
order, results-log rows PR #36, withdrawn by the reset note): every total return and failed part below is the same in
both; only the multiple-testing part's N changed, and it failed in both.

| Experiment | Family (sec. 4) | Prior-only vs buy-and-hold | Failed parts | Look-ahead |
|---|---|---|---|---|
| exp01_minute_entry | L | +131.61% vs +280.26% | return, consistency, baselines, multiple-testing | pass |
| exp02_stop_reentry | L | +194.57% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp03_ath_exit | X | +173.08% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp04_trend_exit | T | +86.10% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp05_vol_scaled_exposure | V | +196.47% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp06_capped_regret_reentry | T | +196.19% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp07_warning_lights_exit | T | +88.19% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp12_vix_fear_reentry | V | +167.89% vs +256.72% | return, consistency, baselines, multiple-testing | pass |
| exp13_e1m1_robustness | V (part of exp12's idea) | +344.27% vs +256.72% | consistency, multiple-testing | pass |

Notes:
- All nine fail the verdict; eight of nine lose to buy-and-hold on return. exp01's buy-and-hold differs because minute
  mode scores a different span. These returns are not comparable with section 2.1 (price returns, cash at 0%):
  buy-and-hold now also earns the dividends that time in cash misses.
- exp13 beats buy-and-hold on return only because its rule was selected after seeing the data (section 7); the verdict
  fails it on consistency and multiple testing, as on price returns.
- **N:** every run was judged at N = 260 (pilot included). In the superseded 2026-11-09/10 rerun, N grew in queue
  order (exp02 at 18, exp04 at 42); the equivalence check of exp02 and exp04 shows that only the multiple-testing part
  changed between the two (deflated Sharpe probability 0.025 -> 0.0038 for exp02, 0.00016 -> 0.000028 for exp04).
- exp06 was interrupted twice by Windows Update restarts and resumed the same run; its result equals the earlier one
  (roadmap, open item).
- **Deflated-Sharpe check on total returns (2026-11-10):** 10,000 no-skill draws on exp04 and exp02; the centered counts
  are at most 1.20 times the expected count (exp02 at N = 100; 1.04 at N = 260; exp04 at most 0.59). Below the 3x rule,
  so the DSR is kept; but on total returns it is about fair, no longer conservative as on price returns (at most 0.24).
  The counts are small (6 against 5 expected, 2 against 1.9), so these ratios are noisy.

### 2.1 Earlier baseline, price returns (phase C, 2026-10-28/29; withdrawn by the 2026-11-09 resets)

First valid baseline at the time. Judge hash `ad4a601ec218bc09`, judge commit `cc094bd`, run commit `1685b17`, N = 260 designs
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
  2026-10-29). **Done** (PR #31, 2026-11-09).
- **Full rerun of the nine experiments** after R2-R4b (one batch, exp01 included because its returns change too:
  about 3 hours for the eight daily ones plus 11-14 hours for exp01). **Done 2026-11-09/10** (section 2); the family
  ledger of section 4 is unchanged (no experiment was added or dropped).
- **Judge v1 freeze** (added 2026-11-04): R4b plus the deflated-Sharpe diagnostic; then the development records are
  reset (`scripts/reset_records.py`, the count of designs kept) and the nine rerun once, which is the baseline.
  **Done 2026-11-10** apart from the open items in the roadmap's freeze section.
- **A few hand-designed experiments** from this list (decided 2026-11-04), pre-registered and queued by Nicolas and
  Claude under the same rules, to check the queue, the grades and the status files in practice before agents rely on
  them.
- **R5** agent runtime chosen (proposal of 2026-10-29), file formats, planner and coder prompts, a numbers-free brief
  for the planner, and **no general internet for code-running agents** (decided 2026-11-04).

---

## 4. Family budget ledger (decided: existing experiments count)

Assignment by each experiment's primary mechanism (proposed by Claude 2026-10-29; Nicolas may move any). Variants
spent before the budget existed are not refunded or charged; they are already in N.

**A variant is a protocol version (decided by Nicolas on 2026-11-14).** Each idea has at most 5 versions, across all the
experiments filed under it (an experiment itself has at most three per family; a derived experiment such as exp13
spends a version of its source idea). Grid width is limited separately: about 3-5 candidates per version (2026-11-17;
was about 3-15), every candidate a design in N. Every new protocol carries `Family: <letter>, idea <id>, variant <k>
of 5`, linted by the runner for its format only (the budget itself is checked by hand against this table until the
judge pull request before the agents enforces it);
this table is updated in Nicolas's selection pull request when the idea is selected, before the agent starts
(2026-11-18; earlier: in the pull request that brings the tests), and after the run in the records pull request. The nine
experiments below are protocol 1.0 and keep their assignment; they are not relabelled.

| Family | Ideas used | Slots left | Experiments | Eligible new ideas (`docs/IDEA_LIST.md`) |
|---|---|---|---|---|
| **T** Trend / time-series momentum | 3 | **0 (closed)** | exp04 (200-day exit), exp06 (trend or near-high exit + buy-stop re-entry), exp07 (warning lights) | none; T1-T4 parked |
| **V** Volatility and risk state | 2 | 1 | exp05 (realized-volatility scaling); exp12 + exp13 (VIX-based re-entry; exp08, the pre-reset VIX signal gate, belongs to the same idea) | none recommended: V1 deferred 2026-11-18 (post-publication dismissal), V2, V3 weak |
| **L** Learned models | 2 | 1 | exp01 (minute take-profit model), exp02 (trailing stop + model re-entry) | none proposed |
| **X** Anchors and highs | 1 | 2 | exp03 (sell near the all-time high) | X1 |
| **C** Calendar and event windows | 1 | 2 | exp15 (C2 pre-turn-of-month exit; variant 1 of 5; selected 2026-11-18, in preparation) | C3-C5 weak (screen 2026-11-18); C1 deferred 2026-11-17 |
| **I** Intraday | 1 | 2 | exp14 (I1 last-half-hour exit on weak days; variant 1 of 5, 6 candidates; run 2026-11-16: fail, the gain disappears after costs) | I2, I3 |
| **R** Short-term reversal | 0 | 3 | — | R1, R2 |
| **M** Macro and valuation | 0 | 3 | — | M1, M2 (T3 could move here as a macro idea) |

Points to settle when resuming:
- exp12 + exp13 used 2 variants under one idea (two protocol versions in all: exp12 1.0 and the derived exp13 1.0;
  7 candidates). Counted as candidates, as first written on 2026-10-29, it was 7; superseded by the 2026-11-14 rule.
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
Note 2026-11-12: since R4c (merged 2026-11-11) the runner can express I1 and I2: a daily fractional design declares
`INTRADAY_DECISION_TIME_LIST` (e.g. `["15:30"]`) and decides at those times as well (`docs/RUNNER_DESIGN.md`,
"Intraday decision times"). Before R4c neither could be run as written.

---

## 6. The idea list

Moved to its own file on 2026-11-16: **`docs/IDEA_LIST.md`** (v1, agreed by Nicolas). It holds the constraints, the
ideas with their status, data needs and caveats, and the ideas considered and not recommended. The first
hand-designed experiment is **I1** (exp14, family I, idea I1); run 2026-11-16, fail (results log).

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
  +199.04% (price returns) is the same after-the-fact selection; the runner's consistency and multiple-testing parts
  reject it. On total returns (judge v1 baseline, 2026-11-10): +344.27% vs +256.72%, rejected by the same two parts.
- **For the thesis:** exp13 is a worked example of selection bias: a rule chosen because it looked best can beat
  buy-and-hold on return and still be noise. The results log gets a note row saying so.

---

## 8. Open questions for later

- Which 3 of C1-C5; which idea takes the last V slot (V1 recommended); keep or drop I3 (`docs/IDEA_LIST.md`).
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
