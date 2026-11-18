# exp15_pre_tom_exit: Protocol

DRAFT (step 1, not preregistered)

*Version 1.0 (2026-11-18). Experiment name `exp15_pre_tom_exit`. Config: `experiments/exp15_pre_tom_exit/config.py` + `so/config.py`.
Review 1 (Claude, 2026-11-18) applied in step 2; protocol still DRAFT (not preregistered). After the first development
run, any rule change is a new `PROTOCOL_VERSION` of this same experiment (same name, same folder; never a renamed copy),
with every candidate renamed (for example `v1.1|<name>`) and a change-log row labelled `bug-fix` or `data-dependent`
(section 11). The folder name must equal `EXPERIMENT_NAME`.*

Derived from: none.

Family: C, idea C2, variant 1 of 5

(The line above is required and must stand alone on its line: the family letter and idea id of
`docs/STAGE1_RESEARCH_PLAN.md` sections 4 and 6 / `docs/IDEA_LIST.md`, and which variant of that idea this version is. A
variant is a protocol version, at most 5 per idea across experiments, counted in section 4.)

This folder is a runner design (`docs/RUNNER_DESIGN.md`). Replay, selection, baselines and the report live in
`so.runner`. Development is `scripts/run_development.py <this folder>`. Holdout evaluation is
`scripts/holdout_evaluate.py` (Nicolas only). Detail and citations: `RESEARCH_BRIEF.md`.

## 1. Background and research question

**Question.** Can a long-only, unlevered SPY overlay that stays invested by default, exits to cash on the
pre-turn-of-month institutional selling days (Etula, Rinne, Suominen & Vaittinen, *RFS* 2020), and buys back for the
turn-of-month rebound, beat buy-and-hold’s total return after our costs?

**Why this direction only.** A long-only overlay gains only by being in cash on sessions that would have lost. The
classical “in only at −1..+3” sketch (`docs/IDEA_LIST.md` C2) would sit out most of the month and cannot add return
relative to buy-and-hold unless almost all of the 20-year gain sits in those four days. Nicolas selected **out on the
pre-TOM selling window, invested otherwise** (2026-11-18). Mechanism: under T+3, institutions that need cash on the
morning of the last trading day of the month (day 0 = T) must sell by the close of T−4; Etula et al. label T−8..T−4
“selling pressure” and T−3 onward the rebound. Idea V1 was deferred the same day; branch `agent/exp15-vrp-exit` is
the record. See `RESEARCH_BRIEF.md`.

**Identity.** The path beats buy-and-hold only if sessions spent in cash lose more, in total-return terms, than cash
earns (T-bill), by more than round-trip costs.

**Overlap (must state).** Development data 2005–2024 overlaps Etula’s US equity sample (Jul 1995–Dec 2013) on
**2005–2013**. Years **2014–2024** are after Etula. McConnell & Xu end in 2005 (only the first development year
overlaps). Scored validation quarters of this draft are **2015–2024** (section 5): entirely after Etula’s sample end,
and inside the decay samples of Gil (Católica, 2006–2023) and Han, Han & Tian (*FRL* 2025). Only the holdout and any
live test are fully out of sample relative to those decay studies’ end dates.

No SPY or other market series were explored for this draft.

**Prediction (written before the first run):** direction — pre-TOM selling days underperform cash on average so a
calendar exit can help gross; most likely verdict failure — **the return part after standard costs** (classical TOM
has largely faded post-publication / post-2013; settlement eras shift inside our span). Multiple testing remains an
expected fail even for a modest real edge (plan §1.1 point 2). A fail is the expected outcome (`docs/IDEA_LIST.md` C2).

## 2. Success criteria

- **Primary (runner verdict return part):** prior-only path total return **strictly above** buy-and-hold total return
  (`primary_success`). The 90% band with better Sharpe or drawdown is reported only, never a pass.
