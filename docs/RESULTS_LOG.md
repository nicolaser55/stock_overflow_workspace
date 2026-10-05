# Stock Overflow: Results Log

*The chronological record of experiment outcomes of the reorganized workspace (from 2026-10-05), for the thesis. Each entry
states what was run, under which protocol version and configuration hash, what was observed, and what the evidence does and
does not support. Failures are results. Test windows touched so far: **none**.*

*Earlier results (v1, v2, the step 13 exploration, the bad tick correction and the audit) are in
`docs/history/RESULTS_LOG_2026-10-05.md`; their 4,089 trials are in `records/legacy/trial_log_legacy_20261005.csv` and
still count.*

## How to add an entry

For every notebook run: date, experiment and step, protocol version, config hash (printed in the header cell), the trial-log
entries added (stage and count), the headline numbers (copy them from the saved outputs), and what they support. For
walk-forward runs, always report: the best candidate after the fact (labelled optimistic), the **prior-only path** with its
minimum detectable effect, the **information test** (model vs its uninformed baselines), and time in the market.

## Summary

| Experiment | Protocol | Status | One-line outcome |
|---|---|---|---|
| `exp01_minute_entry` | 1.0 | Not yet run | — |
| `exp02_stop_reentry` | 1.0 | Not yet run | — |
| `exp03_ath_exit` | 1.0 | Not yet run | — |

## Reproduction checks for the re-run

The trading rules of exp01 and exp02 and the exp03 exploration rules are unchanged, and every run is deterministic, so the
re-run must reproduce these earlier numbers (corrected data). A difference means something changed in the data or the code.

| Notebook | Expected |
|---|---|
| exp02 step01 | buy-and-hold 2005-2014 +69.02% (Sharpe 0.36, drawdown −56.44%); k = 4 with a 5-day delay +62.91%; 200-session rule +50.39% |
| exp02 step03 | 18 candidates from +53.8% to +229.7% vs +243.4% chained buy-and-hold; mean AUC logistic 0.523 (10y) / 0.470 (all); prior-only path +111.66% vs +237.21%, 20 of 43 quarters |
| exp02 step02 | 0 signals (the verdict cannot change with the month minimum: no bin passed training in v2) |
| exp03 step01 | buy-and-hold +69.02%; 5 of 15 rules above it; best: within 0.5%, 5% dip, +80.69% (+11.68 pts) |
| exp01 step03 | validation candidates identical to `lgbm_ev_policy_v1_clean` (best setting +158% vs +230%; at most 16 of 45 quarters) |
| exp01 step02 | new result (base-rate check); the old break-even check found 1,339 training passes and 0 signals |

*Verification run by the assistant (2026-10-05).* To test the reorganized code, the assistant executed pipeline steps 00
and 06 and the notebooks of exp02 (steps 01-03) and exp03 (steps 01-02) once, in its sandbox, on a copy of the same
corrected raw data. The exp02 and exp03 exploration numbers above were reproduced exactly. That run also produced the first
exp03 walk-forward and the new validation baselines, so those results were seen by the assistant before Nicolas's official
run; no rule, grid or baseline was changed afterwards. exp01 was smoke-tested on synthetic data only (a 2010-2022 random
walk with random indicator columns, so no real result was seen). That smoke test showed that the exp01 base-rate signal
check returns CONTINUE on data without any signal (2 signals in one bin of 3,255 tests, about 4 expected by chance); the
verdict now also prints the chance count, and the rule itself is an open decision (`experiments/exp01_minute_entry/PROTOCOL.md`
§13).

## exp01_minute_entry

*Not yet run.*

## exp02_stop_reentry

*Not yet run.*

## exp03_ath_exit

*Not yet run.*
