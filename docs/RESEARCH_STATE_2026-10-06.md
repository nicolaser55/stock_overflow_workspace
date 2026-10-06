# Research State and Roadmap (2026-10-06)

*The handover document for whoever continues the research (Nicolas, an agent, or the assistant). It says where the
project stands, what has been learned, what data has been seen, and what to do next, in order. Update it at the end of
every working session (section 8) and write a new dated copy when the roadmap changes materially.*

## 1. Goal and success criterion

- **Question:** can a long-only, unlevered strategy on SPY (1-minute IBKR bars, 2005-01-03 → 2026-08-13, bad ticks
  corrected) beat **buy-and-hold's total return** after realistic costs, out of sample?
- **Primary success criterion for the next family (Nicolas, 2026-10-06): beat buy-and-hold's total return** on the
  prior-only (honest) validation path, then on the untouched data (§3) once the design is frozen. The secondary criterion
  (higher Sharpe **or** smaller maximum drawdown at ≥ 90% of buy-and-hold's return) is still reported but is not the goal.
- **Direction of the next family (Nicolas, 2026-10-06):** maximize time in the market; exit only on strong evidence;
  design the re-entry explicitly; holding periods of months or years are fine. Use only the features that already exist
  (TSIND, TSSEG, TSCTX, daily features). Then add VIX, then text/qualitative data.

## 2. What has been learned (details: `docs/RESULTS_LOG.md`)

| Experiment | Idea | Honest result (prior-only path) | Lesson |
|---|---|---|---|
| exp01_minute_entry | LightGBM picks minute entries and an SL/TP distance | +146.94% vs +218.48% | The stop/target machinery plus costs loses ~50 points vs passive exposure; the model recovers ~22. Signal check STOP (p = 0.10) |
| exp02_stop_reentry | Trailing stop; a model decides the buy-back | +111.66% vs +237.21% | The stop is nearly free (stop + next-day buy-back ≈ buy-and-hold); **waiting in cash** loses, and the model waits worse than random |
| exp03_ath_exit | Sell near the all-time high, buy back later | +143.05% vs +237.21% | Selling near the high beats random sell timing (19/20, not significant); the buy-back rules waste it |

Facts that constrain every new design:
1. **Rent of cash:** at ~12% a year, each session in cash costs ~0.045% of expected return (~2.7% per 3 months, ~11% per
   year). An exit pays only if the price **falls** by more than the rent plus costs while out (S/R identity: selling at S
   and buying back at R leaves S/R times the shares).
2. **No directional signal so far:** exp02's daily signal check found 0 of 80 tests passing even on training; exp01's
   minute-level check found 2 bins that do not beat chance (p = 0.10).
3. **Volatility is predictable** (clustering), direction mostly is not: designs that act on turbulence or that bound the
   cost of a wrong exit are more promising than designs that predict direction.
4. **Few events:** 2005-2026 contains only a handful of large declines (2008, 2011, 2015-16, late 2018, 2020, 2022,
   spring 2025). A model cannot learn "confidence" from 6-8 events; long-horizon designs must be simple, pre-registered
   rules, judged episode by episode.

## 3. What data has been seen (contamination record)

| Period | Status |
|---|---|
| 2005-01-03 → 2014-12-31 | Exploration period, explored by exp02 step 01 and exp03 step 01 (and earlier work). Famous events (2008) are known to everyone, including the agent: any result that depends on 2008 is hindsight-prone |
| 2015-04 → 2026-04 (validation quarters) | **Development data**, looked at many times by exp01-exp03 and earlier work (audit F6). Every older test window is inside a later validation quarter |
| **2026-05-14 → 2026-08-13** | The latest test window: **never read by any experiment. Untouched. Protect it** |
| After 2026-08-13 | Future data: the final confirmation of a frozen design (paper trading / forward test) |

## 4. Known biases of the current simulator (must be fixed before any success claim)

1. **Dividends are ignored.** SPY paid roughly 1.3-2% a year. Buy-and-hold is understated, and a strategy that sits in
   cash is not charged for the dividends it misses. For strategies that exit for months, this **favours the strategy**.
2. **Cash earns 0%.** T-bills paid up to ~5% in 2023-2025. This **penalizes** time in cash.
3. Both need external data (SPY dividend history; a T-bill rate series): **Nicolas must supply or approve the source**.
   Until then, report results with the bias stated, and do not claim criterion (a) as met.
4. Costs are informal (slippage $0.01/share per side, IBKR fixed fees); overnight gaps can fill stops and buy-stops worse.

## 5. Shared infrastructure available (`so/`)

- `so.core.reentry_simulation`: invested/cash state machine over **one window** (starts invested, state not carried,
  forced buy-back after `max_cash_sessions_in`), trailing stops, re-entry rule builders (model, fixed delay, random,
  oracle), trend rule, buy-and-hold.
- `experiments/exp03_ath_exit/rules.py`: exit-signal + buy-back simulation on top of it, random exit / random buy-back.
- `so.core.schedule`: walk-forward folds; `so.core.evaluation`: pooled selection, prior-only path, MDE, baseline
  summaries, chained daily returns, monthly bootstrap, success criteria; `so.core.trial_log`: the shared trial log.
- `so.features.daily_features`: 16 daily features at the 15:58 decision bar (returns 1-250d, MA50/MA200 distance,
  realized volatility, volatility ratio 20/60, distances to 60/250-day and all-time highs, sessions since 60-day high).
- Pipeline steps 00-06: minute-level features (TSIND, TSSEG, TSCTX) and targets (TSBAR) per day.

## 6. Roadmap (in order)

Numbering: the VIX experiment, planned as exp04 on 2026-10-05, moves after this family.

### Step 0: evaluation for long holding periods (shared code, no trials)
- **Continuous replay:** one path from the first validation session (2015-04-17) to the last validation session
  (2026-04-15); the position **carries across quarters**; no forced buy-back, or a long optional cap (e.g. 250 sessions).
  Rule parameters, if selected, use only data before each decision (expanding window or the pooled rule of exp02).
- **Episode scorecard:** for every exit: sale date and fill S, buy-back date and fill R, S/R, sessions out, reason,
  buy-and-hold return over the same sessions, drawdown avoided, cost paid.
- **Readable statistics:** annualized log excess return with a block-bootstrap interval (monthly blocks); quarters won;
  the prior-only path when a selection exists; time in the market.
- **Fractional exposure** (for exp05): hold w ∈ [0, 1] of the account; rebalance only when |Δw| exceeds a dead band.
- Tests on synthetic data: continuous replay with no exits equals buy-and-hold over the whole span; state carries across
  a quarter boundary; scorecard S/R equals the share ratio; fractional w = 1 equals buy-and-hold, w = 0 equals cash.
- Keep `simulate_stop_reentry_dict` and all exp01-exp03 numbers unchanged (reproduction checks must still pass).

### exp04_trend_exit (benchmark of the family)
- Sell when the 15:58 close is more than *x* below the 200-session average for *n* consecutive decisions; buy back when
  it is above the average by *x* (symmetric). Grid *x* ∈ {0, 3%, 5%} × *n* ∈ {1, 5, 10} (9 candidates).
- Baselines: buy-and-hold; random exit with the same exit frequency and the same re-entry; random re-entry with the same
  exits; `trend_ma200` (x = 0, n = 1) is inside the grid.
- Known: 2005-2014 +50.4% vs +69.0% (drawdown −23% vs −56%); 2015-2026 quarters +106% vs +237% (V-shaped crashes).
  Expected to fail criterion (a); it is the benchmark every later design must beat.

### exp05_vol_scaled_exposure
- First a **volatility signal check** (predict next-20-session realized volatility from current volatility features):
  expected to pass easily; if it does not, check the pipeline.
- Exposure w = min(1, max(floor, σ_target / σ̂)), σ̂ from existing volatility features; floors {30%, 50%} × targets
  {the training median, 75th percentile of realized volatility} (+ dead band 20 points): about 4-6 candidates.
- Baselines: buy-and-hold; constant exposure equal to the strategy's mean exposure (the uninformed version); random
  exposure path with the same distribution.
- Can beat buy-and-hold only if high-volatility periods have below-average returns (the "leverage effect"); without
  leverage it cannot exceed w = 1.

### exp06_capped_regret_reentry
- Any exit signal (exp04's trend exit; exp03's near-ATH exit) paired with a **buy-stop**: if the close rises to
  S × (1 + b), buy back at once (the cost of a wrong exit is capped near b + costs). If the price falls, buy back on a
  recovery trigger (back above the 200-session average, or volatility back below its median). A cooling-off period of
  *c* sessions after a buy-stop re-entry. Grid b ∈ {1%, 2%, 3%} × c ∈ {0, 20} on two exit signals (~12 candidates).
- Arithmetic: with a share q of wrong exits, mean gain G when right and cost c per round trip, exits pay if
  (1 − q) × G > q × (b + c).
- Baselines: same exits with random re-entry; random exits with the same re-entry rule; buy-and-hold.
- **Disclosure required:** this design was suggested by exp03's results (exit timing looked better than random, the
  buy-back worse); it is a data-dependent follow-up and must be labelled so.

