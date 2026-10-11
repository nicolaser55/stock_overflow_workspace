# exp13_e1m1_robustness: Protocol (a DATA-DEPENDENT robustness study of exp12's E1M1)

*Version 1.0 (2026-10-09). Experiment name `exp13_e1m1_robustness`. Config: `experiments/exp13_e1m1_robustness/config.py`
+ `so/config.py` (the exp12 and VIX constants that define the frozen E1M1 are assigned to the experiment config, so the
hash covers them). Decided by Nicolas on 2026-10-09; written by the agent in autonomous mode and committed (message
`preregister exp13`) before any run of this experiment. No new version, variant or rule may follow from its results.*

---

## 1. Why this exists (disclosure)

- **This study is DATA-DEPENDENT.** E1M1 was chosen **after the fact**: it is the best of exp12's six candidates on
  2015-04-17 → 2026-04-15 (exp12 step 02, labelled optimistic, best of 6): **+314.80% vs buy-and-hold +235.39%**, annualized
  log excess +1.92%/yr with a 6-month-block interval [−1.13%, +6.03%], 35 exits, 94.0% in the market. exp12's honest
  prior-only path made **+119.24% vs +229.74%** and exp12 STOPPED by its §8.
- **Nicolas explicitly overrides** exp12's commitment that it was "the LAST VIX re-entry test; no later version may be
  motivated by its results" (decided and attributed to Nicolas on 2026-10-09; recorded in exp12's PROTOCOL change log, its
  results-log entry and `docs/RESEARCH_STATE_2026-10-09.md`).
- **Nothing in this study can turn E1M1's result into out-of-sample evidence.** 2015-2026 is development data reused here
  for the **ninth** time, and 2005-2014 was explored by earlier experiments (exp04-exp07 step 01, exp08's signal checks).
  The study can only show that E1M1 is **ROBUST** (its after-the-fact edge survives perturbations, an earlier period, a
  selection-aware placebo and execution stress) or **FRAGILE**. Every result of this experiment says so.
- **Hindsight:** the rule was written by people who know the 2008, 2018, 2020, 2022 and 2025 declines and their VIX
  peaks; the 2007-2009 stress window is the best-known bear market of the data.
- **No prior-only path exists in this study:** every path is one continuous replay of a fixed rule with no selection
  between periods.
- Nicolas's decisions (2026-10-09): no new data (no pre-2005 history, no other markets, no dividends or T-bill data); the
  untouched window 2026-05-14 → 2026-08-13 stays reserved (never read, never proposed for evaluation); scope = E1M1
  robustness only (no new strategy families, no new rules beyond the neighbourhood of §4 step 02).

## 2. Question and what decides it

*Question:* is E1M1's after-the-fact edge over buy-and-hold on 2015-2026 robust (an earlier period, a parameter
neighbourhood, a selection-aware VIX placebo, execution delay and costs, the removal of its best episode), or fragile?

*The identity:* an episode that sells at S and buys back at R ends with S / R times the shares; final equity /
buy-and-hold ≈ Π S / R over the episodes (costs and cash residues aside). E1M1 beats buy-and-hold only if its M1
re-entries move R below S often and by enough.

*Verdict:* the pre-registered rule of §8, applied once after step 04. Neither verdict is a success claim.

## 3. Data and spans

- **SPY:** IBKR 1-minute bars, daily table from `so.features.daily_features` (decision bar = second-to-last bar of each
  session; fill = open of the last bar). The 150- and 250-session average distances of step 02 are computed exactly as
  `ma200_dist_pct` (decision close / mean of the previous n complete session closes − 1, rounded to 10 decimals;
  `robustness.get_ma_dist_arr`, tested to equal `ma200_dist_pct` exactly at n = 200).
