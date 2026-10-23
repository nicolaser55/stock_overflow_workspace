# exp02_stop_reentry: Volatility trailing stop with model re-entry

*Protocol version 1.0. Config: `experiments/exp02_stop_reentry/config.py`. Design: `design.py`.*

## Question

Starting fully invested in SPY, can a volatility trailing stop plus a model-timed re-entry beat buy-and-hold?

## Rules

- **Stop:** sell when a minute low reaches the trailing stop: the highest close since entry × (1 − k × daily_volatility),
  never moving down, checked minute by minute by the trailing-stop engine; a gap below the stop fills at the open.
  k ∈ {3, 4, 5}. A decision's k and volatility apply from its 15:59 fill to the next decision's fill.
- **Re-entry:** while in cash, buy at 15:59 when P ≥ p*, with P the model probability on today's 16 daily features and
  p* the training base rate of the model in force plus an offset ∈ {−0.05, 0, +0.05}. Forced re-entry after 60 cash
  decisions.
- **Model:** standardized L2 logistic regression (C = 0.1) of `y_fwd_positive` (the 20-session net forward return is
  positive) on `so.config.DAILY_FEATURE_COL_STR_LIST`. Refit on the first session of each ISO week (and the first
  decision) on the rows dated inside the training window (`10Y` or `ALL`) whose label was known strictly before the
  decision (`TSDAY_FWD`); at least 20 rows or the run stops.
- **Candidates:** window × k × offset = 18. Ties: larger k, higher offset, shorter window.
- **Sources:** `SPY_1MIN`, `TSDAY` (today's features), `TSDAY_FWD` (labels). Engine `trailing_stop`.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp02_stop_reentry`. Periods are the validation quarters of
  `PERIOD_RULE` (20-session embargo before the holdout). Each candidate is one continuous stream; a period score is
  its slice minus buy-and-hold over the same dates. The candidate in force for a period is the best mean score of the
  previous 4 periods (prior-only), ties as listed above; the first period takes the first candidate.
- Decisions at the end of the 15:58 bar, fills at the 15:59 open, IBKR fees and slippage (`so.config`), cash at 0%,
  dividends ignored. Every input is read through the view at its `available_ts`.
- Verdict, baselines, look-ahead check and report: the runner's (`so.runner.verdict`). Email-worthy only if every
  part passes. Only Nicolas runs a holdout evaluation.
- Any change to a constant in `config.py` or to the rule after a development run is a new `PROTOCOL_VERSION`, with a
  line in the change log.

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-23 | Written for the point-in-time runner. Earlier versions and results were deleted (Nicolas, 2026-10-22). |
