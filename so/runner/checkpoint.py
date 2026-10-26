import os
import pickle
# IMPORT THE EXPERIMENT ZONE
from so import paths

"""
Run Folder And Checkpoints (infrastructure step 4b-1a)

One folder per run under store04_experiments/runs/<run_id>/. Each candidate stream pickles the design and the engine
at the end of each period. A crashed run restores that pickle and continues. Recorded decisions and scores sit next
to the pickle so the parent can build the prior-only path after every candidate has finished.
"""

# PICKLE PROTOCOL (4 READS ON THE LOCKED PYTHON)
CHECKPOINT_PROTOCOL_INT = 4
# FILE NAMES INSIDE A CANDIDATE FOLDER
CHECKPOINT_FILE_STR = "checkpoint.pkl"
DECISIONS_FILE_STR = "decisions.pkl"
SCORES_FILE_STR = "scores.pkl"
DONE_FILE_STR = "done.marker"
IDENTITY_FILE_STR = "identity.pkl"
# OPTIONAL OVERRIDE (A HOLDOUT RUN WRITES UNDER SO_HOLDOUT_PATH; SPAWNED WORKERS READ IT FROM THE JOB DICT)
_RUNS_ROOT_STR = None


# FUNCTION: SET THE RUNS ROOT FOR THIS PROCESS
def set_runs_root_str(root_str_in):
    """
    None restores the development experiment-zone default.

    Args:
        root_str_in (str | None): Folder that holds one subfolder per run id

    Returns:
        None
    """
    # SPAWNED WORKERS SET THIS FROM THE JOB DICT BEFORE THEY READ A CHECKPOINT
    global _RUNS_ROOT_STR
    _RUNS_ROOT_STR = None if root_str_in is None else str(root_str_in)


# FUNCTION: THE RUNS ROOT UNDER THE EXPERIMENT ZONE
def get_runs_root_str():
    """
    store04_experiments/runs/ of the development data root, unless set_runs_root_str pointed it at a holdout folder.

    Args:
        None

    Returns:
        str: Folder path
    """
    # A HOLDOUT RUN SETS THE OVERRIDE SO CHECKPOINTS NEVER LAND IN THE DEVELOPMENT VIEW
    if _RUNS_ROOT_STR:
        return _RUNS_ROOT_STR
    # THE ZONE FOLLOWS AN ASSIGNMENT WHEN A TEST HAS REPLACED IT
    return os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runs")


# FUNCTION: ONE RUN FOLDER
def get_run_folder_str(run_id_str_in):
    """
    Args:
        run_id_str_in (str): Run id

    Returns:
        str: Folder path
    """
    # ONE FOLDER PER RUN
    return os.path.join(get_runs_root_str(), str(run_id_str_in))


