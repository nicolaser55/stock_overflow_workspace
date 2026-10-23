import hashlib
import importlib.util
import multiprocessing
import os
import subprocess
import sys
from datetime import datetime
from urllib.parse import quote
import json
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL)
from so import config, paths
# IMPORT THE TRIAL LOG
from so.core.trial_log import log_trial_dict
from so.core.point_in_time import (set_direct_read_blocked_bool, get_declared_source_name_list, get_source_spec_dict)
from so.core.reentry_simulation import get_window_session_idx_arr
from so.core.holdout import (check_development_view, check_evaluation_precondition_dict, get_holdout_period_pdf,
                             get_date, get_unread_report_dict, append_holdout_evaluation_dict, set_runner_active_bool,
                             UNREAD_SANITY_CHECK_STR)
from so.core.baseline_report import get_baseline_json_str
from so.core.continuous_replay import get_log_excess_bootstrap_dict
from so.core.evaluation import get_mde_float
# IMPORT THE 4A LOOP, PERIODS, SELECTION AND CHECKPOINTS
from so.runner.engine import (FractionalWeightEngine, TrailingStopEngine, BarrierEngine, ENGINE_FRACTIONAL_STR,
                              ENGINE_TRAILING_STOP_STR, ENGINE_BARRIER_STR)
from so.runner.loop import get_stream_loop, get_design_mode_str, MODE_MINUTE_STR
from so.runner.preflight import (check_design_file, get_design_follow_path_list, get_experiments_package_folder_str)
from so.runner.periods import (check_quarantine_refused, get_development_run_period_pdf, get_period_date)
from so.runner.selection import (get_buy_hold_period_return_dict, get_stream_period_score_dict,
                                 get_runner_selection_pdf, get_governing_candidate_dict,
                                 run_prior_only_from_decisions_dict)
from so.runner.checkpoint import (get_run_folder_str, make_folder, write_pickle, read_pickle, get_file_exists_bool,
                                  write_checkpoint_dict, read_checkpoint_dict, write_decisions_list, read_decisions_list,
                                  write_score_row_list, read_score_row_list, write_done_marker, get_done_bool,
                                  write_run_identity_dict, read_run_identity_dict, set_runs_root_str)
from so.runner.baselines import get_runner_baseline_dict
from so.runner.verdict import (get_equity_daily_return_pdf, get_runner_verdict_dict, get_report_payload_dict,
                               write_run_report_dict, write_run_manifest_dict, get_view_stamp_dict, get_json_value,
                               LOOK_AHEAD_PENDING_STR, LOOK_AHEAD_FAIL_STR, REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR,
                               MANIFEST_FILE_STR)
from so.runner.lookahead import run_lookahead_check_dict, LOOKAHEAD_FILE_STR

"""
Development And Holdout Runs (infrastructure steps 4b-1a, 4b-1b, 4b-1c and 4b-1d)

Candidates, periods, pooled prior-only selection, trial logging, checkpoints and parallel streams on top of the 4a
daily loop. 4b-1b adds baselines over the prior-only span, the shared verdict, report.json / report.md, and
manifest.json written last. 4b-1c fills the look-ahead part of the verdict: truncation and perturbation at sampled
cuts, run in the same spawn pool, written to lookahead.json. Those re-runs never write a trial-log row.

Development (run_development_dict) uses the development view: the quarantine root is refused. Holdout
(run_holdout_dict) is the same stream, selection, baseline, verdict and look-ahead, with the quarantine root and the
evaluation token. Periods are the development periods extended through the window (get_holdout_period_pdf). The run
starts at the development start so selection history and the carried position flow into the window; only window
sessions are reported. No candidate-period trial row is written for the development part. The ledger row and the
stage-"test" trial row are appended before report.json, report.md, the manifest, the daily paths or any printed
result. Progress during the stream does not print window returns.

The design module declares CANDIDATE_LIST and get_candidate_design(candidate), which returns a fresh design object
per candidate. Each candidate is its own stream over the span (first period start through last period end). At the
end of each period the stream is scored (period return and buy-and-hold for the same period). A development run
appends one trial row, then pickles the design and the engine. A crash resumes from that pickle.

Candidates run in separate processes, up to 8, with the spawn start method. There is no shared mutable state. A
single-process run is the same code path as n_jobs=1.

Trial ids are stable: run id + candidate + period. A resumed run never writes the same trial twice. Each row carries
the git commit and a hash of the design folder.

A development run refuses uncommitted changes in the code it uses (so/, the design folder, and every experiments/
folder the preflight already walks), a missing or stale VIEW.json, and the quarantine root. A holdout run reuses
so.core.holdout's token, git, once-only, forward-only and 10-evaluation rules. Each checkpoint stores the commit and
the code hash of those same folders. A resume with a different commit or hash raises: start a new run id.
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
    ENGINE_NAME selects fractional (default), trailing_stop or barrier. Shared costs. Optional MAX_CASH_SESSIONS,
    MAX_HOLD_TRADING_DAYS, RR_RATIO, DEAD_BAND.

    Args:
        design_module_in (module): Design

    Returns:
        Engine: Fresh engine
    """
    # OPTIONAL CONSTANTS, SHARED COSTS
    engine_name_str = str(getattr(design_module_in, "ENGINE_NAME", "") or "")
    if engine_name_str == "":
        engine_name_str = (ENGINE_BARRIER_STR if get_design_mode_str(design_module_in) == MODE_MINUTE_STR
                           else ENGINE_FRACTIONAL_STR)
    initial_capital = config.INITIAL_CAPITAL
    entry_slippage = config.ENTRY_SLIPPAGE_PER_SHARE
    market_exit_slippage = config.MARKET_EXIT_SLIPPAGE_PER_SHARE
    if engine_name_str == ENGINE_TRAILING_STOP_STR:
        max_cash_sessions = getattr(design_module_in, "MAX_CASH_SESSIONS", None)
        engine = TrailingStopEngine(max_cash_sessions, initial_capital, entry_slippage, market_exit_slippage)
        engine.set_stop_params(getattr(design_module_in, "TRAIL_MULTIPLE", None), getattr(design_module_in, "VOLATILITY", None))
        return engine
    if engine_name_str == ENGINE_BARRIER_STR:
        max_hold = int(getattr(design_module_in, "MAX_HOLD_TRADING_DAYS", config.MAX_HOLD_TRADING_DAYS))
        rr_ratio = float(getattr(design_module_in, "RR_RATIO", config.RR_RATIO))
        limit_exit_slippage = config.LIMIT_EXIT_SLIPPAGE_PER_SHARE
        return BarrierEngine(max_hold, rr_ratio, initial_capital, entry_slippage, market_exit_slippage,
                             limit_exit_slippage)
    if engine_name_str not in (ENGINE_FRACTIONAL_STR, ""):
        raise ValueError(f"unknown ENGINE_NAME {engine_name_str!r}")
    dead_band = float(getattr(design_module_in, "DEAD_BAND", 0.0))
    return FractionalWeightEngine(dead_band, initial_capital, entry_slippage, market_exit_slippage)


