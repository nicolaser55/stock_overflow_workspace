import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp01_minute_entry import config as exp_config
# IMPORT BARRIER LABEL FUNCTIONS
from so.features.barrier_labels import get_delta_col_str
# IMPORT TRADE EXECUTION FUNCTIONS
from so.core.trade_execution import get_breakeven_tp_rate_arr
# IMPORT THE SIGNAL CHECK BUILDING BLOCKS
from so.core.signal_bins import get_block_id_arr, get_quantile_bin_edge_arr, get_bin_label_series, get_bootstrap_bin_stat_pdf, \
                                get_bin_month_count_series

"""
Single-Feature Signal Check: exp01 step 02 (stopping rule, PROTOCOL.md §13.1)

Changed from the v1 check (signal_check_v1, 2026-10-01) on 2026-10-05, after the audit:
    - REFERENCE = the window's BASE RATE: the unconditional take profit rate of the same window at the same delta. The v1
      check compared bins with the break-even TP rate, and market drift alone lifted 1,339 training bins above it.
    - TWO-SIDED: a bin reliably BELOW the base rate ("do not enter here") counts as much as one above it.
    - VALIDATION POOLED over the SIGNAL_CHECK_POOLED_QUARTER_COUNT most recent validation quarters (one quarter cannot
      satisfy the month minimum and has little power); training = the 10-year window of the first pooled fold.
    - MONTH MINIMUM: a bin's pass counts only if its rows cover at least SIGNAL_CHECK_MIN_MONTH_COUNT calendar months in
      EACH window (a bin concentrated in a few months gets a degenerate bootstrap interval).
The break-even TP rate is still reported: a bin above its base rate can still be below break-even (not tradable).

For every feature and every delta:
    1. Bin the feature on the TRAINING window (quantile bins for numeric features, one bin per level for categoricals).
    2. Per bin and window: TP rate with a block-bootstrap interval (whole ISO weeks resampled together), base rate of the
       window, break-even TP rate, mean net return, number of distinct months.
    3. A bin PASSES in a window if its interval lies entirely above (or entirely below) the window's base rate.
    4. A bin is a SIGNAL if it passes on training AND, with the same bin edges, on the pooled validation, ON THE SAME SIDE.

Multiple testing: every (feature, delta, bin) is a test; the expected number of chance passes on training alone is about
test_count * (1 - CONFIDENCE_LEVEL) (two-sided), and about test_count * 2 * ((1 - CONFIDENCE_LEVEL) / 2)^2 signals are
expected by chance if the tests were independent. They are not (the 21 deltas share the same bins), so the verdict is
calibrated on a NULL instead (added 2026-10-05, after a synthetic random walk produced 2 signals; the first real run used
the uncalibrated rule):
    5. NULL RUNS: the same check is run SIGNAL_CHECK_NULL_RUN_COUNT times with the feature columns shifted, together, by a
       random number of whole sessions (25%-75% of each window, circularly) against the unchanged outcomes. This keeps
       every series' own structure and the correlation between the tests, and breaks any feature -> outcome link.
    6. The statistic is the number of DISTINCT FEATURE BINS with at least one signal (one bin usually passes at several
       neighbouring deltas).

Verdict: "CONTINUE" if the real check has more distinct signal bins than EVERY null run (p <= 1 / (N + 1) = 0.05 with
19 runs; ties stop), otherwise "STOP". Without null runs (unit tests only) the old rule applies: at least one signal.
"""

