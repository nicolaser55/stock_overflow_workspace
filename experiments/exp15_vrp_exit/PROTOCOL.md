# exp15_vrp_exit: Protocol

DRAFT (step 1, not preregistered)

*Version 1.0 (2026-11-18). Experiment name `exp15_vrp_exit`. Config: `experiments/exp15_vrp_exit/config.py` + `so/config.py`.
Agreed draft for Claude / Nicolas review before step 2 (config, design, tests). After the first development
run, any rule change is a new `PROTOCOL_VERSION` of this same experiment (same name, same folder; never a renamed copy),
with every candidate renamed (for example `v1.1|<name>`) and a change-log row labelled `bug-fix` or `data-dependent`
(section 11). The folder name must equal `EXPERIMENT_NAME`.*

Derived from: none.

Family: V, idea V1, variant 1 of 5

(The line above is required and must stand alone on its line: the family letter and idea id of
`docs/STAGE1_RESEARCH_PLAN.md` sections 4 and 6 / `docs/IDEA_LIST.md`, and which variant of that idea this version is. A
variant is a protocol version, at most 5 per idea across experiments, counted in section 4.)

This folder is a runner design (`docs/RUNNER_DESIGN.md`). Replay, selection, baselines and the report live in
`so.runner`. Development is `scripts/run_development.py <this folder>`. Holdout evaluation is
`scripts/holdout_evaluate.py` (Nicolas only). Detail and citations: `RESEARCH_BRIEF.md`.

## 1. Background and research question

**Question.** Can a long-only, unlevered SPY overlay that stays invested by default, exits to cash when the
variance risk premium (implied variance from the previous VIX close minus realized variance from the last 22
completed sessions) is at or below its point-in-time q-quantile of history so far, and buys back when the premium
rises above that quantile, beat buy-and-hold’s total return after our costs?

**Why.** Bollerslev, Tauchen & Zhou (*RFS* 2009) argue that a high (low) variance risk premium forecasts high (low)
aggregate returns, strongest at the quarterly horizon. Idea V1 (`docs/IDEA_LIST.md`) was selected by Nicolas on
2026-11-17 for the last family-V slot. Post-publication evidence for the *plain* premium is weak (Pyun; Goyal, Welch
& Zafirov *RFS* 2024 dismiss `vrp` through 2021). See `RESEARCH_BRIEF.md`.

**Identity.** The path beats buy-and-hold only if sessions spent in cash lose more, in total-return terms, than cash
earns (T-bill), by more than round-trip costs.

**Overlap (must state).** Development data 2005–2024 overlaps BTZ through 2007, BMXZ 2014 through 2011, Pyun through
2016, and Goyal–Welch–Zafirov through 2021. Scored validation quarters of this draft are **2015–2024** (section 5),
after BTZ’s sample end and still inside GWZ’s evaluation window through 2021. Only the holdout and any live test are
fully out of sample relative to GWZ.

No SPY, VIX or other market series were explored for this draft.

**Prediction (written before the first run):** direction — low VRP → underperformance of SPY vs cash over the following
weeks to a quarter, so a rare cash spell can help gross; most likely verdict failure — **the return part after standard
costs** (and therefore also the lower tier’s $0.02 slippage / T-bill−0.5% checks), consistent with GWZ’s poor investment
performance of `vrp`. Multiple testing remains an expected fail even for a modest real edge (plan §1.1 point 2).

## 2. Success criteria

- **Primary (runner verdict return part):** prior-only path total return **strictly above** buy-and-hold total return
  (`primary_success`). The 90% band with better Sharpe or drawdown is reported only, never a pass.
- **Comparable / secondary:** reported beside the verdict as in `docs/RUNNER_DESIGN.md`.
- **Information test:** the uninformed version of the informed component is **always invested** (buy-and-hold / constant
  exposure at weight 1). The runner’s random-timing baseline (100 seeds) places this path’s cash spells at random under
  the same gap rule — the rate-matched test that the *timing* of low-VRP exits matters.
- **Statistical support:** runner multiple-testing and consistency parts (`so/core/evaluation.py`, verdict parts in
  `docs/RUNNER_DESIGN.md`).