# FUNCTION: APPEND ONE CANDIDATE-PERIOD TRIAL
def log_candidate_period_trial_dict(design_module_in, run_id_str_in, candidate_in, period_row_in, score_dict_in,
                                    commit_str_in, design_folder_hash_str_in, trial_log_path_str_in, note_str_in=""):
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
        note_str_in (str): Free text on the trial row

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
                          note_str_in=str(note_str_in or ""), file_path_str_in=trial_log_path_str_in,
                          trial_id_str_in=trial_id_str)


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
    if job_dict_in.get("runs_root_str"):
        set_runs_root_str(job_dict_in["runs_root_str"])
    design_module = get_file_design_module(job_dict_in["design_file_path_str"])
    check_design_file(job_dict_in["design_file_path_str"])
    # MINUTE DESIGNS WITH A FIT KEY SHARE FITS THROUGH THE RUN FOLDER
    from so.runner.minute import set_fit_cache_folder_str
    set_fit_cache_folder_str(os.path.join(get_run_folder_str(job_dict_in["run_id_str"]), "fit_cache"))
    candidate = job_dict_in["candidate"]
    log_trial_bool = bool(job_dict_in.get("log_trial_bool", True))
    candidate_token_str = get_candidate_token_str(candidate)
    run_id_str = job_dict_in["run_id_str"]
    ohlcv_array_dict = read_pickle(job_dict_in["ohlcv_path_str"])
    period_pdf = read_pickle(job_dict_in["period_path_str"])
    buy_hold_return_dict = read_pickle(job_dict_in["buy_hold_path_str"])
    data_context = read_pickle(job_dict_in["context_path_str"]) if get_file_exists_bool(job_dict_in["context_path_str"]) else None
    date1, date2 = job_dict_in["date1"], job_dict_in["date2"]
    dead_band = float(getattr(design_module, "DEAD_BAND", 0.0))
    default_weight = 0.0 if get_design_mode_str(design_module) == MODE_MINUTE_STR else 1.0
    initial_weight = float(getattr(design_module, "INITIAL_WEIGHT", default_weight))
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
        loop = get_stream_loop(design, ohlcv_array_dict, date1, date2, data_context, engine, initial_weight, dead_band,
                               config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                               job_dict_in["design_file_path_str"], False, design_module)
        score_row_list = []
        completed_period_id_set = set()
    else:
        design = checkpoint_dict["design"]
        engine = checkpoint_dict["engine"]
        loop = get_stream_loop(design, ohlcv_array_dict, date1, date2, data_context, engine, initial_weight, dead_band,
                               config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                               job_dict_in["design_file_path_str"], False, design_module)
        loop.restore_progress(checkpoint_dict["next_session_pos"], checkpoint_dict["target_weight_list"],
                              checkpoint_dict["decision_session_list"], checkpoint_dict["decision_dict_list"])
        if hasattr(loop, "restore_checkpoint_extra"):
            loop.restore_checkpoint_extra(checkpoint_dict)
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
            # A DEVELOPMENT RUN WRITES THE TRIAL ROW BEFORE ANY SUMMARY AND BEFORE THE CHECKPOINT
            if log_trial_bool:
                log_candidate_period_trial_dict(design_module, run_id_str, candidate, period_row_dict, score_dict,
                                                job_dict_in["commit_str"], job_dict_in["design_folder_hash_str"],
                                                job_dict_in["trial_log_path_str"],
                                                note_str_in=job_dict_in.get("note_str_in", ""))
            score_row_list.append(score_dict)
            completed_period_id_set.add(period_id)
            checkpoint_payload_dict = {
                "design": loop.design, "engine": loop.engine, "next_session_pos": loop.next_session_pos_int,
                "target_weight_list": list(loop.target_weight_list),
                "decision_session_list": list(loop.decision_session_list),
                "decision_dict_list": list(loop.decision_dict_list), "period_id": period_id,
                "score_row_list": list(score_row_list),
                "commit_str": commit_str, "code_hash_str": code_hash_str,
            }
            if hasattr(loop, "get_checkpoint_extra_dict"):
                checkpoint_payload_dict.update(loop.get_checkpoint_extra_dict())
            write_checkpoint_dict(run_id_str, candidate_token_str, checkpoint_payload_dict)
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


