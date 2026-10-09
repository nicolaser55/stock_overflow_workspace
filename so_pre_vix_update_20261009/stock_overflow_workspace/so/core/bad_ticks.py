"""
Bad Ticks In The Raw Minute Bars: the detection rule (pipeline step 00) and the one-off correction (2026-10-04)

The correction was applied once on 2026-10-04 (62 cells, records/bad_tick_corrections.csv). Run it again only when new
raw data arrives and step 00 reports bad ticks:

    python scripts/fix_raw_bad_ticks.py                      # DRY RUN: report the bars that would be corrected, write nothing
    python scripts/fix_raw_bad_ticks.py --apply              # back up the raw files, correct them, write the correction log
    python scripts/fix_raw_bad_ticks.py --path "//100.123.162.2/stock_overflow_data/store01_rawzone/ibkr_spy_1min/"

Known limitation (audit of 2026-10-05, docs/history/AUDIT_2026-10-05.md, F1): the 3% threshold leaves smaller wicks of
the same kind (1.5-3%), including some in 2015-2026. The rule is kept unchanged so the pipeline caches stay valid.

Problem (docs/history/RESULTS_LOG_2026-10-05.md, 2026-10-04):
    62 minute bars, all in 2005-2009 (15 / 11 / 14 / 15 / 7 per year), have a high or a low 3-8% away from their own
    open / close AND from the neighbouring bars (e.g. 2007-06-06 14:16: open / close $151.92, high $161.90). Many are
    exactly $5 or $10 off: feed errors, not trades. The least clear-cut cases are 3-4% wicks during the October 2008
    crash (e.g. 2008-10-10 12:19 and 12:50, both with a high of $91.02); they are corrected by the same rule and are
    listed in the correction log so they can be reviewed. The step 00 sanity check did not flag them, because their high / low still enclose the
    open and close. They distort every result that reads minute highs and lows (all-time highs, stop triggers, barrier
    labels, high-based features). Buy-and-hold and the v2 label (opens and closes only) are not affected.

Cleaning rule (decided BEFORE looking at its effect on any result; the threshold comes from the data-quality evidence
alone: every bar above it looks like a feed error, while real fast moves such as the 2010-05-06 flash crash stay below it):

    For every bar, within its session (the first and last bars of a session use only their own body):
        reference_high = max(open, close, previous bar close, next bar open)
        reference_low  = min(open, close, previous bar close, next bar open)
        if high > reference_high x (1 + 3%):   high := max(open, close)      (the wick is cut back to the body)
        if low  < reference_low  x (1 - 3%):   low  := min(open, close)
    Only the high / low cell of a flagged bar changes. Open, close, volume, timestamps and every other column are kept
    byte for byte (the files are read and written as text).

Steps performed with --apply:
    1. Read every raw file (local_file_management.get_path_file_list), as text.
    2. Detect the bad ticks on all files together, sorted by timestamp, neighbours taken within the same session.
    3. Back up every file that will change, byte for byte, into a sibling folder <raw folder>_backup_YYYYMMDD_HHMMSS/.
    4. Overwrite the changed files (local_file_management.write_csv_file_to_path, mode "W").
    5. Re-read them and verify that ONLY the flagged high / low cells changed.
    6. Write the correction log (file, timestamp, column, old value, new value, distance) to:
       - <data>/store02_workzone/step00_data_quality_report/bad_tick_corrections.csv  (<data> = the folder holding the raw folder)
       - records/bad_tick_corrections.csv (versioned in git; commit it)

Running it again after --apply finds nothing to correct (the rule is idempotent).
Step 00 (step00_data_quality_check.ipynb) calls get_bad_tick_pdf to report any bad tick left in the raw data.

After the correction, the cached v1 tables (steps 01-08) were built from the uncorrected data; see docs/RESULTS_LOG.md.
"""

import os
import shutil
import argparse
from datetime import datetime
import numpy as np
import pandas as pd
# IMPORT LOCAL FILE MANAGEMENT FUNCTIONS
from so.core.local_file_management import get_path_file_list, write_csv_file_to_path
# IMPORT PATHS
from so import paths

