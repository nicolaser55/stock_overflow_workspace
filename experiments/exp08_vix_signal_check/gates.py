import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp08_vix_signal_check import config as exp_config
# IMPORT THE SIGNAL CHECK BUILDING BLOCKS
from so.core.signal_bins import get_quantile_bin_edge_arr, get_bin_label_series, get_bootstrap_bin_stat_pdf, get_month_block_id_arr
# IMPORT THE REPLAY PERIODS (THE VALIDATION ROWS TILE THE SPAN AS THE CONTINUOUS REPLAYS DO)
from so.core.continuous_replay import get_replay_period_pdf
# IMPORT THE EXPERIMENT FUNCTIONS REUSED AS THEY ARE (exp02 SIGNAL CHECK AND LOGISTIC MODEL, exp05 FORWARD VOLATILITY)
from experiments.exp02_stop_reentry.signal_check import get_daily_signal_check_pdf
from experiments.exp02_stop_reentry.walk_forward import fit_reentry_model_dict, predict_reentry_proba_arr
from experiments.exp05_vol_scaled_exposure.exposure import get_forward_volatility_arr

"""
Gates: exp08_vix_signal_check (PROTOCOL.md §4-§7)

Analysis rows: SPY sessions from ANALYSIS_START_DATE_STR to the last validation session whose label and every one of the
22 features (16 price features + 6 VIX features of the variant) are known. Training = analysis rows up to the first
fold's train_end; validation = analysis rows of the 44 replay periods (pooled), which tile 2015-04-17 -> 2026-04-15 as
the continuous replays do: each session once, predicted in G2 by the model of the fold whose period contains it.

    G1  exp02's daily signal check on the six VIX features; S1 = number of signal (feature, bin) pairs.
    G2  exp02's logistic regression per fold (expanding training from the analysis start to train_end(f)), BASE (16)
        vs AUGMENTED (22) on the same rows; dAUC = pooled out-of-sample AUC(AUGMENTED) - AUC(BASE).
    G3  D = Spearman(vix_level_prev, forward 20-session volatility) - Spearman(daily_volatility, same) on the validation
        rows; circular month-block bootstrap (6-month blocks).
    G4  mean fwd_net_return_20d of the rows whose vix_level_prev is at or above the training 80th percentile, on training
        and on validation; PASS only if both means are below 0.
    Null (G1, G2): the block of the six VIX columns is circularly shifted by k sessions over all analysis rows (dates,
        labels and price features stay in place); everything learned is re-learned; p = (1 + #null >= real) / (runs + 1).
"""

# FUNCTION: CHECK THE SCHEDULE
def check_schedule_dict(fold_pdf_in):
    """
    Asserts the 44-quarter schedule of exp02-exp07 (first valid_start 2015-04-17, last valid_end 2026-04-15, latest
    test_start 2026-05-14, first train_end 2015-03-18).

    Args:
        fold_pdf_in (pd.DataFrame): Output of exp04's get_schedule_tuple

    Returns:
        dict: fold_count, first_train_end, first_valid_start, last_valid_end, latest_test_start
    """
    # COLLECT THE SCHEDULE FACTS
    schedule_dict = {"fold_count": int(len(fold_pdf_in)), "first_train_end": str(pd.to_datetime(fold_pdf_in["train_end"].iloc[0]).date()),
                     "first_valid_start": str(pd.to_datetime(fold_pdf_in["valid_start"].iloc[0]).date()),
                     "last_valid_end": str(pd.to_datetime(fold_pdf_in["valid_end"].iloc[-1]).date()),
                     "latest_test_start": str(pd.to_datetime(fold_pdf_in["test_start"].iloc[-1]).date())}
    # ASSERT THE EXPECTED VALUES
    assert schedule_dict == {"fold_count": exp_config.EXPECTED_FOLD_COUNT, "first_train_end": exp_config.EXPECTED_FIRST_TRAIN_END_STR,
                             "first_valid_start": exp_config.EXPECTED_FIRST_VALID_START_STR, "last_valid_end": exp_config.EXPECTED_LAST_VALID_END_STR,
                             "latest_test_start": exp_config.EXPECTED_LATEST_TEST_START_STR}, f"❌ Unexpected schedule: {schedule_dict}"
    # RETURN THE FACTS
    return schedule_dict

