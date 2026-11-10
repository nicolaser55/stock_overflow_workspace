import json
import math
import os
import re
from statistics import NormalDist
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE WORKSPACE PATH
from so import config, paths

"""
Multiple-Testing Adjustment (audit B5, decided by Nicolas on 2026-10-25)

Every design tried on the development data is a chance to beat buy-and-hold by luck. The runner's verdict therefore
has a "multiple testing" part that raises the bar with N, the number of distinct designs tried on this data so far:

    design            what N counts, in the trial log (store04_experiments/trial_log.csv) and in the ledger below: an
                      (experiment family, its rule settings) pair. The family drops a trailing _v2 / _v2_1 suffix (a
                      port of the same rules), and run bookkeeping (run id, commit, folder hash, windows, folds, cut
                      dates, seeds) is not part of the key. Rows of stage note / summary are not designs. The count
                      is approximate and errs high: the same rule written two ways counts twice. A rerun of an
                      unchanged design adds nothing.
    pilot             everything tried before the judge v1 freeze is a pilot phase run with earlier, less robust
                      code (decided by Nicolas on 2026-11-03, roadmap R4). Its results were discarded; the list of what
                      was tried (family and settings only, no numbers) is the tried-designs ledger
                      records/legacy/pilot_designs.csv, which only grows (scripts/reset_records.py adds the trial log's
                      designs to it before a reset).
    the verdict's N   distinct designs over the trial log AND the ledger (the pilot-included count; decided by Nicolas on
                      2026-11-10). This revisits the 2026-11-03 rule (N = the trial log only, the pilot-included count
                      reported beside it), after the judge v1 baseline: in the stricter direction, with no verdict
                      depending on it (all nine baseline runs failed at both counts). Why: the pilot designs were tried
                      on the same development data and shaped later choices, and with the trial log alone N restarted
                      after every reset. A reset keeps this N (the ledger takes the trial log's designs first) and a
                      rerun of an unchanged design adds nothing. The trial log's own count is still reported. Known
                      limits: N still grows in queue order (the deflated Sharpe asks how many designs were tried by
                      then); it counts close variants as separate tries, so it overstates the independent ones (errs
                      strict); and the spread V below comes from the trial log only (the ledger holds no numbers).
    deflated Sharpe   the probability that the prior-only path's Sharpe ratio of quarterly excess returns over
                      buy-and-hold is above the best Sharpe ratio expected from N worthless designs (Bailey and Lopez de
                      Prado, "The Deflated Sharpe Ratio", 2014). The spread of Sharpe ratios across designs is measured
                      on the trial log's candidate-period excess returns (validation quarters); with fewer than
                      MT_MIN_DESIGN_COUNT designs of at least MT_MIN_PERIOD_COUNT quarters, it falls back to 1 / T, the
                      variance of a Sharpe estimate under the null. Pass at RUNNER_DSR_MIN_PROBABILITY (0.95) or more.
                      Open (2026-11-10, not changed): the spread also follows queue order (the runs logged so far), and
                      a rerun of an unchanged design appends its quarters again, so they count twice in that design's
                      Sharpe ratio; a reset before a full rerun avoids it, and from R6 (no resets) it needs a fix.
    random timing     the path's total return against random-timing draws, COUNTED, not fitted (roadmap R3,
                      2026-11-02). p = (k + 1) / (M + 1), k = draws at or above the path, M = draws; pass when p is at
                      most RUNNER_MULTIPLE_TESTING_ALPHA / N (Bonferroni). The runner (so.runner.baselines) extends the
                      100 registered draws to the budget M + 1 = ceil(RUNNER_RANDOM_TIMING_TAIL_FACTOR * N / alpha) in
                      batches and stops as soon as k exceeds what the full budget would allow (then p at the budget
                      already exceeds the threshold, so stopping cannot change the outcome). Until 2026-11-02 a normal
                      fit of the 100 draws was used; the tail check (scripts/check_random_timing_tail.py, 10,000 draws)
                      found 35 and 37 draws above its critical value where 1.9 were expected (exp04, exp02), and 6 and
                      5 on the log scale: both fits are too lenient, so the test counts.

Both must pass. Units: the deflated Sharpe uses non-annualized quarterly Sharpe ratios on both sides; the path's
quarters are calendar quarters and the trial log's are validation quarters (both about 63 sessions).
"""

