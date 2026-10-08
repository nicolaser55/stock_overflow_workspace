# exp06_capped_regret_reentry: Protocol (exit signal + buy-stop; DATA-DEPENDENT FOLLOW-UP of exp03)

*Version 1.0 (2026-10-06). Experiment name `exp06_capped_regret_reentry`. Config:
`experiments/exp06_capped_regret_reentry/config.py` + `so/config.py`. Written by the agent in autonomous mode (Nicolas,
2026-10-06) from the roadmap of `docs/RESEARCH_STATE_2026-10-06.md` §6, and committed (message `preregister exp06`)
before any run of this experiment. After the first `validation_only` run of step 02, any change of a rule, grid,
selection rule or baseline is a new version with a new experiment name.*

**Disclosure (required by the roadmap): this design is a data-dependent follow-up.** It was suggested by exp03's
validation results (2026-10-05): near-ATH exits looked better than random exits (the rule beat 19 of 20), but the
buy-backs were worse than random buy-backs (19 of 20 beat the rule). It is therefore not an independent test: the
2015-2026 data motivated it, and its result must be read with that selection in mind. The agent has also seen exp04's
and exp05's results on the same span before writing this protocol.

---

## 1. Background and research question

exp03 and exp04 lost to buy-and-hold mostly on the buy-back: exp04 bought back higher after all 12 exits (product of
S/R 0.518), exp03's buy-backs were worse than random. A wrong exit is expensive because nothing caps it: if the price
rises after the sale, the strategy waits for a signal while buy-and-hold compounds.

**Question.** Does pairing an exit signal with a **buy-stop** (buy back at once if the close rises b above the sale
price) and a recovery trigger beat buy-and-hold's total return after costs, on one continuous path over the validation
span 2015-04-17 → 2026-04-15?

**Arithmetic that decides success** (roadmap). Each episode multiplies the shares by S/R. With a share q of exits ended
by the buy-stop (wrong exits, each losing about b plus the round-trip costs k) and a mean gain G of the other episodes,
the exits pay only if **(1 − q) × G > q × (b + k)**. The buy-stop caps the loss per wrong exit; it does not make wrong
exits rarer, and every buy-stop re-entry happens at a price above the sale.

## 2. Hypothesis and why it could (and could not) work

- *Could work:* if an exit signal carries some timing information (exp03's exits beat random exits), capping the loss of
  the wrong exits at b + k may leave enough of the gains of the right ones.
- *Could fail (expected):* with frequent signals, many small capped losses accumulate (a buy-stop at +1% costs about 1%
  of the shares every time the market keeps rising). The ATH exit fires in every bull market, so q is likely high. The
  trend exit re-enters on its recovery trigger near the same prices as exp04, so its right exits (G) stay small. A
  cooling-off after a buy-stop re-entry limits the churn but leaves the account exposed to the next decline.
- **Known before writing this protocol (disclosed):** exp03 (+143.05% vs +237.21%, quarterly reset) and exp04
  (+70.84% vs +229.74%, continuous) on the same span, and exp04's scorecard (all 12 buy-backs above the sale, i.e. a
  +1-3% buy-stop would have fired in many of them).

## 3. Success criteria (`so/core/evaluation.py`, `so/core/continuous_replay.py`)

| Level | Criterion |
|---|---|
| **Primary** | Prior-only path total return after costs **above buy-and-hold** over the same sessions |
| Comparable return | ≥ 90% of buy-and-hold's total return |
| Secondary (reported, not the goal) | higher Sharpe **or** smaller maximum drawdown, counted only at a comparable return |
| **Information** | The path must also beat the **median of each random family** of §7 (random exit; random re-entry), and more than half of each family's runs |
| Statistical support | Annualized log excess return, circular block bootstrap of **6-month blocks**: "supported" only if the 95% lower bound > 0 |

A path that passes the primary and information criteria is recorded as a **candidate result pending review**
(research-integrity.mdc, "Never" rule 5), never as success; the data-dependent origin (disclosure above) is one of the
biases listed with it.

## 4. Data

SPY 1-minute IBKR bars, regular hours, unadjusted, bad ticks corrected (3% rule); 2007-07-02 missing. The daily table
(`so.features.daily_features.get_daily_feature_pdf`) is built in memory from the raw bars. Used: `ma200_dist_pct`
(decision close ÷ mean of the previous 200 complete session closes − 1), `ath_drawdown_pct` (decision close ÷ highest
high since 2005-01-03 − 1) and `decision_close`; no look-ahead (tested in `tests/test_exp02.py`, `tests/test_exp04.py`).

- Step 01 (exploration): data cut at `so.config.EXPLORATION_DATA_CUTOFF_DATE_STR` (2015-03-18); replay 2005-01-03 →
  2014-12-31.
