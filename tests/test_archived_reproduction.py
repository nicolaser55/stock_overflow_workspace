"""
Workspace Tests: archived-experiment reproduction check (scripts/reproduce_archived.py)

Run from the workspace root:   python tests/test_archived_reproduction.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only, plus a read of the committed notebook outputs (they are not executed). The real trial log is
not written. SO_ALLOW_LEGACY_REPRODUCTION is set only inside subprocesses of this file, and only for the synthetic
fixture. No archived notebook is executed.
"""

import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

# ADD THE WORKSPACE AND THE SCRIPT FOLDER TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "scripts"))
# IMPORT THE REPRODUCTION SCRIPT (IT DOES NOT RUN ON IMPORT)
import reproduce_archived as reproduce

# THE REAL TRIAL LOG, HASHED TO PROVE THESE TESTS DO NOT APPEND TO IT
REAL_TRIAL_LOG_PATH_STR = "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments/trial_log.csv"
REAL_EXPERIMENT_ZONE_STR = "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments"
SCRIPT_PATH_STR = os.path.join(WORKSPACE_PATH_STR, "scripts", "reproduce_archived.py")


# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints a passing check.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")


# FUNCTION: SHA256 OF A FILE
def get_file_sha256_str(path_str_in):
    """
    Hash of a file, or None when it does not exist.

    Args:
        path_str_in (str): File path

    Returns:
        str | None: Hex digest
    """
    # AN ABSENT FILE HAS NO DIGEST
    if not os.path.exists(path_str_in):
        return None
    # HASH IN CHUNKS
    digest = hashlib.sha256()
    with open(path_str_in, "rb") as file_handle:
        while True:
            chunk_bytes = file_handle.read(1024 * 1024)
            if not chunk_bytes:
                break
            digest.update(chunk_bytes)
    return digest.hexdigest()


# FUNCTION: ENVIRONMENT FOR A SUBPROCESS, WITHOUT THE LEGACY FLAG
def get_clean_env_dict():
    """
    A copy of the environment with the data-root override, the zone override and the legacy flag removed.

    Returns:
        dict: Environment
    """
    # DROP OVERRIDES SO THE CHILD SEES THE DEFAULT PATHS
    env_dict = os.environ.copy()
    env_dict.pop("SO_DATA_PATH", None)
    env_dict.pop("SO_EXPERIMENT_ZONE_PATH", None)
    env_dict.pop("SO_ALLOW_LEGACY_REPRODUCTION", None)
    env_dict["PYTHONIOENCODING"] = "utf-8"
    env_dict["PYTHONPATH"] = WORKSPACE_PATH_STR
    return env_dict


# FUNCTION: RUN THE REPRODUCTION SCRIPT
def run_script_result(argument_list_in, env_dict_in):
    """
    Runs scripts/reproduce_archived.py and captures its text.

    Args:
        argument_list_in (list[str]): Arguments
        env_dict_in (dict): Environment

    Returns:
        subprocess.CompletedProcess: The finished process
    """
    # THE VENV INTERPRETER, SO THE SUITE AND THE SCRIPT SHARE ONE PYTHON
    return subprocess.run([sys.executable, SCRIPT_PATH_STR, *argument_list_in], cwd=WORKSPACE_PATH_STR, env=env_dict_in,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


# FUNCTION: WRITE A ONE-CELL NOTEBOOK WITH A FIXED STDOUT
def write_fake_notebook(folder_str_in, cell_text_str_in):
    """
    Writes notebook.ipynb with one code cell whose stdout is the given text.

    Args:
        folder_str_in (str): Folder
        cell_text_str_in (str): Stdout, including the trailing newline

    Returns:
        str: Notebook path
    """
    # A MINIMAL NBFORMAT-4 NOTEBOOK
    notebook_dict = {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": [{
            "cell_type": "code",
            "id": "cell01",
            "metadata": {},
            "execution_count": 1,
            "source": ["print('headline')\n"],
            "outputs": [{"output_type": "stream", "name": "stdout", "text": [cell_text_str_in]}],
        }],
    }
    notebook_path_str = os.path.join(folder_str_in, "notebook.ipynb")
    with open(notebook_path_str, "w", encoding="utf-8", newline="\n") as notebook_file:
        json.dump(notebook_dict, notebook_file)
    return notebook_path_str