# EULER-MASCHERONI CONSTANT (EXPECTED MAXIMUM OF N NORMAL DRAWS)
EULER_GAMMA_FLOAT = 0.5772156649015329
# SETTING KEYS THAT ARE RUN BOOKKEEPING, NOT PART OF A DESIGN
BOOKKEEPING_KEY_SET = {"analysis_start", "commit", "cut_date", "cut_dates", "cuts", "data_cutoff", "design_folder_hash",
                       "helper_hash",
                       "path", "run_id", "run_mode", "span", "step", "train_end", "train_start", "valid_end",
                       "valid_start", "valid_fold_id_list", "window", "kept_quarters", "calibration", "diagnostic",
                       "bootstrap", "null_seed", "null_run_count", "null_shift_share_range", "verdict", "reference",
                       "optimistic_candidate", "min_month_count", "selection", "test", "check"}
# STAGES THAT ARE NOT A DESIGN EVALUATION
NON_DESIGN_STAGE_SET = {"note", "summary"}
# THE TRIED-DESIGNS LEDGER OF THE PILOT PHASE (REPO-RELATIVE; FAMILY AND SETTINGS ONLY)
PILOT_LEDGER_REL_STR = "records/legacy/pilot_designs.csv"
LEGACY_RECORD_REL_LIST = [PILOT_LEDGER_REL_STR]
# THE STANDARD NORMAL
_STANDARD_NORMAL = NormalDist()


# FUNCTION: THE FAMILY OF AN EXPERIMENT NAME
def get_experiment_family_str(experiment_str_in):
    """
    Args:
        experiment_str_in (str): Experiment name, e.g. exp02_stop_reentry_v2_1

    Returns:
        str: The name without a trailing _v<digits>... suffix
    """
    # A PORT OF THE SAME RULES IS THE SAME FAMILY
    return re.sub(r"_v\d.*$", "", str(experiment_str_in))


# FUNCTION: THE DESIGN KEY OF ONE TRIAL ROW
def get_design_key_str(experiment_str_in, setting_json_in):
    """
    Args:
        experiment_str_in (str): Experiment name
        setting_json_in (str | dict | None): The row's setting_json

    Returns:
        str: family|sorted settings without bookkeeping keys
    """
    # PARSE, DROP BOOKKEEPING, SORT
    if isinstance(setting_json_in, dict):
        setting_dict = dict(setting_json_in)
    elif isinstance(setting_json_in, str) and setting_json_in.strip():
        try:
            setting_dict = json.loads(setting_json_in)
        except ValueError:
            setting_dict = {"raw": setting_json_in}
    else:
        setting_dict = {}
    if not isinstance(setting_dict, dict):
        setting_dict = {"value": setting_dict}
    kept_dict = {key_str: value for key_str, value in setting_dict.items() if key_str not in BOOKKEEPING_KEY_SET}
    return get_experiment_family_str(experiment_str_in) + "|" + json.dumps(kept_dict, sort_keys=True, default=str)


# FUNCTION: READ A TRIAL-LOG-SHAPED CSV (EMPTY WHEN ABSENT)
def read_trial_record_pdf(file_path_str_in):
    """
    Args:
        file_path_str_in (str): CSV path

    Returns:
        pd.DataFrame: Rows (empty when the file does not exist)
    """
    # THE FILE MAY NOT EXIST YET (A FRESH DATA ROOT, A TEST)
    if not file_path_str_in or not os.path.isfile(file_path_str_in):
        return pd.DataFrame(columns=["experiment", "stage", "setting_json", "metric_json", "fold_id"])
    return pd.read_csv(file_path_str_in, dtype=str, keep_default_na=False)


# FUNCTION: THE DESIGN KEYS OF A RECORD
def get_design_key_set(record_pdf_in):
    """
    Args:
        record_pdf_in (pd.DataFrame): Trial-log-shaped rows

    Returns:
        set[str]: Design keys of the design-evaluation rows
    """
    # SKIP NOTES AND SUMMARIES
    key_set = set()
    if record_pdf_in is None or len(record_pdf_in) == 0:
        return key_set
    for experiment_str, stage_str, setting_str in zip(record_pdf_in["experiment"], record_pdf_in.get("stage", [""] * len(record_pdf_in)),
                                                      record_pdf_in["setting_json"]):
        if str(stage_str) in NON_DESIGN_STAGE_SET:
            continue
        key_set.add(get_design_key_str(experiment_str, setting_str))
    return key_set


