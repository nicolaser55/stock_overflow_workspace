# exp14_last_half_hour_exit: Protocol

*Version 1.0 (2026-11-16). Experiment name `exp14_last_half_hour_exit`. Config:
`experiments/exp14_last_half_hour_exit/config.py`. Design: `design.py`. Review decisions of 2026-11-16
are applied (section 11). After the first development run, any rule change is a new
`PROTOCOL_VERSION` of this same experiment (same name, same folder; never a renamed copy), with
every candidate renamed (for example `v1.1|<name>`) and a change-log row labelled `bug-fix` or
`data-dependent`. The folder name must equal `EXPERIMENT_NAME`.*

Derived from: none

Family: I, idea I1, variant 1 of 5

(The line above is required and must stand alone on its line: the family letter and idea id of
`docs/STAGE1_RESEARCH_PLAN.md` sections 4 and 6 / `docs/IDEA_LIST.md`, and which variant of that idea
this version is. A variant is a protocol version, at most 5 per idea across experiments.)

This folder is a runner design (`docs/RUNNER_DESIGN.md`). Replay, selection, baselines and the
report live in `so.runner`. Development is `scripts/run_development.py <this folder>`. Holdout
evaluation is `scripts/holdout_evaluate.py` (Nicolas only).

## 1. Background and research question

**Question.** Can a long-only, unlevered SPY overlay that sells into cash before the last half-hour
on weak days, and buys back at the 15:58 decision, beat buy-and-hold’s total return after our costs?

**Why the weak side.** Baltussen, Da, Lammers & Martens (*JFE* 2021) tie last-half-hour continuation
to leveraged-ETF rebalancing and to option dealers who are short gamma: on a down day those hedgers
sell into the decline, which extends it into the close. That is why the overlay steps aside when the
day is already down by more than \(x\), and not when the day is up. Gao, Han, Li & Zhou (*JFE* 2018)
Table 10 is a limitation of that choice: predictability is weaker when the first half-hour is
negative (joint \(R^2\) 0.9%) than when it is positive (joint \(R^2\) 4.5%). See `RESEARCH_BRIEF.md`.

**Identity.** The strategy beats buy-and-hold only if the skipped minutes lose more, in total-return
terms, than cash earns, by more than the round trip. Time out of the market is the 15:31 open
through the 15:59 open, and only on days the signal clears the threshold.

**What the skip does not cover.** The fill of the 15:30 decision is the 15:31 open. The fill of the
15:58 decision is the 15:59 open. The 15:59 bar and the close stay held. Gao’s last half-hour is
15:30–16:00 and includes that last minute. Ours does not.

**Overlap (must state).** Development data 2005–2024 overlaps Gao 1993–2013 on **2005–2013** and
Baltussen 1974–May 2020 on **2005–May 2020**. Those windows are partly replications. The scored
validation quarters of this version are 2015–2024 (section 5), which is after Gao’s sample end and
still overlaps Baltussen through May 2020. Only the holdout and the live test are fully out of sample.
This fold choice **gives up 2008**, where Gao finds the effect strongest.

No SPY, VIX or other market series were explored for this draft.

## 2. Success criteria

- **Primary (runner verdict return part):** prior-only path total return **strictly above** buy-and-hold
  total return (`primary_success`). The 90% band with better Sharpe or drawdown is reported only,
  never a pass.
- **Comparable / secondary:** reported beside the verdict as in `docs/RUNNER_DESIGN.md`.
- **Information test:** the runner’s intraday-aware random-timing baseline (`docs/RUNNER_DESIGN.md`,
  R4c). It keeps each non-base spell’s time of day, so a cash spell from the 15:30 call to the 15:59
  fill is placed at random on other sessions at that same time of day. That is the rate-matched test
  of the signal. There is no always-skip baseline.
- **Statistical support:** runner multiple-testing and consistency parts (`so/core/evaluation.py`,
  verdict parts in `docs/RUNNER_DESIGN.md`).
- **Minimum detectable effect (expected):** papers’ timed last-half-hour edges are a few percent
  annualized when trading **every** day long/short; our selective long-only skip plus about $0.03/share
  round trip implies a **small** edge after costs. A fail after costs is an informative result.

The runner’s shared verdict (return / consistency / baselines / look-ahead / multiple testing) is
`pass` or `fail`. It does not replace this protocol’s stopping rule.