- **Comparable / secondary:** reported beside the verdict as in `docs/RUNNER_DESIGN.md`.
- **Information test:** the uninformed version of the informed component is **always invested** (buy-and-hold /
  constant exposure at weight 1). The runner’s random-timing baseline (100 seeds) places this path’s cash spells at
  random under the same gap rule — the rate-matched test that the *calendar dates* of the exit matter.
- **Statistical support:** runner multiple-testing and consistency parts (`so/core/evaluation.py`, verdict parts in
  `docs/RUNNER_DESIGN.md`).
- **Minimum detectable effect (expected):** Etula’s US selling-pressure days were mildly negative in 1995–2013; recent
  classical-TOM decay studies find little left after ~2013–2014. After our costs, expect a **small or negative** net
  edge. A fail after costs is an informative result.

The runner’s shared verdict (return / consistency / baselines / look-ahead / multiple testing) is `pass` or `fail`.
It does not replace this protocol’s stopping rule.

Lower tier (“candidate for a small live test”, plan §1.1 point 4): every verdict part except multiple testing; still
strictly above buy-and-hold at $0.02 slippage and with cash at T-bill minus 0.5%; Derived from: none; version 1.0 or
bug-fix. Never called a pass. C2’s post-2013 decay evidence weakens point (c)’s spirit even if the paperwork passes.

## 3. Data

- **Instrument:** SPY via point-in-time `SPY_1MIN` only. `decide` reads the decision session date from the view; no TSDAY.
- **Period:** development view through the embargo before the registered holdout (boundary from `so.core.holdout`,
  never hard-coded here). Scored candidate periods are the validation quarters of section 5 (2015-2024 under the
  proposed fold length).
- **Adjustments / cleaning:** shared pipeline only; no new cleaning.
- **No new data source.** The exchange calendar is **rule-coded inside the design** (`calendar_rules.py`; scheduled
  NYSE holidays published in advance); not a registered market-data source. See `RESEARCH_BRIEF.md` section 10.

## 3.1 Data sources

| Source | Convention | Availability | Revision | Role |
|---|---|---|---|---|
| `SPY_1MIN` | bar start | label + 1 minute | not revised (stored IBKR bars) | feature (session date on the view; prices unused by decide) |

`DATA_SOURCE_LIST` on `design.py` must match this table (step 2). `SPY_DIVIDENDS` and `TBILL_3M` are applied by the
runner's total-return layer; `decide` does not read them. `TSDAY` is omitted: the calendar rule uses only the
decision date, and the fractional engine runs with `SPY_1MIN` alone (same pattern as exp14).

## 4. Rules / target / features / model

**Engine:** `fractional`, target weight in **{0, 1}** (same pattern as exp05). `DEAD_BAND = 0.0`.
`INITIAL_WEIGHT = 1.0`. **No fitted model.** Implemented in `Design.decide` in `design.py`. A scheduled 0/1 weight is
a fractional target, so the runner's random-timing baseline relocates cash spells uniformly while keeping their
lengths (`so/runner/baselines.py`) — the information test that the calendar dates matter.

**Day numbering (Etula et al., fixed from the literature, never from our data):**
- Day **0 = T** = last **design-calendar** session of the calendar month.
- Negative indices count design-calendar days before T (T-1, T-2, ...).
- Positive indices count design-calendar days after T into the next month (T+1, ...).

**Cash window (candidate parameters):** inclusive design-calendar indices relative to T: Etula's selling pressure
**T-8..T-4** (`w84`) or narrower core **T-5..T-4** (`w54`). Settlement handling is a second dimension (`fixed` vs
`shift`); see section 5.1. Review 1: keep T-5..T-4 as the core; grid of four as proposed. Friday-T amplification and
Graziani stay parked / related-only.