# FUNCTION: ONE CANDIDATE FOLDER INSIDE A RUN
def get_candidate_folder_str(run_id_str_in, candidate_token_str_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token

    Returns:
        str: Folder path
    """
    # CHECKPOINTS AND OUTPUTS FOR THIS STREAM
    return os.path.join(get_run_folder_str(run_id_str_in), "candidates", str(candidate_token_str_in))


# FUNCTION: CREATE A FOLDER IF NEEDED
def make_folder(folder_str_in):
    """
    Args:
        folder_str_in (str): Folder

    Returns:
        str: The same path
    """
    # EXISTING FOLDERS ARE LEFT AS THEY ARE
    os.makedirs(folder_str_in, exist_ok=True)
    return folder_str_in


# FUNCTION: PICKLE ONE OBJECT
def write_pickle(file_path_str_in, value_in):
    """
    Overwrites the file. Used only for files this run created.

    Args:
        file_path_str_in (str): Path
        value_in: Pickleable object

    Returns:
        None
    """
    # THE FOLDER IS CREATED HERE
    make_folder(os.path.dirname(file_path_str_in))
    with open(file_path_str_in, "wb") as pickle_file:
        pickle.dump(value_in, pickle_file, protocol=CHECKPOINT_PROTOCOL_INT)


# FUNCTION: UNPICKLE ONE OBJECT
def read_pickle(file_path_str_in):
    """
    Args:
        file_path_str_in (str): Path

    Returns:
        object: The stored value
    """
    # A MISSING FILE IS AN ERROR FOR THE CALLER TO HANDLE
    with open(file_path_str_in, "rb") as pickle_file:
        return pickle.load(pickle_file)


# FUNCTION: WHETHER A FILE EXISTS
def get_file_exists_bool(file_path_str_in):
    """
    Args:
        file_path_str_in (str): Path

    Returns:
        bool: True if present
    """
    # A FOLDER IS NOT A CHECKPOINT
    return os.path.isfile(file_path_str_in)


# FUNCTION: WRITE A CANDIDATE CHECKPOINT
def write_checkpoint_dict(run_id_str_in, candidate_token_str_in, checkpoint_dict_in):
    """
    Pickles the design, the engine and the stream progress.

    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token
        checkpoint_dict_in (dict): design, engine, next_session_pos, lists, period_id

    Returns:
        str: Checkpoint path
    """
    # ONE PICKLE PER CANDIDATE (THE LATEST PERIOD)
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), CHECKPOINT_FILE_STR)
    write_pickle(file_path_str, checkpoint_dict_in)
    return file_path_str


# FUNCTION: READ A CANDIDATE CHECKPOINT
def read_checkpoint_dict(run_id_str_in, candidate_token_str_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token

    Returns:
        dict | None: The checkpoint, or None if none has been written
    """
    # A FRESH CANDIDATE HAS NO FILE
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), CHECKPOINT_FILE_STR)
    if not get_file_exists_bool(file_path_str):
        return None
    return read_pickle(file_path_str)


# FUNCTION: WRITE RECORDED DECISIONS
def write_decisions_list(run_id_str_in, candidate_token_str_in, decision_dict_list_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token
        decision_dict_list_in (list): One decision dict per window session so far (and then all of them)

    Returns:
        None
    """
    # THE PARENT READS THIS AFTER EVERY CANDIDATE HAS FINISHED
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), DECISIONS_FILE_STR)
    write_pickle(file_path_str, list(decision_dict_list_in))


# FUNCTION: READ RECORDED DECISIONS
def read_decisions_list(run_id_str_in, candidate_token_str_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token

    Returns:
        list | None: Decision dicts, or None
    """
    # A CRASH BEFORE THE FIRST PERIOD HAS NONE
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), DECISIONS_FILE_STR)
    if not get_file_exists_bool(file_path_str):
        return None
    return read_pickle(file_path_str)


# FUNCTION: WRITE THE SCORED ROWS SO FAR
def write_score_row_list(run_id_str_in, candidate_token_str_in, score_dict_list_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token
        score_dict_list_in (list[dict]): One row per completed period

    Returns:
        None
    """
    # KEPT NEXT TO THE CHECKPOINT
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), SCORES_FILE_STR)
    write_pickle(file_path_str, list(score_dict_list_in))


# FUNCTION: READ THE SCORED ROWS
def read_score_row_list(run_id_str_in, candidate_token_str_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token

    Returns:
        list: Score dicts (empty if none)
    """
    # A FRESH STREAM HAS NO SCORES
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), SCORES_FILE_STR)
    if not get_file_exists_bool(file_path_str):
        return []
    return list(read_pickle(file_path_str))


