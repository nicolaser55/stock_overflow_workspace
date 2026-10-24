import os
import time
import multiprocessing
import numpy as np
# IMPORT THE SHARED CONFIGURATION (CUT COUNT, SEED, TOLERANCE)
from so import config
# IMPORT THE DIRECT-READ FLAG AND THE POINT-IN-TIME HELPERS
from so.core.point_in_time import (set_direct_read_blocked_bool, get_source_spec_dict, add_available_ts_pdf,
                                   get_feature_column_pdf, get_spy_frame_pdf, get_perturbed_feature_pdf,
                                   get_cut_clock_dict, get_minute_bar_available_ts, get_ny_timestamp, DataContext)
# IMPORT THE EXISTING CUT, TRUNCATION AND BAR-PERTURBATION HELPERS
from so.core.holdout import get_date, get_truncated_ohlcv_dict, get_perturbed_ohlcv_dict
# IMPORT THE DAILY LOOP AND THE DECISION SHAPE
from so.runner.loop import get_stream_loop, get_design_mode_str, MODE_MINUTE_STR
from so.runner.engine import get_decision_dict, DECISION_KEY_LIST, FLOAT_DECISION_KEY_LIST
from so.runner.checkpoint import (read_decisions_list, get_file_exists_bool, read_pickle, set_runs_root_str)
from so.runner.verdict import write_json_file, LOOK_AHEAD_PASS_STR, LOOK_AHEAD_FAIL_STR

"""
Automatic Look-Ahead Check (infrastructure step 4b-1c)

A second line behind the point-in-time view. After the candidate streams finish, the runner draws
RUNNER_LOOKAHEAD_CUT_COUNT cut dates (one in each third of the development span, fixed seed), and for every
candidate and every cut it re-runs the stream twice:

    truncation    bars and declared sources stop after the cut. One extra session is kept in the bar arrays so the
                  cut is not the last window session (the last session has no design call).
    perturbation  every bar after the cut's decision bar is overwritten (get_perturbed_ohlcv_dict). Declared feature
                  rows with available_ts after the cut, and label rows with label_known_ts after the cut, are
                  overwritten (get_perturbed_feature_pdf). Session structure is unchanged.

Every decision up to and including the cut must equal the full run's decision. A first mismatch fails that candidate
and fails the verdict. Jobs run in the same spawn pool as the candidate streams. These re-runs never write a trial-log
row and never write a checkpoint.
"""

# FILE WRITTEN IN THE RUN FOLDER
LOOKAHEAD_FILE_STR = "lookahead.json"
# THE TWO CHECK KINDS
KIND_TRUNCATION_STR = "truncation"
KIND_PERTURBATION_STR = "perturbation"
KIND_STR_LIST = [KIND_TRUNCATION_STR, KIND_PERTURBATION_STR]


# FUNCTION: CUT DATES, ONE IN EACH THIRD OF THE SPAN
def get_lookahead_cut_date_list(session_date_list_in, count_int_in=None, seed_int_in=None):
    """
    Drops the last session (it has no design call) and draws one date from each equal third of what remains, with a
    fixed seed.

    Args:
        session_date_list_in (list): Development sessions in order
        count_int_in (int | None): Cut count (None = RUNNER_LOOKAHEAD_CUT_COUNT)
        seed_int_in (int | None): Draw seed (None = RUNNER_LOOKAHEAD_CUT_SEED)

    Returns:
        list[datetime.date]: Cut dates, oldest first
    """
    # THE LAST SESSION CANNOT BE A CUT: THE LOOP DOES NOT CALL decide() THERE
    count_int = int(config.RUNNER_LOOKAHEAD_CUT_COUNT if count_int_in is None else count_int_in)
    seed_int = int(config.RUNNER_LOOKAHEAD_CUT_SEED if seed_int_in is None else seed_int_in)
    session_date_list = [get_date(session_date) for session_date in session_date_list_in]
    if count_int < 1:
        raise ValueError("look-ahead cut count must be at least 1.")
    if len(session_date_list) < count_int + 1:
        raise ValueError(f"need at least {count_int + 1} sessions to draw {count_int} look-ahead cuts.")
    usable_list = session_date_list[:-1]
    usable_count = len(usable_list)
    rng = np.random.default_rng(seed_int)
    cut_list = []
    for third_idx in range(count_int):
        start_idx = (third_idx * usable_count) // count_int
        end_idx = ((third_idx + 1) * usable_count) // count_int
        if end_idx <= start_idx:
            raise ValueError("a look-ahead third is empty.")
        pick_idx = int(rng.integers(start_idx, end_idx))
        cut_list.append(usable_list[pick_idx])
    return cut_list