## 3. Data

- **Instrument:** SPY 1-minute IBKR bars via the point-in-time view. The design reads no other source.
- **Period:** development view through the embargo before the registered holdout (boundary from
  `so.core.holdout`, never hard-coded here). Scored candidate periods are the validation quarters of
  section 5 (2015–2024).
- **Adjustments / cleaning:** shared pipeline only; no new cleaning.
- **No new data source.** No VIX series in this version.

### 3.1 Data sources

| Source | Convention | Availability | Revision | Role |
|---|---|---|---|---|
| `SPY_1MIN` | bar start | label + 1 minute | not revised (stored IBKR bars) | feature (signal returns from bars in the view) |

`DATA_SOURCE_LIST` on `design.py` is `["SPY_1MIN"]` only. `SPY_DIVIDENDS` and `TBILL_3M` are applied
by the runner’s total-return layer. `decide` does not read them. There is no special intraday cash
accrual: interest is the runner’s credit on cash held at the previous close.

## 4. Rules / target / features / model

**Engine:** `fractional`. `INTRADAY_DECISION_TIME_LIST = ["15:30"]` on the module and on `Design`.
`DEAD_BAND = 0.0`. `INITIAL_WEIGHT = 1.0`. **No model.** State between calls lives on the `Design`
object (the candidate, and the log of calls). Implemented in `Design.decide` and
`get_signal_return_float` in `design.py`.

**Prices, from bars in the view, at or before `view.decision_bar_idx`:**

- Previous close = close of the previous session’s last bar.
- `fh` = that close → close of the current session’s **09:59** bar (10:00).
- `rod` = that close → close of the current session’s **15:30** bar.
- Signal return = end / previous close − 1.
- Skip only when the signal is **strictly below** \(-x\). A return equal to \(-x\) does not skip.
  Float division can land a hair below an exact ratio; equality uses an absolute tolerance of
  `SIGNAL_EQUAL_ABS_TOL` (1e-10), far below one tick.

**At 15:30** (`view.intraday_time_str == "15:30"`):

- Weight **0** if the signal is strictly below \(-x\).
- Weight **1** if the signal is finite and not strictly below \(-x\).
- **NaN (keep)** if the previous close is missing, or the exact end bar is missing, or its close is
  not a positive finite price. The bar before a missing 09:59 or 15:30 is not used.

**At 15:58** (`intraday_time_str is None`): weight **1**.

**Early close:** the runner does not map 15:30, so it makes no intraday call and there is no skip.
The daily call still sets weight 1.

**Fills:** next bar open after each decision (15:31 after 15:30; 15:59 after 15:58). Costs:
`ENTRY_SLIPPAGE_PER_SHARE`, `MARKET_EXIT_SLIPPAGE_PER_SHARE`, IBKR fee schedule in `so.config`.

## 5. Walk-forward and selection

Candidate periods are the development validation quarters (`PERIOD_RULE` →
`get_development_fold_pdf`), extended through the holdout by the runner. Embargo =
`so.config.LABEL_HORIZON_SESSIONS` (`EMBARGO_TRADING_DAYS`). There is no rolling model and no
training-window candidate.

**Fold length.** `FOLD_TRAIN_WINDOW_YEARS = 10`. That is the template’s name for the fold-schedule
training length. exp03 and exp04 store the same 10 years as `FIXED_TRAIN_WINDOW_YEARS`. With that
length, validation quarters are **2015–2024**: after Gao’s sample end (31 Dec 2013), and the same
span the frozen V was built on (`docs/RUNNER_DESIGN.md`, “The frozen V”). **This gives up 2008**,
where Gao finds the effect strongest (Dec 2007–Jun 2009: \(r_1\) \(R^2\) 4.1%, joint 6.9%).

**Candidates:** the 6 names in section 5.1. Selection pools the last 4 completed quarters. Tie order:
candidate name ascending. The first period (no completed quarter) takes the first listed candidate
(`fh|x050`).

Period score = period return − buy-and-hold (continuous slice). Prior-only path as usual.

### 5.1 Complete candidate list (trial budget for this version)