# DEFINE THE DEFAULT RAW FOLDER (THE NETWORK SHARE OF NICODESKTOP; FORWARD SLASHES WORK ON WINDOWS)
DEFAULT_RAW_PATH_STR = "//100.123.162.2/stock_overflow_data/store01_rawzone/ibkr_spy_1min/"
# DEFINE THE BAD TICK THRESHOLD (DISTANCE BEYOND THE REFERENCE PRICE)
BAD_TICK_THRESHOLD = 0.03
# DEFINE THE PRICE COLUMNS USED BY THE RULE
PRICE_COL_STR_LIST = ["open", "high", "low", "close"]

# FUNCTION: DETECT THE BAD TICKS OF A MINUTE OHLCV DATAFRAME
def get_bad_tick_pdf(ohlcv_pdf_in, threshold_float_in=BAD_TICK_THRESHOLD):
    """
    Applies the cleaning rule of the module docstring and returns one row per cell to correct.

    Args:
        ohlcv_pdf_in (pd.DataFrame): Minute bars with timestamp, open, high, low, close (any dtype; prices are parsed)
        threshold_float_in (float): Distance beyond the reference price that flags a wick

    Returns:
        pd.DataFrame: row_idx (index label in ohlcv_pdf_in), timestamp, column ("high" / "low"), old_value, new_value,
                      distance (fraction beyond the reference price)
    """
    # PARSE THE PRICES AND THE TIMESTAMPS
    price_pdf = ohlcv_pdf_in[PRICE_COL_STR_LIST].apply(pd.to_numeric, errors="coerce")
    timestamp_series = pd.to_datetime(ohlcv_pdf_in["timestamp"], utc=True).dt.tz_convert("America/New_York")
    # SORT BY TIMESTAMP (THE NEIGHBOURS MUST BE THE ADJACENT MINUTES)
    order_idx = timestamp_series.sort_values(kind="stable").index
    price_pdf, timestamp_series = price_pdf.loc[order_idx], timestamp_series.loc[order_idx]
    # DEFINE THE SESSION OF EVERY BAR
    session_series = timestamp_series.dt.date
    # COLLECT THE BODY OF EVERY BAR
    body_high_series = price_pdf[["open", "close"]].max(axis=1)
    body_low_series = price_pdf[["open", "close"]].min(axis=1)
    # COLLECT THE NEIGHBOURS WITHIN THE SESSION (THE BAR'S OWN BODY WHEN THERE IS NO NEIGHBOUR)
    same_prev_mask = session_series.eq(session_series.shift(1))
    same_next_mask = session_series.eq(session_series.shift(-1))
    prev_close_series = price_pdf["close"].shift(1).where(same_prev_mask)
    next_open_series = price_pdf["open"].shift(-1).where(same_next_mask)
    # CALCULATE THE REFERENCE PRICES
    reference_high_series = pd.concat([body_high_series, prev_close_series, next_open_series], axis=1).max(axis=1)
    reference_low_series = pd.concat([body_low_series, prev_close_series, next_open_series], axis=1).min(axis=1)
    # CALCULATE THE DISTANCES BEYOND THE REFERENCES
    high_distance_series = price_pdf["high"] / reference_high_series - 1
    low_distance_series = 1 - price_pdf["low"] / reference_low_series
    # LIST TO HOLD THE CORRECTIONS
    correction_dict_list = []
    # ITERATE OVER THE TWO WICKS
    for col_str, distance_series, new_value_series in [("high", high_distance_series, body_high_series), ("low", low_distance_series, body_low_series)]:
        # COLLECT THE FLAGGED BARS
        for row_idx in distance_series.index[distance_series > threshold_float_in]:
            # STORE THE CORRECTION
            correction_dict_list.append({"row_idx": row_idx, "timestamp": timestamp_series.loc[row_idx], "column": col_str,
                                         "old_value": float(price_pdf.loc[row_idx, col_str]), "new_value": float(new_value_series.loc[row_idx]),
                                         "distance": round(float(distance_series.loc[row_idx]), 6)})
    # RETURN THE CORRECTIONS (CHRONOLOGICAL)
    return pd.DataFrame(correction_dict_list, columns=["row_idx", "timestamp", "column", "old_value", "new_value", "distance"]) \
             .sort_values(["timestamp", "column"]).reset_index(drop=True)

# FUNCTION: FORMAT A PRICE AS TEXT (NO TRAILING ZEROS, LIKE THE RAW FILES)
def format_price_str(price_float_in):
    """
    Formats a corrected price as text without float noise (e.g. 151.92, not 151.92000000000002).

    Args:
        price_float_in (float): Price

    Returns:
        str: Price text
    """
    # RETURN THE SHORTEST TEXT OF THE ROUNDED PRICE
    return repr(round(float(price_float_in), 6))

