"""
Workspace Tests: the VIX data layer (so.features.vix_features, so.vix_config; roadmap 2026-10-09)

Run from the workspace root:   python tests/test_vix_features.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data; temporary files under logs/test_vix_tmp/ inside the workspace, removed at the end):
    1. Loaders: raise without a cutoff and with a cutoff on or after 2026-05-14; never return a row after the cutoff (a
       row dated 2026-05-14 is planted in a yearly file); never open a file dated after the cutoff (corrupt files are
       planted there); raise when a "date" differs from the New York date of the timestamp.
    2. _prev uses the close of the strictly previous date; _intraday picks the bar labelled decision - 1 minute on a full
       day (15:57) and on a half day (12:57).
    3. Staleness (lag 3 accepted, lag 4 stale) and the fallback of _intraday (missing session, half day without an
       allowed bar), with the counts per year; VIX3M before its first date is NaN and counted as before_start.
    4. No look-ahead: changing any daily close dated on or after session t's date, or any 1-minute bar labelled later
       than decision_ts(t) - 1 minute, changes no feature of sessions up to t (both variants); changing the allowed bar
       does change the intraday feature (the test is sensitive).
    5. Each feature formula by hand on a small table.
    6. The end-to-end function reads raw-format files and equals the in-memory computation.
"""

import os
import sys
import shutil
import warnings
import numpy as np
import pandas as pd

# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
# IGNORE WARNINGS FROM LIBRARIES
warnings.filterwarnings("ignore")

# IMPORT WORKSPACE MODULES
from so import vix_config
from so.core.datetime_utils import ny_tz, get_date_range_market_schedule_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.features.vix_features import (check_cutoff_date, read_vix_daily_pdf, read_vix_1min_pdf, get_vix_table_pdf, get_vix_feature_pdf,
                                      get_vix_feature_col_list, get_vix_coverage_pdf, get_vix_daily_feature_dict)
from synthetic_data import get_synthetic_ohlcv_pdf, get_synthetic_index_daily_pdf, get_synthetic_index_minute_pdf

# DEFINE THE TEMPORARY FOLDER (INSIDE THE WORKSPACE, GITIGNORED)
TMP_PATH_STR = os.path.join(WORKSPACE_PATH_STR, "logs", "test_vix_tmp").replace("\\", "/") + "/"
# DEFINE THE SYNTHETIC SPAN
SPAN_START_STR, SPAN_END_STR = "2019-01-02", "2021-06-30"

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# DEFINE THE SHORT NAMES OF THE SHARED SYNTHETIC INDEX GENERATORS
get_synthetic_daily_bar_pdf, get_synthetic_minute_bar_pdf = get_synthetic_index_daily_pdf, get_synthetic_index_minute_pdf

# FUNCTION: WRITE BARS IN THE RAW FILE FORMAT
def write_raw_bar_file(bar_pdf_in, file_path_str_in):
    # BUILD THE RAW COLUMNS (UTC TIMESTAMP TEXT, EMPTY VOLUME)
    raw_pdf = pd.DataFrame({"timestamp": pd.DatetimeIndex(bar_pdf_in["timestamp"]).tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S+00:00"),
                            "open": bar_pdf_in["close"], "high": bar_pdf_in["close"], "low": bar_pdf_in["close"], "close": bar_pdf_in["close"],
                            "volume": "", "created_ts": "2026-10-07 12:00:00", "date": [str(d) for d in bar_pdf_in["date"]]})
    # WRITE THE FILE
    raw_pdf.to_csv(file_path_str_in, index=False)

# FUNCTION: WRITE A SERIES IN THE RAW FOLDER LAYOUT
def write_raw_series(daily_bar_pdf_in, minute_bar_pdf_in, folder_str_in):
    # CREATE THE FOLDERS
    os.makedirs(f"{folder_str_in}daily/", exist_ok=True)
    os.makedirs(f"{folder_str_in}1min/", exist_ok=True)
    # WRITE ONE DAILY FILE PER YEAR
    for year_int, year_pdf in daily_bar_pdf_in.groupby(pd.to_datetime(daily_bar_pdf_in["date"]).dt.year):
        write_raw_bar_file(year_pdf, f"{folder_str_in}daily/ohlcv_data_{year_int}.csv")
    # WRITE ONE 1-MINUTE FILE PER SESSION
    for date_object, date_pdf in minute_bar_pdf_in.groupby("date"):
        write_raw_bar_file(date_pdf, f"{folder_str_in}1min/ohlcv_data_{date_object.strftime('%Y%m%d')}.csv")

