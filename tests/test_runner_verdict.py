"""
Workspace Tests: runner baselines, verdict, report, manifest (infrastructure 4b-1b)

Run from the workspace root:   python tests/test_runner_verdict.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import json
import os
import sys
import tempfile
import shutil
import numpy as np
import pandas as pd

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
_CURRENT_DATA_PATH_STR = os.environ.get("SO_DATA_PATH", "").strip()
_TEMP_DIR_STR = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
OWNED_TEMP_BOOL = False
if _CURRENT_DATA_PATH_STR and os.path.normcase(os.path.abspath(_CURRENT_DATA_PATH_STR)).startswith(_TEMP_DIR_STR + os.sep):
    TEMP_ROOT_STR = _CURRENT_DATA_PATH_STR
else:
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_verdict_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths
from so.core.evaluation import get_success_criteria_dict, get_rolling_month_window_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from so.runner import (run_development_dict, check_clean_tree, CLEAN_TREE_MESSAGE_STR, get_code_hash_str,
                       get_guarded_code_folder_list, get_runner_baseline_dict, get_random_timing_weight_arr,
                       get_random_timing_seed_list, run_weight_path_dict, get_runner_verdict_dict,
                       get_return_verdict_dict, get_consistency_verdict_dict, get_baseline_verdict_dict,
                       LOOK_AHEAD_PENDING_STR, LOOK_AHEAD_PASS_STR, LOOK_AHEAD_FAIL_STR, EMAIL_WORTHY_STR,
                       NOT_EMAIL_WORTHY_STR, MANIFEST_FILE_STR, LOOKAHEAD_FILE_STR)
from so.runner.checkpoint import get_run_folder_str
from so.runner.baselines import (get_unique_weight_list, get_weight_run_list, get_weight_time_dict,
                                 get_base_weight_float, get_non_base_spell_list, get_base_gap_list,
                                 get_weight_equal_bool)
from so.runner.verdict import REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_candidate_design as cand_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR


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


# FUNCTION: ONE SESSION PER MONTH WITH A CONSTANT DAILY RETURN
def get_month_return_pdf(start_str_in, return_list_in):
    """
    Args:
        start_str_in (str): First month start
        return_list_in (list[float]): One return per month

    Returns:
        pd.DataFrame: date, daily_return
    """
    # THE FIRST CALENDAR DAY OF EACH MONTH
    date_index = pd.date_range(start_str_in, periods=len(return_list_in), freq="MS")
    return pd.DataFrame({"date": list(date_index.date), "daily_return": [float(value) for value in return_list_in]})


# FUNCTION: A BASELINE DICT THE VERDICT CAN BEAT OR LOSE TO
def get_hand_baseline_dict(constant_return_in, random_return_in, draw_count_int_in=100):
    """
    Args:
        constant_return_in (float): Constant-exposure total return
        random_return_in (float): Each random draw's total return
        draw_count_int_in (int): How many identical draws

    Returns:
        dict: Fields get_baseline_verdict_dict reads
    """
    # FIXED SEEDS ARE RECORDED BUT NOT USED
    return {"constant_exposure_total_return": float(constant_return_in), "constant_exposure_weight": 0.5,
            "random_timing_return_list": [float(random_return_in)] * int(draw_count_int_in),
            "random_timing_seed_list": get_random_timing_seed_list(draw_count_int_in),
            "random_timing_switch_count": 2, "buy_hold_total_return": 0.0}


# FUNCTION: THREE INJECTED PERIODS ON A SHORT SYNTHETIC SPAN
def get_injected_period_pdf(session_date_list_in):
    """
    Args:
        session_date_list_in (list): Session dates (at least 12)

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, valid_start, valid_end
    """
    # THE SAME SPLIT AS test_runner_candidates
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    assert len(session_date_list) >= 12
    bound_list = [(0, 3), (4, 7), (8, len(session_date_list) - 1)]
    row_dict_list = []
    for period_id, (start_idx, end_idx) in enumerate(bound_list):
        start_date, end_date = session_date_list[start_idx], session_date_list[end_idx]
        row_dict_list.append({"period_id": period_id, "period_start": start_date, "period_end": end_date,
                              "session_count": int(end_idx - start_idx + 1), "valid_start": start_date, "valid_end": end_date})
    return pd.DataFrame(row_dict_list)


# FUNCTION: A TRIAL-LOG PATH INSIDE THE TEMPORARY DATA ROOT
def get_test_trial_log_path_str(file_name_str_in):
    """
    Args:
        file_name_str_in (str): File name

    Returns:
        str: CSV path
    """
    # THE FOLDER IS CREATED HERE
    folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_verdict_test")
    os.makedirs(folder_str, exist_ok=True)
    return os.path.join(folder_str, file_name_str_in)


# FUNCTION: EACH RETURN PART PASSES AND FAILS, INCLUDING THE 90-100% BAND
def test_return_verdict_parts():
    """
    >= buy-and-hold passes. The comparable band passes only with a smaller drawdown or a higher Sharpe. Below 90%
    fails.

    Returns:
        None
    """
    # CONSTANT POSITIVE BUY-AND-HOLD
    buy_hold_pdf = pd.DataFrame({"date": pd.bdate_range("2010-01-04", periods=20).date,
                                 "daily_return": np.full(20, 0.001)})
    same_pdf = buy_hold_pdf.copy()
    same_success_dict = get_success_criteria_dict(same_pdf, buy_hold_pdf)
    same_dict = get_return_verdict_dict(same_success_dict)
    assert same_dict["pass_bool"] and same_dict["reason_str"] == "total_return_at_least_buy_hold"
    better_pdf = buy_hold_pdf.assign(daily_return=0.002)
    better_dict = get_return_verdict_dict(get_success_criteria_dict(better_pdf, buy_hold_pdf))
    assert better_dict["pass_bool"] and better_dict["reason_str"] == "total_return_at_least_buy_hold"
    # BELOW 90%: HALF THE DAILY RETURN
    below_pdf = buy_hold_pdf.assign(daily_return=0.0004)
    below_success_dict = get_success_criteria_dict(below_pdf, buy_hold_pdf)
    below_dict = get_return_verdict_dict(below_success_dict)
    assert not below_dict["pass_bool"] and below_dict["reason_str"] == "below_comparable"
    assert below_success_dict["strategy_total_return"] < 0.9 * below_success_dict["buy_hold_total_return"]
    # 90-100% BAND, ZERO VOLATILITY: NO SECONDARY WIN
    band_pdf = buy_hold_pdf.assign(daily_return=0.00095)
    band_success_dict = get_success_criteria_dict(band_pdf, buy_hold_pdf)
    band_dict = get_return_verdict_dict(band_success_dict)
    assert band_success_dict["comparable_return"] and band_success_dict["strategy_total_return"] < band_success_dict["buy_hold_total_return"]
    assert not band_dict["pass_bool"] and band_dict["reason_str"] == "comparable_without_secondary"
    # 90-100% BAND WITH A SMALLER DRAWDOWN (ALWAYS-UP VS AN OSCILLATING BUY-AND-HOLD)
    osc_pdf = pd.DataFrame({"date": pd.bdate_range("2010-01-04", periods=20).date,
                            "daily_return": np.array([0.04, -0.02] * 10, dtype=float)})
    flat_pdf = osc_pdf.assign(daily_return=np.full(20, 0.009))
    scaled_success_dict = get_success_criteria_dict(flat_pdf, osc_pdf)
    scaled_dict = get_return_verdict_dict(scaled_success_dict)
    assert scaled_success_dict["comparable_return"] and scaled_success_dict["strategy_total_return"] < scaled_success_dict["buy_hold_total_return"]
    assert scaled_success_dict["secondary_drawdown"] and scaled_dict["pass_bool"]
    assert scaled_dict["reason_str"] == "comparable_with_secondary"
    # 90-100% BAND WITH A HIGHER SHARPE (LOWER VOLATILITY, STILL SOME MOVEMENT)
    low_vol_pdf = osc_pdf.assign(daily_return=np.array([0.012, 0.006] * 10, dtype=float))
    sharpe_success_dict = get_success_criteria_dict(low_vol_pdf, osc_pdf)
    sharpe_dict = get_return_verdict_dict(sharpe_success_dict)
    assert sharpe_success_dict["comparable_return"] and sharpe_success_dict["strategy_total_return"] < sharpe_success_dict["buy_hold_total_return"]
    assert sharpe_success_dict["secondary_sharpe"] and sharpe_dict["pass_bool"]
    passed("each return verdict part passes and fails including the 90-100% band")


# FUNCTION: CONSISTENCY PASSES AT 60% AND FAILS BELOW
def test_consistency_verdict_parts():
    """
    16 months, 5 rolling 12-month windows. Three windows ahead is 60% (pass). One window ahead is 20% (fail).
    Zero windows fail.

    Returns:
        None
    """
    # BUY-AND-HOLD FLAT; STRATEGY GETS A +10% MONTH IN THE FIRST THREE MONTHS
    buy_hold_pdf = get_month_return_pdf("2010-01-01", [0.0] * 16)
    pass_pdf = get_month_return_pdf("2010-01-01", [0.10, 0.10, 0.10] + [0.0] * 13)
    # THE OLD RULE (NO TIE BAND): 3 OF 5 AHEAD PASSES, 1 OF 5 FAILS
    pass_dict = get_consistency_verdict_dict(pass_pdf, buy_hold_pdf, tie_tolerance_in=-1.0, min_decisive_in=1)
    assert pass_dict["window_count"] == 5 and pass_dict["ahead_count"] == 3
    assert np.isclose(pass_dict["ahead_share"], 0.6) and pass_dict["pass_bool"]
    fail_pdf = get_month_return_pdf("2010-01-01", [0.10] + [0.0] * 15)
    fail_dict = get_consistency_verdict_dict(fail_pdf, buy_hold_pdf, tie_tolerance_in=-1.0, min_decisive_in=1)
    assert fail_dict["window_count"] == 5 and fail_dict["ahead_count"] == 1
    assert not fail_dict["pass_bool"]
    # THE TIE BAND (AUDIT S1): THE TWO WINDOWS WITH ZERO EXCESS ARE TIES, SO 3 OF 3 DECISIVE ARE AHEAD
    tie_dict = get_consistency_verdict_dict(pass_pdf, buy_hold_pdf, min_decisive_in=1)
    assert tie_dict["tie_count"] == 2 and tie_dict["decisive_count"] == 3 and np.isclose(tie_dict["ahead_share"], 1.0)
    assert tie_dict["pass_bool"]
    # A RARE-EXIT DESIGN: AHEAD ONLY IN THE WINDOWS WITH ITS ONE EXIT, IDENTICAL ELSEWHERE, IS NO LONGER PUNISHED
    rare_pdf = get_month_return_pdf("2010-01-01", [0.0] * 6 + [0.05] + [0.0] * 33)
    flat_pdf = get_month_return_pdf("2010-01-01", [0.0] * 40)
    old_rare_dict = get_consistency_verdict_dict(rare_pdf, flat_pdf, tie_tolerance_in=-1.0, min_decisive_in=1)
    assert not old_rare_dict["pass_bool"]
    rare_dict = get_consistency_verdict_dict(rare_pdf, flat_pdf, min_decisive_in=1)
    assert rare_dict["decisive_count"] == 7 and rare_dict["ahead_count"] == 7 and rare_dict["pass_bool"]
    # TOO FEW DECISIVE WINDOWS IS INSUFFICIENT EVIDENCE (THE DEFAULT MINIMUM IS 24)
    default_rare_dict = get_consistency_verdict_dict(rare_pdf, flat_pdf)
    assert default_rare_dict["min_decisive_count"] == 24 and not default_rare_dict["enough_decisive_bool"]
    assert not default_rare_dict["pass_bool"]
    short_pdf = get_month_return_pdf("2010-01-01", [0.01] * 3)
    short_dict = get_consistency_verdict_dict(short_pdf, get_month_return_pdf("2010-01-01", [0.0] * 3))
    assert short_dict["window_count"] == 0 and not short_dict["pass_bool"]
    window_pdf = get_rolling_month_window_pdf(pass_pdf, buy_hold_pdf, 12, 1)
    assert list(window_pdf["ahead_bool"]) == [True, True, True, False, False]
    passed("consistency: 60% of decisive windows, ties within +/-0.5 pp excluded, at least 24 decisive windows")


# FUNCTION: BASELINE VERDICT PASSES AND FAILS ON HAND-BUILT RETURNS
def test_baseline_verdict_parts():
    """
    Above the constant baseline and 95 of 100 random draws passes. Below the constant, or only 94 of 100, fails.

    Returns:
        None
    """
    # 96 OF 100 DRAWS BELOW THE PATH, CONSTANT BELOW THE PATH
    pass_baseline_dict = {"constant_exposure_total_return": 0.10, "constant_exposure_weight": 0.5,
                          "random_timing_return_list": [0.05] * 96 + [0.40] * 4, "random_timing_seed_list": list(range(100)),
                          "random_timing_switch_count": 2, "buy_hold_total_return": 0.12}
    pass_dict = get_baseline_verdict_dict(0.20, pass_baseline_dict)
    assert pass_dict["constant_pass_bool"] and pass_dict["random_pass_bool"] and pass_dict["pass_bool"]
    assert pass_dict["random_timing_beaten_count"] == 96
    constant_fail_dict = get_baseline_verdict_dict(0.20, {**pass_baseline_dict, "constant_exposure_total_return": 0.25})
    assert not constant_fail_dict["constant_pass_bool"] and not constant_fail_dict["pass_bool"]
    random_fail_dict = get_baseline_verdict_dict(0.20, {**pass_baseline_dict,
                                                       "random_timing_return_list": [0.05] * 94 + [0.40] * 6})
    assert random_fail_dict["random_timing_beaten_count"] == 94 and not random_fail_dict["random_pass_bool"]
    passed("baseline verdict passes and fails on constant exposure and the 95% random rule")


# FUNCTION: EMAIL-WORTHY ONLY WHEN EVERY PART PASSES
def test_email_worthy_needs_every_part():
    """
    A path that beats buy-and-hold, 60% of windows, the constant baseline and 95% of random draws is email-worthy
    only when look-ahead is pass. pending or a failed part is not email-worthy.

    Returns:
        None
    """
    # 48 MONTHS AHEAD OF A FLAT BUY-AND-HOLD (37 DECISIVE WINDOWS), EASY BASELINES, ONE DESIGN TRIED (EMPTY RECORDS)
    strategy_pdf = get_month_return_pdf("2010-01-01", [0.012, 0.006] * 24)
    buy_hold_pdf = get_month_return_pdf("2010-01-01", [0.0] * 48)
    easy_baseline_dict = get_hand_baseline_dict(-0.5, -0.5, 100)
    empty_log_str = os.path.join(TEMP_ROOT_STR, "verdict_empty_trial_log.csv")

    def get_runner_verdict_dict(strategy_pdf_in, buy_hold_pdf_in, baseline_dict_in, status_str_in, legacy_list_in=None):
        from so.runner.verdict import get_runner_verdict_dict as verdict_func
        return verdict_func(strategy_pdf_in, buy_hold_pdf_in, baseline_dict_in, status_str_in,
                            trial_log_path_str_in=empty_log_str, legacy_path_list_in=legacy_list_in or [])
    pass_dict = get_runner_verdict_dict(strategy_pdf, buy_hold_pdf, easy_baseline_dict, LOOK_AHEAD_PASS_STR)
    assert pass_dict["return_dict"]["pass_bool"] and pass_dict["consistency_dict"]["pass_bool"]
    assert pass_dict["baseline_dict"]["pass_bool"] and pass_dict["look_ahead_dict"]["pass_bool"]
    assert pass_dict["email_worthy_bool"] and pass_dict["label_str"] == EMAIL_WORTHY_STR
    assert pass_dict["failed_list"] == []
    pending_dict = get_runner_verdict_dict(strategy_pdf, buy_hold_pdf, easy_baseline_dict, LOOK_AHEAD_PENDING_STR)
    assert not pending_dict["email_worthy_bool"] and pending_dict["label_str"] == NOT_EMAIL_WORTHY_STR
    assert pending_dict["failed_list"] == ["look-ahead"]
    look_fail_dict = get_runner_verdict_dict(strategy_pdf, buy_hold_pdf, easy_baseline_dict, LOOK_AHEAD_FAIL_STR)
    assert look_fail_dict["failed_list"] == ["look-ahead"]
    hard_baseline_dict = get_hand_baseline_dict(10.0, 10.0, 100)
    base_fail_dict = get_runner_verdict_dict(strategy_pdf, buy_hold_pdf, hard_baseline_dict, LOOK_AHEAD_PASS_STR)
    assert "baselines" in base_fail_dict["failed_list"] and not base_fail_dict["email_worthy_bool"]
    # THE SAME PATH AFTER 2,000 DESIGNS WERE TRIED: THE RANDOM-TIMING DRAWS ARE NO LONGER FAR ENOUGH BELOW IT
    many_path_str = os.path.join(TEMP_ROOT_STR, "verdict_many_designs.csv")
    pd.DataFrame({"experiment": ["expZZ"] * 2000, "stage": ["validation"] * 2000,
                  "setting_json": [json.dumps({"candidate": f"c{idx}"}) for idx in range(2000)],
                  "metric_json": ["{}"] * 2000}).to_csv(many_path_str, index=False)
    close_baseline_dict = {**easy_baseline_dict, "random_timing_return_list": list(np.linspace(0.085, 0.415, 100))}
    one_dict = get_runner_verdict_dict(strategy_pdf, buy_hold_pdf, close_baseline_dict, LOOK_AHEAD_PASS_STR)
    many_dict = get_runner_verdict_dict(strategy_pdf, buy_hold_pdf, close_baseline_dict, LOOK_AHEAD_PASS_STR, [many_path_str])
    assert one_dict["multiple_testing_dict"]["design_count"] == 1 and "multiple-testing" not in one_dict["failed_list"]
    assert many_dict["multiple_testing_dict"]["design_count"] == 2000
    assert "multiple-testing" in many_dict["failed_list"] and not many_dict["email_worthy_bool"]
    passed("email-worthy only when every verdict part passes, including the multiple-testing part")


# FUNCTION: THE MULTIPLE-TESTING PIECES (AUDIT B5)
def test_multiple_testing_parts():
    """
    The deflated Sharpe ratio reproduces the paper's example (0.9004). Designs are counted once: folds, runs and a _v2
    port of the same rule do not add designs; notes do not count; the legacy records join by union. The random-timing
    p-value falls as the path moves above the draws.

    Returns:
        None
    """
    # BAILEY AND LOPEZ DE PRADO (2014): SR 2.5 A YEAR, 1,250 DAYS, SKEW -3, KURTOSIS 10, 100 TRIALS, V[SR] 0.5 A YEAR
    from so.core.multiple_testing import (get_deflated_sharpe_dict, get_tried_design_count_dict,
                                          get_random_timing_p_float, get_design_key_str)
    paper_dict = get_deflated_sharpe_dict(2.5 / np.sqrt(250), 1250, -3.0, 10.0, 0.5 / 250, 100)
    assert abs(paper_dict["probability"] - 0.9004) < 1e-3, paper_dict
    assert get_deflated_sharpe_dict(0.3, 40, 0.0, 3.0, float("nan"), 1)["variance_source_str"] == "null_1_over_T"
    # COUNTING
    log_path_str = os.path.join(TEMP_ROOT_STR, "mt_trial_log.csv")
    legacy_path_str = os.path.join(TEMP_ROOT_STR, "mt_legacy.csv")
    row_list = [{"experiment": "exp02_stop_reentry", "stage": "validation", "setting_json": json.dumps({"candidate": "A", "run_id": f"r{run}", "commit": "x"}), "metric_json": "{}"}
                for run in range(3)]
    row_list += [{"experiment": "exp02_stop_reentry", "stage": "validation", "setting_json": json.dumps({"candidate": "B", "run_id": "r0"}), "metric_json": "{}"},
                 {"experiment": "exp02_stop_reentry", "stage": "note", "setting_json": json.dumps({"candidate": "C"}), "metric_json": "{}"}]
    pd.DataFrame(row_list).to_csv(log_path_str, index=False)
    pd.DataFrame([{"experiment": "exp02_stop_reentry_v2", "stage": "validation", "setting_json": json.dumps({"candidate": "A", "window": "w1"}), "metric_json": "{}"},
                  {"experiment": "exp03_ath_exit", "stage": "exploration", "setting_json": json.dumps({"rule": "x"}), "metric_json": "{}"}]).to_csv(legacy_path_str, index=False)
    count_dict = get_tried_design_count_dict(log_path_str, [legacy_path_str])
    assert count_dict == {"current_count": 2, "legacy_count": 2, "total_count": 3}, count_dict
    assert get_design_key_str("exp02_stop_reentry_v2_1", {"candidate": "A", "commit": "y"}) == get_design_key_str("exp02_stop_reentry", {"candidate": "A"})
    # THE RESTORED PRE-RESET RECORDS ARE IN THE REPOSITORY AND COUNT
    restored_dict = get_tried_design_count_dict(log_path_str)
    assert restored_dict["legacy_count"] >= 200, restored_dict
    # RANDOM TIMING
    draw_list = list(np.linspace(0.0, 1.0, 100))
    assert get_random_timing_p_float(2.0, draw_list) < get_random_timing_p_float(1.0, draw_list) < 0.5
    assert get_random_timing_p_float(0.5, [0.1] * 10) == 0.0 and get_random_timing_p_float(0.05, [0.1] * 10) == 1.0
    passed(f"multiple testing: deflated Sharpe matches the paper, designs counted once ({restored_dict['legacy_count']} pre-reset), random-timing p-value")


# FUNCTION: RANDOM TIMING IS REPRODUCIBLE AND CONSTANT WEIGHT 1 EQUALS BUY-AND-HOLD
def test_baselines_reproducible_and_constant_one_equals_buy_hold():
    """
    The same bars and seeds give the same random-timing returns. Constant exposure at weight 1 matches buy-and-hold
    through the same engine.

    Returns:
        None
    """
    # A SHORT SYNTHETIC SPAN
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    session_count = len(ohlcv_array_dict["session_date_list"])
    one_arr = np.ones(session_count, dtype=float)
    one_dict = run_weight_path_dict(ohlcv_array_dict, date1, date2, one_arr, 1.0, 0.0)
    one_dict["metric_dict"]["mean_weight"] = 1.0
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, one_dict, seed_count_int_in=8)
    assert np.isclose(baseline_dict["constant_exposure_total_return"], baseline_dict["buy_hold_total_return"], atol=0.0)
    assert np.allclose(baseline_dict["constant_exposure_daily_equity_pdf"]["equity"].to_numpy(dtype=float),
                       baseline_dict["buy_hold_daily_equity_pdf"]["equity"].to_numpy(dtype=float), atol=0.0)
    # TWO SWITCHES SO THE FIXED SEEDS MOVE THE SWITCH DATES
    alt_arr = np.ones(session_count, dtype=float)
    if session_count > 6:
        alt_arr[3:6] = 0.0
    alt_dict = run_weight_path_dict(ohlcv_array_dict, date1, date2, alt_arr, 1.0, 0.0)
    first_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, alt_dict, seed_count_int_in=8)
    second_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, alt_dict, seed_count_int_in=8)
    assert first_dict["random_timing_return_list"] == second_dict["random_timing_return_list"]
    assert first_dict["random_timing_seed_list"] == get_random_timing_seed_list(8)
    seed_int = get_random_timing_seed_list(1)[0]
    assert np.allclose(get_random_timing_weight_arr(alt_arr, seed_int),
                       get_random_timing_weight_arr(alt_arr, seed_int), atol=0.0)
    assert get_weight_time_dict(get_random_timing_weight_arr(alt_arr, seed_int)) == get_weight_time_dict(alt_arr)
    assert get_unique_weight_list(alt_arr) == [1.0, 0.0]
    passed("baselines are reproducible with the fixed seeds and constant weight 1 equals buy-and-hold")


# FUNCTION: A WEIGHT PATH FROM (WEIGHT, LENGTH) RUNS
def get_run_weight_arr(run_list_in):
    """
    Args:
        run_list_in (list[tuple]): (weight, length) in order

    Returns:
        np.ndarray: One weight per session
    """
    # CONCATENATE THE SPELLS
    value_list = []
    for weight, length_int in run_list_in:
        value_list.extend([float(weight)] * int(length_int))
    return np.asarray(value_list, dtype=float)


# FUNCTION: SPELL TUPLES IN PATH ORDER
def get_spell_tuple_list(target_weight_arr_in):
    """
    Args:
        target_weight_arr_in (array-like): Path targets

    Returns:
        list[tuple]: One tuple per non-base spell
    """
    # THE SAME SPELLS THE PLACEMENT DRAWS SHUFFLE
    spell_list, _base_count = get_non_base_spell_list(target_weight_arr_in)
    return [tuple(spell) for spell in spell_list]


# FUNCTION: INDEX OF THE FIRST SESSION NOT AT THE BASE WEIGHT
def get_first_spell_start_int(target_weight_arr_in):
    """
    Args:
        target_weight_arr_in (array-like): Path targets

    Returns:
        int: Start index, or -1 if there is no spell
    """
    # BASE WEIGHT IS THE SESSION-COUNT MODE
    base_weight = get_base_weight_float(target_weight_arr_in)
    for idx, weight in enumerate(np.asarray(target_weight_arr_in, dtype=float)):
        if not get_weight_equal_bool(weight, base_weight):
            return int(idx)
    return -1


# FUNCTION: SPELL PLACEMENT KEEPS TIME AT EACH WEIGHT AND DOES NOT MERGE SPELLS
def check_random_timing_preserves_exposure(path_arr_in, seed_list_in, require_distinct_bool_in=True):
    """
    Every draw has the path's time at each weight, the same spell sequences (order may change), and middle gaps
    of at least 1. The same seed reproduces.

    Args:
        path_arr_in (np.ndarray): Path targets
        seed_list_in (list[int]): Seeds
        require_distinct_bool_in (bool): Require some draw to differ from the path

    Returns:
        list[np.ndarray]: The draws
    """
    # THE PATH'S EXPOSURE AND SPELL MULTISET
    path_time_dict = get_weight_time_dict(path_arr_in)
    path_spell_list = get_spell_tuple_list(path_arr_in)
    base_weight = get_base_weight_float(path_arr_in)
    draw_list = [get_random_timing_weight_arr(path_arr_in, seed_int) for seed_int in seed_list_in]
    for draw_arr in draw_list:
        assert len(draw_arr) == len(path_arr_in)
        assert get_weight_time_dict(draw_arr) == path_time_dict
        assert sorted(get_spell_tuple_list(draw_arr)) == sorted(path_spell_list)
        gap_list = get_base_gap_list(draw_arr, base_weight)
        assert len(gap_list) == len(path_spell_list) + 1
        assert all(int(gap_int) >= 1 for gap_int in gap_list[1:-1])
        assert all(int(gap_int) >= 0 for gap_int in gap_list)
        assert int(sum(gap_list)) == int(path_time_dict[base_weight])
    assert np.allclose(draw_list[0], get_random_timing_weight_arr(path_arr_in, seed_list_in[0]), atol=0.0)
    if require_distinct_bool_in:
        assert any(not np.array_equal(draw_arr, path_arr_in) for draw_arr in draw_list)
        assert len({draw_arr.tobytes() for draw_arr in draw_list}) >= 2
    return draw_list


# FUNCTION: TIME AT EACH WEIGHT IS KEPT FOR 2, 3 AND 4 WEIGHTS
def test_random_timing_preserves_time_two_three_four_weights():
    """
    Two, three and four distinct weights. Every draw keeps time-at-weight, the spell sequences, and middle gaps
    of at least 1. Draws differ from the path and from each other. Fixed seeds reproduce.

    Returns:
        None
    """
    # TWO WEIGHTS, SEVERAL CASH SPELLS
    two_arr = get_run_weight_arr([(1.0, 8), (0.0, 3), (1.0, 5), (0.0, 2), (1.0, 7), (0.0, 4), (1.0, 6)])
    seed_list = get_random_timing_seed_list(12)
    check_random_timing_preserves_exposure(two_arr, seed_list)
    assert get_unique_weight_list(two_arr) == [1.0, 0.0]
    # THREE WEIGHTS: A SPELL MAY HOLD MORE THAN ONE NON-BASE WEIGHT
    three_arr = get_run_weight_arr([(1.0, 15), (0.5, 4), (0.0, 3), (1.0, 10), (0.0, 2), (0.5, 5), (1.0, 12),
                                   (0.5, 3), (0.0, 1), (1.0, 8)])
    check_random_timing_preserves_exposure(three_arr, seed_list)
    assert get_unique_weight_list(three_arr) == [1.0, 0.5, 0.0]
    # FOUR WEIGHTS
    four_arr = get_run_weight_arr([(1.0, 10), (0.75, 4), (0.25, 7), (0.0, 3), (1.0, 6), (0.75, 9), (0.25, 2),
                                  (0.0, 5), (1.0, 8), (0.75, 3), (0.25, 6), (0.0, 4)])
    check_random_timing_preserves_exposure(four_arr, seed_list)
    assert get_unique_weight_list(four_arr) == [1.0, 0.75, 0.25, 0.0]
    passed("random timing keeps time at each weight for 2, 3 and 4 weights")


# FUNCTION: ONE EXIT YIELDS MANY DISTINCT DRAWS WITH THE SPELL START SPREAD
def test_random_timing_one_exit_spreads_over_the_window():
    """
    One cash spell on an otherwise invested path. At least 90 of 100 fixed-seed draws are distinct, and the spell
    start is spread over the window. Shuffling run lengths would have returned the path every time.

    Returns:
        None
    """
    # 1000 SESSIONS, ONE 20-SESSION CASH SPELL (980 PLACES FOR IT)
    path_arr = get_run_weight_arr([(1.0, 200), (0.0, 20), (1.0, 780)])
    seed_list = get_random_timing_seed_list(100)
    draw_list = check_random_timing_preserves_exposure(path_arr, seed_list)
    distinct_count = len({draw_arr.tobytes() for draw_arr in draw_list})
    assert distinct_count >= 90, f"one-exit path produced only {distinct_count} distinct draws"
    start_list = [get_first_spell_start_int(draw_arr) for draw_arr in draw_list]
    assert min(start_list) <= len(path_arr) // 5
    assert max(start_list) >= (4 * len(path_arr)) // 5 - 20
    assert max(start_list) - min(start_list) >= len(path_arr) // 3
    passed("one-exit random timing yields many distinct draws with the spell start spread")


# FUNCTION: A PATH WITH NO SPELLS IS RETURNED UNCHANGED
def test_random_timing_no_spells_returns_itself():
    """
    A constant-weight path has no non-base spells. Every seed returns that path.

    Returns:
        None
    """
    # ALL SESSIONS AT THE BASE WEIGHT
    path_arr = get_run_weight_arr([(1.0, 40)])
    seed_list = get_random_timing_seed_list(100)
    draw_list = check_random_timing_preserves_exposure(path_arr, seed_list, require_distinct_bool_in=False)
    for draw_arr in draw_list:
        assert np.array_equal(draw_arr, path_arr)
    cash_arr = get_run_weight_arr([(0.0, 25)])
    assert np.array_equal(get_random_timing_weight_arr(cash_arr, seed_list[0]), cash_arr)
    passed("a path with no spells returns itself")


# FUNCTION: A 94%-INVESTED PATH WITH 9 SHORT CASH SPELLS
def test_random_timing_preserves_ninety_four_percent_invested():
    """
    150 sessions, 9 cash spells of length 1, 141 invested (94%). Every one of the 100 fixed-seed draws stays at
    94% invested with 9 cash spells. Placing switches independently would not.

    Returns:
        None
    """
    # START INVESTED; NINE ONE-SESSION CASH SPELLS
    run_list = [(1.0, 50), (0.0, 1), (1.0, 20), (0.0, 1), (1.0, 15), (0.0, 1), (1.0, 10), (0.0, 1), (1.0, 8),
                (0.0, 1), (1.0, 7), (0.0, 1), (1.0, 12), (0.0, 1), (1.0, 9), (0.0, 1), (1.0, 6), (0.0, 1), (1.0, 4)]
    path_arr = get_run_weight_arr(run_list)
    assert len(path_arr) == 150
    path_time_dict = get_weight_time_dict(path_arr)
    assert path_time_dict[1.0] == 141 and path_time_dict[0.0] == 9
    assert path_time_dict[1.0] / len(path_arr) == 0.94
    cash_spell_count = sum(1 for weight, _length_int in get_weight_run_list(path_arr) if weight == 0.0)
    assert cash_spell_count == 9
    seed_list = get_random_timing_seed_list(100)
    draw_list = check_random_timing_preserves_exposure(path_arr, seed_list)
    invested_share_list = [get_weight_time_dict(draw_arr)[1.0] / len(draw_arr) for draw_arr in draw_list]
    assert all(share == 0.94 for share in invested_share_list)
    assert min(invested_share_list) == 0.94 and max(invested_share_list) == 0.94
    start_set = {get_first_spell_start_int(draw_arr) for draw_arr in draw_list}
    assert len(start_set) > 1
    passed("random timing keeps 94% invested on a path with 9 short cash spells")


# FUNCTION: A CRASHED RUN LEAVES NO MANIFEST; A FINISHED RUN WRITES IT LAST
def test_crashed_run_leaves_no_manifest():
    """
    Crash after the first period's checkpoint. The run folder has no manifest.json. A finished run has the
    manifest, the two report files, lookahead.json, and look-ahead pass.

    Returns:
        None
    """
    # THE SAME SHORT BARS AS THE CANDIDATE SUITE
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    crash_log_str = get_test_trial_log_path_str("crash_manifest.csv")
    crashed_bool = False
    try:
        run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in="verdict_crash", n_jobs_int_in=1,
                             period_pdf_in=period_pdf, trial_log_path_str_in=crash_log_str, commit_str_in="testcommit",
                             code_hash_str_in="testhash", crash_after_period_id_in=0, check_clean_tree_bool_in=False,
                             check_view_bool_in=False, baseline_seed_count_int_in=2)
    except RuntimeError as error:
        crashed_bool = "runner crash after period 0" in str(error)
    assert crashed_bool, "the crash hook did not fire"
    crash_folder_str = get_run_folder_str("verdict_crash")
    assert not os.path.isfile(os.path.join(crash_folder_str, MANIFEST_FILE_STR))
    assert not os.path.isfile(os.path.join(crash_folder_str, REPORT_JSON_FILE_STR))
    finish_log_str = get_test_trial_log_path_str("finish_manifest.csv")
    result_dict = run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in="verdict_finish", n_jobs_int_in=1,
                                       period_pdf_in=period_pdf, trial_log_path_str_in=finish_log_str,
                                       commit_str_in="testcommit", code_hash_str_in="testhash",
                                       check_clean_tree_bool_in=False, check_view_bool_in=False,
                                       baseline_seed_count_int_in=2)
    run_folder_str = result_dict["run_folder_str"]
    manifest_path_str = os.path.join(run_folder_str, MANIFEST_FILE_STR)
    assert os.path.isfile(manifest_path_str)
    assert os.path.isfile(os.path.join(run_folder_str, REPORT_JSON_FILE_STR))
    assert os.path.isfile(os.path.join(run_folder_str, REPORT_MD_FILE_STR))
    with open(manifest_path_str, "r", encoding="utf-8") as manifest_file:
        manifest_dict = json.load(manifest_file)
    assert manifest_dict["status"] == "finished" and manifest_dict["run_id"] == "verdict_finish"
    assert manifest_dict["commit"] == "testcommit" and manifest_dict["code_hash"] == "testhash"
    assert manifest_dict["verdict"]["label"] == NOT_EMAIL_WORTHY_STR
    assert manifest_dict["verdict"]["look_ahead"] == LOOK_AHEAD_PASS_STR
    assert "look-ahead" not in manifest_dict["verdict"]["failed_list"]
    assert REPORT_JSON_FILE_STR in manifest_dict["output_files"]
    assert LOOKAHEAD_FILE_STR in manifest_dict["output_files"]
    with open(os.path.join(run_folder_str, REPORT_JSON_FILE_STR), "r", encoding="utf-8") as report_file:
        report_dict = json.load(report_file)
    assert report_dict["look_ahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR
    assert "strategy_total_return" in report_dict["return_dict"]
    assert os.path.isfile(os.path.join(run_folder_str, LOOKAHEAD_FILE_STR))
    with open(os.path.join(run_folder_str, REPORT_MD_FILE_STR), "r", encoding="utf-8") as markdown_file:
        markdown_str = markdown_file.read()
    assert "two window edges" in markdown_str
    passed("a crashed run leaves no manifest and a finished run writes report then manifest")


# FUNCTION: A DESIGN IMPORTING A DIRTY SIBLING EXPERIMENT FOLDER IS REFUSED
def test_dirty_sibling_experiment_folder_is_refused():
    """
    Design A imports helper B. Uncommitted changes under B refuse. Changes under an unimported sibling C are
    allowed. The code hash covers B and changes when B's files change, not when C's files change.

    Returns:
        None
    """
    # THREE TEMPORARY PACKAGES UNDER experiments/
    folder_a_str = os.path.join(WORKSPACE_PATH_STR, "experiments", "_runner_guard_a")
    folder_b_str = os.path.join(WORKSPACE_PATH_STR, "experiments", "_runner_guard_b")
    folder_c_str = os.path.join(WORKSPACE_PATH_STR, "experiments", "_runner_guard_c")
    design_path_str = os.path.join(folder_a_str, "design.py")
    helper_b_path_str = os.path.join(folder_b_str, "helper.py")
    helper_c_path_str = os.path.join(folder_c_str, "helper.py")
    try:
        os.makedirs(folder_a_str, exist_ok=True)
        os.makedirs(folder_b_str, exist_ok=True)
        os.makedirs(folder_c_str, exist_ok=True)
        with open(helper_b_path_str, "w", encoding="utf-8") as helper_b_file:
            helper_b_file.write("WEIGHT = 1.0\n")
        with open(helper_c_path_str, "w", encoding="utf-8") as helper_c_file:
            helper_c_file.write("WEIGHT = 0.0\n")
        with open(design_path_str, "w", encoding="utf-8") as design_file:
            design_file.write("from experiments._runner_guard_b.helper import WEIGHT\n")
        guarded_list = get_guarded_code_folder_list(folder_a_str, design_file_path_str_in=design_path_str)
        guarded_name_list = [os.path.basename(folder_str) for folder_str in guarded_list]
        assert "_runner_guard_a" in guarded_name_list and "_runner_guard_b" in guarded_name_list
        assert "_runner_guard_c" not in guarded_name_list
        dirty_raised_bool = False
        try:
            check_clean_tree(folder_a_str, porcelain_str_in=" M experiments/_runner_guard_b/helper.py\n",
                             design_file_path_str_in=design_path_str)
        except RuntimeError as error:
            dirty_raised_bool = CLEAN_TREE_MESSAGE_STR in str(error) and "experiments/_runner_guard_b/helper.py" in str(error)
        assert dirty_raised_bool, "a dirty sibling experiment folder was accepted"
        check_clean_tree(folder_a_str, porcelain_str_in=" M experiments/_runner_guard_c/helper.py\n",
                         design_file_path_str_in=design_path_str)
        check_clean_tree(folder_a_str, porcelain_str_in="?? scripts/foo.py\n", design_file_path_str_in=design_path_str)
        hash_one_str = get_code_hash_str(folder_a_str, design_file_path_str_in=design_path_str)
        with open(helper_b_path_str, "w", encoding="utf-8") as helper_b_file:
            helper_b_file.write("WEIGHT = 0.5\n")
        hash_two_str = get_code_hash_str(folder_a_str, design_file_path_str_in=design_path_str)
        assert hash_one_str != hash_two_str
        with open(helper_c_path_str, "w", encoding="utf-8") as helper_c_file:
            helper_c_file.write("WEIGHT = 0.9\n")
        hash_three_str = get_code_hash_str(folder_a_str, design_file_path_str_in=design_path_str)
        assert hash_three_str == hash_two_str
    finally:
        shutil.rmtree(folder_a_str, ignore_errors=True)
        shutil.rmtree(folder_b_str, ignore_errors=True)
        shutil.rmtree(folder_c_str, ignore_errors=True)
    passed("a design importing a dirty sibling experiment folder is refused")


# FUNCTION: TRAILING-STOP BASELINES READ THE POSITION ACTUALLY HELD (AUDIT B1)
def test_trailing_baselines_use_realized_position():
    """
    A trailing-stop path whose decision targets never show its stop-outs. Constant exposure must use the share of
    sessions actually in position, and the random draws must keep that time in the market (not collapse to
    buy-and-hold).

    Returns:
        None
    """
    # A STOP AND A FIVE-DECISION DELAYED RE-ENTRY: REAL CASH SPELLS THE TARGETS DO NOT SHOW
    from so.runner import run_daily_dict, TrailingStopEngine
    from so.runner.baselines import get_exposure_weight_arr, get_filled_target_weight_arr
    import runner_trailing_design as trail_design
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2011-01-03", "2011-12-30", seed_in=11))
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    class DelayedTrailDesign(trail_design.TrailDesign):
        def decide(self, view_in):
            state_dict = view_in.get_engine_state_dict()
            reenter_bool = (not state_dict["in_position"]) and state_dict["cash_session_count"] >= 5
            return {"target_weight": 1.0 if reenter_bool else float("nan"), "flatten_bool": False,
                    "trail_multiple": 2.0, "volatility": 0.006, "reentry_reason": "delay"}
    path_dict = run_daily_dict(DelayedTrailDesign(), ohlcv_array_dict, date1, date2,
                               engine_in=TrailingStopEngine(None), initial_weight_in=1.0)
    held_arr = path_dict["daily_equity_pdf"]["in_position"].astype(bool).to_numpy()[:-1].astype(float)
    assert 0.05 < held_arr.mean() < 0.95, held_arr.mean()
    # THE OLD BEHAVIOUR: NO mean_weight ON A TRAILING RESULT, SO THE DECISION-TARGET PATH IS REFUSED
    refused_bool = False
    try:
        get_runner_baseline_dict(ohlcv_array_dict, date1, date2, path_dict, seed_count_int_in=4)
    except ValueError:
        refused_bool = True
    assert refused_bool, "a trailing result without mean_weight was accepted as a fractional path"
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, path_dict, seed_count_int_in=8,
                                             realized_exposure_bool_in=True)
    assert baseline_dict["exposure_source_str"] == "realized_position"
    assert np.isclose(baseline_dict["constant_exposure_weight"], held_arr.mean(), atol=1e-12)
    random_list = baseline_dict["random_timing_return_list"]
    assert len(set(np.round(random_list, 10))) > 1, "random draws collapsed to one path"
    assert not np.allclose(random_list, baseline_dict["buy_hold_total_return"]), "random draws equal buy-and-hold"
    exposure_arr = get_exposure_weight_arr(path_dict, True)
    from so.runner.baselines import get_random_timing_weight_arr
    draw_arr = get_random_timing_weight_arr(exposure_arr, 42)
    assert get_weight_time_dict(draw_arr) == get_weight_time_dict(get_filled_target_weight_arr(exposure_arr))
    passed(f"trailing-stop baselines use the realized position ({held_arr.mean():.0%} in position) and keep its time in the market")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE A TEMPORARY FOLDER THIS FILE CREATED
    try:
        test_return_verdict_parts()
        test_consistency_verdict_parts()
        test_baseline_verdict_parts()
        test_email_worthy_needs_every_part()
        test_multiple_testing_parts()
        test_baselines_reproducible_and_constant_one_equals_buy_hold()
        test_random_timing_preserves_time_two_three_four_weights()
        test_random_timing_one_exit_spreads_over_the_window()
        test_random_timing_no_spells_returns_itself()
        test_random_timing_preserves_ninety_four_percent_invested()
        test_crashed_run_leaves_no_manifest()
        test_dirty_sibling_experiment_folder_is_refused()
        test_trailing_baselines_use_realized_position()
        print("\nAll runner verdict tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
            if _CURRENT_DATA_PATH_STR:
                os.environ["SO_DATA_PATH"] = _CURRENT_DATA_PATH_STR
            else:
                os.environ.pop("SO_DATA_PATH", None)