- Step 02 (validation): the schedule is built from the full session calendar (the 44 quarters of exp02-exp05), then
  **the bars are cut at the last validation session (2026-04-15)** before any simulation; the replay also refuses any
  window ending on or after 2026-05-14 (`check_replay_window_bool`).

## 5. Rules (`rules.py`)

- **State machine** (`so/core/reentry_simulation.py`, no stop, no forced buy-back): starts INVESTED at the 10:00 open of
  the first session (as buy-and-hold); one decision per session at the 15:58 bar; fills at the 15:59 open with
  $0.01/share slippage and IBKR fixed fees; cash earns 0%; a position open at the end is sold at the last close.
- **Exit signals (2, fixed in advance):**
  - `trend_ma200`: `ma200_dist_pct` < 0 (exp04's textbook rule, x = 0, n = 1: the only exp04 candidate defined before
    any data; exp04's best after the fact, x = 3%, n = 1, is *not* used).
  - `ath_1pct`: `ath_drawdown_pct` ≥ −1% (the middle threshold of exp03's grid; exp03's best after the fact, 0.5%, is
    *not* used).
- **Re-entry** (checked at every cash decision, in this order):
  1. **Buy-stop:** decision close ≥ S × (1 + b), S = the sale fill price → buy back; then the exit signal is ignored for
     the next **c** decisions (cooling-off; `exit_block_sessions`, a backward-compatible option of the simulator).
  2. **Recovery:** decision close above the 200-session average (`ma200_dist_pct` > 0) **and** at least one decision
     close below it from the exit decision on → buy back (no cooling-off). For `trend_ma200` the exit decision is
     already below the average, so this is exactly exp04's re-entry (tested equal).
- **Complete grid (12 candidates):** exit ∈ {`trend_ma200`, `ath_1pct`} × b ∈ {1%, 2%, 3%} × c ∈ {0, 20}, in that order.

## 6. Evaluation design (step 02, continuous replay; `so/core/replay_walk_forward.py`)

- **Periods:** the 44 validation quarters of the exp02-exp05 schedule, made non-overlapping (`get_replay_period_pdf`);
  they tile 2015-04-17 → 2026-04-15.
- **Candidate paths (after the fact, optimistic for the best):** each candidate replayed continuously over all 44
  periods; buy-and-hold over the same span. Period score = candidate period return − buy-and-hold period return. Each
  (candidate, period) is one logged validation trial: **12 × 44 = 528 trials**.
- **Selection:** mean period score over the last 4 periods (`get_pooled_selection_pdf`). Ties: the **longer
  cooling-off, then the smaller buy-stop, then the trend exit** (fewer exits and quicker buy-backs: the choice closest to
  buy-and-hold).
- **Prior-only path (the honest estimate):** the candidate selected at period f governs period f + 1; one continuous
  switching path from period 1's start (2015-07-17) to 2026-04-15 (`get_switching_rule_dict`; the episode in progress
  at a boundary continues under the new period's re-entry rule, with its own sale price). Buy-and-hold over the same span.
- **No test window** is evaluated. A frozen design that passes §3 would be a parked decision for Nicolas.

## 7. Baselines (same simulator, same costs, same span as the prior-only path)

1. **Buy-and-hold.**
2. **Random exit, same re-entry** (20 runs): exit at each invested decision with probability = the path's exits per
   invested decision; re-entry by the path's rule (buy-stop with its cooling-off, recovery). Tests the exit signal.
3. **Random re-entry, same exits** (20 runs): the path's exit signal; re-entry at each cash decision with probability
   1 ÷ the path's mean cash decisions per episode (no buy-stop, no cooling-off). Tests the buy-stop + recovery rule.
4. exp04's textbook rule (`trend_ma200` without a buy-stop) is the benchmark of the family: its continuous result on the
   same span is +108.03% (exp04 candidate 0, after the fact) and its prior-only family result +70.84%.

## 8. Statistics and reporting

- Candidate table: total and annualized return, excess over buy-and-hold, time in the market, exits, buy-stop and
  recovery re-entries, q, G, L, (1 − q) × G vs q × |L|, annualized log excess with its interval, drawdown.
- Prior-only path: total return vs buy-and-hold, annualized returns, **time in the market**, periods won with a one-sided
  sign test, mean / SD / t of the period excess and the **minimum detectable effect**, annualized log excess with the
  6-month-block interval (1-month version alongside), Sharpe, maximum drawdown, the success flags, the information test,
  cost sensitivity at $0.00 / $0.01 / $0.02, the episode scorecard and the trigger arithmetic.
- One **summary** trial-log entry records the prior-only estimate that was seen.
- Multiple testing: report the trials of this experiment together with the 4,089 legacy trials and the 2,615 trials of
  exp01-exp05.

## 9. Stopping rules

- Step 01 (exploration, 2005-2014): context only; it does not change the grid or the selection, and cannot stop the
  experiment.
- Step 02: **STOP** if the prior-only path does not beat buy-and-hold, **or** does not beat the median of both random
  families. Otherwise: candidate result pending review (§3), the biases of §12 listed (the data-dependent origin first),
  the untouched-window evaluation parked for Nicolas.

## 10. Trial budget

Step 01: 12 exploration trials. Step 02: 528 validation trials + 1 summary. **Budget: 545 trials** (one run of each
notebook). A crash half-way is recorded and the notebook re-run once (workflow.mdc).

## 11. Methodological choices (the most conservative option, research-integrity.mdc / workflow.mdc)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| Trend exit | exp04's best (x 3%, n 1), textbook (x 0, n 1) | textbook | Choosing exp04's best would be selection on validation results |
| ATH threshold | 0.5% (exp03's best), 1%, 2% | 1% | Not the after-the-fact best; the middle of exp03's pre-registered grid |
| Recovery trigger | above the average, or volatility below its median | above the 200-session average after a close below it | One trigger, the trend exit's own (exp04 equivalence); the volatility variant would add a grid dimension |
| Forced buy-back | 60, 250, none | none | As exp04; a cap would add an untested parameter |
| Cooling-off applies to | every re-entry, buy-stop re-entries only | buy-stop re-entries only (roadmap) | The roadmap fixes it |
| Tie-break | toward more or fewer exits | longer c, smaller b, trend exit | Closest to buy-and-hold: never favours activity |
| Random re-entry baseline | keep the buy-stop, or none | none (pure random timing) | Tests the whole re-entry rule, as exp03/exp04 |
| Interval | 1-month or longer blocks | 6-month circular blocks (1-month shown) | Long exits make months dependent; wider, less flattering intervals |
| Data cut | full data, cut at the replay end | cut at 2026-04-15 | The simulator cannot read anything later |

## 12. Known limitations and biases

- **Data-dependent origin** (disclosure at the top): the design was suggested by exp03's validation results.
- **Dividends ignored** (favours the strategy while in cash) and **cash at 0%** (penalizes it); both need new data
  (parked decision of 2026-10-06).
- 2015-2026 is development data, seen many times (§2).
- The buy-stop is evaluated on the 15:58 close and filled at the 15:59 open: no intraday stop orders, no gaps modelled
  beyond the minute open.
- The 12 candidates share two exit signals; the selection has little independent choice.

## 13. Implementation

| File | Content |
|---|---|
| `config.py` | Every exp06 constant |
| `rules.py` | Schedule and periods, candidates, exit signals, capped re-entry rule, rule builder, trigger arithmetic |
| `so/core/reentry_simulation.py` | Simulator; the optional cooling-off (`episode_dict["exit_block_sessions"]`, absent = original behaviour, tested) |
| `so/core/continuous_replay.py`, `so/core/replay_walk_forward.py` | Continuous replay, switching, scorecard, candidate paths, prior-only path and baselines (shared) |
| `step01_exploration.ipynb` | 12 candidates on 2005-2014 → `step01_exploration_data/` |
| `step02_continuous_replay.ipynb` | Candidate paths, selection, prior-only path, baselines → `step02_continuous_replay_data/` |
| `tests/test_exp06.py` | Synthetic-data tests (including the simulator's cooling-off) |

## 14. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-06 | Initial protocol (agent, autonomous mode), pre-registered before any run; labelled a data-dependent follow-up of exp03 |
| 1.0 | 2026-10-06 | Runs: step 01 (12 exploration trials) and step 02 (528 validation + 1 summary). Prior-only +147.38% vs +229.74%: the primary criterion fails, the stopping rule (§9) fires, **STOP**, although the information test passed (19/20 random exits, 15/20 random re-entries beaten). No new version (docs/RESULTS_LOG.md) |
| 1.0 | 2026-10-06 | *Correction after the independent audit (`docs/AUDIT_2026-10-06_agent_session.md`, I2), documentation only, no rule changed, no re-run.* The results log called the signals "not pure noise" and said they "carry some timing information". Beating 19 of 20 random exits is an empirical p ≈ (1 + 1) / 21 ≈ 0.10 and beating 15 of 20 random re-entries p ≈ 0.29, for this data-dependent design with 12 candidates, after about 7,400 trials: "consistent with weak timing information; not statistically supported". The information test as defined in §3 (beat both medians) was met; the verdict (STOP) is unchanged |
