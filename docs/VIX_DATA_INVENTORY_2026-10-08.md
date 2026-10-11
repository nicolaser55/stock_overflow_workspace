# VIX and VIX3M data acquired from IBKR: inventory and location (2026-10-08)

**Status of this document.** Counts, date ranges and gaps are copied from the console output of `python scripts/index_data_status.py` that Nicolas ran on 2026-10-08 (after the folder rename, in `venv-ingest`). I did not open the data files themselves and I cannot reach the share from the workspace where this was written. Everything about *how* the data was requested comes from the ingest code (`ingest/index_config.py`, `INDEX_PIPELINE.md`) and the probe results (`claude/VIX_PROBE_RESULTS_2026-10-06.md`). Items marked *inferred* are my reading, not an observation. The counts change whenever a download or merge is run: rerun the status command (§8) for the current figures.

## 1. Summary

| Series | Bar | First date | Last date | Dates in raw | Rows in raw | Size | Missing sessions (in neither raw nor staging) |
|---|---|---|---|---|---|---|---|
| VIX | 1-minute | 2005-10-03 | 2026-10-07 | 5,266 | 3,094,596 | 200.0 MB | 16 of 5,286 |
| VIX | daily | 2005-10-03 | 2026-10-07 | 5,269 | 5,269 | 0.3 MB | 17 of 5,286 |
| VIX3M | 1-minute | 2009-08-12 | 2026-10-06 | 4,310 | 1,723,744 | 111.6 MB | 5 of 4,315 |
| VIX3M | daily | 2009-08-12 | 2026-10-06 | 4,313 | 4,313 | 0.3 MB | 2 of 4,315 |

- All four series were downloaded from IBKR (IB Gateway live port 4001, ibapi 10.45.1, Gateway 1045.1) and merged from staging into raw. A status snapshot from 2026-10-07 still showed the VIX 1-minute and daily downloads in progress (388 VIX 1-minute files in raw); the snapshot of 2026-10-08 shows them complete as listed above.
- Volume is not usable for either index (see §6).
- The data was not yet used by any research step. Nothing in the research pipeline reads these folders.

## 2. Where it resides

Data root: `//100.123.162.2/stock_overflow_data/` (override: environment variable `SO_INGEST_DATA_PATH`). Everything below is under `store01_rawzone/`.

```
store01_rawzone/
├── ibkr_vix_family/                  RAW (add-only, read-only in practice)
│   ├── vix_1min/                     ohlcv_data_YYYYMMDD.csv  (one file per session; 5,266 files)
│   ├── vix_daily/                    ohlcv_data_YYYY.csv      (one file per calendar year; 22 files, 2005-2026)
│   ├── vix3m_1min/                   ohlcv_data_YYYYMMDD.csv  (4,310 files)
│   └── vix3m_daily/                  ohlcv_data_YYYY.csv      (18 files, 2009-2026)
├── ibkr_vix_family_staging/          STAGING (downloads before the merge) and the logs
│   ├── download_log.csv              every download attempt (status, bars, errors, request strings, ibapi / Gateway version)
│   ├── merge_log.csv                 what was added to raw and when
│   ├── vix_1min/                     5 files not merged (see §4); merged/ holds the copies of the 5,266 files already added to raw
│   ├── vix_daily/
│   ├── vix3m_1min/                   merged/ holds the copies of the 4,310 files added to raw
│   └── vix3m_daily/
└── ibkr_vix_family_backup_<time>/    created only if a daily merge changed a raw file: <leaf>/ (e.g. vix_daily/)
```