# FUNCTION: STREAM EVERY CANDIDATE, SELECT, AND BUILD THE PRIOR-ONLY PATH
def run_candidate_streams_dict(design_module_in, ohlcv_array_dict_in, period_pdf_in, data_context_in=None,
                               run_id_str_in=None, n_jobs_int_in=None, trial_log_path_str_in=None, commit_str_in=None,
                               crash_after_period_id_in=None, code_hash_str_in=None, check_clean_tree_bool_in=True,
                               log_trial_bool_in=True, runs_root_str_in=None, note_str_in=""):
    """
    Shared stream used by a development run and a holdout run. Scores each candidate-period from the continuous
    stream, does pooled prior-only selection, and builds the prior-only path from the recorded decisions. A
    development run logs each candidate-period; a holdout run does not.

    Args:
        design_module_in (module): Design (CANDIDATE_LIST, get_candidate_design, SELECTION_RULE)
        ohlcv_array_dict_in (dict): Bars covering the periods
        period_pdf_in (pd.DataFrame): Periods already formed
        data_context_in (DataContext | None): Loaded sources
        run_id_str_in (str | None): Resume key (None = experiment name plus timestamp)
        n_jobs_int_in (int | None): Process count (None = min(8, candidate count); 1 is in-process)
        trial_log_path_str_in (str | None): Trial log CSV (None = the shared log)
        commit_str_in (str | None): Injected commit (None = git HEAD)
        crash_after_period_id_in (int | None): Test hook: raise after that period's checkpoint
        code_hash_str_in (str | None): Injected code hash (None = hash of the code this run uses)
        check_clean_tree_bool_in (bool): Refuse uncommitted changes in the code this run uses
        log_trial_bool_in (bool): Write a candidate-period trial row (False on a holdout run)
        runs_root_str_in (str | None): Checkpoint root (None = development experiment zone)
        note_str_in (str): Free text copied onto each candidate-period trial row

    Returns:
        dict: run_id, period_pdf, score_pdf, selection_pdf, governing_dict, prior_only_dict, trial_id_list,
              candidate_decision_dict, paths used by the look-ahead check
    """
    # THE SAME GUARDS THE DEVELOPMENT RUN ALREADY HAD, MINUS THE VIEW AND THE QUARANTINE
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
    check_design_file(design_file_path_str)
    design_folder_hash_str = get_design_folder_hash_str(design_folder_str)
    commit_str = str(commit_str_in) if commit_str_in is not None else get_git_head_str()
    code_hash_str = (str(code_hash_str_in) if code_hash_str_in is not None
                     else get_code_hash_str(design_folder_str, design_file_path_str_in=design_file_path_str))
    period_pdf = period_pdf_in.copy()
    if period_pdf.empty:
        raise ValueError("no periods to run.")
    date1 = get_period_date(period_pdf.sort_values("period_id")["period_start"].iloc[0])
    date2 = get_period_date(period_pdf.sort_values("period_id")["period_end"].iloc[-1])
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1, date2)
    window_session_date_list = [ohlcv_array_dict_in["session_date_list"][int(session_idx)] for session_idx in window_session_idx_arr]
    buy_hold_return_dict = get_buy_hold_period_return_dict(ohlcv_array_dict_in, period_pdf, date1, date2)
    experiment_name_str = str(getattr(design_module_in, "EXPERIMENT_NAME", "runner"))
    run_id_str = str(run_id_str_in) if run_id_str_in else f"{experiment_name_str}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    if runs_root_str_in is not None:
        set_runs_root_str(runs_root_str_in)
    try:
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
                "log_trial_bool": bool(log_trial_bool_in), "runs_root_str": runs_root_str_in,
                "note_str_in": str(note_str_in or ""),
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
            if log_trial_bool_in:
                for score_dict in read_score_row_list(run_id_str, candidate_token_str):
                    trial_id_list.append(get_trial_id_str(run_id_str, candidate, score_dict["period_id"]))
        score_pdf = pd.DataFrame(score_row_list)
        selection_pdf = get_runner_selection_pdf(score_pdf, design_module_in)
        governing_dict = get_governing_candidate_dict(selection_pdf, period_pdf, candidate_list)
        dead_band = float(getattr(design_module_in, "DEAD_BAND", 0.0))
        default_weight = 0.0 if get_design_mode_str(design_module_in) == MODE_MINUTE_STR else 1.0
        initial_weight = float(getattr(design_module_in, "INITIAL_WEIGHT", default_weight))
        prior_only_dict = run_prior_only_from_decisions_dict(ohlcv_array_dict_in, date1, date2, window_session_date_list,
                                                             candidate_decision_dict, governing_dict, period_pdf, dead_band,
                                                             initial_weight, engine_in=get_candidate_engine(design_module_in),
                                                             design_module_in=design_module_in)
        return {"run_id_str": run_id_str, "period_pdf": period_pdf, "score_pdf": score_pdf, "selection_pdf": selection_pdf,
                "governing_dict": governing_dict, "prior_only_dict": prior_only_dict, "trial_id_list": trial_id_list,
                "date1": date1, "date2": date2, "window_session_date_list": window_session_date_list,
                "candidate_decision_dict": candidate_decision_dict, "commit_str": commit_str,
                "code_hash_str": code_hash_str, "design_folder_hash_str": design_folder_hash_str,
                "run_folder_str": run_folder_str, "design_file_path_str": design_file_path_str,
                "ohlcv_path_str": ohlcv_path_str, "context_path_str": context_path_str,
                "candidate_list": list(candidate_list), "n_jobs_int": n_jobs_int,
                "experiment_name_str": experiment_name_str, "runs_root_str": runs_root_str_in}
    finally:
        # RESTORE THE DEVELOPMENT RUNS ROOT EVEN WHEN A WORKER RAISES
        if runs_root_str_in is not None:
            set_runs_root_str(None)