**Settlement eras (SEC; era of a month = era in force on that month's day T):**
- **T+3:** day T on or before **2017-09-04**.
- **T+2:** day T from **2017-09-05** through **2024-05-27**.
- **T+1:** day T on or after **2024-05-28**.

Under `shift`, the inclusive window moves **one trading day later** per one-day shortening of settlement
(`w84|shift`: T-8..T-4 / T-7..T-3 / T-6..T-2; `w54|shift`: T-5..T-4 / T-4..T-3 / T-3..T-2). Under `fixed`, the
base indices never move. Review 1 confirmed this mapping.

**Decision timing (Review 1):** the decision at the **15:58** bar of session s sets the weight held from the
**15:59** fill of s to the **15:59** fill of the next session. So **weight(s) = 0** exactly when the **next**
design-calendar session after s lies in the candidate's cash window for that next session's month; otherwise
**weight(s) = 1**. The decision may read **only** the date of the decision bar (no prices or volumes). With these
windows the cash spell never crosses past T into the next month.

**Calendar (Review 1: option a):** `calendar_rules.py` in this folder — scheduled NYSE holidays only (New Year's
Day with Sunday to Monday and Saturday not observed; MLK Day; Washington's Birthday; Good Friday from Easter; Memorial
Day; Juneteenth from 2022 with weekend observance; Independence Day; Labor Day; Thanksgiving; Christmas with weekend
observance). **Unscheduled closures** (including 2007-01-02, 2012-10-29, 2012-10-30, 2018-12-05, and any other in the
span) **stay in the day count** as design-calendar sessions. When a planned exit or re-entry falls on a day the
market is closed, the position is unchanged until the **next real session's 15:59** fill. This is a **deliberate
no-look-ahead choice** with a small mechanical cost in those months. If the session before the cash window is closed,
the prior live decision keeps weight 1 through the first window day (late exit by one session). If the last window
day is closed, weight 0 is held through the next live session (late re-entry by one session). No
`pandas_market_calendars` and no `so.core.datetime_utils` in the design.

**Sources:** `SPY_1MIN` only. Early close: still one 15:58-mapped decision when the runner maps it.

## 5. Walk-forward and selection

Candidate periods are the development validation quarters (`PERIOD_RULE` → `get_development_fold_pdf`), extended
through the holdout by the runner. Embargo = `so.config.LABEL_HORIZON_SESSIONS` (`EMBARGO_TRADING_DAYS`). There is
no rolling model and no training-window candidate.

**Fold length.** `FOLD_TRAIN_WINDOW_YEARS = 10` (Review 1: keep, as every other run). Validation quarters are
**2015–2024**: after Etula’s sample end; same scored-span convention as exp14 / frozen V. This **gives up
2008–2009** in the scored windows.

**Candidates:** the 4 names in section 5.1. Selection pools the last 4 completed quarters. Tie order: candidate name
ascending. The first period (no completed quarter) takes the first listed candidate (`w84|fixed`).

Period score = period return − buy-and-hold (continuous slice). Prior-only path as usual.

## 5.1 Complete candidate list (trial budget for this version)

| # | Candidate | Window (vs T) | Settlement |
|---|---|---|---|
| 1 | `w84\|fixed` | T−8..T−4 (Etula selling pressure) | fixed in every era |
| 2 | `w84\|shift` | same width; shifted +1 trading day per shorter settlement step | T+3: −8..−4; T+2: −7..−3; T+1: −6..−2 |
| 3 | `w54\|fixed` | T−5..T−4 (narrower core near peak selling) | fixed |
| 4 | `w54\|shift` | width 2; shifted as above | T+3: −5..−4; T+2: −4..−3; T+1: −3..−2 |

**Trial budget:** 4 candidates (= 4 designs in N) in this version. At most two further versions of this experiment.
Idea C2 has variants 2–5 still available. Family C still has other idea slots after this idea uses one (section 4 of
the research plan).

No retraining section: there is no fitted model. Template §5.1 retraining bullets do not apply; this heading holds the
candidate table instead (same pattern as exp14 / the deferred V1 draft).

## 6. Baselines

Runner shared baselines, same engine, same costs: buy-and-hold; daily-rebalanced constant exposure at the path’s mean
weight; 100-seed random timing.

**Uninformed version of the informed component:** always invested (weight 1) — no pre-TOM calendar exits. Random
timing tests whether the *dates* of cash spells matter beyond their rate.

## 7. Stopping rules

- Signal / exploration: none that peek at development results before preregister. The brief used papers, regulator
  pages and web search; no market series.
- Walk-forward: apply prior-only path vs buy-and-hold and the runner baselines.
- Apply this protocol as written. The runner verdict is reported beside it.
- A fail after costs is a result. Do not widen the grid, retune window edges, or drop a settlement rule after seeing
  outcomes. That would be a new data-dependent version with renamed candidates.

## 7.1 Trial budget

See section 5.1. Variants of idea C2 already spent: **0** (this is variant 1 of 5). Versions this experiment may still
use after 1.0: **2** (family cap three versions total). N rises by 4 if this grid runs.

## 8. Reporting

After-the-fact candidates, prior-only path with baselines, time in the market (and switch counts), MDE context from
the brief, success criteria, `report.json` / `report.md` / `manifest.json`. Candidate-period trial rows go to the
shared trial log as scored. Agents read grades and status only under `store04_experiments/visible/`.

## 9. Discipline, implementation, limitations

- `design.py` must pass the runner preflight: no `so.runner`, `so.core.point_in_time`, `so.core.holdout`, file I/O, or
  `.base`. State lives on the design object between `decide` calls. A value whose `available_ts` is after the decision
  is not in the view.
- **Calendar look-ahead:** scheduled holidays only; no `pandas_market_calendars` day counts in `decide`.
- **Settlement eras** are fixed from the SEC, not tuned on returns.
- Classical TOM and pre-TOM edges may have **decayed** after publication / after 2013 (Gil 2025; Han et al. 2025;
  international Aalto thesis 2014–2022). Etula’s mechanism sample ends 2013; scored years are after that.
- Overlap with published samples (section 1); scored windows give up 2008–2009.
- Step 2: config, design, calendar_rules and tests exist; protocol remains DRAFT until the `preregister` commit.

## 10. Holdout evaluation

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

The development boundary is not a hard-coded date. It is `so.core.holdout.get_development_end_date(embargo)`: the session
an embargo before the active holdout start. Validation folds come from `so.core.schedule.get_development_fold_pdf`
(validation windows only). Do not read the holdout for exploration, validation or any decision.

A holdout evaluation confirms the design when the run is valid (look-ahead check passed, no undeclared source),
its total return after costs is strictly above buy-and-hold's, and strictly above the constant-exposure baseline's.
Random timing, consistency and multiple testing are reported, not decisive. A design that fails is dropped
(decided 2026-11-17, `docs/STAGE1_RESEARCH_PLAN.md` section 1.1).

Only Nicolas runs the evaluation (`scripts/holdout_evaluate.py`), once per frozen design per window. Agents never run
that script or `scripts/holdout_window.py`, and never set `SO_HOLDOUT_PATH` or `SO_HOLDOUT_EVALUATION_TOKEN`.

`design.py` exposes `PERIOD_RULE`, `CANDIDATE_LIST`, `get_candidate_design`, `SELECTION_RULE`, `DATA_SOURCE_LIST`,
`ENGINE_NAME` and `decide(view)` (see `experiments/README.md`). The runner scores every candidate on every period
(continuous-slice return minus buy-and-hold), selects for period f from periods before f only, and builds one
continuous path from the recorded decisions. Look-ahead is truncation and perturbation at three sampled cuts. A
failure fails the verdict.

## 11. Change log
| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-18 | DRAFT step 1: research brief and draft protocol (C2 pre-TOM exit). Not preregistered. |
| 1.0 | 2026-11-18 | DRAFT step 2: Review 1 applied (calendar a, shift mapping, fractional 0/1, decision timing, folds, cost note); config, design, calendar_rules, tests. Still not preregistered. |

An amended version adds a row whose first cell is its `PROTOCOL_VERSION` and whose text holds exactly one label:
`bug-fix` (the code did not do what this protocol says; found without looking at results) or `data-dependent`
(anything results prompted; when in doubt). A crash before the first trial row is not a version: write "pre-run fix:
<what>" in the 1.0 row and commit again with `preregister`.
