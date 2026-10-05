# Stock Overflow — Results Log

*A chronological record of experiment outcomes, for the thesis. Each entry states what was run, under which protocol and config hash, what was observed, and what the evidence does and does not support. Test windows touched so far: **none** (`test_window_touched = 0` for every trial).*

*Since 2026-10-05 every result below is stated on the **corrected** raw data (62 bad wicks removed, see "Data corrections"). The numbers of the first runs, on uncorrected data, are kept next to them as a record.*

## Summary

| Experiment | Steps | Trial-log name (corrected data) | Status | One-line outcome (corrected data) |
|---|---|---|---|---|
| v1: minute entries with symmetric SL/TP | 05–08 | `signal_check_v1_clean`, `lgbm_ev_policy_v1_clean` | **Stopped** 2026-10-04, confirmed 2026-10-05 | No signal beyond market drift; no setting beat buy-and-hold on validation |
| v2: stop and model re-entry | 09–12 | `stop_reentry_v2_clean` | **Stopped** 2026-10-04, confirmed 2026-10-05 | Stops sell into dips that revert; 0 signals; no candidate beat buy-and-hold on validation |
| "Sell at strength" (ATH exits) | 13 | `ath_exit_exploration_clean` | Exploration only (2005–2014) | Weak and inconsistent: 5 of 15 rules beat buy-and-hold (4 of 5 at the 0.5% threshold, none at 1%); no significant fall in prices after near-ATH days |
| v3: add VIX information | — | — | **Next** (agreed 2026-10-04) | Protocol to be written before any data is explored |

**Trial log as of 2026-10-05** (`store03_goldzone/trial_log/trial_log.csv`, 4,089 entries). Every entry counts as a trial, including duplicates and runs on uncorrected data.

| Experiment | Config hash | Stage | Entries | Data | Notes |
|---|---|---|---|---|---|
| `signal_check_v1` | `ff9d0d7e2e` | signal_check | 1 | uncorrected | 2026-10-03 |
| `lgbm_ev_policy_v1` | `ff9d0d7e2e` | validation | 1,080 | uncorrected | 540 distinct candidates: step 08 was run twice |
| `stop_reentry_v2` | `f661934b1a` | exploration / signal_check / validation | 14 / 1 / 792 | uncorrected | logged 2026-10-04 15:08–15:48 |
| `stop_reentry_v2` | `f661934b1a` | exploration / signal_check / validation | 14 / 2 / 792 | **corrected** | logged 2026-10-04 19:03–19:07. **Mislabeled duplicate run** (see "Data corrections"); results identical to `stop_reentry_v2_clean` |
| `ath_exit_exploration` | `f661934b1a` | exploration | 15 | uncorrected | 2026-10-04 15:48 |
| `ath_exit_exploration_clean` | `f661934b1a` | exploration | 15 | corrected | 2026-10-04 19:24, logged with the stale v2 hash; results identical to the next row |
| `ath_exit_exploration_clean` | `34455c40ce` | exploration | 15 | corrected | 2026-10-05 01:32 |
| `signal_check_v1_clean` | `ff9d0d7e2e` | signal_check | 1 | corrected | 2026-10-05 00:01 |
| `lgbm_ev_policy_v1_clean` | `ff9d0d7e2e` | validation | 540 | corrected | 2026-10-05 00:07–00:38 |
| `stop_reentry_v2_clean` | `34455c40ce` | exploration / signal_check / validation | 14 / 1 / 792 | corrected | 2026-10-05 01:27–01:31 |
| `audit_bad_tick_sensitivity_v2` | `34455c40ce` | validation | 1,584 | corrected + bad tick rule at 2% / 1.5% | Audit 2026-10-05 (see the audit entry below). Rows in `records/audit_trials_20261005.csv`; **not yet appended** to `trial_log.csv` |
| (all) | | test | **0** | | No test window has been evaluated |

---

## Data corrections

### Bad ticks in the raw minute bars (found 2026-10-04, corrected 2026-10-04)