# FUNCTION: YYYYMMDD SEED OF ONE CUT
def get_perturbation_seed_int(cut_date_in):
    """
    The same integer get_perturbed_ohlcv_dict uses, and the seed passed to get_perturbed_feature_pdf.

    Args:
        cut_date_in (datetime.date): Cut session

    Returns:
        int: Seed
    """
    # ONE STREAM PER CUT DATE
    return int(get_date(cut_date_in).strftime("%Y%m%d"))


# FUNCTION: BAR ARRAYS THROUGH THE SESSION AFTER THE CUT
def get_lookahead_truncated_ohlcv_dict(ohlcv_array_dict_in, cut_date_in):
    """
    get_truncated_ohlcv_dict through the session after the cut, when that session exists, so the cut still has a
    design call. The extra session is the last window session of the truncated stream and is not compared.

    Args:
        ohlcv_array_dict_in (dict): Full bars
        cut_date_in (datetime.date): Cut session

    Returns:
        dict: Truncated arrays
    """
    # KEEP ONE SESSION PAST THE CUT WHEN THE SPAN HAS IT
    session_date_list = [get_date(session_date) for session_date in ohlcv_array_dict_in["session_date_list"]]
    cut_day = get_date(cut_date_in)
    cut_idx = max(idx for idx, session_day in enumerate(session_date_list) if session_day <= cut_day)
    keep_idx = min(cut_idx + 1, len(session_date_list) - 1)
    return get_truncated_ohlcv_dict(ohlcv_array_dict_in, session_date_list[keep_idx])


# FUNCTION: A CONTEXT WHOSE ROWS STOP AT THE CUT SESSION END
def get_lookahead_truncated_context(data_context_in, ohlcv_array_dict_in, cut_date_in, truncated_ohlcv_dict_in):
    """
    Non-SPY rows with available_ts after the cut session's last bar are dropped. SPY comes from the truncated arrays.

    Args:
        data_context_in (DataContext | None): Loaded sources
        ohlcv_array_dict_in (dict): Full bars (for the cut clocks)
        cut_date_in (datetime.date): Cut session
        truncated_ohlcv_dict_in (dict): Arrays through the extra session

    Returns:
        DataContext | None: Child context, or None when there was no parent
    """
    # NOTHING TO CUT
    if data_context_in is None:
        return None
    clock_dict = get_cut_clock_dict(ohlcv_array_dict_in, cut_date_in)
    return data_context_in.get_truncated_context(clock_dict["session_end_ts"], truncated_ohlcv_dict_in)


# FUNCTION: A CONTEXT WHOSE LATER FEATURE AND LABEL VALUES ARE PERTURBED
def get_lookahead_perturbed_context(data_context_in, ohlcv_array_dict_in, cut_date_in, perturbed_ohlcv_dict_in):
    """
    Feature rows with available_ts after the cut decision, and label rows with label_known_ts after it, are passed
    through get_perturbed_feature_pdf. SPY comes from the already-perturbed arrays.

    Args:
        data_context_in (DataContext | None): Loaded sources
        ohlcv_array_dict_in (dict): Full bars (for the cut clocks)
        cut_date_in (datetime.date): Cut session
        perturbed_ohlcv_dict_in (dict): Arrays with bars after the decision overwritten

    Returns:
        DataContext | None: Child context, or None when there was no parent
    """
    # NOTHING TO PERTURB
    if data_context_in is None:
        return None
    clock_dict = get_cut_clock_dict(ohlcv_array_dict_in, cut_date_in)
    decision_ts = clock_dict["decision_ts"]
    seed_int = get_perturbation_seed_int(cut_date_in)
    child_dict = {}
    for source_name_str, frame_pdf in data_context_in.frame_dict.items():
        if source_name_str == "SPY_1MIN":
            continue
        stamped_pdf = add_available_ts_pdf(source_name_str, frame_pdf)
        spec_dict = get_source_spec_dict(source_name_str)
        if spec_dict["role"] == "feature":
            stamped_pdf = get_feature_column_pdf(source_name_str, stamped_pdf, None)
            child_dict[source_name_str] = get_perturbed_feature_pdf(stamped_pdf, decision_ts, seed_int, source_name_str)
            continue
        work_pdf = stamped_pdf.copy()
        original_available_series = work_pdf["available_ts"].copy() if "available_ts" in work_pdf.columns else None
        work_pdf["available_ts"] = work_pdf["label_known_ts"]
        perturbed_pdf = get_perturbed_feature_pdf(work_pdf, decision_ts, seed_int, source_name_str)
        if original_available_series is not None:
            perturbed_pdf["available_ts"] = original_available_series
        child_dict[source_name_str] = perturbed_pdf
    child_dict["SPY_1MIN"] = get_spy_frame_pdf(perturbed_ohlcv_dict_in)
    return DataContext(data_context_in.mode_str, data_context_in.as_of_limit_ts, None, child_dict,
                       data_context_in.access_sink_list, data_context_in.declared_name_list)