# FUNCTION: CHECK THAT TWO FEATURE TABLES ARE EQUAL (NaN EQUALS NaN)
def check_equal_pdf(pdf1_in, pdf2_in):
    # RETURN THE EQUALITY
    return np.allclose(pdf1_in.to_numpy(dtype=float), pdf2_in.to_numpy(dtype=float), equal_nan=True, rtol=0, atol=1e-12)

# FUNCTION: TEST THE LOADERS
def test_loaders():
    # PREPARE A FOLDER
    folder_str = f"{TMP_PATH_STR}loader/"
    os.makedirs(f"{folder_str}daily/", exist_ok=True)
    os.makedirs(f"{folder_str}1min/", exist_ok=True)
    # WRITE TWO YEAR FILES, THE 2026 ONE WITH ROWS DATED 2026-05-14 (PLANTED) AND LATER
    daily_pdf = get_synthetic_daily_bar_pdf("2025-01-02", "2026-06-30", 15.0, 1)
    write_raw_bar_file(daily_pdf[pd.to_datetime(daily_pdf["date"]).dt.year == 2025], f"{folder_str}daily/ohlcv_data_2025.csv")
    write_raw_bar_file(daily_pdf[pd.to_datetime(daily_pdf["date"]).dt.year == 2026], f"{folder_str}daily/ohlcv_data_2026.csv")
    assert (daily_pdf["date"] == pd.Timestamp("2026-05-14").date()).any()
    # PLANT A CORRUPT YEAR FILE AFTER THE CUTOFF (OPENING IT WOULD RAISE)
    with open(f"{folder_str}daily/ohlcv_data_2027.csv", "w") as file:
        file.write("not,a,bar\n1,2,3\n")
    # WRITE TWO 1-MINUTE FILES AND PLANT A CORRUPT ONE DATED 2026-05-14
    minute_pdf = get_synthetic_minute_bar_pdf("2026-05-12", "2026-05-13", 15.0, 2)
    for date_object, date_pdf in minute_pdf.groupby("date"):
        write_raw_bar_file(date_pdf, f"{folder_str}1min/ohlcv_data_{date_object.strftime('%Y%m%d')}.csv")
    with open(f"{folder_str}1min/ohlcv_data_20260514.csv", "w") as file:
        file.write("not,a,bar\n1,2,3\n")
    # A MISSING CUTOFF RAISES (ARGUMENT OMITTED OR None)
    for call_func in [lambda: read_vix_daily_pdf("vix"), lambda: read_vix_1min_pdf("vix")]:
        try:
            call_func()
            raise AssertionError("a loader ran without a cutoff")
        except TypeError:
            pass
    # A CUTOFF ON OR AFTER THE UNTOUCHED START (OR None) RAISES
    for cutoff_str in [None, "2026-05-14", "2026-08-13", "2030-01-01"]:
        for call_func in [lambda: read_vix_daily_pdf("vix", cutoff_str, folder_str + "daily/"), lambda: read_vix_1min_pdf("vix", cutoff_str, None, folder_str + "1min/")]:
            try:
                call_func()
                raise AssertionError(f"a loader accepted the cutoff {cutoff_str}")
            except ValueError:
                pass
    assert check_cutoff_date("2026-05-13") == pd.Timestamp("2026-05-13").date()
    # THE LOADERS NEVER RETURN A ROW AFTER THE CUTOFF (AND NEVER OPEN THE CORRUPT FILES)
    for cutoff_str in ["2026-05-13", "2026-05-12", "2025-12-31"]:
        loaded_pdf = read_vix_daily_pdf("vix", cutoff_str, folder_str + "daily/")
        assert max(loaded_pdf["date"]) == max(d for d in daily_pdf["date"] if d <= pd.Timestamp(cutoff_str).date())
        assert list(loaded_pdf.columns) == ["timestamp", "open", "high", "low", "close", "created_ts", "date"]
        assert np.allclose(loaded_pdf["close"].to_numpy(), daily_pdf[daily_pdf["date"] <= pd.Timestamp(cutoff_str).date()]["close"].to_numpy())
    loaded_pdf = read_vix_1min_pdf("vix", "2026-05-13", None, folder_str + "1min/")
    assert max(loaded_pdf["date"]) == pd.Timestamp("2026-05-13").date() and len(loaded_pdf) == len(minute_pdf)
    assert (pd.DatetimeIndex(loaded_pdf["timestamp"]) == pd.DatetimeIndex(minute_pdf["timestamp"])).all()
    assert len(read_vix_1min_pdf("vix", "2026-05-12", None, folder_str + "1min/")["date"].unique()) == 1
    # A DATE THAT DIFFERS FROM THE NEW YORK DATE OF ITS TIMESTAMP RAISES
    bad_pdf = daily_pdf[pd.to_datetime(daily_pdf["date"]).dt.year == 2025].copy()
    bad_pdf.loc[bad_pdf.index[3], "timestamp"] = bad_pdf.loc[bad_pdf.index[3], "timestamp"] - pd.Timedelta(hours=3)
    os.makedirs(f"{folder_str}bad/", exist_ok=True)
    write_raw_bar_file(bad_pdf, f"{folder_str}bad/ohlcv_data_2025.csv")
    try:
        read_vix_daily_pdf("vix", "2025-12-31", folder_str + "bad/")
        raise AssertionError("a date mismatch was accepted")
    except ValueError:
        pass
    passed("loaders (cutoff required and < 2026-05-14; no row after the cutoff; later files never opened; date check)")

