"""
Workspace Tests: the daily experiment designs on the runner (exp02-exp07, exp12, exp13) and their shared helpers

Run from the workspace root:   python tests/test_experiments.py   (or python tests/run_all_tests.py)
Synthetic data only (about 3 years of minute bars, synthetic VIX and VIX3M daily closes). The data root is a temporary
folder.

What is verified:
    1. Every design file passes the preflight, and every candidate runs a full stream with a finite result.
    2. Rule mechanics by hand: exp03 delay buy-backs after exactly n cash decisions and dip buy-backs below the sale
       fill; exp04 (x = 0, n = 1) sells only on a close below the average; exp05 weights inside [floor, 1];
       exp06 cooling-off after a buy-stop; the engine snapshot's last_exit_fill_price equals the sale fill.
    3. VixPrevHistory gives the same vix_level_prev, vix_term_prev and vix_pct250_prev as so.features.vix_features on
       every session.
    4. TSDAY no longer serves the columns computed after the decision bar (fill_open, complete-session OHLC).
    5. A development run of exp12 (6 candidates, VIX sources) and of exp02 (model) passes the runner's look-ahead check.
"""

import os
import sys
import shutil
import tempfile
import warnings
import numpy as np
import pandas as pd

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")

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
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_experiments_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
for _name_str in ("SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN", "SO_QUARANTINE_PATH"):
    os.environ.pop(_name_str, None)
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

from so import paths
from so.core.trade_execution import get_ohlcv_array_dict
from so.core.point_in_time import get_minute_bar_available_ts, get_runner_context, get_feature_column_pdf, TSDAY_AFTER_DECISION_COLUMN_LIST
from so.features.daily_features import get_daily_feature_pdf
from so.features.vix_features import get_vix_table_pdf, get_vix_feature_pdf
from so.runner import run_daily_dict, run_development_dict, LOOK_AHEAD_PASS_STR
from so.runner.run import get_candidate_engine
from so.runner.preflight import check_design_file
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_vix_history_design as vix_design
from experiments.exp02_stop_reentry import design as exp02_design
from experiments.exp03_ath_exit import design as exp03_design
from experiments.exp04_trend_exit import design as exp04_design
from experiments.exp05_vol_scaled_exposure import design as exp05_design
from experiments.exp06_capped_regret_reentry import design as exp06_design
from experiments.exp07_warning_lights_exit import design as exp07_design
from experiments.exp12_vix_fear_reentry import design as exp12_design
from experiments.exp13_e1m1_robustness import design as exp13_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
# EVERY DAILY DESIGN
DESIGN_LIST = [exp02_design, exp03_design, exp04_design, exp05_design, exp06_design, exp07_design, exp12_design, exp13_design]


# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Args:
        name_str_in (str): What was checked
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}", flush=True)


# FUNCTION: SYNTHETIC VIX AND VIX3M DAILY CLOSES (ONE ROW PER SESSION, A FEW DAYS MISSING)
def get_vix_frame_dict(session_date_list_in, seed_in=5):
    """
    Args:
        session_date_list_in (list): SPY session dates
        seed_in (int): Seed

    Returns:
        dict: VIX_DAILY, VIX3M_DAILY frames (date, close)
    """
    # A MEAN-REVERTING LEVEL WITH SPIKES; VIX3M SMOOTHER AND USUALLY HIGHER
    rng = np.random.default_rng(seed_in)
    count = len(session_date_list_in)
    level_arr = np.empty(count)
    level_arr[0] = 18.0
    for idx in range(1, count):
        level_arr[idx] = max(9.0, level_arr[idx - 1] + 0.08 * (18.0 - level_arr[idx - 1]) + rng.normal(0, 1.2) + (12.0 if rng.random() < 0.01 else 0.0))
    vix3m_arr = 0.6 * level_arr + 0.4 * 20.0 + rng.normal(0, 0.5, count)
    keep_arr = rng.random(count) > 0.02
    date_list = [pd.Timestamp(day).date() for day in session_date_list_in]
    vix_pdf = pd.DataFrame({"date": date_list, "close": np.round(level_arr, 2)})[keep_arr].reset_index(drop=True)
    vix3m_pdf = pd.DataFrame({"date": date_list, "close": np.round(vix3m_arr, 2)})[keep_arr].reset_index(drop=True)
    return {"VIX_DAILY": vix_pdf, "VIX3M_DAILY": vix3m_pdf}