# FUNCTION: GET THE BIN STATISTICS OF ONE FEATURE, ONE DELTA AND ONE WINDOW
def get_window_bin_stat_pdf(window_pdf_in, bin_label_series_in, y_col_str_in, net_col_str_in, delta_float_in,
                            block_str_in=exp_config.SIGNAL_CHECK_BOOTSTRAP_BLOCK_STR, **bootstrap_kwargs):
    """
    Calculates the per-bin statistics of one window.

    Args:
        window_pdf_in (pd.DataFrame): Resolved labeled rows of the window (decision_ts, entry_price, labels)
        bin_label_series_in (pd.Series): Bin label per row
        y_col_str_in (str): Take profit label column
        net_col_str_in (str): Net return column
        delta_float_in (float): Delta
        block_str_in (str): Bootstrap block ("week" or "day")
        **bootstrap_kwargs: Overrides for so.core.signal_bins.get_bootstrap_bin_stat_pdf

    Returns:
        pd.DataFrame: bin, row_count, month_count, tp_rate, tp_rate_ci_low, tp_rate_ci_high, base_rate, breakeven_tp_rate,
                      mean_net_return, net_return_ci_low, net_return_ci_high
    """
    # COLLECT THE LABELS AND THE BASE RATE OF THE WINDOW
    y_arr = window_pdf_in[y_col_str_in].to_numpy(dtype=float)
    base_rate = float(y_arr.mean()) if len(y_arr) else np.nan
    # CALCULATE THE BIN STATISTICS
    stat_pdf = get_bootstrap_bin_stat_pdf(bin_label_series_in.reset_index(drop=True), get_block_id_arr(window_pdf_in["decision_ts"], block_str_in), y_arr,
                                          window_pdf_in[net_col_str_in].to_numpy(dtype=float),
                                          get_breakeven_tp_rate_arr(window_pdf_in["entry_price"].to_numpy(dtype=float), delta_float_in), **bootstrap_kwargs)
    # ADD THE BASE RATE AND THE MONTH COUNT
    stat_pdf["base_rate"] = base_rate
    stat_pdf["month_count"] = stat_pdf["bin"].map(get_bin_month_count_series(bin_label_series_in, window_pdf_in["decision_ts"])).fillna(0).astype(int)
    # RETURN THE STATISTICS
    return stat_pdf[["bin", "row_count", "month_count", "tp_rate", "tp_rate_ci_low", "tp_rate_ci_high", "base_rate", "breakeven_tp_rate",
                     "mean_net_return", "net_return_ci_low", "net_return_ci_high"]]

