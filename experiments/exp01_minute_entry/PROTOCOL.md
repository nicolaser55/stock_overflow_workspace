# exp01_minute_entry: Minute entries with a model-chosen take-profit distance

*Protocol version 1.0. Config: `experiments/exp01_minute_entry/config.py`. Design: `design.py`, model: `model.py`.
Minute mode of the runner (`docs/RUNNER_DESIGN.md`).*

## Question

Does a long-only entry, taken every 15 minutes when a take-profit model's expected net return clears a threshold,
beat buy-and-hold's total return after costs?

## Rules

- **Decision grid:** one row every 15 minutes (entries at 10:00, 10:15, … at the next minute's open). A row holds the
  registered TSIND, TSSEG and TSCTX features of the allowed scale types (`model.MODEL_FEATURE_COL_LIST`) and the
  decision-bar close, each at its `available_ts`.
- **Model:** one LightGBM classifier per distance d in `so.config.TRAIN_DELTA_LIST` (21 distances), target = take
  profit at +d before the stop at −`RR_RATIO`·d or the 10-session time limit (TSBAR cells; unresolved rows excluded),
  average-uniqueness sample weights, fixed parameters with 4 threads and `deterministic`.
- **Refits:** first session of each ISO week (and the first scored session), on the rows dated inside the candidate's
  window (3, 5 or 10 years, including rows before the scored span) whose label was known strictly before the refit's
  first decision. Fewer than 200 rows: no model, no entry.
- **Entry:** expected net return of each distance from P(take profit) and the decision-bar close, after costs; take the
  best distance; enter when it is above the threshold ∈ {0, 0.02%, 0.05%, 0.10%}. Barrier engine: one position at a
  time, take profit, stop loss, time limit; start in cash.
- **Candidates:** window × threshold = 12. Selection: the previous period's score; ties: shorter window, then higher
  threshold. Candidates with the same window share their fits (same rows, same model).
- **Sources:** `SPY_1MIN`, `TSIND`, `TSSEG`, `TSCTX` (rows, sampled at load), `TSBAR` (labels).

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp01_minute_entry`. Periods are the validation quarters
  of `PERIOD_RULE` (10-session embargo before the holdout). Each candidate is one continuous stream; a period score is
  its slice minus buy-and-hold over the same dates.
- Costs: IBKR fees and slippage (`so.config`), cash at 0%, dividends ignored.
- Verdict, baselines, look-ahead check (minute mode: row clocks, shuffle check, truncation and perturbation) and
  report: the runner's. Only Nicolas runs a holdout evaluation.
- Any change to a constant in `config.py` or to the rule after a development run is a new `PROTOCOL_VERSION`.

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-23 | Written for the point-in-time runner (minute mode). Earlier versions and results were deleted (Nicolas, 2026-10-22). |