# FUNCTION: GET THE VALIDATION PERIOD OF EVERY DATE
def get_valid_fold_id_arr(date_arr_in, period_pdf_in):
    """
    Returns the replay period (so.core.continuous_replay.get_replay_period_pdf: consecutive, non-overlapping periods that
    tile the validation span; a session shared by two quarters belongs to the later one, a session between two quarters
    to the earlier one) that contains each date (-1 outside the span).

    Args:
        date_arr_in (np.ndarray): Session dates (datetime.date)
        period_pdf_in (pd.DataFrame): Replay periods (period_id = fold_id, period_start, period_end)

    Returns:
        np.ndarray: Fold id per date
    """
    # START OUTSIDE EVERY PERIOD
    fold_id_arr = np.full(len(date_arr_in), -1)
    # ITERATE OVER THE PERIODS
    for _, period_row in period_pdf_in.iterrows():
        # FLAG THE DATES OF THE PERIOD
        in_bool_arr = (date_arr_in >= period_row["period_start"]) & (date_arr_in <= period_row["period_end"])
        fold_id_arr[in_bool_arr] = int(period_row["period_id"])
    # RETURN THE FOLD IDS
    return fold_id_arr

# FUNCTION: BUILD THE ANALYSIS ROWS
def get_analysis_pdf(daily_pdf_in, vix_feature_pdf_in, fold_pdf_in, vix_col_str_list_in, base_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST,
                     start_date_str_in=exp_config.ANALYSIS_START_DATE_STR, label_horizon_in=config.LABEL_HORIZON_SESSIONS):
    """
    Joins the SPY table and the VIX features and keeps the analysis rows: dates from the start to the last validation
    session, label and every feature known. Adds the label end date (date of session i + horizon), the training flag
    (date <= first train_end) and the validation fold.

    Args:
        daily_pdf_in (pd.DataFrame): Daily SPY table (so.features.daily_features), all sessions of the cut data
        vix_feature_pdf_in (pd.DataFrame): VIX features of the same sessions (session_idx + feature columns)
        fold_pdf_in (pd.DataFrame): Fold schedule
        vix_col_str_list_in (list[str]): VIX feature columns of the variant
        base_col_str_list_in (list[str]): Price features
        start_date_str_in (str): First date of the analysis
        label_horizon_in (int): Label horizon (sessions)

    Returns:
        pd.DataFrame: Analysis rows in session order (index reset)
    """
    # JOIN THE VIX FEATURES ON THE SESSION
    joined_pdf = daily_pdf_in.merge(vix_feature_pdf_in[["session_idx"] + list(vix_col_str_list_in)], on="session_idx", how="left", validate="one_to_one")
    # ADD THE LABEL END DATE (DATE OF SESSION i + HORIZON; NaT WHEN BEYOND THE DATA)
    joined_pdf["label_end_date"] = joined_pdf["date"].shift(-label_horizon_in)
    # SELECT THE DATES
    last_valid_end = pd.to_datetime(fold_pdf_in["valid_end"].iloc[-1]).date()
    window_pdf = joined_pdf[(joined_pdf["date"] >= pd.Timestamp(start_date_str_in).date()) & (joined_pdf["date"] <= last_valid_end)]
    # KEEP THE COMPLETE ROWS
    analysis_pdf = window_pdf.dropna(subset=list(base_col_str_list_in) + list(vix_col_str_list_in) + ["y_fwd_positive", "label_end_date"]).reset_index(drop=True)
    # ADD THE TRAINING FLAG AND THE VALIDATION PERIOD
    analysis_pdf["is_train"] = analysis_pdf["date"] <= pd.to_datetime(fold_pdf_in["train_end"].iloc[0]).date()
    analysis_pdf["valid_fold_id"] = get_valid_fold_id_arr(np.array(analysis_pdf["date"].tolist()), get_replay_period_pdf(fold_pdf_in, daily_pdf_in["date"].tolist()))
    # RETURN THE ROWS
    return analysis_pdf

# FUNCTION: SHIFT THE VIX BLOCK CIRCULARLY (ONE NULL RUN)
def get_shifted_analysis_pdf(analysis_pdf_in, vix_col_str_list_in, run_idx_in, seed_in=exp_config.NULL_SEED, share_range_in=exp_config.NULL_SHIFT_SHARE_RANGE):
    """
    Circularly shifts the VIX feature columns together by k rows (k = round(u x row count), u uniform in the share range,
    seed = seed_in + run_idx_in); dates, labels and price features stay in place.

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        vix_col_str_list_in (list[str]): VIX feature columns shifted as one block
        run_idx_in (int): Null run index
        seed_in (int): Base seed
        share_range_in (tuple): Range of the shift as a share of the rows

    Returns:
        tuple: (shifted analysis rows, k)
    """
    # DRAW THE SHIFT
    rng = np.random.default_rng(seed_in + run_idx_in)
    shift_int = int(round(rng.uniform(share_range_in[0], share_range_in[1]) * len(analysis_pdf_in)))
    # SHIFT THE BLOCK
    shifted_pdf = analysis_pdf_in.copy()
    shifted_pdf[list(vix_col_str_list_in)] = np.roll(analysis_pdf_in[list(vix_col_str_list_in)].to_numpy(), shift_int, axis=0)
    # RETURN THE ROWS AND THE SHIFT
    return shifted_pdf, shift_int

