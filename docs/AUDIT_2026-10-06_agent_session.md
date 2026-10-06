# Audit of the Cursor agent's session (exp04-exp07), 2026-10-06

*Independent audit by the assistant (not the author of the code under review) of branch `agent/research` of
`nicolaser55/stock_overflow_workspace`, commits `ebaaf03` → `44e2d83` (2026-10-06 14:02 → 14:58), plus `6044e3a`.
Method: code review of every new or changed shared module and rule file; re-execution of all eight new notebooks and of
exp02 step 03 / exp03 step 02 on a separate machine with a copy of the same corrected raw data; an independent
re-implementation of the exp04 rule and of buy-and-hold; checks of commit order, trial log and data scope.*

## Verdict

**The results stand.** Every number reported by the agent was reproduced exactly; the independent simulator agrees to the
cent; pre-registration preceded every run; the untouched window was never read; no look-ahead was found. Four issues
need a correction or a disclosure in the record (I1-I4); none changes a conclusion. exp04, exp05, exp06 and exp07 are
correctly stopped: none beats buy-and-hold on the prior-only path.

## Verified

| # | Check | Evidence | Result |
|---|---|---|---|
| V1 | Reproducibility | The 8 notebooks of exp04-exp07 re-executed in the auditor's sandbox (`validation_only`, separate data folder): all printed numbers identical to the committed outputs; only timestamps and trial ids differ | Pass |
| V2 | Independent re-implementation | Own code (200-session average from session closes, 15:58 decision, 15:59 open fill, $0.01 slippage, IBKR fees, sale at the last close) over 2015-04-17 → 2026-04-15: x = 0, n = 1 **+108.03%, 35 exits**; x = 3%, n = 5 **+123.36%, 6 exits**; buy-and-hold **+235.39%**, all equal to the agent's. Own MA distance equals `ma200_dist_pct` to 5e-11 | Pass |
| V3 | Shared code change | `simulate_stop_reentry_dict` gained an optional cooling-off (`exit_block_until`, default −1 = no effect). With the new code, exp02 step 03 (+111.66% vs +237.21%) and exp03 step 02 (+143.05% vs +237.21%) reproduce; all 8 test suites pass. `so/config.py` unchanged, so exp01-exp03 hashes unchanged | Pass |
| V4 | Pre-registration | Each `preregister expNN` commit contains protocol, config, rules, tests and notebooks **without outputs**; the first trial-log entry of each experiment is 24-36 s after its pre-registration commit (exp04 14:21:59 → 14:22:35; exp05 14:34:28 → 14:34:52; exp06 14:46:37 → 14:47:04; exp07 14:54:26 → 14:54:51); after pre-registration only change-log lines were added to the protocols, configs and rules unchanged | Pass |
| V5 | Untouched data | Replays receive bars up to 2026-04-15 only ("Bars given to the simulator: 2005-01-03 -> 2026-04-15"); a guard in `so/core/continuous_replay.py` refuses windows reaching 2026-05-14; `test_window_touched` is False for all 3,292 trial-log rows; no `test` stage | Pass |
| V6 | Look-ahead | MA from the previous 200 complete sessions; exp07 lights from daily features covered by the no-look-ahead test; exp05 target volatility = quantile of values before each period; the candidate selected at period f governs period f + 1 only (tested) | Pass |
| V7 | Trial counts | exp04 9 + 396 + 1 = 406; exp05 1 + 4 + 176 + 1 = 182; exp06 12 + 528 + 1 = 541; exp07 3 + 132 + 1 = 136; total 1,265; snapshot 3,292 rows | Pass |
| V8 | Buy-and-hold figures | +235.39% = full span from 2015-04-17 (candidate paths); +229.74% = prior-only span from 2015-07-17 (period 0 has no earlier selection; 3.3539 / 1.0171 ≈ 3.2974); +237.21% = exp02/exp03 quarters chained (each quarter re-bought) | Consistent |
| V9 | Statistical choices | 6-month bootstrap blocks fixed in each pre-registered config; 1-month version reported alongside | Pass |

## Issues

| # | Severity | Issue | Action |
|---|---|---|---|
| I1 | Moderate (disclosure) | **exp07 re-entry deviates from the roadmap** (the "or exp06's buy-stop" option was dropped). The design commit `30c8c96` (14:49:13) came 51 s after exp06 step 02 had logged its summary (14:48:22); the agent states the choice was made before reading exp06's outputs, which cannot be verified, and the exp07 protocol's motivation cites exp06's result ("wrong four times out of five"), so the protocol text was at least finalized after it. Thresholds and grid came from the roadmap and are unaffected; the direction of the effect of dropping the buy-stop is unknown | Record in exp07's protocol and results log: "re-entry choice possibly informed by exp06's results" |
| I2 | Minor (wording) | exp06's results log says the signals "are not pure noise" and "carry some timing information" because the path beat 19/20 random exits and 15/20 random re-entries. With 20 runs that is an empirical p ≈ 0.10 and ≈ 0.29, for a data-dependent design, 12 candidates and ~7,400 trials: not evidence of information | Reword: "consistent with weak timing information; not statistically supported" |
| I3 | Minor (acknowledged by the agent) | exp05's "constant exposure" baseline is not constant: the 20-point dead band means it never rebalances and drifts from 86.3% to a mean of 90.9%; the step 01 column is invalid (weight 1 at the first session). The verdict rests on the random-shift baseline (path beats 3/20) and buy-and-hold, so it stands | If exp05 is cited, describe the baseline as "buy 86% and hold"; a band-free constant baseline would need a new version |
| I4 | Minor (chat summary only) | The agent's chat summary says exp07 had "12 exits, none bought back lower": 11 were closed and bought back higher, the 12th was open at the end (valued at the last close, also higher). The results log is correct. The summary's "high-volatility periods did not have lower returns" is a simplification of the log's more careful statement (no monotone pattern in 2005-2014; the timing added nothing in 2015-2026) | None (the record is correct) |
| I5 | Informational | The `supported` flag only tests a positive excess. For exp04 (log excess −6.07%/yr, 95% [−10.54%, −2.14%]) and exp07 (−7.33%/yr, [−12.55%, −3.49%]) the **underperformance** is statistically supported; exp05 and exp06 intervals include 0 | State it explicitly in the cross-experiment write-up |
| I6 | Informational (process) | Four experiments were built, pre-registered, run and documented in 56 minutes without human review before running. Integrity rested on the roadmap fixed beforehand, which held. The 2015-2026 span has now been used by seven experiments (~7,400 trials) and exp04-exp07 were designed with knowledge of famous episodes (2008, 2020): it is development data; any future positive result needs the untouched window or new data | Keep in the thesis limitations |

## Notes for the write-up

- exp05 is the only design with a better risk profile on 2015-2026 (Sharpe 0.73 vs 0.71, maximum drawdown −23.2% vs
  −34.2%), but at 72% of buy-and-hold's total return, and its timing beats only 3 of 20 random shifts: the lower drawdown
  comes from holding less SPY, not from the volatility signal.
- Exploration (2005-2014) favoured exp04, exp05 and exp07 through 2008 alone; every design lost on 2015-2026. This
  contrast between the two periods is itself a result worth reporting.
