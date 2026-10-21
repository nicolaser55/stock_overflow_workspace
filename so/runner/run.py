import hashlib
import importlib.util
import multiprocessing
import os
import subprocess
import sys
from datetime import datetime
from urllib.parse import quote
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL)
from so import config, paths
# IMPORT THE TRIAL LOG
from so.core.trial_log import log_trial_dict
from so.core.point_in_time import set_direct_read_blocked_bool
from so.core.reentry_simulation import get_window_session_idx_arr
from so.core.holdout import check_development_view
# IMPORT THE 4A LOOP, PERIODS, SELECTION AND CHECKPOINTS
from so.runner.engine import FractionalWeightEngine
from so.runner.loop import DailyLoop
from so.runner.preflight import (check_design_file, get_design_follow_path_list, get_experiments_package_folder_str)
from so.runner.periods import (check_quarantine_refused, get_development_run_period_pdf, get_period_date)
from so.runner.selection import (get_buy_hold_period_return_dict, get_stream_period_score_dict,
                                 get_runner_selection_pdf, get_governing_candidate_dict,
                                 run_prior_only_from_decisions_dict)
from so.runner.checkpoint import (get_run_folder_str, make_folder, write_pickle, read_pickle, get_file_exists_bool,
                                  write_checkpoint_dict, read_checkpoint_dict, write_decisions_list, read_decisions_list,
                                  write_score_row_list, read_score_row_list, write_done_marker, get_done_bool,
                                  write_run_identity_dict, read_run_identity_dict)
from so.runner.baselines import get_runner_baseline_dict
from so.runner.verdict import (get_equity_daily_return_pdf, get_runner_verdict_dict, get_report_payload_dict,
                               write_run_report_dict, write_run_manifest_dict, get_view_stamp_dict, LOOK_AHEAD_PENDING_STR,
                               REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR, MANIFEST_FILE_STR)

"""
Development Run (infrastructure steps 4b-1a and 4b-1b)

Candidates, periods, pooled prior-only selection, trial logging, checkpoints and parallel streams on top of the 4a
daily loop. 4b-1b adds baselines over the prior-only span, the shared verdict, report.json / report.md, and
manifest.json written last. Development view only: the quarantine root is refused (holdout evaluation is 4b-1c).

The design module declares CANDIDATE_LIST and get_candidate_design(candidate), which returns a fresh design object
per candidate. Each candidate is its own stream over the span (first period start through last period end). At the
end of each period the stream is scored (period return and buy-and-hold for the same period), one trial row is
appended, then the design and the engine are pickled. A crash resumes from that pickle.

Candidates run in separate processes, up to 8, with the spawn start method. There is no shared mutable state. A
single-process run is the same code path as n_jobs=1.

Trial ids are stable: run id + candidate + period. A resumed run never writes the same trial twice. Each row carries
the git commit and a hash of the design folder.

A run refuses uncommitted changes in the code it uses (so/, the design folder, and every experiments/ folder the
preflight already walks), a missing or stale VIEW.json, and the quarantine root. Each checkpoint stores the commit
and the code hash of those same folders. A resume with a different commit or hash raises: start a new run id.
"""

# CANDIDATES RUN IN AT MOST THIS MANY PROCESSES
MAX_CANDIDATE_PROCESS_COUNT = 8
# A RESUME WHOSE CODE IS NOT THE CODE THAT WROTE THE CHECKPOINT
RESUME_IDENTITY_MESSAGE_STR = ("this run's checkpoint was written by a different commit or code hash; "
                               "start a new run id")
# UNCOMMITTED CHANGES IN THE CODE THIS RUN USES
CLEAN_TREE_MESSAGE_STR = ("uncommitted changes in the code this run uses; "
                          "commit them or start a new run id")
# SHARED PAYLOAD INSIDE THE RUN FOLDER
OHLCV_FILE_STR = "ohlcv.pkl"
PERIOD_FILE_STR = "period.pkl"
BUY_HOLD_FILE_STR = "buy_hold.pkl"
CONTEXT_FILE_STR = "data_context.pkl"


