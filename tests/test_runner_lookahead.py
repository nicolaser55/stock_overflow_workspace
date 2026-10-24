"""
Workspace Tests: runner automatic look-ahead check (infrastructure 4b-1c)

Run from the workspace root:   python tests/test_runner_lookahead.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import json
import os
import sys
import tempfile
import shutil
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
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_lookahead_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths, config
from so.core.trial_log import read_trial_log_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from so.core.point_in_time import (get_runner_context, get_minute_bar_available_ts, get_ny_timestamp,
                                   unregister_source, SOURCE_SPEC_DICT, register_source_dict)
from so.features.daily_features import get_session_decision_idx_dict
from so.runner import (run_development_dict, get_lookahead_cut_date_list, LOOKAHEAD_FILE_STR, LOOK_AHEAD_PASS_STR,
                       LOOK_AHEAD_FAIL_STR, MANIFEST_FILE_STR)
from so.runner.loop import fill_bar_buffer_through_decision
from so.runner.view import SourceFeed, get_sliced_bar_array_dict
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_candidate_design as cand_design
import runner_lookahead_design as look_design
from runner_lookahead_design import LOOKAHEAD_FEAT_STR, LOOKAHEAD_LABEL_STR

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


# FUNCTION: THREE INJECTED PERIODS ON A SHORT SYNTHETIC SPAN
def get_injected_period_pdf(session_date_list_in):
    """
    Three contiguous periods that tile the span.

    Args:
        session_date_list_in (list): Session dates (at least 12)

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, valid_start, valid_end
    """
    # THE SPAN IS LONG ENOUGH FOR THREE PERIODS AND THREE CUT THIRDS
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    assert len(session_date_list) >= 12
    bound_list = [(0, 3), (4, 7), (8, len(session_date_list) - 1)]
    row_dict_list = []
    for period_id, (start_idx, end_idx) in enumerate(bound_list):
        start_date, end_date = session_date_list[start_idx], session_date_list[end_idx]
        row_dict_list.append({"period_id": period_id, "period_start": start_date, "period_end": end_date,
                              "session_count": int(end_idx - start_idx + 1), "valid_start": start_date,
                              "valid_end": end_date})
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
    folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_lookahead_test")
    os.makedirs(folder_str, exist_ok=True)
    return os.path.join(folder_str, file_name_str_in)


# FUNCTION: REGISTER THE TWO TEST SOURCES IF THEY ARE MISSING
def register_lookahead_test_sources():
    """
    Adds the feature and label sources the look-ahead design reads. The design file cannot import the registry.

    Args:
        None

    Returns:
        None
    """
    # THE TEST PLANTS available_ts AND label_known_ts
    ny_str = "America/New_York"

    def add_feature_available_ts_pdf(pdf_in):
        return pdf_in.copy()

    def add_label_known_ts_pdf(pdf_in):
        stamped_pdf = pdf_in.copy()
        if "available_ts" not in stamped_pdf.columns:
            stamped_pdf["available_ts"] = stamped_pdf["label_known_ts"]
        return stamped_pdf

    if LOOKAHEAD_FEAT_STR not in SOURCE_SPEC_DICT:
        register_source_dict(LOOKAHEAD_FEAT_STR, {
            "loader": "test", "time_zone": ny_str, "timestamp_convention": "planted available_ts",
            "availability_func": add_feature_available_ts_pdf, "revision_policy": "not revised",
            "revision_reason": "test frame", "role": "feature", "holdout": "test",
        })
    if LOOKAHEAD_LABEL_STR not in SOURCE_SPEC_DICT:
        register_source_dict(LOOKAHEAD_LABEL_STR, {
            "loader": "test", "time_zone": ny_str, "timestamp_convention": "planted label_known_ts",
            "availability_func": add_label_known_ts_pdf, "revision_policy": "not revised",
            "revision_reason": "test frame", "role": "label", "holdout": "test",
        })


# FUNCTION: DROP THE LOOK-AHEAD TEST SOURCES
def unregister_lookahead_test_sources():
    """
    Args:
        None

    Returns:
        None
    """
    # DROP ONLY WHEN PRESENT
    if LOOKAHEAD_FEAT_STR in SOURCE_SPEC_DICT:
        unregister_source(LOOKAHEAD_FEAT_STR)
    if LOOKAHEAD_LABEL_STR in SOURCE_SPEC_DICT:
        unregister_source(LOOKAHEAD_LABEL_STR)


# FUNCTION: PLANTED FEATURE AND LABEL ROWS, ONE PER SESSION
def get_planted_source_frame_dict(ohlcv_array_dict_in):
    """
    A feature row at each session's decision_ts, and a label row one minute after that decision.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        dict: source name -> frame
    """
    # ONE UNIQUE VALUE PER SESSION
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    feat_row_list, label_row_list = [], []
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        decision_idx = int(idx_dict["decision_idx_arr"][session_idx])
        decision_ts = get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
        feat_row_list.append({"value": 1000.0 + session_idx, "available_ts": decision_ts, "date": session_date})
        label_row_list.append({"value": 1_000_000.0 + session_idx,
                               "label_known_ts": decision_ts + pd.Timedelta(minutes=1), "date": session_date})
    return {LOOKAHEAD_FEAT_STR: pd.DataFrame(feat_row_list), LOOKAHEAD_LABEL_STR: pd.DataFrame(label_row_list)}


# FUNCTION: SYNTHETIC BARS PLUS A RUNNER CONTEXT WITH PLANTED SOURCES
def get_lookahead_fixture_dict():
    """
    Args:
        None

    Returns:
        dict: ohlcv_array_dict, data_context, period_pdf
    """
    # TWO AND A HALF WEEKS IS ENOUGH FOR THREE THIRDS
    register_lookahead_test_sources()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    source_frame_dict = get_planted_source_frame_dict(ohlcv_array_dict)
    data_context = get_runner_context(ohlcv_array_dict, source_frame_dict_in=source_frame_dict,
                                      declared_name_list_in=list(look_design.DATA_SOURCE_LIST))
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    return {"ohlcv_array_dict": ohlcv_array_dict, "data_context": data_context, "period_pdf": period_pdf}


# FUNCTION: RUN THE LOOK-AHEAD DESIGN ON THE FIXTURE
def run_lookahead_design_dict(run_id_str_in, trial_file_str_in, n_jobs_int_in=1):
    """
    Args:
        run_id_str_in (str): Run id
        trial_file_str_in (str): Trial log file name
        n_jobs_int_in (int): Process count

    Returns:
        dict: run_development_dict output plus the fixture
    """
    # IN-PROCESS SO A PATCH ON THE RUNNER STAYS VISIBLE
    fixture_dict = get_lookahead_fixture_dict()
    trial_log_path_str = get_test_trial_log_path_str(trial_file_str_in)
    result_dict = run_development_dict(look_design, fixture_dict["ohlcv_array_dict"],
                                       data_context_in=fixture_dict["data_context"], run_id_str_in=run_id_str_in,
                                       n_jobs_int_in=n_jobs_int_in, period_pdf_in=fixture_dict["period_pdf"],
                                       trial_log_path_str_in=trial_log_path_str, commit_str_in="testcommit",
                                       code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2)
    result_dict["trial_log_path_str"] = trial_log_path_str
    result_dict["period_count_int"] = int(len(fixture_dict["period_pdf"]))
    return result_dict


# FUNCTION: THE LOOK-AHEAD JSON FROM A RUN FOLDER
def read_lookahead_json_dict(run_folder_str_in):
    """
    Args:
        run_folder_str_in (str): Run folder

    Returns:
        dict: Payload
    """
    # UTF-8
    with open(os.path.join(run_folder_str_in, LOOKAHEAD_FILE_STR), "r", encoding="utf-8") as json_file:
        return json.load(json_file)


# FUNCTION: CUT DATES SIT ONE IN EACH THIRD AND ARE STABLE
def test_cut_dates_one_per_third():
    """
    Three cuts, one in each third of the usable span (everything except the last session). The same seed repeats.

    Returns:
        None
    """
    # A 16-SESSION LIST
    session_date_list = list(pd.date_range("2010-06-01", periods=16, freq="B").date)
    cut_list = get_lookahead_cut_date_list(session_date_list)
    assert len(cut_list) == int(config.RUNNER_LOOKAHEAD_CUT_COUNT) == 3
    usable_list = session_date_list[:-1]
    usable_count = len(usable_list)
    for third_idx, cut_date in enumerate(cut_list):
        start_idx = (third_idx * usable_count) // 3
        end_idx = ((third_idx + 1) * usable_count) // 3
        assert usable_list[start_idx] <= cut_date <= usable_list[end_idx - 1]
        assert cut_date != session_date_list[-1]
    again_list = get_lookahead_cut_date_list(session_date_list)
    assert again_list == cut_list
    passed("cut dates: one in each third, last session excluded, seed-stable")


# FUNCTION: A CLEAN DESIGN PASSES THE CHECK
def test_clean_design_passes():
    """
    Constant-weight candidates do not read the future. The check passes, lookahead.json and the manifest record
    pass, and the trial log has one row per candidate-period.

    Returns:
        None
    """
    # THE 4B-1A SYNTHETIC DESIGN
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    trial_log_path_str = get_test_trial_log_path_str("clean.csv")
    result_dict = run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in="lookahead_clean",
                                       n_jobs_int_in=1, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=trial_log_path_str, commit_str_in="testcommit",
                                       code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2)
    lookahead_dict = result_dict["lookahead_dict"]
    assert lookahead_dict["pass_bool"] is True
    assert lookahead_dict["status_str"] == LOOK_AHEAD_PASS_STR
    assert len(lookahead_dict["cut_date_list"]) == 3
    assert result_dict["verdict_dict"]["look_ahead_dict"]["pass_bool"] is True
    assert result_dict["verdict_dict"]["look_ahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR
    assert "look-ahead" not in result_dict["verdict_dict"]["failed_list"]
    payload_dict = read_lookahead_json_dict(result_dict["run_folder_str"])
    assert payload_dict["pass_bool"] is True
    assert payload_dict["cut_seed_int"] == int(config.RUNNER_LOOKAHEAD_CUT_SEED)
    for candidate in cand_design.CANDIDATE_LIST:
        assert payload_dict["candidate_dict"][candidate]["pass_bool"] is True
        assert payload_dict["candidate_dict"][candidate]["first_fail_dict"] is None
    with open(os.path.join(result_dict["run_folder_str"], MANIFEST_FILE_STR), "r", encoding="utf-8") as manifest_file:
        manifest_dict = json.load(manifest_file)
    assert manifest_dict["verdict"]["look_ahead"] == LOOK_AHEAD_PASS_STR
    assert LOOKAHEAD_FILE_STR in manifest_dict["output_files"]
    trial_pdf = read_trial_log_pdf(trial_log_path_str)
    expected_count = len(cand_design.CANDIDATE_LIST) * len(period_pdf)
    assert len(trial_pdf) == expected_count
    passed("clean design: look-ahead pass, lookahead.json and manifest record it, no extra trial rows")


# FUNCTION: THE VIEW-READING DESIGN ALSO PASSES WHEN THE RUNNER IS NOT PATCHED
def test_view_read_design_passes_without_patch():
    """
    Reading the view is not a leak. The check passes.

    Returns:
        None
    """
    # NO PATCH
    result_dict = run_lookahead_design_dict("lookahead_view_clean", "view_clean.csv")
    assert result_dict["lookahead_dict"]["pass_bool"] is True
    trial_pdf = read_trial_log_pdf(result_dict["trial_log_path_str"])
    assert len(trial_pdf) == 1 * result_dict["period_count_int"]
    passed("view-reading design passes when the runner does not leak")


# FUNCTION: ASSERT A FAILED CHECK NAMES THE FIRST CUT SESSION
def check_lookahead_failure(result_dict_in, leak_name_str_in):
    """
    Args:
        result_dict_in (dict): run_development_dict output
        leak_name_str_in (str): What was patched

    Returns:
        None
    """
    # THE FIRST CUT IS THE FIRST SESSION WHOSE LEAKED FUTURE IS PERTURBED
    lookahead_dict = result_dict_in["lookahead_dict"]
    assert lookahead_dict["pass_bool"] is False
    assert lookahead_dict["status_str"] == LOOK_AHEAD_FAIL_STR
    first_fail_dict = lookahead_dict["first_fail_dict"]
    assert first_fail_dict is not None
    first_cut_str = lookahead_dict["cut_date_list"][0]
    assert first_fail_dict["session_date"] == first_cut_str
    assert first_fail_dict["full_decision"] is not None
    assert first_fail_dict["check_decision"] is not None
    assert first_fail_dict["full_decision"] != first_fail_dict["check_decision"]
    assert result_dict_in["verdict_dict"]["look_ahead_dict"]["pass_bool"] is False
    assert "look-ahead" in result_dict_in["verdict_dict"]["failed_list"]
    payload_dict = read_lookahead_json_dict(result_dict_in["run_folder_str"])
    assert payload_dict["pass_bool"] is False
    assert payload_dict["first_fail_dict"]["session_date"] == first_cut_str
    with open(os.path.join(result_dict_in["run_folder_str"], MANIFEST_FILE_STR), "r", encoding="utf-8") as manifest_file:
        manifest_dict = json.load(manifest_file)
    assert manifest_dict["verdict"]["look_ahead"] == LOOK_AHEAD_FAIL_STR
    assert LOOKAHEAD_FILE_STR in manifest_dict["output_files"]
    trial_pdf = read_trial_log_pdf(result_dict_in["trial_log_path_str"])
    assert len(trial_pdf) == 1 * result_dict_in["period_count_int"]
    _ = leak_name_str_in


# FUNCTION: BAR BUFFER FILLED ONE SESSION PAST THE DECISION FAILS THE CHECK
def test_bar_buffer_leak_fails():
    """
    fill_bar_buffer_through_decision copies through the next session's decision bar, and the view slice follows
    that fill so a legal design (no .base) sees the leaked close. The check fails at the first cut and names that
    session.

    Returns:
        None
    """
    # PATCH THE LOOP'S FILL AND THE VIEW SLICE, THEN RESTORE BOTH
    original_fill = fill_bar_buffer_through_decision
    original_slice = get_sliced_bar_array_dict

    def leaking_fill(buffer_dict_in, ohlcv_array_dict_in, session_idx_in, decision_idx_in):
        idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
        next_session_idx = int(session_idx_in) + 1
        if next_session_idx < len(ohlcv_array_dict_in["session_date_list"]):
            next_decision_idx = int(idx_dict["decision_idx_arr"][next_session_idx])
            original_fill(buffer_dict_in, ohlcv_array_dict_in, next_session_idx, next_decision_idx)
            return
        original_fill(buffer_dict_in, ohlcv_array_dict_in, session_idx_in, decision_idx_in)

    def leaking_slice(buffer_dict_in, last_bar_idx_in, session_idx_in):
        leak_idx = int(buffer_dict_in.get("copied_through_idx", last_bar_idx_in))
        leak_session_idx = int(buffer_dict_in.get("copied_through_session_idx", session_idx_in))
        return original_slice(buffer_dict_in, leak_idx, leak_session_idx)

    import so.runner.loop as loop_mod
    import so.runner.view as view_mod
    loop_mod.fill_bar_buffer_through_decision = leaking_fill
    view_mod.get_sliced_bar_array_dict = leaking_slice
    try:
        result_dict = run_lookahead_design_dict("lookahead_bar_leak", "bar_leak.csv")
        check_lookahead_failure(result_dict, "bar")
    finally:
        loop_mod.fill_bar_buffer_through_decision = original_fill
        view_mod.get_sliced_bar_array_dict = original_slice
    passed("bar buffer filled one session past the decision: check fails and names the first differing session")


# FUNCTION: A SOURCE FEED ADVANCED PAST THE MOMENT FAILS THE CHECK
def test_source_buffer_leak_fails():
    """
    Feature SourceFeed.advance_to_ts copies rows through one day after the moment.

    Returns:
        None
    """
    # PATCH ONLY THE FEATURE FEED
    original_advance = SourceFeed.advance_to_ts

    def leaking_advance(self, moment_ts_in):
        if self.role_str != "feature" or self.source_name_str != LOOKAHEAD_FEAT_STR:
            return original_advance(self, moment_ts_in)
        later_ts = get_ny_timestamp(moment_ts_in) + pd.Timedelta(days=1)
        return original_advance(self, later_ts)

    SourceFeed.advance_to_ts = leaking_advance
    try:
        result_dict = run_lookahead_design_dict("lookahead_source_leak", "source_leak.csv")
        check_lookahead_failure(result_dict, "source")
    finally:
        SourceFeed.advance_to_ts = original_advance
    passed("source buffer filled past the moment: check fails and names the first differing session")


# FUNCTION: A LABEL FEED ADVANCED PAST THE MOMENT FAILS THE CHECK
def test_label_buffer_leak_fails():
    """
    Label SourceFeed.advance_to_ts copies rows through one day after the moment.

    Returns:
        None
    """
    # PATCH ONLY THE LABEL FEED
    original_advance = SourceFeed.advance_to_ts

    def leaking_advance(self, moment_ts_in):
        if self.role_str != "label" or self.source_name_str != LOOKAHEAD_LABEL_STR:
            return original_advance(self, moment_ts_in)
        later_ts = get_ny_timestamp(moment_ts_in) + pd.Timedelta(days=1)
        return original_advance(self, later_ts)

    SourceFeed.advance_to_ts = leaking_advance
    try:
        result_dict = run_lookahead_design_dict("lookahead_label_leak", "label_leak.csv")
        check_lookahead_failure(result_dict, "label")
    finally:
        SourceFeed.advance_to_ts = original_advance
    passed("label buffer filled past the moment: check fails and names the first differing session")


# FUNCTION: PARALLEL LOOK-AHEAD JOBS MATCH THE IN-PROCESS RESULT
def test_minute_cut_moment():
    """
    Minute mode: with the cut moment given, a decision after it on the cut session is not compared; one at or before
    it still fails.

    Returns:
        None
    """
    # THREE MINUTES OF THE CUT SESSION: 15:57 AND 15:58 ARE DECIDED BY 15:59, 15:59 IS DECIDED AT 16:00
    from so.runner.lookahead import get_first_decision_difference_dict
    cut_date = pd.Timestamp("2015-05-26").date()
    cut_ts = pd.Timestamp("2015-05-26 15:59", tz="America/New_York")
    bar_ts_list = [pd.Timestamp(f"2015-05-26 15:{minute}", tz="America/New_York") for minute in (57, 58, 59)]
    def get_list(delta_list_in):
        return [{"target_weight": 1.0 if delta is not None else 0.0, "delta": delta, "_decision_ts": bar_ts,
                 "_session_date": cut_date, "_bar_idx": idx} for idx, (bar_ts, delta) in enumerate(zip(bar_ts_list, delta_list_in))]
    full_list = get_list([None, None, None])
    late_list = get_list([None, None, 0.0028])
    early_list = get_list([None, 0.0028, None])
    assert get_first_decision_difference_dict(full_list, None, late_list, None, cut_date, cut_ts) is None
    assert get_first_decision_difference_dict(full_list, None, late_list, None, cut_date) is not None
    fail_dict = get_first_decision_difference_dict(full_list, None, early_list, None, cut_date, cut_ts)
    assert fail_dict is not None and fail_dict["decision_ts"] == str(bar_ts_list[1])
    passed("minute mode: a decision after the cut moment is not compared; one before it still fails")


def test_parallel_lookahead_matches_in_process():
    """
    n_jobs=2 and n_jobs=1 agree on a clean design.

    Returns:
        None
    """
    # THE CONSTANT-WEIGHT DESIGN SPAWNS CLEANLY
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    one_dict = run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in="lookahead_jobs1",
                                    n_jobs_int_in=1, period_pdf_in=period_pdf,
                                    trial_log_path_str_in=get_test_trial_log_path_str("jobs1.csv"),
                                    commit_str_in="testcommit", code_hash_str_in="testhash",
                                    check_clean_tree_bool_in=False, check_view_bool_in=False,
                                    baseline_seed_count_int_in=2)
    two_dict = run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in="lookahead_jobs2",
                                    n_jobs_int_in=2, period_pdf_in=period_pdf,
                                    trial_log_path_str_in=get_test_trial_log_path_str("jobs2.csv"),
                                    commit_str_in="testcommit", code_hash_str_in="testhash",
                                    check_clean_tree_bool_in=False, check_view_bool_in=False,
                                    baseline_seed_count_int_in=2)
    assert one_dict["lookahead_dict"]["pass_bool"] is True
    assert two_dict["lookahead_dict"]["pass_bool"] is True
    assert one_dict["lookahead_dict"]["cut_date_list"] == two_dict["lookahead_dict"]["cut_date_list"]
    passed("n_jobs=2 look-ahead matches the in-process pass")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE A TEMPORARY FOLDER THIS FILE CREATED
    try:
        test_cut_dates_one_per_third()
        test_minute_cut_moment()
        test_clean_design_passes()
        test_view_read_design_passes_without_patch()
        test_bar_buffer_leak_fails()
        test_source_buffer_leak_fails()
        test_label_buffer_leak_fails()
        test_parallel_lookahead_matches_in_process()
        print("\nAll runner look-ahead tests passed ✅")
    finally:
        unregister_lookahead_test_sources()
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
