# Records

Versioned CSV records (the root `.gitignore` excludes `*.csv` except in this folder). All files here are protected
(`protected_paths.txt`): only the scripts named below write them, and only Nicolas runs those scripts.

| File | Content | Written by |
|---|---|---|
| `holdout_windows.csv` | The registered holdout windows (start, end, status) | `scripts/holdout_window.py` (append; a retired row is filled once) |
| `bad_tick_corrections.csv` | The 62 raw cells corrected on 2026-10-04 by the bad-tick rule | `scripts/fix_raw_bad_ticks.py --apply` (append) |
| `bad_tick_invalidated_dates.csv` | The per-day pipeline files rebuilt after that correction | final, never edited |
| `legacy/trial_log_snapshot_20261022.csv` | The trial log of 2026-10-05 -> 2026-10-22 (7,712 rows), deleted at the 2026-10-22 reset and restored from commit `237f60c^` on 2026-10-25 | final, never edited |
| `legacy/audit_trials_20261005.csv` | The 2026-10-05 bad-tick audit trials (1,584 rows), restored the same way | final, never edited |

The two legacy files count in the multiple-testing adjustment (`so/core/multiple_testing.py`): every design tried on
this development data raises the bar, including those tried before the reset (Nicolas, 2026-10-25).

The holdout evaluation ledger (`holdout_evaluations.csv`, one row per evaluation with its results) is not here: it lives
under `SO_HOLDOUT_PATH`, which agents cannot read, so holdout outcomes never reach design work.

The trial log (the multiple-testing record) is `store04_experiments/trial_log.csv` in the data folder; it is only
appended to, through `so.core.trial_log`.
