# exp08_vix_signal_check: Protocol (the gate of the VIX line)

*Version 1.0 (2026-10-09). Experiment name `exp08_vix_signal_check`. Config:
`experiments/exp08_vix_signal_check/config.py` + `so/config.py` (the VIX constants of `so/vix_config.py` are assigned to
the experiment config, so the hash covers them). Written by the agent in autonomous mode from the roadmap decided by
Nicolas on 2026-10-08 and revised on 2026-10-09 (`docs/RESEARCH_STATE_2026-10-09.md` §6), and committed (message
`preregister exp08`) before any run of this experiment. After the first run, any change of a rule, feature, statistic or
gate is a new version with a new experiment name.*

---

## 1. Background and research question

exp01-exp07 used SPY prices only and all lost to buy-and-hold on the honest validation path (2015-2026). The VIX (30-day
implied volatility of S&P 500 options) and VIX3M (3-month) are the first non-price data of the project (approved by
Nicolas on 2026-10-08). exp08 decides, before any trading rule is run, whether the VIX carries information the later
experiments could use. It is a gate: it runs no strategy.

**Questions.**
- G1: does any VIX feature, alone, move the rate of positive 20-session forward returns away from the base rate,
  reliably, on training AND validation, more than a VIX series shifted in time does?
- G2: does adding the six VIX features to exp02's 16 price features raise the out-of-sample AUC of exp02's logistic
  model, more than a shifted VIX does?
- G3: does the VIX forecast the next 20 sessions' realized volatility better than the trailing 20-session realized
  volatility (exp05's σ̂)?
- G4: is the average forward return of high-VIX sessions below 0 (the only case in which an unlevered exposure w ≤ 1
  can beat buy-and-hold by holding less)?

## 2. Hypothesis and why it could (and could not) work

- *Could work:* the VIX is a forward-looking price (option premia), not a function of past SPY prices; implied
  volatility usually forecasts realized volatility well (G3); an inverted term structure (VIX > VIX3M) marks acute
  stress; the variance risk premium has been linked to future returns in the literature.
- *Could fail (expected for G4 and probably G1/G2):* high VIX sessions are followed by large rebounds as well as large
  falls (2009, 2020, 2025); the variance risk premium predicts returns weakly and over horizons longer than 20 sessions;
  the 16 price features already contain realized volatility, drawdowns and trends, so the VIX may add nothing.
- **Known before writing this protocol (disclosed):** the agent knows the 2015-2026 results of exp01-exp07 and famous
  VIX episodes (2008, August 2015, February 2018, March 2020, 2022, April 2025). No VIX-based statistic of the project
  had been computed before `pipeline/step07_VIX_data_check.ipynb` (data quality only: coverage, agreement and feature
  distributions; no label, no return).

## 3. Data

- **SPY:** IBKR 1-minute bars (`store01_rawzone/ibkr_spy_1min/`), daily table from `so.features.daily_features`. The
  schedule is built from the full session calendar (dates only, as exp04 step 02); then **the bars are cut at
  2026-05-13** before any computation: the 20-session label (`fwd_net_return_20d`, `y_fwd_positive`) and the 20-session
  forward volatility of the last validation decision (2026-04-15) end on 2026-05-13, the last session before the
  untouched window. The notebook asserts that the largest session used by any label or forward volatility is ≤ 2026-05-13.
- **VIX / VIX3M:** IBKR daily and 1-minute bars (`store01_rawzone/ibkr_vix_family/`), read only through
  `so.features.vix_features` with the same cutoff (2026-05-13; every loader refuses 2026-05-14 or later). VIX from
  2005-10-03, **VIX3M from 2009-08-12**. Known gaps and their handling: `docs/RESULTS_LOG.md`, "VIX data layer".
- **Features** (`so/features/vix_features.py`), for timing v: `vix_level_v`, `vix_pct250_v`, `vix_chg5_v`,
  `vix_fade_v`, `vix_term_v`, `vrp_v` (definitions in the module docstring).
  - **Primary timing `_prev`:** the previous session's daily close (known before the 15:58 decision; NaN if older than 3
    SPY sessions).
  - **Secondary timing `_intraday`:** the last 1-minute bar labelled at most decision − 1 minute (15:57 on a full day);
    the bar-label convention is unproven, so this variant never opens a gate.
- **Analysis rows:** SPY sessions from 2009-08-12 to 2026-04-15 whose label and all 22 features (16 price + 6 VIX of the
  variant) are known (the term feature exists from 2009-08-13). **Training** = analysis rows up to the first fold's
  train_end (asserted 2015-03-18). **Validation** = analysis rows of the 44 replay periods (pooled), which tile
  2015-04-17 → 2026-04-15 (§11).