# FUNCTION: WHETHER TWO DECISIONS MATCH
def get_decision_equal_bool(full_decision_dict_in, check_decision_dict_in, tolerance_float_in=None):
    """
    target_weight compares within NUMERIC_TOLERANCE, with NaN equal to NaN. The other keys compare exactly.

    Args:
        full_decision_dict_in, check_decision_dict_in (dict): get_decision_dict outputs
        tolerance_float_in (float | None): Absolute band (None = NUMERIC_TOLERANCE)

    Returns:
        bool: True when every key matches
    """
    # NORMALISE BOTH SIDES TO THE SAME KEYS
    tolerance_float = float(config.NUMERIC_TOLERANCE if tolerance_float_in is None else tolerance_float_in)
    full_dict = get_decision_dict(full_decision_dict_in)
    check_dict = get_decision_dict(check_decision_dict_in)
    for key_str in DECISION_KEY_LIST:
        full_value, check_value = full_dict.get(key_str), check_dict.get(key_str)
        if key_str in FLOAT_DECISION_KEY_LIST:
            full_nan_bool = full_value is None or (isinstance(full_value, (float, np.floating)) and np.isnan(full_value))
            check_nan_bool = check_value is None or (isinstance(check_value, (float, np.floating)) and np.isnan(check_value))
            if full_nan_bool and check_nan_bool:
                continue
            if full_nan_bool or check_nan_bool:
                return False
            if abs(float(full_value) - float(check_value)) > tolerance_float:
                return False
            continue
        if full_value != check_value:
            return False
    return True


# FUNCTION: SESSION DATE STORED ON A RECORDED DECISION, OR THE PARALLEL LIST
def get_recorded_session_date(decision_dict_in, session_date_in=None):
    """
    Minute mode stores _session_date on the decision. Daily mode uses the parallel session list.

    Args:
        decision_dict_in (dict): Recorded decision
        session_date_in: Fallback session

    Returns:
        datetime.date | None: Session
    """
    # MINUTE METADATA WINS
    if isinstance(decision_dict_in, dict) and decision_dict_in.get("_session_date") is not None:
        return get_date(decision_dict_in["_session_date"])
    if session_date_in is None:
        return None
    return get_date(session_date_in)