# FUNCTION: RUN THE SIGNAL CHECK OF ONE FEATURE AND ONE DELTA
def get_feature_delta_signal_pdf(train_pdf_in, valid_pdf_in, feature_col_str_in, delta_float_in,
                                 bin_count_in=exp_config.SIGNAL_CHECK_BIN_COUNT,
                                 min_bin_count_in=exp_config.SIGNAL_CHECK_MIN_BIN_COUNT,
                                 min_month_count_in=exp_config.SIGNAL_CHECK_MIN_MONTH_COUNT, **bootstrap_kwargs):
    """
    Runs the base-rate signal check of one feature at one delta (bins from training, re-used on validation).

    Args:
        train_pdf_in (pd.DataFrame): Labeled training rows (decision_ts, entry_price, feature, y_tp_<d>, net_return_<d>)
        valid_pdf_in (pd.DataFrame): Labeled pooled validation rows (same columns)
        feature_col_str_in (str): Feature column
        delta_float_in (float): Delta
        bin_count_in (int): Quantile bins of a numeric feature
        min_bin_count_in (int): Minimum training rows of a tested bin
        min_month_count_in (int | None): Minimum distinct months of a bin in EACH window for its pass to count (None = no minimum)
        **bootstrap_kwargs: Optional overrides for the bootstrap

    Returns:
        pd.DataFrame: One row per training bin with train_* and valid_* statistics, the pass flags and the 'signal' flag
    """
    # DEFINE THE LABEL COLUMNS
    delta_col_str = get_delta_col_str(delta_float_in)
    y_col_str, net_col_str = f"y_tp_{delta_col_str}", f"net_return_{delta_col_str}"
    # DEFINE THE FEATURE TYPE
    is_categorical = config.FEATURE_REGISTRY_DICT[feature_col_str_in]["scale_type"] == "categorical"
    # KEEP THE RESOLVED ROWS
    train_pdf = train_pdf_in[train_pdf_in[y_col_str].notna()]
    valid_pdf = valid_pdf_in[valid_pdf_in[y_col_str].notna()]
    # IF THERE IS NO TRAINING ROW
    if train_pdf.empty:
        return pd.DataFrame()
    # LEARN THE BIN EDGES ON TRAINING
    bin_edge_arr = None if is_categorical else get_quantile_bin_edge_arr(train_pdf[feature_col_str_in], bin_count_in)
    # CALCULATE THE TRAINING STATISTICS
    signal_pdf = get_window_bin_stat_pdf(train_pdf, get_bin_label_series(train_pdf[feature_col_str_in], is_categorical, bin_edge_arr),
                                         y_col_str, net_col_str, delta_float_in, **bootstrap_kwargs).add_prefix("train_").rename(columns={"train_bin": "bin"})
    # CALCULATE THE VALIDATION STATISTICS (SAME EDGES) IF THERE ARE VALIDATION ROWS
    if not valid_pdf.empty:
        valid_stat_pdf = get_window_bin_stat_pdf(valid_pdf, get_bin_label_series(valid_pdf[feature_col_str_in], is_categorical, bin_edge_arr),
                                                 y_col_str, net_col_str, delta_float_in, **bootstrap_kwargs).add_prefix("valid_").rename(columns={"valid_bin": "bin"})
        signal_pdf = signal_pdf.merge(valid_stat_pdf, on="bin", how="left")
    # OTHERWISE ADD EMPTY VALIDATION COLUMNS
    else:
        for col_str in [col.replace("train_", "valid_", 1) for col in signal_pdf.columns if col.startswith("train_")]:
            signal_pdf[col_str] = np.nan
    # DEFINE THE TESTED BINS (ENOUGH TRAINING ROWS, NOT THE MISSING-VALUE BIN)
    signal_pdf["tested"] = (signal_pdf["train_row_count"] >= min_bin_count_in) & (signal_pdf["bin"] != "NaN")
    # DEFINE THE MONTH CONDITION OF EACH WINDOW (NO MINIMUM = ALWAYS TRUE)
    train_month_ok = (signal_pdf["train_month_count"] >= min_month_count_in) if min_month_count_in is not None else pd.Series(True, index=signal_pdf.index)
    valid_month_ok = (signal_pdf["valid_month_count"].fillna(0) >= min_month_count_in) if min_month_count_in is not None else pd.Series(True, index=signal_pdf.index)
    signal_pdf["tested"] = signal_pdf["tested"] & train_month_ok
    # DEFINE THE PASSES ABOVE AND BELOW THE BASE RATE IN EACH WINDOW
    signal_pdf["train_above"] = signal_pdf["tested"] & (signal_pdf["train_tp_rate_ci_low"] > signal_pdf["train_base_rate"])
    signal_pdf["train_below"] = signal_pdf["tested"] & (signal_pdf["train_tp_rate_ci_high"] < signal_pdf["train_base_rate"])
    signal_pdf["valid_above"] = ((signal_pdf["valid_tp_rate_ci_low"] > signal_pdf["valid_base_rate"]).fillna(False).astype(bool) & valid_month_ok).astype(bool)
    signal_pdf["valid_below"] = ((signal_pdf["valid_tp_rate_ci_high"] < signal_pdf["valid_base_rate"]).fillna(False).astype(bool) & valid_month_ok).astype(bool)
    # DEFINE THE SIGNALS (SAME SIDE IN BOTH WINDOWS)
    signal_pdf["signal"] = (signal_pdf["train_above"] & signal_pdf["valid_above"]) | (signal_pdf["train_below"] & signal_pdf["valid_below"])
    # FLAG THE ABOVE-SIDE SIGNALS WHOSE VALIDATION LOWER BOUND IS ALSO ABOVE BREAK-EVEN (TRADABLE AFTER COSTS)
    signal_pdf["above_breakeven"] = signal_pdf["signal"] & signal_pdf["train_above"] & (signal_pdf["valid_tp_rate_ci_low"] > signal_pdf["valid_breakeven_tp_rate"]).fillna(False).astype(bool)
    # ADD THE FEATURE AND THE DELTA
    signal_pdf.insert(0, "delta", delta_float_in)
    signal_pdf.insert(0, "feature", feature_col_str_in)
    # RETURN THE RESULTS
    return signal_pdf