## 4. Gates (`gates.py`)

**G1 UNIVARIATE.** `experiments/exp02_stop_reentry/signal_check.get_daily_signal_check_pdf` on the six `_prev` features
with exp02's constants: 5 quantile bins (edges learned on training), a bin is tested with ≥ 40 training rows and ≥ 6
calendar months in each window, monthly block bootstrap (1,000 iterations), two-sided against each window's base rate, a
**signal** = the interval excludes the base rate on the same side in training and validation. Statistic **S1 = number of
signal (feature, bin) pairs**. PASS if S1 > the maximum of the 19 null runs (§6); S1 = 0 never passes.

**G2 INCREMENTAL.** For every fold f of the 44: training rows = analysis rows from 2009-08-12 to train_end(f) (expanding;
asserted: every training label ends before valid_start(f)); prediction rows = the analysis rows of period f. Model =
exp02's logistic regression (`walk_forward.fit_reentry_model_dict(..., "logistic")`: standardization fitted on the
training rows, L2, C = 0.1, max_iter 2000). BASE = `so.config.DAILY_FEATURE_COL_STR_LIST` (16); AUGMENTED = BASE + the six
`_prev` features; both on exactly the same rows. Statistic **dAUC = AUC(AUGMENTED) − AUC(BASE)** of the pooled
out-of-sample predictions. PASS if dAUC > the maximum of the 19 null runs (AUGMENTED refitted on every fold in every run;
BASE unchanged). Reported: both pooled AUCs with 1-month-block bootstrap intervals (1,000 iterations), the dAUC interval,
the mean per-period dAUC. No LightGBM.

**G3 VOLATILITY FORECAST.** On the validation decisions: target = realized volatility of the next 20 sessions
(`exp05 get_forward_volatility_arr`: std of the close-to-close returns of sessions s+1 … s+20). **D = Spearman(vix_level_prev,
target) − Spearman(daily_volatility, target)**; circular block bootstrap of 6-month blocks of calendar months (exp05's
scheme, 2,000 iterations, seed `so.config.RANDOM_SEED`), the same resampled rows for both correlations. PASS if the 95%
lower bound of D > 0.

**G4 PLAUSIBILITY OF UNLEVERED VOLATILITY SCALING.** Threshold = 80th percentile of `vix_level_prev` on the training rows.
Statistic: mean `fwd_net_return_20d` of the rows at or above the threshold, on training and on the pooled validation,
with 1-month-block intervals. **PASS only if the mean is below 0 in BOTH windows** (point estimates; the intervals are
reported).

**SECONDARY (reported, never a gate):** G1 and G2 with the six `_intraday` features (their own analysis rows).

## 5. Gate decisions (pre-registered; primary results only)

| Experiment | Runs if |
|---|---|
| exp09_vix_reentry | G1 **or** G2 passes |
| exp11_vix_model_exit | G2 passes |
| exp10_vix_vol_scaled_exposure | G3 **and** G4 pass |

- exp09 has **two chances** (G1 or G2). Each gate passes by chance with probability about 1/20 under the null (the real
  value must exceed all 19 shifted runs), so the familywise false-pass rate of the exp09 gate is about 10% (less if G1
  and G2 are positively dependent).
- If none of exp09-exp11 can run, the VIX line stops: "no usable VIX information under the pre-registered gates".
- If only a secondary (`_intraday`) version of G1 or G2 would pass: record "candidate pending review (secondary timing)"
  and park it; it opens nothing.

## 6. Null and statistics

- **Session-shifted null (G1, G2):** 19 runs; run r draws u uniform in [0.25, 0.75] with seed `NULL_SEED + r`
  (20261009 + r), k = round(u × number of analysis rows), and circularly shifts the six VIX columns of the variant **as
  one block** by k rows over all analysis rows; dates, labels and price features stay in place; everything learned (bin
  edges, models) is re-learned in every run. p = (1 + number of null runs ≥ real) / 20. The shift keeps the VIX's own
  persistence and its joint distribution, and breaks only its alignment with the dates.
- Bootstraps: as §4 (month blocks; 6-month circular blocks for G3).
- Descriptive (no gate, no trial): forward 20-session return by `vix_level_prev` quintile (training edges) and by
  term-structure state (`vix_term_prev ≥ 1` vs `< 1`) on training and validation, with 1-month-block intervals; the
  episodes with `vix_term_prev ≥ 1` from 2009-08-12 to 2026-04-15 (start, end, length, SPY return from the fill of the
  first session to the close of the last, and over the next 20 sessions).

