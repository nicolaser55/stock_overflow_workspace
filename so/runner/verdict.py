import json
import os
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (THRESHOLDS, DISPLAY)
from so import config, paths
# IMPORT THE SUCCESS CRITERIA AND THE ROLLING MONTH WINDOWS
from so.core.evaluation import (get_chained_daily_return_pdf, get_success_criteria_dict, get_rolling_month_window_pdf,
                                get_report_float_str)

"""
Runner Verdict, Report And Manifest (infrastructure step 4b-1b)

One shared function, applied to the prior-only path:

    return       total return >= buy-and-hold passes; between 90% and 100% of buy-and-hold passes only with a
                 smaller max drawdown or a higher Sharpe; below 90% fails. Numbers come from
                 so.core.evaluation.get_success_criteria_dict (comparable floor, Sharpe, drawdown).
    consistency  ahead of buy-and-hold on at least 60% of rolling 12-month windows, stepped monthly.
    baselines    total return strictly above the constant-exposure baseline and above at least 95% of the random
                 draws.
    look-ahead   "pass" or "fail" from the automatic truncation and perturbation check (4b-1c). "pending" is not a
                 pass (only used when that check is skipped).

The verdict is "email-worthy" only if every part passes. look-ahead "pending" is not a pass. Otherwise
"not email-worthy", listing what failed.

report.json holds every number behind the verdict. report.md is a short readable summary. manifest.json is written
last, so a manifest only exists for a finished run.
"""

# FILES WRITTEN IN THE RUN FOLDER
REPORT_JSON_FILE_STR = "report.json"
REPORT_MD_FILE_STR = "report.md"
MANIFEST_FILE_STR = "manifest.json"
MANIFEST_TMP_FILE_STR = "manifest.json.tmp"
# LOOK-AHEAD STATUSES (4B-1C FILLS PASS OR FAIL)
LOOK_AHEAD_PENDING_STR = "pending"
LOOK_AHEAD_PASS_STR = "pass"
LOOK_AHEAD_FAIL_STR = "fail"
LOOK_AHEAD_STATUS_SET = {LOOK_AHEAD_PENDING_STR, LOOK_AHEAD_PASS_STR, LOOK_AHEAD_FAIL_STR}
# VERDICT LABELS
EMAIL_WORTHY_STR = "email-worthy"
NOT_EMAIL_WORTHY_STR = "not email-worthy"


# FUNCTION: JSON-SAFE SCALARS AND NESTED STRUCTURES
def get_json_value(value_in):
    """
    NaN and Inf become None. DataFrames become lists of row dicts.

    Args:
        value_in: Any value

    Returns:
        object: JSON-serializable value
    """
    # LEAVES
    if value_in is None:
        return None
    if isinstance(value_in, (bool, str)):
        return value_in
    if isinstance(value_in, (np.bool_,)):
        return bool(value_in)
    if isinstance(value_in, (int, np.integer)):
        return int(value_in)
    if isinstance(value_in, (float, np.floating)):
        value_float = float(value_in)
        return value_float if np.isfinite(value_float) else None
    if isinstance(value_in, pd.Timestamp):
        return None if pd.isna(value_in) else str(value_in.date())
    if isinstance(value_in, dict):
        return {str(key): get_json_value(value) for key, value in value_in.items()}
    if isinstance(value_in, pd.DataFrame):
        return get_json_value(value_in.to_dict(orient="records"))
    if isinstance(value_in, (list, tuple, np.ndarray)):
        return [get_json_value(value) for value in list(value_in)]
    return str(value_in)


