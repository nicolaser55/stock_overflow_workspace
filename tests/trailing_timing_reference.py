import numpy as np
# IMPORT THE WINDOW SESSIONS, THE FIRST ENTRY BAR AND THE DECISION BARS
from so.core.reentry_simulation import get_window_session_idx_arr
from so.core.backtest_simulation import get_session_first_entry_idx
from so.features.daily_features import get_session_decision_idx_dict
# IMPORT THE ENGINE AND THE LOOP HELPERS
from so.runner.engine import TrailingStopEngine, get_decision_dict
from so.runner.loop import get_bar_range_event_dict, get_fill_event_dict

"""
Test reference: TrailingStopEngine driven with the old simulator's session timing

so.core.reentry_simulation.simulate_stop_reentry_dict sets session s's k and volatility before its morning bars. The
runner applies a decision's parameters from its fill (docs/RUNNER_DESIGN.md). This driver uses the old timing so the
engine can be compared with the old simulator exactly. Tests only.
"""


# FUNCTION: TrailingStopEngine WITH THE OLD SIMULATOR'S SESSION TIMING
def run_trailing_session_timing_dict(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr_in, stop_k_in,
                                     reentry_func_in, reentry_reason_str_in="model", exit_signal_arr_in=None,
                                     max_cash_sessions_in=None):
    """
    Sets session s's k and volatility before its morning bars (the old simulator's rule), then asks the old-style
    re-entry rule from the engine snapshot. Same arguments as so.core.reentry_simulation.simulate_stop_reentry_dict.
    Used by the engine tests and by the port calibrations; a run never uses this timing.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Window
        volatility_arr_in (np.ndarray): Volatility per session position
        stop_k_in (float | np.ndarray | None): k (scalar or one per session position)
        reentry_func_in: f(session_idx, cash_session_count, episode_dict) -> bool
        reentry_reason_str_in (str): Label of the rule's re-entries
        exit_signal_arr_in (np.ndarray | None): Flatten flag per session position
        max_cash_sessions_in (int | None): Forced re-entry

    Returns:
        dict: Engine result (trade_pdf, episode_pdf, daily_equity_pdf, metric_dict)
    """
    # THE SAME WINDOW AS THE OLD SIMULATOR
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    engine = TrailingStopEngine(max_cash_sessions_in)
    engine.set_session_bounds(ohlcv_array_dict_in["session_end_idx_arr"], len(ohlcv_array_dict_in["close_arr"]))
    first_session_idx = int(window_session_idx_arr[0])
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, first_session_idx)
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": timestamp_index[first_entry_idx],
                        "raw_price": float(ohlcv_array_dict_in["open_arr"][first_entry_idx]),
                        "close": float(ohlcv_array_dict_in["close_arr"][first_entry_idx]),
                        "session_idx": first_session_idx,
                        "session_date": ohlcv_array_dict_in["session_date_list"][first_session_idx]}, 1.0)
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    # ONE SESSION AT A TIME
    for session_pos, session_idx in enumerate(window_session_idx_arr):
        session_idx = int(session_idx)
        start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][session_idx])
        decision_idx = int(idx_dict["decision_idx_arr"][session_idx])
        fill_idx = int(idx_dict["fill_idx_arr"][session_idx])
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx])
        session_date = ohlcv_array_dict_in["session_date_list"][session_idx]
        is_last_session = session_pos == len(window_session_idx_arr) - 1
        session_k = stop_k_in if stop_k_in is None or np.ndim(stop_k_in) == 0 else stop_k_in[session_idx]
        # THE OLD RULE: THIS SESSION'S PARAMETERS ALSO COVER ITS MORNING
        engine.set_stop_params(session_k, volatility_arr_in[session_idx])
        morning_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, start_idx, decision_idx, session_date)
        if morning_event_dict is not None:
            engine.process_bars(morning_event_dict)
        flatten_bool = False if exit_signal_arr_in is None else bool(exit_signal_arr_in[session_idx])
        target_weight, exit_block_sessions, require_fresh_exit = 0.0, 0, False
        state_dict = engine.get_state_dict()
        if (not state_dict["in_position"]) and engine.episode_dict is not None and reentry_func_in is not None:
            if bool(reentry_func_in(int(session_idx), int(state_dict["cash_session_count"]), engine.episode_dict)):
                target_weight = 1.0
                exit_block_sessions = int(engine.episode_dict.get("exit_block_sessions", 0))
                require_fresh_exit = bool(engine.episode_dict.get("require_fresh_exit", False))
        decision_dict = get_decision_dict({"target_weight": target_weight, "flatten_bool": flatten_bool,
                                           "trail_multiple": session_k, "volatility": volatility_arr_in[session_idx],
                                           "exit_block_sessions": exit_block_sessions,
                                           "require_fresh_exit": require_fresh_exit,
                                           "reentry_reason": reentry_reason_str_in})
        if not is_last_session:
            engine.apply_decision(get_fill_event_dict(ohlcv_array_dict_in, fill_idx, decision_idx, session_idx,
                                                      session_date, end_idx),
                                  decision_dict, float(ohlcv_array_dict_in["close_arr"][decision_idx]))
        afternoon_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, decision_idx + 1, end_idx, session_date)
        if afternoon_event_dict is not None:
            engine.process_bars(afternoon_event_dict)
        if is_last_session:
            engine.close_window({"bar_idx": end_idx, "timestamp": timestamp_index[end_idx],
                                 "raw_price": float(ohlcv_array_dict_in["close_arr"][end_idx]),
                                 "close": float(ohlcv_array_dict_in["close_arr"][end_idx]),
                                 "session_idx": session_idx, "session_date": session_date})
        engine.close_session({"session_date": session_date, "close": float(ohlcv_array_dict_in["close_arr"][end_idx])})
    return engine.get_result_dict()
