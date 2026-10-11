# expNN_<name>: Protocol

*Version 1.0 (YYYY-MM-DD). Experiment name `expNN_<name>`. Config: `experiments/expNN_<name>/config.py` + `so/config.py`.
Agreed with Nicolas on YYYY-MM-DD, before any of this experiment's data was explored. After the first `validation_only`
run, any rule change is a new version with a new experiment name.*

## 1. Background and research question
What is tested, why, and what earlier experiments showed. The identity that decides success (e.g. "buys back lower than it sold").

## 2. Success criteria
Primary / comparable return / secondary / information test (the uninformed baseline the information must beat) /
statistical support (`so/core/evaluation.py`). State the minimum detectable effect you expect to face.

## 3. Data
Instrument, period, adjustments, cleaning, which pipeline steps are used, any new data source (with its timing: when is a
value known relative to the 15:58 decision?).

## 3.1 Data sources
Mandatory. Every source the design reads, and only registered sources (`so.core.point_in_time`, `docs/DATA_SOURCES.md`).
One row per source: registry name, timestamp convention, availability rule, revision policy, role (feature or label).
A source that is not in this table is not used. When the evidence for a clock is unclear, the later time is the one written here.

| Source | Convention | Availability | Revision | Role |
|---|---|---|---|---|
| `SPY_1MIN` | bar start | label + 1 minute | not revised (stored IBKR bars) | feature |
| `VIX_DAILY` | midnight date label | that date at 16:15 America/New_York | not revised (stored print) | feature |

The VIX feature in the template is `vix_level_prev`: the daily close of the previous session, read through `DataContext.get` as of the decision. The same session's 16:15 close is not used.

A development replay loads this list with `get_development_data_context` (through the development end). The evaluation script loads the same names with `load_source_frame_dict` through the window end. A design that omits `DATA_SOURCE_LIST` is treated as `["SPY_1MIN"]`.

## 4. Rules / target / features / model
Exactly as implemented (file and function names). For every feature: what it uses up to the decision bar.

## 5. Walk-forward and selection
Schedule (embargo ≥ horizon), candidates (each logged), selection rule and tie-breaks, refit, test only after freezing.

## 6. Baselines
Same simulator, same costs. Always the uninformed version of the informed component (random / fixed choices).

## 7. Stopping rules
Signal check (base rate, two-sided, ≥ 6 months per bin, pooled validation), exploration on 2005-2014 only, walk-forward
(prior-only path vs buy-and-hold and baselines).

## 8. Reporting
After-the-fact candidates, prior-only path with baselines, time in the market, MDE, success criteria, summary trial entry.

## 9. Discipline, implementation, limitations

## 10. Holdout evaluation

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

The development boundary is not a hard-coded date. It is `so.core.holdout.get_development_end_date(embargo)`: the session
an embargo before the active holdout start. Validation folds come from `so.core.schedule.get_development_fold_pdf`
(validation windows only). Do not read the holdout for exploration, validation or any decision.

Only Nicolas runs the evaluation (`scripts/holdout_evaluate.py`), once per frozen design per window. Agents never run
that script or `scripts/holdout_window.py`, and never set `SO_HOLDOUT_PATH`, `SO_HOLDOUT_EVALUATION_TOKEN` or
`SO_ALLOW_LEGACY_REPRODUCTION`.

`design.py` exposes `PERIOD_RULE`, `CANDIDATE_LIST`, `SELECTION_RULE`, `run_candidate_replay_dict`,
`run_prior_only_path_dict` and `get_baseline_return_dict` (see `experiments/README.md`). The runner scores every
candidate on every period (period return minus buy-and-hold), selects for period f from periods before f only, and
replays one continuous path from the first period through the window end. Before any result is written it re-runs that
path on bars truncated after each of 12 month-ends inside the window. A difference aborts with ledger status
`invalid_lookahead` and writes no daily paths; that row counts against the window budget. A valid run has status
`valid` and reports only the holdout sessions.

The report names the uninformed baselines of §6, computed on the holdout sessions only, plus buy-and-hold over those
sessions: total return against buy-and-hold, annualized log excess with a 6-month block interval, time in the market,
Sharpe, maximum drawdown, the minimum detectable effect, the success criteria (primary: total return above
buy-and-hold; secondary: higher Sharpe or a smaller drawdown with at least 90% of buy-and-hold's return), the position
carried into the window, and the candidate in force in each holdout period.

## 11. Change log
| Version | Date | Change |
|---|---|---|
| 1.0 | YYYY-MM-DD | Initial protocol |
| template | 2026-10-11 | Holdout evaluation section added (rolling 12-month holdout; development boundary from so.core.holdout) |
| template | 2026-10-11 | Holdout evaluation rewritten to the frozen prior-only path (audit R1–R3, H1): design interface, truncation test, ledger status |
