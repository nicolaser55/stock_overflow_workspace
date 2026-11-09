"""
Workspace Tests: point-in-time data (so.core.point_in_time; Nicolas, 2026-10-11)

Run from the workspace root:   python tests/test_point_in_time.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The registry, the ledger, the trial log and SO_DATA_PATH are temporary. The data root is a
temporary folder. records/holdout_windows.csv is not written. SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are set
only inside this file, to temporary values. SO_QUARANTINE_PATH is set only inside this file, to the same temporary root.
"""

import os
import sys
import types
import tempfile
import shutil
import pandas as pd

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_pit_data_")
os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths, config
from so.core.point_in_time import (add_available_ts_pdf, add_tsbar_label_known_ts_pdf, add_tsday_fwd_label_known_ts_pdf, get_as_of_pdf, get_minute_bar_available_ts, get_decision_ts,
                                   get_vix_daily_available_ts, get_derived_available_ts, get_swing_available_ts,
                                   check_feature_available_ts, DataContext, register_source_dict, unregister_source,
                                   SOURCE_SPEC_DICT)
from so.features.vix_features import read_vix_daily_pdf, get_vix_prev_value_pdf
from so.core.external_data import read_spy_dividends_pdf, read_tbill_3m_pdf, SPY_DIVIDENDS_COLUMN_STR_LIST, TBILL_3M_COLUMN_STR_LIST

# KEEP THE REAL REGISTRY PATHS AND POINT THE SUITE AT TEMPORARY FILES
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_WINDOWS_EXISTS_BOOL = os.path.isfile(REAL_WINDOWS_PATH_STR)
REAL_WINDOWS_SIZE_INT = os.path.getsize(REAL_WINDOWS_PATH_STR) if REAL_WINDOWS_EXISTS_BOOL else None
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
# A NEW YORK CLOCK USED BY THE SMALL FRAMES
NY = "America/New_York"

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints the passing line for one test.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")

# FUNCTION: A ONE-MINUTE BAR LABEL ON A FIXED MORNING
def get_label_ts(hour_int_in, minute_int_in):
    """
    2010-06-01 at the given New York hour and minute.

    Args:
        hour_int_in (int): Hour
        minute_int_in (int): Minute

    Returns:
        pd.Timestamp: Bar-start label
    """
    # RETURN THE LABEL
    return pd.Timestamp(year=2010, month=6, day=1, hour=hour_int_in, minute=minute_int_in, tz=NY)

# FUNCTION: TEST BAR AND DAILY AVAILABILITY
def test_availability():
    """
    A 15:58 bar is knowable at 15:59:00. A VIX daily bar is knowable at 16:15. 15:58:30 excludes the 15:58 bar.

    Returns:
        None
    """
    # THE 15:58 BAR ENDS AT 15:59:00, WHICH IS THE DECISION MOMENT
    label_ts = get_label_ts(15, 58)
    bar_pdf = pd.DataFrame({"timestamp": [label_ts], "open": [1.0], "high": [1.0], "low": [1.0], "close": [2.0]})
    stamped_pdf = add_available_ts_pdf("SPY_1MIN", bar_pdf)
    assert stamped_pdf["available_ts"].iloc[0] == get_label_ts(15, 59)
    assert get_decision_ts(label_ts) == get_label_ts(15, 59)
    # 15:58:30 IS STILL INSIDE THE BAR, SO THE BAR IS NOT VISIBLE YET
    hidden_pdf = get_as_of_pdf("SPY_1MIN", get_label_ts(15, 58) + pd.Timedelta(seconds=30), pdf_in=bar_pdf)
    visible_pdf = get_as_of_pdf("SPY_1MIN", get_label_ts(15, 59), pdf_in=bar_pdf)
    assert len(hidden_pdf) == 0 and len(visible_pdf) == 1 and float(visible_pdf["close"].iloc[0]) == 2.0
    # A VIX DAILY BAR DATED THAT DAY IS KNOWABLE AT 16:15
    daily_pdf = pd.DataFrame({"timestamp": [pd.Timestamp("2010-06-01", tz=NY)], "date": [pd.Timestamp("2010-06-01").date()],
                              "open": [10.0], "high": [11.0], "low": [9.0], "close": [18.0]})
    daily_stamped_pdf = add_available_ts_pdf("VIX_DAILY", daily_pdf)
    assert daily_stamped_pdf["available_ts"].iloc[0] == get_vix_daily_available_ts("2010-06-01")
    assert daily_stamped_pdf["available_ts"].iloc[0] == pd.Timestamp(year=2010, month=6, day=1, hour=16, minute=15, tz=NY)
    # A FEATURE WHOSE CLOCK IS AFTER THE DECISION IS REFUSED
    try:
        check_feature_available_ts(daily_stamped_pdf, [get_label_ts(15, 59)])
        raise AssertionError("a 16:15 feature was accepted at the 15:59 decision")
    except ValueError as error:
        assert "available_ts" in str(error)
    passed("availability (15:58 bar at 15:59:00; VIX daily at 16:15; 15:58:30 excludes the bar)")

