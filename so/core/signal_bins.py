import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (BOOTSTRAP SETTINGS AND SEED)
from so import config

"""
Signal Check Building Blocks (shared by the signal checks of every experiment)

    - bootstrap blocks: ISO weeks, session days or calendar months (rows of the same block are resampled together, so
      overlapping trades or labels of the same period stay together);
    - quantile bins learned on the training window and re-used on validation;
    - per-bin rates with block-bootstrap confidence intervals, compared by each experiment with its reference rate
      (the window's base rate since 2026-10-05: market drift alone cannot lift a bin above the base rate of its window).
"""

# FUNCTION: GET THE BOOTSTRAP BLOCK IDS
def get_block_id_arr(decision_ts_series_in, block_str_in):
    """
    Assigns each row to a bootstrap block (ISO week or session date).

    Args:
        decision_ts_series_in (pd.Series): Decision timestamps
        block_str_in (str): "week" or "day"

    Returns:
        np.ndarray: Integer block id per row
    """
    # IF THE BLOCK IS A WEEK
    if block_str_in == "week":
        # COLLECT THE ISO YEAR AND WEEK
        iso_pdf = decision_ts_series_in.dt.isocalendar()
        block_key_series = iso_pdf["year"].astype(int) * 100 + iso_pdf["week"].astype(int)
    # IF THE BLOCK IS A DAY
    elif block_str_in == "day":
        # COLLECT THE SESSION DATE
        block_key_series = pd.Series(decision_ts_series_in.dt.strftime("%Y%m%d").astype(int).to_numpy())
    # IF THE BLOCK IS UNKNOWN
    else:
        # RAISE AN ERROR
        raise ValueError(f"Unknown bootstrap block '{block_str_in}'")
    # RETURN THE INTEGER BLOCK IDS
    return pd.factorize(np.asarray(block_key_series))[0]

# FUNCTION: GET THE BIN EDGES OF A NUMERIC FEATURE
def get_quantile_bin_edge_arr(value_series_in, bin_count_in):
    """
    Calculates quantile bin edges on the training values (duplicate edges are merged, the outer edges are infinite).

    Args:
        value_series_in (pd.Series): Training values of the feature
        bin_count_in (int): Number of quantile bins

    Returns:
        np.ndarray: Bin edges (length = number of bins + 1)
    """
    # COLLECT THE FINITE VALUES
    finite_arr = value_series_in.replace([np.inf, -np.inf], np.nan).dropna().to_numpy(dtype=float)
    # IF THERE ARE NO FINITE VALUES
    if len(finite_arr) == 0:
        # RETURN A SINGLE BIN
        return np.array([-np.inf, np.inf])
    # CALCULATE THE INNER QUANTILE EDGES
    inner_edge_arr = np.unique(np.quantile(finite_arr, np.linspace(0, 1, bin_count_in + 1)[1:-1]))
    # RETURN THE EDGES WITH INFINITE OUTER BOUNDS
    return np.concatenate([[-np.inf], inner_edge_arr, [np.inf]])

# FUNCTION: ASSIGN THE BIN OF EVERY ROW
def get_bin_label_series(value_series_in, is_categorical_bool_in, bin_edge_arr_in=None):
    """
    Assigns each row to a bin label: the category itself for categoricals, the interval for numeric features.
    Missing values get the bin label "NaN" (missing is information too).

    Args:
        value_series_in (pd.Series): Feature values
        is_categorical_bool_in (bool): True for categorical features
        bin_edge_arr_in (np.ndarray | None): Bin edges for numeric features

    Returns:
        pd.Series: Bin label (str) per row
    """
    # IF THE FEATURE IS CATEGORICAL
    if is_categorical_bool_in:
        # RETURN THE CATEGORY AS A STRING
        return value_series_in.astype(object).where(value_series_in.notna(), "NaN").astype(str)
    # CONVERT THE VALUES TO FLOAT
    value_series = pd.to_numeric(value_series_in, errors="coerce").replace([np.inf, -np.inf], np.nan)
    # CUT THE VALUES INTO BINS
    bin_series = pd.cut(value_series, bins=bin_edge_arr_in, right=True, include_lowest=True)
    # RETURN THE BIN LABEL (MISSING VALUES -> "NaN")
    return bin_series.astype(str).where(value_series.notna(), "NaN")