# FUNCTION: RUN THE SIGNAL CHECK OF A LIST OF FEATURES AND DELTAS
def get_signal_check_pdf(train_pdf_in, valid_pdf_in, feature_col_str_list_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST, alert_in=True, **check_kwargs):
    """
    Runs the signal check of every feature at every delta.

    Args:
        train_pdf_in (pd.DataFrame): Labeled training rows
        valid_pdf_in (pd.DataFrame): Labeled pooled validation rows
        feature_col_str_list_in (list[str]): Feature columns
        delta_list_in (list[float]): Deltas
        alert_in (bool): Display progress
        **check_kwargs: Optional overrides for get_feature_delta_signal_pdf (bin_count_in, min_month_count_in, iteration_count_in, ...)

    Returns:
        pd.DataFrame: Concatenated output of get_feature_delta_signal_pdf
    """
    # LIST TO HOLD THE RESULTS
    signal_pdf_list = []
    # ITERATE OVER THE FEATURES
    for feature_idx, feature_col_str in enumerate(feature_col_str_list_in, 1):
        # DISPLAY PROGRESS
        print(f"Feature:\t{feature_col_str}\t[{feature_idx}/{len(feature_col_str_list_in)}]") if alert_in else None
        # ITERATE OVER THE DELTAS
        for delta in delta_list_in:
            # APPEND THE RESULT OF THE FEATURE AND DELTA
            signal_pdf_list.append(get_feature_delta_signal_pdf(train_pdf_in, valid_pdf_in, feature_col_str, delta, **check_kwargs))
    # RETURN THE CONCATENATED RESULTS
    return pd.concat(signal_pdf_list, ignore_index=True) if signal_pdf_list else pd.DataFrame()

# FUNCTION: SHIFT THE FEATURE COLUMNS OF A WINDOW BY WHOLE SESSIONS (NULL WITHOUT A FEATURE -> OUTCOME LINK)
def get_session_shifted_feature_pdf(window_pdf_in, feature_col_str_list_in, rng_in,
                                    shift_share_range_in=exp_config.SIGNAL_CHECK_NULL_SHIFT_SHARE_RANGE):
    """
    Circularly shifts the feature columns of a window, together, by a random number of whole sessions; the outcome columns
    (decision_ts, entry_price, labels) stay in place.

    Args:
        window_pdf_in (pd.DataFrame): Labeled rows of one window
        feature_col_str_list_in (list[str]): Feature columns to shift
        rng_in (np.random.Generator): Random generator
        shift_share_range_in (tuple[float, float]): Range of the shift as a share of the window's sessions

    Returns:
        pd.DataFrame: Copy of the window sorted by decision time, with shifted feature columns and a 'null_shift_session_count' attribute
    """
    # SORT THE ROWS BY DECISION TIME
    window_pdf = window_pdf_in.sort_values("decision_ts").reset_index(drop=True)
    # COLLECT THE SESSION OF EACH ROW (NEW YORK DATE)
    session_arr = pd.to_datetime(window_pdf["decision_ts"], utc=True).dt.tz_convert("America/New_York").dt.date.to_numpy()
    # COLLECT THE FIRST ROW OF EACH SESSION
    first_row_idx_arr = np.flatnonzero(np.r_[True, session_arr[1:] != session_arr[:-1]]) if len(session_arr) else np.array([], dtype=int)
    # COLLECT THE NUMBER OF SESSIONS
    session_count = len(first_row_idx_arr)
    # IF THE WINDOW HAS FEWER THAN 2 SESSIONS, RETURN IT UNCHANGED
    if session_count < 2:
        return window_pdf
    # DRAW THE SHIFT IN SESSIONS (AT LEAST 1, AT MOST session_count - 1)
    low_int = min(max(1, int(session_count * shift_share_range_in[0])), session_count - 1)
    high_int = min(max(low_int, int(session_count * shift_share_range_in[1])), session_count - 1)
    shift_session_count = int(rng_in.integers(low_int, high_int + 1))
    # CONVERT THE SESSION SHIFT INTO A ROW SHIFT (THE ROWS OF THE FIRST shift_session_count SESSIONS)
    row_shift_int = int(first_row_idx_arr[shift_session_count])
    # ITERATE OVER THE FEATURE COLUMNS
    for feature_col_str in feature_col_str_list_in:
        # ROLL THE COLUMN (ROW i RECEIVES THE FEATURES OF ROW i - row_shift_int)
        window_pdf[feature_col_str] = np.roll(window_pdf[feature_col_str].to_numpy(), row_shift_int)
    # RECORD THE SHIFT
    window_pdf.attrs["null_shift_session_count"] = shift_session_count
    # RETURN THE SHIFTED WINDOW
    return window_pdf

