# exp05_vol_scaled_exposure_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp05_vol_scaled_exposure_v2`. Config: `experiments/exp05_vol_scaled_exposure/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** The version 1.0 run already used this data. Nothing was tuned and no rule was added. No further version may follow from this result.

The rules below are the rules of protocol 1.0 (`experiments/exp05_vol_scaled_exposure/PROTOCOL.md` at tag `pre-port-20261012`, commit `00269da`). Version 2.0 changes only the evaluation machinery. The old result is in `docs/RESULTS_LOG.md` (prior-only +165.69% vs buy-and-hold +229.74%, STOP). The version 1.0 signal check passed; it is not re-run.

## 1. Question, rules, grid, selection, baselines, success and stopping (protocol 1.0)

### Question

Does holding w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, with a 20-point dead band, beat buy-and-hold's total return after costs on one continuous path?

### Success criteria

Primary: prior-only path total return after costs above buy-and-hold. Secondary, reported and not the goal: higher Sharpe or smaller maximum drawdown, counted only at a comparable return (≥ 90% of buy-and-hold). Information: the path must beat the constant exposure, the median random shift, and more than half of the random shifts. Statistical support: annualized log excess, 6-month block bootstrap, "supported" only if the lower bound is above 0. The 1-month interval is printed alongside. A path that passes primary and information is a candidate result pending review.

### Rules (`exposure.py`)

- Weight at the 15:58 decision: w = min(1, max(floor, σ_target / σ̂)). w = 1 where σ̂ or the target is missing.
- Target volatility: for each replay period, the q-quantile of every `daily_volatility` value before the period starts (expanding from the first session). Undefined, so w = 1, with fewer than 250 earlier values. The session just before the first period gets the first period's target.
- Execution: start with the weight decided at the session before the span, bought at the first session's 10:00 open. Rebalance at the 15:59 open only if |w − current weight| > 0.20. A target ≥ 1 buys every affordable share. $0.01/share slippage and IBKR fees. Cash earns 0%. The position is sold at the last close.
- Complete grid, 4 candidates: floor ∈ {30%, 50%} × q ∈ {0.50, 0.75}, floor then quantile.

### Selection

Mean period score over the last 4 periods. Period score = the continuous-slice return minus buy-and-hold over the same sessions. Ties: the higher floor, then the higher q (closest to buy-and-hold). The candidate selected at period f governs period f + 1.

### Baselines (same simulator, same costs, same dead band, same span)

1. Buy-and-hold (w = 1).
2. Constant exposure at the prior-only path's mean end-of-day weight.
3. Random shifts (20 runs): the path's target weights, including the session before the span, circularly shifted by a draw in [126, N − 126]. Seed `so.config.RANDOM_SEED`.

### Stopping rule

The version 1.0 signal check passed, so the development replay is run. STOP if the prior-only path does not beat buy-and-hold, or does not beat the constant exposure, the median random shift, and more than half of the random shifts. Otherwise: candidate result pending review. The 2005-2014 exploration is not re-run.

## 2. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start. Dates are not typed in `config.py`.
- SPY minute bars are read through `DataContext` (`DATA_SOURCE_LIST = ["SPY_1MIN"]`).
- The design implements the `so.core.holdout` interface. Period scores are continuous slices. The prior-only path carries the position.
- The first period has no history. The shared selector puts the first listed rule in force (`0.30|0.50`). Protocol 1.0 started the prior-only path at the second period.
- The signal check and the 2005-2014 exploration are not re-run.
- No holdout evaluation is run by the agent. This version is the one prepared for that evaluation.

## 3. Data sources

`SPY_1MIN`. Availability is the decision bar's timestamp. No other source is read.

## 4. Trial budget

4 candidates × 44 quarters + 1 summary = **177**. A development span with fewer quarters logs fewer rows. The budget is not raised. The signal-check and exploration trials of protocol 1.0 are not repeated.

## 5. Reporting

Best candidate after the fact, labelled optimistic. Prior-only path. Constant exposure and random shifts. Mean weight. Minimum detectable effect and both log-excess intervals. Performance over time, turnover, and candidate switches. Stage `validation`, note `re-run under new rules`.

## 6. Known limitations

Dividends ignored, cash at 0%, the 20-point band makes the constant baseline close to "buy a fraction and hold" (recorded in the version 1.0 correction), informal costs, and a grid of correlated candidates. The version 1.0 signal-check descriptive column that started at weight 1 on the first session of the data is not recomputed.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Full experiment. Result in `docs/RESULTS_LOG.md`: prior-only +165.69% vs +229.74%, STOP. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Machinery only (§2). |