# FUNCTION: THE FIRST SESSION WHOSE DECISION DIFFERS, THROUGH THE CUT
def get_first_decision_difference_dict(full_decision_list_in, full_session_list_in, check_decision_list_in,
                                       check_session_list_in, cut_date_in, cut_ts_in=None):
    """
    Walks the full run in order. Minute decisions are matched by _decision_ts within sessions on or before the cut,
    and, when cut_ts_in is given, only those decided (end of the minute) at or before it: a perturbation changes the
    bars after the cut session's decision bar, so a minute decided after that moment may differ. Daily decisions are
    matched by session date. None when every compared decision matches.

    Args:
        full_decision_list_in, check_decision_list_in (list[dict]): Decisions
        full_session_list_in, check_session_list_in (list): Session dates aligned with the decisions (daily)
        cut_date_in (datetime.date): Last session compared (inclusive)
        cut_ts_in (datetime-like | None): Last minute-mode decision moment compared (None = the whole cut session)

    Returns:
        dict | None: session_date, full_decision, check_decision
    """
    # MINUTE MODE HAS MANY DECISIONS PER SESSION; MATCH ON THE BAR TIMESTAMP
    cut_day = get_date(cut_date_in)
    minute_bool = any(isinstance(decision_dict, dict) and decision_dict.get("_decision_ts") is not None
                      for decision_dict in list(full_decision_list_in)[:1])
    if minute_bool:
        check_ts_dict = {}
        for session_date, decision_dict in zip(check_session_list_in or [None] * len(check_decision_list_in),
                                               check_decision_list_in):
            session_day = get_recorded_session_date(decision_dict, session_date)
            if session_day is None or session_day > cut_day:
                continue
            check_ts_dict[str(decision_dict.get("_decision_ts"))] = get_decision_dict(decision_dict)
        for session_date, decision_dict in zip(full_session_list_in or [None] * len(full_decision_list_in),
                                               full_decision_list_in):
            session_day = get_recorded_session_date(decision_dict, session_date)
            if session_day is None:
                continue
            if session_day > cut_day:
                continue
            if cut_ts_in is not None and get_minute_bar_available_ts(decision_dict.get("_decision_ts")) > get_ny_timestamp(cut_ts_in):
                continue
            full_dict = get_decision_dict(decision_dict)
            ts_key_str = str(decision_dict.get("_decision_ts"))
            if ts_key_str not in check_ts_dict:
                return {"session_date": session_day, "full_decision": dict(full_dict), "check_decision": None,
                        "decision_ts": ts_key_str}
            check_dict_row = check_ts_dict[ts_key_str]
            if not get_decision_equal_bool(full_dict, check_dict_row):
                return {"session_date": session_day, "full_decision": dict(full_dict),
                        "check_decision": dict(check_dict_row), "decision_ts": ts_key_str}
        return None
    # DAILY: INDEX THE CHECK BY DATE
    check_dict = {get_date(session_date): get_decision_dict(decision_dict)
                  for session_date, decision_dict in zip(check_session_list_in, check_decision_list_in)}
    for session_date, decision_dict in zip(full_session_list_in, full_decision_list_in):
        session_day = get_date(session_date)
        if session_day > cut_day:
            break
        full_dict = get_decision_dict(decision_dict)
        if session_day not in check_dict:
            return {"session_date": session_day, "full_decision": dict(full_dict), "check_decision": None}
        check_dict_row = check_dict[session_day]
        if not get_decision_equal_bool(full_dict, check_dict_row):
            return {"session_date": session_day, "full_decision": dict(full_dict), "check_decision": dict(check_dict_row)}
    return None


# FUNCTION: ONE LOOK-AHEAD STREAM (NO TRIAL LOG, NO CHECKPOINT)
def run_lookahead_stream_dict(design_module_in, candidate_in, ohlcv_array_dict_in, date1_in, date2_in,
                              data_context_in, design_file_path_str_in):
    """
    A fresh DailyLoop through date2_in. Direct loader calls are blocked. Nothing is appended to the trial log.

    Args:
        design_module_in (module): Design
        candidate_in: Candidate
        ohlcv_array_dict_in (dict): Bars for this check
        date1_in, date2_in: Window bounds
        data_context_in (DataContext | None): Sources for this check
        design_file_path_str_in (str): Design file (already AST-checked on the full run)

    Returns:
        dict: Output of DailyLoop.get_result_dict
    """
    # A FRESH DESIGN AND ENGINE; THE FULL RUN'S CHECKPOINT IS NOT TOUCHED
    from so.runner.run import get_candidate_engine
    design = design_module_in.get_candidate_design(candidate_in)
    engine = get_candidate_engine(design_module_in)
    dead_band = float(getattr(design_module_in, "DEAD_BAND", 0.0))
    default_weight = 0.0 if get_design_mode_str(design_module_in) == MODE_MINUTE_STR else 1.0
    initial_weight = float(getattr(design_module_in, "INITIAL_WEIGHT", default_weight))
    loop = get_stream_loop(design, ohlcv_array_dict_in, date1_in, date2_in, data_context_in, engine, initial_weight,
                           dead_band, config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE,
                           config.MARKET_EXIT_SLIPPAGE_PER_SHARE, design_file_path_str_in, False, design_module_in)
    set_direct_read_blocked_bool(True)
    try:
        loop.run_through_date(date2_in)
    finally:
        set_direct_read_blocked_bool(False)
    return loop.get_result_dict()