# FUNCTION: RUN G1 (UNIVARIATE SIGNAL CHECK)
def run_g1_dict(analysis_pdf_in, vix_col_str_list_in):
    """
    exp02's daily signal check of the VIX features (training = is_train rows, validation = rows of the 44 quarters).

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        vix_col_str_list_in (list[str]): VIX feature columns

    Returns:
        dict: signal_check_pdf, s1 (number of signal pairs), test_count, signal_pair_list
    """
    # SPLIT THE WINDOWS
    train_pdf = analysis_pdf_in[analysis_pdf_in["is_train"]]
    valid_pdf = analysis_pdf_in[analysis_pdf_in["valid_fold_id"] >= 0]
    # RUN exp02's SIGNAL CHECK WITH THIS EXPERIMENT'S (IDENTICAL) CONSTANTS
    signal_check_pdf = get_daily_signal_check_pdf(train_pdf, valid_pdf, list(vix_col_str_list_in), exp_config.SIGNAL_CHECK_BIN_COUNT,
                                                  exp_config.SIGNAL_CHECK_MIN_BIN_COUNT, exp_config.SIGNAL_CHECK_MIN_MONTH_COUNT, alert_in=False)
    # COLLECT THE SIGNALS
    signal_pdf = signal_check_pdf[signal_check_pdf["signal"]]
    # RETURN THE RESULT
    return {"signal_check_pdf": signal_check_pdf, "s1": int(len(signal_pdf.drop_duplicates(["feature", "bin"]))), "test_count": int(signal_check_pdf["tested"].sum()),
            "signal_pair_list": [f"{f} {b}" for f, b in zip(signal_pdf["feature"], signal_pdf["bin"])]}

# FUNCTION: GET THE POOLED OUT-OF-SAMPLE PREDICTIONS OF A FEATURE SET
def get_fold_prediction_pdf(analysis_pdf_in, fold_pdf_in, feature_col_str_list_in):
    """
    Fits exp02's logistic regression for every fold on the analysis rows from the start to train_end(f) (expanding) and
    predicts the rows of the fold's replay period.

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        fold_pdf_in (pd.DataFrame): Fold schedule
        feature_col_str_list_in (list[str]): Model features

    Returns:
        pd.DataFrame: date, valid_fold_id, y_fwd_positive, proba (one row per validation row)
    """
    # LIST TO HOLD THE FOLD PREDICTIONS
    prediction_pdf_list = []
    # ITERATE OVER THE FOLDS
    for _, fold_row in fold_pdf_in.iterrows():
        # SELECT THE TRAINING ROWS (EXPANDING) AND ASSERT EVERY TRAINING LABEL ENDS BEFORE THE QUARTER
        valid_start, train_end = pd.to_datetime(fold_row["valid_start"]).date(), pd.to_datetime(fold_row["train_end"]).date()
        train_pdf = analysis_pdf_in[analysis_pdf_in["date"] <= train_end]
        assert max(train_pdf["label_end_date"]) < valid_start, f"❌ Fold {fold_row['fold_id']}: a training label ends inside the quarter"
        # SELECT THE PREDICTION ROWS
        valid_pdf = analysis_pdf_in[analysis_pdf_in["valid_fold_id"] == int(fold_row["fold_id"])]
        # FIT AND PREDICT
        model_dict = fit_reentry_model_dict(train_pdf, list(feature_col_str_list_in), exp_config.MODEL_STR)
        prediction_pdf_list.append(pd.DataFrame({"date": valid_pdf["date"].to_numpy(), "valid_fold_id": valid_pdf["valid_fold_id"].to_numpy(),
                                                 "y_fwd_positive": valid_pdf["y_fwd_positive"].to_numpy(dtype=int),
                                                 "proba": predict_reentry_proba_arr(model_dict, valid_pdf, list(feature_col_str_list_in)),
                                                 "train_row_count": model_dict["row_count"], "train_base_rate": model_dict["base_rate"]}))
    # RETURN THE PREDICTIONS
    return pd.concat(prediction_pdf_list, ignore_index=True)

