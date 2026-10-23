# exp04_trend_exit: Trend exit below the 200-session average

*Protocol version 1.0. Config: `experiments/exp04_trend_exit/config.py`. Design: `design.py`.*

## Question

Can a rarely-trading trend exit beat buy-and-hold?

## Rules

- **Exit:** sell at 15:59 after the 15:58 close has been more than x below the average of the previous 200 complete
  closes for n consecutive decisions (counted on the data, whatever the position), x ∈ {0, 3%, 5%}, n ∈ {1, 5, 10}.
- **Buy-back:** when the 15:58 close is more than x above that average. No forced buy-back. A missing average (the
  first 200 sessions) never signals.
- **Candidates:** 9. Ties: larger x, then larger n.
- **Sources:** `SPY_1MIN`, `TSDAY`. Engine `trailing_stop` without a stop.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp04_trend_exit`. Periods are the validation quarters of
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