# FUNCTION: TEST DERIVED ROWS AND A DELAYED SWING
def test_derived():
    """
    A row computed from bars up to t is knowable when the last of those bars ends. A swing confirmed k bars later waits.

    Returns:
        None
    """
    # THREE INPUT BARS: THE ROW IS KNOWABLE AT THE END OF THE THIRD
    first_ts = get_label_ts(10, 0)
    label_list = [first_ts + pd.Timedelta(minutes=offset) for offset in range(3)]
    assert get_derived_available_ts(label_list) == get_minute_bar_available_ts(label_list[-1])
    cache_pdf = pd.DataFrame({"timestamp": [label_list[-1]], "close": [5.0]})
    cache_stamped_pdf = add_available_ts_pdf("TSCTX", cache_pdf)
    assert cache_stamped_pdf["available_ts"].iloc[0] == get_derived_available_ts(label_list)
    # A SWING STORED ON ITS OWN BAR, CONFIRMED 3 BARS LATER, IS INVISIBLE UNTIL THAT CONFIRMATION BAR ENDS
    swing_pdf = pd.DataFrame({"timestamp": [first_ts], "close": [4.0], "confirm_lag_bars": [3]})
    swing_stamped_pdf = add_available_ts_pdf("TSSEG", swing_pdf)
    confirmation_ts = get_swing_available_ts(first_ts, 3)
    assert swing_stamped_pdf["available_ts"].iloc[0] == confirmation_ts
    assert confirmation_ts == get_minute_bar_available_ts(first_ts + pd.Timedelta(minutes=3))
    assert len(get_as_of_pdf("TSSEG", confirmation_ts - pd.Timedelta(seconds=1), pdf_in=swing_pdf)) == 0
    assert len(get_as_of_pdf("TSSEG", confirmation_ts, pdf_in=swing_pdf)) == 1
    passed("derived (latest input bar; swing available only after confirmation)")

# FUNCTION: TEST THAT A REVISION IS INVISIBLE UNTIL IT IS RELEASED
def test_vintage():
    """
    The revised value is hidden before its available_ts. Each date sees the value known then.

    Returns:
        None
    """
    # REGISTER A VINTAGE SOURCE FOR THIS TEST ONLY
    register_source_dict("SYNTH_MACRO", {"loader": "test", "time_zone": NY, "timestamp_convention": "release time",
                                         "availability_func": None, "revision_policy": "vintage", "vintage_key_list": ["obs_date"],
                                         "revision_reason": "test vintage", "role": "feature", "holdout": "development boundary"})
    try:
        # TWO RELEASES OF THE SAME OBSERVATION
        vintage_pdf = pd.DataFrame({"obs_date": ["2010-01-01", "2010-01-01"], "value": [1.0, 2.0],
                                    "available_ts": [pd.Timestamp("2010-02-01", tz=NY), pd.Timestamp("2010-03-01", tz=NY)]})
        before_pdf = get_as_of_pdf("SYNTH_MACRO", pd.Timestamp("2010-01-15", tz=NY), pdf_in=vintage_pdf)
        first_pdf = get_as_of_pdf("SYNTH_MACRO", pd.Timestamp("2010-02-15", tz=NY), pdf_in=vintage_pdf)
        revised_pdf = get_as_of_pdf("SYNTH_MACRO", pd.Timestamp("2010-03-15", tz=NY), pdf_in=vintage_pdf)
        # NOTHING, THEN THE FIRST PRINT, THEN THE REVISION
        assert len(before_pdf) == 0
        assert float(first_pdf["value"].iloc[0]) == 1.0
        assert float(revised_pdf["value"].iloc[0]) == 2.0
    finally:
        unregister_source("SYNTH_MACRO")
    passed("vintages (revision invisible until its available_ts)")

