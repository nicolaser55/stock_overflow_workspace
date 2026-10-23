# exp07_warning_lights_exit: Warning-lights exit

*Protocol version 1.0. Config: `experiments/exp07_warning_lights_exit/config.py`. Design: `design.py`.*

## Question

Can an exit on several simultaneous warning signs beat buy-and-hold?

## Rules

- **Lights** (a missing feature is off): close below the 200-session average; 250-session return negative;
  `volatility_ratio_20_60` > 1.2; more than 10% below the ATH; more than 20 sessions since the 60-session high.
- **Exit:** at least k ∈ {3, 4, 5} lights on. **Buy-back:** fewer than k − 1 on. No forced buy-back.
- **Candidates:** 3. Ties: larger k.
- **Sources:** `SPY_1MIN`, `TSDAY`. Engine `trailing_stop` without a stop.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp07_warning_lights_exit`. Periods are the validation quarters of
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
