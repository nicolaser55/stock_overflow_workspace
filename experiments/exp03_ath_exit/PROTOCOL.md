# exp03_ath_exit: Sell near the all-time high

*Protocol version 1.0. Config: `experiments/exp03_ath_exit/config.py`. Design: `design.py`.*

## Question

Can selling when SPY is near its all-time high and buying back later beat buy-and-hold? An episode that sells at S
and buys back at R ends with S / R times the shares: the rule wins only if it buys back lower than it sold.

## Rules

- **Exit:** sell at 15:59 when the 15:58 close is within x of the all-time high (`ath_drawdown_pct` ≥ −x),
  x ∈ {0.5%, 1%, 2%}. ATH = highest high since 2005-01-03 up to the decision bar.
- **Buy-back:** after n ∈ {5, 20, 60} cash decisions, or when the 15:58 close is d ∈ {2%, 5%} below the sale fill
  price. Forced buy-back after 60 cash decisions.
- **Candidates:** 3 × 5 = 15. Ties: tighter x, then list order.
- **Sources:** `SPY_1MIN`, `TSDAY`. Engine `trailing_stop` without a stop.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp03_ath_exit`. Periods are the validation quarters of
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
