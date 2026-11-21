#!/usr/bin/env python3
"""
vm/check_hashes.py (2026-11-21): step 5 of claude/DESIGN_2026-11-18_linux_vm.md (section 6). For one runner clone and
one data root, prints the judge hash, every design's folder hash and helper hash with whether the trial log or
records/legacy/registered_versions.csv already holds it, and the reset-marker status. It calls the clone's own
functions (so.runner.judge_identity, so.runner.run, so.runner.preregistration); nothing is copied. No commit, host,
path or time is printed, so the Windows runner clone and the VM's runner clone must print the same bytes.

    Windows:  <workspace>\\venv-main\\Scripts\\python.exe -I -B vm\\check_hashes.py --workspace D:\\stock_overflow\\runner_workspace `
                  --data D:\\stock_overflow\\data --out C:\\Users\\nico\\Desktop\\hashes_windows.txt
    so-vm:    /opt/so/venvs/main/bin/python -I -B ~/workspace/vm/check_hashes.py --workspace /srv/so/runner_workspace \\
                  --data /srv/so/data --out ~/hashes_vm.txt

-I keeps the script's own folder and PYTHON* variables out; -B writes no __pycache__ into the clone (nico only reads
it on the VM). The clone's folder goes first on sys.path, and the script stops if "so" comes from anywhere else (the
venv's editable install points at nico's workspace). It refuses to run when the complete-data root is set, with the
runner's own guard (so.paths.check_quarantine_refused). It reads the trial log, registered_versions.csv and the reset
marker the way the runner does; it writes only --out.

Exit 0 when the judge hash starts with --expect-judge (default 5b2eb368), every design's folder hash is logged for its
version, every helper hash is logged where its version logged any, and the reset marker does not mismatch (no
marker is what the runner accepts too; both systems must print the same). Otherwise 1.
"""
import argparse
import ast
import hashlib
import os
import subprocess
import sys