# FUNCTION: RUN G2 (INCREMENTAL INFORMATION)
def run_g2_dict(analysis_pdf_in, fold_pdf_in, vix_col_str_list_in, base_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST, base_prediction_pdf_in=None):
    """
    Pooled out-of-sample AUC of AUGMENTED (price + VIX) minus BASE (price) over the 44 quarters, on the same rows.

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        fold_pdf_in (pd.DataFrame): Fold schedule
        vix_col_str_list_in (list[str]): VIX feature columns
        base_col_str_list_in (list[str]): Price features
        base_prediction_pdf_in (pd.DataFrame | None): BASE predictions already computed (unchanged by the null)

    Returns:
        dict: base_prediction_pdf, augmented_prediction_pdf, auc_base, auc_augmented, d_auc, quarter_pdf, mean_quarter_d_auc
    """
    # PREDICT WITH BOTH FEATURE SETS
    base_prediction_pdf = base_prediction_pdf_in if base_prediction_pdf_in is not None else get_fold_prediction_pdf(analysis_pdf_in, fold_pdf_in, base_col_str_list_in)
    augmented_prediction_pdf = get_fold_prediction_pdf(analysis_pdf_in, fold_pdf_in, list(base_col_str_list_in) + list(vix_col_str_list_in))
    assert (base_prediction_pdf["date"].to_numpy() == augmented_prediction_pdf["date"].to_numpy()).all()
    # CALCULATE THE POOLED AUCS
    y_arr = base_prediction_pdf["y_fwd_positive"].to_numpy()
    auc_base, auc_augmented = float(roc_auc_score(y_arr, base_prediction_pdf["proba"])), float(roc_auc_score(y_arr, augmented_prediction_pdf["proba"]))
    # CALCULATE THE AUCS PER QUARTER (QUARTERS WITH ONE CLASS ONLY GET NaN)
    quarter_row_list = []
    for fold_id, fold_idx_arr in base_prediction_pdf.groupby("valid_fold_id").indices.items():
        fold_y_arr = y_arr[fold_idx_arr]
        two_class_bool = 0 < fold_y_arr.mean() < 1
        quarter_row_list.append({"fold_id": int(fold_id), "row_count": len(fold_idx_arr), "positive_share": float(fold_y_arr.mean()),
                                 "auc_base": float(roc_auc_score(fold_y_arr, base_prediction_pdf["proba"].to_numpy()[fold_idx_arr])) if two_class_bool else np.nan,
                                 "auc_augmented": float(roc_auc_score(fold_y_arr, augmented_prediction_pdf["proba"].to_numpy()[fold_idx_arr])) if two_class_bool else np.nan})
    quarter_pdf = pd.DataFrame(quarter_row_list)
    quarter_pdf["d_auc"] = quarter_pdf["auc_augmented"] - quarter_pdf["auc_base"]
    # RETURN THE RESULT
    return {"base_prediction_pdf": base_prediction_pdf, "augmented_prediction_pdf": augmented_prediction_pdf, "auc_base": auc_base, "auc_augmented": auc_augmented,
            "d_auc": auc_augmented - auc_base, "quarter_pdf": quarter_pdf, "mean_quarter_d_auc": float(quarter_pdf["d_auc"].mean())}