# FUNCTION: HOW MANY DESIGNS HAVE BEEN TRIED ON THE DEVELOPMENT DATA
def get_tried_design_count_dict(trial_log_path_str_in=None, legacy_path_list_in=None):
    """
    Args:
        trial_log_path_str_in (str | None): Current trial log (None = the shared log)
        legacy_path_list_in (list[str] | None): Pilot ledger files (None = records/legacy/pilot_designs.csv)

    Returns:
        dict: current_count (trial log), pilot_count (ledger), pilot_included_count (distinct keys over both, at
            least 1), total_count (the verdict's N: the pilot-included count since 2026-11-10)
    """
    # BOTH SOURCES; THE VERDICT COUNTS BOTH (2026-11-10)
    trial_log_path_str = trial_log_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    legacy_path_list = (legacy_path_list_in if legacy_path_list_in is not None
                        else [os.path.join(paths.WORKSPACE_PATH_STR, rel_str) for rel_str in LEGACY_RECORD_REL_LIST])
    current_set = get_design_key_set(read_trial_record_pdf(trial_log_path_str))
    pilot_set = set()
    for path_str in legacy_path_list:
        pilot_set |= get_design_key_set(read_trial_record_pdf(path_str))
    pilot_included_int = max(1, len(current_set | pilot_set))
    return {"current_count": len(current_set), "pilot_count": len(pilot_set), "total_count": pilot_included_int,
            "pilot_included_count": pilot_included_int}


# FUNCTION: SAMPLE SKEWNESS AND KURTOSIS (NON-EXCESS)
def get_moment_tuple(value_arr_in):
    """
    Args:
        value_arr_in (array-like): Observations

    Returns:
        tuple: (skewness, kurtosis); (0, 3) when undefined
    """
    # POPULATION MOMENTS, AS IN THE DEFLATED-SHARPE PAPER
    value_arr = np.asarray(value_arr_in, dtype=float)
    value_arr = value_arr[np.isfinite(value_arr)]
    if len(value_arr) < 3:
        return 0.0, 3.0
    centered_arr = value_arr - value_arr.mean()
    variance = float(np.mean(centered_arr ** 2))
    if variance <= 0:
        return 0.0, 3.0
    return float(np.mean(centered_arr ** 3) / variance ** 1.5), float(np.mean(centered_arr ** 4) / variance ** 2)


# FUNCTION: NON-ANNUALIZED SHARPE RATIO
def get_sharpe_float(value_arr_in):
    """
    Args:
        value_arr_in (array-like): Per-period excess returns

    Returns:
        float: mean / standard deviation (NaN when undefined)
    """
    # SAMPLE STANDARD DEVIATION
    value_arr = np.asarray(value_arr_in, dtype=float)
    value_arr = value_arr[np.isfinite(value_arr)]
    if len(value_arr) < 2:
        return float("nan")
    std_float = float(value_arr.std(ddof=1))
    return float(value_arr.mean() / std_float) if std_float > 0 else float("nan")


# FUNCTION: SPREAD OF SHARPE RATIOS ACROSS THE DESIGNS IN THE TRIAL LOG
def get_trial_sharpe_variance_dict(trial_log_path_str_in=None):
    """
    Each design's quarterly excess returns (validation rows, metric excess_return), its Sharpe ratio, and the variance
    of those ratios across designs with at least MT_MIN_PERIOD_COUNT quarters.

    Args:
        trial_log_path_str_in (str | None): Trial log (None = the shared log)

    Returns:
        dict: design_count, variance (NaN when fewer than MT_MIN_DESIGN_COUNT designs)
    """
    # GROUP THE VALIDATION ROWS BY DESIGN
    record_pdf = read_trial_record_pdf(trial_log_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)
    if len(record_pdf) == 0:
        return {"design_count": 0, "variance": float("nan")}
    excess_dict = {}
    for experiment_str, stage_str, setting_str, metric_str in zip(record_pdf["experiment"], record_pdf["stage"],
                                                                  record_pdf["setting_json"], record_pdf["metric_json"]):
        if str(stage_str) != "validation":
            continue
        try:
            excess_float = float(json.loads(metric_str).get("excess_return"))
        except (ValueError, TypeError, AttributeError):
            continue
        if math.isfinite(excess_float):
            excess_dict.setdefault(get_design_key_str(experiment_str, setting_str), []).append(excess_float)
    sharpe_list = [get_sharpe_float(value_list) for value_list in excess_dict.values()
                   if len(value_list) >= int(config.MT_MIN_PERIOD_COUNT)]
    sharpe_list = [value for value in sharpe_list if math.isfinite(value)]
    if len(sharpe_list) < int(config.MT_MIN_DESIGN_COUNT):
        return {"design_count": len(sharpe_list), "variance": float("nan")}
    return {"design_count": len(sharpe_list), "variance": float(np.var(sharpe_list, ddof=1))}


