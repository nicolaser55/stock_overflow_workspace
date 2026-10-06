# exp05_vol_scaled_exposure: Protocol (fractional exposure scaled by realized volatility)

*Version 1.0 (2026-10-06). Experiment name `exp05_vol_scaled_exposure`. Config:
`experiments/exp05_vol_scaled_exposure/config.py` + `so/config.py`. Written by the agent in autonomous mode (Nicolas,
2026-10-06) from the roadmap of `docs/RESEARCH_STATE_2026-10-06.md` §6, and committed (message `preregister exp05`)
before any run of this experiment. After the first `validation_only` run of step 02, any change of a rule, grid,
selection rule or baseline is a new version with a new experiment name.*

---

## 1. Background and research question

exp01-exp04 were all-in / all-out and lost to buy-and-hold through time out of the market (exp04's trend exit: prior-only
+70.84% vs +229.74%, bought back higher after all 12 exits). exp05 never leaves the market: it holds a **fraction**
w ∈ [floor, 1] of the account in SPY and reduces it when recent volatility is high.

**Question.** Does holding w = min(1, max(floor, σ_target / σ̂)) of the account in SPY, rebalanced only beyond a dead
band, beat buy-and-hold's total return after costs on one continuous path over the validation span 2015-04-17 →
2026-04-15?

**Arithmetic that decides success.** With daily SPY returns r_t and weights w_t ≤ 1 (cash at 0%), the strategy earns
about Σ w_t r_t and buy-and-hold Σ r_t, so the strategy is ahead only if **Σ (1 − w_t) r_t < 0** (plus the costs): the
sessions of reduced exposure must have *negative* returns in total. Lower returns than average are not enough; without
leverage the strategy cannot hold more than buy-and-hold when volatility is low.

## 2. Hypothesis and why it could (and could not) work

- *Could work:* volatility clusters (today's volatility predicts the next month's), and high-volatility periods of SPY
  include its worst sessions (2008, March 2020, 2022). If returns in the highest-volatility regime are negative on
  average, trimming exposure there raises the total return; the "leverage effect" (prices fall as volatility rises) is
  the usual argument.
- *Could fail (expected):* the same high-volatility regimes contain the largest *up* sessions (rebounds of 2009, April
  2020, April 2025). Volatility peaks near the bottom of V-shaped declines, so the weight is lowest during the
  rebound. The published evidence for volatility-managed portfolios (Moreira & Muir, 2017) relies on leverage when
  volatility is low; long-only and unlevered, the usual result is a better Sharpe ratio and a smaller drawdown, at a
  lower total return.
- **Known before writing this protocol (disclosed):** the agent has seen the 2015-2026 results of exp01-exp04 (the
  validation span had V-shaped declines in 2015-16, 2018, 2020 and 2025, and a slower one in 2022). No volatility-scaled
  exposure has been computed in this workspace. The roadmap states this experiment can beat buy-and-hold only if
  high-volatility periods have below-zero returns.

## 3. Success criteria (`so/core/evaluation.py`, `so/core/continuous_replay.py`)

| Level | Criterion |
|---|---|
| **Primary** | Prior-only path total return after costs **above buy-and-hold** over the same sessions |
| Comparable return | ≥ 90% of buy-and-hold's total return |
| Secondary (reported, not the goal) | higher Sharpe **or** smaller maximum drawdown, counted only at a comparable return |
| **Information** | The path must also beat the **constant exposure** at its mean weight **and** the median of the **random shifts** (and more than half of them), §7 |
| Statistical support | Annualized log excess return, circular block bootstrap of **6-month blocks**: "supported" only if the 95% lower bound > 0 |

A path that passes the primary and information criteria is recorded as a **candidate result pending review**
(research-integrity.mdc, "Never" rule 5), never as success.

## 4. Data and the signal check

SPY 1-minute IBKR bars, regular hours, unadjusted, bad ticks corrected (3% rule); 2007-07-02 missing. The daily table
(`so.features.daily_features.get_daily_feature_pdf`) is built in memory from the raw bars. Only `daily_volatility` is
used as σ̂: the standard deviation of the previous 20 complete-session close-to-close returns, known at the 15:58
decision (no look-ahead, tested in `tests/test_exp02.py`). `session_close` and `fill_open` are used by the signal check.