# FUNCTION: TEST THAT LABELS USE label_known_ts AND NOT THE FEATURE DOOR
def test_labels():
    """
    TSBAR is refused through get. get_labels returns a row only when label_known_ts is strictly before the cutoff.

    Returns:
        None
    """
    # TWO LABELS, KNOWN AT 11:00 AND AT 15:00
    early_ts = get_label_ts(11, 0)
    late_ts = get_label_ts(15, 0)
    label_pdf = pd.DataFrame({"timestamp": [get_label_ts(10, 0), get_label_ts(10, 0)], "label_known_ts": [early_ts, late_ts], "y": [1, 0]})
    context = DataContext("development", frame_dict_in={"TSBAR": label_pdf})
    # THE FEATURE DOOR REFUSES THE LABEL
    try:
        context.get("TSBAR", late_ts)
        raise AssertionError("TSBAR was returned through get")
    except ValueError as error:
        assert "get_labels" in str(error)
    # ONLY THE LABEL KNOWN STRICTLY BEFORE THE CUTOFF
    early_pdf = context.get_labels("TSBAR", late_ts)
    none_pdf = context.get_labels("TSBAR", early_ts)
    assert list(early_pdf["y"]) == [1] and len(none_pdf) == 0
    passed("labels (TSBAR refused through get; get_labels keeps label_known_ts before the cutoff)")

# FUNCTION: TEST THE TSDAY_FWD HORIZON CLOCK AND REDACTION
def test_tsday_fwd_clock():
    """
    label_known_ts is the end of session i + LABEL_HORIZON_SESSIONS (one minute after its decision moment: the label
    sells at that session's close; audit S10). The last horizon rows are dropped. A blank
    y_fwd becomes a missing label.

    Returns:
        None
    """
    # FIVE SESSIONS; HORIZON 20 WOULD DROP ALL, SO STAMP A SHORT TABLE WITH THE SHARED HORIZON AFTER A TINY FRAME
    session_count = int(config.LABEL_HORIZON_SESSIONS) + 3
    day_list = pd.bdate_range("2010-06-01", periods=session_count, tz=NY)
    decision_list = [pd.Timestamp(day).tz_convert(NY).replace(hour=15, minute=58) for day in day_list]
    label_pdf = pd.DataFrame({
        "date": [day.date() for day in day_list],
        "decision_ts": decision_list,
        "y_fwd_positive": [1.0] * (session_count - 1) + [""],
        "fwd_net_return_20d": [0.01] * (session_count - 1) + [""],
    })
    stamped_pdf = add_tsday_fwd_label_known_ts_pdf(label_pdf)
    assert len(stamped_pdf) == session_count - int(config.LABEL_HORIZON_SESSIONS)
    first_known = get_decision_ts(decision_list[int(config.LABEL_HORIZON_SESSIONS)]) + pd.Timedelta(minutes=1)
    assert pd.Timestamp(stamped_pdf["label_known_ts"].iloc[0]) == first_known
    assert pd.Timestamp(first_known).hour == 16 and pd.Timestamp(first_known).minute == 0
    assert "TSDAY_FWD" in SOURCE_SPEC_DICT and SOURCE_SPEC_DICT["TSDAY_FWD"]["role"] == "label"
    context = DataContext("development", frame_dict_in={"TSDAY_FWD": stamped_pdf})
    try:
        context.get("TSDAY_FWD", first_known + pd.Timedelta(days=1))
        raise AssertionError("TSDAY_FWD was returned through get")
    except ValueError as error:
        assert "get_labels" in str(error)
    known_pdf = context.get_labels("TSDAY_FWD", first_known + pd.Timedelta(seconds=1))
    assert len(known_pdf) >= 1
    passed("TSDAY_FWD (horizon clock; unfinished dropped; feature door refused)")

