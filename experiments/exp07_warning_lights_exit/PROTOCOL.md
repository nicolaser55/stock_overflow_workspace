# exp07_warning_lights_exit: Protocol (exit only when several warning lights agree)

*Version 1.0 (2026-10-06). Experiment name `exp07_warning_lights_exit`. Config:
`experiments/exp07_warning_lights_exit/config.py` + `so/config.py`. Written by the agent in autonomous mode (Nicolas,
2026-10-06) from the roadmap of `docs/RESEARCH_STATE_2026-10-06.md` §6, and committed (message `preregister exp07`)
before any run of this experiment. After the first `validation_only` run of step 02, any change of a rule, grid,
selection rule or baseline is a new version with a new experiment name.*

---

## 1. Background and research question

exp04 (one trend signal) exited 12 times on the validation span and bought back higher every time; exp06 showed that
exits plus a buy-stop carry some timing information but are wrong four times out of five. exp07 asks whether requiring
**several independent warnings at once** makes exits rare enough, and right often enough, to pay for the time out.

**Question.** Does exiting SPY only when at least k of 5 fixed warning lights are on, and buying back when fewer than
k − 1 are on, beat buy-and-hold's total return after costs, on one continuous path over the validation span 2015-04-17
→ 2026-04-15?

**Identity that decides success.** Each episode multiplies the shares by S/R; the rule wins only if, over its few
episodes, it buys back lower than it sold by more than the costs. With 3-8 exits in 21 years (roadmap), one or two
episodes decide the result: the **episode scorecard is the evidence**, and no statistic will be significant.

## 2. Hypothesis and why it could (and could not) work

- *Could work:* a real bear market (2008, 2022) turns on most lights at once: price below its trend, a negative
  12-month return, rising volatility, a deep drawdown from the high and an old 60-session high. Short corrections turn
  on only one or two. Requiring k lights filters most of exp04's whipsaw exits.
- *Could fail (expected):* by the time 3-5 lights agree, much of the decline has happened (the lights are lagging by
  construction), and the hysteresis re-entry (fewer than k − 1) also waits for the recovery to be under way. V-shaped
  declines (2018, 2020, 2025) may turn the lights on near the bottom.
- **Known before writing this protocol (disclosed):** the agent has seen the validation results of exp01-exp06 on the
  same span (exp04's trend exit, which is light 1, and exp03/exp06's near-ATH logic, related to light 4). The light
  thresholds were fixed in the roadmap (2026-10-06) before any of exp04-exp06 was run. The re-entry rule was fixed in
  commit `30c8c96` after exp06's 2005-2014 exploration but **before** exp06's validation outputs were read.

## 3. Success criteria (`so/core/evaluation.py`, `so/core/continuous_replay.py`)

| Level | Criterion |
|---|---|
| **Primary** | Prior-only path total return after costs **above buy-and-hold** over the same sessions |
| Comparable return | ≥ 90% of buy-and-hold's total return |
| Secondary (reported, not the goal) | higher Sharpe **or** smaller maximum drawdown, counted only at a comparable return |
| **Information** | The path must also beat the **median of each random family** of §7 (random exit; random re-entry), and more than half of each family's runs |
| Statistical support | Annualized log excess return, circular block bootstrap of **6-month blocks**: "supported" only if the 95% lower bound > 0 |

A path that passes the primary and information criteria is recorded as a **candidate result pending review**
(research-integrity.mdc, "Never" rule 5), never as success.

## 4. Data

SPY 1-minute IBKR bars, regular hours, unadjusted, bad ticks corrected (3% rule); 2007-07-02 missing. The daily table
(`so.features.daily_features.get_daily_feature_pdf`) is built in memory from the raw bars. Used: `ma200_dist_pct`,
`return_250d`, `volatility_ratio_20_60`, `ath_drawdown_pct`, `sessions_since_high60`, all known at the 15:58 decision
(no look-ahead, tested in `tests/test_exp02.py` and `tests/test_exp07.py`).

- Step 01 (exploration): data cut at `so.config.EXPLORATION_DATA_CUTOFF_DATE_STR` (2015-03-18); replay 2005-01-03 →
  2014-12-31. The 250-session return exists from early 2006 and the ATH starts at the first session of the data (2005
  highs are pseudo-ATHs): fewer lights can be on in 2005.
- Step 02 (validation): the schedule is built from the full session calendar (the 44 quarters of exp02-exp06), then
  **the bars are cut at the last validation session (2026-04-15)** before any simulation; the replay also refuses any
  window ending on or after 2026-05-14 (`check_replay_window_bool`).

## 5. Rules (`rules.py`)

- **State machine** (`so/core/reentry_simulation.py`, no stop, no forced buy-back): starts INVESTED at the 10:00 open of
  the first session (as buy-and-hold); one decision per session at the 15:58 bar; fills at the 15:59 open with
  $0.01/share slippage and IBKR fixed fees; cash earns 0%; a position open at the end is sold at the last close.
- **Lights** (thresholds fixed by the roadmap, never fitted; a missing feature is an off light):

  | Light | On when |
  |---|---|
  | `below_ma200` | `ma200_dist_pct` < 0 (close below the 200-session average) |
  | `return_250d_negative` | `return_250d` < 0 (close below its level 250 sessions ago) |
  | `volatility_rising` | `volatility_ratio_20_60` > 1.2 (20-session volatility 20% above the 60-session one) |
  | `ath_drawdown_10pct` | `ath_drawdown_pct` < −10% (more than 10% below the all-time high) |
  | `high60_stale` | `sessions_since_high60` > 20 (the 60-session high is more than 20 sessions old) |