# FUNCTION: BUILD THE SYNTHETIC SPY TABLE AND VIX BARS
def get_synthetic_setup_dict():
    # BUILD THE SPY DAILY TABLE
    daily_pdf = get_daily_feature_pdf(get_ohlcv_array_dict(get_synthetic_ohlcv_pdf(SPAN_START_STR, SPAN_END_STR, seed_in=7)))
    # BUILD THE INDEX BARS
    daily_bar_pdf_dict = {"vix": get_synthetic_daily_bar_pdf(SPAN_START_STR, SPAN_END_STR, 15.0, 11), "vix3m": get_synthetic_daily_bar_pdf(SPAN_START_STR, SPAN_END_STR, 17.0, 12)}
    minute_bar_pdf_dict = {"vix": get_synthetic_minute_bar_pdf(SPAN_START_STR, SPAN_END_STR, 15.0, 13), "vix3m": get_synthetic_minute_bar_pdf(SPAN_START_STR, SPAN_END_STR, 17.0, 14)}
    # RETURN THE SETUP
    return {"daily_pdf": daily_pdf, "daily_bar_pdf_dict": daily_bar_pdf_dict, "minute_bar_pdf_dict": minute_bar_pdf_dict,
            "start_date_dict": {"vix": SPAN_START_STR, "vix3m": SPAN_START_STR}}

# FUNCTION: BUILD THE FEATURES OF BOTH VARIANTS
def get_all_feature_pdf(daily_pdf_in, daily_bar_pdf_dict_in, minute_bar_pdf_dict_in, start_date_dict_in):
    # BUILD THE TABLE
    table_pdf = get_vix_table_pdf(daily_pdf_in, daily_bar_pdf_dict_in, minute_bar_pdf_dict_in, start_date_dict_in)
    # RETURN THE FEATURES OF BOTH VARIANTS
    return pd.concat([get_vix_feature_pdf(table_pdf, daily_pdf_in["daily_volatility"].to_numpy(), v) for v in vix_config.VARIANT_STR_LIST], axis=1)

