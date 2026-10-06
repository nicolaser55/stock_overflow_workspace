# exp02_stop_reentry: Protocol

*Version 1.0 (2026-10-05). Experiment name `exp02_stop_reentry`. Config: `experiments/exp02_stop_reentry/config.py` +
`so/config.py`. This is protocol v2 (`docs/history/RESEARCH_PROTOCOL_v2.md`, experiment `stop_reentry_v2`, stopped on
2026-10-04) re-run in the reorganized workspace. **The trading rules are unchanged**; the changes decided by Nicolas on
2026-10-05 concern the signal check and the reporting only (§16). After the first `validation_only` run of step 03, any
rule change is a new version with a new experiment name.*

---

## 1. Background

v1 (now exp01) picked minute-level long entries with a symmetric SL/TP; no setting beat buy-and-hold on validation. A
long-only, unleveraged strategy cannot hold more than 100% of SPY, so it can beat buy-and-hold only by being **out of the
market during declines and back in before the recovery**. This experiment tests exactly that.

The first run (stop_reentry_v2, 2026-10-04, re-run on corrected data as stop_reentry_v2_clean) was stopped: the mechanism
check showed that stops sell into dips that revert, the signal check found 0 signals, and no candidate beat buy-and-hold on
validation (prior-only selection +112% vs +237%). This version re-runs it in a clean workspace with the reporting of §12.

## 2. Research question

Starting from a fully invested position in SPY:

- an **exit based on a calculated risk tolerance** (a volatility-scaled trailing stop),
- combined with a **re-entry decision based on information** (a model of SPY's 20-session forward return),

can these produce a **higher total return after costs than buy-and-hold** over the same period, out of sample?

**How the strategy can beat buy-and-hold.** While invested, the strategy *is* buy-and-hold. The difference comes only from
the out-of-market episodes. An episode that sells at price S and buys back at price R ends with S ÷ R times the shares it
had, before costs. The strategy wins exactly when, on average, it **buys back lower than it sold**.

## 3. Success criteria (`so/core/evaluation.py`)

| Level | Criterion |
|---|---|
| **Primary** | Total return after all costs, chained over the evaluated windows, **above buy-and-hold** over the same windows |
| **Secondary** (counted only at comparable return) | A **higher Sharpe ratio** or a **smaller maximum drawdown** than buy-and-hold, on the chained daily returns |
| **Comparable return** | Strategy total return ≥ 90% of buy-and-hold's. If buy-and-hold is negative: ≥ buy-and-hold − 10% × \|buy-and-hold\| |
| **Information** | The strategy must also beat the same-stop baselines of §10 (fixed-delay and random re-entry). Otherwise the stop rule, not the model, does the work |

The two secondary flags are reported separately, and `secondary_success` is true if **either** holds (decided by Nicolas,
2026-10-05; audit F7).

**Statistical support.** A block-bootstrap interval of the chained excess return over buy-and-hold, resampling calendar
months. "Statistically supported" only if the lower bound of the 95% interval is above 0; otherwise "observed, not
statistically supported". The minimum detectable effect (§12) shows how large an edge would have to be to be detected.

**Metrics:** Sharpe ratio annualized from daily returns, risk-free rate 0; maximum drawdown of the daily equity.

## 4. Data

SPY 1-minute bars from IBKR, regular hours, 2005-01-03 to the latest session, unadjusted, bad ticks corrected by the 3%
rule (`records/bad_tick_corrections.csv`). 2007-07-02 is missing; 2009-07-27 and 2013-12-23 are partial sessions.
Previous sessions are the sessions present in the data. exp02 reads the raw bars only (pipeline steps 01-05 not needed).

## 5. Strategy rules (`so/core/reentry_simulation.py`)

- **State.** INVESTED (all-in SPY) or CASH. Cash earns 0%. One position at a time; the account compounds.
- **Daily decision.** Once per session, on the 15:58 bar (the second-to-last bar on half days). A trade decided there fills
  at the open of the next bar (15:59) plus slippage.
- **Start of each evaluated window.** INVESTED from the first allowed entry of the window's first session (the 10:00 open),
  the same entry as buy-and-hold. A position still open at the window's end is sold at the last close with exit costs, as
  buy-and-hold is. No entry is made at the last session's decision. The state is **not** carried between windows.
- **Exit: trailing stop, checked intraday on every minute bar.**
  - σ = `daily_volatility` of the session: the standard deviation of the previous 20 daily close-to-close returns.
  - Stop for bar j = max(previous stop, highest minute close since the entry up to bar j−1 × (1 − k·σ)). The stop only
    moves up and is active from the bar after the entry.
  - k ∈ **{3, 4, 5}** (`STOP_K_LIST`), selected on validation (§9).
  - A bar opening at or below the stop exits at its open (gap); otherwise a low at or below the stop exits at the stop.
    −$0.01 slippage per share and IBKR fees apply. No take profit, no time limit.
- **Re-entry: information.** At each decision while in CASH (including the decision of the session in which the stop was
  hit, if the stop was hit at or before the decision bar), the model gives P = P(net 20-session forward return > 0) (§6).
  The strategy buys at the 15:59 open if P ≥ p\*, with **p\* = training base rate + offset**, offset ∈ **{−0.05, 0, +0.05}**.
- **Forced re-entry** after 60 decisions in CASH (`MAX_CASH_SESSIONS`), whatever the model says; counted separately.

## 6. Target (`so/features/daily_features.py`, pipeline step 06)

- One row per session, evaluated at the decision bar.
- y = 1 if buying at the 15:59 open (+$0.01) and selling at the close of the last bar of session t+20 (−$0.01) is
  profitable after the per-share fees; 0 otherwise. The last 20 sessions are unresolved (NaN).
- Training rows: all sessions with every feature and a label (not only cash days): a known distribution shift.
- Labels overlap heavily; rows are not weighted; intervals use a monthly block bootstrap.

## 7. Features (`so.config.DAILY_FEATURE_COL_STR_LIST`)

16 scale-free features, each using only bars up to the decision bar and complete previous sessions (tested):
`prev_day_return_pct`, `prev_day_range_pct`, `intraday_return_pct`, `daily_volatility`, `ath_drawdown_pct`,
`return_5d/20d/60d/120d/250d`, `ma50_dist_pct`, `ma200_dist_pct`, `volatility_ratio_20_60`, `high60_dist_pct`,
`high250_dist_pct`, `sessions_since_high60`.

## 8. Model (`walk_forward.py`)

- **Primary:** logistic regression on standardized features, L2 (C = 0.1).
- **Diagnostic:** shallow LightGBM (depth 2, 4 leaves, 200 trees, learning rate 0.02, ≥ 100 rows per leaf); its
  validation AUC is reported, it is never used for decisions.

## 9. Walk-forward and selection (step 03)

- 3-month validation and test windows anchored on the latest session, stepping back 3 months (`so/core/schedule.py`).
- **Embargo: 20 sessions** (the label horizon) between training, validation and test: **44 folds**.
- **Training windows:** 10 years, or all sessions since the start of the data.
- **Candidates per fold:** 2 windows × 3 k × 3 offsets = **18**, each logged as a trial.
- **Selection:** mean validation excess return over the last 4 validation quarters (this fold and the 3 before it).
  Ties: larger k, higher offset, then the 10-year window.
- **Refit and test** (run modes `latest` / `history` only): the selected candidate is refit on its window ending at the
  validation end and evaluated once on the test window.

## 10. Baselines (same simulator, same costs)

1. Buy-and-hold over the same window.
2. Same stop + **fixed-delay** re-entry at the 1st, 5th or 20th cash decision.
3. Same stop + **random** re-entry: 20 runs, re-entering at each cash decision with probability 1 ÷ (the model's mean cash
   decisions per episode; every episode is used when none closed with a re-entry). If the model never left the market in
   the window, every run equals the model.
4. The **200-session moving-average rule** (no stop, no forced re-entry), trading at the 15:59 open.

## 11. Stopping rules

1. **Daily signal check (step 02), before any walk-forward result of this version.** Training = the 10-year window of the
   4th most recent fold; validation = the 4 most recent validation quarters pooled. 5 quantile bins per feature (edges from
   training); per bin, the rate of positive 20-session returns vs the window's base rate, monthly block bootstrap.
   **Two-sided**; a bin's pass counts only if its rows cover **≥ 6 calendar months in each window** (new). STOP or pivot
   if no bin is a signal on the same side in both windows. The pooled validation quarters were test windows of older folds.
2. **Mechanism check (step 01, exploration 2005-2014).** Stop + fixed-delay and oracle re-entry for each k, the 200-session
   rule, and the post-exit path (mean log share gain of re-entering n decisions after each stop, vs the drift reference).
   Informs the design; not an automatic STOP.
3. **Walk-forward (step 03).** On validation: STOP if the prior-only path (§12) fails to beat buy-and-hold and the
   fixed-delay baselines. On test (after freezing): the success criteria of §3.

## 12. Reporting (`so/core/evaluation.py`; honest reporting added 2026-10-05)

- **Every candidate chained** over the validation quarters, with quarters won, time in cash, stops, mean share gain, and the
  mean validation AUC of both models (after the fact: optimistic for the best candidate).
- **Prior-only path** (the honest validation estimate): the candidate selected at fold f is re-simulated on the validation
  quarter of fold f + 1, together with every baseline of §10 on the same quarter (`run_window_with_baseline_dict`, window
  "valid"); the re-simulation must equal the logged candidate. Reported: chained return vs buy-and-hold, quarters won with a
  one-sided sign test, mean and SD of the quarterly excess return, its t statistic and **minimum detectable effect**
  (2.8 × SD / √n per quarter, ×4 per year), mean time in cash, the success criteria and the monthly bootstrap interval, and
  the information test (model vs each baseline; share of random runs beaten).
- **Per test window** (test modes only): metrics of the strategy and of every baseline, stops, re-entries, cash share, cost
  sensitivity at $0.00 / $0.01 / $0.02, the model's percentile among random runs; chained statistics across windows.
- One **summary** trial-log entry per walk-forward run records the prior-only estimate that was seen.

## 13. Discipline against luck and leakage

- Shared trial log `store04_experiments/trial_log.csv`; experiment `exp02_stop_reentry`; the hash covers `so/config.py` and
  this experiment's `config.py`. Stages: `exploration`, `signal_check`, `validation`, `summary`, `test`.
- Exploration only on 2005-01-03 → 2014-12-31. After the first `validation_only` run of step 03, any change is a new version.
- Test windows are evaluated only once the design is frozen.
- Tests: `tests/test_exp02.py` (features vs TSCTX, no look-ahead, label by hand, simulator vs a bar-by-bar reference,
  schedule, selection, signal check incl. the month minimum, criteria, end-to-end fold, prior-only runner == candidates).

## 14. Implementation

| Step / file | Content |
|---|---|
| `config.py` | Every exp02 constant |
| `step01_mechanism_check.ipynb` | Mechanism check (exploration) → `step01_mechanism_check_data/` |
| `signal_check.py`, `step02_signal_check.ipynb` | Two-sided base-rate signal check → `step02_signal_check_data/` |
| `walk_forward.py`, `step03_walk_forward.ipynb` | Schedule, models, candidates, pooled selection, prior-only path, test → `step03_walk_forward_data/` |
| `so/core/reentry_simulation.py` | State machine (shared with exp03) |

## 15. Known limitations

- Dividends ignored (favours time in cash); cash earns 0% (disfavours it).
- State resets to invested at the start of each 3-month window, and re-entry is forced after 60 decisions: the experiment
  tests **short exits** only; it cannot stay out through a long bear market (audit F4).
- Few large declines in 2015-2026: low statistical power (audit F2).
- Distribution shift: trained on all days, used on cash days.
- The 3% bad tick rule leaves smaller wicks that can trigger the stop (audit F1).
- Costs are informal assumptions.

## 16. Change log

| Version | Date | Change |
|---|---|---|
| (v2 2.0 – 2.0.2) | 2026-10-04 | Protocol v2, `stop_reentry_v2` / `stop_reentry_v2_clean`: see `docs/history/RESEARCH_PROTOCOL_v2.md` |
| 1.0 | 2026-10-05 | Re-run in the reorganized workspace as `exp02_stop_reentry`. Trading rules, grids, model, schedule and selection unchanged. Changed (decided by Nicolas, 2026-10-05): the signal check requires ≥ 6 months per bin in each window (`DAILY_SIGNAL_CHECK_MIN_MONTH_COUNT`); honest reporting of §12 (prior-only path with baselines on validation, MDE, success criteria on that path, summary trial entry); the random re-entry baseline also runs when no episode closed (probability from every episode). The validation-stage stopping rule is stated on the prior-only path (§11.3); secondary criterion = Sharpe **or** drawdown (Nicolas, 2026-10-05; the first run's notebook prints both flags) |