def get_config_value_dict(config_path_str):
    """EXPERIMENT_NAME and PROTOCOL_VERSION from an experiment's config.py, parsed (the design code is not run)."""
    with open(config_path_str, "r", encoding="utf-8") as config_file:
        tree = ast.parse(config_file.read(), filename=config_path_str)
    value_dict = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if node.targets[0].id in ("EXPERIMENT_NAME", "PROTOCOL_VERSION") and isinstance(node.value, ast.Constant):
                value_dict[node.targets[0].id] = str(node.value.value)
    return value_dict


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True, help="the runner clone")
    parser.add_argument("--data", required=True, help="the data root (SO_DATA_PATH)")
    parser.add_argument("--out", required=True, help="the output file (also printed)")
    parser.add_argument("--expect-judge", default="5b2eb368")
    args = parser.parse_args()
    workspace_str = os.path.abspath(args.workspace)
    os.environ["SO_DATA_PATH"] = os.path.abspath(args.data)
    sys.path.insert(0, workspace_str)
    import so
    so_folder_str = os.path.normcase(os.path.dirname(os.path.abspath(so.__file__)))
    if so_folder_str != os.path.normcase(os.path.join(workspace_str, "so")):
        raise SystemExit(f"STOP: 'so' was imported from {so_folder_str}, not from {workspace_str}")
    from so import paths
    paths.check_quarantine_refused()
    from so.runner.judge_identity import get_judge_hash_dict
    from so.runner.run import get_design_folder_hash_str
    from so.runner.preregistration import (check_reset_marker_dict, get_design_helper_dict, get_logged_helper_dict,
                                           get_logged_version_dict, get_merged_set_dict, get_registered_version_tuple,
                                           get_registered_versions_path_str)
    try:
        commit_str = subprocess.run(["git", "-C", workspace_str, "log", "--oneline", "-1"], check=True,
                                    stdout=subprocess.PIPE, text=True).stdout.strip()
        status_str = subprocess.run(["git", "-C", workspace_str, "status", "--porcelain"], check=True,
                                    stdout=subprocess.PIPE, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as error:
        commit_str, status_str = f"unknown ({type(error).__name__})", "unknown"
    print(f"(not in the output) clone at {commit_str}; git status {'clean' if status_str == '' else 'NOT CLEAN'}",
          file=sys.stderr)

    line_list, fail_int = [], 0
    judge_dict = get_judge_hash_dict(workspace_str)
    judge_ok_bool = judge_dict["judge_hash"].startswith(args.expect_judge)
    fail_int += 0 if judge_ok_bool else 1
    line_list.append(f"judge {judge_dict['judge_hash']} files {judge_dict['judge_file_count']} "
                     f"{'OK' if judge_ok_bool else 'FAIL expected ' + args.expect_judge}")
    trial_log_str = paths.get_named_data_path_str("LOCAL_TRIAL_LOG_FILE_PATH_STR")
    registered_str = get_registered_versions_path_str()
    line_list.append(f"trial log {'present' if os.path.isfile(trial_log_str) else 'MISSING'}; "
                     f"registered_versions.csv {'present' if os.path.isfile(registered_str) else 'MISSING'}")
    if not os.path.isfile(trial_log_str) or not os.path.isfile(registered_str):
        fail_int += 1
    experiments_str = os.path.join(workspace_str, "experiments")
    design_count_int = 0
    for name_str in sorted(os.listdir(experiments_str)):
        folder_str = os.path.join(experiments_str, name_str)
        design_str = os.path.join(folder_str, "design.py")
        config_str = os.path.join(folder_str, "config.py")
        if not (name_str.startswith("exp") and os.path.isfile(design_str) and os.path.isfile(config_str)):
            continue
        design_count_int += 1
        value_dict = get_config_value_dict(config_str)
        experiment_str = value_dict.get("EXPERIMENT_NAME", "?")
        version_str = value_dict.get("PROTOCOL_VERSION", "?")
        folder_hash_str = get_design_folder_hash_str(folder_str)
        helper_hash_str = get_design_helper_dict(design_str, workspace_str)["helper_hash"]
        registered_folder_dict, registered_helper_dict = get_registered_version_tuple(registered_str, experiment_str)
        folder_set = get_merged_set_dict(get_logged_version_dict(trial_log_str, experiment_str),
                                         registered_folder_dict).get(version_str, set())
        helper_set = get_merged_set_dict(get_logged_helper_dict(trial_log_str, experiment_str),
                                         registered_helper_dict).get(version_str, set())
        folder_ok_bool = folder_hash_str in folder_set
        helper_word_str = "logged" if helper_hash_str in helper_set else ("none logged" if not helper_set else "NOT LOGGED")
        fail_int += (0 if folder_ok_bool else 1) + (1 if helper_word_str == "NOT LOGGED" else 0)
        line_list.append(f"design {name_str} name {experiment_str} version {version_str} "
                         f"folder {folder_hash_str} {'logged' if folder_ok_bool else 'NOT LOGGED'} "
                         f"helper {helper_hash_str} {helper_word_str}")
    try:
        marker_str = check_reset_marker_dict(None, workspace_str)["status_str"]
    except ValueError as error:
        marker_str = f"MISMATCH ({str(error)[:120]})"
    fail_int += 1 if marker_str.startswith("MISMATCH") else 0
    line_list.append(f"reset marker {marker_str}")
    line_list.append(f"{design_count_int} designs, {fail_int} FAIL")
    content_bytes = ("\n".join(line_list) + "\n").encode("utf-8")
    with open(args.out, "wb") as out_file:
        out_file.write(content_bytes)
    sys.stdout.write(content_bytes.decode("utf-8"))
    print(f"(not in the output) output sha256 {hashlib.sha256(content_bytes).hexdigest()}", file=sys.stderr)
    return 1 if fail_int else 0


if __name__ == "__main__":
    sys.exit(main())
