import argparse
import math
import os
import re
import sys
from pathlib import Path

# ADD THE WORKSPACE AND THE SCRIPTS FOLDER TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parent))
# IMPORT THE QUEUE PATHS
from run_queue import get_queue_path_dict, read_json

"""
Equivalence Check Of Two Runs (Nicolas only; design 4.4, roadmap judge v1 freeze, decided 2026-11-04/05)

After the judge v1 freeze, a change to the judge hash that touches no scoring code (the queue, the setup checks, a
script) is accepted when one or two fast daily experiments, rerun under the new judge, reproduce every number of their
baseline run exactly. This script compares the two runs:

    report.json      every value, recursively, except identifiers (run id, commits, hashes, judge identity, paths,
                     folders, timestamps, trial ids, process counts and timings), which differ by construction
    candidates/      each candidate's decisions and scores (decisions.pkl, scores.pkl), read with pandas and compared
                     value by value

Numbers must be identical (not close): the same code on the same data gives the same floats. The multiple-testing
part depends on N, the designs in the trial log, which may grow between the two runs; differences that lie only in
the multiple-testing view (and the grade, when only that changed) are reported separately as "explained by N" when N
differs. Exit 0 when the runs are equivalent, 1 otherwise. It prints numbers: run it as nico or so_runner only.

    python scripts/check_equivalence.py --baseline <run id> --new <run id>

A run id is looked up under the live runs folder. After a reset (scripts/reset_records.py) the baseline run is no
longer there: give it as its full backup path instead, for example
    --baseline D:\\stock_overflow\\backup_records\\reset_20261110_232619\\runs\\exp02_stop_reentry_20261111000527008138
(os.path.join keeps an absolute path, so the same argument takes either form).
"""

# REPORT KEYS THAT DIFFER BY CONSTRUCTION (IDENTITY, PLACE, TIME, WORK DONE)
IGNORED_KEY_PATTERN = re.compile(r"(^|_)(run_id|commit|hash|judge|path|folder|ts|seconds|trial_id|process_count|"
                                 r"preregistration|evaluated)(_|$)")
# TOP-LEVEL REPORT KEYS WHOSE VALUES FOLLOW N (THE DESIGNS IN THE TRIAL LOG; THE TAIL SITS IN multiple_testing_dict)
N_DEPENDENT_KEY_LIST = ["multiple_testing_dict", "grade_dict", "failed_list", "label_str", "email_worthy_bool"]
# CANDIDATE FILES COMPARED
CANDIDATE_FILE_LIST = ["decisions.pkl", "scores.pkl"]


# FUNCTION: THE DIFFERENCES BETWEEN TWO JSON VALUES
def get_value_difference_list(baseline_in, new_in, key_path_str_in=""):
    """
    Args:
        baseline_in, new_in: JSON values
        key_path_str_in (str): Where they sit (for the message)

    Returns:
        list[str]: One line per difference ("path: baseline -> new"); ignored keys are skipped
    """
    # DICTS BY KEY, LISTS BY POSITION, NUMBERS EXACTLY (NaN EQUALS NaN)
    if isinstance(baseline_in, dict) and isinstance(new_in, dict):
        difference_list = []
        for key_str in sorted(set(baseline_in) | set(new_in)):
            if IGNORED_KEY_PATTERN.search(str(key_str)):
                continue
            child_path_str = f"{key_path_str_in}.{key_str}" if key_path_str_in else str(key_str)
            if key_str not in baseline_in or key_str not in new_in:
                difference_list.append(f"{child_path_str}: only in the {'new' if key_str not in baseline_in else 'baseline'} run")
                continue
            difference_list.extend(get_value_difference_list(baseline_in[key_str], new_in[key_str], child_path_str))
        return difference_list
    if isinstance(baseline_in, list) and isinstance(new_in, list):
        if len(baseline_in) != len(new_in):
            return [f"{key_path_str_in}: {len(baseline_in)} items -> {len(new_in)} items"]
        difference_list = []
        for index_int, (baseline_value, new_value) in enumerate(zip(baseline_in, new_in)):
            difference_list.extend(get_value_difference_list(baseline_value, new_value, f"{key_path_str_in}[{index_int}]"))
        return difference_list
    if isinstance(baseline_in, float) and isinstance(new_in, float) and math.isnan(baseline_in) and math.isnan(new_in):
        return []
    if baseline_in != new_in or type(baseline_in) is not type(new_in):
        return [f"{key_path_str_in}: {baseline_in!r} -> {new_in!r}"]
    return []


# FUNCTION: THE DIFFERENCES BETWEEN THE CANDIDATE FILES OF TWO RUNS
def get_candidate_difference_list(baseline_folder_str_in, new_folder_str_in):
    """
    Args:
        baseline_folder_str_in, new_folder_str_in (str): Run folders

    Returns:
        list[str]: One line per missing candidate, missing file or differing file
    """
    # PANDAS READS THE PICKLES; EQUALITY IS VALUE BY VALUE (NaN EQUALS NaN)
    import pandas as pd
    difference_list = []
    baseline_root, new_root = Path(baseline_folder_str_in) / "candidates", Path(new_folder_str_in) / "candidates"
    baseline_set = {path.name for path in baseline_root.iterdir() if path.is_dir()} if baseline_root.is_dir() else set()
    new_set = {path.name for path in new_root.iterdir() if path.is_dir()} if new_root.is_dir() else set()
    for token_str in sorted(baseline_set ^ new_set):
        difference_list.append(f"candidates/{token_str}: only in the {'baseline' if token_str in baseline_set else 'new'} run")
    for token_str in sorted(baseline_set & new_set):
        for file_str in CANDIDATE_FILE_LIST:
            baseline_path, new_path = baseline_root / token_str / file_str, new_root / token_str / file_str
            if not baseline_path.is_file() and not new_path.is_file():
                continue
            if baseline_path.is_file() != new_path.is_file():
                difference_list.append(f"candidates/{token_str}/{file_str}: only in one run")
                continue
            baseline_value, new_value = pd.read_pickle(baseline_path), pd.read_pickle(new_path)
            try:
                same_bool = get_frame_equal_bool(baseline_value, new_value)
            except Exception as error:
                same_bool = False
                difference_list.append(f"candidates/{token_str}/{file_str}: cannot compare ({type(error).__name__})")
                continue
            if not same_bool:
                difference_list.append(f"candidates/{token_str}/{file_str}: values differ")
    return difference_list