# FUNCTION: TEST THAT A STORED TSBAR CELL BECOMES label_known_ts
def test_tsbar_cell_clock():
    """
    Distance cells have no label_known_ts column. The row clock is the end of the latest exit bar on a synthetic
    minute index. An unresolved cell, a missing entry, and an exit past the index stay unfinished. A frame that
    already has label_known_ts or exit_ts keeps that clock.

    Returns:
        None
    """
    # FIVE MINUTE BARS, 10:00 THROUGH 10:04. THE LATEST CELL EXITS THREE BARS AFTER 10:00.
    bar_list = [get_label_ts(10, minute) for minute in range(5)]
    cell_pdf = pd.DataFrame({
        "entry_ts": [get_label_ts(10, 0), get_label_ts(10, 1), get_label_ts(10, 0), get_label_ts(11, 0)],
        "0.0010": ["1|1|TP", "1|1|TP", "1|1|TP", "1|1|TP"],
        "0.0200": ["3|1|SL", "-1|nan|NA", "9|1|TL", "1|1|TP"],
    })
    stamped_pdf = add_tsbar_label_known_ts_pdf(cell_pdf, timestamp_index_in=bar_list)
    assert pd.Timestamp(stamped_pdf["label_known_ts"].iloc[0]) == get_label_ts(10, 4)
    assert pd.Timestamp(stamped_pdf["available_ts"].iloc[0]) == get_label_ts(10, 4)
    assert pd.isna(stamped_pdf["label_known_ts"].iloc[1])
    assert pd.isna(stamped_pdf["label_known_ts"].iloc[2])
    assert pd.isna(stamped_pdf["label_known_ts"].iloc[3])
    # AN EXISTING CLOCK IS KEPT. exit_ts IS THE BAR START, KNOWABLE ONE MINUTE LATER.
    kept_pdf = add_tsbar_label_known_ts_pdf(pd.DataFrame({"label_known_ts": [get_label_ts(15, 0)], "y": [1]}))
    assert pd.Timestamp(kept_pdf["label_known_ts"].iloc[0]) == get_label_ts(15, 0)
    exit_pdf = add_tsbar_label_known_ts_pdf(pd.DataFrame({"exit_ts": [get_label_ts(10, 1)]}))
    assert pd.Timestamp(exit_pdf["label_known_ts"].iloc[0]) == get_minute_bar_available_ts(get_label_ts(10, 1))
    passed("TSBAR cells (latest exit bar; unresolved, missing and out-of-index rows stay unfinished)")

# FUNCTION: TEST THAT AN UNKNOWN SOURCE RAISES
def test_unregistered():
    """
    A name that is not in the registry cannot be read.

    Returns:
        None
    """
    # ASK FOR A NAME THAT WAS NEVER REGISTERED
    try:
        get_as_of_pdf("NOT_A_SOURCE", get_label_ts(12, 0), pdf_in=pd.DataFrame({"timestamp": [get_label_ts(12, 0)]}))
        raise AssertionError("an unregistered source was accepted")
    except ValueError as error:
        assert "Unregistered" in str(error)
    passed("unregistered source raises")