- **Exit:** while invested, sell if at least **k** lights are on at the decision.
- **Re-entry:** while in cash, buy back if **fewer than k − 1** lights are on (hysteresis of one light). The roadmap
  allowed "or by exp06's buy-stop"; it is **not** used (§11).
- **Complete grid (3 candidates):** k ∈ {3, 4, 5}.

## 6. Evaluation design (step 02, continuous replay; `so/core/replay_walk_forward.py`)

- **Periods:** the 44 validation quarters of the exp02-exp06 schedule, made non-overlapping (`get_replay_period_pdf`).
- **Candidate paths (after the fact, optimistic for the best):** each candidate replayed continuously over all 44
  periods; buy-and-hold over the same span. Each (candidate, period) is one logged validation trial: **3 × 44 = 132**.
- **Selection:** mean period score over the last 4 periods (`get_pooled_selection_pdf`). Ties: the **larger k** (fewer
  exits: the choice closest to buy-and-hold). With rare exits most periods tie at 0, so k = 5 governs them.
- **Prior-only path (the honest estimate):** the candidate selected at period f governs period f + 1; one continuous
  switching path from period 1's start (2015-07-17) to 2026-04-15. Buy-and-hold over the same span.
- **No test window** is evaluated. A frozen design that passes §3 would be a parked decision for Nicolas.

## 7. Baselines (same simulator, same costs, same span as the prior-only path)

1. **Buy-and-hold.**
2. **Random exit, same re-entry** (20 runs): exit at each invested decision with probability = the path's exits per
   invested decision; re-entry by the path's rule. Tests the exit signal.
3. **Random re-entry, same exits** (20 runs): the path's exits; re-entry at each cash decision with probability
   1 ÷ the path's mean cash decisions per episode. Tests the re-entry signal.

If the path never exits, every random run equals the path (and the information test cannot pass).

## 8. Statistics and reporting

- Step 01: share of decisions with each light on and with at least k lights; candidate table; the scorecard of every
  candidate.
- Prior-only path: as exp04 (total return vs buy-and-hold, time in the market, periods won with a sign test, MDE,
  annualized log excess with the 6-month-block interval and the 1-month version, Sharpe, drawdown, the success flags,
  the information test, cost sensitivity, **the episode scorecard**).
- One **summary** trial-log entry records the prior-only estimate that was seen.
- Multiple testing: report the trials of this experiment together with the 4,089 legacy trials and the 3,156 trials of
  exp01-exp06.

## 9. Stopping rules

- Step 01 (exploration, 2005-2014): context only; it does not change the grid or the selection, and cannot stop the
  experiment.
- Step 02: **STOP** if the prior-only path does not beat buy-and-hold, **or** does not beat the median of both random
  families. Otherwise: candidate result pending review (§3), the biases of §12 listed, the untouched-window evaluation
  parked for Nicolas.

## 10. Trial budget

Step 01: 3 exploration trials. Step 02: 132 validation trials + 1 summary. **Budget: 140 trials** (one run of each
notebook). A crash half-way is recorded and the notebook re-run once (workflow.mdc).

## 11. Methodological choices (the most conservative option, research-integrity.mdc / workflow.mdc)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| Re-entry | fewer than k − 1 lights; or that rule OR exp06's buy-stop | lights only | The buy-stop is not a validated component (exp06 was data-dependent) and would add a parameter b; fixed before exp06's validation outputs were read |
| Light thresholds | roadmap values, or tuned | roadmap values | Never fitted |
| Missing feature | on, off | off | A light without data cannot warn; fewer exits early in the data |
| Forced buy-back | 60, 250, none | none | As exp04; a cap would add an untested parameter |
| Tie-break | toward more or fewer exits | larger k | Closest to buy-and-hold |
| Interval | 1-month or longer blocks | 6-month circular blocks (1-month shown) | Long exits make months dependent |
| Data cut | full data, cut at the replay end | cut at 2026-04-15 | The simulator cannot read anything later |

## 12. Known limitations and biases

- **Very few episodes:** the result rests on a handful of exits; the MDE will be large and no interval will exclude 0
  unless one episode is very large.
- **Dividends ignored** (favours the strategy while in cash) and **cash at 0%** (penalizes it); both need new data
  (parked decision of 2026-10-06).
- 2015-2026 is development data, seen many times (§2); light 1 is exp04's signal.
- The lights are correlated (a decline turns on several at once), so "k of 5" is less than 5 independent votes.
- Costs are informal; gaps at the 15:59 fill are not modelled beyond the minute open.

## 13. Implementation

| File | Content |
|---|---|
| `config.py` | Every exp07 constant (lights, k) |
| `rules.py` | Schedule and periods, candidates, lights, rule builder |
| `so/core/continuous_replay.py`, `so/core/replay_walk_forward.py` | Continuous replay, switching, scorecard, candidate paths, prior-only path and baselines (shared) |
| `step01_exploration.ipynb` | Light frequencies and 3 candidates on 2005-2014 → `step01_exploration_data/` |
| `step02_continuous_replay.ipynb` | Candidate paths, selection, prior-only path, baselines → `step02_continuous_replay_data/` |
| `tests/test_exp07.py` | Synthetic-data tests |

## 14. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Initial protocol (agent, autonomous mode), pre-registered before any run |
