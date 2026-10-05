# exp01_minute_entry: Protocol

*Version 1.0 (2026-10-05). Experiment name `exp01_minute_entry`. Config: `experiments/exp01_minute_entry/config.py` +
`so/config.py`. This is protocol v1 (`docs/history/RESEARCH_PROTOCOL_v1.md`, experiments `signal_check_v1` /
`lgbm_ev_policy_v1`, stopped on 2026-10-04) re-run in the reorganized workspace. **The trading rules, targets, features,
model, policy, schedule and selection are unchanged**; the changes decided by Nicolas on 2026-10-05 concern the signal
check and the reporting (§17). After the first `validation_only` run of step 03, any rule change is a new version with a
new experiment name.*

---

## 1. Research question

Can a model trained on SPY's own minute-level price action, technical indicators and market context:

- pick **long entries**,
- **and an SL/TP distance for each entry**,

so that, **after realistic costs, its total return beats buy-and-hold over the same period**, out of sample?

The original aim ("TP reached substantially more often than SL") is tested in its meaningful form by the signal check: the
TP rate **after a signal** must exceed the **unconditional** TP rate at the same distance (the base rate), because a high TP
rate alone can be obtained without skill (audit §4). The qualitative (text) part of the original hypothesis is deferred.

## 2. Success definition

