import argparse
import json
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE AND THE SCRIPTS FOLDER TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parent))
# IMPORT THE QUEUE PATHS AND THE ROW FORMAT
from run_queue import get_queue_path_dict
from run_development import get_results_row_str
import pandas as pd

"""
Append Finished Runs To docs/RESULTS_LOG.md (audit S3, 2026-10-25)

The queue runs each job in a temporary worktree, so a run cannot write the repository's results log. Finished runs
are listed in store04_experiments/run_index.csv. This script appends one row to docs/RESULTS_LOG.md for every finished
run in the index whose run id is not in the log yet (oldest first), from the run's own report.json. It only appends;
commit the change on a branch and open a pull request.

    python scripts/append_results_log.py            # append
    python scripts/append_results_log.py --dry-run  # print the rows only
"""

# THE RESULTS LOG OF THIS WORKSPACE
RESULTS_LOG_PATH = Path(__file__).resolve().parents[1] / "docs" / "RESULTS_LOG.md"


# FUNCTION: THE ROWS TO APPEND
def get_new_row_list(path_dict_in, results_log_path_in=RESULTS_LOG_PATH):
    """
    Args:
        path_dict_in (dict): Queue paths (run_index, runs)
        results_log_path_in (Path): docs/RESULTS_LOG.md

    Returns:
        list[str]: Rows for finished runs not yet in the log, in finish order
    """
    # FINISHED RUNS THE LOG DOES NOT NAME
    if not os.path.isfile(path_dict_in["run_index"]):
        return []
    log_text_str = Path(results_log_path_in).read_text(encoding="utf-8")
    index_pdf = pd.read_csv(path_dict_in["run_index"], dtype=str, keep_default_na=False)
    index_pdf = index_pdf.loc[index_pdf["status"] == "done"].sort_values("finished_ts", kind="mergesort")
    row_list, seen_set = [], set()
    for row in index_pdf.itertuples(index=False):
        if row.run_id in seen_set or f"| {row.run_id} |" in log_text_str:
            continue
        report_path_str = os.path.join(path_dict_in["runs"], row.run_id, "report.json")
        if not os.path.isfile(report_path_str):
            continue
        with open(report_path_str, encoding="utf-8") as file_obj:
            report_dict = json.load(file_obj)
        row_list.append(get_results_row_str(report_dict, row.run_id, row.note, str(row.finished_ts)[:10]))
        seen_set.add(row.run_id)
    return row_list


# PARSE THE COMMAND
if __name__ == "__main__":
    # APPEND, OR PRINT ONLY
    parser = argparse.ArgumentParser(description="Append finished queue runs to docs/RESULTS_LOG.md.")
    parser.add_argument("--dry-run", action="store_true", help="Print the rows; change nothing")
    arg_dict = parser.parse_args()
    new_row_list = get_new_row_list(get_queue_path_dict())
    print("\n".join(new_row_list) if new_row_list else "no new finished runs")
    if new_row_list and not arg_dict.dry_run:
        log_text_str = RESULTS_LOG_PATH.read_text(encoding="utf-8")
        with open(RESULTS_LOG_PATH, "a", encoding="utf-8", newline="\n") as file_obj:
            if not log_text_str.endswith("\n"):
                file_obj.write("\n")
            file_obj.write("\n".join(new_row_list) + "\n")
        print(f"appended {len(new_row_list)} row(s) to {RESULTS_LOG_PATH}")