# FUNCTION: TEST THE TIMING OF BOTH VARIANTS
def test_timing(setup_dict_in):
    # BUILD THE TABLE
    daily_pdf = setup_dict_in["daily_pdf"]
    table_pdf = get_vix_table_pdf(daily_pdf, setup_dict_in["daily_bar_pdf_dict"], setup_dict_in["minute_bar_pdf_dict"], setup_dict_in["start_date_dict"])
    # _prev IS THE CLOSE OF THE PREVIOUS SESSION'S DATE (EVERY DATE HAS A BAR HERE), NEVER THE SAME DATE'S
    close_series = setup_dict_in["daily_bar_pdf_dict"]["vix"].set_index("date")["close"]
    expected_arr = close_series.reindex(table_pdf["date"].shift(1)).to_numpy()
    assert table_pdf["vix_prev_status"].iloc[0] == "before_start" and np.isnan(table_pdf["vix_prev"].iloc[0])
    assert np.allclose(table_pdf["vix_prev"].to_numpy()[1:], expected_arr[1:]) and (table_pdf["vix_prev_lag"].to_numpy()[1:] == 0).all()
    assert not np.allclose(table_pdf["vix_prev"].to_numpy()[1:], close_series.reindex(table_pdf["date"]).to_numpy()[1:])
    # _intraday IS THE BAR LABELLED DECISION - 1 MINUTE: 15:57 ON A FULL DAY, 12:57 ON A HALF DAY
    for date_str, decision_str, bar_str in [("2020-03-10", "15:58", "15:57"), ("2020-11-27", "12:58", "12:57"), ("2019-07-03", "12:58", "12:57")]:
        row = table_pdf[table_pdf["date"] == pd.Timestamp(date_str).date()].iloc[0]
        assert pd.Timestamp(row["decision_ts"]).strftime("%H:%M") == decision_str and pd.Timestamp(row["vix_intraday_ts"]).tz_convert(ny_tz).strftime("%H:%M") == bar_str
        minute_pdf = setup_dict_in["minute_bar_pdf_dict"]["vix"]
        bar_close = minute_pdf[(minute_pdf["date"] == row["date"]) & (pd.DatetimeIndex(minute_pdf["timestamp"]).strftime("%H:%M") == bar_str)]["close"].iloc[0]
        assert row["vix_intraday"] == bar_close and row["vix_intraday_source"] == "bar"
    passed("timing (_prev = close of the strictly previous date; _intraday = bar at 15:57 on a full day, 12:57 on half days)")