# FUNCTION: A FILESYSTEM-SAFE CANDIDATE TOKEN
def get_candidate_token_str(candidate_in):
    """
    Percent-encodes the candidate name so a path and a trial id stay unique.

    Args:
        candidate_in: Candidate (usually a str)

    Returns:
        str: Token
    """
    # QUOTE EVERY CHARACTER THAT IS NOT UNRESERVED
    return quote(str(candidate_in), safe="")


# FUNCTION: THE STABLE TRIAL ID
def get_trial_id_str(run_id_str_in, candidate_in, period_id_in):
    """
    run id + candidate + period. A resumed run rebuilds the same string.

    Args:
        run_id_str_in (str): Run id
        candidate_in: Candidate
        period_id_in (int): Period id

    Returns:
        str: Trial id
    """
    # THREE FIELDS, PERCENT-ENCODED CANDIDATE
    return f"{run_id_str_in}__{get_candidate_token_str(candidate_in)}__{int(period_id_in)}"


# FUNCTION: SHA256 OF THE DESIGN FOLDER'S FILES
def get_design_folder_hash_str(folder_path_str_in):
    """
    Sorted relative paths and file bytes, skipping __pycache__ and .pyc. The hash changes when a design file changes.

    Args:
        folder_path_str_in (str): Design folder

    Returns:
        str: Hex digest
    """
    # EVERY FILE UNDER THE FOLDER, IN PATH ORDER
    hasher = hashlib.sha256()
    folder_str = os.path.abspath(folder_path_str_in)
    path_list = []
    for dir_str, dir_name_list, file_name_list in os.walk(folder_str):
        dir_name_list[:] = sorted(name_str for name_str in dir_name_list if name_str != "__pycache__")
        for file_name_str in sorted(file_name_list):
            if file_name_str.endswith(".pyc"):
                continue
            path_list.append(os.path.join(dir_str, file_name_str))
    for file_path_str in path_list:
        rel_str = os.path.relpath(file_path_str, folder_str).replace("\\", "/")
        hasher.update(rel_str.encode("utf-8"))
        hasher.update(b"\0")
        with open(file_path_str, "rb") as file_obj:
            hasher.update(file_obj.read())
    return hasher.hexdigest()


# FUNCTION: GIT HEAD OF THE WORKSPACE
def get_git_head_str():
    """
    git rev-parse HEAD. "unknown" when git is missing.

    Args:
        None

    Returns:
        str: Commit hash, or "unknown"
    """
    # THE WORKSPACE ROOT, NOT THE DATA FOLDER
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=paths.WORKSPACE_PATH_STR, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# FUNCTION: FOLDERS THE CLEAN-TREE CHECK AND THE CODE HASH COVER
def get_guarded_code_folder_list(design_folder_str_in, design_file_path_str_in=None):
    """
    so/, the design folder, and every experiments/ package folder the preflight already walks from the design file.

    Args:
        design_folder_str_in (str): Design folder
        design_file_path_str_in (str | None): Design file (None = so/ and the design folder only)

    Returns:
        list[str]: Absolute folder paths, sorted uniquely
    """
    # ALWAYS so/ AND THE DESIGN FOLDER
    folder_set = {os.path.abspath(os.path.join(paths.WORKSPACE_PATH_STR, "so")),
                  os.path.abspath(design_folder_str_in)}
    if design_file_path_str_in:
        for path_str in get_design_follow_path_list(design_file_path_str_in):
            package_str = get_experiments_package_folder_str(path_str)
            if package_str is not None:
                folder_set.add(os.path.abspath(package_str))
    return sorted(folder_set)


