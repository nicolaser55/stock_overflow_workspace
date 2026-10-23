# exp06_capped_regret_reentry: Exit with a capped-regret re-entry

*Protocol version 1.0. Config: `experiments/exp06_capped_regret_reentry/config.py`. Design: `design.py`.*

## Question

Can a trend or near-ATH exit beat buy-and-hold when a wrong exit is capped by a buy-stop?

## Rules

- **Exit:** `trend_ma200` (15:58 close below the 200-session average) or `ath_1pct` (within 1% of the ATH).
- **Re-entry, first of:** buy-stop: the 15:58 close is at least b ∈ {1%, 2%, 3%} above the sale fill price, after
  which exits are ignored for c ∈ {0, 20} decisions; recovery: the close is above the 200-session average after at
  least one close below it since the exit decision. No forced buy-back.
- **Candidates:** 2 × 3 × 2 = 12. Ties: longer c, smaller b, trend exit first.
- **Sources:** `SPY_1MIN`, `TSDAY`. Engine `trailing_stop` without a stop.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp06_capped_regret_reentry`. Periods are the validation quarters of
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