# FUNCTION: TEST THE STALENESS RULE, THE FALLBACK AND THE SERIES START
def test_staleness_fallback(setup_dict_in):
    # COLLECT THE SESSIONS
    daily_pdf = setup_dict_in["daily_pdf"]
    date_list = daily_pdf["date"].tolist()
    # REMOVE 3 CONSECUTIVE DAILY BARS IN 2019 (LAG 3 ACCEPTED) AND 4 IN 2020 (LAG 4 STALE)
    block3_list, block4_list = date_list[100:103], date_list[300:304]
    daily_bar_pdf = setup_dict_in["daily_bar_pdf_dict"]["vix"]
    daily_bar_pdf = daily_bar_pdf[~daily_bar_pdf["date"].isin(block3_list + block4_list)]
    # REMOVE THE 1-MINUTE BARS OF A FULL DAY AND OF A HALF DAY IN 2020; KEEP ONLY BARS AFTER 12:57 ON A 2019 HALF DAY
    minute_pdf = setup_dict_in["minute_bar_pdf_dict"]["vix"]
    minute_label_arr = pd.DatetimeIndex(minute_pdf["timestamp"]).strftime("%H:%M").to_numpy()
    drop_bool_arr = minute_pdf["date"].isin([pd.Timestamp("2020-03-10").date(), pd.Timestamp("2020-11-27").date()]).to_numpy()
    drop_bool_arr |= (minute_pdf["date"] == pd.Timestamp("2019-11-29").date()).to_numpy() & (minute_label_arr <= "12:57")
    minute_pdf = minute_pdf[~drop_bool_arr]
    # BUILD THE TABLE WITH VIX3M STARTING ON 2019-08-12
    start_date_dict = {"vix": SPAN_START_STR, "vix3m": "2019-08-12"}
    vix3m_daily_pdf = setup_dict_in["daily_bar_pdf_dict"]["vix3m"]
    vix3m_daily_pdf = vix3m_daily_pdf[vix3m_daily_pdf["date"] >= pd.Timestamp("2019-08-12").date()]
    vix3m_minute_pdf = setup_dict_in["minute_bar_pdf_dict"]["vix3m"]
    vix3m_minute_pdf = vix3m_minute_pdf[vix3m_minute_pdf["date"] >= pd.Timestamp("2019-08-12").date()]
    table_pdf = get_vix_table_pdf(daily_pdf, {"vix": daily_bar_pdf, "vix3m": vix3m_daily_pdf}, {"vix": minute_pdf, "vix3m": vix3m_minute_pdf}, start_date_dict)
    # LAG 3 IS ACCEPTED: THE SESSION AFTER THE 3-BAR GAP USES THE BAR BEFORE THE GAP
    after3_row, before3_date = table_pdf.iloc[103], date_list[99]
    assert after3_row["vix_prev_status"] == "ok" and after3_row["vix_prev_lag"] == 3 and after3_row["vix_prev"] == daily_bar_pdf.set_index("date")["close"][before3_date]
    # LAG 4 IS STALE (NaN)
    assert table_pdf.iloc[304]["vix_prev_status"] == "stale" and np.isnan(table_pdf.iloc[304]["vix_prev"]) and table_pdf.iloc[304]["vix_prev_lag"] == 4
    assert table_pdf.iloc[303]["vix_prev_status"] == "ok" and table_pdf.iloc[303]["vix_prev_lag"] == 3
    # THE COUNTS PER YEAR
    coverage_pdf = get_vix_coverage_pdf(table_pdf).set_index(["series", "year"])
    year4_int, year3_int = date_list[300].year, date_list[100].year
    assert year3_int == 2019 and year4_int == 2020
    assert coverage_pdf.loc[("vix", 2019), "prev_ok_lagged"] == 3 and coverage_pdf.loc[("vix", 2019), "prev_stale"] == 0 and coverage_pdf.loc[("vix", 2019), "prev_before_start"] == 1
    assert coverage_pdf.loc[("vix", 2020), "prev_ok_lagged"] == 3 and coverage_pdf.loc[("vix", 2020), "prev_stale"] == 1
    assert coverage_pdf.loc[("vix", 2019), "intraday_fallback"] == 1 and coverage_pdf.loc[("vix", 2020), "intraday_fallback"] == 2 and coverage_pdf.loc[("vix", 2021), "intraday_fallback"] == 0
    # A FALLBACK USES THE _prev VALUE
    fallback_pdf = table_pdf[table_pdf["vix_intraday_source"] == "fallback"]
    assert len(fallback_pdf) == 3 and np.allclose(fallback_pdf["vix_intraday"].to_numpy(), fallback_pdf["vix_prev"].to_numpy())
    # VIX3M IS NaN BEFORE ITS FIRST DATE (before_start, NOT MISSING OR FALLBACK); ITS FIRST SESSION HAS AN INTRADAY VALUE ONLY
    before_bool_arr = table_pdf["date"].to_numpy() < pd.Timestamp("2019-08-12").date()
    assert table_pdf.loc[before_bool_arr, "vix3m_prev"].isna().all() and table_pdf.loc[before_bool_arr, "vix3m_intraday"].isna().all()
    assert (table_pdf.loc[before_bool_arr, "vix3m_intraday_source"] == "before_start").all()
    first_row = table_pdf[table_pdf["date"] == pd.Timestamp("2019-08-12").date()].iloc[0]
    assert first_row["vix3m_prev_status"] == "before_start" and np.isnan(first_row["vix3m_prev"]) and first_row["vix3m_intraday_source"] == "bar"
    assert coverage_pdf.loc[("vix3m", 2019), "prev_missing"] == 0 and coverage_pdf.loc[("vix3m", 2019), "intraday_fallback"] == 0
    # THE TERM FEATURE IS NaN BEFORE THE VIX3M START
    feature_pdf = get_vix_feature_pdf(table_pdf, daily_pdf["daily_volatility"].to_numpy(), "prev")
    assert feature_pdf.loc[before_bool_arr, "vix_term_prev"].isna().all() and feature_pdf.loc[~before_bool_arr, "vix_term_prev"].notna().sum() > 400
    passed("staleness (lag 3 kept, lag 4 NaN), fallback counts per year (1 in 2019, 2 in 2020), VIX3M before its start")