# FUNCTION: THE DEFLATED SHARPE RATIO
def get_deflated_sharpe_dict(sharpe_float_in, period_count_int_in, skew_float_in, kurtosis_float_in,
                             trial_variance_float_in, design_count_int_in):
    """
    DSR = Phi( (SR - SR0) sqrt(T - 1) / sqrt(1 - skew SR + (kurt - 1) / 4 SR^2) ), with
    SR0 = sqrt(V) ((1 - gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e))). N = 1 gives SR0 = 0 (the probabilistic
    Sharpe ratio). V not finite or not positive falls back to 1 / T.

    Args:
        sharpe_float_in (float): Non-annualized Sharpe ratio of the path's period excess returns
        period_count_int_in (int): T, the number of periods
        skew_float_in, kurtosis_float_in (float): Skewness and (non-excess) kurtosis of those returns
        trial_variance_float_in (float): Variance of Sharpe ratios across the designs tried
        design_count_int_in (int): N

    Returns:
        dict: probability, expected_max_sharpe, variance_used, variance_source_str
    """
    # UNDEFINED INPUTS GIVE PROBABILITY 0 (THE PART FAILS)
    period_count = int(period_count_int_in)
    sharpe_float = float(sharpe_float_in)
    if period_count < 2 or not math.isfinite(sharpe_float):
        return {"probability": 0.0, "expected_max_sharpe": float("nan"), "variance_used": float("nan"),
                "variance_source_str": "undefined"}
    variance_float = float(trial_variance_float_in)
    variance_source_str = "trial_log"
    if not math.isfinite(variance_float) or variance_float <= 0:
        variance_float = 1.0 / period_count
        variance_source_str = "null_1_over_T"
    design_count = max(1, int(design_count_int_in))
    if design_count == 1:
        expected_max_float = 0.0
    else:
        expected_max_float = math.sqrt(variance_float) * (
            (1.0 - EULER_GAMMA_FLOAT) * _STANDARD_NORMAL.inv_cdf(1.0 - 1.0 / design_count)
            + EULER_GAMMA_FLOAT * _STANDARD_NORMAL.inv_cdf(1.0 - 1.0 / (design_count * math.e)))
    denominator_float = 1.0 - float(skew_float_in) * sharpe_float + (float(kurtosis_float_in) - 1.0) / 4.0 * sharpe_float ** 2
    if denominator_float <= 0:
        return {"probability": 0.0, "expected_max_sharpe": expected_max_float, "variance_used": variance_float,
                "variance_source_str": variance_source_str}
    z_float = (sharpe_float - expected_max_float) * math.sqrt(period_count - 1) / math.sqrt(denominator_float)
    return {"probability": float(_STANDARD_NORMAL.cdf(z_float)), "expected_max_sharpe": float(expected_max_float),
            "variance_used": float(variance_float), "variance_source_str": variance_source_str}