### exp07_warning_lights_exit
- Exit only when at least *k* of these are true at the decision: close below the 200-session average; 250-session return
  < 0; `volatility_ratio_20_60` > 1.2; more than 10% below the all-time high; 60-session high more than 20 sessions old.
  Re-entry when fewer than k − 1 are true, or by exp06's buy-stop. k ∈ {3, 4, 5} (3 candidates; thresholds fixed in the
  protocol, never fitted).
- Expect 3-8 exits in 21 years: the episode scorecard is the evidence; say so.

### Then: VIX (new data, needs Nicolas)
- Data: VIX daily (closes at 16:15 ET, after the 15:58 decision: use the previous day's close or intraday values) and
  VIX3M (from 2007-12-04). Re-run exp05 with VIX as σ̂; add a VIX light to exp07; then a **meta-labeling** model that
  only filters exits proposed by exp04/exp07 (target: did the exit beat the rent of cash).

### Then: text / qualitative data (new data, needs Nicolas)

## 7. Open items

1. Confirm that the first run of exp01 step 02 (notebook at git tag `first-run-20261006`) shows `test_count 5628`,
   `train_pass_count 174`, `signal_count 4` (the re-run's real-check numbers). Record the result in `docs/RESULTS_LOG.md`.
2. Reporting improvement (Step 0): replace the total-return bootstrap interval with an annualized log-excess interval.
3. Dividends and cash yield (§4): ask Nicolas for the data sources before exp04's first validation run, or run with the
   bias stated.
4. Commit executed notebooks of every run with their outputs; snapshot the trial log into `records/` after each session.

## 8. Session log (append one line per working session)

| Date | Who | What was done | Next step |
|---|---|---|---|
| 2026-10-06 | Nicolas + assistant | exp01-exp03 re-run and stopped; results logged; roadmap of the "stay invested" family; Cursor agent set up | Step 0 plan, for Nicolas's review |
