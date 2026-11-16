# DRAFT — not for preregister or queue

# exp14_last_half_hour_exit: Protocol

*DRAFT version 1.0 (2026-11-16). Experiment name `exp14_last_half_hour_exit`. Config and design are
not written yet (step 2). Agreed content of this draft is pending Nicolas review of
`RESEARCH_BRIEF.md`. After approval and implementation, a separate commit with subject starting
`preregister exp14` is required before any run. After the first development run, any rule change is a
new `PROTOCOL_VERSION` of this same experiment (same name, same folder; never a renamed copy), with
every candidate renamed (for example `v1.1|<name>`) and a change-log row labelled `bug-fix` or
`data-dependent` (section 11). The folder name must equal `EXPERIMENT_NAME`.*

Derived from: none

Family: I, idea I1, variant 1 of 5

(The line above is required and must stand alone on its line: the family letter and idea id of
`docs/STAGE1_RESEARCH_PLAN.md` sections 4 and 6 / `docs/IDEA_LIST.md`, and which variant of that idea
this version is. A variant is a protocol version, at most 5 per idea across experiments.)

This folder will be a runner design (`docs/RUNNER_DESIGN.md`). Replay, selection, baselines and the
report live in `so.runner`. Development is `scripts/run_development.py <this folder>`. Holdout
evaluation is `scripts/holdout_evaluate.py` (Nicolas only).

## 1. Background and research question

**Question.** Can a long-only, unlevered SPY overlay that sells into cash for the last half-hour on
“weak” days (signal return since the previous close below \(-\,x\) at 15:30) and buys back at the
15:58/15:59 daily call beat buy-and-hold’s **total return** after our costs?

**Why.** Gao, Han, Li & Zhou (*JFE* 2018) and Baltussen, Da, Lammers & Martens (*JFE* 2021) report that
early-day / rest-of-day returns positively predict the last half-hour; Baltussen link it to gamma
hedging that can persist. CXO (2014) finds the link still present in 2012–2014 but small after
frictions. See `RESEARCH_BRIEF.md`.

**Identity.** The strategy beats buy-and-hold only if the skipped last-half-hour intervals lose more
(in total-return terms) than cash earns, by more than round-trip costs. Time out of the market is
tiny (~30 minutes on signal days only).

**Overlap (must state).** Development data 2005–2024 overlaps Gao 1993–2013 on **2005–2013** and
Baltussen 1974–May 2020 on **2005–May 2020**. Those windows are partly replications, not fully
independent tests. Only the holdout and live test are fully out of sample.

No SPY, VIX or other market series were explored for this draft.

## 2. Success criteria

- **Primary (runner verdict return part):** prior-only path total return **strictly above** buy-and-hold
  total return (`primary_success`). The 90% band with better Sharpe or drawdown is reported only,
  never a pass.
- **Comparable / secondary:** reported beside the verdict as in `docs/RUNNER_DESIGN.md`.
- **Information test:** the selected path must beat the **always-skip** baseline (weight 0 at every
  15:30 call, weight 1 at every 15:58 call) as well as the runner’s constant-exposure and
  random-timing baselines. The signal must earn its keep versus indiscriminate last-half-hour exit.
- **Statistical support:** runner multiple-testing and consistency parts (`so/core/evaluation.py`,
  verdict parts in `docs/RUNNER_DESIGN.md`).
- **Minimum detectable effect (expected):** papers’ timed last-half-hour edges are a few percent
  annualized when trading **every** day long/short; our selective long-only skip plus ~$0.03/share
  round trip implies a **small** edge after costs. A fail after costs is an informative result.

The runner’s shared verdict (return / consistency / baselines / look-ahead / multiple testing) is
`pass` or `fail`. It does not replace this protocol’s stopping rule.

## 3. Data

- **Instrument:** SPY 1-minute IBKR bars via the point-in-time view.
- **Period:** development view through the embargo before the registered holdout (boundary from
  `so.core.holdout`, never hard-coded here).
- **Adjustments / cleaning:** shared pipeline only; no new cleaning.
- **Optional VIX gate:** previous session’s VIX daily close (`VIX_DAILY`), expanding median of all
  previous sessions’ values available at the decision (point-in-time).
- **No new data source.**

### 3.1 Data sources

| Source | Convention | Availability | Revision | Role |
|---|---|---|---|---|
| `SPY_1MIN` | bar start | label + 1 minute | not revised (stored IBKR bars) | feature (signal returns from bars in the view) |
| `VIX_DAILY` | previous session close | available as previous-session VIX at the decision | not revised for this design | feature (gate only; candidates with `vixmed`) |
| `SPY_DIVIDENDS` | ex-date | ex-date open (runner total-return path) | registered source | label/path (runner, not read in `decide`) |
| `TBILL_3M` | FRED schedule | next business day (runner cash) | registered source | label/path (runner, not read in `decide`) |

`DATA_SOURCE_LIST` on `design.py` must match the sources the design reads (`SPY_1MIN`, and
`VIX_DAILY` if any candidate uses the gate). Dividends and T-bill are applied by the runner’s
total-return layer, not by `decide`.

## 4. Rules / target / features / model

**Engine:** `fractional`. `INTRADAY_DECISION_TIME_LIST = ["15:30"]` on the module and `Design` class.
`DEAD_BAND = 0.0`. `INITIAL_WEIGHT = 1.0`.

**No model.** Pure rules.

**At 15:30** (`view.intraday_time_str == "15:30"`):
- Compute signal return from previous session close to the signal end price (both from bars in the
  view):
  - `fh`: previous close → **10:00** bar close (Gao first half-hour).
  - `rod`: previous close → **15:30** decision bar close (Baltussen rest-of-day through the decision).