**Problem.** 62 bars (15 / 11 / 14 / 15 / 7 in 2005 / 2006 / 2007 / 2008 / 2009, none later) had a high or low 3–8% beyond both their own open/close and their neighbours' prices. Many were exactly ±$5 or ±$10 away, e.g. 2007-06-06 14:16 high $161.90 with open/close $151.92. The step 00 sanity check did not flag them, because it only tests that high and low enclose open and close.
- **Affected:** everything that reads minute highs and lows: v1 barrier labels and price-action features; v2 trailing-stop exits and high-based features (`ath_drawdown_pct`, `high60/250_dist_pct`, `sessions_since_high60`, `prev_day_range_pct`); the step 13 ATH definition.
- **Not affected:** buy-and-hold and the v2 label (opens and closes only).

**Rule (decided before its effect on any result was looked at).** `fix_raw_bad_ticks.py` cuts a wick back to the bar body when it is more than 3% beyond max/min(open, close, previous close, next open), neighbours taken within the same session only. The threshold comes from the data-quality evidence alone: every bar above it looks like a feed error, and the 2010-05-06 flash crash stays below it. Only the 62 high/low cells change.
- Tested on a copy of the raw data: 62 cells flagged, backups byte-identical, exactly 62 lines changed, 0 bad ticks on a second pass. Unit test in `tests/run_tests.py`.
- Applied by Nicolas on 2026-10-04; the log of every corrected cell is `records/bad_tick_corrections.csv`. The original files are kept in `store01_rawzone/ibkr_ohlcv_data_backup_<timestamp>/`.
- **Least clear-cut cases:** a few 3–4% wicks during the October 2008 crash (e.g. 2008-10-10 12:19 and 12:50, both with a high of $91.02). The rule corrects them like the others.

**Estimated vs actual impact.** Before the correction, the impact was estimated on a copy with the wicks clipped to the body. The reruns on the corrected data gave exactly the estimated values: step 10 (k = 4, 5-day delay) +62.9%, step 13 (within 0.5% of the ATH, 5% dip buy-back) +80.7%. The fake 2007 highs had hidden the October 2007 top from the ATH definition; days within 1% of the ATH in 2005–2007 went from 45 to 172.

### How each step was rebuilt

**Steps 09–13 (v2, step 13)** rebuild their tables from the raw data on every run, so they were simply rerun.
- **Mislabeled duplicate run.** The first rerun (2026-10-04 19:03–19:24) used notebook kernels that were still open from the earlier session, so they kept the old `config_v2.py` in memory. Steps 10–12 therefore logged under `stop_reentry_v2` / `f661934b1a`, and step 13 under `ath_exit_exploration_clean` with the stale hash. Their results are on corrected data: a rerun with fresh kernels (2026-10-05 01:27–01:32, `stop_reentry_v2_clean` / `34455c40ce`) reproduced every validation metric exactly (checked on all 792 entries, and on the 15 step 13 entries). The trial log was not edited; the two runs are told apart by `logged_ts` (above). The step 11 and step 12 output files of the uncorrected run were overwritten by that first rerun; their numbers are kept in this log and in the committed notebooks (tag `v2-final`).
- **Lesson:** restart the kernel before running a notebook that depends on a changed `.py` file.

**Steps 01–08 (v1)** were rebuilt **for the affected dates only** (decided 2026-10-04 to save compute). `invalidate_bad_tick_dates.py` derived, from the code, which per-day files can depend on a corrected cell, and moved them to `stock_overflow_data/archive_bad_tick_invalidated_<timestamp>/` (list in `records/bad_tick_invalidated_dates.csv`):
- step 01 and step 02: the 58 sessions that contain a corrected cell;
- step 03 (TSSEG): those + every session whose `cum_max` (highest high since 2005) changed, up to 2013-05-06, when the real price passed the fake $161.90 high (2,018 sessions);
- step 04 (TSCTX): those + the session after each bad day (previous-day high/low features) (2,022 sessions);
- step 05 (TSBAR): each bad day and the 10 sessions before it, because a barrier trade can stay open up to 10 sessions (441 sessions);
- step 06 (model dataset): every date of steps 02–05 (2,063 sessions).

