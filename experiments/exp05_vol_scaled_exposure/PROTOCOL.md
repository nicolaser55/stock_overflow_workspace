# exp05_vol_scaled_exposure: Volatility-scaled exposure

*Protocol version 1.0. Config: `experiments/exp05_vol_scaled_exposure/config.py`. Design: `design.py`.*

## Question

Can holding less SPY when volatility is high beat buy-and-hold? With weights w ≤ 1 the strategy is ahead only if
the periods of reduced exposure have negative returns in total.

## Rules

- **Weight:** w = min(1, max(floor, σ_target / σ̂)), decided at 15:58, filled at 15:59. σ̂ = today's
  `daily_volatility`. σ_target = the q-quantile of every `daily_volatility` value of the sessions before the current
  calendar quarter's first session (at least 250 values, otherwise w = 1); fixed for the quarter. Missing σ̂: w = 1.
- **Dead band:** rebalance only when |w − current weight| > 0.2. Integer shares.
- **Candidates:** floor ∈ {0.3, 0.5} × q ∈ {0.5, 0.75} = 4. Ties: higher floor, then higher q.
- **Sources:** `SPY_1MIN`, `TSDAY`. Engine `fractional`.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp05_vol_scaled_exposure`. Periods are the validation quarters of
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