- **Minimum detectable effect (expected):** published quarterly adj. \(R^2\) for VRP was about 6.8% in 1990–2007 (BTZ);
  post-2021 evaluations dismiss the predictor. After our costs, expect a **small or negative** net edge. A fail after
  costs is an informative result.

The runner’s shared verdict (return / consistency / baselines / look-ahead / multiple testing) is `pass` or `fail`.
It does not replace this protocol’s stopping rule.

Lower tier (“candidate for a small live test”, plan §1.1 point 4): every verdict part except multiple testing; still
strictly above buy-and-hold at $0.02 slippage and with cash at T-bill minus 0.5%; Derived from: none; version 1.0 or
bug-fix. Never called a pass.

## 3. Data

- **Instrument:** SPY via point-in-time `SPY_1MIN`; previous-session VIX via `VIX_DAILY`.
- **Period:** development view through the embargo before the registered holdout (boundary from `so.core.holdout`,
  never hard-coded here). Scored candidate periods are the validation quarters of section 5 (2015–2024 under the
  proposed fold length).
- **Adjustments / cleaning:** shared pipeline only; no new cleaning.
- **No new data source.** VIX files in `store01_rawzone/ibkr_vix_family/` are already approved read-only sources.

## 3.1 Data sources

| Source | Convention | Availability | Revision | Role |
|---|---|---|---|---|
| `SPY_1MIN` | bar start | label + 1 minute | not revised (stored IBKR bars) | feature (realized variance from bars in the view) |
| `VIX_DAILY` | midnight date label | that date at 16:15 New York | not revised | feature (previous session’s close → implied variance; same-session close not used at 15:58) |
| `TSDAY` | end of decision bar | end of decision bar | not revised | feature (session row / RuleDesign history scaffolding) |

`DATA_SOURCE_LIST` on `design.py` must match this table (step 2). `SPY_DIVIDENDS` and `TBILL_3M` are applied by the
runner’s total-return layer; `decide` does not read them.

## 4. Rules / target / features / model

**Engine:** `trailing_stop` without a stop (`RuleDesign`). `DEAD_BAND` unused for flatten/re-entry flags.
`INITIAL_WEIGHT = 1.0`. **No fitted model.** State between calls lives on the `Design` object (candidate, expanding
VRP history, warm-up count). Implemented in step 2 in `Design.decide` / RuleDesign subclass methods in `design.py`
(template placeholders until then).

**Features at the 15:58 decision, only from the view:**

- `vix_prev` = previous session’s `VIX_DAILY` close, at most the shared stale-max sessions old (exp12 /
  `VixPrevHistory` pattern). Missing or stale → no exit, no re-entry (keep).
- \(IV = (vix\_prev / 100)^2\) (annualized variance units; matched to RV scaling in step 2).
- \(RV\) = sum of squared log returns over the last **22 completed sessions** (today excluded), sampling either
  **5-minute** closes (`rv5m`) or **1-minute** closes (`rv1m`) from `SPY_1MIN` bars in the view. Rescale to the same
  units as \(IV\).
- \(VRP = IV - RV\). Append to history **after** computing today’s quantile from prior values only.
- Expanding empirical **q**-quantile of prior VRP values. Warm-up: fewer than **252** prior VRP points → never exit.

**Exit (flatten):** invested and warm-up done and \(VRP \le\) current expanding q-quantile.

**Re-entry:** in cash and \(VRP\) **strictly above** that same expanding q-quantile (recomputed each day from history
before today). No minimum time out.

**Forced buy-back:** after **60** cash decisions (`MAX_CASH_SESSIONS`), buy back regardless of VRP (crash-miss cap).

**Fills / costs:** 15:59 open; `ENTRY_SLIPPAGE_PER_SHARE`, `MARKET_EXIT_SLIPPAGE_PER_SHARE`, IBKR fees in `so.config`.

**Early close / missing bars:** see `RESEARCH_BRIEF.md` §9; missing inputs → keep.

## 5. Walk-forward and selection

Candidate periods are the development validation quarters (`PERIOD_RULE` → `get_development_fold_pdf`), extended
through the holdout by the runner. Embargo = `so.config.LABEL_HORIZON_SESSIONS` (`EMBARGO_TRADING_DAYS`). There is
no rolling model and no training-window candidate.