| # | Candidate | Signal | \(x\) | End price |
|---|---|---|---|---|
| 1 | `fh|x050` | first half-hour | 0.5% | close of the 09:59 bar |
| 2 | `fh|x100` | first half-hour | 1.0% | close of the 09:59 bar |
| 3 | `fh|x150` | first half-hour | 1.5% | close of the 09:59 bar |
| 4 | `rod|x050` | rest-of-day | 0.5% | close of the 15:30 bar |
| 5 | `rod|x100` | rest-of-day | 1.0% | close of the 15:30 bar |
| 6 | `rod|x150` | rest-of-day | 1.5% | close of the 15:30 bar |

**Trial budget:** 6 candidates (= 6 designs in N) in this version. At most two further versions of
this experiment. Idea I1 has variants 2–5 still available. Family I still has two other idea slots
(I2, I3) after this idea is used.

No retraining section: there is no fitted model.

## 6. Baselines

Runner shared baselines, same engine, same costs: buy-and-hold; daily-rebalanced constant exposure at
the path’s mean weight (dead band 0.05, bar-weighted because the weight changes inside the day);
100-seed random timing.

**Information test (R4c).** Random timing is intraday-aware: spells of non-base weight keep their
time of day and are placed at random under the same gap rule. A 15:30 sell / 15:59 buy-back is
compared with the same intraday window on randomly chosen sessions. That is the rate-matched test of
the threshold and of the choice between `fh` and `rod`. There is no always-skip path.

## 7. Stopping rules

- Signal / exploration: none that peek at development results before preregister. The brief used
  papers and one web search (section 7 of `RESEARCH_BRIEF.md`); no market series.
- Walk-forward: apply prior-only path vs buy-and-hold and the runner baselines.
- Apply this protocol as written. The runner verdict is reported beside it.
- A fail after costs is a result. Do not widen the grid, add a VIX gate, or drop a threshold after
  seeing outcomes. That would be a new data-dependent version with renamed candidates.

### 7.1 Trial budget

See section 5.1. Variants of idea I1 already spent: **0** (this is variant 1 of 5). Versions this
experiment may still use after 1.0: **2** (family cap three versions total).

## 8. Reporting

After-the-fact candidates, prior-only path with baselines, time in the market (and skip counts), MDE
context from the brief, success criteria, `report.json` / `report.md` / `manifest.json`. Candidate-period
trial rows go to the shared trial log as scored. Agents read grades and status only under
`store04_experiments/visible/`.

## 9. Discipline, implementation, limitations

- `design.py` passes the runner preflight: no `so.runner`, `so.core.point_in_time`, `so.core.holdout`,
  file I/O, or `.base`. State lives on the design object between `decide` calls.
- Fixed per-share slippage on intraday fills may understate fast markets (runner limit note).
- Gao’s predictability is weaker when the first half-hour is negative (Table 10). This overlay only
  skips on the weak side.
- The cash spell stops at the 15:59 open, so the last minute and the close stay held, unlike Gao’s
  15:30–16:00 window.
- Overlap with published samples, and the choice to leave 2008 out of the validation quarters
  (sections 1 and 5).
- CXO: extreme-decile last-half-hour moves may be smaller than frictions.
- Post-2020: no SPY replication of Gao through 2024 was found in the one search. 0DTE growth since
  2022 does not, on Dim, Eraker & Vilkov or on the 2023 Cboe note, imply a larger short-gamma
  extension into the close; dealer gamma in those accounts is often positive, which damps moves.
  Detail in `RESEARCH_BRIEF.md` section 7.
- Early closes: no 15:30 call, so no skip that session.
- No special intraday cash accrual.

## 10. Holdout evaluation

Frozen prior-only path from development start through the holdout; same code, same 15:30 / 15:58
decisions and fills, same costs. Only Nicolas runs `scripts/holdout_evaluate.py`. Agents never set
holdout env vars or read the quarantine.

## 11. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-16 | Draft from the research brief, then the review: VIX gate dropped (6 candidates, `SPY_1MIN` only); always-skip baseline removed in favour of the R4c random-timing test; `FOLD_TRAIN_WINDOW_YEARS` 10 so validation quarters are 2015–2024 (gives up 2008); prices are the previous session’s last close, the 09:59 close and the 15:30 close; the skip is 15:31–15:59; weak-day skip kept. Config, design and synthetic tests written. Preregistered. |

An amended version after a run adds a row labelled exactly `bug-fix` or `data-dependent`. A crash
before the first trial row is not a version: write "pre-run fix: <what>" and commit again with
`preregister`.
