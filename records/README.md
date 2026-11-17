# Records

Versioned CSV records (the root `.gitignore` excludes `*.csv` except in this folder). All files here are protected
(`protected_paths.txt`): only the scripts named below write them, and only Nicolas runs those scripts.

| File | Content | Written by |
|---|---|---|
| `holdout_windows.csv` | The registered holdout windows (start, end, status) | `scripts/holdout_window.py` (append; a retired row is filled once) |
| `bad_tick_corrections.csv` | The 62 raw cells corrected on 2026-10-04 by the bad-tick rule | `scripts/fix_raw_bad_ticks.py --apply` (append) |
| `bad_tick_invalidated_dates.csv` | The per-day pipeline files rebuilt after that correction | final, never edited |
| `legacy/pilot_designs.csv` | The tried-designs ledger: every design tried before the judge v1 freeze (the pilot phase), as source, experiment, stage and settings only (no results, no window dates, no notes). Made on 2026-11-03 from the two pre-reset records (the trial log of 2026-10-05 -> 2026-10-22 and the 2026-10-05 bad-tick audit trials; 9,296 rows, 260 designs, same design keys); those files and their numbers were removed from the repository (they stay in git history) | `scripts/reset_records.py` (append only) |
| `legacy/registered_versions.csv` | Every experiment version the pre-registration guard has seen: source, experiment, protocol version, design-folder hash and helper hash (no results, no dates). Seeded on 2026-11-09 from the trial log the first reset moved (`reset_20261109_193443`); without it a reset made every logged version look new and the guard refused all nine baseline reruns. The guard reads it together with the trial log, so the folder-hash lock, the helper-hash lock and the three-version limit hold across resets | `scripts/reset_records.py` (append only; `--register-from` for a backed-up log) |
| `agent_phase.txt` | The phase switch: `development` until roadmap R6, then `agents` (results log in grades only; no more resets) | Nicolas, by a one-line merge |

Since 2026-11-10 (decided by Nicolas) the verdict's multiple-testing N counts the trial log and this ledger together:
the distinct designs over both (`so/core/multiple_testing.py`, `get_tried_design_count_dict`). The pilot's results
were discarded, but its designs still count. The trial-log count alone is reported as information. (From 2026-11-03
to 2026-11-10 the ledger did not enter the verdict.) From R6 nothing is reset and everything counts.

The holdout evaluation ledger (`holdout_evaluations.csv`, one row per evaluation with its results) is not here: it lives
under `SO_HOLDOUT_PATH`, which agents cannot read, so holdout outcomes never reach design work.

The trial log (the multiple-testing record) is `store04_experiments/trial_log.csv` in the data folder; it is only
appended to, through `so.core.trial_log`.