# FUNCTION: GET MONTH-BLOCK BOOTSTRAP INTERVALS OF THE POOLED AUCS
def get_auc_interval_dict(base_prediction_pdf_in, augmented_prediction_pdf_in, iteration_count_in=config.BOOTSTRAP_ITERATION_COUNT,
                          confidence_level_in=config.CONFIDENCE_LEVEL, seed_in=config.RANDOM_SEED):
    """
    Resamples calendar months with replacement (1-month blocks) and recomputes AUC(BASE), AUC(AUGMENTED) and dAUC.

    Args:
        base_prediction_pdf_in, augmented_prediction_pdf_in (pd.DataFrame): Pooled predictions (same rows, same order)
        iteration_count_in (int): Bootstrap iterations
        confidence_level_in (float): Two-sided confidence level
        seed_in (int): Random seed

    Returns:
        dict: {auc_base, auc_augmented, d_auc}_ci_low / _ci_high
    """
    # COLLECT THE ROWS OF EVERY MONTH
    month_id_arr = get_month_block_id_arr(base_prediction_pdf_in["date"])
    month_idx_list = [np.flatnonzero(month_id_arr == month_id) for month_id in range(int(month_id_arr.max()) + 1)]
    y_arr, base_arr, augmented_arr = (base_prediction_pdf_in["y_fwd_positive"].to_numpy(), base_prediction_pdf_in["proba"].to_numpy(),
                                      augmented_prediction_pdf_in["proba"].to_numpy())
    # RESAMPLE THE MONTHS
    rng = np.random.default_rng(seed_in)
    boot_list = []
    for _ in range(iteration_count_in):
        sample_idx_arr = np.concatenate([month_idx_list[m] for m in rng.integers(0, len(month_idx_list), size=len(month_idx_list))])
        sample_y_arr = y_arr[sample_idx_arr]
        if 0 < sample_y_arr.mean() < 1:
            auc_base, auc_augmented = roc_auc_score(sample_y_arr, base_arr[sample_idx_arr]), roc_auc_score(sample_y_arr, augmented_arr[sample_idx_arr])
            boot_list.append((auc_base, auc_augmented, auc_augmented - auc_base))
    # CALCULATE THE PERCENTILES
    boot_arr = np.array(boot_list)
    low_pct, high_pct = 100 * (1 - confidence_level_in) / 2, 100 * (1 + confidence_level_in) / 2
    result_dict = {}
    for col_idx, name_str in enumerate(["auc_base", "auc_augmented", "d_auc"]):
        result_dict[f"{name_str}_ci_low"], result_dict[f"{name_str}_ci_high"] = (float(v) for v in np.percentile(boot_arr[:, col_idx], [low_pct, high_pct]))
    # RETURN THE INTERVALS
    return result_dict

# FUNCTION: RUN A STATISTIC UNDER THE SESSION-SHIFTED NULL
def get_null_dict(analysis_pdf_in, vix_col_str_list_in, statistic_func_in, real_value_in, run_count_in=exp_config.NULL_RUN_COUNT, seed_in=exp_config.NULL_SEED,
                  share_range_in=exp_config.NULL_SHIFT_SHARE_RANGE, alert_in=True):
    """
    Recomputes a statistic on run_count_in circularly shifted copies of the analysis rows (VIX block shifted, everything
    re-learned by the statistic function) and compares the real value with the null runs.

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        vix_col_str_list_in (list[str]): VIX feature columns (shifted as one block)
        statistic_func_in (callable): f(analysis_pdf) -> float
        real_value_in (float): Statistic on the real rows
        run_count_in (int): Null runs
        seed_in (int): Base seed
        share_range_in (tuple): Shift range (share of the rows)
        alert_in (bool): Display progress

    Returns:
        dict: null_value_list, shift_list, null_max, null_ge_count, p_value, passed (real > null maximum)
    """
    # LISTS TO HOLD THE RUNS
    null_value_list, shift_list = [], []
    # ITERATE OVER THE RUNS
    for run_idx in range(run_count_in):
        # SHIFT THE VIX BLOCK AND RECOMPUTE THE STATISTIC
        shifted_pdf, shift_int = get_shifted_analysis_pdf(analysis_pdf_in, vix_col_str_list_in, run_idx, seed_in, share_range_in)
        null_value_list.append(float(statistic_func_in(shifted_pdf)))
        shift_list.append(shift_int)
        print(f"\tnull run {run_idx + 1}/{run_count_in}: shift {shift_int} rows, value {null_value_list[-1]:.4f}") if alert_in else None
    # COMPARE THE REAL VALUE
    null_ge_count = int(sum(value >= real_value_in for value in null_value_list))
    # RETURN THE NULL
    return {"null_value_list": null_value_list, "shift_list": shift_list, "null_max": float(max(null_value_list)), "null_ge_count": null_ge_count,
            "p_value": (1 + null_ge_count) / (run_count_in + 1), "passed": bool(real_value_in > max(null_value_list))}

