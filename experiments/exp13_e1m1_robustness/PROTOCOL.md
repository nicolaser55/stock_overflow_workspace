# exp13_e1m1_robustness: exp12's E1M1 alone

*Protocol version 1.0. Config: `experiments/exp13_e1m1_robustness/config.py`. Design: `design.py`.*

## Question

How does exp12's rule E1M1 do on its own, without a selection among six rules?

## Rules

- The rule, sources and engine of `experiments/exp12_vix_fear_reentry` candidate `E1M1`. One candidate, so the
  candidate in force is always E1M1.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp13_e1m1_robustness`. Periods are the validation quarters of
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
