import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp12_vix_fear_reentry import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE AND THE REPLAY PERIODS
from so.core.schedule import get_walk_forward_fold_pdf
from so.core.continuous_replay import get_replay_period_pdf
# IMPORT THE CHAINED DAILY RETURNS
from so.core.evaluation import get_chained_daily_return_pdf
# IMPORT THE EXIT RULES OF exp04 AND exp07 (REUSED, NOT RE-TUNED)
from experiments.exp04_trend_exit.rules import get_trend_exit_signal_arr, get_trend_reentry_signal_arr
from experiments.exp07_warning_lights_exit.rules import get_light_pdf

"""
Rules: exp12_vix_fear_reentry (PROTOCOL.md §4; exp09's rules of 2026-10-09, _prev timing only)

State machine (so.core.reentry_simulation, no stop, continuous replay, no forced buy-back). Every value is known at the
15:58 decision of its session (the VIX _prev features use the daily close of the previous session).

Exits (fixed, each with its original re-entry rule as the fallback):
    E1  exit when the decision close is below the 200-session average; original re-entry when above (exp04, x = 0, n = 1)
    E2  exit when at least 4 of exp07's 5 lights are on; original re-entry when fewer than 3 are on (exp07, k = 4)

Modifications (parameters fixed):
    M1  fear-fade re-entry: buy back at the first decision after the exit where vix_level_prev <= 0.85 x the maximum of
        vix_level_prev over the decisions from the exit decision to now, or when the original re-entry fires, whichever
        comes first. A NaN vix_level_prev makes the condition false and does not enter the maximum.
    M2  term-structure re-entry: buy back at the first decision where vix_term_prev < 1, provided vix_term_prev was >= 1
        at least once from the exit decision on; or when the original re-entry fires, whichever comes first. NaN =
        condition false (a NaN is neither < 1 nor >= 1).
    M3  no exit into fear: the exit signal is ignored at decisions where vix_term_prev >= 1 or vix_pct250_prev >= 0.9
        (NaN = not suppressed); original re-entry.
    M1 and M2: after a VIX-triggered re-entry, a new exit requires the exit signal to switch off and on again (a fresh
    signal): the re-entry rule sets episode_dict["require_fresh_exit"] = True and the shared simulator ignores the exit
    signal until it has been off once. Never after the original rule's re-entry. When the original rule and the VIX
    trigger fire on the same decision, the re-entry is labelled "original" (the exit signal is then off for both exits:
    above the average for E1, fewer than 3 lights for E2, so the label changes no trade).

The exit decision of an episode is the session before its first cash decision (the sale fills at the last bar of the
exit decision's session). The maxima and the "was >= 1" condition are read from the feature arrays over the sessions
exit decision .. now, so they do not depend on which candidate governed the earlier sessions of the episode.

The identity of exp02-exp07 applies: an episode that sells at S and buys back at R ends with S / R times the shares;
final equity / buy-and-hold is about the product of S / R over the episodes (costs and cash residues aside).
"""

"""
Schedule And Candidates
"""

# FUNCTION: GET THE SCHEDULE AND THE REPLAY PERIODS
def get_schedule_tuple(session_date_list_in, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS, max_fold_count_in=None):
    """
    Builds the exp02-exp07 schedule (20-session embargo, folds that fit a 10-year window) and its replay periods, exactly
    as exp04 step 02.

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        train_years_in (int): Fixed window a fold must fit (years; smaller in tests)
        max_fold_count_in (int | None): Keep only the most recent folds

    Returns:
        tuple: (fold_pdf, period_pdf)
    """
    # BUILD THE SCHEDULE
    fold_pdf = get_walk_forward_fold_pdf(session_date_list_in, exp_config.EMBARGO_TRADING_DAYS, [train_years_in], max_fold_count_in=max_fold_count_in)
    # RETURN THE SCHEDULE AND THE PERIODS
    return fold_pdf, get_replay_period_pdf(fold_pdf, session_date_list_in)

