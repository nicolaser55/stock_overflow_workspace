# exp03_ath_exit_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp03_ath_exit_v2`. Config: `experiments/exp03_ath_exit/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** The version 1.0 run already used this data. Nothing was tuned and no rule was added. No further version may follow from this result.

The rules below are the rules of protocol 1.0 (`experiments/exp03_ath_exit/PROTOCOL.md` at tag `pre-port-20261012`, commit `00269da`), copied verbatim. Version 2.0 changes only the evaluation machinery, listed after the verbatim sections. The old result is in `docs/RESULTS_LOG.md` (prior-only +143.05% vs buy-and-hold +237.21%, STOP).

## 1. Question, rules, grid, selection, baselines, success and stopping (protocol 1.0, verbatim)

### Hypothesis

Instead of selling on weakness (exp02 stops, which sell into dips that revert), **sell when SPY is at or near its all-time high** and buy back later, lower (Nicolas, 2026-10-04).

The identity of exp02 applies: an episode that sells at S and buys back at R ends with S ÷ R times the shares. A rule beats buy-and-hold only if, on average, it **buys back lower than it sold**. Prices that merely rise *less* than usual after near-ATH days are not enough.

### Success criteria

As exp02 (`so/core/evaluation.py`): primary = chained total return after costs above buy-and-hold; secondary = higher Sharpe **or** smaller maximum drawdown at a comparable return (≥ 90% of buy-and-hold's; either is enough, Nicolas 2026-10-05); **information** = the rule must beat its random baselines (§7); monthly block-bootstrap interval of the chained excess return ("statistically supported" only if its lower bound is above 0).

### Rules (`rules.py`; one candidate = one threshold × one buy-back)

- **State machine** (`so/core/reentry_simulation.py`, no stop): invested by default; one decision per session at 15:58, fills at the 15:59 open (+ slippage), IBKR fees, cash earns 0%.
- **Exit:** sell when the 15:58 close is within **x** of the all-time high, x ∈ **{0.5%, 1%, 2%}** (`ATH_WITHIN_LIST`). ATH = highest high since 2005-01-03 (previous sessions and today up to the decision bar; `ath_drawdown_pct`).
- **Buy-back:** after **5, 20 or 60** cash decisions (`BUYBACK_DELAY_LIST`), or when the 15:58 close is **2% or 5%** below the sale fill price (`BUYBACK_DIP_LIST`).
- **Forced buy-back** after 60 cash decisions (`MAX_CASH_SESSIONS`).
- 3 × 5 = **15 candidates**, listed in a fixed order (`rule_order`).
- Each evaluated window starts invested at its first 10:00 open, as buy-and-hold; a position open at the window's end is sold at the last close; state is not carried between windows.

### Walk-forward and selection

- **The same schedule as exp02** (3-month windows, 20-session embargo, folds that fit a 10-year window). No model is trained; the embargo and the window only make the folds identical to exp02's.
- **Validation:** every rule on every validation quarter (15 trials per fold, logged).
- **Selection:** mean validation excess return over the last 4 validation quarters (this fold and the 3 before it). Ties: the tighter threshold (fewer exits), then the rule order.

### Baselines (same simulator, same costs)

1. **Buy-and-hold** over the same window.
2. **Random buy-back** (same ATH exit): 20 runs, buying back at each cash decision with probability 1 ÷ (the rule's mean cash decisions per episode in the window). Tests the buy-back rule.
3. **Random exit** (same buy-back rule): 20 runs, selling at each invested decision with probability = the rule's exits per invested decision in the window. Tests the ATH exit signal itself.
4. **200-session moving-average rule** (reference only).

When the rule never exits in a window, every random run equals the rule. The **information test** uses baselines 2 and 3: the rule must beat the median of both random families. Baseline 4 is context only and decides nothing.

### Stopping rule

On validation: **STOP** if the prior-only path fails to beat buy-and-hold, or fails to beat the random baselines (the information test).

## 2. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 20 before the registered holdout start (`so.core.holdout`). Dates are not typed in `config.py`.
- SPY minute bars are read through `DataContext` (`DATA_SOURCE_LIST = ["SPY_1MIN"]`).
- The design implements the `so.core.holdout` interface. Period scores are fresh windows, which is how protocol 1.0 scored a quarter. The prior-only path is one continuous replay, because that is the path the runner continues. The first period, which has no history, uses the first listed rule (`0.005|delay_5`).
- The 2005-2014 exploration is not re-run. Its verdict stays in `docs/RESULTS_LOG.md`.
- No holdout evaluation is run by the agent.

## 3. Data sources

`SPY_1MIN`. Availability is the decision bar's timestamp (`so.core.point_in_time`). No other source is read.

## 4. Trial budget

15 candidates × 44 quarters + 1 summary = **661**. A development span with fewer quarters logs fewer rows. The budget is not raised.

## 5. Reporting

Best candidate after the fact, labelled optimistic. Prior-only path. Uninformed baselines (both random families, and the trend rule as context). Time in the market. Minimum detectable effect and the 6-month log-excess interval. Performance over time, turnover, and candidate switches. Stage `validation`, note `re-run under new rules`.

## 6. Known limitations

The limitations of protocol 1.0 still apply: pseudo-ATHs in 2005-2006, few independent ATH episodes, a residual bad tick can set a false ATH, dividends ignored, cash at 0%. The continuous prior-only path carries the position across quarters. Protocol 1.0 reset each quarter. Period scores stay fresh windows so they can be compared with the old saved quarters on shared bounds.

## 7. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-05 | Full experiment. Result in `docs/RESULTS_LOG.md`: prior-only +143.05% vs +237.21%, STOP. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Machinery only (§2). |
