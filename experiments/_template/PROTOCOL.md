# expNN_<name>: Protocol

*Version 1.0 (YYYY-MM-DD). Experiment name `expNN_<name>`. Config: `experiments/expNN_<name>/config.py` + `so/config.py`.
Agreed with Nicolas on YYYY-MM-DD, before any of this experiment's data was explored. After the first development
run, any rule change is a new version with a new experiment name.*

This folder is the runner template (`docs/RUNNER_DESIGN.md`). A new experiment copies it and fills the sections
below. `design.py` declares the candidates, the sources, the engine and `decide(view)`. Replay, selection, baselines
and the report live in `so.runner`. Development is `scripts/run_development.py <this folder>`. Holdout evaluation is
`scripts/holdout_evaluate.py` (Nicolas only).

## 1. Background and research question
What is tested, why, and what earlier experiments showed. The identity that decides success (e.g. "buys back lower than it sold").

## 2. Success criteria
Primary / comparable return / secondary / information test (the uninformed baseline the information must beat) /
statistical support (`so/core/evaluation.py`). State the minimum detectable effect you expect to face.

The runner's shared verdict (return / consistency / baselines / look-ahead) is applied after every development run.
It does not replace this protocol's stopping rule.

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
| `TSDAY_FWD` | decision of session i + 20 | `label_known_ts` at that later decision; unfinished rows dropped | not revised | label |

The two features are `intraday_return_pct` (decision close over the session open) and `prev_day_return_pct` (the previous session's close-to-close return). Both are computed from the view's SPY bars at the decision moment, the end of the 15:58 bar. The same session's close, the 15:59 bar, is not a feature.

`DATA_SOURCE_LIST` on `design.py` must match this table. `scripts/run_development.py` loads that list through the development end. The evaluation script loads the same names through the window end from the quarantine root.

## 4. Rules / target / features / model
Exactly as implemented (file and function names). For every feature: what it uses up to the decision bar.

This template: `Design.decide` in `design.py`. Logistic regression of `y_fwd_positive` on the two features. The weight is the predicted probability, clipped to [0, 1]. Engine `fractional`, dead band 0, initial weight 1.

## 5. Walk-forward and selection
Candidate periods are the development validation quarters (`PERIOD_RULE` → `get_development_fold_pdf`), extended through the holdout. The embargo is the label horizon (`so.config.LABEL_HORIZON_SESSIONS`). The fold schedule's `train_years` is 1, so a validation quarter exists; it is not the model's training window. The candidates are the three training windows below. Selection pools the last 4 completed quarters. A tie takes the longer window, then the candidate name. The first period has no completed quarter and takes the first listed candidate (`6M`).

Fill `CANDIDATE_LIST`, `get_candidate_design`, `PERIOD_RULE`, `SELECTION_RULE`, `CANDIDATE_TIE_VALUE_DICT`, `ENGINE_NAME`, `DEAD_BAND`, `INITIAL_WEIGHT` on `design.py`.

## 5.1 Retraining
Pre-registered (Nicolas, 2026-10-11). Changing any line here after a result is a new version.

- **Training-window candidates:** `6M`, `2Y`, `10Y` (`so.config.TRAIN_WINDOW_CANDIDATE_LIST_DEFAULT`). A row is inside a window when its date is on or after (retrain day − the window) and on or before the retrain day.
- **Retraining frequency:** weekly, the first session of each calendar week (`so.config.RETRAIN_FREQUENCY_DEFAULT_STR`). A Monday holiday is a Tuesday refit. The first decision of a stream always refits. `RETRAIN_FREQUENCY_COMPARISON_STR` is empty: this template does not pre-register the optional weekly-versus-quarterly comparison. A protocol that does pre-register it may name one comparison, and no other.
- **Label:** `y_fwd_positive` on `TSDAY_FWD`, 1 when the net return from the fill to the close 20 sessions later is positive (`so.config.LABEL_HORIZON_SESSIONS`). `label_known_ts` is the decision moment of that later session. The last 20 sessions have no clock and are dropped. A redacted blank cell is a missing label, never filled with 0.
- **Purge:** a training row must have `label_known_ts` strictly before the retraining decision (`view.get_labels`). Rows that fail are dropped and counted as purged. They are never filled with 0 or any other value.
- **Feature known times:** both features are read from the SPY bars in the view. There is no second clock.
- **Minimum training rows:** 20. A refit with fewer rows raises. There is no fallback window. A one-class window returns that class's rate; that is the model's defined behaviour, not a different window.
- **Selection:** period score = period return − buy-and-hold, a continuous slice of the candidate's stream. The candidate for quarter f is chosen from the last 4 completed quarters before f (prior-only). Tie order: longer training window (`train_window_months` descending: 10Y, then 2Y, then 6M), then the candidate name ascending.
- **Decisions:** every session of the span, at the decision bar, with the latest model of the candidate in force. The weight is the predicted probability. NaN means keep.

## 6. Baselines
The runner's shared baselines, same engine, same costs: buy-and-hold, daily-rebalanced constant exposure at the path's mean weight, and 100-seed random timing that places the path's non-base spells at random. Always also name the uninformed version of the informed component this protocol tests.

## 7. Stopping rules
Signal check (base rate, two-sided, ≥ 6 months per bin, pooled validation), exploration on 2005-2014 only, walk-forward
(prior-only path vs buy-and-hold and baselines). Apply this protocol's rule as written. The runner verdict is reported beside it.

## 8. Reporting
After-the-fact candidates, prior-only path with baselines, time in the market, MDE, success criteria, runner report.json / report.md / manifest.json. Candidate-period trial rows go to the shared trial log as they are scored.

## 9. Discipline, implementation, limitations

`design.py` must pass the runner preflight: no `so.runner`, `so.core.point_in_time`, `so.core.holdout`, file I/O, or `.base`. State lives on the design object between `decide` calls. A value whose `available_ts` is after the decision is not in the view.

## 10. Holdout evaluation

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

The development boundary is not a hard-coded date. It is `so.core.holdout.get_development_end_date(embargo)`: the session
an embargo before the active holdout start. Validation folds come from `so.core.schedule.get_development_fold_pdf`
(validation windows only). Do not read the holdout for exploration, validation or any decision.

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
| 1.0 | YYYY-MM-DD | Initial protocol |
| template | 2026-10-11 | Holdout evaluation section added (rolling 12-month holdout; development boundary from so.core.holdout) |
| template | 2026-10-11 | Holdout evaluation rewritten to the frozen prior-only path (audit R1–R3, H1): design interface, truncation test, ledger status |
| template | 2026-10-12 | Rolling retrain example (Nicolas, 2026-10-11): weekly logistic regression, windows 6M/2Y/10Y, purge by dropping unfinished labels. VIX is no longer read. |
| template | 2026-10-22 | Runner port (infrastructure 4c). `decide(view)` with `view.get_labels("TSDAY_FWD")`. No copied replay, selection, baseline or report code. Entry point `scripts/run_development.py`. |