- **Step 01** (exploration): data cut at `so.config.EXPLORATION_DATA_CUTOFF_DATE_STR` (2015-03-18); decisions
  2005-01-03 → 2014-12-31 (the 20 forward sessions of the last decisions end before the cutoff).
  - **Signal check (gate of step 02):** Spearman correlation between σ̂ and the realized volatility of the next 20
    sessions (standard deviation of the close-to-close returns of sessions s+1 … s+20), 95% interval from a circular
    block bootstrap of 6-month blocks of calendar months (2,000 iterations, seed `so.config.RANDOM_SEED`); also the
    log-log regression slope and R². **PASS if the lower bound > 0.**
  - **Descriptive:** mean forward 20-session log return (15:59 fill → 15:59 fill 20 sessions later) by quintile of σ̂
    (edges from the same window), with the share of positive returns. Overlapping windows: no test, description only.
  - **Exploration:** the 4 candidates as one continuous path over 2005-2014 (targets fixed per calendar year), against
    buy-and-hold and the constant exposure at the same mean weight.
- **Step 02** (validation): the schedule is built from the full session calendar (so that the 44 quarters equal
  exp02-exp04's), then **the bars are cut at the last validation session (2026-04-15)** before any simulation, so no bar
  of the untouched window (2026-05-14 → 2026-08-13) or of 2026-04-16 → 2026-05-13 is given to the simulator. The replay
  also refuses any window ending on or after 2026-05-14 (`check_replay_window_bool`).

## 5. Rules (`exposure.py`, `so/core/fractional_exposure.py`)

- **Weight:** w_s = min(1, max(floor, σ_target / σ̂_s)) at the 15:58 decision of session s; w = 1 where σ̂ or the target
  is missing.
- **Target volatility:** for each replay period, the q-quantile of **every** `daily_volatility` value of the sessions
  before the period starts (expanding from 2005-01-03, as the anchored training windows of the schedule), fixed for the
  whole period; undefined (w = 1) with fewer than 250 earlier values. The session just before the first period gets the
  first period's target (it decides the initial weight).
- **Execution:** the account starts with the weight decided at the session before the span, bought at the 10:00 open of
  the first session. At each later decision it computes the current weight at the 15:58 close and rebalances at the 15:59
  open **only if |w_s − current weight| > 0.20** (dead band); a target ≥ 1 buys every affordable share. $0.01/share
  slippage and IBKR fixed fees on every trade; cash earns 0%; the position is sold at the last close.
- **Complete grid (4 candidates):** floor ∈ {30%, 50%} × q ∈ {0.50, 0.75}, in that order.

## 6. Evaluation design (step 02, continuous replay)

- **Periods:** the 44 validation quarters of the exp02-exp04 schedule (20-session embargo, folds that fit 10 years),
  made non-overlapping (`get_replay_period_pdf`); they tile 2015-04-17 → 2026-04-15.
- **Candidate paths (after the fact, optimistic for the best):** each candidate replayed continuously over all 44
  periods; buy-and-hold over the same span. Period score = candidate period return − buy-and-hold period return. Each
  (candidate, period) is one logged validation trial: **4 × 44 = 176 trials**.
- **Selection:** mean period score over the last 4 periods (`so.core.evaluation.get_pooled_selection_pdf`). Ties: the
  **higher floor, then the higher q** (the choice closest to buy-and-hold).
- **Prior-only path (the honest estimate):** the candidate selected at period f governs period f + 1. One continuous
  path from period 1's start (2015-07-17) to 2026-04-15; each session's weight is the weight of its period's candidate,
  and the position carries across periods. Buy-and-hold over the same span.
- **No test window** is evaluated. A frozen design that passes §3 would be a parked decision for Nicolas.

## 7. Baselines (same simulator, same costs, same dead band, same span as the prior-only path)

1. **Buy-and-hold** (w = 1).
2. **Constant exposure** at the prior-only path's mean end-of-day weight (the uninformed version: same average exposure,
   no timing). Tests whether the *timing* of the reductions adds anything over holding less SPY all the time.
3. **Random shifts** (20 runs): the path's target weights circularly shifted by a random number of sessions in
   [126, N − 126] (N = path sessions plus the session before it; seed `so.config.RANDOM_SEED`). Same distribution and
   persistence of the weights, timing unrelated to volatility.

## 8. Statistics and reporting

- Signal check: Spearman correlation and interval, log-log slope and R², and the volatility-bin table.
- Candidate table: total and annualized return, excess over buy-and-hold, mean weight, rebalances, periods won,
  annualized log excess with its interval, Sharpe, maximum drawdown.
- Prior-only path: total return vs buy-and-hold, annualized returns, **mean weight in SPY** (the time-in-the-market
  measure of a fractional path), rebalances and costs, periods won with a one-sided sign test, mean / SD / t of the period
  excess and the **minimum detectable effect** (2.8 × SD / √n per period, × 4 per year), annualized log excess with the
  6-month-block interval (1-month version alongside), Sharpe, maximum drawdown, the success flags, the information test,
  and the cost sensitivity at $0.00 / $0.01 / $0.02.