# FUNCTION: SHA256 OF THE CODE THIS RUN USES
def get_code_hash_str(design_folder_str_in, design_file_path_str_in=None):
    """
    Content hash of so/, the design folder, and every imported experiments/ package folder, skipping __pycache__
    and .pyc. A change in any of those trees changes it.

    Args:
        design_folder_str_in (str): Design folder
        design_file_path_str_in (str | None): Design file (None = so/ and the design folder only)

    Returns:
        str: Hex digest
    """
    # FOLDER RELATIVE PATHS PLUS CONTENT HASHES, IN PATH ORDER
    hasher = hashlib.sha256()
    for folder_str in get_guarded_code_folder_list(design_folder_str_in, design_file_path_str_in):
        rel_str = os.path.relpath(folder_str, paths.WORKSPACE_PATH_STR).replace("\\", "/")
        hasher.update(rel_str.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(get_design_folder_hash_str(folder_str).encode("utf-8"))
        hasher.update(b"\0")
    return hasher.hexdigest()


# FUNCTION: PATHS FROM git status --porcelain
def get_porcelain_path_list(porcelain_str_in):
    """
    Args:
        porcelain_str_in (str): Output of git status --porcelain

    Returns:
        list[str]: Workspace-relative paths (forward slashes)
    """
    # XY PLUS A SPACE, THEN THE PATH; A RENAME HAS " -> "
    path_list = []
    for line_str in porcelain_str_in.splitlines():
        if len(line_str) < 4:
            continue
        rest_str = line_str[3:]
        part_list = rest_str.split(" -> ", 1) if " -> " in rest_str else [rest_str]
        for part_str in part_list:
            path_str = part_str.strip()
            if path_str.startswith('"') and path_str.endswith('"') and len(path_str) >= 2:
                path_str = path_str[1:-1]
            path_list.append(path_str.replace("\\", "/"))
    return path_list


# FUNCTION: WHETHER A PATH SITS IN A FOLDER
def get_path_in_folder_bool(path_str_in, folder_str_in):
    """
    Args:
        path_str_in (str): Workspace-relative path
        folder_str_in (str): Workspace-relative folder (no trailing slash)

    Returns:
        bool: True if the path is the folder or a file under it
    """
    # PREFIX MATCH ON FORWARD SLASHES
    path_str = path_str_in.replace("\\", "/").lstrip("./")
    folder_str = folder_str_in.replace("\\", "/").strip("/")
    if folder_str == "":
        return False
    return path_str == folder_str or path_str.startswith(folder_str + "/")


# FUNCTION: REFUSE UNCOMMITTED CHANGES IN THE CODE THIS RUN USES
def check_clean_tree(design_folder_str_in, porcelain_str_in=None, design_file_path_str_in=None):
    """
    git status --porcelain. Untracked files outside so/, the design folder, and imported experiments/ folders are
    allowed.

    Args:
        design_folder_str_in (str): Absolute or workspace-relative design folder
        porcelain_str_in (str | None): Injected status text (None = run git)
        design_file_path_str_in (str | None): Design file whose experiments/ imports are also guarded

    Returns:
        None
    """
    # READ THE STATUS FROM THE WORKSPACE ROOT
    if porcelain_str_in is None:
        try:
            porcelain_str = subprocess.check_output(["git", "status", "--porcelain"], cwd=paths.WORKSPACE_PATH_STR,
                                                    text=True)
        except (OSError, subprocess.CalledProcessError) as error:
            raise RuntimeError(f"could not read git status for the clean-tree guard: {error}") from error
    else:
        porcelain_str = porcelain_str_in
    rel_folder_list = []
    for folder_str in get_guarded_code_folder_list(design_folder_str_in, design_file_path_str_in):
        rel_folder_list.append(os.path.relpath(folder_str, paths.WORKSPACE_PATH_STR).replace("\\", "/"))
    offender_list = []
    for path_str in get_porcelain_path_list(porcelain_str):
        if any(get_path_in_folder_bool(path_str, folder_str) for folder_str in rel_folder_list):
            offender_list.append(path_str)
    if offender_list:
        raise RuntimeError(f"{CLEAN_TREE_MESSAGE_STR}: {', '.join(offender_list)}")


# FUNCTION: REFUSE A CHECKPOINT FROM A DIFFERENT COMMIT OR CODE HASH
def check_resume_identity(stored_dict_in, commit_str_in, code_hash_str_in):
    """
    Args:
        stored_dict_in (dict): Stored commit_str and code_hash_str
        commit_str_in (str): Current commit
        code_hash_str_in (str): Current code hash

    Returns:
        None
    """
    # MISSING KEYS ARE A MISMATCH (AN OLDER CHECKPOINT IS NOT THIS CODE)
    if (str(stored_dict_in.get("commit_str")) != str(commit_str_in)
            or str(stored_dict_in.get("code_hash_str")) != str(code_hash_str_in)):
        raise RuntimeError(RESUME_IDENTITY_MESSAGE_STR)


# FUNCTION: LOAD A DESIGN FILE INTO A NAMED MODULE
def get_file_design_module(file_path_str_in):
    """
    Executes the file into sys.modules under a stable name so a pickled design class can be found on resume.

    Args:
        file_path_str_in (str): Path of design.py

    Returns:
        module: The loaded module
    """
    # THE NAME IS A HASH OF THE PATH SO TWO DESIGNS DO NOT COLLIDE
    abs_path_str = os.path.abspath(file_path_str_in)
    module_name_str = "so_runner_design_" + hashlib.md5(abs_path_str.encode("utf-8")).hexdigest()
    if module_name_str in sys.modules:
        return sys.modules[module_name_str]
    spec = importlib.util.spec_from_file_location(module_name_str, abs_path_str)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name_str] = module
    spec.loader.exec_module(module)
    return module


