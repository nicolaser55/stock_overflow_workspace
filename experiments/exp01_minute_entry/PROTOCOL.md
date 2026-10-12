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
- The model is refit on the first session of each ISO week, on rows inside the candidate's window whose `label_known_ts` is strictly before that refit's first decision. An unfinished label is dropped and counted out of the fit. It is not filled with 0. There is no fallback window. A refit with fewer than 200 rows raises.
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