# FUNCTION: ONE LOOK-AHEAD JOB (THE SPAWN TARGET)
def run_lookahead_job_dict(job_dict_in):
    """
    Loads the shared payload, builds the truncated or perturbed inputs, re-runs one candidate through the cut, and
    compares decisions. Does not write a trial row or a checkpoint.

    Args:
        job_dict_in (dict): Paths and scalars (no live objects)

    Returns:
        dict: candidate, cut_date, kind, pass_bool, first_fail_dict
    """
    # LOAD THE DESIGN FILE FIRST SO get_candidate_design IS THE SAME CLASS
    from so.runner.run import get_file_design_module, get_candidate_token_str
    from so.runner.preflight import check_design_file
    if job_dict_in.get("runs_root_str"):
        set_runs_root_str(job_dict_in["runs_root_str"])
    design_module = get_file_design_module(job_dict_in["design_file_path_str"])
    check_design_file(job_dict_in["design_file_path_str"])
    # THE SAME RUN'S FIT CACHE: A REFIT ON UNCHANGED ROWS (BEFORE THE CUT) IS NOT FITTED AGAIN
    from so.runner.checkpoint import get_run_folder_str
    from so.runner.minute import set_fit_cache_folder_str
    set_fit_cache_folder_str(os.path.join(get_run_folder_str(job_dict_in["run_id_str"]), "fit_cache"))
    candidate = job_dict_in["candidate"]
    cut_date = get_date(job_dict_in["cut_date"])
    kind_str = str(job_dict_in["kind_str"])
    ohlcv_array_dict = read_pickle(job_dict_in["ohlcv_path_str"])
    data_context = (read_pickle(job_dict_in["context_path_str"])
                    if get_file_exists_bool(job_dict_in["context_path_str"]) else None)
    date1 = get_date(job_dict_in["date1"])
    date2 = get_date(job_dict_in["date2"])
    cut_ts = None
    if kind_str == KIND_TRUNCATION_STR:
        check_ohlcv_dict = get_lookahead_truncated_ohlcv_dict(ohlcv_array_dict, cut_date)
        check_context = get_lookahead_truncated_context(data_context, ohlcv_array_dict, cut_date, check_ohlcv_dict)
        check_date2 = get_date(check_ohlcv_dict["session_date_list"][-1])
    elif kind_str == KIND_PERTURBATION_STR:
        check_ohlcv_dict = get_perturbed_ohlcv_dict(ohlcv_array_dict, cut_date)
        check_context = get_lookahead_perturbed_context(data_context, ohlcv_array_dict, cut_date, check_ohlcv_dict)
        # ONLY DECISIONS THROUGH THE CUT ARE COMPARED: STOP AT THE SESSION AFTER IT (THE CUT STILL HAS ITS DECISION)
        check_date2 = get_date(get_lookahead_truncated_ohlcv_dict(ohlcv_array_dict, cut_date)["session_date_list"][-1])
        # MINUTE MODE: THE CUT SESSION'S MINUTES AFTER ITS DECISION BAR SEE PERTURBED BARS AND ARE NOT COMPARED
        cut_ts = get_cut_clock_dict(ohlcv_array_dict, cut_date)["decision_ts"]
    else:
        raise ValueError(f"unknown look-ahead kind {kind_str!r}")
    result_dict = run_lookahead_stream_dict(design_module, candidate, check_ohlcv_dict, date1, check_date2,
                                            check_context, job_dict_in["design_file_path_str"])
    candidate_token_str = get_candidate_token_str(candidate)
    full_decision_list = read_decisions_list(job_dict_in["run_id_str"], candidate_token_str)
    if full_decision_list is None:
        raise ValueError(f"candidate {candidate!r} has no recorded decisions for the look-ahead check.")
    full_session_list = job_dict_in["full_session_list"]
    minute_bool = bool(full_decision_list) and isinstance(full_decision_list[0], dict) and full_decision_list[0].get("_session_date") is not None
    if not minute_bool and len(full_session_list) != len(full_decision_list):
        raise ValueError("recorded decisions and sessions have different lengths.")
    if minute_bool:
        full_session_list = [decision_dict.get("_session_date") for decision_dict in full_decision_list]
    first_fail_dict = get_first_decision_difference_dict(full_decision_list, full_session_list,
                                                         result_dict["decision_dict_list"],
                                                         result_dict["decision_session_list"], cut_date, cut_ts)
    pass_bool = first_fail_dict is None
    return {"candidate": candidate, "cut_date": cut_date, "kind_str": kind_str, "pass_bool": bool(pass_bool),
            "first_fail_dict": first_fail_dict, "seed_int": get_perturbation_seed_int(cut_date)}