# FUNCTION: GET THE DATA QUALITY REPORT FOLDER OF THE DATA FOLDER THAT HOLDS THE RAW FOLDER
def get_dq_report_path_str(raw_path_str_in):
    """
    Returns <data>/store02_workzone/step00_data_quality_report/ for the data folder that holds the raw folder, so the
    log lands next to the corrected data whether the raw folder is given as the network share or as the local path.
    Falls back to paths.LOCAL_DQ_REPORT_DATA_FILE_PATH_STR when the raw folder is not inside store01_rawzone/.

    Args:
        raw_path_str_in (str): Raw folder (ending with "/")

    Returns:
        str: Data quality report folder (ending with "/")
    """
    # COLLECT THE PARENT FOLDER OF THE RAW FOLDER
    rawzone_path_str = os.path.dirname(raw_path_str_in.rstrip("/"))
    # IF THE RAW FOLDER IS NOT INSIDE store01_rawzone/, USE THE CONFIGURED PATH
    if os.path.basename(rawzone_path_str) != "store01_rawzone":
        return paths.LOCAL_DQ_REPORT_DATA_FILE_PATH_STR
    # RETURN THE REPORT FOLDER NEXT TO THE RAWZONE
    return f"{os.path.dirname(rawzone_path_str)}/store02_workzone/step00_data_quality_report/"

