# Update Guide (2026-10-06): from the first run to the decisions of 2026-10-05

*For the situation of 2026-10-06: the **first** zip of 2026-10-05 was installed and all 10 notebooks of
`docs/RERUN_GUIDE_2026-10-05.md` §E were run. The **second** zip of that day adds Nicolas's three decisions (exp01 null
calibration, exp03 baselines kept, secondary criterion "either"). This guide applies only the differences, keeps every
executed notebook and adds exactly one notebook run.*

## What differs between the first and the second zip

| File | Change | Effect on the first run |
|---|---|---|
| `experiments/exp01_minute_entry/config.py` | + `SIGNAL_CHECK_NULL_RUN_COUNT = 19`, `SIGNAL_CHECK_NULL_SHIFT_SHARE_RANGE = (0.25, 0.75)` | exp01 config hash `16493e598a` → `15716b01a3` |
| `experiments/exp01_minute_entry/signal_check.py` | + session-shifted null runs; verdict calibrated on them | the first run's verdict is the **uncalibrated** one |
| `experiments/exp01_minute_entry/step02_signal_check.ipynb` | runs the 19 null runs, saves `null_run_data.csv` | **re-run once** |
| `so/core/evaluation.py` | + `secondary_success` = Sharpe flag **or** drawdown flag | none: both flags are already printed |
| `experiments/exp02_stop_reentry/step03_walk_forward.ipynb`, `experiments/exp03_ath_exit/step02_walk_forward.ipynb` | one extra print line (`secondary met (either)`) | none: **not** in the update pack, keep your executed versions |
| `tests/test_shared_and_exp01.py`, `tests/test_exp02.py` | tests of the null and of "either" | — |
| `experiments/*/PROTOCOL.md`, `docs/RESULTS_LOG.md`, `docs/RERUN_GUIDE_2026-10-05.md`, this guide | the decisions and this situation recorded | — |

Unchanged: everything else, including the exp02 and exp03 config hashes (`53a86cd30f`, `b8523207d1`) and every other
notebook.

## A. Save the first run (before copying anything)

1. Snapshot the trial log: copy `C:\Users\nico\Desktop\stock_overflow_data\store04_experiments\trial_log.csv` to
   `<workspace>\records\trial_log_snapshot_20261006_first_run.csv`.
2. Check that `records\legacy\trial_log_legacy_20261005.csv` (rerun guide C.1) is in the workspace.
3. Commit the executed notebooks with their outputs and tag the state:

   ```
   git add -A
   git commit -m "first run of exp01-exp03 (first zip of 2026-10-05), executed notebooks"
   git tag first-run-20261006
   git push
   git push --tags
   ```

## B. Copy the update pack over the workspace (do not delete anything)

`stock_overflow_update_20261006.zip` contains only the changed files, in the workspace layout. From the workspace folder
in PowerShell:

```
Expand-Archive -Path <path to stock_overflow_update_20261006.zip> -DestinationPath $env:TEMP\so_update -Force
Copy-Item -Path $env:TEMP\so_update\stock_overflow_workspace\* -Destination . -Recurse -Force
git status
```

`git status` must list only the files of the table above (minus the two exp02/exp03 notebooks). Do **not** copy the full
second zip over the workspace: it would replace your executed notebooks with empty ones and remove
`records\legacy\trial_log_legacy_20261005.csv`. If you had edited `docs\RESULTS_LOG.md`, merge your edits back in.

## C. Check the environment

1. No reinstall is needed (the editable install reads the new files). Restart the Jupyter server or every kernel.
2. `venv-main\Scripts\python tests\run_all_tests.py` → "All test suites passed ✅" (it now includes "signal check null").

## D. Data folder

Nothing to delete and nothing to add. The re-run of exp01 step 02 overwrites
`store04_experiments\exp01_minute_entry\step02_signal_check_data\signal_check_data.csv` and `base_rate_data.csv` (same
content) and adds `null_run_data.csv`. The trial log keeps every entry of the first run.

## E. Run (one notebook)

| Notebook | Time | Check |
|---|---|---|
| `experiments/exp01_minute_entry/step02_signal_check.ipynb` | reading as before + ~2 min for the real check + 19 null runs spread over all CPU cores (about 14 min on 2 cores) | see below |

- The header **warns** that an earlier `signal_check` entry exists (hash `16493e598a`, current `15716b01a3`). Expected:
  this run adds one trial-log entry. Run it once.
- The real check is deterministic: `test_count`, `train_pass_count`, `signal_count`, `signal_feature_list` and
  `signal_delta_list` must equal the first run's (in the notebook committed at `first-run-20261006`). A difference means
  something changed in the data or the code: stop and send both notebooks.
- New: `signal_bin_count`, the 19 null counts, `null_p_value` and the **calibrated verdict**, which is the protocol's
  verdict (§13). The first run's uncalibrated verdict stays on record.

Do **not** re-run anything else:

- exp01 step 01: the model dataset is unchanged.
- exp01 step 03: it does not read the two new constants; re-running would log 120 duplicate validation trials with
  identical numbers. Its entries keep hash `16493e598a`, which differs from `15716b01a3` only by those constants.
- exp02 and exp03: "secondary met" = the printed Sharpe flag **or** the printed drawdown flag.

## F. After the run

1. Copy `store04_experiments\trial_log.csv` to `records\trial_log_snapshot.csv`.
2. Commit the executed step 02 notebook and the update; push.
3. Send the executed notebooks for `docs/RESULTS_LOG.md`: pipeline steps 00 and 06, exp02 steps 01-03, exp03 steps 01-02,
   exp01 steps 01-03, and both versions of exp01 step 02 (first run and re-run), or their outputs.

*Note for the record:* in the first run, exp01 step 03 was run regardless of the step 02 verdict (the rerun guide ran
every notebook in order). Under the protocol, a STOP at step 02 would have ended the experiment before step 03, so if the
calibrated verdict is STOP, the walk-forward results are reported as run past the stopping rule.
