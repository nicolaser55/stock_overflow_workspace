# exp04_trend_exit_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp04_trend_exit_v2`. Config: `experiments/exp04_trend_exit/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** The version 1.0 run already used this data. Nothing was tuned and no rule was added. No further version may follow from this result.

The rules below are the rules of protocol 1.0 (`experiments/exp04_trend_exit/PROTOCOL.md` at tag `pre-port-20261012`, commit `00269da`). Version 2.0 changes only the evaluation machinery, listed after those sections. The old result is in `docs/RESULTS_LOG.md` (prior-only +70.84% vs buy-and-hold +229.74%, STOP).

## 1. Question, rules, grid, selection, baselines, success and stopping (protocol 1.0)

### Question

Does the classic trend exit, sell when SPY has been clearly below its 200-session average and buy back when it is clearly above it, beat buy-and-hold's total return after costs, on one continuous path, with the position carried across quarters?

Selling at S and buying back at R leaves S/R times the shares. The rule wins only if, on average, it buys back lower than it sold, by more than the costs.

### Success criteria

Primary: prior-only path total return after costs above buy-and-hold. Secondary, reported and not the goal: higher Sharpe or smaller maximum drawdown, counted only at a comparable return (≥ 90% of buy-and-hold). Information: the path must beat the median of each random family. Statistical support: annualized log excess, circular block bootstrap of 6-month blocks, "supported" only if the 95% lower bound is above 0. The 1-month block interval is printed alongside. A path that passes primary and information is a candidate result pending review, never a success claim.

### Rules (`rules.py`)

- State machine (`so.core.reentry_simulation`, no stop): starts invested at the first session's 10:00 open; one decision per session at 15:58; fills at the 15:59 open with $0.01/share slippage and IBKR fees; cash earns 0%; a position open at the end is sold at the last close.
- Exit: while invested, sell if `ma200_dist_pct` < −x on this decision and the n − 1 previous decisions (counted on the data, whatever the position).
- Re-entry: while in cash, buy back if `ma200_dist_pct` > +x on the decision. One decision, not n.
- No forced buy-back (`MAX_CASH_SESSIONS = None`).
- Complete grid, 9 candidates: x ∈ {0, 3%, 5%} × n ∈ {1, 5, 10}, buffer then confirmation. (x = 0, n = 1) is the textbook 200-session rule.

### Selection

Mean period score over the last 4 periods (this one and the 3 before; fewer for the first). Period score = the candidate's continuous-slice return minus buy-and-hold over the same sessions. Ties: the larger x, then the larger n (fewer, later exits; closest to buy-and-hold). The candidate selected at period f governs period f + 1.

### Baselines (same simulator, same costs, same span as the prior-only path)

1. Buy-and-hold.
2. Random exit, same re-entry (20 runs): exit at each invested decision with probability = the path's exits per invested decision; re-entry by the path's rule.
3. Random re-entry, same exits (20 runs): the path's exit signal; re-entry at each cash decision with probability 1 ÷ the path's mean cash decisions per episode.
4. The textbook rule is inside the grid. It is not a separate baseline.

If the path never exits, every random run equals the path. The information test uses baselines 2 and 3.

### Stopping rule

STOP if the prior-only path does not beat buy-and-hold, or does not beat the median of both random families. Otherwise: candidate result pending review. The 2005-2014 exploration does not change the grid and cannot stop the experiment.

## 2. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start (`so.core.holdout`). Dates are not typed in `config.py`.
- SPY minute bars are read through `DataContext` (`DATA_SOURCE_LIST = ["SPY_1MIN"]`).
- The design implements the `so.core.holdout` interface. A candidate's period score is the slice of one continuous path, which is how protocol 1.0 scored a quarter. The prior-only path is one continuous replay that switches rules at period boundaries and carries the position.
- The first period has no history. The shared selector puts the first listed rule in force (`0.00|1`). Protocol 1.0 started the prior-only path at the second period. The runner requires a candidate on every period, including the first.
- The 2005-2014 exploration is not re-run. Its verdict stays in `docs/RESULTS_LOG.md`.
- No holdout evaluation is run by the agent.

## 3. Data sources

`SPY_1MIN`. Availability is the decision bar's timestamp (`so.core.point_in_time`). No other source is read.

## 4. Trial budget

9 candidates × 44 quarters + 1 summary = **397**. A development span with fewer quarters logs fewer rows. The budget is not raised. The 9 exploration trials of protocol 1.0 are not repeated.

## 5. Reporting

Best candidate after the fact, labelled optimistic (the chain of its continuous slices). Prior-only path. Uninformed baselines (both random families). Time in the market. Minimum detectable effect and the 6-month log-excess interval, with the 1-month interval printed alongside. Performance over time, turnover, and candidate switches. Stage `validation`, note `re-run under new rules`.

## 6. Known limitations

The limitations of protocol 1.0 still apply: dividends ignored (this favours a rule that holds cash), cash at 0% (this penalizes it), few large declines, informal costs, and a grid of strongly correlated candidates. The continuous path carries the position across periods, as protocol 1.0 did.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Full experiment. Result in `docs/RESULTS_LOG.md`: prior-only +70.84% vs +229.74%, STOP. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Machinery only (§2). |