# FUNCTION: RUN G3 (VOLATILITY FORECAST)
def run_g3_dict(analysis_pdf_in, daily_pdf_in, level_col_str_in="vix_level_prev", horizon_in=exp_config.FORWARD_VOLATILITY_HORIZON_SESSIONS,
                iteration_count_in=exp_config.G3_BOOTSTRAP_ITERATION_COUNT, block_month_count_in=exp_config.G3_BLOCK_MONTH_COUNT, seed_in=config.RANDOM_SEED):
    """
    D = Spearman(VIX level, forward realized volatility) - Spearman(daily_volatility, forward realized volatility) on the
    validation rows, with exp05's circular month-block bootstrap (the same resampled rows for both correlations).

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows (session_idx, date, valid_fold_id, daily_volatility, VIX level)
        daily_pdf_in (pd.DataFrame): Daily SPY table of the cut data (session_close; the forward volatility is computed on it)
        level_col_str_in (str): VIX level column
        horizon_in (int): Forward horizon (sessions)
        iteration_count_in (int): Bootstrap iterations
        block_month_count_in (int): Months per circular block
        seed_in (int): Random seed

    Returns:
        dict: row_count, month_count, spearman_vix, spearman_realized, d, d_ci_low, d_ci_high, last_forward_session_date, passed
    """
    # COMPUTE THE FORWARD VOLATILITY ON THE DAILY TABLE AND ATTACH IT BY SESSION
    forward_arr = get_forward_volatility_arr(daily_pdf_in, horizon_in)
    forward_series = pd.Series(forward_arr, index=daily_pdf_in["session_idx"].to_numpy())
    valid_pdf = analysis_pdf_in[analysis_pdf_in["valid_fold_id"] >= 0].copy()
    valid_pdf["forward_volatility"] = forward_series.reindex(valid_pdf["session_idx"].to_numpy()).to_numpy()
    # KEEP THE FINITE POSITIVE ROWS
    mask_arr = np.isfinite(valid_pdf[[level_col_str_in, "daily_volatility", "forward_volatility"]].to_numpy(dtype=float)).all(axis=1) & (valid_pdf["forward_volatility"] > 0).to_numpy()
    valid_pdf = valid_pdf[mask_arr]
    # COLLECT THE LAST SESSION REACHED BY A FORWARD VOLATILITY (SESSION i + HORIZON)
    session_date_series = pd.Series(daily_pdf_in["date"].to_numpy(), index=daily_pdf_in["session_idx"].to_numpy())
    last_forward_session_date = session_date_series[int(valid_pdf["session_idx"].max()) + horizon_in]
    # CALCULATE THE OBSERVED STATISTICS
    level_arr, realized_arr, target_arr = (valid_pdf[c].to_numpy(dtype=float) for c in [level_col_str_in, "daily_volatility", "forward_volatility"])
    spearman_vix, spearman_realized = float(spearmanr(level_arr, target_arr).correlation), float(spearmanr(realized_arr, target_arr).correlation)
    # RESAMPLE CIRCULAR BLOCKS OF MONTHS (exp05's SCHEME)
    month_code_arr, month_label_arr = pd.factorize(pd.to_datetime(valid_pdf["date"]).dt.to_period("M").to_numpy())
    month_count = len(month_label_arr)
    row_idx_list = [np.flatnonzero(month_code_arr == code) for code in range(month_count)]
    rng = np.random.default_rng(seed_in)
    block_count = int(np.ceil(month_count / block_month_count_in))
    boot_list = []
    for _ in range(iteration_count_in):
        start_arr = rng.integers(0, month_count, size=block_count)
        sample_month_arr = ((start_arr[:, None] + np.arange(block_month_count_in)[None, :]) % month_count).ravel()[:month_count]
        sample_idx_arr = np.concatenate([row_idx_list[code] for code in sample_month_arr])
        boot_list.append(spearmanr(level_arr[sample_idx_arr], target_arr[sample_idx_arr]).correlation - spearmanr(realized_arr[sample_idx_arr], target_arr[sample_idx_arr]).correlation)
    ci_low, ci_high = np.percentile(boot_list, [2.5, 97.5])
    # RETURN THE CHECK
    return {"row_count": int(len(valid_pdf)), "month_count": int(month_count), "spearman_vix": spearman_vix, "spearman_realized": spearman_realized,
            "d": spearman_vix - spearman_realized, "d_ci_low": float(ci_low), "d_ci_high": float(ci_high), "last_forward_session_date": last_forward_session_date,
            "passed": bool(ci_low > 0)}