# FUNCTION: RUN THE FIX
def run_fix(raw_path_str_in, apply_bool_in, threshold_float_in=BAD_TICK_THRESHOLD):
    """
    Detects the bad ticks of every raw file and, with apply_bool_in, backs up, corrects, verifies and logs them.

    Args:
        raw_path_str_in (str): Raw folder (ending with "/")
        apply_bool_in (bool): False = dry run (report only)
        threshold_float_in (float): Bad tick threshold

    Returns:
        pd.DataFrame: The correction log
    """
    # COLLECT THE RAW CSV FILES
    file_path_list = sorted(file_path for file_path in get_path_file_list(raw_path_str_in) if file_path.lower().endswith(".csv"))
    # STOP IF THERE ARE NO FILES
    if not file_path_list:
        raise SystemExit(f"No CSV files found in '{raw_path_str_in}'")
    # READ EVERY FILE AS TEXT (EVERY CELL IS KEPT EXACTLY AS WRITTEN)
    text_pdf_dict = {file_path: pd.read_csv(file_path, dtype=str, keep_default_na=False) for file_path in file_path_list}
    # STACK THE FILES (REMEMBER THE FILE AND THE ROW OF EVERY BAR)
    stacked_pdf = pd.concat([text_pdf.assign(_file=file_path, _row=np.arange(len(text_pdf))) for file_path, text_pdf in text_pdf_dict.items()], ignore_index=True)
    # DETECT THE BAD TICKS
    correction_pdf = get_bad_tick_pdf(stacked_pdf, threshold_float_in)
    # MAP EVERY CORRECTION TO ITS FILE AND ITS ROW IN THAT FILE
    correction_pdf["file"] = correction_pdf["row_idx"].map(stacked_pdf["_file"]).map(os.path.basename)
    correction_pdf["file_row"] = correction_pdf["row_idx"].map(stacked_pdf["_row"])
    correction_pdf["file_path"] = correction_pdf["row_idx"].map(stacked_pdf["_file"])
    # DISPLAY THE REPORT
    print(f"Raw folder:\t{raw_path_str_in}\t({len(file_path_list)} files, {len(stacked_pdf):,} bars)")
    print(f"Threshold:\t{threshold_float_in:.0%}\tCells to correct:\t{len(correction_pdf)}\t(bars: {correction_pdf['row_idx'].nunique()})")
    # IF THERE ARE CORRECTIONS, DISPLAY THE COUNT PER YEAR AND THE LIST
    if not correction_pdf.empty:
        print(correction_pdf.groupby(correction_pdf["timestamp"].dt.year)["column"].count().rename("cells per year").to_string())
        print(correction_pdf[["timestamp", "column", "old_value", "new_value", "distance", "file"]].to_string(index=False))
    # STOP HERE IN A DRY RUN OR WHEN THERE IS NOTHING TO CORRECT
    if not apply_bool_in or correction_pdf.empty:
        print("\nDry run: nothing was written." if not apply_bool_in else "\nNothing to correct.")
        return correction_pdf
    # CREATE THE BACKUP FOLDER (SIBLING OF THE RAW FOLDER)
    run_ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path_str = f"{raw_path_str_in.rstrip('/')}_backup_{run_ts_str}/"
    os.makedirs(backup_path_str, exist_ok=False)
    # ITERATE OVER THE FILES TO CHANGE
    for file_path, file_correction_pdf in correction_pdf.groupby("file_path"):
        # BACK UP THE ORIGINAL FILE BYTE FOR BYTE
        shutil.copy2(file_path, f"{backup_path_str}{os.path.basename(file_path)}")
        # APPLY THE CORRECTIONS TO THE TEXT TABLE
        corrected_pdf = text_pdf_dict[file_path].copy()
        for _, correction_row in file_correction_pdf.iterrows():
            corrected_pdf.loc[correction_row["file_row"], correction_row["column"]] = format_price_str(correction_row["new_value"])
        # OVERWRITE THE FILE
        write_csv_file_to_path(corrected_pdf, file_path, "W", alert_in=False)
        # VERIFY: RE-READ AND COMPARE WITH THE ORIGINAL, CELL BY CELL
        reread_pdf = pd.read_csv(file_path, dtype=str, keep_default_na=False)
        changed_mask = reread_pdf.ne(text_pdf_dict[file_path])
        changed_cell_set = {(row, col) for row, col in zip(*np.nonzero(changed_mask.to_numpy()))}
        expected_cell_set = {(int(row["file_row"]), int(reread_pdf.columns.get_loc(row["column"]))) for _, row in file_correction_pdf.iterrows()}
        assert list(reread_pdf.columns) == list(text_pdf_dict[file_path].columns) and len(reread_pdf) == len(text_pdf_dict[file_path]), f"Shape changed: {file_path}"
        assert changed_cell_set == expected_cell_set, f"Unexpected changes in {file_path}"
        print(f"✅ {os.path.basename(file_path)}:\t{len(file_correction_pdf)} cells corrected, backup in {backup_path_str}")
    # WRITE THE CORRECTION LOG (DATA FOLDER AND VERSIONED RECORDS FOLDER)
    log_pdf = correction_pdf.assign(threshold=threshold_float_in, corrected_ts=run_ts_str, backup_folder=backup_path_str)[
        ["timestamp", "column", "old_value", "new_value", "distance", "file", "file_row", "threshold", "corrected_ts", "backup_folder"]]
    log_pdf["timestamp"] = log_pdf["timestamp"].astype(str)
    workspace_path_str = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))).replace("\\", "/")
    for log_path_str in [f"{get_dq_report_path_str(raw_path_str_in)}bad_tick_corrections.csv", f"{workspace_path_str}/records/bad_tick_corrections.csv"]:
        write_csv_file_to_path(log_pdf, log_path_str, "A", alert_in=False)
        print(f"📝 Correction log:\t{log_path_str}")
    # RE-DETECT TO CONFIRM NOTHING IS LEFT
    remaining_pdf = get_bad_tick_pdf(pd.concat([pd.read_csv(file_path, dtype=str, keep_default_na=False) for file_path in file_path_list], ignore_index=True), threshold_float_in)
    print(f"Remaining bad ticks after the fix:\t{len(remaining_pdf)}")
    # RETURN THE LOG
    return log_pdf

# FUNCTION: MAIN (COMMAND LINE)
def main():
    """
    Parses the command line and runs the fix (scripts/fix_raw_bad_ticks.py calls this function).
    """
    # PARSE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Detect and correct bad ticks in the raw IBKR minute bars (see the module docstring).")
    parser.add_argument("--path", default=paths.LOCAL_OHLCV_DATA_FILE_PATH_STR, help="raw folder, ending with '/'")
    parser.add_argument("--apply", action="store_true", help="back up, correct, verify and log (default: dry run)")
    parser.add_argument("--threshold", type=float, default=BAD_TICK_THRESHOLD, help="bad tick threshold (default 0.03)")
    args = parser.parse_args()
    # RUN THE FIX
    run_fix(args.path if args.path.endswith("/") else f"{args.path}/", args.apply, args.threshold)
