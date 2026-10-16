# exp07_warning_lights_exit_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp07_warning_lights_exit_v2`. Config: `experiments/exp07_warning_lights_exit/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** Nothing was tuned and no rule was added. No further version may follow from this result.

The rules below are the rules of protocol 1.0 at tag `pre-port-20261012`. The old result is in `docs/RESULTS_LOG.md` (prior-only +49.09% vs buy-and-hold +229.74%, STOP).

## 1. Question, rules, grid, selection, baselines, success and stopping (protocol 1.0)

### Question

Does selling when at least k of five fixed warning lights are on, and buying back when fewer than k − 1 are on, beat buy-and-hold's total return after costs on one continuous path?

### Success criteria

Primary: prior-only total return above buy-and-hold. Secondary: higher Sharpe or smaller maximum drawdown only at ≥ 90% of buy-and-hold. Information: beat the median of each random family. Statistical support: 6-month block bootstrap of annualized log excess, lower bound above 0. The 1-month interval is printed alongside.

### Rules (`rules.py`)

- State machine, no stop, no forced buy-back. Starts invested. Decision at 15:58, fill at the 15:59 open, $0.01/share slippage, IBKR fees, cash at 0%.
- Lights, a missing feature is off: `below_ma200` (`ma200_dist_pct` < 0), `return_250d_negative` (`return_250d` < 0), `volatility_rising` (`volatility_ratio_20_60` > 1.2), `ath_drawdown_10pct` (`ath_drawdown_pct` < −10%), `high60_stale` (`sessions_since_high60` > 20).
- Exit when at least k lights are on. Buy back when fewer than k − 1 are on. exp06's buy-stop is not used.
- Complete grid, 3 candidates: k ∈ {3, 4, 5}.

### Selection

Mean period score over the last 4 periods. Ties: the larger k. The candidate selected at period f governs period f + 1.

### Baselines

1. Buy-and-hold.
2. Random exit, same re-entry (20 runs).
3. Random re-entry, same exits (20 runs).

If the path never exits, every random run equals the path.

### Stopping rule

STOP if the prior-only path does not beat buy-and-hold, or does not beat the median of both random families. Otherwise: candidate result pending review. The 2005-2014 exploration is not re-run.

## 2. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start.
- SPY minute bars are read through `DataContext` (`DATA_SOURCE_LIST = ["SPY_1MIN"]`).
- The design implements the `so.core.holdout` interface. Period scores are continuous slices. The prior-only path carries the position.
- The first period uses the first listed rule (`k3`). Protocol 1.0 started the prior-only path at the second period.
- No holdout evaluation is run by the agent.

## 3. Data sources

`SPY_1MIN` only.

## 4. Trial budget

3 × 44 + 1 = **133**. Fewer development quarters log fewer rows. The exploration trials are not repeated.

## 5. Reporting

Optimistic chain, prior-only path, both random families, time in the market, MDE, both log-excess intervals, turnover and switches. Stage `validation`, note `re-run under new rules`.

## 6. Known limitations

Dividends ignored, cash at 0%, informal costs, and lights that are strongly correlated. With rare exits many periods tie, so the larger k governs them.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Full experiment. Prior-only +49.09% vs +229.74%, STOP. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Machinery only (§2). |
| 2.0 | 2026-10-13 | Preregister amendment, before any version 2.0 run. Scores within NUMERIC_TOLERANCE (1e-6) of the best pooled score are tied, then this protocol's tie order. A comparison counts a difference of at most 1e-6 as a match and also reports the maximum absolute difference. Summary prints show 6 decimal places. Calculations, and files later code reads, stay at full precision. |
| 2.0 | 2026-10-15 | Holdout report baselines are the development report's uninformed baselines over the span passed in, with this protocol's fixed seeds, through the point-in-time context. Report-only: no rule, grid, threshold, window, cost, baseline, selection or stopping rule changes. Development results unchanged. |
