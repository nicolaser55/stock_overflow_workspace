# exp06_capped_regret_reentry_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp06_capped_regret_reentry_v2`. Config: `experiments/exp06_capped_regret_reentry/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** Data-dependent follow-up of exp03, as protocol 1.0. Nothing was tuned and no rule was added. No further version may follow from this result.

The rules below are the rules of protocol 1.0 at tag `pre-port-20261012`. The old result is in `docs/RESULTS_LOG.md` (prior-only +147.38% vs buy-and-hold +229.74%, STOP; the information test as defined was met).

## 1. Question, rules, grid, selection, baselines, success and stopping (protocol 1.0)

### Question

Does pairing a fixed exit (textbook trend break, or within 1% of the all-time high) with a buy-stop at S × (1 + b), a cooling-off, or a recovery above the 200-session average, beat buy-and-hold's total return after costs on one continuous path?

### Success criteria

Primary: prior-only total return above buy-and-hold. Secondary: higher Sharpe or smaller maximum drawdown only at ≥ 90% of buy-and-hold. Information: beat the median of each random family. Statistical support: 6-month block bootstrap of annualized log excess, lower bound above 0. The 1-month interval is printed alongside. Passing primary and information is a candidate result pending review.

### Rules (`rules.py`)

- State machine, no stop, no forced buy-back. Starts invested. Decision at 15:58, fill at the 15:59 open, $0.01/share slippage, IBKR fees, cash at 0%.
- Exits: `trend_ma200` (`ma200_dist_pct` < 0) and `ath_1pct` (`ath_drawdown_pct` ≥ −1%).
- Re-entry, in order: buy-stop when the decision close ≥ S × (1 + b), then the exit is ignored for the next c decisions; otherwise recovery when the close is above the 200-session average and at least one close since the exit was below it.
- Complete grid, 12 candidates: exit ∈ {`trend_ma200`, `ath_1pct`} × b ∈ {1%, 2%, 3%} × c ∈ {0, 20}, in that order.

### Selection

Mean period score over the last 4 periods. Period score is the continuous-slice return minus buy-and-hold. Ties: the longer cooling-off, then the smaller buy-stop, then the trend exit. The candidate selected at period f governs period f + 1.

### Baselines

1. Buy-and-hold.
2. Random exit, same re-entry (20 runs).
3. Random re-entry, same exits (20 runs), with no buy-stop and no cooling-off.
4. The textbook trend rule is the family benchmark. It is not a separate logged baseline of this version.

If the path never exits, every random run equals the path.

### Stopping rule

STOP if the prior-only path does not beat buy-and-hold, or does not beat the median of both random families. Otherwise: candidate result pending review. The 2005-2014 exploration does not change the grid and is not re-run.

## 2. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start.
- SPY minute bars are read through `DataContext` (`DATA_SOURCE_LIST = ["SPY_1MIN"]`).
- The design implements the `so.core.holdout` interface. Period scores are continuous slices. The prior-only path carries the position and switches the re-entry rule, including its cooling-off, at period boundaries.
- The first period uses the first listed rule (`trend_ma200|0.01|0`). Protocol 1.0 started the prior-only path at the second period.
- No holdout evaluation is run by the agent.

## 3. Data sources

`SPY_1MIN` only.

## 4. Trial budget

12 × 44 + 1 = **529**. Fewer development quarters log fewer rows. The 12 exploration trials are not repeated.

## 5. Reporting

Optimistic chain, prior-only path, both random families, time in the market, MDE, both log-excess intervals, turnover and switches. Stage `validation`, note `re-run under new rules`.

## 6. Known limitations

Data-dependent origin (exp03's validation). Dividends ignored, cash at 0%, informal costs. Beating 19 of 20 random exits in version 1.0 was an empirical p ≈ 0.10 and was not statistical support. The verdict stayed STOP.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Full experiment. Prior-only +147.38% vs +229.74%, STOP. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Machinery only (§2). |
| 2.0 | 2026-10-13 | Preregister amendment, before any version 2.0 run. Scores within NUMERIC_TOLERANCE (1e-6) of the best pooled score are tied, then this protocol's tie order. A comparison counts a difference of at most 1e-6 as a match and also reports the maximum absolute difference. Summary prints show 6 decimal places. Calculations, and files later code reads, stay at full precision. |
| 2.0 | 2026-10-15 | Holdout report baselines are the development report's uninformed baselines over the span passed in, with this protocol's fixed seeds, through the point-in-time context. Report-only: no rule, grid, threshold, window, cost, baseline, selection or stopping rule changes. Development results unchanged. |