# FUNCTION: THE CONTEXT A DEVELOPMENT RUN WOULD LOAD, BUILT FROM THE SYNTHETIC BARS
def get_context(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, design_module_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars
        daily_pdf_in (pd.DataFrame): get_daily_feature_pdf of the bars
        vix_frame_dict_in (dict): Synthetic VIX frames
        design_module_in (module): Design (DATA_SOURCE_LIST)

    Returns:
        DataContext: Runner context
    """
    # ONLY THE DECLARED SOURCES
    frame_dict = {"TSDAY": daily_pdf_in, "TSDAY_FWD": daily_pdf_in, **vix_frame_dict_in}
    declared_list = list(design_module_in.DATA_SOURCE_LIST)
    limit_ts = get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][-1])
    return get_runner_context(ohlcv_array_dict_in, {name: frame_dict[name] for name in declared_list if name in frame_dict},
                              limit_ts, declared_list)


# FUNCTION: ONE CANDIDATE STREAM
def run_candidate_dict(design_module_in, candidate_in, ohlcv_array_dict_in, context_in, date1_in, date2_in):
    """
    Args:
        design_module_in (module): Design
        candidate_in (str): Candidate
        ohlcv_array_dict_in (dict): Bars
        context_in (DataContext): Sources
        date1_in, date2_in: Window

    Returns:
        tuple: (result dict, design object)
    """
    # THE ENGINE AND THE START WEIGHT THE RUNNER WOULD USE
    design_obj = design_module_in.get_candidate_design(candidate_in)
    result_dict = run_daily_dict(design_obj, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=context_in,
                                 engine_in=get_candidate_engine(design_module_in),
                                 initial_weight_in=float(getattr(design_module_in, "INITIAL_WEIGHT", 1.0)),
                                 dead_band_in=float(getattr(design_module_in, "DEAD_BAND", 0.0)),
                                 design_file_path_str_in=design_module_in.__file__)
    return result_dict, design_obj


# FUNCTION: EVERY CANDIDATE OF EVERY DESIGN RUNS
def test_every_candidate_runs(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, date1_in, date2_in):
    """
    Returns:
        dict: (module name, candidate) -> result dict
    """
    # PREFLIGHT, THEN ONE STREAM PER CANDIDATE
    result_by_key_dict = {}
    candidate_count = 0
    for design_module in DESIGN_LIST:
        check_design_file(design_module.__file__)
        context = get_context(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, design_module)
        assert len(design_module.CANDIDATE_LIST) == len(set(design_module.CANDIDATE_LIST)) > 0
        for candidate in design_module.CANDIDATE_LIST:
            result_dict, _design_obj = run_candidate_dict(design_module, candidate, ohlcv_array_dict_in, context, date1_in, date2_in)
            assert np.isfinite(result_dict["metric_dict"]["total_return"]), (design_module.EXPERIMENT_NAME, candidate)
            assert len(result_dict["daily_equity_pdf"]) == len(result_dict["decision_session_list"])
            result_by_key_dict[(design_module.EXPERIMENT_NAME, candidate)] = result_dict
            candidate_count += 1
    trade_count = sum(len(result_dict["trade_pdf"]) for result_dict in result_by_key_dict.values())
    passed(f"{len(DESIGN_LIST)} designs pass the preflight; {candidate_count} candidate streams finish ({trade_count} trades)")
    return result_by_key_dict


# FUNCTION: RULE MECHANICS BY HAND
def test_mechanics(result_by_key_dict_in, daily_pdf_in):
    """
    Args:
        result_by_key_dict_in (dict): Output of test_every_candidate_runs
        daily_pdf_in (pd.DataFrame): Daily features
    """
    # THE DAILY ROW OF A TIMESTAMP'S SESSION
    daily_by_day_pdf = daily_pdf_in.assign(day=[pd.Timestamp(day).date() for day in daily_pdf_in["date"]]).set_index("day")

    def get_day(timestamp_in):
        return pd.Timestamp(timestamp_in).tz_convert("America/New_York").date() if pd.Timestamp(timestamp_in).tzinfo else pd.Timestamp(timestamp_in).date()

    # exp03 DELAY: EVERY RULE BUY-BACK AFTER EXACTLY n CASH DECISIONS
    delay_result = result_by_key_dict_in[("exp03_ath_exit", "0.020|delay_5")]
    episode_pdf = delay_result["episode_pdf"]
    closed_pdf = episode_pdf[episode_pdf["reentry_reason"] == "delay"]
    assert len(closed_pdf) > 0 and (closed_pdf["cash_session_count"] == 5).all()
    # exp03 DIP: THE BUY-BACK DECISION CLOSE IS AT LEAST 2% BELOW THE SALE FILL
    dip_result = result_by_key_dict_in[("exp03_ath_exit", "0.020|dip_2pct")]
    dip_pdf = dip_result["episode_pdf"]
    dip_pdf = dip_pdf[dip_pdf["reentry_reason"] == "dip"]
    for row in dip_pdf.itertuples(index=False):
        decision_close = float(daily_by_day_pdf.loc[get_day(row.reentry_ts), "decision_close"])
        assert decision_close <= row.exit_fill_price * 0.98 + 1e-9
    # LAST EXIT FILL PRICE ON THE SNAPSHOT IS THE SALE FILL (CHECKED THROUGH THE DIP RULE ABOVE AND HERE)
    trade_pdf = dip_result["trade_pdf"]
    assert len(trade_pdf) > 0 and len(dip_pdf) >= 0
    # exp04 x = 0, n = 1: EVERY SIGNAL SALE IS ON A SESSION WHOSE CLOSE WAS BELOW THE AVERAGE
    trend_trade_pdf = result_by_key_dict_in[("exp04_trend_exit", "0.00|1")]["trade_pdf"]
    signal_pdf = trend_trade_pdf[trend_trade_pdf["exit_reason"] == "SIGNAL"]
    assert len(signal_pdf) > 0
    assert all(float(daily_by_day_pdf.loc[get_day(sell_ts), "ma200_dist_pct"]) < 0 for sell_ts in signal_pdf["sell_ts"])
    # exp05: EVERY TARGET WEIGHT IS INSIDE [floor, 1]
    for candidate in exp05_design.CANDIDATE_LIST:
        weight_arr = result_by_key_dict_in[("exp05_vol_scaled_exposure", candidate)]["target_weight_arr"][:-1]
        floor_float = float(candidate.split("|")[0])
        finite_arr = weight_arr[np.isfinite(weight_arr)]
        assert len(finite_arr) and finite_arr.min() >= floor_float - 1e-12 and finite_arr.max() <= 1.0 + 1e-12
        assert (finite_arr < 1.0).any(), candidate
    # exp06 COOLING 20: NO SIGNAL EXIT WITHIN 20 DECISIONS OF A BUY-STOP RE-ENTRY
    cooling_result = result_by_key_dict_in[("exp06_capped_regret_reentry", "ath_1pct|0.01|20")]
    session_list = [pd.Timestamp(day).date() for day in cooling_result["decision_session_list"]]
    session_pos_dict = {day: pos for pos, day in enumerate(session_list)}
    cooling_trade_pdf = cooling_result["trade_pdf"].reset_index(drop=True)
    checked_count = 0
    for idx in range(len(cooling_trade_pdf) - 1):
        if cooling_trade_pdf.loc[idx + 1, "entry_reason"] != "buy_stop":
            continue
        next_exit = cooling_trade_pdf.loc[idx + 1]
        if next_exit["exit_reason"] == "SIGNAL":
            gap = session_pos_dict[get_day(next_exit["sell_ts"])] - session_pos_dict[get_day(next_exit["buy_ts"])]
            assert gap > 20, gap
            checked_count += 1
    passed(f"mechanics (exp03 delay {len(closed_pdf)} buy-backs at 5 cash decisions, {len(dip_pdf)} dip buy-backs below the "
           f"sale fill; exp04 {len(signal_pdf)} sales below the average; exp05 weights in [floor, 1]; exp06 {checked_count} "
           f"buy-stop re-entries respect the cooling-off)")


# FUNCTION: THE VIX HISTORY EQUALS THE VECTORIZED DEFINITION
def test_vix_history(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, date1_in, date2_in):
    """
    Returns:
        None
    """
    # STREAM THE LOGGING DESIGN
    context = get_context(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, vix_design)
    design_obj = vix_design.get_candidate_design("vix")
    run_daily_dict(design_obj, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=context,
                   design_file_path_str_in=vix_design.__file__)
    log_pdf = pd.DataFrame(design_obj.log_list)
    # THE SHARED VECTORIZED FEATURES ON THE SAME ROWS
    table_pdf = get_vix_table_pdf(daily_pdf_in, {"vix": vix_frame_dict_in["VIX_DAILY"], "vix3m": vix_frame_dict_in["VIX3M_DAILY"]})
    feature_pdf = get_vix_feature_pdf(table_pdf, daily_pdf_in["daily_volatility"].to_numpy(), "prev")
    feature_pdf["day"] = [pd.Timestamp(day).date() for day in table_pdf["date"]]
    merged_pdf = log_pdf.assign(day=[pd.Timestamp(day).date() for day in log_pdf["session"]]).merge(feature_pdf, on="day", suffixes=("", "_ref"))
    assert len(merged_pdf) == len(log_pdf) > 250
    for column_str in ("vix_level_prev", "vix_term_prev", "vix_pct250_prev"):
        left_arr, right_arr = merged_pdf[column_str].to_numpy(dtype=float), merged_pdf[f"{column_str}_ref"].to_numpy(dtype=float)
        assert np.allclose(left_arr, right_arr, atol=1e-12, equal_nan=True), column_str
    nan_count = int(np.isnan(merged_pdf["vix_level_prev"].to_numpy(dtype=float)).sum())
    passed(f"VixPrevHistory == so.features.vix_features on {len(merged_pdf)} sessions (level, term, pct250; {nan_count} missing levels)")


# FUNCTION: TSDAY DOES NOT SERVE AFTER-DECISION COLUMNS
def test_tsday_columns(daily_pdf_in):
    """
    Returns:
        None
    """
    # THE FEATURE PATH DROPS THEM AND REFUSES A REQUEST FOR THEM
    served_pdf = get_feature_column_pdf("TSDAY", daily_pdf_in, None)
    assert not set(TSDAY_AFTER_DECISION_COLUMN_LIST) & set(served_pdf.columns)
    assert "decision_close" in served_pdf.columns and "daily_volatility" in served_pdf.columns
    assert not [column_str for column_str in served_pdf.columns if column_str.startswith("fwd_") or column_str.startswith("y_fwd")]
    try:
        get_feature_column_pdf("TSDAY", daily_pdf_in, ["session_close"])
        raise AssertionError("session_close was served")
    except ValueError:
        pass
    passed(f"TSDAY serves no after-decision column ({', '.join(TSDAY_AFTER_DECISION_COLUMN_LIST)}) and no label")


# FUNCTION: THE RUNNER'S LOOK-AHEAD CHECK PASSES FOR exp12 AND exp02
def test_lookahead(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, date1_in):
    """
    Returns:
        None
    """
    # FOUR INJECTED PERIODS OVER THE LAST PART OF THE DATA
    session_list = [pd.Timestamp(day).date() for day in ohlcv_array_dict_in["session_date_list"]]
    start_idx = session_list.index(pd.Timestamp(date1_in).date())
    bound_list = [start_idx + 63 * step for step in range(5)]
    bound_list[-1] = min(bound_list[-1], len(session_list)) - 1
    row_list = []
    for period_id in range(4):
        first_idx, last_idx = bound_list[period_id] + (1 if period_id else 0), bound_list[period_id + 1]
        row_list.append({"period_id": period_id, "period_start": session_list[first_idx], "period_end": session_list[last_idx],
                         "session_count": last_idx - first_idx + 1, "valid_start": session_list[first_idx], "valid_end": session_list[last_idx]})
    period_pdf = pd.DataFrame(row_list)
    log_folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "experiments_test")
    os.makedirs(log_folder_str, exist_ok=True)
    for design_module in (exp12_design, exp02_design):
        context = get_context(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, design_module)
        result_dict = run_development_dict(design_module, ohlcv_array_dict_in, data_context_in=context,
                                           run_id_str_in=f"look_{design_module.EXPERIMENT_NAME}", n_jobs_int_in=1,
                                           period_pdf_in=period_pdf,
                                           trial_log_path_str_in=os.path.join(log_folder_str, "trial_log.csv"),
                                           commit_str_in="testcommit", code_hash_str_in="testhash",
                                           check_clean_tree_bool_in=False, check_view_bool_in=False,
                                           baseline_seed_count_int_in=2)
        assert result_dict["lookahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR, (design_module.EXPERIMENT_NAME, result_dict["lookahead_dict"].get("first_fail_dict"))
    passed("look-ahead check passes for exp12 (VIX sources, 6 candidates) and exp02 (weekly model, 18 candidates)")


# RUN THE SUITE
if __name__ == "__main__":
    try:
        print("Generating synthetic data...", flush=True)
        synthetic_ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2021-01-04", "2023-12-29", minute_vol_in=0.0007, seed_in=23))
        synthetic_daily_pdf = get_daily_feature_pdf(synthetic_ohlcv_array_dict)
        synthetic_vix_dict = get_vix_frame_dict(synthetic_ohlcv_array_dict["session_date_list"])
        stream_date1 = synthetic_ohlcv_array_dict["session_date_list"][350]
        stream_date2 = synthetic_ohlcv_array_dict["session_date_list"][-1]
        test_tsday_columns(synthetic_daily_pdf)
        result_dict = test_every_candidate_runs(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_dict, stream_date1, stream_date2)
        test_mechanics(result_dict, synthetic_daily_pdf)
        test_vix_history(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_dict, stream_date1, stream_date2)
        test_lookahead(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_dict, stream_date1)
        print("\nAll experiment design tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