# FUNCTION: EQUALITY OF TWO PICKLED VALUES (FRAMES, SERIES, LISTS, DICTS)
def get_frame_equal_bool(baseline_in, new_in):
    """
    Args:
        baseline_in, new_in: Values read from the pickles

    Returns:
        bool: True when equal, value by value
    """
    # PANDAS OBJECTS WITH equals (NaN-AWARE); CONTAINERS ELEMENT BY ELEMENT
    import pandas as pd
    if isinstance(baseline_in, (pd.DataFrame, pd.Series)) or isinstance(new_in, (pd.DataFrame, pd.Series)):
        return type(baseline_in) is type(new_in) and baseline_in.equals(new_in)
    if isinstance(baseline_in, dict) and isinstance(new_in, dict):
        return set(baseline_in) == set(new_in) and all(get_frame_equal_bool(baseline_in[key], new_in[key]) for key in baseline_in)
    if isinstance(baseline_in, (list, tuple)) and isinstance(new_in, (list, tuple)):
        return len(baseline_in) == len(new_in) and all(get_frame_equal_bool(a, b) for a, b in zip(baseline_in, new_in))
    if isinstance(baseline_in, float) and isinstance(new_in, float) and math.isnan(baseline_in) and math.isnan(new_in):
        return True
    return bool(baseline_in == new_in)


# FUNCTION: COMPARE TWO RUNS
def get_equivalence_dict(baseline_folder_str_in, new_folder_str_in):
    """
    Args:
        baseline_folder_str_in, new_folder_str_in (str): Run folders

    Returns:
        dict: equivalent_bool, scoring_difference_list, n_difference_list (explained by N), n_pair (baseline N, new N),
            candidate_difference_list, same_experiment_bool
    """
    # THE REPORTS; THE N-DEPENDENT PART APART
    baseline_report_dict = read_json(os.path.join(baseline_folder_str_in, "report.json"))
    new_report_dict = read_json(os.path.join(new_folder_str_in, "report.json"))
    baseline_n = (baseline_report_dict.get("multiple_testing_dict") or {}).get("design_count")
    new_n = (new_report_dict.get("multiple_testing_dict") or {}).get("design_count")
    difference_list = get_value_difference_list(baseline_report_dict, new_report_dict)
    n_changed_bool = baseline_n != new_n
    n_difference_list = [line_str for line_str in difference_list
                         if n_changed_bool and re.split(r"[.\[:]", line_str, maxsplit=1)[0] in N_DEPENDENT_KEY_LIST]
    scoring_difference_list = [line_str for line_str in difference_list if line_str not in n_difference_list]
    candidate_difference_list = get_candidate_difference_list(baseline_folder_str_in, new_folder_str_in)
    same_experiment_bool = (baseline_report_dict.get("experiment_name_str") == new_report_dict.get("experiment_name_str")
                            and baseline_report_dict.get("protocol_version_str") == new_report_dict.get("protocol_version_str"))
    return {"equivalent_bool": bool(same_experiment_bool and not scoring_difference_list and not candidate_difference_list),
            "scoring_difference_list": scoring_difference_list, "n_difference_list": n_difference_list,
            "n_pair": (baseline_n, new_n), "candidate_difference_list": candidate_difference_list,
            "same_experiment_bool": same_experiment_bool}


# PARSE THE COMMAND
if __name__ == "__main__":
    # TWO RUN IDS UNDER THE QUEUE'S RUN FOLDER
    parser = argparse.ArgumentParser(description="Check that a rerun under a new judge reproduces a baseline run exactly.")
    parser.add_argument("--baseline", required=True,
                        help="Run id of the baseline run under the live runs folder, or, after a reset, its full path "
                             "(backup_records\\reset_<time>\\runs\\<run id>)")
    parser.add_argument("--new", required=True, help="Run id of the rerun under the new judge (or its full path)")
    arg_dict = parser.parse_args()
    runs_str = get_queue_path_dict()["runs"]
    outcome_dict = get_equivalence_dict(os.path.join(runs_str, arg_dict.baseline), os.path.join(runs_str, arg_dict.new))
    if not outcome_dict["same_experiment_bool"]:
        print("NOT COMPARABLE: the two runs are of different experiments or protocol versions")
    for line_str in outcome_dict["scoring_difference_list"] + outcome_dict["candidate_difference_list"]:
        print(f"DIFFERENT  {line_str}")
    for line_str in outcome_dict["n_difference_list"]:
        print(f"explained by N {outcome_dict['n_pair'][0]} -> {outcome_dict['n_pair'][1]}:  {line_str}")
    print("EQUIVALENT: every scoring number and every candidate file is identical" if outcome_dict["equivalent_bool"]
          else "NOT EQUIVALENT: a full rerun is needed (design 4.4)")
    sys.exit(0 if outcome_dict["equivalent_bool"] else 1)