# FUNCTION: QUARTERLY EXCESS RETURNS OF A PATH OVER BUY-AND-HOLD
def get_quarter_excess_arr(strategy_return_pdf_in, buy_hold_return_pdf_in):
    """
    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): date, daily_return (same dates)

    Returns:
        np.ndarray: Strategy quarter return minus buy-and-hold quarter return, per calendar quarter
    """
    # CHAIN DAILY RETURNS WITHIN EACH CALENDAR QUARTER
    merged_pdf = strategy_return_pdf_in.merge(buy_hold_return_pdf_in, on="date", suffixes=("_strategy", "_buy_hold"))
    if len(merged_pdf) == 0:
        return np.array([], dtype=float)
    merged_pdf["quarter"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("Q")
    grouped = merged_pdf.groupby("quarter", sort=True)
    strategy_arr = grouped["daily_return_strategy"].apply(lambda series: float(np.prod(1.0 + series) - 1.0)).to_numpy()
    buy_hold_arr = grouped["daily_return_buy_hold"].apply(lambda series: float(np.prod(1.0 + series) - 1.0)).to_numpy()
    return np.asarray(strategy_arr - buy_hold_arr, dtype=float)


# FUNCTION: THE RANDOM-TIMING DRAW BUDGET FOR N DESIGNS
def get_random_timing_draw_target_int(design_count_int_in, alpha_in=None, factor_in=None):
    """
    Args:
        design_count_int_in (int): N (at least 1)
        alpha_in (float | None): Family-wise alpha (None = RUNNER_MULTIPLE_TESTING_ALPHA)
        factor_in (int | None): Budget factor (None = RUNNER_RANDOM_TIMING_TAIL_FACTOR)

    Returns:
        int: M, the number of draws such that M + 1 = ceil(factor * N / alpha)
    """
    # ROUNDED TO 9 DECIMALS BEFORE THE CEILING: 2 * 260 / 0.05 IS 10400 EXACTLY, NOT 10400.000000000002 (ONE TOO MANY)
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA if alpha_in is None else alpha_in)
    factor_int = int(config.RUNNER_RANDOM_TIMING_TAIL_FACTOR if factor_in is None else factor_in)
    design_count = max(1, int(design_count_int_in))
    return int(math.ceil(round(factor_int * design_count / alpha_float, 9))) - 1


# FUNCTION: THE MOST DRAWS AT OR ABOVE THE PATH THAT STILL PASS, FOR M DRAWS AND N DESIGNS
def get_random_timing_at_or_above_max_int(draw_count_int_in, design_count_int_in, alpha_in=None):
    """
    The largest k with (k + 1) / (M + 1) <= alpha / N; -1 when even k = 0 fails (too few draws to pass).

    Args:
        draw_count_int_in (int): M
        design_count_int_in (int): N
        alpha_in (float | None): Family-wise alpha (None = RUNNER_MULTIPLE_TESTING_ALPHA)

    Returns:
        int: k_max
    """
    # (k + 1) <= (M + 1) * alpha / N, WITH A SMALL ROUNDING ALLOWANCE IN THE PASSING DIRECTION ONLY FOR EXACT EQUALITY
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA if alpha_in is None else alpha_in)
    bound_float = (int(draw_count_int_in) + 1) * alpha_float / max(1, int(design_count_int_in))
    return int(math.floor(round(bound_float, 9))) - 1


# FUNCTION: THE EMPIRICAL RANDOM-TIMING TEST FROM GIVEN DRAWS (NO EXTRA DRAWS)
def get_random_timing_count_dict(path_return_in, random_return_list_in, design_count_int_in, alpha_in=None):
    """
    The test on the draws given, without drawing more. With 100 draws it cannot pass once N > 5 (1 / 101 > 0.05 / N):
    the runner extends the draws (so.runner.baselines.get_random_timing_tail_dict); a caller without them gets the
    strict answer.

    Args:
        path_return_in (float): Path total return
        random_return_list_in (list[float]): Random-timing total returns (a non-finite draw counts as at or above)
        design_count_int_in (int): N
        alpha_in (float | None): Family-wise alpha

    Returns:
        dict: the tail-dict fields (see get_random_timing_tail_dict) for these draws only
    """
    # COUNT; A NON-FINITE PATH NEVER PASSES
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA if alpha_in is None else alpha_in)
    design_count = max(1, int(design_count_int_in))
    value_arr = np.asarray(list(random_return_list_in), dtype=float)
    path_float = float(path_return_in)
    path_finite_bool = math.isfinite(path_float)
    at_or_above_int = int(np.sum(~(value_arr < path_float))) if path_finite_bool else int(len(value_arr))
    draw_count = int(len(value_arr))
    at_or_above_max = get_random_timing_at_or_above_max_int(draw_count, design_count, alpha_float)
    p_float = float((at_or_above_int + 1) / (draw_count + 1))
    return {"method_str": "empirical", "design_count": design_count, "alpha": alpha_float,
            "p_max": alpha_float / design_count, "path_return_used": path_float,
            "draw_target": draw_count, "draw_count": draw_count, "registered_draw_count": draw_count,
            "at_or_above_count": at_or_above_int, "at_or_above_max": at_or_above_max, "p": p_float,
            "stopped_early_bool": False, "budget_exceeded_bool": False, "extension_bool": False,
            "pass_bool": bool(path_finite_bool and draw_count > 0 and at_or_above_int <= at_or_above_max)}


