import sys
import numpy as np
import pandas as pd
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE SHARED CONFIGURATION AND THE PATHS
from so import config, paths
# IMPORT DATA LOADING, EXECUTION AND DAILY FEATURE FUNCTIONS
from so.core.raw_data import get_complete_ohlcv_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
# IMPORT THE exp02 STEP 01 BENCHMARKS (BUY AND HOLD, 200-SESSION TREND RULE)
from so.core.reentry_simulation import get_buy_and_hold_result_dict, simulate_trend_rule_dict
# IMPORT THE CONTINUOUS REPLAY AND THE exp04 RULES
from so.core.continuous_replay import simulate_continuous_replay_dict
from experiments.exp04_trend_exit import config as exp04_config
from experiments.exp04_trend_exit.rules import get_rule_builder_func

"""
SPY Raw Folder Rename Check (roadmap 2026-10-09, step 0.3; no trial-log entry)

The SPY raw folder was renamed to store01_rawzone/ibkr_spy_1min/ on main (so.paths). This script proves, through the
existing loaders and functions, that the renamed folder gives the numbers recorded before the rename:
    (a) 5,436 sessions, 2005-01-03 -> 2026-08-13 (a count of session DATES only: the bars are cut at 2026-04-15 right
        after the dates are collected, so no price dated 2026-05-14 or later enters any computation);
    (b) buy-and-hold 2005-01-03 -> 2014-12-31 = +69.02% and the 200-session trend rule = +50.39% (exp02 step 01);
    (c) exp04's continuous replay of x = 0, n = 1 over 2015-04-17 -> 2026-04-15 = +108.03% with 35 exits, and
        buy-and-hold over the same span = +235.39% (exp04 step 02).
Equality to 2 decimals of a percent and the exact exit count. Exit code 0 if every check holds, 1 otherwise.
"""

# DEFINE THE EXPECTED VALUES (RECORDED IN docs/RESULTS_LOG.md BEFORE THE RENAME)
EXPECTED_SESSION_COUNT = 5436
EXPECTED_FIRST_DATE_STR, EXPECTED_LAST_DATE_STR = "2005-01-03", "2026-08-13"
EXPECTED_EXPLORATION_BUY_HOLD_PCT, EXPECTED_EXPLORATION_TREND_PCT = 69.02, 50.39
EXPECTED_REPLAY_TREND_PCT, EXPECTED_REPLAY_EXIT_COUNT, EXPECTED_REPLAY_BUY_HOLD_PCT = 108.03, 35, 235.39
# DEFINE THE DATA CUT OF CHECKS (b) AND (c) AND THE REPLAY SPAN
DATA_CUT_DATE_STR = "2026-04-15"
REPLAY_START_DATE_STR, REPLAY_END_DATE_STR = "2015-04-17", "2026-04-15"