# FUNCTION: TEST THE ABSENCE OF LOOK-AHEAD
def test_no_look_ahead(setup_dict_in):
    # COLLECT THE SETUP
    daily_pdf, start_date_dict = setup_dict_in["daily_pdf"], setup_dict_in["start_date_dict"]
    full_feature_pdf = get_all_feature_pdf(daily_pdf, setup_dict_in["daily_bar_pdf_dict"], setup_dict_in["minute_bar_pdf_dict"], start_date_dict)
    assert full_feature_pdf.iloc[300:].notna().all().all()
    # CHOOSE SESSIONS (ONE HALF DAY)
    half_idx = int(np.flatnonzero(daily_pdf["date"].to_numpy() == pd.Timestamp("2020-11-27").date())[0])
    for session_idx in [300, half_idx, 560]:
        # COLLECT THE DECISION AND THE LAST ALLOWED LABEL
        session_date, decision_ts = daily_pdf["date"].iloc[session_idx], pd.Timestamp(daily_pdf["decision_ts"].iloc[session_idx])
        allowed_ts = decision_ts - pd.Timedelta(minutes=1)
        # PERTURB EVERY DAILY CLOSE DATED ON OR AFTER THE SESSION'S DATE AND EVERY 1-MINUTE BAR LABELLED AFTER THE ALLOWED TIME
        rng = np.random.default_rng(session_idx)
        daily_bar_pdf_dict = {s: p.assign(close=np.where(p["date"].to_numpy() >= session_date, p["close"].to_numpy() * rng.uniform(0.5, 2.0, len(p)), p["close"].to_numpy()))
                              for s, p in setup_dict_in["daily_bar_pdf_dict"].items()}
        minute_bar_pdf_dict = {s: p.assign(close=np.where(pd.DatetimeIndex(p["timestamp"]) > allowed_ts, p["close"].to_numpy() * rng.uniform(0.5, 2.0, len(p)), p["close"].to_numpy()))
                               for s, p in setup_dict_in["minute_bar_pdf_dict"].items()}
        perturbed_feature_pdf = get_all_feature_pdf(daily_pdf, daily_bar_pdf_dict, minute_bar_pdf_dict, start_date_dict)
        # NO FEATURE OF SESSIONS UP TO t CHANGES; LATER FEATURES DO
        assert check_equal_pdf(perturbed_feature_pdf.iloc[:session_idx + 1], full_feature_pdf.iloc[:session_idx + 1])
        assert not check_equal_pdf(perturbed_feature_pdf.iloc[session_idx + 1:], full_feature_pdf.iloc[session_idx + 1:])
        # PERTURBING THE ALLOWED BAR ITSELF CHANGES THE INTRADAY FEATURES OF t (THE TEST IS SENSITIVE)
        minute_bar_pdf_dict = {s: p.assign(close=np.where(pd.DatetimeIndex(p["timestamp"]) == allowed_ts, p["close"].to_numpy() * 1.5, p["close"].to_numpy()))
                               for s, p in setup_dict_in["minute_bar_pdf_dict"].items()}
        sensitive_feature_pdf = get_all_feature_pdf(daily_pdf, setup_dict_in["daily_bar_pdf_dict"], minute_bar_pdf_dict, start_date_dict)
        assert sensitive_feature_pdf["vix_level_intraday"].iloc[session_idx] != full_feature_pdf["vix_level_intraday"].iloc[session_idx]
        assert check_equal_pdf(sensitive_feature_pdf[get_vix_feature_col_list("prev")], full_feature_pdf[get_vix_feature_col_list("prev")])
    passed("no look-ahead (later daily closes and bars after decision - 1 minute change nothing up to t; both variants; half day included)")