# FUNCTION: RUN LOOK-AHEAD JOBS, SPAWNED OR IN-PROCESS
def run_lookahead_job_list(job_dict_list_in, n_jobs_int_in):
    """
    n_jobs 1 runs in this process. More than 1 uses spawn, up to MAX_CANDIDATE_PROCESS_COUNT.

    Args:
        job_dict_list_in (list[dict]): One job per candidate-cut-kind
        n_jobs_int_in (int): Requested process count

    Returns:
        list[dict]: Worker returns, in job-list order
    """
    # THE SAME CAP AS THE CANDIDATE STREAMS
    from so.runner.run import MAX_CANDIDATE_PROCESS_COUNT
    job_count = len(job_dict_list_in)
    if job_count == 0:
        return []
    n_jobs_int = max(1, min(int(n_jobs_int_in), MAX_CANDIDATE_PROCESS_COUNT, job_count))
    if n_jobs_int <= 1:
        return [run_lookahead_job_dict(job_dict) for job_dict in job_dict_list_in]
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=n_jobs_int) as pool:
        return pool.map(run_lookahead_job_dict, job_dict_list_in)


# FUNCTION: JSON-SAFE DECISION FOR THE FAILURE RECORD
def get_lookahead_decision_payload_dict(decision_dict_in):
    """
    Args:
        decision_dict_in (dict | None): A decision, or None when the check session is missing

    Returns:
        dict | None: JSON-safe decision
    """
    # MISSING IS RECORDED AS NULL
    if decision_dict_in is None:
        return None
    payload_dict = {}
    for key_str, value in dict(decision_dict_in).items():
        if isinstance(value, (float, np.floating)):
            payload_dict[key_str] = None if not np.isfinite(float(value)) else float(value)
        elif isinstance(value, (np.bool_,)):
            payload_dict[key_str] = bool(value)
        else:
            payload_dict[key_str] = value
    return payload_dict


# FUNCTION: THE FAILURE RECORD FOR LOOKAHEAD.JSON
def get_lookahead_fail_payload_dict(first_fail_dict_in, cut_date_in, kind_str_in):
    """
    Args:
        first_fail_dict_in (dict): session_date, full_decision, check_decision
        cut_date_in (datetime.date): Cut
        kind_str_in (str): truncation or perturbation

    Returns:
        dict: Record
    """
    # THE FIRST SESSION THAT DIFFERED, AND BOTH VALUES
    return {"cut_date": str(get_date(cut_date_in)), "kind_str": str(kind_str_in),
            "session_date": str(get_date(first_fail_dict_in["session_date"])),
            "full_decision": get_lookahead_decision_payload_dict(first_fail_dict_in.get("full_decision")),
            "check_decision": get_lookahead_decision_payload_dict(first_fail_dict_in.get("check_decision"))}