# FUNCTION: THE MULTIPLE-TESTING PART OF THE VERDICT
def get_multiple_testing_verdict_dict(strategy_return_pdf_in, buy_hold_return_pdf_in, path_return_in,
                                      random_return_list_in, trial_log_path_str_in=None, legacy_path_list_in=None,
                                      random_timing_tail_dict_in=None):
    """
    Both the deflated Sharpe ratio and the Bonferroni random-timing test must pass.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): date, daily_return of the path and buy-and-hold
        path_return_in (float): Path total return
        random_return_list_in (list[float]): Random-timing total returns
        trial_log_path_str_in (str | None): Trial log (None = the shared log)
        legacy_path_list_in (list[str] | None): Pilot ledger files (None = records/legacy/pilot_designs.csv)
        random_timing_tail_dict_in (dict | None): The runner's extended draw count
            (so.runner.baselines.get_random_timing_tail_dict); None = count random_return_list_in only (strict)

    Returns:
        dict: pass_bool, design_count (the verdict's N), design_count_scope_str, current_design_count (trial log),
            pilot_design_count (ledger), deflated Sharpe numbers, random-timing counts, p-value and its threshold
    """
    # N (THE PILOT-INCLUDED COUNT), THEN BOTH TESTS
    count_dict = get_tried_design_count_dict(trial_log_path_str_in, legacy_path_list_in)
    design_count = int(count_dict["total_count"])
    excess_arr = get_quarter_excess_arr(strategy_return_pdf_in, buy_hold_return_pdf_in)
    sharpe_float = get_sharpe_float(excess_arr)
    skew_float, kurtosis_float = get_moment_tuple(excess_arr)
    variance_dict = get_trial_sharpe_variance_dict(trial_log_path_str_in)
    dsr_dict = get_deflated_sharpe_dict(sharpe_float, len(excess_arr), skew_float, kurtosis_float,
                                        variance_dict["variance"], design_count)
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA)
    # THE RUNNER'S COUNT MUST HAVE BEEN MADE FOR THIS N AND ALPHA; OTHERWISE THE STRICT COUNT OF THE GIVEN DRAWS
    tail_dict = dict(random_timing_tail_dict_in or {})
    tail_mismatch_bool = bool(tail_dict) and (int(tail_dict.get("design_count", -1)) != design_count
                                              or abs(float(tail_dict.get("alpha", -1.0)) - alpha_float) > 1e-12)
    if not tail_dict or tail_mismatch_bool:
        tail_dict = get_random_timing_count_dict(path_return_in, random_return_list_in, design_count, alpha_float)
    tail_dict["tail_mismatch_bool"] = tail_mismatch_bool
    random_p_float = float(tail_dict["p"])
    random_threshold_float = alpha_float / design_count
    dsr_pass_bool = dsr_dict["probability"] >= float(config.RUNNER_DSR_MIN_PROBABILITY)
    random_pass_bool = bool(tail_dict["pass_bool"])
    return {"pass_bool": bool(dsr_pass_bool and random_pass_bool), "design_count": design_count,
            "design_count_scope_str": "pilot_included",
            "current_design_count": int(count_dict["current_count"]),
            "pilot_design_count": int(count_dict["pilot_count"]),
            "quarter_count": int(len(excess_arr)), "quarter_excess_sharpe": sharpe_float,
            "quarter_excess_skew": skew_float, "quarter_excess_kurtosis": kurtosis_float,
            "trial_sharpe_design_count": int(variance_dict["design_count"]),
            "deflated_sharpe_probability": float(dsr_dict["probability"]),
            "deflated_sharpe_min": float(config.RUNNER_DSR_MIN_PROBABILITY),
            "expected_max_sharpe": dsr_dict["expected_max_sharpe"], "trial_sharpe_variance": dsr_dict["variance_used"],
            "trial_sharpe_variance_source_str": dsr_dict["variance_source_str"], "dsr_pass_bool": bool(dsr_pass_bool),
            "random_timing_p": random_p_float, "random_timing_p_max": random_threshold_float,
            "random_timing_tail_dict": tail_dict,
            "random_pass_bool": bool(random_pass_bool)}