Steps 01–06 then regenerated the missing dates; steps 07 and 08 were rerun in full.
- **Step 05 was regenerated for all dates, not 441:** its folder held only 110 files when it ran (when and why the older TSBAR files left the folder is not recorded). So every target is now built from the corrected data.
- **Consistency check (2026-10-05).** `verify_model_dataset.py` rebuilt every one of the 5,436 model dataset days in memory from the current step 02–05 files and compared it with the saved file: **5,436 identical, 0 differences** (`records/model_dataset_verification.csv`). The step 06 files that were not regenerated therefore equal a full rebuild, and the older TSBAR files equalled the new ones on every unaffected date.
- **Limitation:** on unaffected dates, the step 01–04 files are still the caches built earlier (several carried over from the previous workspace). The v1 pipeline is "corrected wherever the correction can matter", not rebuilt entirely from scratch.

### Other open verifications

- **TSSEG spot check: 2021-08-24 differs** from a regeneration (4 of 5 dates identical; checked 2026-10-04 and again 2026-10-05). TSIND for the same date is identical, so the snapshots match; the difference is in a TSSEG-only part. Unrelated to the bad ticks (none after 2009). Cause not identified; a diagnostic cell is pending. TSSEG is used only by v1.
- **Step 00 rerun on the corrected data (2026-10-04):** reported run by Nicolas; its bad tick count (expected 0) was not reviewed here.

---

## Experiment v1 — `lgbm_ev_policy_v1_clean` (protocol v1, config hash `ff9d0d7e2e`)

**Design.** Minute-level long entries, each with a symmetric SL/TP of 0.1–1% and at most 10 days of holding. LightGBM P(TP) model per distance, with an expected-return policy.

**Results on corrected data (2026-10-05).**
- **Signal check (`signal_check_v1_clean`): STOP, identical to the uncorrected run.**
  - 0 of 5,691 bins passed on both training and validation.
  - 1,339 training passes, against 142 expected by chance. Almost all of them were at distances where being long already beat break-even, i.e. market drift.
  - Identical as expected: its window (training 2016–2026, validation 2026-01-30 → 2026-04-29) contains no corrected data.
- **Walk-forward, validation only (45 quarters, 2015–2026; 540 validation trials):**
  - The best of 12 settings (3-year training, threshold 0.05%) chained **+158%, against +230%** for buy-and-hold over the same spans.
  - Every setting beat buy-and-hold in at most 16 of 45 quarters.
  - The model was invested 76–95% of the time.
  - The selected setting changed in 24 of the 45 folds, all in folds 0–33, whose training windows contain data from before May 2013. Folds 34–44 are identical to the uncorrected run, which shows that the run is deterministic and that the changes come from the data correction.

**Uncorrected run (2026-10-04, `lgbm_ev_policy_v1`), for the record:** best setting +162% against +247%; at most 18 of 45 quarters; signal check identical.

**Conclusion.** Stopped. No evidence of an edge, on either version of the data.

---

## Experiment v2 — `stop_reentry_v2_clean` (protocol v2.0.2, config hash `34455c40ce`)

**Design.** Invested by default. Exit on an intraday trailing stop at k × 20-day volatility (k ∈ {3, 4, 5}). Re-entry when a logistic regression's P(20-session forward return > 0) is at least the training base rate + offset (offset ∈ {−5, 0, +5} pts). Forced re-entry after 60 sessions in cash. 16 daily features. Same rules as `stop_reentry_v2` (config hash `f661934b1a`); only the experiment name changed.

**Step 09 (daily table).**
- 5,436 sessions; first complete feature row 2005-12-29.
- Base rate of positive 20-session net returns: 65.7% overall, ranging from 34.8% (2008) and 41.4% (2022) to 81.3% (2017). (Unchanged by the correction: the label uses opens and closes only.)

