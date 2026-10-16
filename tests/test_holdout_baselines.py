import importlib
import json
import os
import sys
import numpy as np
import pandas as pd

"""
Workspace Tests: holdout report baselines

The fast checks cover the family statistics and the span cut. They do not read market data and they do not write the
trial log. The development replay (`python tests/test_holdout_baselines.py development`) reloads each v2 prior-only
path from the saved period and selection tables and requires the saved baseline columns within NUMERIC_TOLERANCE.
It does not rescore the grid and it does not append a trial. exp01 and exp02 retrain, so that replay is not part of
the default suite.
"""

# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)

# IMPORT THE SHARED TOLERANCE AND THE BASELINE HELPERS
from so import config
from so.core.baseline_report import get_baseline_json_str, get_comparison_baseline_dict, get_random_family_stat_dict, get_span_path_dict
from so.paths import LOCAL_TRIAL_LOG_FILE_PATH_STR, get_experiment_data_path_str

# THE NINE V2 DESIGNS. exp01 SKIPS REFITS OUTSIDE THE SAVED SCORE SPAN
DESIGN_TUPLE_LIST = (
    ("exp13", "experiments.exp13_e1m1_robustness", False),
    ("exp12", "experiments.exp12_vix_fear_reentry", False),
    ("exp03", "experiments.exp03_ath_exit", False),
    ("exp04", "experiments.exp04_trend_exit", False),
    ("exp05", "experiments.exp05_vol_scaled_exposure", False),
    ("exp06", "experiments.exp06_capped_regret_reentry", False),
    ("exp07", "experiments.exp07_warning_lights_exit", False),
    ("exp02", "experiments.exp02_stop_reentry", False),
    ("exp01", "experiments.exp01_minute_entry", True),
)

# FUNCTION: PRINT A PASSED TEST
def passed(message_str_in):
    """
    Prints a passed test and flushes, so a redirected log shows the line as it happens.

    Args:
        message_str_in (str): Message

    Returns:
        None
    """
    # PRINT THE MESSAGE
    print(f"✅ {message_str_in}", flush=True)

# FUNCTION: TEST THE FAMILY STATISTICS AND THE SPAN CUT
def test_family_and_span():
    """
    The median is np.median. Percentiles, counts and lists are not returns the success criteria compare.
    A path already inside the span is returned unchanged.

    Returns:
        None
    """
    # THE SAVED MEDIAN, THE PERCENTILES, AND THE STRICT COUNT
    return_list = [0.1, 0.2, 0.3, 0.4]
    stat_dict = get_random_family_stat_dict("random_exit", return_list, 0.25)
    assert stat_dict["random_exit_median"] == float(np.median(return_list))
    assert stat_dict["random_exit_p05"] == float(np.percentile(return_list, 5))
    assert stat_dict["random_exit_p95"] == float(np.percentile(return_list, 95))
    assert stat_dict["random_exit_count"] == 4 and stat_dict["random_exit_beaten_count"] == 2
    # ONLY THE NAMED RETURN IS COMPARED, AND A LIST DOES NOT ENTER THE LEDGER JSON
    comparison_dict = get_comparison_baseline_dict({**stat_dict, "random_exit_list": return_list}, ["random_exit_median"])
    assert list(comparison_dict) == ["random_exit_median"]
    stored_dict = json.loads(get_baseline_json_str({**stat_dict, "random_exit_list": return_list, "missing": np.nan}))
    assert "random_exit_list" not in stored_dict and stored_dict["missing"] is None and stored_dict["random_exit_count"] == 4
    # A PATH WHOSE EQUITY IS ALREADY THE SPAN IS THE SAME OBJECT
    equity_pdf = pd.DataFrame({"date": ["2015-01-02", "2015-01-05"], "equity": [100.0, 101.0], "in_position": [True, True]})
    path_dict = {"daily_equity_pdf": equity_pdf, "metric_dict": {"total_return": 0.01}}
    assert get_span_path_dict(path_dict, None, "2015-01-02", "2015-01-05") is path_dict
    passed("family statistics and an exact span")

# FUNCTION: THE EMBARGO THE DEVELOPMENT REPORT USED
def get_embargo_int(name_str_in, design_module_in, config_module_in):
    """
    exp13 uses the period rule. The others use EMBARGO_TRADING_DAYS.

    Args:
        name_str_in (str): Short name
        design_module_in (module): Design
        config_module_in (module): Experiment config

    Returns:
        int: Embargo sessions
    """
    # exp13 HAS NO EMBARGO CONSTANT OF ITS OWN
    if name_str_in == "exp13":
        return int(design_module_in.PERIOD_RULE["embargo_sessions"])
    return int(config_module_in.EMBARGO_TRADING_DAYS)