- Folder names come from one place in code: `ingest/index_config.py` (`INDEX_RAW_FOLDER_NAME_STR`, `INDEX_STAGING_FOLDER_NAME_STR`).
- The status output shows `staging/merged` as "folder missing" for the daily folders: daily staging files are merged into the raw year file rather than moved, so no `merged/` copy exists there. The 1-minute `merged/` folders exist and hold 5,266 (VIX) and 4,310 (VIX3M) files.
- SPY is in separate folders (`ibkr_spy_1min/`, `ibkr_spy_1min_staging/`) and was not touched by the index pipeline. The Apple trial data is in `ibkr_aapl_*` folders (separate document).
- The probe and alignment outputs of 2026-10-06 are **not** in the share: they are in the repo folder `stock_overflow_data_ingest/probe_output/` (`vix_probe_*`, `index_alignment_*`). They contain no price data after 2026-05-13.

## 3. File format

The columns and the timestamp text are those of the SPY raw files: `timestamp, open, high, low, close, volume, created_ts, date`. Files are written and merged as text, so prices and timestamps keep their exact characters. The daily timestamp is midnight New York time of the date (a label, not a time of trade). IBKR's unset volume value (2**127 - 1) is written as an empty cell; 0 and negative volumes are kept as received.

## 4. Not merged yet and missing data

**VIX 1-minute, in staging, not in raw (5 files, 2,736 rows):** four partial sessions, 2020-11-27, 2020-12-24, 2024-07-03 and 2024-12-24, saved after 3 requests and flagged `partial`; a fifth file whose date the output does not list (the staging range starts at 2005-10-03, so I infer it is that date, not verified). A partial session is merged only with `--include-partial`; the merge has not been applied to these. A dry run (`python scripts/merge_index_staging_into_raw.py`) shows the decision for each file.

**Sessions IBKR did not return (log `no_data` / `empty`, nothing saved):**

| Series | Sessions | Observation |
|---|---|---|
| VIX 1-minute | 2006-05-01 to 2006-05-19 (15 sessions, counted by me) and 2011-09-12 | 16 requests, `no_data` (error 162, HMDS returned no data) |
| VIX daily | the same 2006-05 sessions, 2006-11-24 and 2011-09-12 | 17 sessions missing, 2 requests logged `empty` |
| VIX3M 1-minute | 2011-09-12, 2017-10-20, 2017-10-23, 2017-10-24, **2026-10-07** | the first four are `no_data` (error 162); 2026-10-07 was not downloaded yet |
| VIX3M daily | 2011-09-12 and **2026-10-07** | the 2011 year file is saved and flagged `partial` |

- VIX 1-minute bars exist for 2006-11-24, while the daily bar for that date is missing: observed, cause not investigated.
- 2011-09-12 is missing in all four series.
- Reconciliation: VIX 1-minute shows 5,266 raw dates plus 5 staged files, while the status counts 5,270 of 5,286 sessions present. The one-file difference is not explained by the output (a staged date also present in raw, or a raw date outside the session list, are both possible); I did not check.
- The download log lists 27 requests whose last attempt was not complete: VIX 1-minute 16 `no_data` + 4 `partial`; VIX daily 2 `empty`; VIX3M 1-minute 4 `no_data`; VIX3M daily 1 `partial`.

## 5. How the data was requested

- Contracts: `IND`, exchange `CBOE`, currency `USD`, TRADES, regular trading hours.
- **1-minute:** one request per NYSE session, duration `1 D`, end time 17:00 New York written as a UTC string (`YYYYMMDD-21:00:00` or `-22:00:00`). One staging file per session. The probe used a 16:30 end; the pipeline uses 17:00 so that the latest bars seen (to 16:29 from 2022) are included. The 17:00 choice was not verified on the real server (see §7).
- **Daily:** one request per calendar year of missing sessions (end = last wanted date + 3 days, duration `2 Y`, bars outside the wanted dates dropped); one staging file per year, later runs add rows.
- The end format must be UTC for the indices: the SPY format (`... US/Eastern`) was refused with error 10314 in the probe.
- Pacing: at most 4 requests in flight, at least 0.5 s between requests.
- Earliest dates requested: VIX 2005-10-03, VIX3M 2009-08-12 (the earliest data IBKR reported in the probe, `reqHeadTimeStamp`).
- Merge: add-only, dry run by default, existing rows win, backup first for daily merges. 1-minute files are checked for positive prices, consistent high/low, no duplicate minutes, no bars of another date and no core-hour gaps (09:31 to 15:59) unless `--include-partial`.

