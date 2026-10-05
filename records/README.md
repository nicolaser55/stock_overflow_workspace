# Records

Research records that must be versioned even though they are CSV files (the root `.gitignore` excludes `*.csv` except in
this folder and its sub-folders).

| File | Content | How to update |
|---|---|---|
| `bad_tick_corrections.csv` | The 62 raw cells corrected on 2026-10-04 by the bad tick rule (timestamp, column, old and new value, distance, file, row, threshold, run time, backup folder) | Appended by `scripts/fix_raw_bad_ticks.py --apply`, never by hand |
| `bad_tick_invalidated_dates.csv` | The per-day files of the old steps 01-06 moved for regeneration after the correction (record of the targeted rebuild of 2026-10-04/05) | Final; never edited |
| `trial_log_snapshot.csv` | Copy of `store04_experiments/trial_log.csv` (the multiple-testing record of the reorganized workspace) | After each working session on nicodesktop: copy, commit, push |
| `legacy/trial_log_legacy_20261005.csv` | The previous trial log (4,089 entries, 2026-10-03 → 2026-10-05): v1, v2, step 13 | Copied once on 2026-10-05; never edited |
| `legacy/audit_trials_20261005.csv` | The 1,584 validation entries of the audit's bad tick sensitivity check (`audit_bad_tick_sensitivity_v2`) | Final; never edited |

The trial logs are the multiple-testing record of the thesis (how many things were tried before a result was reported).
Never edit or delete their rows.