# FUNCTION: REPLAY ONE SAVED DEVELOPMENT PATH AND COMPARE ITS BASELINES
def check_saved_baselines(name_str_in, module_str_in, score_span_bool_in, span_cache_dict_in):
    """
    Loads the saved period and selection tables, replays that prior-only path once, and requires every saved
    baseline_* column within NUMERIC_TOLERANCE. Periods are not passed, so an unmodified path is not replayed twice.

    Args:
        name_str_in (str): Short name, used to select one design
        module_str_in (str): Design package
        score_span_bool_in (bool): Call set_score_span before the path
        span_cache_dict_in (dict): Embargo -> development bars

    Returns:
        None
    """
    # LOAD THE DESIGN, THE SAVED TABLES, AND THE DEVELOPMENT BARS
    from so.core.development_span import get_development_ohlcv_dict
    design_module = importlib.import_module(module_str_in + ".design")
    config_module = importlib.import_module(module_str_in + ".config")
    folder_str = get_experiment_data_path_str(config_module.EXPERIMENT_NAME, "step01_development_data")
    period_pdf = pd.read_csv(folder_str + "period_data.csv")
    # CSV DATES ARE STRINGS. THE SAVED RUN PASSED datetime.date, WHICH SOME COMPARISONS REQUIRE
    for column_str in ("period_start", "period_end"):
        period_pdf[column_str] = period_pdf[column_str].map(lambda value: pd.Timestamp(value).date())
    selection_pdf = pd.read_csv(folder_str + "selection_data.csv")
    summary_pdf = pd.read_csv(folder_str + "summary_data.csv")
    assert len(summary_pdf) == 1
    embargo_int = get_embargo_int(name_str_in, design_module, config_module)
    if embargo_int not in span_cache_dict_in:
        span_cache_dict_in[embargo_int] = get_development_ohlcv_dict(embargo_int)
    ohlcv_array_dict = span_cache_dict_in[embargo_int]["ohlcv_array_dict"]
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    # THE FINISHED exp01 RUN DID NOT FIT WEEKS OUTSIDE THIS SPAN
    if score_span_bool_in:
        design_module.set_score_span(date1, date2)
    data_context = design_module.get_development_data_context(span_cache_dict_in[embargo_int]["anchor_session_list"])
    print(f"replaying {config_module.EXPERIMENT_NAME}", flush=True)
    path_dict = design_module.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context)
    baseline_dict = design_module.get_baseline_return_dict(ohlcv_array_dict, date1, date2, data_context, path_dict)
    # EVERY SAVED BASELINE COLUMN, AND NO TRIAL ROW
    compared_count = 0
    for column_str in summary_pdf.columns:
        if not str(column_str).startswith("baseline_"):
            continue
        saved_value = summary_pdf[column_str].iloc[0]
        if pd.isna(saved_value):
            continue
        key_str = str(column_str)[len("baseline_"):]
        assert key_str in baseline_dict, f"{name_str_in} missing {key_str}"
        difference = abs(float(baseline_dict[key_str]) - float(saved_value))
        assert difference <= config.NUMERIC_TOLERANCE, f"{name_str_in} {key_str} {baseline_dict[key_str]} vs {saved_value}"
        compared_count += 1
    assert compared_count > 0
    passed(f"{config_module.EXPERIMENT_NAME} baselines match the saved development file ({compared_count} columns)")

# FUNCTION: REPLAY THE REQUESTED DESIGNS
def test_development_baselines(name_list_in):
    """
    Replays each requested design. The real trial log must be the same size afterwards.

    Args:
        name_list_in (list): Short names, or empty for all nine

    Returns:
        None
    """
    # THE TRIAL LOG IS ONLY READ FOR ITS SIZE
    trial_size = os.path.getsize(LOCAL_TRIAL_LOG_FILE_PATH_STR) if os.path.isfile(LOCAL_TRIAL_LOG_FILE_PATH_STR) else None
    span_cache_dict = {}
    for name_str, module_str, score_span_bool in DESIGN_TUPLE_LIST:
        if name_list_in and name_str not in name_list_in:
            continue
        check_saved_baselines(name_str, module_str, score_span_bool, span_cache_dict)
    if trial_size is not None:
        assert os.path.getsize(LOCAL_TRIAL_LOG_FILE_PATH_STR) == trial_size
    passed("development baselines added no trial row")

# RUN THE SUITE
if __name__ == "__main__":
    # A REDIRECTED WINDOWS LOG IS NOT CP1252
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # THE DEFAULT SUITE IS THE FAST CHECK. "development" REPLAYS THE SAVED PATHS
    test_family_and_span()
    if len(sys.argv) > 1 and sys.argv[1] == "development":
        test_development_baselines(sys.argv[2:])
    print("\nAll holdout-baseline tests passed ✅", flush=True)
