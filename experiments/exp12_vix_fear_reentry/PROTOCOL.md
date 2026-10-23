# exp12_vix_fear_reentry: VIX-modified exits and re-entries

*Protocol version 1.0. Config: `experiments/exp12_vix_fear_reentry/config.py`. Design: `design.py`.*

## Question

Does VIX information improve two simple exits?

## Rules

- **E1:** exit when the 15:58 close is below the 200-session average; original re-entry when it is back above.
- **E2:** exit when at least 4 of exp07's 5 lights are on; original re-entry when fewer than 3 are on.
- **M1:** also re-enter when `vix_level_prev` ≤ 0.85 × its maximum from the exit decision through today.
- **M2:** also re-enter when `vix_term_prev` (VIX / VIX3M) < 1 after it was ≥ 1 on a decision since the exit.
- **M3:** ignore the exit while `vix_term_prev` ≥ 1 or `vix_pct250_prev` ≥ 0.9 (missing values do not suppress).
- After an M1 or M2 re-entry, a new exit needs the signal to be off once first. No forced buy-back.
- VIX values: the previous date's daily close, at most 3 sessions old (`so.features.view_history.VixPrevHistory`).
- **Candidates:** E1/E2 × M1/M2/M3 = 6. Ties: E2M3, E2M1, E2M2, E1M3, E1M1, E1M2.
- **Sources:** `SPY_1MIN`, `TSDAY`, `VIX_DAILY`, `VIX3M_DAILY`. Engine `trailing_stop` without a stop.

## Evaluation (shared runner, `docs/RUNNER_DESIGN.md`)

- Development only: `scripts/run_development.py experiments/exp12_vix_fear_reentry`. Periods are the validation quarters of
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
