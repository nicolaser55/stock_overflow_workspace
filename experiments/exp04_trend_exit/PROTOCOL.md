# exp04_trend_exit: Protocol (benchmark of the "stay invested, exit rarely" family)

*Version 1.0 (2026-10-06). Experiment name `exp04_trend_exit`. Config: `experiments/exp04_trend_exit/config.py` +
`so/config.py`. Written by the agent in autonomous mode (Nicolas, 2026-10-06) from the roadmap of
`docs/RESEARCH_STATE_2026-10-06.md` §6, and committed (message `preregister exp04`) before any run of this experiment.
After the first `validation_only` run of step 02, any change of a rule, grid, selection rule or baseline is a new version
with a new experiment name.*

---

## 1. Background and research question

exp01-exp03 lost to buy-and-hold mainly because of **time out of the market**: at ~12% a year, each session in cash costs
~0.045% of expected return. The new family (Nicolas, 2026-10-06) maximizes time in the market and exits only on strong
evidence, with an explicit re-entry, and allows holding periods of months or years.

**Question.** Does the classic trend exit, *sell when SPY has been clearly below its 200-session average for a while and
buy back when it is clearly above it*, beat buy-and-hold's total return after costs, on one continuous path over the
validation span 2015-04-17 → 2026-04-15, with the position carried across quarters?

**Identity that decides success.** Selling at S and buying back at R leaves S/R times the shares. The rule wins only if,
on average, it buys back lower than it sold, by more than the costs. A trend exit sells *after* a decline has started and
buys back *after* a recovery has started, so it gives up the move between the true turning point and its signal twice
per round trip.

## 2. Hypothesis and why it could (and could not) work

- *Could work:* long bear markets (2000-2002, 2008) unfold over months; a rule that is out for most of such a decline
  avoids a drawdown far larger than the two signal lags.
- *Could fail (expected):* the 2015-2026 declines were mostly V-shaped (2015-16, late 2018, 2020, spring 2025): the price
  crosses the average near the bottom and recovers before the buy-back signal. 2022 was slower.
- **Known before writing this protocol (disclosed):** the textbook rule (x = 0, n = 1) gave +50.4% vs +69.0% on 2005-2014
  (exp02 step 01) and +106.16% vs +237.21% on the 2015-2026 validation quarters with the quarterly reset (exp02/exp03
  baselines). The roadmap states this experiment is **expected to fail** criterion (a); its role is the **benchmark** that
  exp05-exp07 must beat.

## 3. Success criteria (`so/core/evaluation.py`, `so/core/continuous_replay.py`)

| Level | Criterion |
|---|---|
| **Primary** | Prior-only path total return after costs **above buy-and-hold** over the same sessions |
| Comparable return | ≥ 90% of buy-and-hold's total return |
| Secondary (reported, not the goal) | higher Sharpe **or** smaller maximum drawdown, counted only at a comparable return |
| **Information** | The path must also beat the **median of each random family** of §7 (random exit; random re-entry) |
| Statistical support | Annualized log excess return, circular block bootstrap of **6-month blocks**: "supported" only if the 95% lower bound > 0 |

A path that passes the primary and information criteria is recorded as a **candidate result pending review**
(research-integrity.mdc, "Never" rule 5), never as success.

## 4. Data

SPY 1-minute IBKR bars, regular hours, unadjusted, bad ticks corrected (3% rule); 2007-07-02 missing. The daily table
(`so.features.daily_features.get_daily_feature_pdf`) is built in memory from the raw bars. Only `ma200_dist_pct` is used
(decision close at 15:58 ÷ mean of the previous 200 complete session closes − 1; no look-ahead, tested).

- Step 01 (exploration): data cut at `so.config.EXPLORATION_DATA_CUTOFF_DATE_STR` (2015-03-18); replay 2005-01-03 →
  2014-12-31.