# FUNCTION: BASELINES, LOOK-AHEAD, VERDICT, REPORT AND MANIFEST
def write_runner_finish_dict(design_module_in, ohlcv_array_dict_in, stream_dict_in, prior_only_dict_in, date1_in,
                             date2_in, baseline_seed_count_int_in=None, look_ahead_status_str_in=LOOK_AHEAD_PENDING_STR,
                             run_lookahead_bool_in=True, extra_report_dict_in=None, extra_manifest_dict_in=None,
                             write_files_bool_in=True):
    """
    The shared tail of a development run and a holdout run. Look-ahead re-runs the full stream (stream_dict_in
    dates). Baselines and the verdict use prior_only_dict_in over date1_in..date2_in (the reported span).

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Bars
        stream_dict_in (dict): Output of run_candidate_streams_dict
        prior_only_dict_in (dict): Path the verdict sees (full span, or the rebased window slice)
        date1_in, date2_in: Reported span
        baseline_seed_count_int_in (int | None): Random-timing draws
        look_ahead_status_str_in (str): Used only when run_lookahead_bool_in is False
        run_lookahead_bool_in (bool): Run the automatic look-ahead check
        extra_report_dict_in, extra_manifest_dict_in (dict | None): Fields folded into the report and the manifest
        write_files_bool_in (bool): Write report.json, report.md and the manifest. Holdout leaves this False
            until the ledger row and the stage-test trial are appended.

    Returns:
        dict: baseline_dict, verdict_dict, report_dict, manifest_dict, lookahead_dict
    """
    # LOOK-AHEAD WALKS THE FULL STREAM; BASELINES AND THE VERDICT SEE THE REPORTED PATH
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict_in, date1_in, date2_in, prior_only_dict_in,
                                             seed_count_int_in=baseline_seed_count_int_in)
    lookahead_dict = None
    look_ahead_status_str = look_ahead_status_str_in
    if run_lookahead_bool_in:
        lookahead_dict = run_lookahead_check_dict(
            design_module_in, ohlcv_array_dict_in, stream_dict_in["run_id_str"], stream_dict_in["date1"],
            stream_dict_in["date2"], stream_dict_in["candidate_list"], stream_dict_in["window_session_date_list"],
            stream_dict_in["n_jobs_int"], stream_dict_in["design_file_path_str"], stream_dict_in["ohlcv_path_str"],
            stream_dict_in["context_path_str"], stream_dict_in["run_folder_str"],
            runs_root_str_in=stream_dict_in.get("runs_root_str"))
        look_ahead_status_str = lookahead_dict["status_str"]
    strategy_return_pdf = get_equity_daily_return_pdf(prior_only_dict_in["daily_equity_pdf"])
    buy_hold_return_pdf = get_equity_daily_return_pdf(baseline_dict["buy_hold_daily_equity_pdf"])
    verdict_dict = get_runner_verdict_dict(strategy_return_pdf, buy_hold_return_pdf, baseline_dict,
                                           look_ahead_status_str_in=look_ahead_status_str)
    if lookahead_dict is not None:
        verdict_dict["look_ahead_dict"]["cut_date_list"] = list(lookahead_dict["cut_date_list"])
        verdict_dict["look_ahead_dict"]["first_fail_dict"] = lookahead_dict.get("first_fail_dict")
        verdict_dict["look_ahead_dict"]["elapsed_seconds"] = lookahead_dict.get("elapsed_seconds")
    extra_report_dict = dict(extra_report_dict_in or {})
    view_stamp_dict = extra_report_dict.pop("view_stamp_dict", get_view_stamp_dict())
    report_dict = get_report_payload_dict(verdict_dict, {
        "run_id_str": stream_dict_in["run_id_str"], "experiment_name_str": stream_dict_in["experiment_name_str"],
        "protocol_version_str": str(getattr(design_module_in, "PROTOCOL_VERSION", "")),
        "commit_str": stream_dict_in["commit_str"], "code_hash_str": stream_dict_in["code_hash_str"],
        "view_stamp_dict": view_stamp_dict, "candidate_list": list(stream_dict_in["candidate_list"]),
        "trial_id_list": list(stream_dict_in["trial_id_list"]), "date1": str(date1_in), "date2": str(date2_in),
        **extra_report_dict,
    })
    output_file_list = [REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR, MANIFEST_FILE_STR]
    if lookahead_dict is not None:
        output_file_list = [REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR, LOOKAHEAD_FILE_STR, MANIFEST_FILE_STR]
    manifest_dict = {"status": "finished", "run_id": stream_dict_in["run_id_str"],
                     "commit": stream_dict_in["commit_str"], "code_hash": stream_dict_in["code_hash_str"],
                     "view_stamp": view_stamp_dict,
                     "design": {"experiment_name": stream_dict_in["experiment_name_str"],
                                "protocol_version": str(getattr(design_module_in, "PROTOCOL_VERSION", "")),
                                "file": stream_dict_in["design_file_path_str"]},
                     "candidate_list": list(stream_dict_in["candidate_list"]),
                     "trial_id_list": list(stream_dict_in["trial_id_list"]),
                     "output_files": list(output_file_list),
                     "verdict": {"email_worthy": bool(verdict_dict["email_worthy_bool"]),
                                 "label": verdict_dict["label_str"], "failed_list": list(verdict_dict["failed_list"]),
                                 "look_ahead": look_ahead_status_str}}
    if extra_manifest_dict_in:
        manifest_dict.update(dict(extra_manifest_dict_in))
    finish_dict = {"baseline_dict": baseline_dict, "verdict_dict": verdict_dict, "report_dict": report_dict,
                   "manifest_dict": manifest_dict, "lookahead_dict": lookahead_dict}
    if write_files_bool_in:
        write_runner_result_files_dict(stream_dict_in, finish_dict)
    return finish_dict