# FUNCTION: CHECK THE SCHEDULE OF THE REAL DATA
def check_schedule_dict(fold_pdf_in, period_pdf_in):
    """
    Asserts the 44 periods of exp04 step 02 (first valid_start 2015-04-17, last valid_end 2026-04-15, latest test_start
    2026-05-14, never read).

    Args:
        fold_pdf_in (pd.DataFrame): Fold schedule (built from the full session calendar)
        period_pdf_in (pd.DataFrame): Replay periods

    Returns:
        dict: period_count, first_valid_start, last_valid_end, latest_test_start
    """
    # COLLECT THE VALUES
    schedule_dict = {"period_count": int(len(period_pdf_in)), "first_valid_start": str(pd.Timestamp(fold_pdf_in["valid_start"].iloc[0]).date()),
                     "last_valid_end": str(pd.Timestamp(fold_pdf_in["valid_end"].iloc[-1]).date()),
                     "latest_test_start": str(pd.Timestamp(fold_pdf_in["test_start"].iloc[-1]).date())}
    # ASSERT THE EXPECTED SCHEDULE
    assert schedule_dict["period_count"] == exp_config.EXPECTED_PERIOD_COUNT == len(fold_pdf_in), f"❌ Schedule: {schedule_dict}"
    assert schedule_dict["first_valid_start"] == exp_config.EXPECTED_FIRST_VALID_START_STR, f"❌ Schedule: {schedule_dict}"
    assert schedule_dict["last_valid_end"] == exp_config.EXPECTED_LAST_VALID_END_STR, f"❌ Schedule: {schedule_dict}"
    assert schedule_dict["latest_test_start"] == exp_config.EXPECTED_LATEST_TEST_START_STR, f"❌ Schedule: {schedule_dict}"
    # RETURN THE VALUES
    return schedule_dict

# FUNCTION: GET THE 6 CANDIDATES
def get_rule_candidate_list(exit_rule_list_in=exp_config.EXIT_RULE_STR_LIST, modification_list_in=exp_config.MODIFICATION_STR_LIST,
                            tie_order_dict_in=exp_config.TIE_ORDER_DICT):
    """
    Lists the 6 candidates in a fixed order (E1M1, E1M2, E1M3, E2M1, E2M2, E2M3) with their tie-break rank.

    Args:
        exit_rule_list_in (list[str]): Exits
        modification_list_in (list[str]): Modifications
        tie_order_dict_in (dict): Candidate name -> tie-break rank (0 first)

    Returns:
        list[dict]: exit_rule, modification, candidate_name, tie_order
    """
    # RETURN THE GRID
    return [{"exit_rule": exit_str, "modification": modification_str, "candidate_name": f"{exit_str}{modification_str}",
             "tie_order": int(tie_order_dict_in[f"{exit_str}{modification_str}"])} for exit_str in exit_rule_list_in for modification_str in modification_list_in]

# FUNCTION: GET THE 2 UNMODIFIED EXITS (BASELINE)
def get_unmodified_candidate_list():
    """
    Lists the unmodified exits E1 and E2 (each with its original re-entry), the baseline of the information test.

    Returns:
        list[dict]: exit_rule, modification ("none"), candidate_name, tie_order
    """
    # RETURN THE BASELINE CANDIDATES
    return get_rule_candidate_list(exp_config.EXIT_RULE_STR_LIST, [exp_config.UNMODIFIED_STR], exp_config.UNMODIFIED_TIE_ORDER_DICT)

"""
Signals
"""