# FUNCTION: GET THE BOOTSTRAPPED BIN STATISTICS
def get_bootstrap_bin_stat_pdf(bin_label_series_in, block_id_arr_in, y_tp_arr_in, net_return_arr_in, breakeven_arr_in,
                               iteration_count_in=config.BOOTSTRAP_ITERATION_COUNT,
                               confidence_level_in=config.CONFIDENCE_LEVEL,
                               seed_in=config.RANDOM_SEED):
    """
    Calculates per-bin statistics with block bootstrap confidence intervals.

    Args:
        bin_label_series_in (pd.Series): Bin label per row
        block_id_arr_in (np.ndarray): Bootstrap block id per row
        y_tp_arr_in (np.ndarray): 1 if take profit, 0 otherwise (resolved rows only)
        net_return_arr_in (np.ndarray): Net return per row
        breakeven_arr_in (np.ndarray): Breakeven take profit rate per row
        iteration_count_in (int): Bootstrap iterations
        confidence_level_in (float): Two-sided confidence level
        seed_in (int): Random seed

    Returns:
        pd.DataFrame: One row per bin: bin, row_count, tp_rate, tp_rate_ci_low, tp_rate_ci_high, breakeven_tp_rate,
                      mean_net_return, net_return_ci_low, net_return_ci_high
    """
    # FACTORIZE THE BIN LABELS
    bin_code_arr, bin_label_arr = pd.factorize(bin_label_series_in)
    # COLLECT THE NUMBER OF BINS AND BLOCKS
    bin_count, block_count = len(bin_label_arr), int(block_id_arr_in.max()) + 1
    # BUILD THE BLOCK x BIN SUM MATRICES
    count_mat = np.zeros((block_count, bin_count))
    tp_mat = np.zeros((block_count, bin_count))
    net_mat = np.zeros((block_count, bin_count))
    np.add.at(count_mat, (block_id_arr_in, bin_code_arr), 1)
    np.add.at(tp_mat, (block_id_arr_in, bin_code_arr), y_tp_arr_in)
    np.add.at(net_mat, (block_id_arr_in, bin_code_arr), net_return_arr_in)
    # DRAW THE BOOTSTRAP BLOCK WEIGHTS (HOW MANY TIMES EACH BLOCK IS RESAMPLED)
    rng = np.random.default_rng(seed_in)
    weight_mat = np.zeros((iteration_count_in, block_count))
    np.add.at(weight_mat, (np.repeat(np.arange(iteration_count_in), block_count), rng.integers(0, block_count, size=iteration_count_in * block_count)), 1)
    # CALCULATE THE BOOTSTRAPPED STATISTICS (ITERATIONS x BINS)
    with np.errstate(invalid="ignore", divide="ignore"):
        boot_count_mat = weight_mat @ count_mat
        boot_tp_rate_mat = (weight_mat @ tp_mat) / boot_count_mat
        boot_net_mat = (weight_mat @ net_mat) / boot_count_mat
    # DEFINE THE PERCENTILES
    low_pct, high_pct = 100 * (1 - confidence_level_in) / 2, 100 * (1 + confidence_level_in) / 2
    # CALCULATE THE BIN TOTALS
    row_count_arr = count_mat.sum(axis=0)
    # CALCULATE THE MEAN BREAKEVEN PER BIN
    breakeven_sum_arr = np.bincount(bin_code_arr, weights=breakeven_arr_in, minlength=bin_count)
    # RETURN DATAFRAME
    return pd.DataFrame({
        "bin": bin_label_arr.astype(str),
        "row_count": row_count_arr.astype(int),
        "tp_rate": tp_mat.sum(axis=0) / row_count_arr,
        "tp_rate_ci_low": np.nanpercentile(boot_tp_rate_mat, low_pct, axis=0),
        "tp_rate_ci_high": np.nanpercentile(boot_tp_rate_mat, high_pct, axis=0),
        "breakeven_tp_rate": breakeven_sum_arr / row_count_arr,
        "mean_net_return": net_mat.sum(axis=0) / row_count_arr,
        "net_return_ci_low": np.nanpercentile(boot_net_mat, low_pct, axis=0),
        "net_return_ci_high": np.nanpercentile(boot_net_mat, high_pct, axis=0),
    })

# FUNCTION: GET THE CALENDAR MONTH BLOCK IDS
def get_month_block_id_arr(date_series_in):
    """
    Assigns every row to its calendar month (bootstrap block).

    Args:
        date_series_in (pd.Series): Session dates or timestamps

    Returns:
        np.ndarray: Integer block id per row
    """
    # RETURN THE FACTORIZED MONTHS
    return pd.factorize(get_month_label_arr(date_series_in))[0]

# FUNCTION: GET THE CALENDAR MONTH LABEL OF EVERY ROW
def get_month_label_arr(date_series_in):
    """
    Returns the calendar month ("YYYY-MM") of every row.

    Args:
        date_series_in (pd.Series): Session dates or timestamps (timezone-aware timestamps are allowed)

    Returns:
        np.ndarray: Month label per row
    """
    # CONVERT TO DATETIMES (TIMEZONE DROPPED: THE MONTH OF THE LOCAL TIMESTAMP IS KEPT)
    datetime_series = pd.Series(pd.to_datetime(pd.Series(date_series_in).reset_index(drop=True)))
    # IF THE TIMESTAMPS ARE TIMEZONE-AWARE
    if getattr(datetime_series.dt, "tz", None) is not None:
        # DROP THE TIMEZONE
        datetime_series = datetime_series.dt.tz_localize(None)
    # RETURN THE MONTH LABELS
    return datetime_series.dt.to_period("M").astype(str).to_numpy()

# FUNCTION: COUNT THE DISTINCT MONTHS OF EVERY BIN
def get_bin_month_count_series(bin_label_series_in, date_series_in):
    """
    Counts the distinct calendar months covered by the rows of every bin (a bin whose rows fall in a few months gets a
    degenerate bootstrap interval, e.g. [1.0, 1.0], so experiments require a minimum number of months).

    Args:
        bin_label_series_in (pd.Series): Bin label per row
        date_series_in (pd.Series): Session date or timestamp per row (same order)

    Returns:
        pd.Series: Bin label -> number of distinct months
    """
    # RETURN THE DISTINCT MONTHS PER BIN
    return pd.Series(get_month_label_arr(date_series_in)).groupby(pd.Series(bin_label_series_in).reset_index(drop=True).astype(str).to_numpy()).nunique()