# FUNCTION: TEST THE FORMULAS BY HAND
def test_formulas():
    # BUILD A SMALL TABLE WITH ONE MISSING VALUE
    rng = np.random.default_rng(5)
    row_count = 300
    x_arr = np.round(15 * np.exp(np.cumsum(rng.normal(0, 0.05, row_count))), 2)
    x_arr[100] = np.nan
    m_arr = x_arr * rng.uniform(0.85, 1.15, row_count)
    m_arr[200] = np.nan
    vol_arr = rng.uniform(0.005, 0.02, row_count)
    vol_arr[0] = np.nan
    table_pdf = pd.DataFrame({"vix_prev": x_arr, "vix3m_prev": m_arr})
    feature_pdf = get_vix_feature_pdf(table_pdf, vol_arr, "prev")
    # COMPUTE THE FEATURES BY HAND
    for t in range(row_count):
        # LEVEL, TERM AND VRP
        assert np.allclose(feature_pdf["vix_level_prev"].iloc[t], x_arr[t], equal_nan=True)
        assert np.allclose(feature_pdf["vix_term_prev"].iloc[t], x_arr[t] / m_arr[t], equal_nan=True)
        assert np.allclose(feature_pdf["vrp_prev"].iloc[t], (x_arr[t] / 100) ** 2 - (vol_arr[t] * np.sqrt(252)) ** 2, equal_nan=True)
        # PERCENTILE OF THE PREVIOUS 250 VALUES
        window_arr = x_arr[t - 250:t] if t >= 250 else None
        pct_float = np.nan if window_arr is None or np.isnan(window_arr).any() or np.isnan(x_arr[t]) else float((window_arr < x_arr[t]).sum()) / 250
        assert np.allclose(feature_pdf["vix_pct250_prev"].iloc[t], pct_float, equal_nan=True)
        # 5-SESSION LOG CHANGE
        assert np.allclose(feature_pdf["vix_chg5_prev"].iloc[t], np.log(x_arr[t] / x_arr[t - 5]) if t >= 5 else np.nan, equal_nan=True)
        # FADE FROM THE 20-VALUE MAXIMUM
        fade_window_arr = x_arr[t - 19:t + 1] if t >= 19 else None
        fade_float = np.nan if fade_window_arr is None or np.isnan(fade_window_arr).any() else x_arr[t] / fade_window_arr.max() - 1
        assert np.allclose(feature_pdf["vix_fade_prev"].iloc[t], fade_float, equal_nan=True)
    # THE NaN AT ROW 100 BLOCKS THE PERCENTILE OF ROWS 101-350, THE FADE OF ROWS 100-119
    assert feature_pdf["vix_pct250_prev"].iloc[250:].isna().all() and feature_pdf["vix_fade_prev"].iloc[100:120].isna().all() and feature_pdf["vix_fade_prev"].iloc[120:].notna().all()
    # A TABLE WITHOUT GAPS HAS PERCENTILES FROM ROW 250 AND THE FADE IS NEVER POSITIVE
    clean_pdf = get_vix_feature_pdf(pd.DataFrame({"vix_prev": np.nan_to_num(x_arr, nan=15.0), "vix3m_prev": 1.0}), vol_arr, "prev")
    assert clean_pdf["vix_pct250_prev"].iloc[:250].isna().all() and clean_pdf["vix_pct250_prev"].iloc[250:].between(0, 1).all()
    assert (clean_pdf["vix_fade_prev"].dropna() <= 0).all() and (clean_pdf["vix_fade_prev"].dropna() == 0).any()
    assert get_vix_feature_col_list("intraday") == ["vix_level_intraday", "vix_pct250_intraday", "vix_chg5_intraday", "vix_fade_intraday", "vix_term_intraday", "vrp_intraday"]
    passed("formulas by hand (level, pct250, chg5, fade, term, vrp; NaN propagation; fade <= 0)")

