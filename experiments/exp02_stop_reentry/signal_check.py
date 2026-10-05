import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp02_stop_reentry import config as exp_config
# IMPORT THE SIGNAL CHECK BUILDING BLOCKS (QUANTILE BINS, BIN LABELS, BLOCK BOOTSTRAP, MONTH COUNTS)
from so.core.signal_bins import get_quantile_bin_edge_arr, get_bin_label_series, get_bootstrap_bin_stat_pdf, \
                                get_month_block_id_arr, get_bin_month_count_series

"""
Daily Signal Check (exp02 step 02, PROTOCOL.md §11.1): the stopping rule of the re-entry model

Question: does any single daily feature move the rate of positive 20-session forward returns AWAY FROM THE BASE RATE,
reliably, on training AND on the pooled validation quarters?

    - the reference is the BASE RATE of each window (share of positive forward returns), not a break-even rate: market
      drift alone lifts every bin above break-even, it cannot lift a bin above the base rate of the same window;
    - TWO-SIDED: a bin far BELOW the base rate is just as useful (it says "stay in cash") as a bin far above it;
    - validation is POOLED over several consecutive quarters, because one quarter (about 60 daily rows) cannot detect a
      modest effect;
    - bootstrap blocks are calendar months (20-session labels overlap across weeks);
    - a bin's pass counts only if its rows cover at least DAILY_SIGNAL_CHECK_MIN_MONTH_COUNT calendar months in EACH
      window (new in exp02 1.0: a bin concentrated in a few months gets a degenerate interval such as [1.0, 1.0]).

A bin is a signal when its confidence interval excludes the window's base rate ON THE SAME SIDE on training and on the
pooled validation (same bin edges, learned on training).
"""

# FUNCTION: GET THE BIN STATISTICS OF ONE FEATURE IN ONE WINDOW
def get_window_bin_stat_pdf(window_pdf_in, bin_label_series_in, **bootstrap_kwargs):
    """
    Calculates, per bin, the rate of positive forward returns with a monthly block bootstrap interval, against the
    window's base rate.

    Args:
        window_pdf_in (pd.DataFrame): Labelled daily rows of the window
        bin_label_series_in (pd.Series): Bin label per row
        **bootstrap_kwargs: Overrides for so.core.signal_bins.get_bootstrap_bin_stat_pdf (iteration_count_in, ...)

    Returns:
        pd.DataFrame: bin, row_count, month_count, rate, rate_ci_low, rate_ci_high, base_rate, mean_fwd_return
    """
    # COLLECT THE LABELS
    y_arr = window_pdf_in["y_fwd_positive"].to_numpy(dtype=float)
    # COUNT THE DISTINCT CALENDAR MONTHS OF EVERY BIN
    month_count_series = get_bin_month_count_series(bin_label_series_in, window_pdf_in["date"])
    # CALCULATE THE BASE RATE OF THE WINDOW
    base_rate = float(y_arr.mean())
    # CALCULATE THE BIN STATISTICS (THE "BREAKEVEN" SLOT CARRIES THE BASE RATE)
    stat_pdf = get_bootstrap_bin_stat_pdf(bin_label_series_in.reset_index(drop=True), get_month_block_id_arr(window_pdf_in["date"]), y_arr,
                                          window_pdf_in["fwd_net_return_20d"].to_numpy(dtype=float), np.full(len(y_arr), base_rate), **bootstrap_kwargs)
    # ADD THE MONTH COUNT
    stat_pdf["month_count"] = stat_pdf["bin"].map(month_count_series).fillna(0).astype(int)
    # RETURN THE RENAMED STATISTICS
    return stat_pdf.rename(columns={"tp_rate": "rate", "tp_rate_ci_low": "rate_ci_low", "tp_rate_ci_high": "rate_ci_high",
                                    "breakeven_tp_rate": "base_rate", "mean_net_return": "mean_fwd_return"})[
        ["bin", "row_count", "month_count", "rate", "rate_ci_low", "rate_ci_high", "base_rate", "mean_fwd_return"]]