## 6. Characteristics of the data you need to know before using it

All of these are observations from the 2026-10-06 probe on a sample of sessions (30 sessions), not checks of the downloaded files.

1. **The 1-minute session window changes by era**, so a fixed bar count does not apply. VIX first bar 09:31 (2007 to 2015), 03:15 from 2016 (with a gap from 09:15 to 09:30 in the sampled sessions), last bar 15:59, 16:14 or 16:29 or later by era; VIX3M 09:31 to 15:59 until about 2011, 09:31 to 16:14 afterwards. Some March 2020 VIX days start at 09:31, 09:46 or 09:56. The pipeline logs the first and last bar per session (`download_log.csv`: `first_bar_str`, `last_bar_str`) and flags only missing minutes between 09:31 and 15:59.
2. **Volume is not meaningful** (0, negative or unset).
3. **The label convention of the 1-minute bars is not proven.** The correlation check against SPY showed no lead (no look-ahead detected) and a delay of about one minute. Use only bars labelled before the decision minute, and expect values that may be stale by about a minute.
4. **Daily and 1-minute bars do not always agree.** In the probe, VIX3M's daily close differed from the last minute bar on 3 of 29 sessions (2022-09-13, 2024-08-05, 2025-04-09), and VIX's daily high differed from the highest minute high on 2 of 30 sessions (2022-06-13, 2022-09-13). Cause unknown.
5. **VIX3M starts on 2009-08-12 here**, not on 2007-12-04 as in Cboe's own history; an earlier term-structure feature cannot come from this source.
6. **The daily VIX close is only known at 16:15 New York**, after the 15:58 decision of the SPY experiments; use the previous day's close or intraday values.
7. Data from **2026-05-14 on** (the untouched window of the research) is stored like any other date. It must not be evaluated on.

## 7. Open items

- The 17:00 New York end of the 1-minute requests was not verified on the real server before the full run (the probe used 16:30). The `first_bar_str`, `last_bar_str` and `extra_str` columns of the download log would show bars of another date or a changed window; I have not looked at them.
- Merge the 5 staged VIX 1-minute files, or leave them out on purpose (decision for Nicolas: `--include-partial` for the four partial sessions).
- Download VIX3M 2026-10-07 (and the matching VIX3M daily date). Both missing dates are after the last downloaded session of that series, so a plain `python scripts/download_ibkr_index.py` fetches them.
- Whether the 2006-05 and 2011-09-12 gaps and the VIX3M 2017-10-20/23/24 gaps are real gaps in IBKR's history or temporary service errors is unknown; a later `--from-start` run would retry them.
- No integrity check of the files beyond the merge checks was run (no comparison with an outside source such as Cboe).
- The ingest guide `claude/INGEST_WORKSPACE_2026-10-06.md` and the probe doc still use the folder names from before the rename and describe no index download; this document and `INDEX_PIPELINE.md` in the repo reflect the current names.

## 8. How to refresh this inventory

```
venv-ingest\Scripts\activate
python scripts\index_data_status.py          # counts, ranges, missing sessions, problem requests (read-only)
python scripts\merge_index_staging_into_raw.py   # dry run: what the merge would do with the staged files
```

## Sources

- Console output of `python scripts/index_data_status.py`, run by Nicolas on 2026-10-08 (and the 2026-10-07 snapshot for the progress remark).
- `ingest/index_config.py` and `INDEX_PIPELINE.md` (ingest workspace, as delivered on 2026-10-06 to 2026-10-08).
- Project doc `claude/VIX_PROBE_RESULTS_2026-10-06.md`.