**Step 10 (mechanism check, exploration 2005–2014 only; 14 exploration trials).**
- Buy-and-hold: +69.0% (Sharpe 0.36, max drawdown −56.4%).
- **Stop + fixed-delay re-entry lost to buy-and-hold for every k and every delay** (9 variants).
  - Excess return ranged from **−6.1 pts** (k = 4, 5-day delay: +62.9%) to −100.0 pts (k = 3, 20-day delay: −30.9%).
  - The k = 4, 5-day variant reached 91% of buy-and-hold's return, with a Sharpe ratio of 0.37 (vs 0.36) and a max drawdown of −41.5% (vs −56.4%). On the success criteria that would count as "comparable return, smaller drawdown". It is one of 9 variants tried, it uses no information, and its neighbours are far worse (k = 4 with a 1-day delay +20.5%; k = 3 and k = 5 with a 5-day delay −6.1% and +20.1%). It is recorded as an observation, not as a candidate.
- **Post-exit path (main evidence).** The mean log share gain of re-entering n decisions after a stop is **negative at every n shown (1, 2, 3, 5, 10, 20, 40, 60) and every k** (−0.1% to −2.0%).
  - Relative to the drift reference it is below at every n shown except n = 40 (0.00 to +0.12 pts); at n = 1–20 it is 0.04 to 0.47 pts below.
  - Only 30–47% of stops would have been bought back lower.
  - Prices tended to **rebound after a stop**, by more than drift alone explains. The stop tends to sell near the low of a short dip.
- **Oracle** (perfect foresight up to 60 sessions): +1,086% to +1,423%. A loose ceiling, uninformative as expected.
- **200-session trend rule:** +50.4% (Sharpe 0.42, max drawdown −23.3%). Return 73% of buy-and-hold's, below the 90% "comparable" floor. Unchanged by the correction (closes only).
- *Uncorrected run:* excess −44.7 to −109.4 pts (k = 4, 5-day delay +24.3%); share gain below the drift reference at every n (−0.1 to −1.1 pts); 26–45% of stops bought back lower; oracle +946% to +1,387%.

**Step 11 (daily signal check, stopping rule).** **Identical to the uncorrected run** (its training window starts 2015-03-20, after every corrected `cum_max` value).
- Training window 2015-03-20 → 2025-03-19 (2,515 rows, base rate 66.3%); pooled validation of folds 40–43 (250 rows, base rate 77.6%).
- **0 training passes out of 80 tests (4 expected by chance), 0 signals: STOP.**
- The largest training lift was +8 pts (`return_120d` in (4.2%, 8.1%]: 74% vs 66%), with an interval of [64%, 83%] that includes the base rate.
- **Method caveat:** validation bins with few rows concentrated in a few months can produce degenerate bootstrap intervals (e.g. [1.0, 1.0]). This could create false validation passes. It did not affect this verdict, because no bin passed training. `min_month_count_in` was added for later experiments.

**Step 12 (walk-forward, validation only: 44 quarters, 2015-04 → 2026-04; 792 validation trials).**
- **All 18 candidates lost to buy-and-hold.**
  - Chained validation returns: +54% to +230%, against +243%.
  - Mean excess per quarter: −0.2 to −1.8 pts.
  - Quarters beating buy-and-hold: 14 to 21 of 44.
  - The best candidate after the fact (all history, k = 5, offset 0) reached +230%, 94% of buy-and-hold's return. It is the best of 18 picked with hindsight, so this number is optimistic.
- **Selection using only the 4 previous quarters** (`get_pooled_selection_pdf`, evaluated on the next validation quarter: an honest pseudo out-of-sample): **+112% vs +237%**, beating buy-and-hold in 20 of 43 quarters.
- **Insurance pattern.** The "all history" candidates with offset 0 or +5 pts gained +2.6 to +5.1 pts per **down** quarter (12 quarters) but lost −1.3 to −3.5 pts per **up** quarter (32 quarters). With up quarters 2.7 times as frequent, the net effect was negative.
- **Model ranking ability (mean validation AUC):** logistic regression 10-year window 0.523 (above 0.5 in 50% of folds), all history 0.470 (39%); LightGBM 0.51. Indistinguishable from no ranking ability.
- *Uncorrected run:* all 18 lost (+66% to +195%); pooled selection +141% vs +237% (23 of 43); AUC 0.538 / 0.456; LightGBM 0.51–0.52.