- Gate: if candidate has `vixmed`, require previous-session VIX \(>\) expanding median of all prior
  available VIX values; if VIX missing, do **not** skip (keep weight 1 / NaN keep — exact NaN policy
  fixed in design with tests).
- If signal return \(< -x\) and gate passes: target weight **0**; else target weight **1** (or NaN =
  keep if history too short).

**At 15:58** (`intraday_time_str is None`): target weight **1** (buy back; fill 15:59).

**Fills:** next bar open after each decision (15:31 after 15:30; 15:59 after 15:58). Costs:
`ENTRY_SLIPPAGE_PER_SHARE`, `MARKET_EXIT_SLIPPAGE_PER_SHARE`, IBKR fee schedule in `so.config`.

## 5. Walk-forward and selection

Candidate periods: development validation quarters (`PERIOD_RULE` → `get_development_fold_pdf`),
extended through the holdout by the runner. Embargo = `so.config.LABEL_HORIZON_SESSIONS`.
`train_years` = 1 so a validation quarter exists (no rolling train window for this rule design).

**Candidates:** the 12 names in section 5.1. Selection pools the last 4 completed quarters. Tie order:
candidate name ascending. First period (no completed quarter) takes the first listed candidate
(`fh|x050|off`).

Period score = period return − buy-and-hold (continuous slice). Prior-only path as usual.

### 5.1 Complete candidate list (trial budget for this version)

| # | Candidate | Signal | \(x\) | VIX gate |
|---|---|---|---|---|
| 1 | `fh|x050|off` | first half-hour | 0.5% | off |
| 2 | `fh|x100|off` | first half-hour | 1.0% | off |
| 3 | `fh|x150|off` | first half-hour | 1.5% | off |
| 4 | `fh|x050|vixmed` | first half-hour | 0.5% | VIX > expanding median |
| 5 | `fh|x100|vixmed` | first half-hour | 1.0% | VIX > expanding median |
| 6 | `fh|x150|vixmed` | first half-hour | 1.5% | VIX > expanding median |
| 7 | `rod|x050|off` | rest-of-day to 15:30 | 0.5% | off |
| 8 | `rod|x100|off` | rest-of-day to 15:30 | 1.0% | off |
| 9 | `rod|x150|off` | rest-of-day to 15:30 | 1.5% | off |
| 10 | `rod|x050|vixmed` | rest-of-day to 15:30 | 0.5% | VIX > expanding median |
| 11 | `rod|x100|vixmed` | rest-of-day to 15:30 | 1.0% | VIX > expanding median |
| 12 | `rod|x150|vixmed` | rest-of-day to 15:30 | 1.5% | VIX > expanding median |

**Trial budget:** 12 candidates (= 12 designs in N) in this version; at most two further versions of
this experiment in family I (three versions in all); idea I1 has variants 2–5 still available across
experiments. Family I still has two other idea slots (I2, I3) after this idea is used.

No retraining section: there is no fitted model.

## 6. Baselines

Runner shared baselines, same engine, same costs: buy-and-hold; daily-rebalanced constant exposure at
the path’s mean weight (dead band 0.05); 100-seed random timing (intraday-aware).

**Uninformed version of the informed component:** always-skip last half-hour (weight 0 at every 15:30,
weight 1 at every 15:58), same costs. The threshold/signal/VIX information must beat this.

## 7. Stopping rules

- Signal / exploration: none that peek at development results before preregister; brief used papers
  only.
- Walk-forward: apply prior-only path vs buy-and-hold and baselines as scored by the runner.
- Apply this protocol as written. Runner verdict reported beside it.
- A fail after costs is a result; do not widen the grid after seeing outcomes (that would be a new
  data-dependent version with renamed candidates).

### 7.1 Trial budget

See section 5.1. Variants of idea I1 already spent: **0** (this is variant 1 of 5). Versions this
experiment may still use after 1.0: **2** (family cap three versions total).

## 8. Reporting

After-the-fact candidates, prior-only path with baselines, time in the market (and skip counts), MDE
context from the brief, success criteria, `report.json` / `report.md` / `manifest.json`. Candidate-period
trial rows go to the shared trial log as scored. Agents read grades/status only under
`store04_experiments/visible/`.

## 9. Discipline, implementation, limitations

- `design.py` must pass runner preflight: no `so.runner`, `so.core.point_in_time`, `so.core.holdout`,
  file I/O, or `.base`. State on the design object between `decide` calls.
- Fixed per-share slippage on intraday fills may understate fast markets (runner limit note).
- Gao’s predictability is **weaker when the first half-hour is negative** (Table 10); this overlay
  only skips on the weak side — a known limitation.
- Overlap with published samples (section 1).
- CXO: extreme-decile last-half-hour moves may be smaller than frictions.
- Early closes: no 15:30 call → no skip that session (runner mapping).

## 10. Holdout evaluation

Frozen prior-only path from development start through the holdout; same code, same 15:30 / 15:58
decisions and fills, same costs. Only Nicolas runs `scripts/holdout_evaluate.py`. Agents never set
holdout env vars or read the quarantine.

## 11. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 DRAFT | 2026-11-16 | Draft protocol from template + research brief; no `config.py` / `design.py` yet; not preregistered |

An amended version after a run adds a row labelled exactly `bug-fix` or `data-dependent`. A crash
before the first trial row is not a version: write "pre-run fix: \<what\>" and commit again with
`preregister`.