# FUNCTION: WRITE THE RUNNER RESULT FILES (REPORT, THEN MANIFEST LAST)
def write_runner_result_files_dict(stream_dict_in, finish_dict_in, reported_path_dict_in=None):
    """
    Daily paths when reported_path_dict_in is passed, then report.json and report.md, then the manifest. A holdout
    run calls this only after the ledger row and the stage-test trial are appended. Development writes through this
    with no daily paths.

    Args:
        stream_dict_in (dict): Output of run_candidate_streams_dict
        finish_dict_in (dict): Output of write_runner_finish_dict
        reported_path_dict_in (dict | None): Rebased window path; None skips the daily CSVs

    Returns:
        None
    """
    # DAILY PATHS FIRST WHEN THIS IS A COUNTED HOLDOUT RESULT
    if reported_path_dict_in is not None:
        output_path_str = stream_dict_in["run_folder_str"]
        os.makedirs(output_path_str, exist_ok=True)
        reported_path_dict_in["daily_equity_pdf"].to_csv(os.path.join(output_path_str, "strategy_daily_equity.csv"),
                                                        index=False)
        finish_dict_in["baseline_dict"]["buy_hold_daily_equity_pdf"].to_csv(
            os.path.join(output_path_str, "buy_hold_daily_equity.csv"), index=False)
    # REPORT BEFORE THE MANIFEST; A CRASH HERE STILL LEAVES THE LEDGER ROW
    write_run_report_dict(stream_dict_in["run_folder_str"], finish_dict_in["report_dict"])
    write_run_manifest_dict(stream_dict_in["run_folder_str"], finish_dict_in["manifest_dict"])


# FUNCTION: A DEVELOPMENT RUN OF EVERY CANDIDATE
def run_development_dict(design_module_in, ohlcv_array_dict_in, data_context_in=None, run_id_str_in=None,
                         n_jobs_int_in=None, period_pdf_in=None, trial_log_path_str_in=None, commit_str_in=None,
                         crash_after_period_id_in=None, code_hash_str_in=None, check_clean_tree_bool_in=True,
                         check_view_bool_in=True, baseline_seed_count_int_in=None,
                         look_ahead_status_str_in=LOOK_AHEAD_PENDING_STR, run_lookahead_bool_in=True,
                         note_str_in=""):
    """
    Development view. Refuses the quarantine root. Forms periods from PERIOD_RULE unless period_pdf_in is passed
    (tests). Streams each candidate, logs each candidate-period as it is scored, then builds the prior-only path
    from the recorded decisions. After a finished path it runs the shared baselines, the look-ahead check
    (truncation and perturbation at sampled cuts), applies the verdict, writes report.json and report.md, and
    writes manifest.json last.

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
        look_ahead_status_str_in (str): Used only when run_lookahead_bool_in is False
        run_lookahead_bool_in (bool): Run the automatic look-ahead check (default True)
        note_str_in (str): Free text copied onto each candidate-period trial row

    Returns:
        dict: run_id, period_pdf, score_pdf, selection_pdf, governing_dict, prior_only_dict, trial_id_list,
              baseline_dict, verdict_dict, report_dict, manifest_dict, lookahead_dict
    """
    # THE DEVELOPMENT VIEW NEVER OPENS THE QUARANTINE
    check_quarantine_refused()
    if check_view_bool_in:
        check_development_view()
    period_pdf = period_pdf_in
    if period_pdf is None:
        period_pdf, _fold_pdf = get_development_run_period_pdf(design_module_in, ohlcv_array_dict_in["session_date_list"])
    stream_dict = run_candidate_streams_dict(
        design_module_in, ohlcv_array_dict_in, period_pdf, data_context_in=data_context_in, run_id_str_in=run_id_str_in,
        n_jobs_int_in=n_jobs_int_in, trial_log_path_str_in=trial_log_path_str_in, commit_str_in=commit_str_in,
        crash_after_period_id_in=crash_after_period_id_in, code_hash_str_in=code_hash_str_in,
        check_clean_tree_bool_in=check_clean_tree_bool_in, log_trial_bool_in=True, note_str_in=note_str_in)
    finish_dict = write_runner_finish_dict(
        design_module_in, ohlcv_array_dict_in, stream_dict, stream_dict["prior_only_dict"], stream_dict["date1"],
        stream_dict["date2"], baseline_seed_count_int_in=baseline_seed_count_int_in,
        look_ahead_status_str_in=look_ahead_status_str_in, run_lookahead_bool_in=run_lookahead_bool_in)
    return {**stream_dict, **finish_dict}