# FUNCTION: THE VIEW.json STAMP IN A DATA ROOT
def get_view_stamp_dict(root_str_in=None):
    """
    window_start and built_ts when VIEW.json is present and readable. None when the file is missing. A broken file
    is None as well: the run guard check_development_view already refused a stale stamp when that check is on.

    Args:
        root_str_in (str | None): Data root (None = the development SO_DATA_PATH root)

    Returns:
        dict | None: Stamp fields, or None
    """
    # THE CALLER PASSES THE QUARANTINE ROOT ON A HOLDOUT RUN; DEVELOPMENT LEAVES THIS AT THE VIEW
    root_str = paths.get_data_root_str() if root_str_in is None else str(root_str_in)
    view_path_str = root_str.rstrip("\\/") + "/VIEW.json"
    if not os.path.isfile(view_path_str):
        return None
    try:
        with open(view_path_str, "r", encoding="utf-8") as view_file:
            view_dict = json.load(view_file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(view_dict, dict):
        return None
    return {"window_start": view_dict.get("window_start"), "built_ts": view_dict.get("built_ts"),
            "window_id": view_dict.get("window_id"), "window_end": view_dict.get("window_end")}


# FUNCTION: WRITE A JSON FILE (UTF-8, INDENTED)
def write_json_file(file_path_str_in, payload_in):
    """
    Overwrites the file. Used only for files this run created.

    Args:
        file_path_str_in (str): Path
        payload_in (dict | list): JSON payload

    Returns:
        None
    """
    # THE FOLDER IS CREATED HERE
    os.makedirs(os.path.dirname(file_path_str_in), exist_ok=True)
    with open(file_path_str_in, "w", encoding="utf-8") as json_file:
        json.dump(get_json_value(payload_in), json_file, indent=2)
        json_file.write("\n")


# FUNCTION: THE RETURN PART OF THE VERDICT
def get_return_verdict_dict(success_dict_in):
    """
    >= buy-and-hold passes. The 90-100% band (comparable_return, strictly below buy-and-hold) passes only with a
    smaller max drawdown or a higher Sharpe. Below 90% fails.

    Args:
        success_dict_in (dict): Output of get_success_criteria_dict

    Returns:
        dict: pass_bool, reason_str, and the numbers
    """
    # THE NUMBERS ARE ALREADY COMPUTED
    strategy_return = float(success_dict_in["strategy_total_return"])
    buy_hold_return = float(success_dict_in["buy_hold_total_return"])
    comparable_bool = bool(success_dict_in["comparable_return"])
    secondary_bool = bool(success_dict_in["secondary_success"])
    if strategy_return >= buy_hold_return:
        pass_bool, reason_str = True, "total_return_at_least_buy_hold"
    elif comparable_bool and secondary_bool:
        pass_bool, reason_str = True, "comparable_with_secondary"
    elif comparable_bool:
        pass_bool, reason_str = False, "comparable_without_secondary"
    else:
        pass_bool, reason_str = False, "below_comparable"
    return {"pass_bool": bool(pass_bool), "reason_str": reason_str, "strategy_total_return": strategy_return,
            "buy_hold_total_return": buy_hold_return, "comparable_return": comparable_bool,
            "comparable_floor": float(success_dict_in["comparable_floor"]),
            "strategy_sharpe_ratio": float(success_dict_in["strategy_sharpe_ratio"]),
            "buy_hold_sharpe_ratio": float(success_dict_in["buy_hold_sharpe_ratio"]),
            "strategy_max_drawdown": float(success_dict_in["strategy_max_drawdown"]),
            "buy_hold_max_drawdown": float(success_dict_in["buy_hold_max_drawdown"]),
            "secondary_sharpe": bool(success_dict_in["secondary_sharpe"]),
            "secondary_drawdown": bool(success_dict_in["secondary_drawdown"]),
            "secondary_success": secondary_bool}


# FUNCTION: THE CONSISTENCY PART OF THE VERDICT
def get_consistency_verdict_dict(strategy_return_pdf_in, buy_hold_return_pdf_in,
                                 window_months_in=None, step_months_in=None, min_share_in=None):
    """
    Ahead of buy-and-hold on at least 60% of rolling 12-month windows, stepped monthly. Zero windows fail.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): date, daily_return
        window_months_in, step_months_in (int | None): Window and step (None = config)
        min_share_in (float | None): Required share (None = config)

    Returns:
        dict: pass_bool, window_count, ahead_count, ahead_share, min_share, window_pdf
    """
    # THE SHARED ROLLING-MONTH TABLE
    window_int = int(config.RUNNER_CONSISTENCY_WINDOW_MONTHS if window_months_in is None else window_months_in)
    step_int = int(config.RUNNER_CONSISTENCY_STEP_MONTHS if step_months_in is None else step_months_in)
    min_share = float(config.RUNNER_CONSISTENCY_MIN_SHARE if min_share_in is None else min_share_in)
    window_pdf = get_rolling_month_window_pdf(strategy_return_pdf_in, buy_hold_return_pdf_in, window_int, step_int)
    window_count = int(len(window_pdf))
    ahead_count = int(window_pdf["ahead_bool"].sum()) if window_count else 0
    ahead_share = float(ahead_count / window_count) if window_count else float("nan")
    pass_bool = bool(window_count > 0 and ahead_share >= min_share)
    return {"pass_bool": pass_bool, "window_count": window_count, "ahead_count": ahead_count,
            "ahead_share": ahead_share, "min_share": min_share, "window_months": window_int, "step_months": step_int,
            "window_pdf": window_pdf}


# FUNCTION: THE BASELINE PART OF THE VERDICT
def get_baseline_verdict_dict(strategy_total_return_in, baseline_dict_in, beat_share_in=None):
    """
    Strictly above the constant-exposure total return, and strictly above at least 95% of the random draws.

    Args:
        strategy_total_return_in (float): Prior-only total return
        baseline_dict_in (dict): Output of get_runner_baseline_dict
        beat_share_in (float | None): Required share of random draws (None = config)

    Returns:
        dict: pass_bool, constant and random comparisons
    """
    # THE PATH MUST BE STRICTLY ABOVE EACH COMPARISON
    min_share = float(config.RUNNER_RANDOM_TIMING_BEAT_SHARE if beat_share_in is None else beat_share_in)
    strategy_return = float(strategy_total_return_in)
    constant_return = float(baseline_dict_in["constant_exposure_total_return"])
    random_list = [float(value) for value in list(baseline_dict_in.get("random_timing_return_list") or [])]
    random_count = int(len(random_list))
    beaten_count = int(sum(value < strategy_return for value in random_list))
    beaten_share = float(beaten_count / random_count) if random_count else float("nan")
    constant_pass_bool = bool(strategy_return > constant_return)
    random_pass_bool = bool(random_count > 0 and beaten_share >= min_share)
    return {"pass_bool": bool(constant_pass_bool and random_pass_bool),
            "constant_exposure_total_return": constant_return,
            "constant_exposure_weight": float(baseline_dict_in.get("constant_exposure_weight", np.nan)),
            "constant_pass_bool": constant_pass_bool,
            "random_timing_return_list": random_list, "random_timing_count": random_count,
            "random_timing_beaten_count": beaten_count, "random_timing_beaten_share": beaten_share,
            "random_timing_min_share": min_share, "random_pass_bool": random_pass_bool,
            "random_timing_switch_count": int(baseline_dict_in.get("random_timing_switch_count", 0)),
            "random_timing_seed_list": list(baseline_dict_in.get("random_timing_seed_list") or []),
            "buy_hold_total_return": float(baseline_dict_in.get("buy_hold_total_return", np.nan))}


# FUNCTION: THE LOOK-AHEAD PART OF THE VERDICT
def get_look_ahead_verdict_dict(status_str_in=LOOK_AHEAD_PENDING_STR):
    """
    The automatic look-ahead check fills pass or fail. pending is not a pass.

    Args:
        status_str_in (str): pending, pass, or fail

    Returns:
        dict: status_str, pass_bool
    """
    # UNKNOWN STATUSES ARE TREATED AS PENDING
    status_str = str(status_str_in) if status_str_in in LOOK_AHEAD_STATUS_SET else LOOK_AHEAD_PENDING_STR
    return {"status_str": status_str, "pass_bool": bool(status_str == LOOK_AHEAD_PASS_STR)}


# FUNCTION: THE SHARED VERDICT ON THE PRIOR-ONLY PATH
def get_runner_verdict_dict(strategy_return_pdf_in, buy_hold_return_pdf_in, baseline_dict_in,
                            look_ahead_status_str_in=LOOK_AHEAD_PENDING_STR):
    """
    One decision rule. email-worthy only if return, consistency, baselines and look-ahead all pass.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): date, daily_return
        baseline_dict_in (dict): Output of get_runner_baseline_dict
        look_ahead_status_str_in (str): pending, pass, or fail

    Returns:
        dict: parts, failed_list, email_worthy_bool, label_str, success_dict
    """
    # RETURN NUMBERS FROM THE EXISTING SUCCESS CRITERIA
    success_dict = get_success_criteria_dict(strategy_return_pdf_in, buy_hold_return_pdf_in)
    return_dict = get_return_verdict_dict(success_dict)
    consistency_dict = get_consistency_verdict_dict(strategy_return_pdf_in, buy_hold_return_pdf_in)
    baseline_verdict_dict = get_baseline_verdict_dict(return_dict["strategy_total_return"], baseline_dict_in)
    look_ahead_dict = get_look_ahead_verdict_dict(look_ahead_status_str_in)
    failed_list = []
    if not return_dict["pass_bool"]:
        failed_list.append("return")
    if not consistency_dict["pass_bool"]:
        failed_list.append("consistency")
    if not baseline_verdict_dict["pass_bool"]:
        failed_list.append("baselines")
    if not look_ahead_dict["pass_bool"]:
        failed_list.append("look-ahead")
    email_worthy_bool = len(failed_list) == 0
    return {"return_dict": return_dict, "consistency_dict": consistency_dict, "baseline_dict": baseline_verdict_dict,
            "look_ahead_dict": look_ahead_dict, "failed_list": failed_list,
            "email_worthy_bool": bool(email_worthy_bool),
            "label_str": EMAIL_WORTHY_STR if email_worthy_bool else NOT_EMAIL_WORTHY_STR,
            "success_dict": success_dict}


# FUNCTION: DAILY RETURNS OF ONE EQUITY CURVE THAT STARTED AT INITIAL CAPITAL
def get_equity_daily_return_pdf(daily_equity_pdf_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Args:
        daily_equity_pdf_in (pd.DataFrame): date, equity
        initial_capital_in (float): Starting capital

    Returns:
        pd.DataFrame: date, daily_return
    """
    # THE SAME CHAINING THE SUCCESS CRITERIA ALREADY USE
    return get_chained_daily_return_pdf([daily_equity_pdf_in], initial_capital_in)


# FUNCTION: THE REPORT PAYLOAD (EVERY NUMBER BEHIND THE VERDICT)
def get_report_payload_dict(verdict_dict_in, extra_dict_in=None):
    """
    Args:
        verdict_dict_in (dict): Output of get_runner_verdict_dict
        extra_dict_in (dict | None): Run identity fields folded in

    Returns:
        dict: JSON payload
    """
    # THE PARTS STAY NESTED SO 4B-1C CAN ADD LOOK-AHEAD NUMBERS IN PLACE
    payload_dict = {"label_str": verdict_dict_in["label_str"],
                    "email_worthy_bool": bool(verdict_dict_in["email_worthy_bool"]),
                    "failed_list": list(verdict_dict_in["failed_list"]),
                    "return_dict": dict(verdict_dict_in["return_dict"]),
                    "consistency_dict": dict(verdict_dict_in["consistency_dict"]),
                    "baseline_dict": dict(verdict_dict_in["baseline_dict"]),
                    "look_ahead_dict": dict(verdict_dict_in["look_ahead_dict"]),
                    "success_dict": dict(verdict_dict_in["success_dict"])}
    if extra_dict_in:
        payload_dict.update(dict(extra_dict_in))
    return payload_dict


# FUNCTION: A SHORT MARKDOWN SUMMARY OF THE VERDICT
def get_report_markdown_str(report_dict_in):
    """
    Args:
        report_dict_in (dict): Output of get_report_payload_dict

    Returns:
        str: Markdown
    """
    # DISPLAY NUMBERS USE THE SHARED REPORT DECIMALS
    return_dict = report_dict_in["return_dict"]
    consistency_dict = report_dict_in["consistency_dict"]
    baseline_dict = report_dict_in["baseline_dict"]
    look_ahead_dict = report_dict_in["look_ahead_dict"]
    run_id_str = str(report_dict_in.get("run_id_str") or "")
    experiment_str = str(report_dict_in.get("experiment_name_str") or "")
    line_list = [f"# Run {run_id_str}".rstrip(), ""]
    if experiment_str:
        line_list.append(f"Experiment: {experiment_str}")
        line_list.append("")
    line_list.append(f"## Verdict: {report_dict_in['label_str']}")
    line_list.append("")
    if report_dict_in["failed_list"]:
        line_list.append("Failed: " + ", ".join(report_dict_in["failed_list"]) + ".")
    else:
        line_list.append("Every part passed.")
    line_list.extend(["", "### Return", ""])
    line_list.append(
        f"Prior-only total return {get_report_float_str(return_dict['strategy_total_return'])} vs buy-and-hold "
        f"{get_report_float_str(return_dict['buy_hold_total_return'])}: "
        f"{'pass' if return_dict['pass_bool'] else 'fail'} ({return_dict['reason_str']})."
    )
    line_list.append(
        f"Sharpe {get_report_float_str(return_dict['strategy_sharpe_ratio'])} vs "
        f"{get_report_float_str(return_dict['buy_hold_sharpe_ratio'])}. "
        f"Max drawdown {get_report_float_str(return_dict['strategy_max_drawdown'])} vs "
        f"{get_report_float_str(return_dict['buy_hold_max_drawdown'])}."
    )
    line_list.extend(["", "### Consistency", ""])
    share_str = get_report_float_str(consistency_dict["ahead_share"]) if np.isfinite(consistency_dict["ahead_share"]) else "n/a"
    line_list.append(
        f"Ahead of buy-and-hold on {consistency_dict['ahead_count']} of {consistency_dict['window_count']} "
        f"rolling {consistency_dict['window_months']}-month windows ({share_str}; need "
        f"{get_report_float_str(consistency_dict['min_share'])}): "
        f"{'pass' if consistency_dict['pass_bool'] else 'fail'}."
    )
    line_list.extend(["", "### Baselines", ""])
    line_list.append(
        f"Constant exposure (weight {get_report_float_str(baseline_dict['constant_exposure_weight'])}, "
        f"daily rebalanced): {get_report_float_str(baseline_dict['constant_exposure_total_return'])}. "
        f"Path is above: {'pass' if baseline_dict['constant_pass_bool'] else 'fail'}."
    )
    random_share_str = (get_report_float_str(baseline_dict["random_timing_beaten_share"])
                        if np.isfinite(baseline_dict["random_timing_beaten_share"]) else "n/a")
    line_list.append(
        f"Random timing ({baseline_dict['random_timing_count']} seeds; same time at each weight as the path; "
        f"switch count may differ from the path only at the two window edges; path has "
        f"{baseline_dict['random_timing_switch_count']} switches): path above "
        f"{baseline_dict['random_timing_beaten_count']} of {baseline_dict['random_timing_count']} "
        f"({random_share_str}; need {get_report_float_str(baseline_dict['random_timing_min_share'])}): "
        f"{'pass' if baseline_dict['random_pass_bool'] else 'fail'}."
    )
    line_list.extend(["", "### Look-ahead", ""])
    if look_ahead_dict["status_str"] == LOOK_AHEAD_PENDING_STR:
        line_list.append("pending.")
    elif look_ahead_dict["status_str"] == LOOK_AHEAD_FAIL_STR:
        fail_dict = look_ahead_dict.get("first_fail_dict") or {}
        session_str = str(fail_dict.get("session_date") or "")
        if session_str:
            line_list.append(f"fail (first differing session {session_str}).")
        else:
            line_list.append("fail.")
    else:
        line_list.append(f"{look_ahead_dict['status_str']}.")
    unread_dict = report_dict_in.get("unread_dict") or {}
    if unread_dict:
        line_list.extend(["", "### Never-read tail", ""])
        count_value = unread_dict.get("unread_session_count")
        count_int = 0 if count_value is None or (isinstance(count_value, float) and not np.isfinite(count_value)) else int(count_value)
        label_str = str(unread_dict.get("label_str") or "")
        line_list.append(f"{label_str} ({count_int} sessions).")
    line_list.append("")
    return "\r\n".join(line_list)


# FUNCTION: WRITE report.json AND report.md IN THE RUN FOLDER
def write_run_report_dict(run_folder_str_in, report_dict_in):
    """
    Args:
        run_folder_str_in (str): Run folder
        report_dict_in (dict): Output of get_report_payload_dict

    Returns:
        dict: json_path_str, md_path_str
    """
    # JSON FIRST, THEN THE READABLE SUMMARY
    json_path_str = os.path.join(run_folder_str_in, REPORT_JSON_FILE_STR)
    md_path_str = os.path.join(run_folder_str_in, REPORT_MD_FILE_STR)
    write_json_file(json_path_str, report_dict_in)
    with open(md_path_str, "w", encoding="utf-8", newline="") as md_file:
        md_file.write(get_report_markdown_str(report_dict_in))
    return {"json_path_str": json_path_str, "md_path_str": md_path_str}


# FUNCTION: WRITE manifest.json LAST (ATOMIC REPLACE)
def write_run_manifest_dict(run_folder_str_in, manifest_dict_in):
    """
    Writes a temporary file, then replaces manifest.json. A crash before this call leaves no manifest.

    Args:
        run_folder_str_in (str): Run folder
        manifest_dict_in (dict): Manifest payload

    Returns:
        str: Manifest path
    """
    # THE TMP FILE IS REPLACED ONTO THE FINAL NAME
    os.makedirs(run_folder_str_in, exist_ok=True)
    tmp_path_str = os.path.join(run_folder_str_in, MANIFEST_TMP_FILE_STR)
    manifest_path_str = os.path.join(run_folder_str_in, MANIFEST_FILE_STR)
    write_json_file(tmp_path_str, manifest_dict_in)
    os.replace(tmp_path_str, manifest_path_str)
    return manifest_path_str
