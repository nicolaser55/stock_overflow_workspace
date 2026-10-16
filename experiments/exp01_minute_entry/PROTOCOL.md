# exp01_minute_entry_v2: Protocol

*Version 2.0 (2026-10-12). Experiment name `exp01_minute_entry_v2`. Config: `experiments/exp01_minute_entry/config.py` + `so/config.py`.*

**Label: re-run under the new rules, not new evidence.** Nothing was tuned and no rule was added. The signal check of protocol 1.0 already stopped the experiment (2 distinct signal bins vs a null maximum of 4, p = 0.10). That check is not repeated, and this replay does not reverse that STOP. No further version may follow from this result.

## 1. Question, grid, selection, baselines, success and stopping (protocol 1.0 / 1.1)

Does a long-only minute entry, bought when a take-profit model's expected net return clears a threshold, beat buy-and-hold's total return after costs?

Grid, 12 candidates: training window L ∈ {3, 5, 10} years × expected-net-return threshold ∈ {0, 0.02%, 0.05%, 0.10%}. The model is one LightGBM classifier per distance, with the parameters, the 15-minute sampling and the uniqueness weights of protocol 1.0. Features are the same registered columns (ratio, bounded, categorical, count, time).

Selection: the previous quarter's total return. Ties: the shorter window, then the higher threshold. The choice at period f governs period f + 1.

Baselines: 20 random entries at the path's buy rate, and a fixed entry at the 09:59 decision (10:00 open) with a 0.50% distance. Same simulator and costs.

Stopping, from protocol 1.0 §13 step 03: STOP if the prior-only path does not beat buy-and-hold and does not beat the random-entry baseline. Otherwise: candidate result pending review. No success is claimed. The multivariate check of protocol 1.1 is not repeated; it could not reverse the STOP.

## 2. Version 2.0 changes (machinery only)

- The development end is the session an embargo of 10 before the registered holdout start.
- Features (TSIND, TSSEG, TSCTX) and barrier labels (TSBAR) are read through `DataContext`, with SPY minute bars.
- The model is refit on the first session of each ISO week, on rows inside the candidate's window whose `label_known_ts` is strictly before that refit's first decision. An unfinished label is dropped and counted out of the fit. It is not filled with 0. There is no fallback window. Sessions before the first refit that has 200 knowable rows are not scored. A later refit with fewer than 200 rows raises.
- A refit whose model cannot govern a scored session is not executed. The calendar is still the full one: sampled sessions from the first through the last, the first session of each ISO week, and the first session of that span. The walk starts at the latest calendar refit on or before the first scored session and stops at the last scored session. Earlier refits are not fit. The 200-row rule still applies to them, and a short refit after a successful one still raises. The model that governs each scored session is unchanged.
- The TSBAR files do not store `label_known_ts`. Each distance cell stores `exit_bar_count` (minute bars from `entry_ts` to the exit bar). The row clock is the end of the latest of those bars, including distances the model does not train. A slower unused distance can only delay the row. A cell with reason `NA`, a negative count, a missing entry bar, or an exit bar outside the loaded minute bars leaves the whole row unfinished.
- Stored `decision_ts` and `entry_ts` are timezone strings. They are parsed to New York timestamps before the 15-minute sample, the same conversion protocol 1.0 applied. The sample still keeps 10:00, 10:15, 10:30 and so on.
- A quarter's score is that quarter's simulation, using the weekly models. The prior-only path is one simulation that switches window and threshold at period boundaries.
- The first period uses the first listed candidate (`3Y|0.0000`). Protocol 1.0 started the prior-only path at the second quarter.
- No holdout evaluation is run by the agent.

## 3. Data sources

`SPY_1MIN`, `TSIND`, `TSSEG`, `TSCTX`, `TSBAR`.

## 4. Trial budget

12 × 44 + 1 = **529**. Fewer development quarters log fewer rows. The signal-check trials are not repeated.

## 5. Known limitations

The signal check already failed. Dividends ignored, cash at 0%, informal costs. Weekly refits use the same model class as the old once-per-quarter fit; the schedule of the fit is the machinery change. Positions can stay open past a quarter's end, so a quarter score and the continuous prior-only path are not the same object. Both are reported.

## 6. Change log

| Version | Date | Change |
|---|---|---|
| 1.0 / 1.1 | 2026-10 | Signal check STOP (p = 0.10). Multivariate check added after the fact and could not reverse it. Code at tag `pre-port-20261012`. |
| 2.0 | 2026-10-12 | Re-run under the new rules, not new evidence. Weekly refits, windows 3, 5 and 10 years, label purge (§2). |
| 2.0 | 2026-10-13 | Preregister amendment, before any version 2.0 run. Scores within NUMERIC_TOLERANCE (1e-6) of the best pooled score are tied, then this protocol's tie order. A comparison counts a difference of at most 1e-6 as a match and also reports the maximum absolute difference. Summary prints show 6 decimal places. Calculations, and files later code reads, stay at full precision. |
| 2.0 | 2026-10-13 | Preregister amendment, before any version 2.0 run. The development run of 2026-10-13 06:10 failed before any trial row: the stored TSBAR cells have no `label_known_ts`. The clock is the end of the latest stored exit bar; an unresolved cell leaves the row unfinished (§2). No grid, threshold, window, cost, baseline, selection, or stopping rule changes. |
| 2.0 | 2026-10-14 | Preregister amendment, before any finished version 2.0 run. The development run of 2026-10-13 16:57 failed inside the first candidate of period 0: stored `entry_ts` is a string, and interval sampling reads `.dt`. The strings are parsed to New York timestamps before sampling (§2). Sessions before the first refit that has 200 knowable rows are not scored; a later refit below 200 rows still raises, and the window is not shortened. No rule, grid, window, cost, baseline or stopping rule changes. |
| 2.0 | 2026-10-14 | Preregister amendment, before any finished version 2.0 run. The weekly calendar starts at the first sampled session, 2005-01-03. With the embargo of 10 the development end is 2025-07-31 (42 periods). Session files through that date give 1,074 weekly refits: 526 before the refit that governs period 0 (2015-02-02, a Monday refit) and none after the last scored session. Those 526 fits are not executed (§2). On the first two periods, 2015-02-02 → 2015-07-31, all three windows and all 12 candidates matched the unskipped loop: 2,893 scored rows, maximum absolute probability difference 0, model-id difference 0, decision and period-score difference 0, inside NUMERIC_TOLERANCE 1e-6. The unused weeks' row counts matched the training mask on all 526 weeks for 3Y, 5Y and 10Y. No trial-log row was written. No rule, grid, window, cost, baseline or stopping rule changes. |
| 2.0 | 2026-10-15 | Holdout report baselines are the development report's uninformed baselines over the span passed in, with this protocol's fixed seeds, through the point-in-time context. Report-only: no rule, grid, threshold, window, cost, baseline, selection or stopping rule changes. Development results unchanged. |
