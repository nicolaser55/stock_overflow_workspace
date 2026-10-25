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

    N                 distinct designs in the trial log (store04_experiments/trial_log.csv) plus the pre-reset records
                      kept in records/legacy/ (the trial log of 2026-10-05 -> 2026-10-22 and the 2026-10-05 audit
                      trials), restored from git history. A design is (experiment family, its rule settings): the
                      family drops a trailing _v2 / _v2_1 suffix (a port of the same rules), and run bookkeeping
                      (run id, commit, folder hash, windows, folds, cut dates, seeds) is not part of the key. Rows of
                      stage note / summary are not designs. The count is approximate and errs high: the same rule
                      written two ways counts twice.
    deflated Sharpe   the probability that the prior-only path's Sharpe ratio of quarterly excess returns over
                      buy-and-hold is above the best Sharpe ratio expected from N worthless designs (Bailey and Lopez de
                      Prado, "The Deflated Sharpe Ratio", 2014). The spread of Sharpe ratios across designs is measured
                      on the trial log's candidate-period excess returns (validation quarters); with fewer than
                      MT_MIN_DESIGN_COUNT designs of at least MT_MIN_PERIOD_COUNT quarters, it falls back to 1 / T, the
                      variance of a Sharpe estimate under the null. Pass at RUNNER_DSR_MIN_PROBABILITY (0.95) or more.
    random timing     the path's total return against the random-timing draws, with a normal approximation of the
                      draws (100 draws cannot resolve a tail of 0.05 / N directly). Pass when the one-sided p-value is
                      at most RUNNER_MULTIPLE_TESTING_ALPHA / N (Bonferroni).

Both must pass. Units: the deflated Sharpe uses non-annualized quarterly Sharpe ratios on both sides; the path's
quarters are calendar quarters and the trial log's are validation quarters (both about 63 sessions).
"""

# EULER-MASCHERONI CONSTANT (EXPECTED MAXIMUM OF N NORMAL DRAWS)
EULER_GAMMA_FLOAT = 0.5772156649015329
# SETTING KEYS THAT ARE RUN BOOKKEEPING, NOT PART OF A DESIGN
BOOKKEEPING_KEY_SET = {"analysis_start", "commit", "cut_date", "cut_dates", "cuts", "data_cutoff", "design_folder_hash",
                       "path", "run_id", "run_mode", "span", "step", "train_end", "train_start", "valid_end",
                       "valid_start", "valid_fold_id_list", "window", "kept_quarters", "calibration", "diagnostic",
                       "bootstrap", "null_seed", "null_run_count", "null_shift_share_range", "verdict", "reference",
                       "optimistic_candidate", "min_month_count", "selection", "test", "check"}
# STAGES THAT ARE NOT A DESIGN EVALUATION
NON_DESIGN_STAGE_SET = {"note", "summary"}
# THE PRE-RESET RECORDS (REPO-RELATIVE)
LEGACY_RECORD_REL_LIST = ["records/legacy/trial_log_snapshot_20261022.csv", "records/legacy/audit_trials_20261005.csv"]
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
        legacy_path_list_in (list[str] | None): Pre-reset records (None = LEGACY_RECORD_REL_LIST in the workspace)

    Returns:
        dict: current_count, legacy_count, total_count (distinct keys over both, at least 1)
    """
    # BOTH SOURCES, THEN THE UNION
    trial_log_path_str = trial_log_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    legacy_path_list = (legacy_path_list_in if legacy_path_list_in is not None
                        else [os.path.join(paths.WORKSPACE_PATH_STR, rel_str) for rel_str in LEGACY_RECORD_REL_LIST])
    current_set = get_design_key_set(read_trial_record_pdf(trial_log_path_str))
    legacy_set = set()
    for path_str in legacy_path_list:
        legacy_set |= get_design_key_set(read_trial_record_pdf(path_str))
    return {"current_count": len(current_set), "legacy_count": len(legacy_set),
            "total_count": max(1, len(current_set | legacy_set))}


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