# FUNCTION: THE DESIGN FILE OF A MODULE
def get_module_file_path_str(design_module_in):
    """
    Args:
        design_module_in (module): Design

    Returns:
        str: Path
    """
    # A MODULE WITH NO FILE CANNOT BE SPAWNED
    file_path_str = getattr(design_module_in, "__file__", None)
    if not file_path_str or not os.path.isfile(file_path_str):
        raise ValueError("the design module has no file; the runner loads a design.py.")
    return os.path.abspath(file_path_str)


# FUNCTION: A DEFAULT ENGINE FOR ONE CANDIDATE
def get_candidate_engine(design_module_in):
    """
    FractionalWeightEngine with the design's DEAD_BAND (default 0) and the shared costs.

    Args:
        design_module_in (module): Design

    Returns:
        FractionalWeightEngine: Fresh engine
    """
    # OPTIONAL CONSTANTS, SHARED COSTS
    dead_band = float(getattr(design_module_in, "DEAD_BAND", 0.0))
    return FractionalWeightEngine(dead_band, config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE,
                                  config.MARKET_EXIT_SLIPPAGE_PER_SHARE)


# FUNCTION: APPEND ONE CANDIDATE-PERIOD TRIAL
def log_candidate_period_trial_dict(design_module_in, run_id_str_in, candidate_in, period_row_in, score_dict_in,
                                    commit_str_in, design_folder_hash_str_in, trial_log_path_str_in):
    """
    One row, as soon as the period is scored, before any summary. A stable id that is already present is skipped.

    Args:
        design_module_in (module): Design (EXPERIMENT_NAME, PROTOCOL_VERSION)
        run_id_str_in (str): Run id
        candidate_in: Candidate
        period_row_in (pd.Series | dict): Period
        score_dict_in (dict): total_return, buy_hold_total_return, excess_return
        commit_str_in (str): Git commit
        design_folder_hash_str_in (str): Hash of the design folder
        trial_log_path_str_in (str): Trial log CSV

    Returns:
        dict: The trial row
    """
    # THE ID IS STABLE ACROSS A RESUME
    period_id = int(period_row_in["period_id"] if not isinstance(period_row_in, dict) else period_row_in["period_id"])
    trial_id_str = get_trial_id_str(run_id_str_in, candidate_in, period_id)
    setting_dict = {"run_id": run_id_str_in, "candidate": candidate_in, "commit": commit_str_in,
                    "design_folder_hash": design_folder_hash_str_in}
    metric_dict = {"total_return": float(score_dict_in["total_return"]),
                   "buy_hold_total_return": float(score_dict_in["buy_hold_total_return"]),
                   "excess_return": float(score_dict_in["excess_return"])}
    fold_row = {"fold_id": period_id,
                "valid_start": get_period_date(period_row_in["period_start"] if not isinstance(period_row_in, dict) else period_row_in["period_start"]),
                "valid_end": get_period_date(period_row_in["period_end"] if not isinstance(period_row_in, dict) else period_row_in["period_end"])}
    return log_trial_dict(design_module_in, "validation", setting_dict, metric_dict, False, fold_row_in=fold_row,
                          file_path_str_in=trial_log_path_str_in, trial_id_str_in=trial_id_str)