# FUNCTION: RUN THE DAILY SIGNAL CHECK
def get_daily_signal_check_pdf(train_pdf_in, valid_pdf_in, feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST,
                               bin_count_in=exp_config.DAILY_SIGNAL_CHECK_BIN_COUNT,
                               min_bin_count_in=exp_config.DAILY_SIGNAL_CHECK_MIN_BIN_COUNT,
                               min_month_count_in=exp_config.DAILY_SIGNAL_CHECK_MIN_MONTH_COUNT, alert_in=True, **bootstrap_kwargs):
    """
    Runs the two-sided base-rate signal check for every feature.

    Args:
        train_pdf_in (pd.DataFrame): Labelled training rows (so.features.daily_features.get_daily_train_pdf)
        valid_pdf_in (pd.DataFrame): Labelled rows of the pooled validation quarters
        feature_col_str_list_in (list[str]): Features to check
        bin_count_in (int): Quantile bins per feature (edges learned on training)
        min_bin_count_in (int): Minimum rows in a training bin for it to count as a test
        min_month_count_in (int | None): Minimum distinct calendar months of a bin, in EACH window, for its pass to count
            (None = no minimum, the behaviour of the stop_reentry_v2 run of 2026-10-04)
        alert_in (bool): Display progress
        **bootstrap_kwargs: Overrides for the bootstrap

    Returns:
        pd.DataFrame: One row per (feature, bin) with training and validation statistics and the pass / signal flags
    """
    # LIST TO HOLD THE FEATURE RESULTS
    result_pdf_list = []
    # ITERATE OVER THE FEATURES
    for feature_idx, feature_col_str in enumerate(feature_col_str_list_in, 1):
        # DISPLAY PROGRESS
        print(f"Feature:\t{feature_col_str}\t[{feature_idx}/{len(feature_col_str_list_in)}]") if alert_in else None
        # LEARN THE BIN EDGES ON TRAINING
        bin_edge_arr = get_quantile_bin_edge_arr(train_pdf_in[feature_col_str], bin_count_in)
        # CALCULATE THE BIN STATISTICS OF BOTH WINDOWS (SAME EDGES)
        train_stat_pdf = get_window_bin_stat_pdf(train_pdf_in, get_bin_label_series(train_pdf_in[feature_col_str], False, bin_edge_arr), **bootstrap_kwargs)
        valid_stat_pdf = get_window_bin_stat_pdf(valid_pdf_in, get_bin_label_series(valid_pdf_in[feature_col_str], False, bin_edge_arr), **bootstrap_kwargs)
        # MERGE THE WINDOWS ON THE BIN LABEL
        merged_pdf = train_stat_pdf.add_prefix("train_").rename(columns={"train_bin": "bin"}).merge(
            valid_stat_pdf.add_prefix("valid_").rename(columns={"valid_bin": "bin"}), on="bin", how="left")
        # ADD THE FEATURE NAME
        merged_pdf.insert(0, "feature", feature_col_str)
        # APPEND THE FEATURE RESULT
        result_pdf_list.append(merged_pdf)
    # CONCATENATE THE RESULTS
    result_pdf = pd.concat(result_pdf_list, ignore_index=True)
    # DEFINE THE TESTED BINS (ENOUGH TRAINING ROWS, NOT THE MISSING-VALUE BIN)
    result_pdf["tested"] = (result_pdf["train_row_count"] >= min_bin_count_in) & (result_pdf["bin"] != "NaN")
    # DEFINE THE PASSES ABOVE AND BELOW THE BASE RATE IN EACH WINDOW
    result_pdf["train_above"] = result_pdf["tested"] & (result_pdf["train_rate_ci_low"] > result_pdf["train_base_rate"])
    result_pdf["train_below"] = result_pdf["tested"] & (result_pdf["train_rate_ci_high"] < result_pdf["train_base_rate"])
    result_pdf["valid_above"] = (result_pdf["valid_rate_ci_low"] > result_pdf["valid_base_rate"]).fillna(False).astype(bool)
    result_pdf["valid_below"] = (result_pdf["valid_rate_ci_high"] < result_pdf["valid_base_rate"]).fillna(False).astype(bool)
    # IF A MONTH MINIMUM IS REQUIRED
    if min_month_count_in is not None:
        # DEFINE THE BINS WITH ENOUGH MONTHS IN EACH WINDOW
        train_month_ok = result_pdf["train_month_count"] >= min_month_count_in
        valid_month_ok = result_pdf["valid_month_count"].fillna(0) >= min_month_count_in
        # APPLY THE MINIMUM TO THE TESTS AND THE PASSES
        result_pdf["tested"] = result_pdf["tested"] & train_month_ok
        result_pdf["train_above"] &= train_month_ok
        result_pdf["train_below"] &= train_month_ok
        result_pdf["valid_above"] &= valid_month_ok
        result_pdf["valid_below"] &= valid_month_ok
    # DEFINE THE SIGNALS (SAME SIDE IN BOTH WINDOWS)
    result_pdf["signal"] = (result_pdf["train_above"] & result_pdf["valid_above"]) | (result_pdf["train_below"] & result_pdf["valid_below"])
    # RETURN THE RESULTS
    return result_pdf

# FUNCTION: GET THE DAILY SIGNAL CHECK VERDICT
def get_daily_signal_check_verdict_dict(signal_check_pdf_in, confidence_level_in=config.CONFIDENCE_LEVEL):
    """
    Summarizes the daily signal check into the stopping-rule verdict.

    Args:
        signal_check_pdf_in (pd.DataFrame): Output of get_daily_signal_check_pdf
        confidence_level_in (float): Confidence level of the bootstrap

    Returns:
        dict: test_count, train_pass_count, expected_chance_pass_count (two-sided), signal_count, signal_feature_list, verdict
    """
    # COUNT THE TESTS
    test_count = int(signal_check_pdf_in["tested"].sum())
    # COLLECT THE SIGNALS
    signal_pdf = signal_check_pdf_in[signal_check_pdf_in["signal"]]
    # RETURN THE VERDICT
    return {
        "test_count": test_count,
        "train_pass_count": int((signal_check_pdf_in["train_above"] | signal_check_pdf_in["train_below"]).sum()),
        "expected_chance_pass_count": round(test_count * (1 - confidence_level_in), 1),
        "signal_count": int(len(signal_pdf)),
        "signal_feature_list": sorted(signal_pdf["feature"].unique().tolist()),
        "verdict": "CONTINUE" if len(signal_pdf) > 0 else "STOP",
    }