# FUNCTION: GET THE MEAN FORWARD RETURN OF A SET OF ROWS WITH A MONTH-BLOCK INTERVAL
def get_mean_return_interval_dict(window_pdf_in):
    """
    Mean fwd_net_return_20d of the rows with a 1-month block bootstrap interval (so.core.signal_bins, one bin).

    Args:
        window_pdf_in (pd.DataFrame): Rows (date, y_fwd_positive, fwd_net_return_20d)

    Returns:
        dict: row_count, month_count, mean_fwd_return, ci_low, ci_high
    """
    # IF THERE ARE NO ROWS
    if window_pdf_in.empty:
        return {"row_count": 0, "month_count": 0, "mean_fwd_return": np.nan, "ci_low": np.nan, "ci_high": np.nan}
    # CALCULATE THE STATISTICS OF ONE BIN
    stat_pdf = get_bootstrap_bin_stat_pdf(pd.Series(["all"] * len(window_pdf_in)), get_month_block_id_arr(window_pdf_in["date"]),
                                          window_pdf_in["y_fwd_positive"].to_numpy(dtype=float), window_pdf_in["fwd_net_return_20d"].to_numpy(dtype=float),
                                          np.zeros(len(window_pdf_in)))
    # RETURN THE MEAN AND ITS INTERVAL
    return {"row_count": int(len(window_pdf_in)), "month_count": int(pd.to_datetime(window_pdf_in["date"]).dt.to_period("M").nunique()),
            "mean_fwd_return": float(stat_pdf["mean_net_return"].iloc[0]), "ci_low": float(stat_pdf["net_return_ci_low"].iloc[0]),
            "ci_high": float(stat_pdf["net_return_ci_high"].iloc[0])}

# FUNCTION: RUN G4 (PLAUSIBILITY OF UNLEVERED VOLATILITY SCALING)
def run_g4_dict(analysis_pdf_in, level_col_str_in="vix_level_prev", top_quantile_in=exp_config.G4_TOP_QUANTILE):
    """
    Mean forward 20-session net return of the rows whose VIX level is at or above the training quantile, on training
    and on the pooled validation. PASS only if both means are below 0 (cash earns 0% in the simulator).

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        level_col_str_in (str): VIX level column
        top_quantile_in (float): Training quantile that starts the top group

    Returns:
        dict: threshold, train_* and valid_* statistics (row_count, month_count, mean_fwd_return, ci_low, ci_high), passed
    """
    # LEARN THE THRESHOLD ON TRAINING
    train_pdf = analysis_pdf_in[analysis_pdf_in["is_train"]]
    valid_pdf = analysis_pdf_in[analysis_pdf_in["valid_fold_id"] >= 0]
    threshold = float(np.quantile(train_pdf[level_col_str_in].to_numpy(dtype=float), top_quantile_in))
    # CALCULATE THE MEANS OF THE TOP ROWS
    train_dict = get_mean_return_interval_dict(train_pdf[train_pdf[level_col_str_in] >= threshold])
    valid_dict = get_mean_return_interval_dict(valid_pdf[valid_pdf[level_col_str_in] >= threshold])
    # RETURN THE CHECK
    return {"threshold": threshold, **{f"train_{k}": v for k, v in train_dict.items()}, **{f"valid_{k}": v for k, v in valid_dict.items()},
            "passed": bool(train_dict["mean_fwd_return"] < 0 and valid_dict["mean_fwd_return"] < 0)}

# FUNCTION: GET THE GATE DECISIONS
def get_gate_decision_dict(g1_passed_in, g2_passed_in, g3_passed_in, g4_passed_in):
    """
    Applies the pre-registered gate rules (primary results only): exp09 if G1 or G2; exp11 if G2; exp10 if G3 and G4.

    Args:
        g1_passed_in, g2_passed_in, g3_passed_in, g4_passed_in (bool): Primary gate results

    Returns:
        dict: exp09_runs, exp10_runs, exp11_runs, vix_line_stops
    """
    # APPLY THE RULES
    decision_dict = {"exp09_runs": bool(g1_passed_in or g2_passed_in), "exp10_runs": bool(g3_passed_in and g4_passed_in), "exp11_runs": bool(g2_passed_in)}
    decision_dict["vix_line_stops"] = not any(decision_dict.values())
    # RETURN THE DECISIONS
    return decision_dict