# FUNCTION: TEST THE END-TO-END FUNCTION ON RAW-FORMAT FILES
def test_end_to_end():
    # BUILD A SHORT SPY TABLE AND ITS INDEX BARS
    date1_str, date2_str = "2020-10-01", "2021-01-29"
    daily_pdf = get_daily_feature_pdf(get_ohlcv_array_dict(get_synthetic_ohlcv_pdf(date1_str, date2_str, seed_in=3)))
    folder_dict, daily_bar_pdf_dict, minute_bar_pdf_dict = {}, {}, {}
    for seed_int, series_str in enumerate(vix_config.VIX_SERIES_STR_LIST):
        daily_bar_pdf_dict[series_str] = get_synthetic_daily_bar_pdf("2020-09-01", "2021-02-26", 20.0 + seed_int, 20 + seed_int)
        minute_bar_pdf_dict[series_str] = get_synthetic_minute_bar_pdf("2020-09-25", "2021-02-26", 20.0 + seed_int, 30 + seed_int)
        write_raw_series(daily_bar_pdf_dict[series_str], minute_bar_pdf_dict[series_str], f"{TMP_PATH_STR}e2e_{series_str}/")
        folder_dict.update({(series_str, "daily"): f"{TMP_PATH_STR}e2e_{series_str}/daily/", (series_str, "1min"): f"{TMP_PATH_STR}e2e_{series_str}/1min/"})
    # THE SPY TABLE MAY NOT RUN PAST THE CUTOFF
    try:
        get_vix_daily_feature_dict(daily_pdf, "2021-01-15", raw_path_dict_in=folder_dict)
        raise AssertionError("an SPY table past the cutoff was accepted")
    except AssertionError as error:
        assert "past the VIX cutoff" in str(error)
    # RUN THE END-TO-END FUNCTION WITH THE CUTOFF AT THE LAST SPY SESSION
    result_dict = get_vix_daily_feature_dict(daily_pdf, date2_str, raw_path_dict_in=folder_dict)
    assert result_dict["last_date_dict"] == {"vix_daily": pd.Timestamp(date2_str).date(), "vix3m_daily": pd.Timestamp(date2_str).date(), "vix_1min": pd.Timestamp(date2_str).date(), "vix3m_1min": pd.Timestamp(date2_str).date()}
    # IT EQUALS THE IN-MEMORY COMPUTATION ON THE BARS UP TO THE CUTOFF
    cut_daily_dict = {s: p[p["date"] <= pd.Timestamp(date2_str).date()] for s, p in daily_bar_pdf_dict.items()}
    cut_minute_dict = {s: p[(p["date"] <= pd.Timestamp(date2_str).date()) & (p["date"] >= pd.Timestamp(date1_str).date())] for s, p in minute_bar_pdf_dict.items()}
    expected_pdf = get_all_feature_pdf(daily_pdf, cut_daily_dict, cut_minute_dict, vix_config.SERIES_START_DATE_DICT)
    feature_col_list = get_vix_feature_col_list("prev") + get_vix_feature_col_list("intraday")
    assert list(result_dict["feature_pdf"].columns) == ["session_idx", "date"] + feature_col_list
    assert check_equal_pdf(result_dict["feature_pdf"][feature_col_list], expected_pdf[feature_col_list])
    assert result_dict["feature_pdf"]["vix_level_intraday"].notna().all() and result_dict["feature_pdf"]["vix_level_prev"].notna().all()
    # THE PRIMARY-ONLY CALL DOES NOT LOAD THE 1-MINUTE BARS
    prev_dict = get_vix_daily_feature_dict(daily_pdf, date2_str, ["prev"], raw_path_dict_in=folder_dict)
    assert prev_dict["minute_bar_pdf_dict"] is None and list(prev_dict["feature_pdf"].columns) == ["session_idx", "date"] + get_vix_feature_col_list("prev")
    passed("end-to-end (raw-format files, cutoff checks, equal to the in-memory computation, primary-only call)")

# RUN THE TESTS
if __name__ == "__main__":
    # START FROM AN EMPTY TEMPORARY FOLDER
    shutil.rmtree(TMP_PATH_STR, ignore_errors=True)
    os.makedirs(TMP_PATH_STR, exist_ok=True)
    try:
        test_loaders()
        setup_dict = get_synthetic_setup_dict()
        test_timing(setup_dict)
        test_staleness_fallback(setup_dict)
        test_no_look_ahead(setup_dict)
        test_formulas()
        test_end_to_end()
    finally:
        # REMOVE THE TEMPORARY FOLDER
        shutil.rmtree(TMP_PATH_STR, ignore_errors=True)
    print("\nAll VIX data layer tests passed ✅")
