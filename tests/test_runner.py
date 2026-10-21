"""
Workspace Tests: point-in-time runner (so.runner; infrastructure step 4a)

Run from the workspace root:   python tests/test_runner.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import os
import sys
import tempfile
import shutil
import numpy as np
import pandas as pd

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_data_")
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
from so.core.holdout import get_perturbed_ohlcv_dict
from so.core.point_in_time import (get_ny_timestamp, get_minute_bar_available_ts, get_runner_context,
                                   register_source_dict, unregister_source, SOURCE_SPEC_DICT)
from so.core.reentry_simulation import get_buy_and_hold_result_dict
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_session_decision_idx_dict
from so.runner import run_daily_dict
from synthetic_data import get_synthetic_ohlcv_pdf

# A NEW YORK CLOCK USED BY THE SMALL FRAMES
NY = "America/New_York"
# TEST SOURCE NAMES (UNREGISTERED AT THE END)
TEST_FEAT_STR = "RUNNER_TEST_FEAT"
TEST_LABEL_STR = "RUNNER_TEST_LABEL"


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


# FUNCTION: NORMALIZE AN ALREADY-STAMPED FEATURE FRAME
def add_test_feature_available_ts_pdf(pdf_in):
    """
    Copies the frame and localizes available_ts. The test plants the clock.

    Args:
        pdf_in (pd.DataFrame): Rows with available_ts

    Returns:
        pd.DataFrame: Copy with New York available_ts
    """
    # THE TEST OWNS THE CLOCK COLUMN
    stamped_pdf = pdf_in.copy()
    stamped_pdf["available_ts"] = [get_ny_timestamp(ts) for ts in stamped_pdf["available_ts"]]
    return stamped_pdf


# FUNCTION: NORMALIZE AN ALREADY-STAMPED LABEL FRAME
def add_test_label_known_ts_pdf(pdf_in):
    """
    Copies the frame and localizes label_known_ts. available_ts is that same clock.

    Args:
        pdf_in (pd.DataFrame): Rows with label_known_ts

    Returns:
        pd.DataFrame: Copy with both clocks
    """
    # A LABEL IS KNOWABLE WHEN ITS OUTCOME IS
    stamped_pdf = pdf_in.copy()
    stamped_pdf["label_known_ts"] = [get_ny_timestamp(ts) for ts in stamped_pdf["label_known_ts"]]
    stamped_pdf["available_ts"] = stamped_pdf["label_known_ts"]
    return stamped_pdf


# FUNCTION: REGISTER THE TWO TEST SOURCES
def register_test_sources():
    """
    Adds the feature and label sources this suite uses. The built-in registry is unchanged besides these two names.

    Args:
        None

    Returns:
        None
    """
    # FEATURE AND LABEL DOORS FOR THE LOOK-AHEAD CHECK
    register_source_dict(TEST_FEAT_STR, {"loader": "test", "time_zone": NY, "timestamp_convention": "planted available_ts",
                                         "availability_func": add_test_feature_available_ts_pdf, "revision_policy": "not revised",
                                         "revision_reason": "test frame", "role": "feature", "holdout": "test"})
    register_source_dict(TEST_LABEL_STR, {"loader": "test", "time_zone": NY, "timestamp_convention": "planted label_known_ts",
                                          "availability_func": add_test_label_known_ts_pdf, "revision_policy": "not revised",
                                          "revision_reason": "test frame", "role": "label", "holdout": "test"})


# FUNCTION: DROP THE TWO TEST SOURCES
def unregister_test_sources():
    """
    Removes the sources this suite added.

    Args:
        None

    Returns:
        None
    """
    # DROP ONLY WHEN PRESENT (A FAILED TEST MAY HAVE UNREGISTERED ALREADY)
    if TEST_FEAT_STR in SOURCE_SPEC_DICT:
        unregister_source(TEST_FEAT_STR)
    if TEST_LABEL_STR in SOURCE_SPEC_DICT:
        unregister_source(TEST_LABEL_STR)


# FUNCTION: A DESIGN THAT ALWAYS RETURNS WEIGHT 1
class ConstantOneDesign:
    """Weight 1 at every decision."""

    # SPY ONLY
    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: ALWAYS 1
    def decide(self, view_in):
        """
        Returns target weight 1.

        Args:
            view_in (DecisionView): Unused besides existing

        Returns:
            float: 1.0
        """
        # THE PATH THAT MUST MATCH BUY-AND-HOLD
        return 1.0


# FUNCTION: A DESIGN THAT ONLY RECORDS THE LAST VISIBLE CLOSE
class RecordingDesign:
    """Stores the last close of each view. Used to check that a later-bar perturbation does not move earlier decisions."""

    # SPY ONLY
    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: START WITH EMPTY LOGS
    def __init__(self):
        """
        Args:
            None
        """
        # ONE ENTRY PER DECISION
        self.last_close_list = []
        self.session_date_list = []

    # FUNCTION: RECORD THEN RETURN 1
    def decide(self, view_in):
        """
        Stores the last sliced close and the session date.

        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: 1.0
        """
        # THE LAST BAR OF THE SLICE IS THE DECISION BAR
        bar_array_dict = view_in.get_bar_array_dict()
        self.last_close_list.append(float(bar_array_dict["close_arr"][-1]))
        self.session_date_list.append(view_in.session_date)
        return 1.0


# FUNCTION: A DESIGN THAT RECORDS THE LAST VISIBLE CLOSE AND PROBES THE THREE DOORS
class ProbeDesign:
    """Tries to read past the moment; records what the view actually returned."""

    # FUNCTION: STORE THE DECLARED LIST AND THE LOG
    def __init__(self, declared_name_list_in):
        """
        Args:
            declared_name_list_in (list[str]): DATA_SOURCE_LIST
        """
        # THE RUNNER PASSES THIS LIST INTO THE CONTEXT
        self.DATA_SOURCE_LIST = list(declared_name_list_in)
        self.event_list = []
        self.last_close_list = []
        self.session_date_list = []
        self.slice_len_list = []
        self.feat_value_list = []
        self.label_value_list = []

    # FUNCTION: PROBE BARS, A SOURCE AND A LABEL, THEN RETURN 1
    def decide(self, view_in):
        """
        Asks for data after the moment on all three doors, then returns weight 1.

        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: 1.0
        """
        # BARS: THE SLICE STOPS AT THE DECISION BAR
        bar_array_dict = view_in.get_bar_array_dict()
        close_arr = bar_array_dict["close_arr"]
        self.slice_len_list.append(int(len(close_arr)))
        self.last_close_list.append(float(close_arr[-1]))
        self.session_date_list.append(view_in.session_date)
        last_label_ts = bar_array_dict["timestamp_index"][-1]
        assert get_minute_bar_available_ts(last_label_ts) == view_in.decision_ts
        try:
            _ = close_arr[len(close_arr)]
            raise AssertionError("a bar past the decision was in the slice")
        except IndexError:
            self.event_list.append("bars_cut")
        try:
            close_arr[0] = 0.0
            raise AssertionError("the bar slice was writable")
        except ValueError:
            self.event_list.append("bars_readonly")
        # SOURCE: A CLOCK AFTER THE MOMENT RAISES; THE DEFAULT CUT OMITS THE LATE ROW
        try:
            view_in.get(TEST_FEAT_STR, as_of_ts_in=view_in.decision_ts + pd.Timedelta(minutes=1))
            raise AssertionError("a source as_of after the decision was served")
        except ValueError:
            self.event_list.append("source_refused")
        feat_pdf = view_in.get(TEST_FEAT_STR)
        self.feat_value_list.append(list(feat_pdf["value"]) if len(feat_pdf) else [])
        assert (pd.to_datetime(feat_pdf["available_ts"]).map(get_ny_timestamp) <= view_in.decision_ts).all() if len(feat_pdf) else True
        # LABEL: A CUTOFF AFTER THE MOMENT RAISES; THE DEFAULT CUT IS STRICTLY BEFORE
        try:
            view_in.get_labels(TEST_LABEL_STR, known_before_ts_in=view_in.decision_ts + pd.Timedelta(days=1))
            raise AssertionError("a label cutoff after the decision was served")
        except ValueError:
            self.event_list.append("label_refused")
        label_pdf = view_in.get_labels(TEST_LABEL_STR)
        self.label_value_list.append(list(label_pdf["value"]) if len(label_pdf) else [])
        if len(label_pdf):
            assert (pd.to_datetime(label_pdf["label_known_ts"]).map(get_ny_timestamp) < view_in.decision_ts).all()
        return 1.0


# FUNCTION: BUILD SYNTHETIC BARS AND A RUNNER CONTEXT WITH PLANTED SOURCES
def get_runner_fixture_dict():
    """
    A few sessions of synthetic SPY, plus one early feature row, one late feature row, and three label rows.

    Args:
        None

    Returns:
        dict: ohlcv_array_dict, data_context, date1, date2, first_decision_ts, first_decision_idx
    """
    # TWO WEEKS IS ENOUGH FOR A BUY-AND-HOLD MATCH AND A PERTURBATION
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    first_decision_idx = int(idx_dict["decision_idx_arr"][0])
    first_decision_ts = get_minute_bar_available_ts(ohlcv_array_dict["timestamp_index"][first_decision_idx])
    last_session_date = ohlcv_array_dict["session_date_list"][-1]
    # ONE FEATURE ROW KNOWABLE AT THE FIRST DECISION, ONE KNOWABLE AFTER THE LAST SESSION
    feat_pdf = pd.DataFrame({"value": [1.0, 99.0],
                             "available_ts": [first_decision_ts, pd.Timestamp(year=last_session_date.year, month=last_session_date.month,
                                                                             day=last_session_date.day, hour=18, minute=0, tz=NY)]})
    # LABELS: BEFORE THE FIRST DECISION, AT THE FIRST DECISION (EXCLUDED), AND AFTER THE LAST SESSION
    label_pdf = pd.DataFrame({"value": [10.0, 20.0, 30.0],
                              "label_known_ts": [first_decision_ts - pd.Timedelta(minutes=1), first_decision_ts,
                                                 pd.Timestamp(year=last_session_date.year, month=last_session_date.month,
                                                              day=last_session_date.day, hour=18, minute=0, tz=NY)]})
    data_context = get_runner_context(ohlcv_array_dict,
                                      source_frame_dict_in={TEST_FEAT_STR: feat_pdf, TEST_LABEL_STR: label_pdf},
                                      declared_name_list_in=["SPY_1MIN", TEST_FEAT_STR, TEST_LABEL_STR])
    return {"ohlcv_array_dict": ohlcv_array_dict, "data_context": data_context,
            "date1": ohlcv_array_dict["session_date_list"][0], "date2": last_session_date,
            "first_decision_ts": first_decision_ts, "first_decision_idx": first_decision_idx,
            "decision_idx_arr": idx_dict["decision_idx_arr"], "fill_idx_arr": idx_dict["fill_idx_arr"]}


# FUNCTION: TEST THAT A DESIGN CANNOT READ PAST ITS MOMENT
def test_lookahead_cut():
    """
    Bars stop at the decision bar. A later source as_of and a later label cutoff raise. Default reads omit late rows.

    Returns:
        None
    """
    # PLANT THE SOURCES, RUN ONCE, THEN DROP THEM
    register_test_sources()
    try:
        fixture_dict = get_runner_fixture_dict()
        probe = ProbeDesign(["SPY_1MIN", TEST_FEAT_STR, TEST_LABEL_STR])
        run_daily_dict(probe, fixture_dict["ohlcv_array_dict"], fixture_dict["date1"], fixture_dict["date2"],
                       data_context_in=fixture_dict["data_context"])
        session_count = len(fixture_dict["ohlcv_array_dict"]["session_date_list"])
        decision_count = session_count - 1
        assert len(probe.session_date_list) == decision_count
        assert probe.event_list.count("bars_cut") == decision_count
        assert probe.event_list.count("bars_readonly") == decision_count
        assert probe.event_list.count("source_refused") == decision_count
        assert probe.event_list.count("label_refused") == decision_count
        # THE FIRST SLICE ENDS AT THE FIRST DECISION BAR, NOT AT THE FILL
        assert probe.slice_len_list[0] == fixture_dict["first_decision_idx"] + 1
        assert probe.last_close_list[0] == float(fixture_dict["ohlcv_array_dict"]["close_arr"][fixture_dict["first_decision_idx"]])
        fill_idx = int(fixture_dict["fill_idx_arr"][0])
        assert fill_idx == fixture_dict["first_decision_idx"] + 1
        assert probe.slice_len_list[0] == fill_idx
        # THE LATE FEATURE ROW IS NEVER VISIBLE; THE EARLY ONE IS
        assert probe.feat_value_list[0] == [1.0]
        assert 99.0 not in [value for row_list in probe.feat_value_list for value in row_list]
        # THE LABEL AT THE FIRST DECISION IS EXCLUDED THEN, AND VISIBLE ON THE NEXT SESSION (STRICTLY BEFORE)
        assert probe.label_value_list[0] == [10.0]
        assert 20.0 in probe.label_value_list[1]
        assert 30.0 not in [value for row_list in probe.label_value_list for value in row_list]
    finally:
        unregister_test_sources()
    passed("lookahead cut (bars, source, label)")


# FUNCTION: TEST THAT WEIGHT 1 MATCHES BUY-AND-HOLD
def test_weight_one_is_buy_and_hold():
    """
    initial_weight 1 and decide() = 1 reproduce buy-and-hold equity, with no rebalance.

    Returns:
        None
    """
    # THE SAME SYNTHETIC SPAN AS THE OTHER CHECKS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    runner_dict = run_daily_dict(ConstantOneDesign(), ohlcv_array_dict, date1, date2, dead_band_in=0.2, initial_weight_in=1.0)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    assert np.allclose(runner_dict["daily_equity_pdf"]["equity"], buy_hold_dict["daily_equity_pdf"]["equity"], atol=1e-6)
    assert runner_dict["metric_dict"]["rebalance_count"] == 0
    passed("weight 1 throughout reproduces buy-and-hold")


# FUNCTION: TEST THAT TWO IDENTICAL RUNS MATCH
def test_identical_runs():
    """
    Two runs on the same arrays, design and engine give the same trades, marks and targets.

    Returns:
        None
    """
    # TWO FRESH DESIGNS, SAME BARS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    first_dict = run_daily_dict(ConstantOneDesign(), ohlcv_array_dict, date1, date2, dead_band_in=0.2, initial_weight_in=1.0)
    second_dict = run_daily_dict(ConstantOneDesign(), ohlcv_array_dict, date1, date2, dead_band_in=0.2, initial_weight_in=1.0)
    assert np.allclose(first_dict["daily_equity_pdf"]["equity"], second_dict["daily_equity_pdf"]["equity"], atol=0.0)
    assert np.allclose(first_dict["target_weight_arr"], second_dict["target_weight_arr"], equal_nan=True)
    assert list(first_dict["decision_session_list"]) == list(second_dict["decision_session_list"])
    first_trade_pdf, second_trade_pdf = first_dict["trade_pdf"], second_dict["trade_pdf"]
    assert len(first_trade_pdf) == len(second_trade_pdf)
    if len(first_trade_pdf):
        assert first_trade_pdf["delta_share_count"].tolist() == second_trade_pdf["delta_share_count"].tolist()
        assert first_trade_pdf["fill_price"].tolist() == second_trade_pdf["fill_price"].tolist()
        assert first_trade_pdf["reason"].tolist() == second_trade_pdf["reason"].tolist()
    passed("two identical runs give identical results")


# FUNCTION: TEST THAT A LATER-BAR PERTURBATION LEAVES EARLIER DECISIONS UNCHANGED
def test_later_bar_perturbation():
    """
    Overwriting every bar after a session's decision bar does not change that session's last visible close, or any
    earlier one.

    Returns:
        None
    """
    # RECORD THE LAST VISIBLE CLOSE ON THE ORIGINAL BARS AND ON THE PERTURBED BARS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    cut_date = ohlcv_array_dict["session_date_list"][2]
    original_design = RecordingDesign()
    original_dict = run_daily_dict(original_design, ohlcv_array_dict, date1, date2, dead_band_in=0.2, initial_weight_in=1.0)
    perturbed_array_dict = get_perturbed_ohlcv_dict(ohlcv_array_dict, cut_date)
    perturbed_design = RecordingDesign()
    perturbed_dict = run_daily_dict(perturbed_design, perturbed_array_dict, date1, date2, dead_band_in=0.2, initial_weight_in=1.0)
    # DECISIONS ON OR BEFORE THE CUT SESSION SEE THE SAME LAST BAR
    for idx, session_date in enumerate(original_design.session_date_list):
        if session_date <= cut_date:
            assert session_date == perturbed_design.session_date_list[idx]
            assert original_design.last_close_list[idx] == perturbed_design.last_close_list[idx]
            assert original_dict["target_weight_arr"][idx] == perturbed_dict["target_weight_arr"][idx]
    # THE FILL BAR OF THE CUT SESSION DID MOVE, SO A LEAK WOULD HAVE CHANGED THE CUT DECISION'S LAST CLOSE
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    cut_session_idx = int(ohlcv_array_dict["date_session_idx_dict"][cut_date])
    fill_idx = int(idx_dict["fill_idx_arr"][cut_session_idx])
    assert not np.isclose(ohlcv_array_dict["close_arr"][fill_idx], perturbed_array_dict["close_arr"][fill_idx])
    passed("perturbing a later bar leaves earlier decisions unchanged")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY FOLDER
    try:
        test_lookahead_cut()
        test_weight_one_is_buy_and_hold()
        test_identical_runs()
        test_later_bar_perturbation()
        assert TEST_FEAT_STR not in SOURCE_SPEC_DICT
        assert TEST_LABEL_STR not in SOURCE_SPEC_DICT
        print("\nAll runner tests passed ✅")
    finally:
        unregister_test_sources()
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