# FUNCTION: GET THE BASE EXIT AND RE-ENTRY SIGNALS OF E1 AND E2
def get_base_signal_dict(daily_pdf_in):
    """
    E1 from exp04's rules.py (x = 0, n = 1) and E2 from exp07's rules.py (k = 4).

    Args:
        daily_pdf_in (pd.DataFrame): Output of so.features.daily_features.get_daily_feature_pdf (indexed by session position)

    Returns:
        dict: "E1" / "E2" -> {"exit_arr", "reentry_arr"} (bool per session position)
    """
    # COUNT THE LIGHTS OF exp07 (A MISSING FEATURE IS AN OFF LIGHT)
    light_count_arr = get_light_pdf(daily_pdf_in, exp_config.E2_LIGHT_DICT)["light_count"].to_numpy()
    # RETURN THE SIGNALS
    return {"E1": {"exit_arr": get_trend_exit_signal_arr(daily_pdf_in, exp_config.E1_BUFFER, exp_config.E1_CONFIRMATION, exp_config.E1_MA_DIST_COL_STR),
                   "reentry_arr": get_trend_reentry_signal_arr(daily_pdf_in, exp_config.E1_BUFFER, exp_config.E1_MA_DIST_COL_STR)},
            "E2": {"exit_arr": light_count_arr >= exp_config.E2_LIGHT_K, "reentry_arr": light_count_arr < exp_config.E2_LIGHT_K - 1}}

# FUNCTION: GET THE M3 SUPPRESSION OF EVERY DECISION
def get_m3_suppress_arr(vix_feature_pdf_in, term_threshold_in=exp_config.M3_TERM_THRESHOLD, pct_threshold_in=exp_config.M3_PCT250_THRESHOLD):
    """
    True where the exit is ignored: vix_term_prev >= 1 or vix_pct250_prev >= 0.9 (NaN = not suppressed).

    Args:
        vix_feature_pdf_in (pd.DataFrame): VIX features aligned with the daily table (vix_term_prev, vix_pct250_prev)
        term_threshold_in (float): Term-structure threshold
        pct_threshold_in (float): Percentile threshold

    Returns:
        np.ndarray: Bool per session position
    """
    # COLLECT THE FEATURES
    term_arr = vix_feature_pdf_in[exp_config.VIX_TERM_COL_STR].to_numpy(dtype=float)
    pct_arr = vix_feature_pdf_in[exp_config.VIX_PCT250_COL_STR].to_numpy(dtype=float)
    # RETURN THE SUPPRESSION (A NaN COMPARISON IS FALSE)
    with np.errstate(invalid="ignore"):
        return (term_arr >= term_threshold_in) | (pct_arr >= pct_threshold_in)

# FUNCTION: CHECK THE M1 TRIGGER AT A DECISION
def get_m1_trigger_bool(level_arr_in, exit_session_idx_in, session_idx_in, fade_ratio_in=exp_config.M1_FADE_RATIO):
    """
    True if level(now) <= fade_ratio x max(level over exit decision .. now); NaN values do not enter the maximum and a
    NaN level now is False.

    Args:
        level_arr_in (np.ndarray): vix_level_prev per session position
        exit_session_idx_in (int): Session position of the exit decision
        session_idx_in (int): Session position of the current decision
        fade_ratio_in (float): Fade ratio (0.85)

    Returns:
        bool: Trigger
    """
    # COLLECT THE CURRENT LEVEL AND THE LEVELS SINCE THE EXIT DECISION
    level_now = level_arr_in[session_idx_in]
    window_arr = level_arr_in[exit_session_idx_in:session_idx_in + 1]
    window_arr = window_arr[np.isfinite(window_arr)]
    # IF THE LEVEL IS MISSING OR NO MAXIMUM EXISTS
    if not np.isfinite(level_now) or len(window_arr) == 0:
        return False
    # RETURN THE TRIGGER
    return bool(level_now <= fade_ratio_in * window_arr.max())

# FUNCTION: CHECK THE M2 TRIGGER AT A DECISION
def get_m2_trigger_bool(term_arr_in, exit_session_idx_in, session_idx_in, term_threshold_in=exp_config.M2_TERM_THRESHOLD):
    """
    True if term(now) < 1 and term >= 1 on at least one decision from the exit decision on (NaN is neither).

    Args:
        term_arr_in (np.ndarray): vix_term_prev per session position
        exit_session_idx_in (int): Session position of the exit decision
        session_idx_in (int): Session position of the current decision
        term_threshold_in (float): Threshold (1.0)

    Returns:
        bool: Trigger
    """
    # COLLECT THE CURRENT VALUE AND THE VALUES SINCE THE EXIT DECISION
    term_now = term_arr_in[session_idx_in]
    window_arr = term_arr_in[exit_session_idx_in:session_idx_in + 1]
    # RETURN THE TRIGGER (A NaN COMPARISON IS FALSE)
    with np.errstate(invalid="ignore"):
        return bool(term_now < term_threshold_in and (window_arr >= term_threshold_in).any())