# FUNCTION: THE FULL LOOK-AHEAD CHECK AFTER THE CANDIDATE STREAMS
def run_lookahead_check_dict(design_module_in, ohlcv_array_dict_in, run_id_str_in, date1_in, date2_in,
                             candidate_list_in, window_session_date_list_in, n_jobs_int_in, design_file_path_str_in,
                             ohlcv_path_str_in, context_path_str_in, run_folder_str_in, runs_root_str_in=None):
    """
    Draws the cuts, runs truncation and perturbation jobs in parallel, writes lookahead.json, and returns the
    summary the verdict reads.

    Args:
        design_module_in (module): Design (unused besides existing; workers reload the file)
        ohlcv_array_dict_in (dict): Full bars
        run_id_str_in (str): Run id (recorded decisions live in the run folder)
        date1_in, date2_in: Span bounds
        candidate_list_in (list): Candidates in list order
        window_session_date_list_in (list): Sessions of the span
        n_jobs_int_in (int): Process count
        design_file_path_str_in, ohlcv_path_str_in, context_path_str_in, run_folder_str_in (str): Paths
        runs_root_str_in (str | None): Checkpoint root (None = development experiment zone)

    Returns:
        dict: pass_bool, status_str, cut_date_list, seed_int, candidate_dict, first_fail_dict, elapsed_seconds,
              path_str
    """
    # CUTS ARE A PROPERTY OF THE SPAN, NOT OF A CANDIDATE
    _ = design_module_in
    start_time = time.perf_counter()
    cut_date_list = get_lookahead_cut_date_list(window_session_date_list_in)
    seed_int = int(config.RUNNER_LOOKAHEAD_CUT_SEED)
    perturbation_seed_dict = {str(cut_date): get_perturbation_seed_int(cut_date) for cut_date in cut_date_list}
    session_str_list = [str(get_date(session_date)) for session_date in window_session_date_list_in]
    job_dict_list = []
    for candidate in candidate_list_in:
        for cut_date in cut_date_list:
            for kind_str in KIND_STR_LIST:
                job_dict_list.append({
                    "candidate": candidate, "cut_date": str(cut_date), "kind_str": kind_str,
                    "run_id_str": run_id_str_in, "design_file_path_str": design_file_path_str_in,
                    "ohlcv_path_str": ohlcv_path_str_in, "context_path_str": context_path_str_in,
                    "date1": str(get_date(date1_in)), "date2": str(get_date(date2_in)),
                    "full_session_list": list(session_str_list),
                    "runs_root_str": runs_root_str_in,
                })
    result_list = run_lookahead_job_list(job_dict_list, n_jobs_int_in)
    result_key_dict = {(row["candidate"], str(get_date(row["cut_date"])), row["kind_str"]): row for row in result_list}
    candidate_dict = {}
    overall_pass_bool = True
    overall_fail_dict = None
    for candidate in candidate_list_in:
        check_list = []
        candidate_pass_bool = True
        candidate_fail_dict = None
        for cut_date in cut_date_list:
            for kind_str in KIND_STR_LIST:
                row_dict = result_key_dict[(candidate, str(cut_date), kind_str)]
                row_fail_dict = None
                if not row_dict["pass_bool"]:
                    row_fail_dict = get_lookahead_fail_payload_dict(row_dict["first_fail_dict"], cut_date, kind_str)
                    candidate_pass_bool = False
                    if candidate_fail_dict is None:
                        candidate_fail_dict = row_fail_dict
                    overall_pass_bool = False
                    if overall_fail_dict is None:
                        overall_fail_dict = {"candidate": candidate, **row_fail_dict}
                check_list.append({"cut_date": str(cut_date), "kind_str": kind_str,
                                   "pass_bool": bool(row_dict["pass_bool"]),
                                   "seed_int": int(row_dict["seed_int"]),
                                   "first_fail_dict": row_fail_dict})
        candidate_dict[str(candidate)] = {"pass_bool": bool(candidate_pass_bool), "check_list": check_list,
                                          "first_fail_dict": candidate_fail_dict}
    elapsed_seconds = float(time.perf_counter() - start_time)
    status_str = LOOK_AHEAD_PASS_STR if overall_pass_bool else LOOK_AHEAD_FAIL_STR
    payload_dict = {"cut_date_list": [str(cut_date) for cut_date in cut_date_list],
                    "cut_count_int": int(len(cut_date_list)), "cut_seed_int": seed_int,
                    "perturbation_seed_dict": perturbation_seed_dict, "candidate_dict": candidate_dict,
                    "pass_bool": bool(overall_pass_bool), "status_str": status_str,
                    "first_fail_dict": overall_fail_dict, "elapsed_seconds": elapsed_seconds}
    path_str = write_lookahead_json(run_folder_str_in, payload_dict)
    payload_dict["path_str"] = path_str
    return payload_dict


# FUNCTION: WRITE lookahead.json IN THE RUN FOLDER
def write_lookahead_json(run_folder_str_in, payload_dict_in):
    """
    Args:
        run_folder_str_in (str): Run folder
        payload_dict_in (dict): Payload

    Returns:
        str: Path
    """
    # THE SAME JSON WRITER THE REPORT USES
    path_str = os.path.join(run_folder_str_in, LOOKAHEAD_FILE_STR)
    write_json_file(path_str, payload_dict_in)
    return path_str