- One **summary** trial-log entry records the prior-only estimate that was seen.
- Multiple testing: report the trials of this experiment together with the 4,089 legacy trials and the 2,433 trials of
  exp01-exp04.

## 9. Stopping rules

- Step 01: if the signal check fails (lower bound ≤ 0), step 02 is **not run**: the pipeline is checked and the result
  recorded; the experiment stops unless a pipeline bug is found (its fix would be a new version). The descriptive table
  and the exploration are context only; they do not change the grid or the selection.
- Step 02: **STOP** if the prior-only path does not beat buy-and-hold, **or** does not beat the constant exposure, the
  median random shift and more than half of the random shifts. Otherwise: candidate result pending review (§3), the
  biases of §12 listed, the untouched-window evaluation parked for Nicolas.

## 10. Trial budget

Step 01: 1 signal check + 4 exploration trials. Step 02: 176 validation trials + 1 summary. **Budget: 185 trials** (one
run of each notebook). A crash half-way is recorded and the notebook re-run once (workflow.mdc).

## 11. Methodological choices (the most conservative option, research-integrity.mdc / workflow.mdc)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| σ̂ | 20-session std, 60-session std, EWMA, VIX | `daily_volatility` (20 sessions) | Existing feature, no new parameter; VIX is new data (parked) |
| Target history | rolling 10 years, expanding | expanding (as the anchored training windows) | The roadmap's "training median"; no extra window parameter |
| Target updates | every session, per period | fixed per period | A target that moves with today's data partly cancels the signal; per period mirrors training → validation |
| Dead band | 0, 10, 20 points | 20 points (roadmap) | Fewer trades; fixed in the roadmap, not tuned |
| Tie-break | toward lower or higher exposure | higher floor, then higher q | Closest to buy-and-hold: never favours de-risking |
| Random baseline | i.i.d. permutation, circular shift | circular shift (≥ 126 sessions) | Keeps the persistence (few rebalances, same costs); a permutation would trade daily, pay more costs and be easier to beat |
| Uninformed exposure | 100%, the path's mean weight | both reported; the mean weight is the information test | Separates "holding less" from "timing" |
| Interval | 1-month or longer blocks | 6-month circular blocks (1-month shown) | Volatility regimes make months dependent; wider, less flattering intervals |
| Data cut | full data, cut at the replay end | cut at 2026-04-15 | The simulator cannot read anything later |

## 12. Known limitations and biases

- **Dividends ignored** (SPY ~1.3-2% a year): buy-and-hold is understated and the cash share is not charged for missed
  dividends, which **favours this strategy** by about (1 − mean weight) × 1.5% a year. **Cash earns 0%** (T-bills up to
  ~5% in 2023-2025), which **penalizes** it by about (1 − mean weight) × the T-bill rate. Both need new data (parked
  decision of 2026-10-06).
- 2015-2026 is development data, seen many times by exp01-exp04 and earlier work (§2).
- With w ≥ floor the strategy is always mostly invested; its excess over buy-and-hold is small by construction and the
  MDE will be large relative to it.
- The 4 candidates are strongly correlated; the selection has little to choose from.
- Costs are informal; gaps at the 15:59 fill are not modelled beyond the minute open. Fractional shares are not allowed
  (the weight is rounded down to whole shares).

## 13. Implementation

| File | Content |
|---|---|
| `config.py` | Every exp05 constant |
| `exposure.py` | Schedule and periods, candidates, targets, weights, weight-path simulation, candidate paths, prior-only path and baselines, signal check, volatility-bin table |
| `so/core/fractional_exposure.py`, `so/core/continuous_replay.py` | Fractional simulator, periods, assignment, summary, bootstrap (shared, Step 0) |
| `step01_exploration.ipynb` | Signal check, volatility-bin table, 4 candidates on 2005-2014 → `step01_exploration_data/` |
| `step02_continuous_replay.ipynb` | Candidate paths, selection, prior-only path, baselines → `step02_continuous_replay_data/` |
| `tests/test_exp05.py` | Synthetic-data tests |

## 14. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Initial protocol (agent, autonomous mode), pre-registered before any run |
| 1.0 | 2026-10-06 | Runs: step 01 (signal check PASS, 4 exploration trials) and step 02 (176 validation + 1 summary). Prior-only +165.69% vs +229.74%, below the constant exposure (+198.52%) and 17 of 20 random shifts: the stopping rule (§9) fires, **STOP**. Recorded defect: step 01's descriptive constant-exposure column is invalid (initial weight 1 at the first session of the data); step 02 unaffected. Observed: the 20-point band makes the constant baseline a buy-and-hold of 86% (docs/RESULTS_LOG.md). No new version |