# FUNCTION: ONE CANDIDATE STREAM (THE SPAWN TARGET)
def run_candidate_job_dict(job_dict_in):
    """
    Loads the shared payload from the run folder, streams one candidate, logs each period as it is scored, and
    checkpoints. No shared mutable state with other candidates.

    Args:
        job_dict_in (dict): Paths and scalars (no live objects)

    Returns:
        dict: candidate, score_row_list, decision_count
    """
    # LOAD THE DESIGN FILE FIRST SO A PICKLED CLASS CAN BE FOUND
    design_module = get_file_design_module(job_dict_in["design_file_path_str"])
    check_design_file(job_dict_in["design_file_path_str"])
    candidate = job_dict_in["candidate"]
    candidate_token_str = get_candidate_token_str(candidate)
    run_id_str = job_dict_in["run_id_str"]
    ohlcv_array_dict = read_pickle(job_dict_in["ohlcv_path_str"])
    period_pdf = read_pickle(job_dict_in["period_path_str"])
    buy_hold_return_dict = read_pickle(job_dict_in["buy_hold_path_str"])
    data_context = read_pickle(job_dict_in["context_path_str"]) if get_file_exists_bool(job_dict_in["context_path_str"]) else None
    date1, date2 = job_dict_in["date1"], job_dict_in["date2"]
    dead_band = float(getattr(design_module, "DEAD_BAND", 0.0))
    initial_weight = float(getattr(design_module, "INITIAL_WEIGHT", 1.0))
    crash_after_period_id = job_dict_in.get("crash_after_period_id")
    commit_str = job_dict_in["commit_str"]
    code_hash_str = job_dict_in["code_hash_str"]
    checkpoint_dict = read_checkpoint_dict(run_id_str, candidate_token_str)
    if checkpoint_dict is not None:
        check_resume_identity(checkpoint_dict, commit_str, code_hash_str)
    # A FINISHED STREAM RETURNS THE SAVED SCORES AFTER THE IDENTITY CHECK
    if get_done_bool(run_id_str, candidate_token_str):
        return {"candidate": candidate, "score_row_list": read_score_row_list(run_id_str, candidate_token_str),
                "decision_count": len(read_decisions_list(run_id_str, candidate_token_str) or [])}
    if checkpoint_dict is None:
        design = design_module.get_candidate_design(candidate)
        engine = get_candidate_engine(design_module)
        loop = DailyLoop(design, ohlcv_array_dict, date1, date2, data_context, engine, initial_weight, dead_band,
                         config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                         job_dict_in["design_file_path_str"], check_source_bool_in=False)
        score_row_list = []
        completed_period_id_set = set()
    else:
        design = checkpoint_dict["design"]
        engine = checkpoint_dict["engine"]
        loop = DailyLoop(design, ohlcv_array_dict, date1, date2, data_context, engine, initial_weight, dead_band,
                         config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                         job_dict_in["design_file_path_str"], check_source_bool_in=False)
        loop.restore_progress(checkpoint_dict["next_session_pos"], checkpoint_dict["target_weight_list"],
                              checkpoint_dict["decision_session_list"], checkpoint_dict["decision_dict_list"])
        score_row_list = list(checkpoint_dict.get("score_row_list") or read_score_row_list(run_id_str, candidate_token_str))
        completed_period_id_set = {int(row["period_id"]) for row in score_row_list}
    # BLOCK DIRECT LOADER CALLS FOR THE WHOLE STREAM
    set_direct_read_blocked_bool(True)
    try:
        period_column_str_list = list(period_pdf.columns)
        for period_row in period_pdf.sort_values("period_id").itertuples(index=False):
            period_row_dict = {column_str: getattr(period_row, column_str) for column_str in period_column_str_list}
            period_id = int(period_row_dict["period_id"])
            if period_id in completed_period_id_set:
                continue
            loop.run_through_date(period_row_dict["period_end"])
            result_dict = loop.get_result_dict()
            score_dict = get_stream_period_score_dict(result_dict["daily_equity_pdf"], period_row_dict,
                                                      buy_hold_return_dict[period_id])
            score_dict["candidate"] = candidate
            score_dict["fold_id"] = period_id
            # THE TRIAL ROW IS WRITTEN BEFORE ANY SUMMARY AND BEFORE THE CHECKPOINT
            log_candidate_period_trial_dict(design_module, run_id_str, candidate, period_row_dict, score_dict,
                                            job_dict_in["commit_str"], job_dict_in["design_folder_hash_str"],
                                            job_dict_in["trial_log_path_str"])
            score_row_list.append(score_dict)
            completed_period_id_set.add(period_id)
            write_checkpoint_dict(run_id_str, candidate_token_str, {
                "design": loop.design, "engine": loop.engine, "next_session_pos": loop.next_session_pos_int,
                "target_weight_list": list(loop.target_weight_list),
                "decision_session_list": list(loop.decision_session_list),
                "decision_dict_list": list(loop.decision_dict_list), "period_id": period_id,
                "score_row_list": list(score_row_list),
                "commit_str": commit_str, "code_hash_str": code_hash_str,
            })
            write_decisions_list(run_id_str, candidate_token_str, loop.decision_dict_list)
            write_score_row_list(run_id_str, candidate_token_str, score_row_list)
            if crash_after_period_id is not None and int(period_id) == int(crash_after_period_id):
                raise RuntimeError(f"runner crash after period {period_id} checkpoint")
    finally:
        set_direct_read_blocked_bool(False)
    write_done_marker(run_id_str, candidate_token_str)
    return {"candidate": candidate, "score_row_list": score_row_list, "decision_count": len(loop.decision_dict_list)}