# FUNCTION: BUILD A ONE-CANDIDATE DESIGN MODULE
def get_design_module(name_str_in, candidate_func_in, path_func_in, source_name_list_in=None):
    """
    A design module the runner can hash and call.

    Args:
        name_str_in (str): Experiment name
        candidate_func_in (callable): run_candidate_replay_dict
        path_func_in (callable): run_prior_only_path_dict
        source_name_list_in (list | None): DATA_SOURCE_LIST (None = the attribute is absent)

    Returns:
        module: Design
    """
    # THE CONSTANTS THE RUNNER HASHES
    design_module = types.ModuleType(name_str_in)
    design_module.EXPERIMENT_NAME = name_str_in
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["constant"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    design_module.run_candidate_replay_dict = candidate_func_in
    design_module.run_prior_only_path_dict = path_func_in
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    if source_name_list_in is not None:
        design_module.DATA_SOURCE_LIST = list(source_name_list_in)
    return design_module


# FUNCTION: TEST THAT THE EXISTING VIX FUNCTIONS ARE UNCHANGED FOR AN OLD CALLER
def test_vix_regression():
    """
    get_vix_prev_value_pdf and read_vix_daily_pdf return the values written into the synthetic frame.

    Returns:
        None
    """
    # THE PREVIOUS CLOSE IS THE HAND VALUE, NOT A NEW DEFINITION
    session_date_list = [pd.Timestamp("2010-06-01").date(), pd.Timestamp("2010-06-02").date(), pd.Timestamp("2010-06-03").date()]
    daily_pdf = pd.DataFrame({"date": session_date_list, "close": [10.0, 12.0, 11.0]})
    prev_pdf = get_vix_prev_value_pdf(session_date_list, daily_pdf, "2005-10-03")
    assert float(prev_pdf["value"].iloc[1]) == 10.0 and float(prev_pdf["value"].iloc[2]) == 12.0
    # A ONE-ROW YEAR FILE COMES BACK WITH THE CLOSE THAT WAS WRITTEN
    folder_str = os.path.join(TEMP_ROOT_STR, "vix_daily").replace("\\", "/") + "/"
    os.makedirs(folder_str, exist_ok=True)
    raw_pdf = pd.DataFrame({"timestamp": ["2010-06-01 04:00:00+00:00"], "open": [17.0], "high": [18.0], "low": [16.0],
                            "close": [17.25], "volume": [0], "created_ts": ["2010-06-01 20:00:00+00:00"], "date": ["2010-06-01"]})
    raw_pdf.to_csv(os.path.join(folder_str, "ohlcv_data_2010.csv"), index=False)
    loaded_pdf = read_vix_daily_pdf("vix", "2010-06-15", raw_path_str_in=folder_str, enforce_holdout_bool_in=False)
    again_pdf = read_vix_daily_pdf("vix", "2010-06-15", raw_path_str_in=folder_str, enforce_holdout_bool_in=False)
    assert float(loaded_pdf["close"].iloc[0]) == 17.25 and float(again_pdf["close"].iloc[0]) == 17.25
    passed("VIX regression (previous close and the loaded close match the file)")


# FUNCTION: WRITE THE TWO SYNTHETIC CONTRACT FILES (INGEST DATA CONTRACT VERSION 2) UNDER A ROOT
def write_external_files(root_str_in):
    """
    Writes store01_rawzone/fred_dtb3/dtb3.csv and store01_rawzone/spy_dividends/spy_dividends.csv with invented values.

    Args:
        root_str_in (str): Data root ending with "/"

    Returns:
        tuple[str, str]: The T-bill folder and the dividend folder
    """
    # T-BILL: A FIRST RELEASE, ITS REVISION, AND A DAY FRED PUBLISHED NO VALUE (".")
    rate_folder_str = f"{root_str_in}store01_rawzone/fred_dtb3/"
    os.makedirs(rate_folder_str, exist_ok=True)
    pd.DataFrame([["2010-01-05", "2010-01-05 16:30:00-05:00", "2010-01-04", "0.08", "2010-01-05", "first_seen", "R1"],
                  ["2010-02-01", "2010-02-01 16:30:00-05:00", "2010-01-04", "0.09", "2010-02-01", "revision", "R2"],
                  ["2010-01-06", "2010-01-06 16:30:00-05:00", "2010-01-05", ".", "2010-01-06", "first_seen", "R1"]],
                 columns=TBILL_3M_COLUMN_STR_LIST).to_csv(f"{rate_folder_str}dtb3.csv", index=False)
    # DIVIDENDS: A FIRST RELEASE AT THE EX-DATE OPEN AND A LATER CORRECTION
    dividend_folder_str = f"{root_str_in}store01_rawzone/spy_dividends/"
    os.makedirs(dividend_folder_str, exist_ok=True)
    pd.DataFrame([["2010-03-19", "2010-03-19 09:30:00-04:00", "2010-03-19", "2010-03-23", "2010-04-30", "", "0.512800", "regular", "USD", "first_seen", "R1"],
                  ["2010-06-01", "2010-06-01 10:00:00-04:00", "2010-03-19", "2010-03-23", "2010-04-30", "", "0.513000", "regular", "USD", "revision", "R2"]],
                 columns=SPY_DIVIDENDS_COLUMN_STR_LIST).to_csv(f"{dividend_folder_str}spy_dividends.csv", index=False)
    return rate_folder_str, dividend_folder_str

# FUNCTION: TEST THE EXTERNAL-SOURCE LOADERS AND THEIR REGISTRY ENTRIES
def test_external_sources():
    """
    SPY_DIVIDENDS and TBILL_3M: contract header, clocks, cutoff, types, vintage as-of, the holdout guard, the disk loader,
    and the runner view returning the same release as development.

    Returns:
        None
    """
    # THE FILES, UNDER THE TEMPORARY DATA ROOT (THE PATHS OF so.paths)
    root_str = TEMP_ROOT_STR.replace("\\", "/").rstrip("/") + "/"
    rate_folder_str, dividend_folder_str = write_external_files(root_str)
    assert paths.LOCAL_TBILL_3M_PATH_STR == rate_folder_str and paths.LOCAL_SPY_DIVIDENDS_PATH_STR == dividend_folder_str
    # LOADERS: TYPES, "." AS NaN, AND THE CUTOFF ON date (THE REVISIONS ARE DATED 2010-02-01 AND 2010-06-01)
    rate_pdf = read_tbill_3m_pdf("2010-12-31", enforce_holdout_bool_in=False)
    assert len(rate_pdf) == 3 and rate_pdf["value_pct"].isna().sum() == 1
    assert str(rate_pdf["available_ts"].iloc[0]) == "2010-01-05 16:30:00-05:00"
    assert len(read_tbill_3m_pdf("2010-01-31", enforce_holdout_bool_in=False)) == 2
    dividend_pdf = read_spy_dividends_pdf("2010-12-31", enforce_holdout_bool_in=False)
    assert len(dividend_pdf) == 2 and float(dividend_pdf["amount_usd"].iloc[0]) == 0.5128 and pd.isna(dividend_pdf["declared_date"].iloc[0])
    assert len(read_spy_dividends_pdf("2010-05-31", enforce_holdout_bool_in=False)) == 1
    # NO CUTOFF, ANOTHER CONTRACT VERSION, A date THAT IS NOT THE NEW YORK DATE OF available_ts, A MISSING FILE: ALL RAISE
    for call in (lambda: read_tbill_3m_pdf(None, enforce_holdout_bool_in=False),):
        try:
            call()
            raise AssertionError("no cutoff accepted")
        except ValueError:
            pass
    bad_folder_str = os.path.join(TEMP_ROOT_STR, "bad_rate").replace("\\", "/") + "/"
    os.makedirs(bad_folder_str, exist_ok=True)
    good_pdf = pd.read_csv(f"{rate_folder_str}dtb3.csv", dtype=str, keep_default_na=False)
    for bad_pdf, error_type in ((good_pdf.drop(columns="ingest_run_id"), ValueError), (good_pdf.assign(date="2010-01-04"), ValueError)):
        bad_pdf.to_csv(f"{bad_folder_str}dtb3.csv", index=False)
        try:
            read_tbill_3m_pdf("2010-12-31", raw_path_str_in=bad_folder_str, enforce_holdout_bool_in=False)
            raise AssertionError("a file outside the contract was accepted")
        except error_type:
            pass
    try:
        read_spy_dividends_pdf("2010-12-31", raw_path_str_in=bad_folder_str, enforce_holdout_bool_in=False)
        raise AssertionError("a missing file was accepted")
    except FileNotFoundError:
        pass
    # REGISTRY: ONE ROW PER KEY, THE RELEASE KNOWN AT as_of (LOOKED UP BY KEY; ROWS COME BACK IN RELEASE ORDER)
    OBS_DATE = pd.Timestamp("2010-01-04").date()
    first_pdf = get_as_of_pdf("TBILL_3M", pd.Timestamp("2010-01-20 15:59", tz=NY), pdf_in=rate_pdf)
    revised_pdf = get_as_of_pdf("TBILL_3M", pd.Timestamp("2010-02-02 15:59", tz=NY), pdf_in=rate_pdf)
    assert len(first_pdf) == 2 and float(first_pdf.set_index("observation_date")["value_pct"].loc[OBS_DATE]) == 0.08
    assert float(revised_pdf.set_index("observation_date")["value_pct"].loc[OBS_DATE]) == 0.09
    # THE FEATURE CLOCK: THE 2010-01-04 RATE IS NOT KNOWN AT THE 2010-01-05 15:59 DECISION (POSTED AT 16:30)
    assert len(get_as_of_pdf("TBILL_3M", pd.Timestamp("2010-01-05 15:59", tz=NY), pdf_in=rate_pdf)) == 0
    # THE DIVIDEND IS NOT KNOWN AT THE PREVIOUS SESSION'S DECISION, AND IS AT THE EX-DATE'S
    assert len(get_as_of_pdf("SPY_DIVIDENDS", pd.Timestamp("2010-03-18 15:59", tz=NY), pdf_in=dividend_pdf)) == 0
    ex_pdf = get_as_of_pdf("SPY_DIVIDENDS", pd.Timestamp("2010-03-19 15:59", tz=NY), pdf_in=dividend_pdf)
    assert len(ex_pdf) == 1 and float(ex_pdf["amount_usd"].iloc[0]) == 0.5128
    assert float(get_as_of_pdf("SPY_DIVIDENDS", pd.Timestamp("2010-06-02", tz=NY), pdf_in=dividend_pdf)["amount_usd"].iloc[0]) == 0.513
    # BUILT-IN: A TEST CANNOT UNREGISTER THEM
    for name_str in ("SPY_DIVIDENDS", "TBILL_3M"):
        try:
            unregister_source(name_str)
            raise AssertionError(f"{name_str} was unregistered")
        except ValueError:
            pass
    # THE RUNNER VIEW RETURNS THE SAME RELEASE AS DEVELOPMENT; get_new STILL STREAMS EVERY NEW ROW
    from so.runner.view import SourceFeed, get_view_source_state_dict, DecisionView
    moment_ts = pd.Timestamp("2010-02-02 15:59", tz=NY)
    feed = SourceFeed("TBILL_3M", "feature", add_available_ts_pdf("TBILL_3M", rate_pdf))
    feed.advance_to_ts(moment_ts)
    view = DecisionView(moment_ts, 0, 0, moment_ts.date(), {}, get_view_source_state_dict({"TBILL_3M": feed}))
    view_pdf = view.get("TBILL_3M")
    assert len(view_pdf) == 2 and float(view_pdf.set_index("observation_date")["value_pct"].loc[OBS_DATE]) == 0.09
    assert len(view.get("TBILL_3M", pd.Timestamp("2010-01-20 15:59", tz=NY))) == 2
    assert float(view.get("TBILL_3M", pd.Timestamp("2010-01-20 15:59", tz=NY)).set_index("observation_date")["value_pct"].loc[OBS_DATE]) == 0.08
    assert len(view.get_new("TBILL_3M")) == 3
    # WITH A WINDOW FROM 2010-06-01: THE DISK LOADER STOPS BEFORE IT, A CUTOFF ON THE START RAISES
    pd.DataFrame([{"window_id": "test", "status": "active", "start": "2010-06-01", "end": "2011-05-31", "session_count": 1,
                   "months_covered": 12, "opened_ts": "2026-11-09T00:00:00", "opened_by": "test", "data_last_session_at_open": "2011-05-31",
                   "retired_ts": "", "retire_reason": ""}]).to_csv(REGISTRY_PATH_STR, index=False)
    try:
        from so.core.point_in_time import get_stamped_source_frame_dict
        frame_dict = get_stamped_source_frame_dict(["TBILL_3M", "SPY_DIVIDENDS"], "2010-05-31")
        assert len(frame_dict["TBILL_3M"]) == 3 and len(frame_dict["SPY_DIVIDENDS"]) == 1
        try:
            read_spy_dividends_pdf("2010-06-01")
            raise AssertionError("a cutoff on the window start was accepted")
        except ValueError:
            pass
    finally:
        os.remove(REGISTRY_PATH_STR)
    passed("SPY_DIVIDENDS and TBILL_3M: contract, clocks, cutoff, vintage as-of, guard, disk loader, runner view = development")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY FOLDERS
    try:
        test_availability()
        test_derived()
        test_vintage()
        test_labels()
        test_tsday_fwd_clock()
        test_tsbar_cell_clock()
        test_unregistered()
        test_vix_regression()
        test_external_sources()
        assert os.path.isfile(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_EXISTS_BOOL
        if REAL_WINDOWS_EXISTS_BOOL:
            assert os.path.getsize(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_SIZE_INT
        assert "SYNTH_MACRO" not in SOURCE_SPEC_DICT
        print("\nAll point-in-time tests passed ✅")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