**Conclusion (2026-10-04, confirmed on corrected data 2026-10-05).** All three stopping-rule checks point the same way. No daily price-derived feature reliably shifts the 20-session up-rate. The stop mechanism sells into short dips that tend to revert. No re-entry setting beats buy-and-hold on validation, and the honest pseudo out-of-sample selection did worse on corrected data than on uncorrected data. **v2 is stopped under protocol §11.** Test windows were not evaluated and remain unseen.

---

## Exploration — "sell at strength" (all-time-high exits) (`step13_ath_exit_exploration.ipynb`, `ath_exit_exploration_clean`)

**Hypothesis (Nicolas, 2026-10-04).** Instead of selling on weakness (v2 stops), sell when SPY is at or near its all-time high (ATH) and buy back later, lower.

**Scope.** Exploration only: data cut at 2015-03-18 (the end of the first fold's training window), events from 2005-01-03 to 2014-12-31. No data from the walk-forward period was read. 15 rule simulations per run. The ATH is measured since 2005-01-03, so 2005–2006 highs are pseudo-ATHs (the 2000 peak is not in the data). **30 exploration trials have now been spent on this idea** (15 uncorrected, 15 corrected; the duplicate corrected run adds 15 more log entries with identical results).

**Sample size (corrected data).** Days within 1% of the ATH: 409 (2005: 30, 2006: 81, 2007: 61, 2013: 101, 2014: 136). They cluster into 12 separate episodes (15 within 0.5%, 8 within 2%, 14 for 52-week highs). Statistical power is low.

**Forward returns after near-ATH days** (log return from the 15:59 fill, compared with all days; monthly block bootstrap of the difference):
- After **1–20 sessions**, the event mean was close to 0 and **slightly negative** for the two tighter thresholds (within 0.5%: −0.02% to −0.14%; within 1%: −0.03% to −0.09%), against +0.02% to +0.43% for all days. **Every 95% interval of the difference includes 0.**
- After **40–60 sessions** the event mean was positive (+0.45% to +1.40%), close to the all-day mean.
- Prices rose less than usual for about a month after near-ATH days, and roughly flat at the tightest thresholds, but did not fall significantly.

**Rule simulations** (sell when the 15:58 close is within 0.5% / 1% / 2% of the ATH; buy back after 5 / 20 / 60 decisions or after a 2% / 5% dip; forced after 60 decisions; buy-and-hold +69.0%):

| ATH within | delay 5 | delay 20 | delay 60 | dip 2% | dip 5% |
|---|---|---|---|---|---|
| 0.5% | **+7.1** | **+5.0** | −3.4 | **+2.7** | **+11.7** |
| 1% | −7.9 | −7.7 | −19.4 | −13.0 | −2.1 |
| 2% | **+1.0** | −23.6 | −46.9 | −24.1 | −29.9 |

*(excess return over buy-and-hold, pts)*
- **5 of 15 rules beat buy-and-hold**, 4 of them at the 0.5% threshold. The best (within 0.5%, buy back after a 5% dip or 60 decisions): +80.7%, Sharpe 0.41 vs 0.36, max drawdown −55.2% vs −56.4%.
- **The pattern is not smooth:** every rule at the 1% threshold lost, although it contains all the 0.5% days. A real "sell near the top" effect would be expected to weaken gradually with the threshold, not to flip sign between 0.5% and 1%.
- **Max drawdown was about unchanged (−52% to −56%) for every rule:** the 2008 crash started months after the October 2007 ATH, and the 60-decision cap had already put the strategy back in.
- **Most buy-backs were forced, not chosen.** Within 1% of the ATH with a 5% dip: 17 episodes; 5 bought back after a dip (+5.3% to +6.1% more shares each), 11 were forced back in after 60 decisions (mostly at higher prices, down to −6.0%), 1 ended with the window. 35% of episodes bought back lower.
- Even the best rule adds less than 1% per year (+11.7 pts of cumulative return over 10 years), from about 15 episodes.

**Uncorrected run (2026-10-04, `ath_exit_exploration`), for the record:** 14 of 15 rules lost by 6 to 39 pts; the only winner was within 0.5% with a 5-day delay (+8.3 pts). The fake 2007 highs had removed most 2005–2007 near-ATH days.

**Conclusion (2026-10-05).** On corrected data the idea looks better than first reported, but the evidence is weak: no forward-return difference is significant, the positive rules sit at one threshold while the next threshold loses everywhere, the sample holds about 15 episodes, drawdown is not reduced, and 30 trials have been spent. It is **not evidence of an edge**. If it is pursued, the threshold and the buy-back rule must be fixed in a protocol *before* any 2015–2026 data is looked at, evaluated through walk-forward validation, and the 30 exploration trials counted. Choosing the 0.5% / 5% dip rule *because* it was best here would be selection on the exploration results.

---

## Independent audit (2026-10-05, `docs/AUDIT_2026-10-05.md`)

A new assistant audited the workspace at commit `ba94815` against the raw minute bars. Full findings in the audit document; the results are recorded here.

**Reproduced exactly (corrected data):**
- the 62 bad tick cells (`records/bad_tick_corrections.csv`, recomputed from the uncorrected file);
- step 10: buy-and-hold +69.0%, k = 4 with a 5-day delay +62.9%, MA200 +50.4%;
- step 12: all 18 candidates (+54% to +230% vs +243%), mean AUC (logistic 0.523 / 0.470, LightGBM 0.515 / 0.512) and the prior-only selection (+111.7% vs +237.2%, 20 of 43);
- the uncorrected step 12 run (+66% to +195%; prior-only +141.1%, 23 of 43).

Both test suites pass. Step 00 on the corrected data reports 0 bad ticks (saved output), which closes that open verification.

**Bad tick sensitivity (new trials: `audit_bad_tick_sensitivity_v2`, 1,584 validation entries, no test window).** The 3% rule leaves smaller wicks that look like the same feed errors, including some in 2015–2026 (e.g. 2020-05-14 09:40 low 272.99 vs ~278.4; 2025-05-27 13:13 low 578.43 vs ~590). Re-running step 12 with the same rule at 2% and at 1.5% (in memory, v2 rules unchanged) gave:

| Cleaning | Best candidate after the fact | Candidates above buy-and-hold | Prior-only selection |
|---|---|---|---|
| 3% (official) | +229.7% | 0 of 18 | +111.7% (20 of 43) |
| 2% | +227.7% | 0 of 18 | +103.1% (19 of 43) |
| 1.5% | +276.3% (all, k = 4, offset 0) | 1 of 18 | +104.2% (19 of 43) |

- The **v2 verdict is unchanged**: the prior-only selection loses at every cleaning level.
- The **ranking of candidates is not robust**: changing 0.01% of the cells changed 189 of 792 candidate-quarters, and at 1.5% one candidate ends above buy-and-hold. The 1.5% and 2% runs are a perturbation check, not design candidates; none is to be selected.

**Statistical power (from the 44 quarterly validation excess returns per candidate).** The quarterly excess return has a standard deviation of 2.0–6.6 points. The smallest true excess return detectable with 80% power at the 5% level is about +3.4 to +11 points per year (median +6.7). A realistic edge over buy-and-hold cannot be "statistically supported" on 2015–2026 alone.

**Other audit observations, for the record:**
- The v1 shortfall (+158% vs +230%) matches zero-skill exposure of about 79% of the time. The "capping winners" interpretation is questioned (audit F3; the best setting's exposure is still to be checked).
- v2's forced re-entry after 60 cash decisions and the reset to invested at each window start mean that only short exits were tested (audit F4).
- `records/trial_log_snapshot.csv` and `records/model_dataset_verification.csv` are missing, and the tag `v2-final` is not in the repository (audit F7).

