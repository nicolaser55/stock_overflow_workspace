# Pipeline (shared data, steps 00-06)

The pipeline turns the raw IBKR minute bars into per-day features and targets that every experiment can use. Its outputs
are **kept across experiments**: re-running an experiment never requires re-running the pipeline.

| Step | Notebook | Output | Used by |
|---|---|---|---|
| 00 | `step00_data_quality_check.ipynb` | `store02_workzone/step00_data_quality_report/` | everyone (run first, and whenever raw data changes) |
| 01 | `step01_PA_ohlcv_data_collection.ipynb` | `store02_workzone/step01_PA_ohlcv_data/` (per-minute snapshots, cache) | steps 02-03 |
| 02 | `step02_TSIND_data_collection.ipynb` | `store02_workzone/step02_TSIND_data/` (43 indicator fields per minute) | exp01 |
| 03 | `step03_TSSEG_data_collection.ipynb` | `store02_workzone/step03_TSSEG_data/` (segments, `cum_max`) | exp01 |
| 04 | `step04_TSCTX_data_collection.ipynb` | `store02_workzone/step04_TSCTX_data/` (context features, tested for look-ahead) | exp01 |
| 05 | `step05_TSBAR_data_collection.ipynb` | `store03_goldzone/step05_TSBAR_data/` (barrier targets, 32 SL/TP distances) | exp01 |
| 06 | `step06_TSDAY_data_collection.ipynb` | `store02_workzone/step06_TSDAY_data/TSDAY_data.csv` (one row per session) | exp02, exp03 (they rebuild it in memory; this file is the record) |

Steps 00-05 are the notebooks of the previous workspace with only their imports changed (logic unchanged); their caches
(steps 01-05) were built and corrected on 2026-10-04/05 and are kept as they are. Step 06 is the former step 09 (TSDAY)
without its result tables (base rates by year belong to the experiments, which control which period they look at).

The code lives in `so/features/` (snapshots, indicators, context, barrier labels, daily features) and `so/core/`
(raw data, data quality, bad ticks, execution rules). Constants are in `so/config.py`. **Changing a pipeline constant
changes the meaning of the cached files**: regenerate the affected steps and start new experiment versions.

## When new raw data arrives

1. Run step 00. If it reports bad ticks: `python scripts/fix_raw_bad_ticks.py` (dry run), then `--apply`, then step 00 again.
2. Run steps 01 -> 04 for the missing dates (ignore mode `"I"`).
3. Run step 05: regenerate the incomplete dates (mode `"W"`), then the missing ones.
4. Run step 06.
5. Experiments: exp01 step 01 regenerates its 30 most recent model dataset days and adds the missing ones; exp02 and exp03
   read the raw data directly.

Note: the walk-forward schedule is anchored on the last session of the data, so new data shifts every fold window.

## Known limitations (kept as they are)

- The bad tick rule (3%) leaves smaller wicks of the same kind (1.5-3%), including some in 2015-2026
  (`docs/history/AUDIT_2026-10-05.md`, F1). Rules that trigger on minute lows can be affected.
- 2007-07-02 is missing (not available from IBKR); 2009-07-27 and 2013-12-23 are partial sessions.
- Prices are not adjusted for dividends: ex-dividend dates show as small overnight drops.
- `TSSEG` 2021-08-24 differs from a regeneration (cause not identified; only exp01 uses TSSEG).
- `validate_der_price_ohlcv_pdf_list` never compares; `get_pdf1_pdf2_diff_list` stops at the first difference; the
  `ms_*` text columns lose `""` to NaN on a CSV round trip.