# FUNCTION: GET THE FORWARD RETURN BY VIX LEVEL QUINTILE AND BY TERM-STRUCTURE STATE (DESCRIPTIVE)
def get_descriptive_return_pdf(analysis_pdf_in, level_col_str_in="vix_level_prev", term_col_str_in="vix_term_prev",
                               bin_count_in=exp_config.DESCRIPTIVE_BIN_COUNT, threshold_in=exp_config.TERM_STRESS_THRESHOLD):
    """
    Mean forward 20-session net return and positive share per VIX level quintile (training edges) and per term-structure
    state (term >= threshold vs < threshold), on training and on validation. Descriptive only.

    Args:
        analysis_pdf_in (pd.DataFrame): Analysis rows
        level_col_str_in (str): VIX level column
        term_col_str_in (str): Term-structure column
        bin_count_in (int): Quantile bins
        threshold_in (float): Inverted term-structure threshold

    Returns:
        pd.DataFrame: grouping, group, window, row_count, month_count, mean_fwd_return, ci_low, ci_high, positive_share
    """
    # LEARN THE LEVEL EDGES ON TRAINING
    train_bool_arr, valid_bool_arr = analysis_pdf_in["is_train"].to_numpy(), (analysis_pdf_in["valid_fold_id"] >= 0).to_numpy()
    edge_arr = get_quantile_bin_edge_arr(analysis_pdf_in.loc[train_bool_arr, level_col_str_in], bin_count_in)
    level_label_series = get_bin_label_series(analysis_pdf_in[level_col_str_in], False, edge_arr).reset_index(drop=True)
    term_label_series = pd.Series(np.where(analysis_pdf_in[term_col_str_in].to_numpy() >= threshold_in, f"term >= {threshold_in}", f"term < {threshold_in}"))
    # LIST TO HOLD THE ROWS
    row_list = []
    # ITERATE OVER THE GROUPINGS, THE WINDOWS AND THE GROUPS
    for grouping_str, label_series in [("vix_level_quintile", level_label_series), ("term_structure", term_label_series)]:
        for window_str, window_bool_arr in [("train", train_bool_arr), ("valid", valid_bool_arr)]:
            for group_str in sorted(label_series.unique()):
                group_pdf = analysis_pdf_in[window_bool_arr & (label_series == group_str).to_numpy()]
                row_list.append({"grouping": grouping_str, "group": group_str, "window": window_str, **get_mean_return_interval_dict(group_pdf),
                                 "positive_share": float(group_pdf["y_fwd_positive"].mean()) if len(group_pdf) else np.nan})
    # RETURN THE TABLE
    return pd.DataFrame(row_list)

# FUNCTION: GET THE INVERTED TERM-STRUCTURE EPISODES (DESCRIPTIVE)
def get_term_episode_pdf(daily_pdf_in, term_series_in, start_date_in, end_date_in, threshold_in=exp_config.TERM_STRESS_THRESHOLD,
                         after_sessions_in=exp_config.EPISODE_AFTER_SESSIONS):
    """
    Lists the runs of consecutive sessions with term >= threshold between two dates: start, end, length, SPY return from
    the fill of the first session to the close of the last, and over the next after_sessions_in sessions (close to close;
    NaN when beyond the data).

    Args:
        daily_pdf_in (pd.DataFrame): Daily SPY table of the cut data (date, fill_open, session_close)
        term_series_in (pd.Series): Term-structure value per row of daily_pdf_in (same order)
        start_date_in, end_date_in (datetime.date): Window of the episode starts
        threshold_in (float): Threshold
        after_sessions_in (int): Sessions after the episode

    Returns:
        pd.DataFrame: One row per episode
    """
    # FLAG THE STRESS SESSIONS
    date_arr = np.array(daily_pdf_in["date"].tolist())
    stress_bool_arr = (term_series_in.to_numpy(dtype=float) >= threshold_in) & (date_arr >= start_date_in) & (date_arr <= end_date_in)
    fill_arr, close_arr = daily_pdf_in["fill_open"].to_numpy(dtype=float), daily_pdf_in["session_close"].to_numpy(dtype=float)
    # FIND THE RUNS
    edge_arr = np.diff(np.concatenate([[0], stress_bool_arr.astype(int), [0]]))
    start_idx_arr, end_idx_arr = np.flatnonzero(edge_arr == 1), np.flatnonzero(edge_arr == -1) - 1
    # BUILD THE EPISODES
    row_list = []
    for start_idx, end_idx in zip(start_idx_arr, end_idx_arr):
        after_idx = end_idx + after_sessions_in
        row_list.append({"start_date": date_arr[start_idx], "end_date": date_arr[end_idx], "session_count": int(end_idx - start_idx + 1),
                         "spy_return_episode": close_arr[end_idx] / fill_arr[start_idx] - 1,
                         "spy_return_next_20": close_arr[after_idx] / close_arr[end_idx] - 1 if after_idx < len(close_arr) else np.nan,
                         "next_20_end_date": date_arr[after_idx] if after_idx < len(close_arr) else None})
    # RETURN THE EPISODES
    return pd.DataFrame(row_list)