# FUNCTION: COUNT THE SIGNALS OF A SIGNAL CHECK
def get_signal_count_dict(signal_check_pdf_in):
    """
    Counts the tests, training passes, signals and distinct signal bins of a signal check.

    Args:
        signal_check_pdf_in (pd.DataFrame): Output of get_signal_check_pdf

    Returns:
        dict: test_count, train_pass_count, signal_count, signal_bin_count
    """
    # IF THE CHECK IS EMPTY
    if signal_check_pdf_in.empty:
        return {"test_count": 0, "train_pass_count": 0, "signal_count": 0, "signal_bin_count": 0}
    # COLLECT THE SIGNALS
    signal_pdf = signal_check_pdf_in[signal_check_pdf_in["signal"]]
    # RETURN THE COUNTS
    return {"test_count": int(signal_check_pdf_in["tested"].sum()),
            "train_pass_count": int((signal_check_pdf_in["train_above"] | signal_check_pdf_in["train_below"]).sum()),
            "signal_count": int(len(signal_pdf)),
            "signal_bin_count": int(signal_pdf[["feature", "bin"]].astype(str).drop_duplicates().shape[0])}

# FUNCTION: RUN ONE NULL SIGNAL CHECK
def get_null_signal_count_dict(train_pdf_in, valid_pdf_in, feature_col_str_list_in, delta_list_in, run_id_in,
                               seed_in=config.RANDOM_SEED, **check_kwargs):
    """
    Runs the signal check once on session-shifted features (both windows shifted independently).

    Args:
        train_pdf_in, valid_pdf_in (pd.DataFrame): Labeled training and pooled validation rows
        feature_col_str_list_in (list[str]): Feature columns
        delta_list_in (list[float]): Deltas
        run_id_in (int): Null run number (with seed_in, defines the shifts)
        seed_in (int): Base random seed
        **check_kwargs: Optional overrides for get_feature_delta_signal_pdf (the same as the real check)

    Returns:
        dict: run_id, train_shift_session_count, valid_shift_session_count and the counts of get_signal_count_dict
    """
    # CREATE THE RANDOM GENERATOR OF THE RUN
    rng = np.random.default_rng([seed_in, run_id_in])
    # SHIFT THE FEATURES OF EACH WINDOW
    train_pdf = get_session_shifted_feature_pdf(train_pdf_in, feature_col_str_list_in, rng)
    valid_pdf = get_session_shifted_feature_pdf(valid_pdf_in, feature_col_str_list_in, rng)
    # RUN THE SIGNAL CHECK WITH THE SAME SETTINGS
    null_check_pdf = get_signal_check_pdf(train_pdf, valid_pdf, feature_col_str_list_in, delta_list_in, alert_in=False, **check_kwargs)
    # RETURN THE COUNTS
    return {"run_id": run_id_in, "train_shift_session_count": train_pdf.attrs.get("null_shift_session_count"),
            "valid_shift_session_count": valid_pdf.attrs.get("null_shift_session_count"), **get_signal_count_dict(null_check_pdf)}

# FUNCTION: RUN THE NULL SIGNAL CHECKS
def get_null_signal_count_pdf(train_pdf_in, valid_pdf_in, feature_col_str_list_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST,
                              run_count_in=exp_config.SIGNAL_CHECK_NULL_RUN_COUNT, job_count_in=-1, seed_in=config.RANDOM_SEED, **check_kwargs):
    """
    Runs the null signal checks, in parallel processes (joblib, installed with scikit-learn).

    Args:
        train_pdf_in, valid_pdf_in (pd.DataFrame): Labeled training and pooled validation rows
        feature_col_str_list_in (list[str]): Feature columns
        delta_list_in (list[float]): Deltas
        run_count_in (int): Number of null runs
        job_count_in (int): Parallel processes (-1 = all cores, 1 = sequential); does not change the results
        seed_in (int): Base random seed
        **check_kwargs: Optional overrides for get_feature_delta_signal_pdf (the same as the real check)

    Returns:
        pd.DataFrame: One row per null run (output of get_null_signal_count_dict)
    """
    # IMPORT JOBLIB
    from joblib import Parallel, delayed
    # RUN THE NULL CHECKS
    dict_list = Parallel(n_jobs=job_count_in)(delayed(get_null_signal_count_dict)(train_pdf_in, valid_pdf_in, feature_col_str_list_in, delta_list_in,
                                                                                   run_id, seed_in, **check_kwargs) for run_id in range(run_count_in))
    # RETURN THE RUNS
    return pd.DataFrame(dict_list)