## 7. Stopping rules

The gates of §5 are the stopping rules of the VIX line. exp08 itself has no strategy and no further step: after its one
run, the gate decisions are recorded and the roadmap continues with the experiments they allow (in the order exp09,
exp10, exp11), or the VIX line stops.

## 8. Reporting

For each gate: the real statistic, the null values and their maximum, the p-value, the intervals, PASS/FAIL; the
secondary G1/G2; the gate decisions; the descriptive tables. Trial-log entries (stage `signal_check`): G1, G2, G3, G4,
G1 intraday, G2 intraday = **6 entries**. Multiple testing: reported with the 3,293 earlier workspace trials and the 4,089
legacy trials.

## 9. Trial budget

6 entries, **budget 10** (one run of the notebook; a crash half-way is recorded and the notebook re-run once).

## 10. Known limitations and biases (disclosure)

- The follow-ups of this gate (exp09, exp10, exp11) are **data-dependent follow-ups of experiments known to have failed**
  on 2015-2026 (exp04/exp07, exp05, exp02), designed with knowledge of famous VIX episodes (2008, 2020).
- 2015-2026 is development data, **reused for the eighth time** (exp01-exp07 and the earlier work, about 7,400 trials).
- **VIX3M starts 2009-08-12** in the IBKR data: the training window of every gate starts there (about 5.6 years to the
  first train_end instead of 10 for the price-only experiments), and `vix_pct250` uses VIX values back to 2008.
- The IBKR index data was **not compared with Cboe's official values**; the daily close disagrees with the last 1-minute
  close on 2.6% (VIX) and 10.6% (VIX3M) of the dates, a few by more than 1 point (`docs/RESULTS_LOG.md`, VIX data layer).
- The **1-minute bar-label convention is unproven** (a delay of about one minute observed in the probe, no look-ahead
  detected); hence the 1-minute margin and the secondary status of `_intraday`.
- Overlapping 20-session labels: neighbouring rows are not independent; the month blocks and the shifted null account for
  part of it, not all.
- G1 and G2 test association with the 20-session label, not a trading rule; passing a gate is necessary, not sufficient.
- G4 compares point estimates with 0; its intervals will be wide.

## 11. Methodological choices (the most conservative option)

| Choice | Options | Chosen | Why |
|---|---|---|---|
| Validation rows | the 44 quarters as listed (a boundary session counted twice, sessions between quarters left out); the 44 replay periods | replay periods (`get_replay_period_pdf`) | Each session once, and the same tiling the continuous replays and exp11 use (the model of the period containing the session) |
| Null | i.i.d. permutation of rows; circular shift of the block | circular shift of the six columns together | Keeps the VIX's persistence and cross-feature structure; a permutation would destroy both and give a null too easy to beat |
| Null range | any shift; [25%, 75%] of the rows | [25%, 75%] (roadmap) | Avoids shifts so small that the shifted VIX is still almost aligned |
| Gate threshold | p ≤ 0.05; real > all 19 null runs | real > all 19 null runs | Same strictness, no interpolation |
| G2 training window | rolling 10 years; expanding from 2009-08-12 | expanding (roadmap) | VIX3M starts 2009; a rolling window would be shorter still |
| AUC interval | 1-month or longer blocks | 1-month blocks (reported only, not a gate) | The gate is the null; the interval describes the uncertainty |
| G4 rule | point estimate < 0 in both windows; upper bound < 0 | point estimates in both windows (roadmap) | Already demanding (two windows); stated as written in the roadmap |
| Primary timing | `_prev`, `_intraday` | `_prev` | `_intraday` depends on an unproven bar-label convention |

## 12. Implementation

| File | Content |
|---|---|
| `config.py` | Every exp08 constant (VIX constants assigned from `so/vix_config.py`) |
| `gates.py` | Schedule check, analysis rows, null shift, G1-G4, gate decisions, descriptive tables |
| `step01_vix_gate.ipynb` | The single run → `store04_experiments/exp08_vix_signal_check/step01_gate_data/` |
| `so/features/vix_features.py`, `so/vix_config.py` | VIX data layer (shared, tested in `tests/test_vix_features.py`) |
| `tests/test_exp08.py` | Synthetic-data tests (planted information is found, the null and the gate rules, G3/G4 by hand) |

## 13. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-09 | Initial protocol (agent, autonomous mode), pre-registered before any run |
