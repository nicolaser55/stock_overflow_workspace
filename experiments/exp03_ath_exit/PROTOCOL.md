# exp03_ath_exit: Protocol ("sell at strength")

*Version 1.0 (2026-10-05). Experiment name `exp03_ath_exit`. Config: `experiments/exp03_ath_exit/config.py` +
`so/config.py`. The idea was explored on 2005-2014 on 2026-10-04 (step 13 of the previous workspace, 30 exploration trials:
`ath_exit_exploration`, `ath_exit_exploration_clean`). On 2026-10-05 Nicolas decided to turn it into a full walk-forward
experiment, with **all 15 exploration rules as candidates** and the same pooled selection as exp02. This protocol fixes the
design before its first validation run in the project. After that run, any rule change is a new version.*

*Disclosure: while verifying the reorganized code on 2026-10-05, the assistant executed this experiment's notebooks once,
on a copy of the same data, in its own sandbox. Those results were seen by the assistant only; no rule, grid or baseline
was changed after that run. The official first run is Nicolas's.*

---

## 1. Hypothesis

Instead of selling on weakness (exp02 stops, which sell into dips that revert), **sell when SPY is at or near its all-time
high** and buy back later, lower (Nicolas, 2026-10-04).

The identity of exp02 applies: an episode that sells at S and buys back at R ends with S ÷ R times the shares. A rule beats
buy-and-hold only if, on average, it **buys back lower than it sold**. Prices that merely rise *less* than usual after
near-ATH days are not enough.

## 2. What the exploration showed (2005-2014, corrected data; `docs/history/RESULTS_LOG_2026-10-05.md`)

- Forward returns after near-ATH days: slightly negative for 1-20 sessions at the tight thresholds, no difference
  significant; positive at 40-60 sessions.
- 5 of 15 rules beat buy-and-hold (+69.0%): 4 of 5 at the 0.5% threshold, none at 1%, one at 2%; best +11.7 pts
  (0.5%, buy back after a 5% dip). Drawdown about unchanged; about 15 independent episodes; most buy-backs forced.
- Conclusion then: weak and inconsistent, not evidence of an edge. **Choosing the best exploration rule would be selection
  on exploration results**, so the walk-forward keeps all 15 and lets the past quarters choose.

## 3. Success criteria

As exp02 (`so/core/evaluation.py`): primary = chained total return after costs above buy-and-hold; secondary = higher Sharpe
and smaller maximum drawdown at a comparable return (≥ 90% of buy-and-hold's); **information** = the rule must beat its
random baselines (§7); monthly block-bootstrap interval of the chained excess return ("statistically supported" only if its
lower bound is above 0).

## 4. Rules (`rules.py`; one candidate = one threshold × one buy-back)

- **State machine** (`so/core/reentry_simulation.py`, no stop): invested by default; one decision per session at 15:58,
  fills at the 15:59 open (+ slippage), IBKR fees, cash earns 0%.
- **Exit:** sell when the 15:58 close is within **x** of the all-time high, x ∈ **{0.5%, 1%, 2%}** (`ATH_WITHIN_LIST`).
  ATH = highest high since 2005-01-03 (previous sessions and today up to the decision bar; `ath_drawdown_pct`).
- **Buy-back:** after **5, 20 or 60** cash decisions (`BUYBACK_DELAY_LIST`), or when the 15:58 close is **2% or 5%** below
  the sale fill price (`BUYBACK_DIP_LIST`).
- **Forced buy-back** after 60 cash decisions (`MAX_CASH_SESSIONS`).
- 3 × 5 = **15 candidates**, listed in a fixed order (`rule_order`).
- Each evaluated window starts invested at its first 10:00 open, as buy-and-hold; a position open at the window's end is
  sold at the last close; state is not carried between windows.

## 5. Data

As exp02: SPY minute bars, unadjusted, bad ticks corrected (3% rule). The daily table is built in memory from the raw bars.

## 6. Walk-forward (step 02, `walk_forward.py`)

- **The same schedule as exp02** (3-month windows, 20-session embargo, folds that fit a 10-year window): **44 folds** with
  the same validation quarters. No model is trained; the embargo and the window only make the folds identical to exp02's.
- **Validation:** every rule on every validation quarter (15 trials per fold, logged).
- **Selection:** mean validation excess return over the last 4 validation quarters (this fold and the 3 before it).
  Ties: the tighter threshold (fewer exits), then the rule order.
- **Test** (run modes `latest` / `history` only, after freezing): the selected rule on the test window, once.

## 7. Baselines (same simulator, same costs)

1. **Buy-and-hold** over the same window.
2. **Random buy-back** (same ATH exit): 20 runs, buying back at each cash decision with probability 1 ÷ (the rule's mean cash
   decisions per episode in the window). Tests the buy-back rule.
3. **Random exit** (same buy-back rule): 20 runs, selling at each invested decision with probability = the rule's exits per
   invested decision in the window. Tests the ATH exit signal itself.
4. **200-session moving-average rule** (reference only).

When the rule never exits in a window, every random run equals the rule. *Baselines 3 and 4 were added by the assistant
when writing this protocol (the agreed design named buy-and-hold and random buy-back); Nicolas to confirm.*

## 8. Reporting

As exp02 §12: every rule chained over the validation quarters (after the fact, optimistic) with its exits, time in cash and
share of episodes bought back lower; the **prior-only path** (rule selected at fold f, evaluated with its baselines on fold
f + 1's validation quarter; the re-simulation must equal the logged candidate) with chained return, quarters won with a
sign test, mean/SD/t of the quarterly excess, minimum detectable effect, time in cash, success criteria, bootstrap interval
and the information test; one **summary** trial-log entry per run. Exploration (step 01): forward-return table and the 15
rules over 2005-2014, logged as 15 exploration trials.

## 9. Stopping rule

On validation: **STOP** if the prior-only path fails to beat buy-and-hold, or fails to beat the random baselines (the
information test). The test windows are evaluated only after the design is frozen.

## 10. Discipline

- Trial log experiment `exp03_ath_exit`; the hash covers `so/config.py` + this `config.py`. Stages: `exploration`,
  `validation`, `summary`, `test`. The 30 exploration trials of 2026-10-04 stay in the legacy trial log and count.
- The exploration notebook reads data only up to 2015-03-18 (`so.config.EXPLORATION_DATA_CUTOFF_DATE_STR`).
- Tests: `tests/test_exp03.py`.

## 11. Known limitations

- Pseudo-ATHs in 2005-2006 (SPY's 2000 peak is not in the data).
- Few independent ATH episodes; the 60-decision cap and the quarterly reset limit time out of the market (as exp02).
- The ATH uses minute highs: a residual bad tick (audit F1, e.g. 2014-12-18 15:59 high $212.97) can set a false ATH until
  the real price passes it.
- Dividends ignored (favours time in cash); cash earns 0%.

## 12. Change log

| Version | Date | Change |
|---|---|---|
| (exploration) | 2026-10-04 | Step 13 exploration, 15 rules, 2005-2014 (`ath_exit_exploration`, `ath_exit_exploration_clean`) |
| 1.0 | 2026-10-05 | Full experiment (decided by Nicolas): all 15 rules as walk-forward candidates, exp02's schedule and pooled selection, buy-and-hold and random buy-back baselines; random exit and trend baselines added by the assistant (to confirm); honest reporting as exp02 |