# FUNCTION: MARK A CANDIDATE STREAM COMPLETE
def write_done_marker(run_id_str_in, candidate_token_str_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token

    Returns:
        None
    """
    # AN EMPTY FILE IS ENOUGH
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), DONE_FILE_STR)
    make_folder(os.path.dirname(file_path_str))
    with open(file_path_str, "w", encoding="utf-8") as done_file:
        done_file.write("done\n")


# FUNCTION: WRITE THE RUN IDENTITY (COMMIT AND CODE HASH)
def write_run_identity_dict(run_id_str_in, identity_dict_in):
    """
    One pickle at the run folder root. Written once when the run starts.

    Args:
        run_id_str_in (str): Run id
        identity_dict_in (dict): commit_str, code_hash_str

    Returns:
        None
    """
    # THE PARENT CHECKS THIS BEFORE ANY WORKER RUNS
    file_path_str = os.path.join(get_run_folder_str(run_id_str_in), IDENTITY_FILE_STR)
    write_pickle(file_path_str, dict(identity_dict_in))


# FUNCTION: READ THE RUN IDENTITY
def read_run_identity_dict(run_id_str_in):
    """
    Args:
        run_id_str_in (str): Run id

    Returns:
        dict | None: commit_str and code_hash_str, or None if the run has not started
    """
    # A FRESH RUN ID HAS NO FILE
    file_path_str = os.path.join(get_run_folder_str(run_id_str_in), IDENTITY_FILE_STR)
    if not get_file_exists_bool(file_path_str):
        return None
    return read_pickle(file_path_str)


# FUNCTION: WHETHER A CANDIDATE STREAM HAS FINISHED
def get_done_bool(run_id_str_in, candidate_token_str_in):
    """
    Args:
        run_id_str_in (str): Run id
        candidate_token_str_in (str): Filesystem-safe candidate token

    Returns:
        bool: True if the done marker is present
    """
    # RESUME SKIPS A FINISHED STREAM
    file_path_str = os.path.join(get_candidate_folder_str(run_id_str_in, candidate_token_str_in), DONE_FILE_STR)
    return get_file_exists_bool(file_path_str)


# THE LARGE FILES A FINISHED RUN NO LONGER NEEDS (AUDIT S11, 2026-10-25)
PRUNE_RUN_FILE_LIST = ["ohlcv.pkl", "data_context.pkl"]
PRUNE_RUN_FOLDER_LIST = ["fit_cache"]


# FUNCTION: DELETE THE BULK OF A FINISHED RUN
def prune_finished_run_folder(run_folder_str_in):
    """
    Called after the manifest is written. Deletes the bar and source pickles, every candidate checkpoint and the
    shared fit cache. Kept: report.json, report.md, lookahead.json, manifest.json, the identity, and per candidate
    decisions.pkl, scores.pkl and done.marker (enough to rebuild the prior-only path and to audit every decision).
    A rerun under the same run id rebuilds what it needs.

    Args:
        run_folder_str_in (str): Run folder

    Returns:
        int: Bytes freed
    """
    # ONLY A FINISHED RUN (ITS MANIFEST EXISTS)
    import shutil
    if not os.path.isfile(os.path.join(run_folder_str_in, "manifest.json")):
        return 0
    freed_int = 0
    path_list = [os.path.join(run_folder_str_in, file_str) for file_str in PRUNE_RUN_FILE_LIST]
    candidate_root_str = os.path.join(run_folder_str_in, "candidates")
    if os.path.isdir(candidate_root_str):
        for token_str in os.listdir(candidate_root_str):
            path_list.append(os.path.join(candidate_root_str, token_str, CHECKPOINT_FILE_STR))
    for path_str in path_list:
        if os.path.isfile(path_str):
            freed_int += os.path.getsize(path_str)
            os.remove(path_str)
    for folder_str in PRUNE_RUN_FOLDER_LIST:
        folder_path_str = os.path.join(run_folder_str_in, folder_str)
        if os.path.isdir(folder_path_str):
            for dir_str, _dir_list, file_list in os.walk(folder_path_str):
                freed_int += sum(os.path.getsize(os.path.join(dir_str, file_str)) for file_str in file_list)
            shutil.rmtree(folder_path_str, ignore_errors=True)
    return int(freed_int)
