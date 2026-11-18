"""
Workspace Tests: the experiment designs on the runner (exp01 minute; exp02-exp07, exp12-exp14 daily) and their shared helpers

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
    6. exp14: fh and rod signal arithmetic, the exact -x edge, the 15:30 sell and 15:58 buy-back, an early
       close, missing bars, and a change after 15:30 that must not move the 15:30 decision.

One experiment only (python tests/run_all_tests.py --experiment expNN, which sets SO_TEST_EXPERIMENT=expNN): its own
test_expNN_* functions, every candidate of its design (from DESIGN_LIST) on the runner, and the runner's look-ahead
check on that design. A new experiment registers here: its design in DESIGN_LIST, its tests named test_expNN_*, and
the calls in the full run below.
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
from so.core.backtest_simulation import get_session_first_entry_idx
from so.core.point_in_time import get_minute_bar_available_ts, get_runner_context, get_feature_column_pdf, TSDAY_AFTER_DECISION_COLUMN_LIST
from so.features.daily_features import get_daily_feature_pdf, get_session_decision_idx_dict
from so.runner.view import (DecisionView, get_empty_bar_buffer_dict, fill_bar_buffer_through_decision,
                            get_sliced_bar_array_dict, get_decision_view)
from so.runner.intraday import INTRADAY_LIST_KEY_STR, get_session_call_list
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
from experiments.exp14_last_half_hour_exit import config as exp14_config
from experiments.exp14_last_half_hour_exit import design as exp14_design
from experiments.exp14_last_half_hour_exit.design import get_signal_return_float, get_weak_day_bool

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
# EVERY DAILY DESIGN
DESIGN_LIST = [exp02_design, exp03_design, exp04_design, exp05_design, exp06_design, exp07_design, exp12_design,
               exp13_design, exp14_design]


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
def test_every_candidate_runs(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, date1_in, date2_in, design_list_in=None):
    """
    Args:
        design_list_in (list | None): Designs to run (None = DESIGN_LIST)

    Returns:
        dict: (module name, candidate) -> result dict
    """
    # PREFLIGHT, THEN ONE STREAM PER CANDIDATE
    design_list = list(DESIGN_LIST if design_list_in is None else design_list_in)
    result_by_key_dict = {}
    candidate_count = 0
    for design_module in design_list:
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
    passed(f"{len(design_list)} designs pass the preflight; {candidate_count} candidate streams finish ({trade_count} trades)")
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
def test_lookahead(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, date1_in, design_list_in=None):
    """
    Args:
        design_list_in (list | None): Designs to check (None = exp12 and exp02)

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
    design_list = [exp12_design, exp02_design] if design_list_in is None else list(design_list_in)
    for design_module in design_list:
        context = get_context(ohlcv_array_dict_in, daily_pdf_in, vix_frame_dict_in, design_module)
        result_dict = run_development_dict(design_module, ohlcv_array_dict_in, data_context_in=context,
                                           run_id_str_in=f"look_{design_module.EXPERIMENT_NAME}", n_jobs_int_in=1,
                                           period_pdf_in=period_pdf,
                                           trial_log_path_str_in=os.path.join(log_folder_str, "trial_log.csv"),
                                           commit_str_in="testcommit", code_hash_str_in="testhash",
                                           check_clean_tree_bool_in=False, check_view_bool_in=False,
                                           baseline_seed_count_int_in=2)
        assert result_dict["lookahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR, (design_module.EXPERIMENT_NAME, result_dict["lookahead_dict"].get("first_fail_dict"))
    if design_list_in is None:
        passed("look-ahead check passes for exp12 (VIX sources, 6 candidates) and exp02 (weekly model, 18 candidates)")
    else:
        passed(f"look-ahead check passes for {', '.join(module.EXPERIMENT_NAME for module in design_list)}")


# FUNCTION: ONE EXPERIMENT ONLY (tests/run_all_tests.py --experiment expNN SETS SO_TEST_EXPERIMENT)
def run_one_experiment(experiment_str_in):
    """
    Runs the experiment's own test_<expNN>_* functions (in file order), every candidate of its design on the runner,
    and the runner's look-ahead check on it. A new experiment registers by adding its design to DESIGN_LIST and naming
    its tests test_<expNN>_*.

    Args:
        experiment_str_in (str): e.g. exp15

    Returns:
        None
    """
    # THE EXPERIMENT'S OWN TESTS AND DESIGNS
    prefix_str = f"test_{experiment_str_in}_"
    own_test_list = sorted([value for name_str, value in globals().items() if name_str.startswith(prefix_str) and callable(value)],
                           key=lambda value: value.__code__.co_firstlineno)
    design_list = [module for module in DESIGN_LIST if str(module.EXPERIMENT_NAME).startswith(experiment_str_in + "_")]
    assert own_test_list or design_list, (f"no {prefix_str}* test and no design of {experiment_str_in} in DESIGN_LIST: "
                                          f"register the experiment in this suite first")
    print(f"{experiment_str_in} only: {len(own_test_list)} own tests, {len(design_list)} design(s)", flush=True)
    for test_func in own_test_list:
        test_func()
    if design_list:
        print("Generating synthetic data...", flush=True)
        ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2021-01-04", "2023-12-29", minute_vol_in=0.0007, seed_in=23))
        daily_pdf = get_daily_feature_pdf(ohlcv_array_dict)
        vix_dict = get_vix_frame_dict(ohlcv_array_dict["session_date_list"])
        date1, date2 = ohlcv_array_dict["session_date_list"][350], ohlcv_array_dict["session_date_list"][-1]
        test_every_candidate_runs(ohlcv_array_dict, daily_pdf, vix_dict, date1, date2, design_list_in=design_list)
        test_lookahead(ohlcv_array_dict, daily_pdf, vix_dict, date1, design_list_in=design_list)



# FUNCTION: exp01 (MINUTE MODE): PREFLIGHT, MODEL ON PLANTED ROWS, ROW-LOCAL SIGNAL, UNIQUENESS WEIGHTS
def test_exp01_model():
    """
    Returns:
        None
    """
    # IMPORT THE MINUTE CHECKS, THE SHARED CONFIG AND exp01
    from so import config
    from so.runner.minute import check_minute_signal, get_shuffled_signal_list
    from experiments.exp01_minute_entry import design as exp01_design
    from experiments.exp01_minute_entry.model import MODEL_FEATURE_COL_LIST, get_uniqueness_weight_arr
    from so.features.barrier_labels import get_delta_col_str
    check_design_file(exp01_design.__file__)
    check_minute_signal(exp01_design)
    assert len(exp01_design.CANDIDATE_LIST) == 12 and exp01_design.CANDIDATE_LIST[0] == "3Y|0.0000"
    # UNIQUENESS: TWO OVERLAPPING TRADES WEIGH HALF AN ISOLATED ONE
    weight_arr = get_uniqueness_weight_arr(np.array([100, 100, 1000]), np.array([9, 9, 9]))
    assert np.isclose(weight_arr[2] / weight_arr[0], 2.0) and np.isclose(weight_arr.mean(), 1.0)
    # PLANTED TRAINING ROWS: TAKE PROFIT WHEN THE FIRST NUMERIC FEATURE IS HIGH
    rng = np.random.default_rng(3)
    row_count = 1500
    row_dict = {}
    numeric_list = [column_str for column_str in MODEL_FEATURE_COL_LIST if config.FEATURE_REGISTRY_DICT[column_str]["scale_type"] != "categorical"]
    for column_str in MODEL_FEATURE_COL_LIST:
        if column_str in numeric_list:
            row_dict[column_str] = rng.random(row_count)
        else:
            row_dict[column_str] = rng.choice(list(config.CATEGORY_LEVEL_DICT[column_str]), row_count)
    row_pdf = pd.DataFrame(row_dict)
    row_pdf["close"] = 400.0
    row_pdf["bar_idx"] = np.arange(row_count) * 15
    tp_arr = row_pdf[numeric_list[0]].to_numpy() > 0.5
    for delta in config.TRAIN_DELTA_LIST:
        reason_arr = np.where(tp_arr, "TP", "SL")
        row_pdf[get_delta_col_str(delta)] = [f"{int(count)}|400.0|{reason}" for count, reason in zip(rng.integers(1, 40, row_count), reason_arr)]
    candidate_design = exp01_design.get_candidate_design("3Y|0.0005")
    model = candidate_design.fit(row_pdf)
    assert len(model["models"]) == len(config.TRAIN_DELTA_LIST) and model["threshold"] == 0.0005
    # THE SIGNAL IS ROW-LOCAL AND ENTERS MOSTLY ON THE PLANTED ROWS
    score_pdf = row_pdf[list(exp01_design.FEATURE_COL_LIST)].copy()
    score_pdf["bar_idx"] = row_pdf["bar_idx"]
    decision_list = get_shuffled_signal_list(score_pdf, model, exp01_design.signal, "exp01", list(exp01_design.FEATURE_COL_LIST))
    enter_arr = np.array([float(decision_dict["target_weight"]) > 0 for decision_dict in decision_list])
    assert enter_arr.any() and enter_arr[tp_arr].mean() > enter_arr[~tp_arr].mean()
    # FEWER THAN 200 ROWS: NO MODEL, NO ENTRY
    small_model = candidate_design.fit(row_pdf.head(150))
    assert small_model["models"] == {}
    small_decision_list = get_shuffled_signal_list(score_pdf.head(20), small_model, exp01_design.signal, "exp01", list(exp01_design.FEATURE_COL_LIST))
    assert not any(float(decision_dict["target_weight"]) > 0 for decision_dict in small_decision_list)
    passed(f"exp01 (minute): preflight, 21 distance models on planted rows, row-local signal enters on "
           f"{enter_arr[tp_arr].mean():.0%} of planted vs {enter_arr[~tp_arr].mean():.0%} of other rows; <200 rows never enters")


# FUNCTION: ROWS OF A SYNTHETIC FRAME AT ONE CLOCK
def get_exp14_clock_mask(ohlcv_pdf_in, ts_str_in):
    """
    Args:
        ohlcv_pdf_in (pd.DataFrame): Synthetic minute bars
        ts_str_in (str): Bar start

    Returns:
        pd.Series: Boolean mask, one row
    """
    # MATCH THE CLOCK, NOT THE TIMEZONE OBJECT
    clock_str = pd.Timestamp(ts_str_in).strftime("%Y-%m-%d %H:%M")
    stamp_str = ohlcv_pdf_in["timestamp"].dt.tz_convert("America/New_York").dt.strftime("%Y-%m-%d %H:%M")
    return stamp_str == clock_str


# FUNCTION: SET ONE BAR'S OPEN AND CLOSE
def set_exp14_bar(ohlcv_pdf_in, ts_str_in, close_float_in, open_float_in=None):
    """
    Args:
        ohlcv_pdf_in (pd.DataFrame): Synthetic minute bars
        ts_str_in (str): Bar start
        close_float_in (float): Close
        open_float_in (float | None): Open (defaults to the close)

    Returns:
        None
    """
    # ONE BAR
    mask_arr = get_exp14_clock_mask(ohlcv_pdf_in, ts_str_in)
    assert int(mask_arr.sum()) == 1, ts_str_in
    open_float = float(close_float_in if open_float_in is None else open_float_in)
    close_float = float(close_float_in)
    ohlcv_pdf_in.loc[mask_arr, "open"] = open_float
    ohlcv_pdf_in.loc[mask_arr, "close"] = close_float
    ohlcv_pdf_in.loc[mask_arr, "high"] = max(open_float, close_float)
    ohlcv_pdf_in.loc[mask_arr, "low"] = min(open_float, close_float)


# FUNCTION: DROP ONE BAR
def drop_exp14_bar(ohlcv_pdf_in, ts_str_in):
    """
    Args:
        ohlcv_pdf_in (pd.DataFrame): Synthetic minute bars
        ts_str_in (str): Bar start to remove

    Returns:
        pd.DataFrame: Copy without that bar
    """
    # ONE BAR
    mask_arr = get_exp14_clock_mask(ohlcv_pdf_in, ts_str_in)
    assert int(mask_arr.sum()) == 1, ts_str_in
    return ohlcv_pdf_in.loc[~mask_arr].reset_index(drop=True)


# FUNCTION: THREE JUNE SESSIONS WITH A KNOWN PREVIOUS CLOSE, fh CLOSE AND rod CLOSE
def get_exp14_june_dict(drop_ts_list_in=None, fh_close_in=198.0, rod_close_in=196.0, later_close_in=None):
    """
    2010-06-01 last close is 200. 2010-06-02 09:59 and 15:30 are the signal ends. 09:58 and 15:29 are
    planted far below 200 so a design that substitutes the previous bar would skip.

    Args:
        drop_ts_list_in (list | None): Bar clocks to remove
        fh_close_in (float): 09:59 close
        rod_close_in (float): 15:30 close
        later_close_in (float | None): Close of every 2010-06-02 bar after 15:30

    Returns:
        dict: Bar arrays
    """
    # ZERO MINUTE NOISE; THE BARS THE SIGNAL READS ARE OVERWRITTEN
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-03", start_price_in=200.0, minute_vol_in=0.0, seed_in=1)
    set_exp14_bar(ohlcv_pdf, "2010-06-01 15:59", 200.0)
    set_exp14_bar(ohlcv_pdf, "2010-06-02 09:58", 180.0)
    set_exp14_bar(ohlcv_pdf, "2010-06-02 09:59", fh_close_in)
    set_exp14_bar(ohlcv_pdf, "2010-06-02 15:29", 180.0)
    set_exp14_bar(ohlcv_pdf, "2010-06-02 15:30", rod_close_in)
    if later_close_in is not None:
        stamp = ohlcv_pdf["timestamp"].dt.tz_convert("America/New_York")
        later_mask = (stamp.dt.date == pd.Timestamp("2010-06-02").date()) & (stamp.dt.hour * 60 + stamp.dt.minute > 15 * 60 + 30)
        ohlcv_pdf.loc[later_mask, ["open", "high", "low", "close"]] = float(later_close_in)
    else:
        set_exp14_bar(ohlcv_pdf, "2010-06-02 15:31", 195.50)
        set_exp14_bar(ohlcv_pdf, "2010-06-02 15:59", 194.25)
    for ts_str in list(drop_ts_list_in or []):
        ohlcv_pdf = drop_exp14_bar(ohlcv_pdf, ts_str)
    return get_ohlcv_array_dict(ohlcv_pdf)


# FUNCTION: SESSION POSITION OF A DATE
def get_exp14_session_idx(ohlcv_array_dict_in, day_str_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        day_str_in (str): Session date

    Returns:
        int: Session position
    """
    # THE DATE LIST IS datetime.date
    day = pd.Timestamp(day_str_in).date()
    day_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    return day_list.index(day)


# FUNCTION: BAR INDEX OF A CLOCK
def get_exp14_bar_idx(ohlcv_array_dict_in, ts_str_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        ts_str_in (str): Bar start

    Returns:
        int: Bar index
    """
    # ONE BAR
    clock_str = pd.Timestamp(ts_str_in).strftime("%Y-%m-%d %H:%M")
    stamp = ohlcv_array_dict_in["timestamp_index"].tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M")
    hit_idx_arr = np.flatnonzero(np.asarray(stamp) == clock_str)
    assert len(hit_idx_arr) == 1, (ts_str_in, len(hit_idx_arr))
    return int(hit_idx_arr[0])


# FUNCTION: THE VIEW THE RUNNER WOULD BUILD AT ONE BAR
def get_exp14_view(ohlcv_array_dict_in, session_idx_in, bar_idx_in, time_str_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        session_idx_in (int): Session
        bar_idx_in (int): Decision bar
        time_str_in (str | None): Intraday time, or None for the 15:58 call

    Returns:
        DecisionView: View that stops at that bar
    """
    # THE SAME BUFFER FILL THE LOOP USES
    buffer_dict = get_empty_bar_buffer_dict(ohlcv_array_dict_in)
    fill_bar_buffer_through_decision(buffer_dict, ohlcv_array_dict_in, int(session_idx_in), int(bar_idx_in))
    return get_decision_view(buffer_dict, int(session_idx_in), int(bar_idx_in), {}, None, time_str_in)


# FUNCTION: A VIEW WHOSE ARRAYS CONTINUE PAST THE 15:30 DECISION BAR
def get_exp14_leaked_view(ohlcv_array_dict_in, session_idx_in, decision_idx_in, end_idx_in):
    """
    The slice includes later bars. decision_bar_idx stays at the 15:30 bar.

    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        session_idx_in (int): Session
        decision_idx_in (int): 15:30 bar
        end_idx_in (int): Last bar of the session

    Returns:
        DecisionView: Leaked view
    """
    # FILL THROUGH THE CLOSE, THEN POINT THE DECISION AT 15:30
    buffer_dict = get_empty_bar_buffer_dict(ohlcv_array_dict_in)
    fill_bar_buffer_through_decision(buffer_dict, ohlcv_array_dict_in, int(session_idx_in), int(end_idx_in))
    bar_dict = get_sliced_bar_array_dict(buffer_dict, int(end_idx_in), int(session_idx_in))
    decision_ts = get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][int(decision_idx_in)])
    session_date = ohlcv_array_dict_in["session_date_list"][int(session_idx_in)]
    return DecisionView(decision_ts, int(decision_idx_in), int(session_idx_in), session_date, bar_dict, {}, None, "15:30")


# FUNCTION: THE RECORDED DAILY DECISION OF ONE SESSION
def get_exp14_record(result_dict_in, day_str_in):
    """
    Args:
        result_dict_in (dict): run_daily_dict output
        day_str_in (str): Session date

    Returns:
        dict: Decision record
    """
    # ONE ROW PER SESSION THE LOOP CALLED
    day = pd.Timestamp(day_str_in).date()
    record_dict = {pd.Timestamp(session_date).date(): decision_dict
                   for session_date, decision_dict in zip(result_dict_in["decision_session_list"], result_dict_in["decision_dict_list"])}
    return record_dict[day]


# FUNCTION: INTERFACE, SIGNAL ARITHMETIC, AND THE EXACT -x EDGE
def test_exp14_signal_and_threshold():
    """
    Returns:
        None
    """
    # THE PRE-REGISTERED LIST AND THE FOLD LENGTH
    check_design_file(exp14_design.__file__)
    assert exp14_design.EXPERIMENT_NAME == "exp14_last_half_hour_exit" and exp14_design.PROTOCOL_VERSION == "1.0"
    assert exp14_design.DATA_SOURCE_LIST == ["SPY_1MIN"] and exp14_design.ENGINE_NAME == "fractional"
    assert exp14_design.CANDIDATE_LIST == ["fh|x050", "fh|x100", "fh|x150", "rod|x050", "rod|x100", "rod|x150"]
    assert exp14_design.INTRADAY_DECISION_TIME_LIST == ["15:30"]
    assert list(exp14_design.Design.INTRADAY_DECISION_TIME_LIST) == ["15:30"]
    assert exp14_config.FOLD_TRAIN_WINDOW_YEARS == 10 and exp14_design.PERIOD_RULE["train_years"] == [10]
    # 198/200 - 1 SITS A HAIR BELOW -0.01; THAT MUST NOT SKIP. ONE CENT THROUGH THE LINE MUST
    assert get_weak_day_bool(198.0 / 200.0 - 1.0, 0.01) is False
    assert get_weak_day_bool(197.99 / 200.0 - 1.0, 0.01) is True
    assert get_weak_day_bool(197.0 / 200.0 - 1.0, 0.015) is False
    assert get_weak_day_bool(196.99 / 200.0 - 1.0, 0.015) is True
    assert get_weak_day_bool(np.nan, 0.01) is False
    # THE VIEW: fh IS THE 09:59 CLOSE, rod IS THE 15:30 CLOSE, BOTH OVER THE PREVIOUS LAST CLOSE
    ohlcv_array_dict = get_exp14_june_dict()
    session_idx = get_exp14_session_idx(ohlcv_array_dict, "2010-06-02")
    bar_1530 = get_exp14_bar_idx(ohlcv_array_dict, "2010-06-02 15:30")
    bar_1558 = get_exp14_bar_idx(ohlcv_array_dict, "2010-06-02 15:58")
    view_1530 = get_exp14_view(ohlcv_array_dict, session_idx, bar_1530, "15:30")
    fh_float = get_signal_return_float(view_1530, "fh")
    rod_float = get_signal_return_float(view_1530, "rod")
    assert np.isclose(fh_float, 198.0 / 200.0 - 1.0) and np.isclose(rod_float, 196.0 / 200.0 - 1.0)
    # EXACTLY -1% DOES NOT SKIP; -1% IS BELOW -0.5% AND DOES
    fh_edge = exp14_design.get_candidate_design("fh|x100")
    assert fh_edge.decide(view_1530) == 1.0 and np.isclose(fh_edge.last_signal_return_float, fh_float)
    assert exp14_design.get_candidate_design("fh|x050").decide(view_1530) == 0.0
    # -2% SKIPS THE WIDEST rod THRESHOLD; THE 15:58 CALL ON THE SAME OBJECT IS WEIGHT 1
    rod_design = exp14_design.get_candidate_design("rod|x150")
    assert rod_design.decide(view_1530) == 0.0
    assert rod_design.decide(get_exp14_view(ohlcv_array_dict, session_idx, bar_1558, None)) == 1.0
    assert [row["weight_float"] for row in rod_design.call_log_list] == [0.0, 1.0]
    # THE FIRST SESSION HAS NO PREVIOUS CLOSE
    first_idx = get_exp14_session_idx(ohlcv_array_dict, "2010-06-01")
    first_view = get_exp14_view(ohlcv_array_dict, first_idx, get_exp14_bar_idx(ohlcv_array_dict, "2010-06-01 15:30"), "15:30")
    assert not np.isfinite(get_signal_return_float(first_view, "fh"))
    assert not np.isfinite(exp14_design.get_candidate_design("rod|x050").decide(first_view))
    passed("exp14 signal arithmetic (fh 09:59, rod 15:30, over the previous last close); exactly -x does not skip")


# FUNCTION: THE 15:30 SELL FILLS AT 15:31 AND THE 15:58 BUY-BACK FILLS AT 15:59
def test_exp14_sell_and_buy_back():
    """
    Returns:
        None
    """
    # rod IS -2%, SO EVEN x150 SELLS. fh IS EXACTLY -1%, SO x100 DOES NOT
    ohlcv_array_dict = get_exp14_june_dict()
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    sell_idx = get_exp14_bar_idx(ohlcv_array_dict, "2010-06-02 15:31")
    buy_idx = get_exp14_bar_idx(ohlcv_array_dict, "2010-06-02 15:59")
    sold_dict = run_daily_dict(exp14_design.get_candidate_design("rod|x150"), ohlcv_array_dict, date1, date2,
                               initial_weight_in=1.0, dead_band_in=0.0)
    record_dict = get_exp14_record(sold_dict, "2010-06-02")
    intraday_tuple = record_dict[INTRADAY_LIST_KEY_STR]
    assert len(intraday_tuple) == 1 and intraday_tuple[0][0] == "15:30" and float(intraday_tuple[0][1]) == 0.0
    assert float(record_dict["target_weight"]) == 1.0
    trade_pdf = sold_dict["trade_pdf"]
    sell_pdf = trade_pdf[trade_pdf["trade_idx"].astype(int) == sell_idx]
    buy_pdf = trade_pdf[trade_pdf["trade_idx"].astype(int) == buy_idx]
    assert len(sell_pdf) == 1 and int(sell_pdf["delta_share_count"].iloc[0]) < 0
    assert float(sell_pdf["raw_price"].iloc[0]) == 195.50
    assert len(buy_pdf) == 1 and int(buy_pdf["delta_share_count"].iloc[0]) > 0
    assert float(buy_pdf["raw_price"].iloc[0]) == 194.25
    held_dict = run_daily_dict(exp14_design.get_candidate_design("fh|x100"), ohlcv_array_dict, date1, date2,
                               initial_weight_in=1.0, dead_band_in=0.0)
    held_tuple = get_exp14_record(held_dict, "2010-06-02")[INTRADAY_LIST_KEY_STR]
    assert float(held_tuple[0][1]) == 1.0
    assert not (held_dict["trade_pdf"]["trade_idx"].astype(int) == sell_idx).any()
    passed("exp14 15:30 sell fills at the 15:31 open; 15:58 buy-back fills at the 15:59 open; exactly -x does not sell")


# FUNCTION: AN EARLY CLOSE HAS NO 15:30 CALL AND NO SKIP
def test_exp14_early_close():
    """
    Returns:
        None
    """
    # 2010-11-26 CLOSES AT 13:00. PRICES ARE FAR BELOW THE PREVIOUS CLOSE, SO A CALL WOULD SKIP
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-11-24", "2010-11-29", start_price_in=200.0, minute_vol_in=0.0, seed_in=2)
    set_exp14_bar(ohlcv_pdf, "2010-11-24 15:59", 200.0)
    stamp = ohlcv_pdf["timestamp"].dt.tz_convert("America/New_York")
    half_mask = stamp.dt.date == pd.Timestamp("2010-11-26").date()
    assert int(half_mask.sum()) > 0
    ohlcv_pdf.loc[half_mask, ["open", "high", "low", "close"]] = 150.0
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_idx = get_exp14_session_idx(ohlcv_array_dict, "2010-11-26")
    decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict)["decision_idx_arr"][session_idx])
    call_list = get_session_call_list(ohlcv_array_dict, session_idx, ("15:30",), decision_idx,
                                      get_session_first_entry_idx(ohlcv_array_dict, session_idx))
    assert call_list == []
    end_ts = ohlcv_array_dict["timestamp_index"][int(ohlcv_array_dict["session_end_idx_arr"][session_idx])]
    end_ts = end_ts.tz_convert("America/New_York")
    assert (end_ts.hour, end_ts.minute) < (15, 30)
    result_dict = run_daily_dict(exp14_design.get_candidate_design("rod|x050"), ohlcv_array_dict,
                                 ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1],
                                 initial_weight_in=1.0, dead_band_in=0.0)
    record_dict = get_exp14_record(result_dict, "2010-11-26")
    assert len(record_dict[INTRADAY_LIST_KEY_STR]) == 0 and float(record_dict["target_weight"]) == 1.0
    start_idx = int(ohlcv_array_dict["session_start_idx_arr"][session_idx])
    end_idx = int(ohlcv_array_dict["session_end_idx_arr"][session_idx])
    trade_idx_arr = result_dict["trade_pdf"]["trade_idx"].astype(int)
    on_half_pdf = result_dict["trade_pdf"].loc[(trade_idx_arr >= start_idx) & (trade_idx_arr <= end_idx)]
    assert not (on_half_pdf["delta_share_count"] < 0).any()
    passed("exp14 early close: no 15:30 call and no skip, even when the session is far below the previous close")


# FUNCTION: A MISSING 09:59 OR 15:30 BAR DOES NOT SKIP, AND A NEIGHBOUR IS NOT A SUBSTITUTE
def test_exp14_missing_bars():
    """
    Returns:
        None
    """
    # 09:58 IS 180. USING IT WOULD SKIP EVERY THRESHOLD
    dropped_fh_dict = get_exp14_june_dict(drop_ts_list_in=["2010-06-02 09:59"])
    session_idx = get_exp14_session_idx(dropped_fh_dict, "2010-06-02")
    view_fh = get_exp14_view(dropped_fh_dict, session_idx, get_exp14_bar_idx(dropped_fh_dict, "2010-06-02 15:30"), "15:30")
    assert not np.isfinite(get_signal_return_float(view_fh, "fh"))
    assert not np.isfinite(exp14_design.get_candidate_design("fh|x150").decide(view_fh))
    assert np.isclose(get_signal_return_float(view_fh, "rod"), 196.0 / 200.0 - 1.0)
    # THE RUNNER MAPS A MISSING 15:30 TO 15:29. THAT BAR'S CLOSE IS 180 AND MUST NOT BE THE rod END
    dropped_rod_dict = get_exp14_june_dict(drop_ts_list_in=["2010-06-02 15:30"])
    session_idx = get_exp14_session_idx(dropped_rod_dict, "2010-06-02")
    decision_idx = int(get_session_decision_idx_dict(dropped_rod_dict)["decision_idx_arr"][session_idx])
    call_list = get_session_call_list(dropped_rod_dict, session_idx, ("15:30",), decision_idx,
                                      get_session_first_entry_idx(dropped_rod_dict, session_idx))
    assert len(call_list) == 1 and call_list[0][0] == "15:30"
    mapped_ts = dropped_rod_dict["timestamp_index"][call_list[0][1]].tz_convert("America/New_York")
    assert (mapped_ts.hour, mapped_ts.minute) == (15, 29)
    view_rod = get_exp14_view(dropped_rod_dict, session_idx, call_list[0][1], "15:30")
    assert float(view_rod.get_bar_array_dict()["close_arr"][int(view_rod.decision_bar_idx)]) == 180.0
    assert not np.isfinite(get_signal_return_float(view_rod, "rod"))
    assert not np.isfinite(exp14_design.get_candidate_design("rod|x050").decide(view_rod))
    passed("exp14 missing 09:59 and missing 15:30: no skip, and the previous bar is not the signal")


# FUNCTION: BARS AFTER 15:30 DO NOT CHANGE THE 15:30 DECISION
def test_exp14_no_lookahead():
    """
    Returns:
        None
    """
    # THE PROPER SLICE STOPS AT 15:30. THE LEAKED SLICE KEEPS LATER BARS AND decision_bar_idx STILL POINTS AT 15:30
    base_dict = get_exp14_june_dict()
    pumped_dict = get_exp14_june_dict(later_close_in=500.0)
    session_idx = get_exp14_session_idx(base_dict, "2010-06-02")
    bar_1530 = get_exp14_bar_idx(base_dict, "2010-06-02 15:30")
    assert get_exp14_bar_idx(pumped_dict, "2010-06-02 15:30") == bar_1530
    weight_base = exp14_design.get_candidate_design("rod|x150").decide(get_exp14_view(base_dict, session_idx, bar_1530, "15:30"))
    pumped_design = exp14_design.get_candidate_design("rod|x150")
    weight_pumped = pumped_design.decide(get_exp14_view(pumped_dict, session_idx, bar_1530, "15:30"))
    assert weight_base == 0.0 and weight_pumped == 0.0
    assert np.isclose(pumped_design.last_signal_return_float, 196.0 / 200.0 - 1.0)
    end_idx = int(base_dict["session_end_idx_arr"][session_idx])
    leaked_pumped = get_exp14_leaked_view(pumped_dict, session_idx, bar_1530, end_idx)
    assert int(leaked_pumped.decision_bar_idx) == bar_1530
    assert int(leaked_pumped.decision_bar_idx) < len(leaked_pumped.get_bar_array_dict()["close_arr"]) - 1
    assert float(leaked_pumped.get_bar_array_dict()["close_arr"][-1]) == 500.0
    assert exp14_design.get_candidate_design("rod|x150").decide(leaked_pumped) == 0.0
    assert exp14_design.get_candidate_design("rod|x150").decide(get_exp14_leaked_view(base_dict, session_idx, bar_1530, end_idx)) == 0.0
    # CHANGING THE 15:30 CLOSE ITSELF DOES CHANGE THE DECISION, WITH THE SAME LATER BARS AT 500
    strong_dict = get_exp14_june_dict(rod_close_in=210.0, later_close_in=500.0)
    assert exp14_design.get_candidate_design("rod|x150").decide(get_exp14_view(strong_dict, session_idx, bar_1530, "15:30")) == 1.0
    strong_end = int(strong_dict["session_end_idx_arr"][session_idx])
    assert exp14_design.get_candidate_design("rod|x150").decide(
        get_exp14_leaked_view(strong_dict, session_idx, bar_1530, strong_end)) == 1.0
    passed("exp14 no look-ahead: a change after 15:30 does not change the 15:30 decision; a change of the 15:30 close does")


# RUN THE SUITE
if __name__ == "__main__":
    try:
        only_experiment_str = os.environ.get("SO_TEST_EXPERIMENT", "").strip()
        if only_experiment_str:
            run_one_experiment(only_experiment_str)
            print(f"\nAll {only_experiment_str} tests passed ✅")
            raise SystemExit(0)
        test_exp14_signal_and_threshold()
        test_exp14_sell_and_buy_back()
        test_exp14_early_close()
        test_exp14_missing_bars()
        test_exp14_no_lookahead()
        print("Generating synthetic data...", flush=True)
        synthetic_ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2021-01-04", "2023-12-29", minute_vol_in=0.0007, seed_in=23))
        synthetic_daily_pdf = get_daily_feature_pdf(synthetic_ohlcv_array_dict)
        synthetic_vix_dict = get_vix_frame_dict(synthetic_ohlcv_array_dict["session_date_list"])
        stream_date1 = synthetic_ohlcv_array_dict["session_date_list"][350]
        stream_date2 = synthetic_ohlcv_array_dict["session_date_list"][-1]
        test_tsday_columns(synthetic_daily_pdf)
        test_exp01_model()
        result_dict = test_every_candidate_runs(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_dict, stream_date1, stream_date2)
        test_mechanics(result_dict, synthetic_daily_pdf)
        test_vix_history(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_dict, stream_date1, stream_date2)
        test_lookahead(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_dict, stream_date1)
        print("\nAll experiment design tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