- Step 02 (validation): the schedule is built from the full session calendar (so that the 44 quarters equal exp02's and
  exp03's), then **the bars are cut at the last validation session (2026-04-15)** before any simulation, so no bar of the
  untouched window (2026-05-14 → 2026-08-13) or of 2026-04-16 → 2026-05-13 is ever given to the simulator. The replay
  also refuses any window ending on or after 2026-05-14 (`check_replay_window_bool`).
- The daily table's forward label columns are not used.

## 5. Rules (`rules.py`)

- **State machine** (`so/core/reentry_simulation.py`, no stop): starts INVESTED at the 10:00 open of the first session
  (as buy-and-hold); one decision per session at the 15:58 bar; fills at the 15:59 open with $0.01/share slippage and
  IBKR fixed fees; cash earns 0%; a position open at the end is sold at the last close.
- **Exit:** while invested, sell if `ma200_dist_pct` < −x on this decision **and** the n − 1 previous decisions
  (counted on the data, whatever the position).
- **Re-entry:** while in cash, buy back if `ma200_dist_pct` > +x on the decision.
- **No forced buy-back** (`MAX_CASH_SESSIONS = None`): the rule alone decides when to return.
- **Complete grid (9 candidates):** x ∈ {0, 3%, 5%} × n ∈ {1, 5, 10}, in that order. (x = 0, n = 1) is the textbook
  200-day rule (tested equal to `simulate_trend_rule_dict`).

## 6. Evaluation design (step 02, continuous replay; `so/core/replay_walk_forward.py`)

- **Periods:** the 44 validation quarters of the exp02/exp03 schedule (20-session embargo, folds that fit 10 years),
  made non-overlapping (`get_replay_period_pdf`: period f = fold f's validation start → the session before fold f + 1's
  validation start; the last period ends 2026-04-15). They tile 2015-04-17 → 2026-04-15.
- **Candidate paths (after the fact, optimistic for the best):** each candidate replayed continuously over all 44
  periods; buy-and-hold replayed over the same span. Period score = candidate period return − buy-and-hold period return.
  Each (candidate, period) is one logged validation trial: **9 × 44 = 396 trials**.
- **Selection:** mean period score over the last 4 periods (this one and the 3 before; fewer for the first),
  `so.core.evaluation.get_pooled_selection_pdf`. Ties: the **larger x, then the larger n** (fewer, later exits: the
  choice closest to buy-and-hold).
- **Prior-only path (the honest estimate):** the candidate selected at period f governs period f + 1. One continuous
  path from period 1's start (2015-07-17) to 2026-04-15 switches rules at period boundaries while the position carries
  (`get_switching_rule_dict`). Buy-and-hold is replayed over the same span.
- **No test window** is evaluated. A frozen design that passes §3 would be a parked decision for Nicolas (untouched data).

## 7. Baselines (same simulator, same costs, same span as the prior-only path)

1. **Buy-and-hold.**
2. **Random exit, same re-entry** (20 runs): exit at each invested decision with probability = the path's exits per
   invested decision; re-entry by the path's rule. Tests the exit signal.
3. **Random re-entry, same exits** (20 runs): the path's exit signal; re-entry at each cash decision with probability
   1 ÷ the path's mean cash decisions per episode. Tests the re-entry signal.
4. The textbook rule (x = 0, n = 1) is inside the grid; its own continuous path is reported with the candidates.

If the path never exits, every random run equals the path.

## 8. Statistics and reporting

- Candidate table: total and annualized return, excess over buy-and-hold, time in the market, exits, mean cash
  decisions per episode, share of episodes bought back lower, annualized log excess with its interval.
- Prior-only path: total return vs buy-and-hold, annualized returns, **time in the market**, periods won with a one-sided
  sign test, mean / SD / t of the period excess and the **minimum detectable effect** (2.8 × SD / √n per period, × 4 per
  year), annualized log excess with the 6-month-block interval (the 1-month version printed alongside), Sharpe, maximum
  drawdown, the success flags, the information test (median of each random family and the share of runs beaten), cost
  sensitivity at $0.00 / $0.01 / $0.02, and the **episode scorecard** (every exit: dates, S, R, S/R, sessions out,
  buy-and-hold change while out, largest decline avoided, cost).
- One **summary** trial-log entry records the prior-only estimate that was seen.
- Multiple testing: report the trials of this experiment together with the 4,089 legacy trials and the 2,027 trials of
  exp01-exp03.

Plain-words reading of the log excess: an annualized log excess of −0.05 means the strategy's wealth grows about 5% a
year more slowly than buy-and-hold's (continuously compounded).

## 9. Stopping rules

- Step 01 (exploration, 2005-2014): context only; it does not change the grid or the selection, and cannot stop the
  experiment.
- Step 02: **STOP** if the prior-only path does not beat buy-and-hold, **or** does not beat the median of both random
  families. Otherwise: candidate result pending review (§3), the biases of §11 listed, the untouched-window evaluation
  parked for Nicolas.

## 10. Trial budget

Step 01: 9 exploration trials. Step 02: 396 validation trials + 1 summary. **Budget: 410 trials** (one run of each
notebook). A crash half-way is recorded and the notebook re-run once (workflow.mdc).

## 11. Methodological choices (the most conservative option, research-integrity.mdc / workflow.mdc)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| Re-entry confirmation | n decisions above +x, or one | one decision above +x (as the roadmap states) | The roadmap fixes it; changing it would add a grid dimension |
| Forced buy-back | 60, 250, none | none | The rule is defined without one; a cap would add an untested parameter |
| Tie-break | toward more or fewer exits | larger x, then larger n | Closest to buy-and-hold: never favours activity |
| Interval | 1-month or longer blocks | 6-month circular blocks (1-month shown) | Long exits make months dependent; longer blocks give wider, less flattering intervals |
| Random baselines matched to | each period, or the whole path | the whole path | One rate over the path; per-period matching would reuse the path's timing |
| Data cut | full data, or cut at the replay end | cut at 2026-04-15 | The simulator cannot read anything later |

## 12. Known limitations and biases

- **Dividends ignored** (SPY ~1.3-2% a year): buy-and-hold is understated and time in cash is not charged for missed
  dividends, which **favours this strategy**. **Cash earns 0%** (T-bills up to ~5% in 2023-2025), which **penalizes** it.
  Both need new data (parked decision of 2026-10-06).
- 2015-2026 is development data, seen many times by exp01-exp03 and earlier work; the textbook rule's validation result
  was known (§2).
- Few large declines: the scorecard (a handful of episodes) is the main evidence; the MDE will be several percent a year.
- Costs are informal; gaps at the 15:59 fill are not modelled beyond the minute open.
- The 9 candidates are strongly correlated; the selection has little to choose from.

## 13. Implementation

| File | Content |
|---|---|
| `config.py` | Every exp04 constant |
| `rules.py` | Schedule and periods, candidates, exit / re-entry signals, rule builder |
| `so/core/continuous_replay.py`, `so/core/replay_walk_forward.py` | Continuous replay, periods, switching, scorecard, bootstrap, candidate paths, prior-only path and baselines (shared, Step 0) |
| `step01_exploration.ipynb` | 9 candidates on 2005-2014 → `step01_exploration_data/` |
| `step02_continuous_replay.ipynb` | Candidate paths, selection, prior-only path, baselines → `step02_continuous_replay_data/` |
| `tests/test_exp04.py`, `tests/test_continuous_replay.py` | Synthetic-data tests |

## 14. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Initial protocol (agent, autonomous mode), pre-registered before any run |
