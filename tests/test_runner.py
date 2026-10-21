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
from so.core.fractional_exposure import simulate_fractional_exposure_dict
from so.core.reentry_simulation import get_buy_and_hold_result_dict
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_session_decision_idx_dict
from so.runner import run_daily_dict, check_design_file
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


# FUNCTION: WHETHER A BUFFER TAIL AFTER THE FILLED PREFIX IS EMPTY
def get_nan_tail_bool(array_in, filled_count_in):
    """
    True when every value at or after filled_count_in is NaN, NaT, or None.

    Args:
        array_in (np.ndarray): Buffer or slice
        filled_count_in (int): Length of the visible prefix

    Returns:
        bool: True if the tail is empty
    """
    # A SLICE HAS NO TAIL; ITS .base MIGHT
    if filled_count_in >= len(array_in):
        return True
    tail_arr = array_in[int(filled_count_in):]
    if np.issubdtype(array_in.dtype, np.datetime64):
        return bool(np.isnat(tail_arr).all())
    if np.issubdtype(array_in.dtype, np.floating):
        return bool(np.isnan(tail_arr).all())
    if array_in.dtype == object:
        return all(value is None for value in tail_arr)
    if np.issubdtype(array_in.dtype, np.integer):
        return bool((tail_arr == np.iinfo(array_in.dtype).min).all())
    return False


# FUNCTION: NUMPY ARRAYS REACHABLE FROM THE VIEW, INCLUDING .base
def get_reachable_array_list(root_in):
    """
    Walks dicts, lists, runner objects and frames. Does not walk pandas internals.

    Args:
        root_in (object): Usually a DecisionView

    Returns:
        list[np.ndarray]: Arrays
    """
    # IDENTITY SET SO A BUFFER IS YIELDED ONCE
    seen_set, array_list, stack_list = set(), [], [root_in]
    while stack_list:
        obj = stack_list.pop()
        obj_id = id(obj)
        if obj_id in seen_set:
            continue
        seen_set.add(obj_id)
        if isinstance(obj, np.ndarray):
            array_list.append(obj)
            if obj.base is not None:
                stack_list.append(obj.base)
            continue
        if isinstance(obj, pd.DatetimeIndex):
            array_list.append(obj.asi8)
            continue
        if isinstance(obj, pd.DataFrame):
            for column_str in obj.columns:
                stack_list.append(obj[column_str].to_numpy())
            continue
        if isinstance(obj, pd.Series):
            stack_list.append(obj.to_numpy())
            continue
        if isinstance(obj, dict):
            stack_list.extend(obj.values())
            continue
        if isinstance(obj, (list, tuple)):
            stack_list.extend(obj)
            continue
        if hasattr(obj, "__dict__") and type(obj).__module__.startswith("so.runner"):
            stack_list.extend(vars(obj).values())
    return array_list


# FUNCTION: NUMERIC VALUES IN DATAFRAMES REACHABLE FROM THE VIEW
def get_reachable_frame_value_list(root_in):
    """
    Values in DataFrame columns reachable from the view.

    Args:
        root_in (object): Usually a DecisionView

    Returns:
        list: Cell values
    """
    # SAME WALK AS THE ARRAYS, COLLECTING FRAME CELLS
    seen_set, value_list, stack_list = set(), [], [root_in]
    while stack_list:
        obj = stack_list.pop()
        obj_id = id(obj)
        if obj_id in seen_set:
            continue
        seen_set.add(obj_id)
        if isinstance(obj, pd.DataFrame):
            for column_str in obj.columns:
                value_list.extend(list(obj[column_str]))
            continue
        if isinstance(obj, dict):
            stack_list.extend(obj.values())
            continue
        if isinstance(obj, (list, tuple)):
            stack_list.extend(obj)
            continue
        if hasattr(obj, "__dict__") and type(obj).__module__.startswith("so.runner"):
            stack_list.extend(vars(obj).values())
    return value_list


