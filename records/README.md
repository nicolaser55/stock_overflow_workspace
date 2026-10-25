# Records

Versioned CSV records (the root `.gitignore` excludes `*.csv` except in this folder). All files here are protected
(`protected_paths.txt`): only the scripts named below write them, and only Nicolas runs those scripts.

| File | Content | Written by |
|---|---|---|
| `holdout_windows.csv` | The registered holdout windows (start, end, status) | `scripts/holdout_window.py` (append; a retired row is filled once) |
| `holdout_evaluations.csv` | One summary row per holdout evaluation (created by the first evaluation) | `scripts/holdout_evaluate.py` (append) |
| `bad_tick_corrections.csv` | The 62 raw cells corrected on 2026-10-04 by the bad-tick rule | `scripts/fix_raw_bad_ticks.py --apply` (append) |
| `bad_tick_invalidated_dates.csv` | The per-day pipeline files rebuilt after that correction | final, never edited |

The trial log (the multiple-testing record) is `store04_experiments/trial_log.csv` in the data folder; it is only
appended to, through `so.core.trial_log`.