# FUNCTION: GET THE RULE BUILDER OF THE EXPERIMENT
def get_rule_builder_func(daily_pdf_in, vix_feature_pdf_in):
    """
    Returns f(candidate_dict) -> (exit_signal_arr, reentry_func, reentry_reason_str) for so.core.replay_walk_forward.
    The re-entry rule records why it bought back in episode_dict["reentry_trigger"] ("M1", "M2" or "original").

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (indexed by session position)
        vix_feature_pdf_in (pd.DataFrame): VIX _prev features with the same session positions (session_idx column)

    Returns:
        function: Rule builder
    """
    # CHECK THE ALIGNMENT OF THE TWO TABLES
    assert len(daily_pdf_in) == len(vix_feature_pdf_in) and (vix_feature_pdf_in["session_idx"].to_numpy() == daily_pdf_in["session_idx"].to_numpy()).all(), "❌ VIX features not aligned"
    # COLLECT THE SIGNALS AND THE FEATURES ONCE
    base_signal_dict = get_base_signal_dict(daily_pdf_in)
    level_arr = vix_feature_pdf_in[exp_config.VIX_LEVEL_COL_STR].to_numpy(dtype=float)
    term_arr = vix_feature_pdf_in[exp_config.VIX_TERM_COL_STR].to_numpy(dtype=float)
    suppress_arr = get_m3_suppress_arr(vix_feature_pdf_in)
    # FUNCTION: BUILD ONE CANDIDATE
    def rule_builder_func(candidate_dict_in):
        exit_str, modification_str = candidate_dict_in["exit_rule"], candidate_dict_in["modification"]
        exit_arr, original_arr = base_signal_dict[exit_str]["exit_arr"], base_signal_dict[exit_str]["reentry_arr"]
        # M3: THE EXIT IS IGNORED UNDER FEAR; ORIGINAL RE-ENTRY
        if modification_str == "M3":
            exit_arr = exit_arr & ~suppress_arr
        # FUNCTION: THE RE-ENTRY RULE
        def reentry_func(session_idx, cash_session_count, episode_dict):
            # THE ORIGINAL RULE FIRST (LABELLED "original" WHEN BOTH FIRE)
            if bool(original_arr[session_idx]):
                episode_dict["reentry_trigger"] = "original"
                return True
            # THE VIX TRIGGER OF M1 OR M2 (THE EXIT DECISION IS THE SESSION BEFORE THE FIRST CASH DECISION)
            exit_session_idx = int(episode_dict["first_cash_session_idx"]) - 1
            if (modification_str == "M1" and get_m1_trigger_bool(level_arr, exit_session_idx, session_idx)) or \
               (modification_str == "M2" and get_m2_trigger_bool(term_arr, exit_session_idx, session_idx)):
                episode_dict["reentry_trigger"] = modification_str
                episode_dict["require_fresh_exit"] = True
                return True
            # OTHERWISE STAY IN CASH
            return False
        # RETURN THE RULE
        return exit_arr, reentry_func, "rule"
    # RETURN THE BUILDER
    return rule_builder_func

"""
Reports
"""

# FUNCTION: GET THE RE-ENTRY REASON OF EVERY EPISODE
def get_reentry_trigger_list(simulation_dict_in):
    """
    The re-entry reason of every episode, in the order of the episode table (and of the scorecard): "M1", "M2",
    "original rule", "end of data", or the simulator's label when no rule of this experiment bought back (e.g. "random").

    Args:
        simulation_dict_in (dict): Output of simulate_stop_reentry_dict

    Returns:
        list[str]: One reason per episode
    """
    # COLLECT THE EPISODES
    episode_pdf = simulation_dict_in["episode_pdf"]
    # IF THERE IS NO EPISODE
    if episode_pdf is None or episode_pdf.empty:
        return []
    # COLLECT THE TRIGGERS (ABSENT WHEN NO RULE OF THIS EXPERIMENT BOUGHT BACK)
    trigger_list = episode_pdf["reentry_trigger"].tolist() if "reentry_trigger" in episode_pdf.columns else [np.nan] * len(episode_pdf)
    # RETURN THE REASONS
    return ["end of data" if reason_str == "window_end" else ("original rule" if trigger == "original" else (trigger if isinstance(trigger, str) else str(reason_str)))
            for reason_str, trigger in zip(episode_pdf["reentry_reason"].tolist(), trigger_list)]

