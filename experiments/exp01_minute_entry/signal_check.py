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
test_count * (1 - CONFIDENCE_LEVEL) (two-sided). The verdict reports both numbers.

Verdict: "CONTINUE" if at least one bin is a signal, otherwise "STOP".
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

# FUNCTION: GET THE SIGNAL CHECK VERDICT
def get_signal_check_verdict_dict(signal_check_pdf_in, confidence_level_in=config.CONFIDENCE_LEVEL):
    """
    Summarizes the signal check into the stopping-rule verdict.

    Args:
        signal_check_pdf_in (pd.DataFrame): Output of get_signal_check_pdf
        confidence_level_in (float): Confidence level used by the bootstrap

    Returns:
        dict: test_count, train_pass_count, expected_chance_pass_count (two-sided), expected_chance_signal_count (two-sided,
              assuming independent windows and tests), signal_count, signal_bin_count (distinct feature bins among the
              signals), signal_above_count, signal_below_count, signal_above_breakeven_count, signal_feature_list,
              signal_delta_list, verdict
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
        "expected_chance_signal_count": round(test_count * 2 * ((1 - confidence_level_in) / 2) ** 2, 1),
        "signal_count": int(len(signal_pdf)),
        "signal_bin_count": int(signal_pdf[["feature", "bin"]].astype(str).drop_duplicates().shape[0]),
        "signal_above_count": int(signal_pdf["train_above"].sum()),
        "signal_below_count": int(signal_pdf["train_below"].sum()),
        "signal_above_breakeven_count": int(signal_pdf["above_breakeven"].sum()),
        "signal_feature_list": sorted(signal_pdf["feature"].unique().tolist()),
        "signal_delta_list": sorted(signal_pdf["delta"].unique().tolist()),
        "verdict": "CONTINUE" if len(signal_pdf) > 0 else "STOP",
    }