# FUNCTION: SLICE THE CONTINUOUS PATH TO THE REPORTED HOLDOUT SESSIONS
def get_reported_path_dict(prior_only_dict_in, start_date_in, end_date_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Keeps equity and target weights on [start_date_in, end_date_in]. Equity is rebased so the equity entering that
    span equals the initial capital. The carried position is the first window weight.

    Args:
        prior_only_dict_in (dict): Full-span engine result
        start_date_in, end_date_in: Inclusive reported bounds
        initial_capital_in (float): Starting capital of the reported span

    Returns:
        dict: Sliced path with rebased equity and metric_dict
    """
    # CUT THE EQUITY, THEN REBASE TO THE CAPITAL THAT ENTERED THE SPAN
    start_date, end_date = get_date(start_date_in), get_date(end_date_in)
    equity_pdf = prior_only_dict_in["daily_equity_pdf"].copy()
    equity_pdf["date"] = equity_pdf["date"].map(get_date)
    prior_pdf = equity_pdf[equity_pdf["date"] < start_date]
    holdout_pdf = equity_pdf[(equity_pdf["date"] >= start_date) & (equity_pdf["date"] <= end_date)].copy()
    if holdout_pdf.empty:
        raise ValueError("the prior-only path has no sessions in the reported holdout span.")
    base_float = float(prior_pdf["equity"].iloc[-1]) if len(prior_pdf) else float(initial_capital_in)
    holdout_pdf["equity"] = holdout_pdf["equity"] * (float(initial_capital_in) / base_float)
    session_list = [get_date(session_date) for session_date in list(prior_only_dict_in.get("decision_session_list") or [])]
    target_arr = np.asarray(prior_only_dict_in.get("target_weight_arr"), dtype=float)
    keep_idx_list = [idx for idx, session_date in enumerate(session_list) if start_date <= session_date <= end_date]
    reported_session_list = [session_list[idx] for idx in keep_idx_list]
    reported_target_arr = target_arr[keep_idx_list] if len(target_arr) else np.array([], dtype=float)
    weight_arr = holdout_pdf["weight"].to_numpy(dtype=float) if "weight" in holdout_pdf.columns else np.array([], dtype=float)
    counted_weight_arr = weight_arr[:-1] if len(weight_arr) > 1 else weight_arr
    mean_weight = float(counted_weight_arr.mean()) if len(counted_weight_arr) else 0.0
    total_return = float(holdout_pdf["equity"].iloc[-1]) / float(initial_capital_in) - 1.0
    metric_dict = dict(prior_only_dict_in.get("metric_dict") or {})
    metric_dict["mean_weight"] = mean_weight
    metric_dict["total_return"] = total_return
    reported_dict = dict(prior_only_dict_in)
    reported_dict["daily_equity_pdf"] = holdout_pdf.reset_index(drop=True)
    reported_dict["target_weight_arr"] = reported_target_arr
    reported_dict["decision_session_list"] = reported_session_list
    reported_dict["metric_dict"] = metric_dict
    reported_dict["carried_weight"] = float(holdout_pdf["weight"].iloc[0]) if "weight" in holdout_pdf.columns else np.nan
    return reported_dict


# FUNCTION: LEDGER FIELDS FROM THE RUNNER VERDICT AND THE UNREAD TAIL
def get_holdout_ledger_fields_dict(verdict_dict_in, baseline_dict_in, reported_path_dict_in, unread_dict_in,
                                   ohlcv_array_dict_in, start_date_in, end_date_in, governing_dict_in, period_pdf_in):
    """
    Maps the shared verdict onto the existing holdout ledger columns. Missing optional fields stay absent and the
    append leaves them empty.

    Args:
        verdict_dict_in (dict): Output of get_runner_verdict_dict
        baseline_dict_in (dict): Output of get_runner_baseline_dict
        reported_path_dict_in (dict): Rebased window path
        unread_dict_in (dict): Output of get_unread_report_dict
        ohlcv_array_dict_in (dict): Bars (unused besides existing)
        start_date_in, end_date_in: Reported span
        governing_dict_in (dict): period_id -> candidate
        period_pdf_in (pd.DataFrame): Full-span periods

    Returns:
        dict: Ledger columns that this run can fill
    """
    # THE VERDICT ALREADY RAN THE SUCCESS CRITERIA ON THE REPORTED SPAN
    _ = ohlcv_array_dict_in
    return_dict = verdict_dict_in["return_dict"]
    success_dict = verdict_dict_in["success_dict"]
    holdout_pdf = reported_path_dict_in["daily_equity_pdf"]
    strategy_return_pdf = get_equity_daily_return_pdf(holdout_pdf)
    buy_hold_return_pdf = get_equity_daily_return_pdf(baseline_dict_in["buy_hold_daily_equity_pdf"])
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=6)
    merged_pdf = strategy_return_pdf.merge(buy_hold_return_pdf, on="date", suffixes=("_strategy", "_buy_hold"))
    merged_pdf["month"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("M")
    month_pdf = merged_pdf.groupby("month").agg(
        strategy_log=("daily_return_strategy", lambda series: float(np.log1p(series).sum())),
        buy_hold_log=("daily_return_buy_hold", lambda series: float(np.log1p(series).sum())))
    month_excess_arr = (month_pdf["strategy_log"] - month_pdf["buy_hold_log"]).to_numpy(dtype=float)
    start_date, end_date = get_date(start_date_in), get_date(end_date_in)
    holdout_period_pdf = period_pdf_in[period_pdf_in["period_end"].map(get_date) >= start_date]
    candidate_dict = {int(period_row.period_id): governing_dict_in.get(int(period_row.period_id))
                      for period_row in holdout_period_pdf.itertuples(index=False)}
    baseline_return_dict = {"buy_hold": float(baseline_dict_in["buy_hold_total_return"]),
                            "constant_exposure": float(baseline_dict_in["constant_exposure_total_return"])}
    return {
        "total_return": float(return_dict["strategy_total_return"]),
        "buy_hold_total_return": float(return_dict["buy_hold_total_return"]),
        "annualized_log_excess": log_excess_dict["annualized_log_excess"],
        "log_excess_ci_low": log_excess_dict["ci_low"], "log_excess_ci_high": log_excess_dict["ci_high"],
        "in_market_pct": float(holdout_pdf["in_position"].mean()) if "in_position" in holdout_pdf.columns else np.nan,
        "sharpe_ratio": float(return_dict["strategy_sharpe_ratio"]),
        "max_drawdown": float(return_dict["strategy_max_drawdown"]),
        "mde": get_mde_float(float(np.std(month_excess_arr, ddof=1)) if len(month_excess_arr) > 1 else np.nan,
                             len(month_excess_arr)),
        "primary_pass": bool(success_dict["primary_success"]),
        "secondary_pass": bool(success_dict["secondary_success"]),
        "comparable_pass": bool(success_dict["comparable_return"]),
        "baselines_beaten": {"constant_exposure": bool(verdict_dict_in["baseline_dict"]["constant_pass_bool"]),
                             "random_timing": bool(verdict_dict_in["baseline_dict"]["random_pass_bool"])},
        "baseline_returns": get_baseline_json_str(baseline_return_dict),
        "carried_weight": reported_path_dict_in.get("carried_weight", np.nan),
        "holdout_candidates": json.dumps({str(key): value for key, value in candidate_dict.items()}),
        "unread_start": unread_dict_in.get("unread_start", np.nan),
        "unread_session_count": unread_dict_in.get("unread_session_count", np.nan),
        "unread_total_return": unread_dict_in.get("unread_total_return", np.nan),
        "unread_buy_hold_total_return": unread_dict_in.get("unread_buy_hold_total_return", np.nan),
    }


# FUNCTION: A HOLDOUT EVALUATION OF A RUNNER DESIGN
def run_holdout_dict(design_module_in, design_id_str_in, ohlcv_array_dict_in, token_file_path_str_in,
                     data_context_in=None, git_precondition_dict_in=None, design_folder_str_in=".",
                     ledger_path_str_in=None, trial_log_path_str_in=None, period_pdf_in=None, run_id_str_in=None,
                     n_jobs_int_in=None, commit_str_in=None, code_hash_str_in=None, check_clean_tree_bool_in=False,
                     baseline_seed_count_int_in=None, look_ahead_status_str_in=LOOK_AHEAD_PENDING_STR,
                     run_lookahead_bool_in=True):
    """
    Nicolas only. Same stream, selection, baseline, verdict and look-ahead as run_development_dict, with the
    quarantine root and the evaluation token. Periods are get_holdout_period_pdf unless period_pdf_in is passed
    (tests). The run starts at the development start; only window sessions are reported. No candidate-period trial
    row is written. Token, git, once-only, forward-only and the 10-evaluation budget are so.core.holdout's checks.
    Everything is computed in memory; the ledger row and the stage-test trial are appended before report.json,
    report.md, the manifest, the daily paths or any printed result. Progress during the stream does not print
    window returns.

    Args:
        design_module_in (module): Design with get_candidate_design
        design_id_str_in (str): Design id
        ohlcv_array_dict_in (dict): Bars from the first session through the window end
        token_file_path_str_in (str): Token file
        data_context_in (DataContext | None): Loaded sources (the script loads them from the quarantine)
        git_precondition_dict_in (dict | None): Injected git result
        design_folder_str_in (str): Design folder for the git probe and the design-tree hash
        ledger_path_str_in (str | None): Ledger CSV
        trial_log_path_str_in (str | None): Trial log CSV
        period_pdf_in (pd.DataFrame | None): Injected periods (None = get_holdout_period_pdf)
        run_id_str_in (str | None): Resume key (None = design_id)
        n_jobs_int_in, commit_str_in, code_hash_str_in: Passed through to the stream
        check_clean_tree_bool_in (bool): Extra runner clean-tree check (the holdout git probe already requires a
            clean tree; tests that inject that probe leave this False)
        baseline_seed_count_int_in (int | None): Random-timing draws
        look_ahead_status_str_in (str): Used only when run_lookahead_bool_in is False
        run_lookahead_bool_in (bool): Run the automatic look-ahead check

    Returns:
        dict: The stream result, the reported path, the verdict, the ledger row and the unread dict
    """
    # THE TOKEN AND THE OTHER HOLDOUT RULES ARE CHECKED BEFORE THE QUARANTINE ROOT IS READ
    precondition_dict = check_evaluation_precondition_dict(
        design_module_in, design_id_str_in, token_file_path_str_in, git_precondition_dict_in, design_folder_str_in,
        ledger_path_str_in, session_date_list_in=ohlcv_array_dict_in["session_date_list"])
    quarantine_root_str = paths.get_quarantine_root_str()
    window_dict = precondition_dict["window_dict"]
    reported_start = get_date(precondition_dict["reported_start"])
    reported_end = get_date(precondition_dict["reported_end"])
    declared_name_list = get_declared_source_name_list(design_module_in)
    for source_name_str in declared_name_list:
        get_source_spec_dict(source_name_str)
    period_pdf = period_pdf_in
    if period_pdf is None:
        period_pdf = get_holdout_period_pdf(design_module_in, ohlcv_array_dict_in["session_date_list"], window_dict)
    results_path_str = os.environ.get("SO_HOLDOUT_PATH") or None
    runs_root_str = os.path.join(results_path_str, str(window_dict["window_id"]))
    run_id_str = str(run_id_str_in) if run_id_str_in else str(design_id_str_in)
    trial_log_path_str = trial_log_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    set_runner_active_bool(True)
    undeclared_error = None
    stream_dict = None
    try:
        stream_dict = run_candidate_streams_dict(
            design_module_in, ohlcv_array_dict_in, period_pdf, data_context_in=data_context_in, run_id_str_in=run_id_str,
            n_jobs_int_in=n_jobs_int_in, trial_log_path_str_in=trial_log_path_str, commit_str_in=commit_str_in,
            code_hash_str_in=code_hash_str_in, check_clean_tree_bool_in=check_clean_tree_bool_in,
            log_trial_bool_in=False, runs_root_str_in=runs_root_str)
    except ValueError as error:
        if "undeclared source" not in str(error):
            raise
        undeclared_error = error
    finally:
        set_runner_active_bool(False)
    access_name_list = []
    if data_context_in is not None and hasattr(data_context_in, "get_access_name_list"):
        access_name_list = list(data_context_in.get_access_name_list())
    undeclared_name_list = [source_name_str for source_name_str in access_name_list if source_name_str not in declared_name_list]
    row_dict = {"window_id": window_dict["window_id"], "design_id": design_id_str_in,
                "experiment_name": str(getattr(design_module_in, "EXPERIMENT_NAME", "") or ""),
                "design_hash": precondition_dict["design_hash_str"], "commit": precondition_dict["commit_str"],
                "evaluated_ts": datetime.now().isoformat(timespec="seconds"),
                "reported_start": reported_start, "reported_end": reported_end,
                "sources_read": ",".join(access_name_list)}
    if undeclared_error is not None or undeclared_name_list:
        row_dict["status"] = "invalid_undeclared"
        append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
        log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                       {}, True, fold_row_in={"test_start": reported_start, "test_end": reported_end},
                       note_str_in="invalid_undeclared", file_path_str_in=trial_log_path_str, alert_in=False)
        print(f"invalid_undeclared: {undeclared_error or undeclared_name_list}")
        return {"ledger_row_dict": row_dict, "stream_dict": stream_dict, "precondition_dict": precondition_dict}
    reported_path_dict = get_reported_path_dict(stream_dict["prior_only_dict"], reported_start, reported_end)
    unread_dict = get_unread_report_dict(reported_path_dict["daily_equity_pdf"], ohlcv_array_dict_in, reported_end)
    unread_count = unread_dict.get("unread_session_count")
    unread_display_dict = dict(unread_dict)
    unread_display_dict["label_str"] = UNREAD_SANITY_CHECK_STR
    unread_display_dict["unread_session_count"] = (0 if unread_count is None or (isinstance(unread_count, float) and not np.isfinite(unread_count))
                                                   else int(unread_count))
    quarantine_stamp_dict = get_view_stamp_dict(quarantine_root_str)
    view_stamp_dict = get_view_stamp_dict()
    set_runs_root_str(runs_root_str)
    try:
        finish_dict = write_runner_finish_dict(
            design_module_in, ohlcv_array_dict_in, stream_dict, reported_path_dict, reported_start, reported_end,
            baseline_seed_count_int_in=baseline_seed_count_int_in, look_ahead_status_str_in=look_ahead_status_str_in,
            run_lookahead_bool_in=run_lookahead_bool_in,
            extra_report_dict_in={"view_stamp_dict": view_stamp_dict, "quarantine_stamp_dict": quarantine_stamp_dict,
                                  "window_id": window_dict["window_id"], "unread_dict": unread_display_dict,
                                  "report_session_date_list": [str(session_date) for session_date in reported_path_dict["decision_session_list"]]},
            extra_manifest_dict_in={"window_id": window_dict["window_id"], "quarantine_stamp": quarantine_stamp_dict},
            write_files_bool_in=False)
    finally:
        set_runs_root_str(None)
    look_ahead_status_str = finish_dict["verdict_dict"]["look_ahead_dict"]["status_str"]
    if look_ahead_status_str == LOOK_AHEAD_FAIL_STR:
        row_dict["status"] = "invalid_lookahead"
        append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
        log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                       {}, True, fold_row_in={"test_start": reported_start, "test_end": reported_end},
                       note_str_in="invalid_lookahead", file_path_str_in=trial_log_path_str, alert_in=False)
        finish_dict["manifest_dict"]["ledger_row"] = get_json_value(row_dict)
        write_runner_result_files_dict(stream_dict, finish_dict)
        print("invalid_lookahead")
        return {**stream_dict, **finish_dict, "ledger_row_dict": row_dict, "reported_path_dict": reported_path_dict,
                "unread_dict": unread_display_dict, "precondition_dict": precondition_dict,
                "report_session_date_list": list(reported_path_dict["decision_session_list"])}
    ledger_fields_dict = get_holdout_ledger_fields_dict(
        finish_dict["verdict_dict"], finish_dict["baseline_dict"], reported_path_dict, unread_dict,
        ohlcv_array_dict_in, reported_start, reported_end, stream_dict["governing_dict"], stream_dict["period_pdf"])
    row_dict["status"] = "valid"
    row_dict.update(ledger_fields_dict)
    append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
    log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                   {key_str: row_dict[key_str] for key_str in ["total_return", "buy_hold_total_return", "annualized_log_excess", "primary_pass"]},
                   True, fold_row_in={"test_start": reported_start, "test_end": reported_end},
                   note_str_in="holdout evaluation", file_path_str_in=trial_log_path_str, alert_in=False)
    finish_dict["manifest_dict"]["ledger_row"] = get_json_value(row_dict)
    finish_dict["manifest_dict"]["window_id"] = window_dict["window_id"]
    finish_dict["manifest_dict"]["quarantine_stamp"] = quarantine_stamp_dict
    write_runner_result_files_dict(stream_dict, finish_dict, reported_path_dict)
    return {**stream_dict, **finish_dict, "ledger_row_dict": row_dict, "reported_path_dict": reported_path_dict,
            "unread_dict": unread_display_dict, "precondition_dict": precondition_dict,
            "report_session_date_list": list(reported_path_dict["decision_session_list"])}