# FUNCTION: ADD THE RE-ENTRY REASON AND THE VIX TO A SCORECARD
def get_vix_scorecard_pdf(scorecard_pdf_in, simulation_dict_in, vix_feature_pdf_in):
    """
    Adds to so.core.continuous_replay.get_episode_scorecard_pdf: the re-entry reason and vix_level_prev at the exit
    decision and at the buy-back decision (both are the sessions of the fills).

    Args:
        scorecard_pdf_in (pd.DataFrame): Episode scorecard (same episode order as the simulation)
        simulation_dict_in (dict): Output of simulate_stop_reentry_dict
        vix_feature_pdf_in (pd.DataFrame): VIX features (date, vix_level_prev)

    Returns:
        pd.DataFrame: The scorecard with reentry_trigger, vix_at_exit, vix_at_reentry
    """
    # IF THE SCORECARD IS EMPTY
    if scorecard_pdf_in.empty:
        return scorecard_pdf_in.copy()
    # MAP THE DATES TO THE VIX LEVEL
    level_dict = dict(zip(vix_feature_pdf_in["date"].tolist(), vix_feature_pdf_in[exp_config.VIX_LEVEL_COL_STR].to_numpy(dtype=float)))
    # ADD THE COLUMNS
    scorecard_pdf = scorecard_pdf_in.copy()
    scorecard_pdf["reentry_trigger"] = get_reentry_trigger_list(simulation_dict_in)
    scorecard_pdf["vix_at_exit"] = [level_dict.get(date, np.nan) for date in scorecard_pdf["exit_date"]]
    scorecard_pdf["vix_at_reentry"] = [level_dict.get(date, np.nan) for date in scorecard_pdf["reentry_date"]]
    # RETURN THE SCORECARD
    return scorecard_pdf