# FUNCTION: RUN CANDIDATE JOBS, SPAWNED OR IN-PROCESS
def run_candidate_job_list(job_dict_list_in, n_jobs_int_in):
    """
    n_jobs 1 runs in this process. More than 1 uses spawn, up to MAX_CANDIDATE_PROCESS_COUNT.

    Args:
        job_dict_list_in (list[dict]): One job per candidate
        n_jobs_int_in (int): Requested process count

    Returns:
        list[dict]: Worker returns, in candidate-list order
    """
    # ONE PROCESS PER CANDIDATE, CAPPED
    job_count = len(job_dict_list_in)
    n_jobs_int = max(1, min(int(n_jobs_int_in), MAX_CANDIDATE_PROCESS_COUNT, job_count))
    if n_jobs_int <= 1:
        return [run_candidate_job_dict(job_dict) for job_dict in job_dict_list_in]
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=n_jobs_int) as pool:
        return pool.map(run_candidate_job_dict, job_dict_list_in)


# FUNCTION: A DEVELOPMENT RUN OF EVERY CANDIDATE
def run_development_dict(design_module_in, ohlcv_array_dict_in, data_context_in=None, run_id_str_in=None,
                         n_jobs_int_in=None, period_pdf_in=None, trial_log_path_str_in=None, commit_str_in=None,
                         crash_after_period_id_in=None, code_hash_str_in=None, check_clean_tree_bool_in=True,
                         check_view_bool_in=True, baseline_seed_count_int_in=None,
                         look_ahead_status_str_in=LOOK_AHEAD_PENDING_STR):
    """
    Development view. Refuses the quarantine root. Forms periods from PERIOD_RULE unless period_pdf_in is passed
    (tests). Streams each candidate, logs each candidate-period as it is scored, then builds the prior-only path
    from the recorded decisions. After a finished path it runs the shared baselines, applies the verdict, writes
    report.json and report.md, and writes manifest.json last.

    Args:
        design_module_in (module): Design (CANDIDATE_LIST, get_candidate_design, PERIOD_RULE, SELECTION_RULE)
        ohlcv_array_dict_in (dict): Bars through the development end
        data_context_in (DataContext | None): Loaded sources
        run_id_str_in (str | None): Resume key (None = experiment name plus timestamp)
        n_jobs_int_in (int | None): Process count (None = min(8, candidate count); 1 is in-process)
        period_pdf_in (pd.DataFrame | None): Injected periods (None = PERIOD_RULE)
        trial_log_path_str_in (str | None): Trial log CSV (None = the shared log)
        commit_str_in (str | None): Injected commit (None = git HEAD)
        crash_after_period_id_in (int | None): Test hook: raise after that period's checkpoint
        code_hash_str_in (str | None): Injected code hash (None = hash of the code this run uses)
        check_clean_tree_bool_in (bool): Refuse uncommitted changes in the code this run uses
        check_view_bool_in (bool): Call check_development_view (tests that inject periods may pass False)
        baseline_seed_count_int_in (int | None): Random-timing draws (None = RUNNER_RANDOM_TIMING_SEED_COUNT)
        look_ahead_status_str_in (str): pending until 4b-1c fills pass or fail

    Returns:
        dict: run_id, period_pdf, score_pdf, selection_pdf, governing_dict, prior_only_dict, trial_id_list,
              baseline_dict, verdict_dict, report_dict, manifest_dict
    """
    # THE DEVELOPMENT VIEW NEVER OPENS THE QUARANTINE
    check_quarantine_refused()
    if not hasattr(design_module_in, "CANDIDATE_LIST"):
        raise ValueError("design module is missing CANDIDATE_LIST.")
    if not hasattr(design_module_in, "get_candidate_design"):
        raise ValueError("design module is missing get_candidate_design.")
    candidate_list = list(design_module_in.CANDIDATE_LIST)
    if len(candidate_list) == 0:
        raise ValueError("CANDIDATE_LIST is empty.")
    design_file_path_str = get_module_file_path_str(design_module_in)
    design_folder_str = os.path.dirname(design_file_path_str)
    if check_clean_tree_bool_in:
        check_clean_tree(design_folder_str, design_file_path_str_in=design_file_path_str)
    if check_view_bool_in:
        check_development_view()
    check_design_file(design_file_path_str)
    design_folder_hash_str = get_design_folder_hash_str(design_folder_str)
    commit_str = str(commit_str_in) if commit_str_in is not None else get_git_head_str()
    code_hash_str = (str(code_hash_str_in) if code_hash_str_in is not None
                     else get_code_hash_str(design_folder_str, design_file_path_str_in=design_file_path_str))
    period_pdf = period_pdf_in
    if period_pdf is None:
        period_pdf, _fold_pdf = get_development_run_period_pdf(design_module_in, ohlcv_array_dict_in["session_date_list"])
    else:
        period_pdf = period_pdf.copy()
    if period_pdf.empty:
        raise ValueError("no periods to run.")
    date1 = get_period_date(period_pdf.sort_values("period_id")["period_start"].iloc[0])
    date2 = get_period_date(period_pdf.sort_values("period_id")["period_end"].iloc[-1])
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1, date2)
    window_session_date_list = [ohlcv_array_dict_in["session_date_list"][int(session_idx)] for session_idx in window_session_idx_arr]
    buy_hold_return_dict = get_buy_hold_period_return_dict(ohlcv_array_dict_in, period_pdf, date1, date2)
    experiment_name_str = str(getattr(design_module_in, "EXPERIMENT_NAME", "runner"))
    run_id_str = str(run_id_str_in) if run_id_str_in else f"{experiment_name_str}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    run_folder_str = make_folder(get_run_folder_str(run_id_str))
    stored_identity_dict = read_run_identity_dict(run_id_str)
    if stored_identity_dict is not None:
        check_resume_identity(stored_identity_dict, commit_str, code_hash_str)
    else:
        write_run_identity_dict(run_id_str, {"commit_str": commit_str, "code_hash_str": code_hash_str})
    ohlcv_path_str = os.path.join(run_folder_str, OHLCV_FILE_STR)
    period_path_str = os.path.join(run_folder_str, PERIOD_FILE_STR)
    buy_hold_path_str = os.path.join(run_folder_str, BUY_HOLD_FILE_STR)
    context_path_str = os.path.join(run_folder_str, CONTEXT_FILE_STR)
    write_pickle(ohlcv_path_str, ohlcv_array_dict_in)
    write_pickle(period_path_str, period_pdf)
    write_pickle(buy_hold_path_str, buy_hold_return_dict)
    if data_context_in is not None:
        write_pickle(context_path_str, data_context_in)
    trial_log_path_str = trial_log_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    n_jobs_int = int(n_jobs_int_in) if n_jobs_int_in is not None else min(MAX_CANDIDATE_PROCESS_COUNT, len(candidate_list))
    job_dict_list = []
    for candidate in candidate_list:
        job_dict_list.append({
            "candidate": candidate, "run_id_str": run_id_str, "design_file_path_str": design_file_path_str,
            "ohlcv_path_str": ohlcv_path_str, "period_path_str": period_path_str, "buy_hold_path_str": buy_hold_path_str,
            "context_path_str": context_path_str, "date1": date1, "date2": date2,
            "commit_str": commit_str, "code_hash_str": code_hash_str, "design_folder_hash_str": design_folder_hash_str,
            "trial_log_path_str": trial_log_path_str, "crash_after_period_id": crash_after_period_id_in,
        })
    run_candidate_job_list(job_dict_list, n_jobs_int)
    score_row_list = []
    candidate_decision_dict = {}
    trial_id_list = []
    for candidate in candidate_list:
        candidate_token_str = get_candidate_token_str(candidate)
        score_row_list.extend(read_score_row_list(run_id_str, candidate_token_str))
        decision_list = read_decisions_list(run_id_str, candidate_token_str)
        if decision_list is None:
            raise ValueError(f"candidate {candidate!r} has no recorded decisions.")
        candidate_decision_dict[candidate] = decision_list
        for score_dict in read_score_row_list(run_id_str, candidate_token_str):
            trial_id_list.append(get_trial_id_str(run_id_str, candidate, score_dict["period_id"]))
    score_pdf = pd.DataFrame(score_row_list)
    selection_pdf = get_runner_selection_pdf(score_pdf, design_module_in)
    governing_dict = get_governing_candidate_dict(selection_pdf, period_pdf, candidate_list)
    dead_band = float(getattr(design_module_in, "DEAD_BAND", 0.0))
    initial_weight = float(getattr(design_module_in, "INITIAL_WEIGHT", 1.0))
    prior_only_dict = run_prior_only_from_decisions_dict(ohlcv_array_dict_in, date1, date2, window_session_date_list,
                                                         candidate_decision_dict, governing_dict, period_pdf, dead_band,
                                                         initial_weight)
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict_in, date1, date2, prior_only_dict,
                                             seed_count_int_in=baseline_seed_count_int_in)
    strategy_return_pdf = get_equity_daily_return_pdf(prior_only_dict["daily_equity_pdf"])
    buy_hold_return_pdf = get_equity_daily_return_pdf(baseline_dict["buy_hold_daily_equity_pdf"])
    verdict_dict = get_runner_verdict_dict(strategy_return_pdf, buy_hold_return_pdf, baseline_dict,
                                           look_ahead_status_str_in=look_ahead_status_str_in)
    view_stamp_dict = get_view_stamp_dict()
    report_dict = get_report_payload_dict(verdict_dict, {
        "run_id_str": run_id_str, "experiment_name_str": experiment_name_str,
        "protocol_version_str": str(getattr(design_module_in, "PROTOCOL_VERSION", "")),
        "commit_str": commit_str, "code_hash_str": code_hash_str, "view_stamp_dict": view_stamp_dict,
        "candidate_list": list(candidate_list), "trial_id_list": list(trial_id_list),
        "date1": str(date1), "date2": str(date2),
    })
    write_run_report_dict(run_folder_str, report_dict)
    manifest_dict = {"status": "finished", "run_id": run_id_str, "commit": commit_str, "code_hash": code_hash_str,
                     "view_stamp": view_stamp_dict,
                     "design": {"experiment_name": experiment_name_str,
                                "protocol_version": str(getattr(design_module_in, "PROTOCOL_VERSION", "")),
                                "file": design_file_path_str},
                     "candidate_list": list(candidate_list), "trial_id_list": list(trial_id_list),
                     "output_files": [REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR, MANIFEST_FILE_STR],
                     "verdict": {"email_worthy": bool(verdict_dict["email_worthy_bool"]),
                                 "label": verdict_dict["label_str"], "failed_list": list(verdict_dict["failed_list"])}}
    write_run_manifest_dict(run_folder_str, manifest_dict)
    return {"run_id_str": run_id_str, "period_pdf": period_pdf, "score_pdf": score_pdf, "selection_pdf": selection_pdf,
            "governing_dict": governing_dict, "prior_only_dict": prior_only_dict, "trial_id_list": trial_id_list,
            "date1": date1, "date2": date2, "window_session_date_list": window_session_date_list,
            "candidate_decision_dict": candidate_decision_dict, "commit_str": commit_str,
            "code_hash_str": code_hash_str, "design_folder_hash_str": design_folder_hash_str,
            "run_folder_str": run_folder_str, "baseline_dict": baseline_dict, "verdict_dict": verdict_dict,
            "report_dict": report_dict, "manifest_dict": manifest_dict}