| | Definition |
|---|---|
| **Primary metric** | Total return after all costs vs buy-and-hold over the same span (`excess_return = total_return − buy_hold_return`) |
| **Secondary metrics** | Annualized Sharpe ratio (daily mark-to-market, risk-free 0) and maximum drawdown, at a comparable return (≥ 90% of buy-and-hold's) |
| **Information** | The model must beat the random-entry baseline of matched activity (§11) |
| **Diagnostics** | Trades, TP/SL/TL rates, WIN/LOSS/NULL counts, exposure, decisions skipped while a position was open |
| **Benchmark** | Buy-and-hold: buy at the first allowed entry (10:00 open), sell at the last close (or at the strategy's last exit if later), same slippage and fees |

Dividends are ignored (favours time in cash); cash earns 0%.

## 3. Data

SPY 1-minute bars from IBKR, regular hours, 2005-01-03 onward, unadjusted, bad ticks corrected by the 3% rule. Pipeline
steps 00-05 (kept, see `pipeline/README.md`) provide the features (TSIND, TSSEG, TSCTX) and targets (TSBAR).

## 4. Decision and execution rules (`so/core/trade_execution.py`, `so/core/backtest_simulation.py`)

1. **Decision:** the feature row of bar t (every feature uses only bars ≤ t: snapshot design, tested).
2. **Entry:** the open of bar t+1 in the same session; first entry 10:00 (decision 09:59), last entry 15:59 (decision 15:58).
3. **Barriers:** TP = open·(1+d), SL = open·(1−d·rr), rr = 1, rounded to $0.001; active from the bar after the entry.
4. **Exit on each active bar, in this order:** open ≤ SL → exit at the open (SL); open ≥ TP + 1 tick → exit at the open (TP);
   low reaches SL → exit at SL (SL wins if TP is also hit); high reaches TP + 1 tick → exit at TP.
5. **Holding limit:** 10 trading days (entry day = day 1); time-limit exit at the close of the last bar of day 10.
6. **One position at a time**; buy decisions made while a position is open are skipped.
7. **Sizing:** the whole account in every trade, compounding.

## 5. Costs (`so/config.py`)

Entry +$0.01/share; SL, time-limit and end exits −$0.01/share; TP limit exits no slippage; IBKR fixed fees $0.005/share,
min $1, max 1% per side; sensitivity $0.00 / $0.01 / $0.02. Informal assumptions, not measured fills.

## 6. Target (pipeline step 05, TSBAR)

One row per decision bar and one cell per SL/TP distance (`exit_bar_count|exit_price|exit_reason`, reason TP/SL/TL/NA).
32 distances 0.05%–2.00%; the 21 distances 0.10%–1.00% are modelled (`MODEL_DELTA_LIST`). `y_tp` = 1 for TP, 0 for SL or
TL; NA rows excluded. `net_return` is computed with §5 when the dataset is read.

## 7. Features

TSIND (43 fields), TSSEG, TSCTX, registered with a scale type in `so.config.FEATURE_REGISTRY_DICT`. Absolute-dollar
features are excluded from the model (they encode the price level, i.e. the year). Constants keep their original values.

## 8. Sampling and weights

Training rows every 15 minutes from 10:00 (`SAMPLING_MODE = "interval"`), uniqueness weights. Validation and test simulate
**every** eligible minute.

## 9. Splits and walk-forward (`so/core/schedule.py`, `walk_forward.py`)

```
|---- train (L years) ----| 10 sessions |-- validation (3 months) --| 10 sessions |-- test (3 months) --|
```

Anchored on the last session, stepping back 3 months; embargo 10 sessions (≥ the holding limit); about 45 folds.
L ∈ {3, 5, 10} years and the expected-return threshold ∈ {0, 0.02%, 0.05%, 0.10%} are selected by the validation total
return of the quarter (ties: shorter L, higher threshold). Test: refit on the L years ending at the validation end,
evaluated once.

## 10. Model and decision policy (proposal, never formally agreed)

One LightGBM classifier per distance predicting P(TP first). At each eligible minute: expected net return of every distance
from P(TP) and the decision bar's close (time-limit exits counted as losses), best distance, buy if above the threshold.

## 11. Baselines (same simulator, same costs)

1. Buy-and-hold over the same span.
2. **Random entry:** 20 runs; each eligible minute buys with the model's buy rate, at a distance drawn from the model's
   chosen distances (matched activity).
3. **Fixed time:** buy at the 10:00 open every session when flat, with a 0.50% distance.

## 12. Statistics and reporting (honest reporting added 2026-10-05)

- **Every candidate chained** over the validation quarters (after the fact: optimistic for the best one), with exposure and
  the **zero-skill reference** (1 + buy-and-hold)^exposure − 1: what a strategy without skill, invested that share of the
  time, is expected to return (audit F3).
- **Prior-only path:** the setting selected at fold f − 1, with its decisions on fold f's validation quarter, together with
  the baselines of §11 on the same quarter (the information test); chained return vs buy-and-hold, quarters won with a
  one-sided sign test, mean/SD/t of the quarterly excess return and the **minimum detectable effect**, mean exposure.
  Positions can extend past a quarter's end (up to 10 sessions), so the path is summarized per quarter (no daily bootstrap).
- **Per test window** (test modes only): model and baseline metrics, the model's percentile among the random runs, cost
  sensitivity; across folds: chained returns, folds beating buy-and-hold with a sign test, Sharpe, worst drawdown, trades.
- One **summary** trial-log entry per walk-forward run records the prior-only estimate that was seen.

## 13. Stopping rules

1. **Signal check (step 02), base-rate version.**
   - Windows: training = the 10-year window of the 4th most recent fold; validation = the 4 most recent validation quarters
     pooled (all after that training window; they were test windows of older folds). The latest test window is not read.
   - Per (feature, distance): 10 quantile bins (edges from training; one bin per level for categoricals). Per bin: TP rate
     with a block-bootstrap interval (whole ISO weeks), the window's **base rate** (unconditional TP rate at that distance),
     the break-even TP rate, the number of distinct months.
   - A bin is tested if it has ≥ 200 training rows and covers ≥ 6 calendar months in training; its validation pass counts
     only if it covers ≥ 6 months in the pooled validation.
   - **Two-sided:** a bin is a signal if its interval lies entirely above (or entirely below) the base rate on training and
     on validation, on the same side. Signals above the base rate whose validation lower bound is also above break-even are
     counted separately (tradable after costs).
   - **STOP or pivot if no bin is a signal.** The report gives the training passes expected by chance (5% of the tests),
     the **signals expected by chance** (tests × 2 × 2.5%², assuming independent tests and windows) and the number of
     distinct feature bins among the signals (one bin usually passes at several neighbouring distances).
   - *Calibration warning (found 2026-10-05, before any real run).* With about 3,000 tests the chance count is about 4,
     so "at least one signal" is a weak bar: in the assistant's smoke run on a synthetic random walk (no signal by
     construction), the check found 2 signals (one bin of `prev_day_range_pct` at 0.89% and 1.00%) and returned CONTINUE.
     The tests are strongly correlated (the 21 distances share the same bins), so the realized count is clumpy and the
     chance count is only a guide. **A CONTINUE whose signal count is not clearly above the chance count is not evidence of
     a signal.** Whether to tighten the rule (e.g. require more signal bins than expected by chance, or a null run with
     shuffled weeks) is open for Nicolas to decide **before** the first real run of step 02.
2. **Walk-forward (step 03).** On validation: STOP if the prior-only path fails to beat buy-and-hold and the random-entry
   baseline. On test (after freezing): the success definition of §2.

## 14. Discipline against luck and leakage

- Shared trial log; experiment `exp01_minute_entry`; hash covers `so/config.py` + this `config.py`.
- `validation_only` until the design is frozen; any change after the first validation run = new version.
- Look-ahead tests (`tests/test_shared_and_exp01.py`): context features identical on truncated data; target cells equal
  simulated trades; embargo gaps; snapshot k contains bars 0..k only; drift-only data is not a signal; month minimum.

## 15. Implementation

| Step / file | Content |
|---|---|
| `config.py` | Every exp01 constant |
| `model_dataset.py`, `step01_model_dataset.ipynb` | Join of pipeline features and targets per day → `step01_model_dataset_data/` |
| `signal_check.py`, `step02_signal_check.ipynb` | Base-rate signal check → `step02_signal_check_data/` |
| `walk_forward.py`, `step03_walk_forward.ipynb` | Model, policy, fold runner, baselines, prior-only path, test → `step03_walk_forward_data/` |

## 16. Known limitations

Dividends ignored; costs informal; break-even assumes exits at the barriers; per-share fee in labels assumes ≥ 200 shares
(the simulator uses exact fees); SL/TP rounded to $0.001 while prices move in $0.01; absolute features excluded; the
price-action constants were chosen visually; the 3% bad tick rule leaves smaller wicks that can trigger small SL distances;
ex-dividend overnight drops trigger small SL distances on overnight holds.

## 17. Change log

| Version | Date | Change |
|---|---|---|
| (v1 1 – 1.2) | 2026-10-01 → 10-04 | Protocol v1 (`signal_check_v1`, `lgbm_ev_policy_v1`, `*_clean`): see `docs/history/RESEARCH_PROTOCOL_v1.md` |
| 1.0 | 2026-10-05 | Re-run in the reorganized workspace as `exp01_minute_entry`. Trading rules, targets, features, model, policy, schedule and selection unchanged. Changed (decided by Nicolas, 2026-10-05): the signal check compares bins with the window's **base rate** instead of the break-even rate, is two-sided, pools the 4 most recent validation quarters (training = the 10-year window of the first pooled fold) and requires ≥ 6 months per bin in each window; the verdict also reports the signals expected by chance and the distinct signal bins (reporting only); honest reporting of §12 (prior-only path with baselines on validation, exposure and the zero-skill reference, MDE, summary trial entry) |