**Fold length.** `FOLD_TRAIN_WINDOW_YEARS = 10` (step 2 will set this in `config.py`; template still shows 1 until
then). Validation quarters are then **2015–2024**: after BTZ’s sample end; still overlapping GWZ through 2021. This
**gives up 2008–2009** in the scored windows (open review question).

**Candidates:** the 4 names in section 5.1. Selection pools the last 4 completed quarters. Tie order: candidate name
ascending. The first period (no completed quarter) takes the first listed candidate (`q05|rv5m`).

Period score = period return − buy-and-hold (continuous slice). Prior-only path as usual.

## 5.1 Complete candidate list (trial budget for this version)

| # | Candidate | q | RV sampling |
|---|---|---|---|
| 1 | `q05\|rv5m` | 5% | 5-minute |
| 2 | `q10\|rv5m` | 10% | 5-minute |
| 3 | `q20\|rv5m` | 20% | 5-minute |
| 4 | `q10\|rv1m` | 10% | 1-minute |

**Trial budget:** 4 candidates (= 4 designs in N) in this version. At most two further versions of this experiment.
Idea V1 has variants 2–5 still available. Family V closes once this experiment runs (section 4 of the research plan).

No retraining section: there is no fitted model. Template §5.1 retraining bullets do not apply; this heading holds the
candidate table instead (same pattern as exp14).

## 6. Baselines

Runner shared baselines, same engine, same costs: buy-and-hold; daily-rebalanced constant exposure at the path’s mean
weight; 100-seed random timing.

**Uninformed version of the informed component:** always invested (weight 1) — no VRP quantile exits. Random timing
tests whether the *dates* of cash spells matter beyond their rate.

## 7. Stopping rules

- Signal / exploration: none that peek at development results before preregister. The brief used papers and one web
  search; no market series.
- Walk-forward: apply prior-only path vs buy-and-hold and the runner baselines.
- Apply this protocol as written. The runner verdict is reported beside it.
- A fail after costs is a result. Do not widen the grid, add hysteresis, or drop a quantile after seeing outcomes.
  That would be a new data-dependent version with renamed candidates.

## 7.1 Trial budget

See section 5.1. Variants of idea V1 already spent: **0** (this is variant 1 of 5). Versions this experiment may still
use after 1.0: **2** (family cap three versions total). N rises by 4 if this grid runs.

## 8. Reporting

After-the-fact candidates, prior-only path with baselines, time in the market (and switch counts), MDE context from
the brief, success criteria, `report.json` / `report.md` / `manifest.json`. Candidate-period trial rows go to the
shared trial log as scored. Agents read grades and status only under `store04_experiments/visible/`.

## 9. Discipline, implementation, limitations

- `design.py` must pass the runner preflight: no `so.runner`, `so.core.point_in_time`, `so.core.holdout`, file I/O, or
  `.base`. State lives on the design object between `decide` calls. A value whose `available_ts` is after the decision
  is not in the view.
- **Same-session VIX is not used** (16:15 clock vs 15:58 decision).
- **Crash → negative VRP → rebound miss** is a named literature risk; mitigation is the 60-session forced buy-back
  only, not a data-tuned delay.
- Post-publication dismissal of plain `vrp` (GWZ 2024); plain OOS weakness (Pyun).
- Overlap with published samples (section 1); scored windows give up 2008–2009.
- Step 1: `design.py` / full `config.py` constants are still placeholders until step 2 after review.

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

## 11. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-18 | DRAFT step 1: research brief and draft protocol for idea V1 (variance risk premium exit). Four candidates (`q05\|rv5m`, `q10\|rv5m`, `q20\|rv5m`, `q10\|rv1m`). Config name only; design still template. Not preregistered. |

An amended version adds a row whose first cell is its `PROTOCOL_VERSION` and whose text holds exactly one label:
`bug-fix` (the code did not do what this protocol says; found without looking at results) or `data-dependent`
(anything results prompted; when in doubt). A crash before the first trial row is not a version: write "pre-run fix:
<what>" in the 1.0 row and commit again with `preregister`.