# FUNCTION: A DESIGN THAT RETURNS A PRECOMPUTED WEIGHT PER SESSION
class ScriptedWeightDesign:
    """Returns target_weight_arr[session] from a date lookup. Used for engine parity."""

    # SPY ONLY
    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: STORE THE WEIGHTS
    def __init__(self, weight_arr_in, session_date_list_in):
        """
        Args:
            weight_arr_in (np.ndarray): One weight per session (NaN = keep)
            session_date_list_in (list): Session dates aligned with the array
        """
        # THE CURRENT SESSION DATE IS KNOWABLE AT THE DECISION
        self.weight_dict = {session_date: float(weight) for session_date, weight in zip(session_date_list_in, weight_arr_in)}

    # FUNCTION: THE WEIGHT FOR THIS SESSION
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: Target weight
        """
        # LOOK UP BY THE SESSION BEING DECIDED
        return self.weight_dict[view_in.session_date]


# FUNCTION: WHETHER EVERY ARRAY BEHIND THE VIEW IS EMPTY AFTER THE MOMENT
def get_view_tail_ok_bool(view_in):
    """
    True when every 1-d array reachable from the view, including each slice's .base, is NaN / NaT / None after the
    visible prefix (bars through the decision bar, sessions through this session).

    Args:
        view_in (DecisionView): View at this moment

    Returns:
        bool: True if no later bar or session value is stored
    """
    # THE VISIBLE PREFIX LENGTHS ARE THE SLICE LENGTHS
    bar_array_dict = view_in.get_bar_array_dict()
    close_arr = bar_array_dict["close_arr"]
    filled_bar_count = len(close_arr)
    filled_session_count = int(view_in.session_idx) + 1
    bar_buffer_len = len(close_arr.base) if close_arr.base is not None else filled_bar_count
    session_end_arr = bar_array_dict["session_end_idx_arr"]
    session_buffer_len = len(session_end_arr.base) if session_end_arr.base is not None else len(session_end_arr)
    ok_bool = True
    for array in get_reachable_array_list(view_in):
        if array.ndim != 1:
            continue
        if len(array) == bar_buffer_len and not get_nan_tail_bool(array, filled_bar_count):
            ok_bool = False
        if len(array) == session_buffer_len and not get_nan_tail_bool(array, filled_session_count):
            ok_bool = False
        if array.base is not None and getattr(array.base, "ndim", 1) == 1 and len(array.base) > len(array):
            if not get_nan_tail_bool(array.base, len(array)):
                ok_bool = False
    return ok_bool


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
        self.new_feat_value_list = []
        self.new_label_value_list = []
        self.first_tail_ok_bool = None
        self.first_late_reachable_bool = None
        self.first_has_data_context_bool = None
        self.first_close_base_len = None
        self.first_forbidden_type_list = []

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
        # ROWS NEW SINCE THE PREVIOUS CALL
        new_feat_pdf = view_in.get_new(TEST_FEAT_STR)
        new_label_pdf = view_in.get_new(TEST_LABEL_STR)
        self.new_feat_value_list.append(list(new_feat_pdf["value"]) if len(new_feat_pdf) else [])
        self.new_label_value_list.append(list(new_label_pdf["value"]) if len(new_label_pdf) else [])
        # AT THE FIRST DECISION, NOTHING AFTER THE MOMENT MAY BE REACHABLE
        if self.first_tail_ok_bool is None:
            self.first_close_base_len = 0 if close_arr.base is None else len(close_arr.base)
            self.first_tail_ok_bool = get_view_tail_ok_bool(view_in)
            late_value_set = {999999.0, 20.0, 30.0}
            reachable_value_list = get_reachable_frame_value_list(view_in)
            late_in_frame_bool = any(
                isinstance(value, (int, float, np.integer, np.floating)) and float(value) in late_value_set
                for value in reachable_value_list)
            late_in_array_bool = False
            for array in get_reachable_array_list(view_in):
                if array.ndim != 1:
                    continue
                if np.issubdtype(array.dtype, np.floating):
                    late_in_array_bool = late_in_array_bool or any(np.any(array == late_float) for late_float in late_value_set)
                elif array.dtype == object:
                    late_in_array_bool = late_in_array_bool or any(
                        isinstance(value, (int, float, np.integer, np.floating)) and float(value) in late_value_set
                        for value in array)
            self.first_late_reachable_bool = bool(late_in_frame_bool or late_in_array_bool)
            self.first_has_data_context_bool = hasattr(view_in, "_data_context")
            self.first_forbidden_type_list = [type_name_str for type_name_str in get_reachable_type_name_set(view_in)
                                              if type_name_str in {"DataContext", "SourceFeed"}]
        return 1.0


# FUNCTION: TYPE NAMES OF so OBJECTS REACHABLE FROM THE VIEW
def get_reachable_type_name_set(root_in):
    """
    Walks runner objects hanging off the view.

    Args:
        root_in (object): Usually a DecisionView

    Returns:
        set[str]: Type names
    """
    # IDENTITY SET SO A BUFFER IS VISITED ONCE
    seen_set, name_set, stack_list = set(), set(), [root_in]
    while stack_list:
        obj = stack_list.pop()
        obj_id = id(obj)
        if obj_id in seen_set:
            continue
        seen_set.add(obj_id)
        name_set.add(type(obj).__name__)
        if isinstance(obj, (np.ndarray, pd.DataFrame, pd.Series, pd.DatetimeIndex)):
            continue
        if isinstance(obj, dict):
            stack_list.extend(obj.values())
            continue
        if isinstance(obj, (list, tuple)):
            stack_list.extend(obj)
            continue
        if hasattr(obj, "__dict__") and type(obj).__module__.startswith("so."):
            stack_list.extend(vars(obj).values())
    return name_set


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
    feat_pdf = pd.DataFrame({"value": [1.0, 999999.0],
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
        assert 999999.0 not in [value for row_list in probe.feat_value_list for value in row_list]
        # THE LABEL AT THE FIRST DECISION IS EXCLUDED THEN, AND VISIBLE ON THE NEXT SESSION (STRICTLY BEFORE)
        assert probe.label_value_list[0] == [10.0]
        assert 20.0 in probe.label_value_list[1]
        assert 30.0 not in [value for row_list in probe.label_value_list for value in row_list]
        # get_new ON THE FIRST CALL IS THE VISIBLE PREFIX; THE NEXT CALL ADDS THE LABEL NOW KNOWN
        assert probe.new_feat_value_list[0] == [1.0]
        assert probe.new_label_value_list[0] == [10.0]
        assert probe.new_feat_value_list[1] == []
        assert probe.new_label_value_list[1] == [20.0]
    finally:
        unregister_test_sources()
    passed("lookahead cut (bars, source, label)")


# FUNCTION: TEST THAT THE FIRST-DECISION VIEW HOLDS NO FUTURE
def test_first_decision_no_future():
    """
    At the first decide(), every array behind the view (including .base) is NaN / NaT after the decision bar, and no
    source or label row after the moment is reachable. The view does not hold a DataContext or a SourceFeed.

    Returns:
        None
    """
    # THE SAME FIXTURE AS THE LOOK-AHEAD CUT
    register_test_sources()
    try:
        fixture_dict = get_runner_fixture_dict()
        probe = ProbeDesign(["SPY_1MIN", TEST_FEAT_STR, TEST_LABEL_STR])
        run_daily_dict(probe, fixture_dict["ohlcv_array_dict"], fixture_dict["date1"], fixture_dict["date2"],
                       data_context_in=fixture_dict["data_context"])
        close_len = len(fixture_dict["ohlcv_array_dict"]["close_arr"])
        assert probe.first_close_base_len == close_len
        assert probe.slice_len_list[0] == fixture_dict["first_decision_idx"] + 1
        assert probe.slice_len_list[0] < close_len
        assert probe.first_tail_ok_bool is True
        assert probe.first_late_reachable_bool is False
        assert probe.first_has_data_context_bool is False
        assert probe.first_forbidden_type_list == []
    finally:
        unregister_test_sources()
    passed("first decision: .base tail empty, no later source or label row reachable")


# FUNCTION: ONE BANNED DESIGN-FILE SNIPPET
def get_banned_snippet_list():
    """
    One (name, source) pair per banned identifier. Each file is refused on its own.

    Args:
        None

    Returns:
        list[tuple]: (banned name, python source)
    """
    # EACH SNIPPET IS A MINIMAL DESIGN FILE
    header_str = "class Design:\n    DATA_SOURCE_LIST = ['SPY_1MIN']\n    def decide(self, view_in):\n"
    return [
        ("base", header_str + "        x = view_in.get_bar_array_dict()['close_arr'].base\n        return 1.0\n"),
        ("__closure__", header_str + "        x = (lambda: 0).__closure__\n        return 1.0\n"),
        ("__self__", header_str + "        x = view_in.get.__self__\n        return 1.0\n"),
        ("__globals__", header_str + "        x = view_in.get.__globals__\n        return 1.0\n"),
        ("__dict__", header_str + "        x = view_in.__dict__\n        return 1.0\n"),
        ("gc", "import gc\n" + header_str + "        gc.collect()\n        return 1.0\n"),
        ("inspect", "import inspect\n" + header_str + "        inspect.getsource(self.decide)\n        return 1.0\n"),
        ("_getframe", "import sys\n" + header_str + "        sys._getframe()\n        return 1.0\n"),
        ("ctypes", "import ctypes\n" + header_str + "        ctypes.c_int(0)\n        return 1.0\n"),
        ("so.runner", "import so.runner\n" + header_str + "        return 1.0\n"),
        ("so.core.point_in_time", "from so.core.point_in_time import DataContext\n" + header_str + "        return 1.0\n"),
        ("so.core.holdout", "from so.core.holdout import get_perturbed_ohlcv_dict\n" + header_str + "        return 1.0\n"),
    ]


# FUNCTION: TEST THAT EACH BANNED NAME IN A DESIGN FILE IS REFUSED
def test_preflight_refuses_banned_names():
    """
    check_design_file and run_daily_dict both refuse a design file that uses each banned name.

    Returns:
        None
    """
    # A CLEAN FILE PASSES; EACH BANNED FILE RAISES BEFORE decide()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    temp_dir_str = tempfile.mkdtemp(prefix="so_runner_preflight_")
    try:
        clean_path_str = os.path.join(temp_dir_str, "clean_design.py")
        with open(clean_path_str, "w", encoding="utf-8") as clean_file:
            clean_file.write("class Design:\n    DATA_SOURCE_LIST = ['SPY_1MIN']\n    def decide(self, view_in):\n        return 1.0\n")
        check_design_file(clean_path_str)
        run_daily_dict(ConstantOneDesign(), ohlcv_array_dict, date1, date2, design_file_path_str_in=clean_path_str)
        for banned_str, source_str in get_banned_snippet_list():
            file_path_str = os.path.join(temp_dir_str, f"banned_{banned_str.replace('.', '_')}.py")
            with open(file_path_str, "w", encoding="utf-8") as banned_file:
                banned_file.write(source_str)
            raised_bool = False
            try:
                check_design_file(file_path_str)
            except ValueError:
                raised_bool = True
            assert raised_bool, f"check_design_file accepted {banned_str}"
            loop_raised_bool = False
            try:
                run_daily_dict(ConstantOneDesign(), ohlcv_array_dict, date1, date2, design_file_path_str_in=file_path_str)
            except ValueError:
                loop_raised_bool = True
            assert loop_raised_bool, f"run_daily_dict accepted {banned_str}"
    finally:
        shutil.rmtree(temp_dir_str, ignore_errors=True)
    passed("preflight refuses each banned name in a design file")


# FUNCTION: TEST THAT THE FRACTIONAL ENGINE MATCHES simulate_fractional_exposure_dict
def test_engine_parity_synthetic_year():
    """
    Random target weights with NaNs, dead band 0 and 0.1, initial weight 0.5, over a synthetic year, give the same
    trades and equity as simulate_fractional_exposure_dict.

    Returns:
        None
    """
    # ONE SYNTHETIC YEAR, THE SAME WEIGHT PATH FOR BOTH DEAD BANDS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2010-12-31", seed_in=8)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_date_list = list(ohlcv_array_dict["session_date_list"])
    date1, date2 = session_date_list[0], session_date_list[-1]
    rng = np.random.default_rng(21)
    weight_arr = rng.uniform(0.0, 1.0, len(session_date_list))
    weight_arr[rng.random(len(session_date_list)) < 0.2] = np.nan
    for dead_band in (0.0, 0.1):
        design = ScriptedWeightDesign(weight_arr, session_date_list)
        runner_dict = run_daily_dict(design, ohlcv_array_dict, date1, date2, dead_band_in=dead_band, initial_weight_in=0.5)
        sim_dict = simulate_fractional_exposure_dict(ohlcv_array_dict, date1, date2, weight_arr, dead_band, 0.5)
        runner_trade_pdf, sim_trade_pdf = runner_dict["trade_pdf"], sim_dict["trade_pdf"]
        assert list(runner_trade_pdf.columns) == list(sim_trade_pdf.columns)
        assert len(runner_trade_pdf) == len(sim_trade_pdf)
        if len(runner_trade_pdf):
            assert runner_trade_pdf["delta_share_count"].tolist() == sim_trade_pdf["delta_share_count"].tolist()
            assert runner_trade_pdf["fill_price"].tolist() == sim_trade_pdf["fill_price"].tolist()
            assert runner_trade_pdf["reason"].tolist() == sim_trade_pdf["reason"].tolist()
            assert runner_trade_pdf["raw_price"].tolist() == sim_trade_pdf["raw_price"].tolist()
            assert runner_trade_pdf["trade_idx"].tolist() == sim_trade_pdf["trade_idx"].tolist()
            assert runner_trade_pdf["fee"].tolist() == sim_trade_pdf["fee"].tolist()
            assert runner_trade_pdf["share_count_after"].tolist() == sim_trade_pdf["share_count_after"].tolist()
        assert runner_dict["daily_equity_pdf"]["date"].tolist() == sim_dict["daily_equity_pdf"]["date"].tolist()
        assert runner_dict["daily_equity_pdf"]["equity"].tolist() == sim_dict["daily_equity_pdf"]["equity"].tolist()
        assert runner_dict["daily_equity_pdf"]["in_position"].tolist() == sim_dict["daily_equity_pdf"]["in_position"].tolist()
        assert runner_dict["metric_dict"] == sim_dict["metric_dict"]
    passed("engine parity vs simulate_fractional_exposure_dict (year, NaNs, dead band 0 and 0.1, w0=0.5)")


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
        test_first_decision_no_future()
        test_preflight_refuses_banned_names()
        test_weight_one_is_buy_and_hold()
        test_identical_runs()
        test_later_bar_perturbation()
        test_engine_parity_synthetic_year()
        assert TEST_FEAT_STR not in SOURCE_SPEC_DICT
        assert TEST_LABEL_STR not in SOURCE_SPEC_DICT
        print("\nAll runner tests passed ✅")
    finally:
        unregister_test_sources()
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
