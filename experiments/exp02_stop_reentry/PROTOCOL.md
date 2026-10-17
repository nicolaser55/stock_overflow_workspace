# exp02_stop_reentry_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp02_stop_reentry_v2`. Config: `experiments/exp02_stop_reentry/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** The version 1.0 run already used this data. Nothing was tuned and no rule was added. No further version may follow from this result.

The rules below are the rules of protocol 1.0 (`experiments/exp02_stop_reentry/PROTOCOL.md` at tag `pre-port-20261012`, commit `00269da`), copied verbatim. Version 2.0 changes only the evaluation machinery, listed after the verbatim sections.

## 1. Question, rules, grid, selection, baselines, success and stopping (protocol 1.0, verbatim)

### Research question

Starting from a fully invested position in SPY:

- an **exit based on a calculated risk tolerance** (a volatility-scaled trailing stop),
- combined with a **re-entry decision based on information** (a model of SPY's 20-session forward return),

can these produce a **higher total return after costs than buy-and-hold** over the same period, out of sample?

**How the strategy can beat buy-and-hold.** While invested, the strategy *is* buy-and-hold. The difference comes only from
the out-of-market episodes. An episode that sells at price S and buys back at price R ends with S ÷ R times the shares it
had, before costs. The strategy wins exactly when, on average, it **buys back lower than it sold**.

### Success criteria (`so/core/evaluation.py`)

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
statistically supported". The minimum detectable effect shows how large an edge would have to be to be detected.

**Metrics:** Sharpe ratio annualized from daily returns, risk-free rate 0; maximum drawdown of the daily equity.

### Strategy rules (`so/core/reentry_simulation.py`)

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

### Target

- One row per session, evaluated at the decision bar.
- y = 1 if buying at the 15:59 open (+$0.01) and selling at the close of the last bar of session t+20 (−$0.01) is
  profitable after the per-share fees; 0 otherwise. The last 20 sessions are unresolved (NaN).
- Training rows: all sessions with every feature and a label (not only cash days): a known distribution shift.
- Labels overlap heavily; rows are not weighted; intervals use a monthly block bootstrap.

### Walk-forward and selection

- **Embargo: 20 sessions** (the label horizon).
- **Training windows:** 10 years, or all sessions since the start of the data.
- **Candidates:** 2 windows × 3 k × 3 offsets = **18**, each logged as a trial.
- **Selection:** mean validation excess return over the last 4 validation quarters.
  Ties: larger k, higher offset, then the 10-year window.

### Baselines (same simulator, same costs)

1. Buy-and-hold over the same window.
2. Same stop + **fixed-delay** re-entry at the 1st, 5th or 20th cash decision.
3. Same stop + **random** re-entry: 20 runs, re-entering at each cash decision with probability 1 ÷ (the model's mean cash
   decisions per episode; every episode is used when none closed with a re-entry). If the model never left the market in
   the window, every run equals the model.
4. The **200-session moving-average rule** (no stop, no forced re-entry), trading at the 15:59 open.

### Stopping rule (walk-forward)

On validation: STOP if the prior-only path fails to beat buy-and-hold and the fixed-delay baselines. This version applies
that rule to the new prior-only path. A pass would still not be a success claim (research-integrity rule 5). No further
version may follow from this result.

The signal check and the mechanism check of protocol 1.0 are not re-run. Their verdicts stay in `docs/RESULTS_LOG.md`.

## 2. Version 2.0 changes

Only the evaluation machinery changes:

- The development boundary is `so.core.holdout.get_development_end_date` (the session an embargo before the active holdout
  start). Dates are not typed in `config.py`.
- Bars and features are read through `DataContext`. `DATA_SOURCE_LIST` is `SPY_1MIN`.
- The design exposes the holdout interface (`PERIOD_RULE`, `CANDIDATE_LIST`, `SELECTION_RULE`, `run_candidate_replay_dict`,
  `run_prior_only_path_dict`, `get_baseline_return_dict`).
- The re-entry model is refit weekly (`so.core.rolling_retrain`) on the original windows `10Y` and `ALL`, with the original
  label. A row is used only when `label_known_ts` is strictly before the retraining decision. Rows that fail are dropped
  and counted as purged. p* is that refit's training base rate plus the candidate's offset.
- A candidate period is still scored as a fresh window (start invested), which is how protocol 1.0 scored a quarter.
- The prior-only path is one continuous replay. The candidate selected for period f governs period f + 1. The first period
  has no history and takes the first listed candidate (`10Y|3|-0.05`). While a candidate is in force, its k is the stop
  multiplier on those sessions.
- The diagnostic LightGBM of protocol 1.0 is not refit. It never placed a trade.
- No holdout evaluation is run by the agent.

## 3. Data sources

| Source | Convention | Availability | Revision | Role |
|---|---|---|---|---|
| `SPY_1MIN` | bar start | label + 1 minute | not revised (stored IBKR bars) | feature and label inputs |

The 16 features are `so.config.DAILY_FEATURE_COL_STR_LIST`. Each uses bars up to the decision bar. The label looks 20
sessions forward. `label_known_ts` is the decision moment of that later session.

## 4. Retraining

Pre-registered (Nicolas, 2026-10-11 and 2026-10-12). Changing a line here after a result is a new version. This version
will not have one.

- **Training-window candidates:** `10Y` and `ALL` (protocol 1.0: 10 years, and all history).
- **Retraining frequency:** weekly, the first session of each calendar week. No frequency comparison is pre-registered.
- **Label:** `y_fwd_positive`, protocol 1.0 section "Target" above.
- **Purge:** `label_known_ts` strictly before the retraining decision. Dropped rows are counted, never filled.
- **Minimum training rows:** 20. A smaller refit raises. There is no fallback window.
- **Selection and tie order:** protocol 1.0, above. The tie columns are `stop_k` descending, `threshold_offset` descending,
  `train_window_months` ascending (10Y before ALL).

## 5. Trial budget

18 candidates × 44 folds + 1 summary = **793**, the old validation grid plus its summary row. This run logs one validation
trial per candidate per development period, plus one summary. Baselines are reported and are not extra grid trials.

## 6. Reporting

Best candidate after the fact, labelled **optimistic**. Prior-only path. Uninformed baselines (same-stop fixed delay,
matched random re-entry, the 200-session rule, buy-and-hold). Time in the market. Minimum detectable effect and the
6-month block interval of the annualized log excess. Performance over time, turnover, candidate switches, and the refit
log (rows used, share purged, prediction move).

## 7. Holdout evaluation

Only Nicolas runs `scripts/holdout_evaluate.py`. The agent does not run it and does not set `SO_HOLDOUT_PATH` or
`SO_HOLDOUT_EVALUATION_TOKEN`.

## 8. Known limitations

Dividends ignored. Cash earns 0%. Costs are informal. The old version's state reset each quarter; this prior-only path
carries the position. The two numbers are not the same object. The old results stay in `docs/RESULTS_LOG.md`.

## 9. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-05 | See tag `pre-port-20261012`. Results: `docs/RESULTS_LOG.md`, exp02 (prior-only +111.66% vs +237.21%, STOP). |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence (Nicolas, 2026-10-12). Machinery only, section 2. |
| 2.0 | 2026-10-13 | Shared selection now treats scores within NUMERIC_TOLERANCE (1e-6) as tied. This experiment is not re-run. Its trials stand. |
| 2.0 | 2026-10-15 | Holdout report baselines are the development report's uninformed baselines over the span passed in, with this protocol's fixed seeds, through the point-in-time context. Report-only: no rule, grid, threshold, window, cost, baseline, selection or stopping rule changes. Development results unchanged. |
| 2.0 | 2026-10-16 | The removed `SO_ALLOW_LEGACY_REPRODUCTION` flag is no longer named. No rule, grid, threshold, window, cost, baseline, selection or stopping rule changes. |