- **VIX / VIX3M:** IBKR daily bars of `store01_rawzone/ibkr_vix_family/` (approved 2026-10-08), read only through
  `so.features.vix_features.get_vix_daily_feature_dict`, variant `"prev"` (the previous session's daily close), with the
  loader cutoff equal to the SPY cut of the notebook (the loader refuses 2026-05-14 and later).
- **DEV** = 2015-04-17 → 2026-04-15, exp12's candidate span: its 44 replay periods are read (dates only) from exp12's saved
  `step02_continuous_replay_data/replay_period_data.csv` and `fold_schedule_data.csv` (asserted: 44 periods, the bounds,
  the latest test start 2026-05-14, never read). SPY and VIX are cut at **2026-04-15** before any computation, so no bar of
  2026-04-16 or later is read (exp12 loaded the calendar to build its schedule; exp13 does not need to).
- **STRESS** = from the first session on or after 2005-10-04 where both the 200-session average distance and
  `vix_level_prev` exist → 2014-12-31. SPY and VIX cut at **2015-03-18** (`so.config.EXPLORATION_DATA_CUTOFF_DATE_STR`):
  nothing of 2015-2026 is read in step 01, nor in the STRESS paths of step 02. Before the first 150- or 250-session
  average exists the variant is invested (a NaN distance never signals an exit).
- **Every notebook prints and asserts the last SPY, VIX and VIX3M dates loaded** (≤ the cutoff, and equal to it on the
  real data).
- **Reproduction asserts first in every DEV notebook** (steps 02-04): frozen E1M1 = +314.80% with 35 exits; unmodified E1 =
  +108.03% with 35 exits; buy-and-hold = +235.39% (percent to 2 decimals, exact exit counts). Step 01 asserts exp12 step
  01 on 2009-08-13 → 2014-12-31: E1M1 +104.51%, E1 +49.00%, buy-and-hold +104.57%. **If any differs: stop, record, park.**

## 4. The frozen rule and the steps

**E1M1 is FROZEN exactly as exp12 implemented it** (`experiments/exp12_vix_fear_reentry/rules.get_rule_builder_func`,
imported, never re-implemented): E1 = exp04's trend rule with x = 0, n = 1 (exit when the decision close is below the
200-session average, original re-entry when above); M1 = buy back at the first decision after the exit where
`vix_level_prev` ≤ 0.85 × its maximum over the decisions from the exit decision to now (NaN skipped and never true), or
by the original re-entry, whichever comes first (the original rule is checked first and labelled "original" when both
fire); after an M1 re-entry a new exit needs a fresh exit signal. No stop, no forced buy-back, ± $0.01 slippage per share
per side, IBKR fees, cash at 0% (exp12's costs).

**Reported for every path:** total return vs buy-and-hold over the same sessions; annualized log excess with the 6-month
and the 1-month block-bootstrap intervals; time in the market; exits; Sharpe; maximum drawdown; product of S/R.

### Step 01 — stress test on 2005-2014 (`step01_stress_2005_2014.ipynb`, stage `exploration`, 2 trials)
- Frozen E1M1, the unmodified E1 and E2M1 (exp12's code) and buy-and-hold, each one continuous replay starting invested,
  over three windows: **STRESS**; **2007-10-01 → 2009-08-12**; **2009-08-13 → 2014-12-31** (reproduces exp12 step 01, asserted).
- The full E1M1 STRESS scorecard: exit date and fill S, buy-back date and fill R, S/R, sessions out, re-entry reason,
  `vix_level_prev` at the exit, its maximum while out, at the buy-back; for every M1 re-entry SPY's lowest session close
  from the buy-back to the next exit (or the end) and the drawdown from the buy-back price to it.
- Logged: E1M1 and E2M1 (metrics of the three windows in one entry each; window columns = STRESS).

### Step 02 — parameter neighbourhood (`step02_neighbourhood.ipynb`, stage `robustness`, 72 trials; DESCRIPTIVE)
- Grid: fade ratio {0.70, 0.75, 0.80, 0.85, 0.90, 0.95} × average length {150, 200, 250} × fresh-signal rule {on, off} =
  **36 variants** (E1M1 = 0.85 / 200 / on), each over DEV and over STRESS = **72 paths**, all logged.
- Variants: `robustness.get_variant_rule_tuple`, the same structure as exp12's M1 with exp04's and exp12's primitives
  (`get_trend_exit_signal_arr`, `get_trend_reentry_signal_arr`, `get_m1_trigger_bool`); at 0.85 / 200 / on it equals the
  frozen E1M1 trade for trade (tested; asserted in the notebook against the frozen path).
- Reported: two grids of total return minus buy-and-hold (DEV, STRESS); the number of the 36 beating buy-and-hold on DEV,
  on STRESS and on both; E1M1's rank on DEV. **No variant is picked, recommended or carried forward.**

### Step 03 — placebo and information tests on DEV (`step03_placebo.ipynb`, stage `placebo`, 4 trials)
- **P1 (misaligned VIX, single rule):** the VIX feature table is circularly shifted by k = round(u × rows) rows, u ~
  U[0.25, 0.75] with seed `vix_config.NULL_SEED + run` (exp08's convention), over the loaded rows (2005 → 2026-04-15); SPY
  stays in place; the frozen E1M1 is re-run (exp12's rule builder on the shifted table). **999 runs**; p1 = (1 + #runs with
  total return ≥ real) / 1000.
- **P2 (selection-aware; the PRIMARY information statistic):** in the same 999 shifted runs, all six exp12 candidates (E1M1,
  E1M2, E1M3, E2M1, E2M2, E2M3) are run and the **maximum** total return is kept; p2 = (1 + #runs with that maximum ≥ E1M1's
  real +314.80%) / 1000. It asks whether picking the best of six on misaligned VIX data does as well as E1M1 did.
- **P3:** random re-entry after E1M1's own exits (exp04's family: re-entry run i uses `RANDOM_SEED + i`, probability = 1 /
  E1M1's mean cash decisions per episode), 999 runs.
- **P4:** random exits (run i uses `RANDOM_SEED + 1000 + i`, probability = E1M1's exits / invested decisions) with E1M1's
  re-entry rule, 999 runs.
- Each null: median, 5th and 95th percentiles, the real value's rank, p. **Each null is ONE trial entry carrying its run
  count** (4 entries).

### Step 04 — execution and episodes on DEV (`step04_execution_and_episodes.ipynb`, 2 `robustness` + 1 `summary`)
- **E1 delay:** every trade (exit and re-entry) one session late (`robustness.get_delayed_rule_tuple`: the exit signal of
  session t sells at t + 1; the re-entry rule is asked at s about s − 1 with the episode's first cash decision moved back
  by one, so M1's maximum still starts at the original exit decision; tested).
- **E2 costs:** slippage 0 / 1 / 2 / 5 cents per share per side (buy-and-hold also reported at the same slippage).
- **E3 episodes:** Π S/R and final equity / buy-and-hold without the best one and the best two episodes (largest log S/R;
  exp12's `get_concentration_dict`) and whether each still beats buy-and-hold; log excess per calendar year; log excess on
  2015-04-17 → 2020-12-31 and 2021-01-01 → 2026-04-15; the share of the total log excess from the episodes overlapping
  2020-02-01 → 2020-06-30; the split of Π S/R by re-entry reason.
- Logged: the delayed path and the 5-cent path (`robustness`), then one `summary` entry with the verdict.

## 5. Selection

None. Every path is a fixed rule replayed continuously. Nothing in steps 01-04 selects, ranks for use, or modifies a
rule; the step 02 rank is descriptive.

## 6. Baselines

Buy-and-hold over the same sessions (same simulator and costs); the unmodified E1 (what M1 adds); the random families P3
and P4 (uninformed re-entry with the same exits, uninformed exits with the same re-entry); the shifted-VIX nulls P1 and
P2 (the same rules with the VIX information destroyed, and the same best-of-six selection on it).

## 7. Statistics

- 6-month block bootstrap of the annualized log excess (exp12's primary; 1-month reported alongside), `so.core.continuous_replay`.
- Placebo p-values = (1 + #null ≥ real) / (runs + 1), 999 runs each.
- Multiple testing: the conclusion rests on the 4,089 legacy trials, the 3,570 workspace trials before exp13 (exp01-exp12)
  and exp13's 81; and on E1M1 being the best of six after the fact (P2 is the only test that accounts for that choice).

## 8. Verdict rule (pre-registered exactly; applied once, after step 04, by `robustness.get_verdict_dict`)

**"ROBUST CANDIDATE PENDING REVIEW"** only if ALL hold:

| | Criterion |
|---|---|
| R1 | STRESS: frozen E1M1's total return ≥ buy-and-hold's over the STRESS window |
| R2 | ≥ 24 of the 36 variants beat buy-and-hold on DEV **and** ≥ 18 of 36 beat it on STRESS |
| R3 | p2 ≤ 0.05 (selection-aware VIX placebo, step 03) |
| R4 | E1M1 still beats buy-and-hold on DEV without its single best episode (final equity / buy-and-hold ÷ its S/R > 1) |
| R5 | the one-session-delayed E1M1 and the 5-cent-slippage E1M1 each beat buy-and-hold on DEV (buy-and-hold under exp12's costs, +235.39%) |

Otherwise **"E1M1 IS NOT ROBUST"**, listing every criterion with its numbers and which failed. Either way: no success
claim, and no new version or variant.

- **If NOT ROBUST:** the VIX line is closed; park "write-up of the negative result" (recommendation: do it now).
- **If ROBUST:** park "E1M1: forward (paper) test of the frozen rule from new data after 2026-10-07, and/or approval of new
  out-of-sample data (pre-2005 SPY + Cboe VIX history)". The untouched window stays reserved and is not proposed. Listed
  biases: dividends ignored (about 94% invested, small), cash at 0%, informal costs, the after-the-fact choice, the ninth
  reuse of 2015-2026, the total trial count.

## 9. Trial budget

2 exploration + 72 robustness + 4 placebo + 2 robustness + 1 summary = **81 expected, budget 150**. Each notebook asserts
its expected count and the budget before it logs (`robustness.check_step_trial_dict`), and every entry fills the window
columns (`valid_start`, `valid_end`) with its span. A notebook is run once; a crash half-way is recorded with the trials
it logged, and the notebook is re-run once.

## 10. Known limitations and biases

- Everything in §1: after-the-fact choice of E1M1, Nicolas's override of exp12's last-test commitment, the ninth reuse of
  2015-2026, earlier exploration of 2005-2014, hindsight of the 2008, 2018, 2020, 2022 and 2025 declines.
- Robustness is not out-of-sample evidence: a rule fitted to well-known crashes can survive perturbations of itself.
- Few events: 35 exits on DEV; the result rests on a handful of M1 episodes (hence R4 and the concentration reports).
- The IBKR VIX data was not compared with Cboe's official values; VIX3M starts 2009-08-12 (it enters only E1M2 / E2M2 /
  E1M3 / E2M3 in P2).
- Simulator biases: dividends ignored (favours time in cash; small at about 94% invested), cash at 0% (penalizes it),
  informal costs (slippage per share, IBKR fixed fees, no gap model beyond the fill at the open of the last bar).
- P1 / P2 shift the VIX table over the loaded rows (2005 → 2026-04-15), so a shifted DEV session may receive a VIX value
  from 2005-2014 or from later DEV dates: it destroys the alignment, not the VIX's distribution.

## 11. Methodological choices (the most conservative option)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| R5 benchmark | buy-and-hold under exp12's costs / buy-and-hold paying the same slippage | exp12's costs (+235.39%); the same-slippage comparison is reported | Buy-and-hold trades twice; at 5 cents it loses almost nothing, so the stricter benchmark barely differs and does not flatter E1M1 |
| Step 01 windows | one STRESS replay sliced / each window its own replay starting invested | each its own replay | exp12 step 01's convention (needed for its reproduction assert); a slice would inherit a cash state from before the window |
| Variant builder | exp12's builder with patched constants / a parameterized copy of the M1 structure | a parameterized builder from exp04 / exp12 primitives, proved equal to the frozen rule at 0.85 / 200 / on | exp12's builder reads module constants; patching them would risk changing the frozen rule in the same process |
| Missing longer average on STRESS | drop sessions / invested until it exists | invested (NaN never signals) | The same STRESS sessions for every variant against the same buy-and-hold |
| DEV schedule | rebuild from the full calendar (as exp12) / read exp12's saved periods | read exp12's saved dates | No SPY bar after 2026-04-15 is loaded; the dates are asserted |
| P2 candidate set | E1M1 alone / the six modified candidates / the six plus the two unmodified | the six modified candidates | E1M1 was selected from those six; the unmodified exits do not use the VIX |
| Delay | delay the exits only / every trade | every trade | The harsher and more realistic test of a close-to-close decision rule |
| Parallel nulls | sequential / processes (8) | 8 processes, each run seeded by its index | Results are identical for any number of processes (tested: parallel = sequential) |

## 12. Implementation

| File | Content |
|---|---|
| `config.py` | Every constant (frozen rule, spans, reproduction targets, grid, nulls, execution, verdict thresholds, budget) |
| `robustness.py` | Span loads (cut before any computation), DEV periods from exp12, reproduction, frozen / variant / delayed rules, replay and metrics, stress scorecard, placebo runs and summaries, span and reason reports, verdict |
| `step01_stress_2005_2014.ipynb` | Three windows, E1M1 / E1 / E2M1 / buy-and-hold, scorecard (2 trials) |
| `step02_neighbourhood.ipynb` | 36 variants × DEV and STRESS (72 trials) |
| `step03_placebo.ipynb` | P1-P4 with 999 runs each (4 trials) |
| `step04_execution_and_episodes.ipynb` | Delay, costs, episodes, verdict (3 trials) |
| `tests/test_exp13.py` | Config, average distances, variants = frozen, delay, VIX shift, nulls (parallel = sequential), reports, verdict |

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-09 | Initial protocol (agent, autonomous mode, from Nicolas's decision of 2026-10-09), pre-registered before any run (`afe6b42`) |
| 1.0 (result) | 2026-10-09 | Run once (81 trials, as expected). Verdict **E1M1 IS NOT ROBUST** (R1 STRESS, R2 PLATEAU, R3 INFORMATION, R4 EPISODES fail; R5 EXECUTION holds). The VIX line is closed. No new version. Details: `docs/RESULTS_LOG.md`, exp13 |