# FUNCTION: ONE-SIDED P-VALUE AGAINST THE RANDOM-TIMING DRAWS (NORMAL APPROXIMATION)
def get_random_timing_p_float(path_return_in, random_return_list_in):
    """
    Args:
        path_return_in (float): Path total return
        random_return_list_in (list[float]): Random-timing total returns

    Returns:
        float: P(a random draw >= the path) under a normal fit of the draws (1.0 when undefined)
    """
    # A NORMAL FIT OF THE DRAWS
    random_arr = np.asarray(random_return_list_in, dtype=float)
    random_arr = random_arr[np.isfinite(random_arr)]
    if len(random_arr) < 2 or not math.isfinite(float(path_return_in)):
        return 1.0
    std_float = float(random_arr.std(ddof=1))
    if std_float <= 0:
        return 0.0 if float(path_return_in) > float(random_arr.mean()) else 1.0
    return float(1.0 - _STANDARD_NORMAL.cdf((float(path_return_in) - float(random_arr.mean())) / std_float))


# FUNCTION: THE MULTIPLE-TESTING PART OF THE VERDICT
def get_multiple_testing_verdict_dict(strategy_return_pdf_in, buy_hold_return_pdf_in, path_return_in,
                                      random_return_list_in, trial_log_path_str_in=None, legacy_path_list_in=None):
    """
    Both the deflated Sharpe ratio and the Bonferroni random-timing test must pass.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): date, daily_return of the path and buy-and-hold
        path_return_in (float): Path total return
        random_return_list_in (list[float]): Random-timing total returns
        trial_log_path_str_in (str | None): Trial log (None = the shared log)
        legacy_path_list_in (list[str] | None): Pre-reset records (None = records/legacy)

    Returns:
        dict: pass_bool, design counts, deflated Sharpe numbers, random-timing p-value and its threshold
    """
    # N, THEN BOTH TESTS
    count_dict = get_tried_design_count_dict(trial_log_path_str_in, legacy_path_list_in)
    design_count = int(count_dict["total_count"])
    excess_arr = get_quarter_excess_arr(strategy_return_pdf_in, buy_hold_return_pdf_in)
    sharpe_float = get_sharpe_float(excess_arr)
    skew_float, kurtosis_float = get_moment_tuple(excess_arr)
    variance_dict = get_trial_sharpe_variance_dict(trial_log_path_str_in)
    dsr_dict = get_deflated_sharpe_dict(sharpe_float, len(excess_arr), skew_float, kurtosis_float,
                                        variance_dict["variance"], design_count)
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA)
    random_p_float = get_random_timing_p_float(path_return_in, random_return_list_in)
    random_threshold_float = alpha_float / design_count
    dsr_pass_bool = dsr_dict["probability"] >= float(config.RUNNER_DSR_MIN_PROBABILITY)
    random_pass_bool = random_p_float <= random_threshold_float
    return {"pass_bool": bool(dsr_pass_bool and random_pass_bool), "design_count": design_count,
            "current_design_count": int(count_dict["current_count"]),
            "legacy_design_count": int(count_dict["legacy_count"]),
            "quarter_count": int(len(excess_arr)), "quarter_excess_sharpe": sharpe_float,
            "quarter_excess_skew": skew_float, "quarter_excess_kurtosis": kurtosis_float,
            "trial_sharpe_design_count": int(variance_dict["design_count"]),
            "deflated_sharpe_probability": float(dsr_dict["probability"]),
            "deflated_sharpe_min": float(config.RUNNER_DSR_MIN_PROBABILITY),
            "expected_max_sharpe": dsr_dict["expected_max_sharpe"], "trial_sharpe_variance": dsr_dict["variance_used"],
            "trial_sharpe_variance_source_str": dsr_dict["variance_source_str"], "dsr_pass_bool": bool(dsr_pass_bool),
            "random_timing_p": random_p_float, "random_timing_p_max": random_threshold_float,
            "random_pass_bool": bool(random_pass_bool)}