# FUNCTION: COMPARE A RETURN WITH ITS EXPECTED VALUE (2 DECIMALS OF A PERCENT)
def check_pct_bool(name_str_in, value_float_in, expected_pct_in):
    """
    Prints and compares a total return (fraction) with its expected value in percent, rounded to 2 decimals.

    Args:
        name_str_in (str): Name of the check
        value_float_in (float): Observed total return (fraction)
        expected_pct_in (float): Expected total return (percent, 2 decimals)

    Returns:
        bool: True if equal at 2 decimals
    """
    # ROUND THE OBSERVED VALUE AND COMPARE
    observed_pct = round(100 * float(value_float_in), 2)
    ok_bool = observed_pct == expected_pct_in
    # DISPLAY THE RESULT
    print(f"{'OK  ' if ok_bool else 'DIFF'}\t{name_str_in}:\t{observed_pct:+.2f}% (expected {expected_pct_in:+.2f}%)")
    # RETURN THE RESULT
    return ok_bool

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # DISPLAY THE RAW FOLDER
    print(f"Raw folder:\t{paths.LOCAL_OHLCV_DATA_FILE_PATH_STR}")
    # READ THE RAW BARS, COLLECT THE SESSION DATES, THEN CUT THE BARS AT THE DATA CUT (NO LATER PRICE IS USED)
    complete_ohlcv_pdf = get_complete_ohlcv_pdf()
    session_date_list = sorted(complete_ohlcv_pdf["date"].unique())
    cut_ohlcv_pdf = complete_ohlcv_pdf[complete_ohlcv_pdf["date"] <= pd.Timestamp(DATA_CUT_DATE_STR).date()].reset_index(drop=True)
    del complete_ohlcv_pdf
    # (a) SESSION COUNT AND RANGE
    result_bool_list = [len(session_date_list) == EXPECTED_SESSION_COUNT and str(session_date_list[0]) == EXPECTED_FIRST_DATE_STR and str(session_date_list[-1]) == EXPECTED_LAST_DATE_STR]
    print(f"{'OK  ' if result_bool_list[-1] else 'DIFF'}\t(a) sessions:\t{len(session_date_list):,}, {session_date_list[0]} -> {session_date_list[-1]} (expected {EXPECTED_SESSION_COUNT:,}, {EXPECTED_FIRST_DATE_STR} -> {EXPECTED_LAST_DATE_STR})")
    # BUILD THE ARRAYS AND THE DAILY TABLE OF THE CUT DATA
    ohlcv_array_dict = get_ohlcv_array_dict(cut_ohlcv_pdf)
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict)
    print(f"Bars used by (b) and (c):\t{cut_ohlcv_pdf['date'].min()} -> {cut_ohlcv_pdf['date'].max()}")
    assert cut_ohlcv_pdf["date"].max() < pd.Timestamp(exp04_config.UNTOUCHED_START_DATE_STR).date()
    # (b) EXPLORATION BUY AND HOLD AND 200-SESSION TREND RULE (exp02 STEP 01 FUNCTIONS)
    exploration_buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, config.EXPLORATION_START_DATE_STR, config.EXPLORATION_END_DATE_STR)
    exploration_trend_dict = simulate_trend_rule_dict(ohlcv_array_dict, daily_pdf, config.EXPLORATION_START_DATE_STR, config.EXPLORATION_END_DATE_STR, "ma200_dist_pct")
    result_bool_list.append(check_pct_bool("(b) buy-and-hold 2005-2014", exploration_buy_hold_dict["metric_dict"]["total_return"], EXPECTED_EXPLORATION_BUY_HOLD_PCT))
    result_bool_list.append(check_pct_bool("(b) 200-session rule 2005-2014", exploration_trend_dict["metric_dict"]["total_return"], EXPECTED_EXPLORATION_TREND_PCT))
    # (c) exp04 CONTINUOUS REPLAY OF x = 0, n = 1 AND BUY AND HOLD OVER THE VALIDATION SPAN
    exit_signal_arr, reentry_func, reason_str = get_rule_builder_func(daily_pdf)({"buffer": 0.0, "confirmation": 1})
    replay_dict = simulate_continuous_replay_dict(ohlcv_array_dict, REPLAY_START_DATE_STR, REPLAY_END_DATE_STR, exp04_config.UNTOUCHED_START_DATE_STR,
                                                  volatility_arr_in=np.full(len(daily_pdf), np.nan), stop_k_in=None, reentry_func_in=reentry_func,
                                                  reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr, max_cash_sessions_in=exp04_config.MAX_CASH_SESSIONS)
    replay_buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, REPLAY_START_DATE_STR, REPLAY_END_DATE_STR)
    result_bool_list.append(check_pct_bool("(c) exp04 x = 0, n = 1 replay", replay_dict["metric_dict"]["total_return"], EXPECTED_REPLAY_TREND_PCT))
    exit_count = int(replay_dict["metric_dict"]["signal_exit_count"])
    result_bool_list.append(exit_count == EXPECTED_REPLAY_EXIT_COUNT)
    print(f"{'OK  ' if result_bool_list[-1] else 'DIFF'}\t(c) exits:\t{exit_count} (expected {EXPECTED_REPLAY_EXIT_COUNT})")
    result_bool_list.append(check_pct_bool("(c) buy-and-hold 2015-04-17 -> 2026-04-15", replay_buy_hold_dict["metric_dict"]["total_return"], EXPECTED_REPLAY_BUY_HOLD_PCT))
    # DISPLAY THE VERDICT AND EXIT
    print(f"\nRENAME CHECK:\t{'PASSED' if all(result_bool_list) else 'FAILED'}\t({sum(result_bool_list)} of {len(result_bool_list)} checks)")
    raise SystemExit(0 if all(result_bool_list) else 1)