# FUNCTION: WRITE A ONE-ROW EXPECTED CSV FOR THE FAKE NOTEBOOK
def write_fake_expected_csv(folder_str_in, value_str_in):
    """
    expected.csv whose pattern reads the fake notebook's total-return line.

    Args:
        folder_str_in (str): Folder
        value_str_in (str): Expected total return

    Returns:
        str: CSV path
    """
    # THE PATTERN IS A COLUMN SO THE FIXTURE DOES NOT USE THE ARCHIVED TABLE
    csv_path_str = os.path.join(folder_str_in, "expected.csv")
    with open(csv_path_str, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["experiment", "notebook", "cell_id", "label", "value", "precision", "pattern"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({
            "experiment": "fake",
            "notebook": "notebook.ipynb",
            "cell_id": "cell01",
            "label": "prior-only total return",
            "value": value_str_in,
            "precision": "2",
            "pattern": r"Total return:\tpath ([0-9.]+)%",
        })
    return csv_path_str


# FUNCTION: TEST THAT THE SCRIPT REFUSES TO START WITHOUT THE FLAG
def test_flag_refused():
    """
    Without SO_ALLOW_LEGACY_REPRODUCTION=1 the script exits non-zero and does not touch the real trial log.

    Returns:
        None
    """
    # HASH THE REAL LOG, THEN RUN WITH THE FLAG ABSENT
    before_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    result = run_script_result([], get_clean_env_dict())
    after_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    assert result.returncode != 0
    assert "Refusing to run" in result.stdout
    assert before_str == after_str
    passed("the script refuses to run without SO_ALLOW_LEGACY_REPRODUCTION=1")


# FUNCTION: TEST THAT A ZONE POINTED AT THE REAL FOLDER IS REFUSED
def test_real_zone_refused():
    """
    SO_EXPERIMENT_ZONE_PATH set to store04_experiments is refused before any notebook runs.

    Returns:
        None
    """
    # THE FLAG IS SET, AND THE ZONE IS THE REAL ONE
    before_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    env_dict = get_clean_env_dict()
    env_dict["SO_ALLOW_LEGACY_REPRODUCTION"] = "1"
    env_dict["SO_EXPERIMENT_ZONE_PATH"] = REAL_EXPERIMENT_ZONE_STR
    result = run_script_result(["--fixtures", os.path.join(tempfile.gettempdir(), "so_reproduce_missing")], env_dict)
    after_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    assert result.returncode != 0
    assert "real or the default" in result.stdout
    assert before_str == after_str
    passed("a zone pointed at the real experiment folder is refused")


# FUNCTION: TEST THE EXPERIMENT-ZONE OVERRIDE IN so.paths
def test_experiment_zone_override():
    """
    Unset, the zone is store04_experiments. Set, writes go to that folder and the real trial log is unchanged.

    Returns:
        None
    """
    # THE DEFAULT PATH, WITH NOTHING WRITTEN
    before_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    default_code_str = (
        "import os, sys\n"
        "sys.path.insert(0, os.environ['WORKSPACE'])\n"
        "from so import paths\n"
        "print(paths.LOCAL_EXPERIMENTZONE_PATH_STR)\n"
        "print(paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)\n"
    )
    default_env_dict = get_clean_env_dict()
    default_env_dict["WORKSPACE"] = WORKSPACE_PATH_STR
    default_result = subprocess.run([sys.executable, "-c", default_code_str], cwd=WORKSPACE_PATH_STR, env=default_env_dict,
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert default_result.returncode == 0, default_result.stderr
    default_line_list = default_result.stdout.strip().splitlines()
    assert default_line_list[0] == "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments/"
    assert default_line_list[1] == "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments/trial_log.csv"
    # A BLANK OVERRIDE IS THE SAME DEFAULT
    blank_env_dict = dict(default_env_dict)
    blank_env_dict["SO_EXPERIMENT_ZONE_PATH"] = ""
    blank_result = subprocess.run([sys.executable, "-c", default_code_str], cwd=WORKSPACE_PATH_STR, env=blank_env_dict,
                                  capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert blank_result.returncode == 0, blank_result.stderr
    assert blank_result.stdout.strip().splitlines()[0] == default_line_list[0]
    # THE OVERRIDE: WRITE A PROBE AND A TRIAL LOG INTO A TEMPORARY ZONE
    zone_str = tempfile.mkdtemp(prefix="so_zone_override_")
    override_code_str = (
        "import os, sys\n"
        "sys.path.insert(0, os.environ['WORKSPACE'])\n"
        "from so import paths\n"
        "print(paths.LOCAL_EXPERIMENTZONE_PATH_STR)\n"
        "print(paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)\n"
        "probe_str = paths.get_experiment_data_path_str('probe_reproduction', 'step00')\n"
        "os.makedirs(probe_str, exist_ok=True)\n"
        "open(probe_str + 'probe.csv', 'w', encoding='utf-8').write('probe\\n')\n"
        "open(paths.LOCAL_TRIAL_LOG_FILE_PATH_STR, 'w', encoding='utf-8').write('probe\\n')\n"
    )
    override_env_dict = get_clean_env_dict()
    override_env_dict["WORKSPACE"] = WORKSPACE_PATH_STR
    override_env_dict["SO_EXPERIMENT_ZONE_PATH"] = zone_str
    override_result = subprocess.run([sys.executable, "-c", override_code_str], cwd=WORKSPACE_PATH_STR, env=override_env_dict,
                                     capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert override_result.returncode == 0, override_result.stderr
    printed_list = override_result.stdout.strip().splitlines()
    zone_norm_str = os.path.normcase(os.path.abspath(zone_str))
    assert os.path.normcase(os.path.abspath(printed_list[0].rstrip("/"))) == zone_norm_str
    assert os.path.normcase(os.path.abspath(printed_list[1])) == os.path.normcase(os.path.abspath(os.path.join(zone_str, "trial_log.csv")))
    assert os.path.exists(os.path.join(zone_str, "probe_reproduction", "step00", "probe.csv"))
    assert os.path.exists(os.path.join(zone_str, "trial_log.csv"))
    # NOTHING LANDED IN THE REAL ZONE
    assert not os.path.exists(os.path.join(REAL_EXPERIMENT_ZONE_STR, "probe_reproduction"))
    assert get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR) == before_str
    shutil.rmtree(zone_str, ignore_errors=True)
    passed("SO_EXPERIMENT_ZONE_PATH redirects the zone and the trial log; the default folder is unchanged")


# FUNCTION: TEST EXTRACTION AND A MATCHING FIXTURE
def test_fake_notebook_matches():
    """
    A tiny notebook's printed total return matches the fixture table, and the real trial log is unchanged.

    Returns:
        None
    """
    # BUILD THE FIXTURE AND RUN THE SCRIPT WITH THE FLAG, IN A TEMPORARY ZONE
    before_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    folder_str = tempfile.mkdtemp(prefix="so_reproduce_match_")
    zone_str = tempfile.mkdtemp(prefix="so_reproduce_match_zone_")
    try:
        write_fake_notebook(folder_str, "Total return:\tpath 10.00% | buy & hold 20.00%\n")
        write_fake_expected_csv(folder_str, "10.00")
        report_str = os.path.join(folder_str, "report.csv")
        env_dict = get_clean_env_dict()
        env_dict["SO_ALLOW_LEGACY_REPRODUCTION"] = "1"
        env_dict["SO_EXPERIMENT_ZONE_PATH"] = zone_str
        result = run_script_result(["--fixtures", folder_str, "--report", report_str], env_dict)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "1 match, 0 mismatch" in result.stdout
        with open(report_str, newline="", encoding="utf-8") as report_file:
            report_row = next(csv.DictReader(report_file))
        assert report_row["expected"] == "10.00"
        assert report_row["reproduced"] == "10.00"
        assert report_row["match"] == "True"
        assert get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR) == before_str
        assert not os.path.exists(os.path.join(REAL_EXPERIMENT_ZONE_STR, "trial_log.csv")) or get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR) == before_str
    finally:
        shutil.rmtree(folder_str, ignore_errors=True)
        shutil.rmtree(zone_str, ignore_errors=True)
    passed("a fake notebook's printed total return matches at the recorded precision")


# FUNCTION: TEST THAT A MISMATCH IS A NON-ZERO EXIT
def test_fake_notebook_mismatch():
    """
    The same print compared with a different expected value exits non-zero.

    Returns:
        None
    """
    # THE PRINT IS 10.00 AND THE TABLE SAYS 11.00
    before_str = get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR)
    folder_str = tempfile.mkdtemp(prefix="so_reproduce_mismatch_")
    zone_str = tempfile.mkdtemp(prefix="so_reproduce_mismatch_zone_")
    try:
        write_fake_notebook(folder_str, "Total return:\tpath 10.00% | buy & hold 20.00%\n")
        write_fake_expected_csv(folder_str, "11.00")
        report_str = os.path.join(folder_str, "report.csv")
        env_dict = get_clean_env_dict()
        env_dict["SO_ALLOW_LEGACY_REPRODUCTION"] = "1"
        env_dict["SO_EXPERIMENT_ZONE_PATH"] = zone_str
        result = run_script_result(["--fixtures", folder_str, "--report", report_str], env_dict)
        assert result.returncode != 0, result.stdout
        assert "0 match, 1 mismatch" in result.stdout
        with open(report_str, newline="", encoding="utf-8") as report_file:
            report_row = next(csv.DictReader(report_file))
        assert report_row["match"] == "False"
        assert report_row["reproduced"] == "10.00"
        assert get_file_sha256_str(REAL_TRIAL_LOG_PATH_STR) == before_str
    finally:
        shutil.rmtree(folder_str, ignore_errors=True)
        shutil.rmtree(zone_str, ignore_errors=True)
    passed("a mismatch exits non-zero")


# FUNCTION: TEST --list AND THE DEPENDENCY ORDER
def test_list_order():
    """
    --list prints the notebooks in dependency order. --only exp13 also includes exp12 step 02. --only exp05 does not.

    Returns:
        None
    """
    # THE FULL LIST
    env_dict = get_clean_env_dict()
    env_dict["SO_ALLOW_LEGACY_REPRODUCTION"] = "1"
    full_result = run_script_result(["--list"], env_dict)
    assert full_result.returncode == 0, full_result.stderr
    full_text_str = full_result.stdout
    assert full_text_str.index("experiments/exp01_minute_entry/step01_model_dataset.ipynb") < full_text_str.index("experiments/exp01_minute_entry/step02_signal_check.ipynb")
    assert full_text_str.index("experiments/exp03_ath_exit/step02_walk_forward.ipynb") < full_text_str.index("experiments/exp04_trend_exit/step02_continuous_replay.ipynb")
    assert full_text_str.index("experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb") < full_text_str.index("experiments/exp13_e1m1_robustness/step01_stress_2005_2014.ipynb")
    # exp05 ALONE DOES NOT PULL exp03 (THE SCHEDULE CHECK IS SKIPPED WHEN THAT FILE IS ABSENT)
    only_result = run_script_result(["--list", "--only", "exp05"], env_dict)
    assert only_result.returncode == 0, only_result.stderr
    assert "exp05_vol_scaled_exposure" in only_result.stdout
    assert "exp03_ath_exit" not in only_result.stdout
    # exp13 READS exp12's SAVED PERIODS
    exp13_result = run_script_result(["--list", "--only", "exp13"], env_dict)
    assert exp13_result.returncode == 0, exp13_result.stderr
    assert "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb" in exp13_result.stdout
    assert exp13_result.stdout.index("step02_continuous_replay.ipynb") < exp13_result.stdout.index("step01_stress_2005_2014.ipynb")
    passed("--list follows the dependency order")


# FUNCTION: TEST THAT THE EXPECTED TABLE MATCHES THE COMMITTED NOTEBOOKS
def test_committed_outputs_match_expected_table():
    """
    Every shipped figure is extracted once from the committed notebook and rounds to the expected value.
    The notebooks are not executed.

    Returns:
        None
    """
    # THE FLAG STAYS UNSET: THIS ONLY READS SAVED OUTPUTS
    assert os.environ.get("SO_ALLOW_LEGACY_REPRODUCTION") != "1"
    expected_row_list = reproduce.read_expected_row_list(reproduce.EXPECTED_CSV_PATH)
    pattern_dict = reproduce.get_figure_pattern_dict()
    csv_key_set = {(row["notebook"], row["cell_id"], row["label"]) for row in expected_row_list}
    assert csv_key_set == set(pattern_dict)
    comparison_row_list = reproduce.compare_figure_row_list(expected_row_list, reproduce.WORKSPACE_PATH, pattern_dict)
    failed_list = [row for row in comparison_row_list if row["match"] != "True"]
    assert not failed_list, failed_list[:5]
    passed(f"committed notebook outputs match the expected table ({len(expected_row_list)} numbers)")


# RUN THE TESTS
if __name__ == "__main__":
    test_flag_refused()
    test_real_zone_refused()
    test_experiment_zone_override()
    test_fake_notebook_matches()
    test_fake_notebook_mismatch()
    test_list_order()
    test_committed_outputs_match_expected_table()