# FUNCTION: GET THE SIGNAL CHECK VERDICT
def get_signal_check_verdict_dict(signal_check_pdf_in, null_count_pdf_in=None, confidence_level_in=config.CONFIDENCE_LEVEL):
    """
    Summarizes the signal check into the stopping-rule verdict.

    Args:
        signal_check_pdf_in (pd.DataFrame): Output of get_signal_check_pdf
        null_count_pdf_in (pd.DataFrame | None): Output of get_null_signal_count_pdf (None = no calibration, unit tests only)
        confidence_level_in (float): Confidence level used by the bootstrap

    Returns:
        dict: test_count, train_pass_count, expected_chance_pass_count (two-sided), expected_chance_signal_count (two-sided,
              assuming independent windows and tests), signal_count, signal_bin_count (distinct feature bins among the
              signals), signal_above_count, signal_below_count, signal_above_breakeven_count, signal_feature_list,
              signal_delta_list, null_run_count, null_signal_bin_count_list, null_max_signal_bin_count, null_p_value,
              verdict_basis, verdict
    """
    # COUNT THE TESTS AND THE SIGNALS
    count_dict = get_signal_count_dict(signal_check_pdf_in)
    test_count = count_dict["test_count"]
    # COLLECT THE SIGNALS
    signal_pdf = signal_check_pdf_in[signal_check_pdf_in["signal"]]
    # IF THERE ARE NULL RUNS: CONTINUE ONLY ABOVE EVERY RUN (TIES STOP)
    if null_count_pdf_in is not None and len(null_count_pdf_in):
        null_count_arr = null_count_pdf_in["signal_bin_count"].to_numpy(dtype=int)
        null_max_int = int(null_count_arr.max())
        null_p_value = float((1 + (null_count_arr >= count_dict["signal_bin_count"]).sum()) / (1 + len(null_count_arr)))
        continue_bool = count_dict["signal_bin_count"] > null_max_int
        verdict_basis_str = f"distinct signal bins above every one of {len(null_count_arr)} null runs"
    # OTHERWISE: AT LEAST ONE SIGNAL (UNCALIBRATED)
    else:
        null_count_arr, null_max_int, null_p_value = np.array([], dtype=int), None, None
        continue_bool = count_dict["signal_count"] > 0
        verdict_basis_str = "at least one signal (no null runs: uncalibrated)"
    # RETURN THE VERDICT
    return {
        "test_count": test_count,
        "train_pass_count": count_dict["train_pass_count"],
        "expected_chance_pass_count": round(test_count * (1 - confidence_level_in), 1),
        "expected_chance_signal_count": round(test_count * 2 * ((1 - confidence_level_in) / 2) ** 2, 1),
        "signal_count": count_dict["signal_count"],
        "signal_bin_count": count_dict["signal_bin_count"],
        "signal_above_count": int(signal_pdf["train_above"].sum()),
        "signal_below_count": int(signal_pdf["train_below"].sum()),
        "signal_above_breakeven_count": int(signal_pdf["above_breakeven"].sum()),
        "signal_feature_list": sorted(signal_pdf["feature"].unique().tolist()),
        "signal_delta_list": sorted(signal_pdf["delta"].unique().tolist()),
        "null_run_count": int(len(null_count_arr)),
        "null_signal_bin_count_list": null_count_arr.tolist(),
        "null_max_signal_bin_count": null_max_int,
        "null_p_value": null_p_value,
        "verdict_basis": verdict_basis_str,
        "verdict": "CONTINUE" if continue_bool else "STOP",
    }