# FUNCTION: GET THE CONCENTRATION REPORTS (a) AND (c)
def get_concentration_dict(scorecard_pdf_in, strategy_equity_pdf_in, buy_hold_equity_pdf_in,
                           window_start_str_in=exp_config.CONCENTRATION_WINDOW_START_STR, window_end_str_in=exp_config.CONCENTRATION_WINDOW_END_STR):
    """
    (a) final equity / buy-and-hold and the product of S / R; both again without the episode with the largest log(S/R)
        and without the two largest (the equity ratio divided by their S / R: an approximation that ignores costs).
    (c) the share of the total log excess log(final equity / buy-and-hold) contributed by the episodes that overlap the
        window (sum of their log(S/R) / total log excess).

    Args:
        scorecard_pdf_in (pd.DataFrame): Episode scorecard (log_share_gain, s_over_r, exit_date, reentry_date)
        strategy_equity_pdf_in, buy_hold_equity_pdf_in (pd.DataFrame): Daily equity of the path and of buy-and-hold
        window_start_str_in, window_end_str_in (str): Window of report (c)

    Returns:
        dict: equity_ratio, product_s_over_r, and the _without_top1 / _without_top2 versions with their beats flags;
              window_episode_count, window_log_share_gain, total_log_excess, window_share_of_log_excess
    """
    # CALCULATE THE EQUITY RATIO AND THE TOTAL LOG EXCESS
    equity_ratio = float(strategy_equity_pdf_in["equity"].iloc[-1] / buy_hold_equity_pdf_in["equity"].iloc[-1])
    total_log_excess = float(np.log(equity_ratio))
    # COLLECT THE EPISODE LOG GAINS (LARGEST FIRST)
    log_gain_arr = np.sort(scorecard_pdf_in["log_share_gain"].to_numpy(dtype=float))[::-1] if not scorecard_pdf_in.empty else np.array([])
    result_dict = {"episode_count": int(len(log_gain_arr)), "equity_ratio": equity_ratio, "product_s_over_r": float(np.exp(log_gain_arr.sum())),
                   "total_log_excess": total_log_excess}
    # REMOVE THE LARGEST ONE AND TWO EPISODES
    for drop_count in [1, 2]:
        removed_log = float(log_gain_arr[:drop_count].sum()) if len(log_gain_arr) >= drop_count else np.nan
        result_dict[f"product_s_over_r_without_top{drop_count}"] = float(np.exp(log_gain_arr[drop_count:].sum())) if np.isfinite(removed_log) else np.nan
        result_dict[f"equity_ratio_without_top{drop_count}"] = float(equity_ratio / np.exp(removed_log)) if np.isfinite(removed_log) else np.nan
        result_dict[f"beats_buy_hold_without_top{drop_count}"] = bool(result_dict[f"equity_ratio_without_top{drop_count}"] > 1) if np.isfinite(removed_log) else None
    # COLLECT THE EPISODES OVERLAPPING THE WINDOW
    window_start, window_end = pd.Timestamp(window_start_str_in).date(), pd.Timestamp(window_end_str_in).date()
    in_window_arr = np.array([(exit_date <= window_end) and (reentry_date >= window_start) for exit_date, reentry_date in
                              zip(scorecard_pdf_in.get("exit_date", []), scorecard_pdf_in.get("reentry_date", []))], dtype=bool)
    window_log = float(scorecard_pdf_in.loc[in_window_arr, "log_share_gain"].sum()) if len(in_window_arr) else 0.0
    result_dict.update({"window_episode_count": int(in_window_arr.sum()), "window_log_share_gain": window_log,
                        "window_share_of_log_excess": float(window_log / total_log_excess) if total_log_excess != 0 else np.nan})
    # RETURN THE REPORTS
    return result_dict

# FUNCTION: GET THE LOG EXCESS PER CALENDAR YEAR (REPORT (b))
def get_yearly_log_excess_pdf(strategy_equity_pdf_in, buy_hold_equity_pdf_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Log excess over buy-and-hold per calendar year: sum over the year's sessions of log(1 + r_path) - log(1 + r_bh).

    Args:
        strategy_equity_pdf_in, buy_hold_equity_pdf_in (pd.DataFrame): Daily equity over the same sessions
        initial_capital_in (float): Starting equity of both paths

    Returns:
        pd.DataFrame: year, session_count, strategy_log_return, buy_hold_log_return, log_excess, in_market_pct
    """
    # CALCULATE THE DAILY RETURNS AND MERGE THEM
    merged_pdf = get_chained_daily_return_pdf([strategy_equity_pdf_in], initial_capital_in).merge(
        get_chained_daily_return_pdf([buy_hold_equity_pdf_in], initial_capital_in), on="date", suffixes=("_strategy", "_buy_hold"))
    merged_pdf["in_position"] = merged_pdf["date"].map(dict(zip(strategy_equity_pdf_in["date"], strategy_equity_pdf_in["in_position"].astype(bool))))
    merged_pdf["year"] = pd.to_datetime(merged_pdf["date"]).dt.year
    # SUM THE LOG RETURNS PER YEAR
    year_pdf = merged_pdf.groupby("year").agg(session_count=("date", "size"),
                                              strategy_log_return=("daily_return_strategy", lambda s: float(np.log1p(s).sum())),
                                              buy_hold_log_return=("daily_return_buy_hold", lambda s: float(np.log1p(s).sum())),
                                              in_market_pct=("in_position", "mean")).reset_index()
    year_pdf["log_excess"] = year_pdf["strategy_log_return"] - year_pdf["buy_hold_log_return"]
    # RETURN THE TABLE
    return year_pdf[["year", "session_count", "strategy_log_return", "buy_hold_log_return", "log_excess", "in_market_pct"]]
