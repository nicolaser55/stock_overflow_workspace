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
commit the change on a branch and open a pull request. Nicolas runs it: the run index and the reports are readable only
by so_runner and him (roadmap R4).

The switch records/agent_phase.txt (roadmap R4, decided 2026-10-28 / 2026-11-03) decides the row format:
    development   rows as before: verdict, prior-only and buy-and-hold total returns, failed parts, look-ahead
    agents        rows with identifiers, the grade and its reason only, no numbers (agents can read the log in git)
It is "development" until R6, which flips it just before the first supervised agent cycle. Rows already written stay.

    python scripts/append_results_log.py            # append
    python scripts/append_results_log.py --dry-run  # print the rows only
"""

# THE RESULTS LOG OF THIS WORKSPACE
RESULTS_LOG_PATH = Path(__file__).resolve().parents[1] / "docs" / "RESULTS_LOG.md"
# THE PHASE SWITCH (ROADMAP R4; FLIPPED TO "agents" IN R6 BY A ONE-LINE MERGE). A PROTECTED RECORD, NOT A .py FILE:
# THE JUDGE HASH DOES NOT INCLUDE IT, SO FLIPPING IT CHANGES NO JUDGE (so.runner.judge_identity)
AGENT_PHASE_PATH = Path(__file__).resolve().parents[1] / "records" / "agent_phase.txt"
PHASE_DEVELOPMENT_STR = "development"
PHASE_AGENTS_STR = "agents"
PHASE_SET = {PHASE_DEVELOPMENT_STR, PHASE_AGENTS_STR}
# THE TABLE OF GRADED ROWS (IDENTIFIERS, GRADE, REASON; NO NUMBERS)
GRADED_SECTION_STR = "## Graded rows (agent phase: identifiers, grade and reason only)"
GRADED_HEADER_STR = ("| Date | Experiment | Protocol | Run id | Grade | Reason | Note |\n"
                     "|---|---|---|---|---|---|---|")


# FUNCTION: THE CURRENT PHASE
def get_agent_phase_str(phase_path_in=AGENT_PHASE_PATH):
    """
    Args:
        phase_path_in (Path): records/agent_phase.txt

    Returns:
        str: "development" (rows with returns; records may be reset) or "agents" (graded rows only; nothing is reset).
        The first non-comment, non-blank line decides; a missing or unknown value is "agents", the stricter one.
    """
    # COMMENTS START WITH #
    try:
        text_str = Path(phase_path_in).read_text(encoding="utf-8")
    except OSError:
        return PHASE_AGENTS_STR
    for line_str in text_str.splitlines():
        value_str = line_str.split("#", 1)[0].strip().lower()
        if value_str:
            return value_str if value_str in PHASE_SET else PHASE_AGENTS_STR
    return PHASE_AGENTS_STR


# FUNCTION: ONE GRADED ROW (NO NUMBERS)
def get_graded_row_str(report_dict_in, run_id_str_in, note_str_in, date_str_in):
    """
    Args:
        report_dict_in (dict): report.json of the run (grade_dict written by the runner since R4)
        run_id_str_in (str): Run id
        note_str_in (str): The job's note
        date_str_in (str): Date shown

    Returns:
        str: The row
    """
    # A REPORT WITHOUT A GRADE (BEFORE R4) GETS NO GRADE, NOT A GUESS
    grade_dict = report_dict_in.get("grade_dict") or {}
    grade_str = str(grade_dict.get("grade_str") or "no grade recorded")
    reason_str = str(grade_dict.get("reason_str") or "")
    if grade_dict.get("audit_str") == "pending":
        reason_str = f"{reason_str}; audit pending" if "audit" not in reason_str else reason_str
    return (f"| {date_str_in} | {report_dict_in.get('experiment_name_str', '')} | "
            f"{report_dict_in.get('protocol_version_str', '')} | {run_id_str_in} | {grade_str} | "
            f"{reason_str.replace('|', '/')} | {str(note_str_in).replace('|', '/')} |")


# FUNCTION: THE ROWS TO APPEND
def get_new_row_list(path_dict_in, results_log_path_in=RESULTS_LOG_PATH, phase_str_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths (run_index, runs)
        results_log_path_in (Path): docs/RESULTS_LOG.md
        phase_str_in (str | None): "development" (rows with returns) or "agents" (graded rows); None = the switch

    Returns:
        list[str]: Rows for finished runs not yet in the log, in finish order. In the agent phase the first graded
        row is preceded by the graded section header when the log has none yet.
    """
    # FINISHED RUNS THE LOG DOES NOT NAME
    if not os.path.isfile(path_dict_in["run_index"]):
        return []
    phase_str = phase_str_in or get_agent_phase_str()
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
        if phase_str == PHASE_AGENTS_STR:
            row_list.append(get_graded_row_str(report_dict, row.run_id, row.note, str(row.finished_ts)[:10]))
        else:
            row_list.append(get_results_row_str(report_dict, row.run_id, row.note, str(row.finished_ts)[:10]))
        seen_set.add(row.run_id)
    if row_list and phase_str == PHASE_AGENTS_STR and GRADED_SECTION_STR not in log_text_str:
        row_list = ["", GRADED_SECTION_STR, "", GRADED_HEADER_STR] + row_list
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
