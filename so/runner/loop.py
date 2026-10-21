import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL)
from so import config
# IMPORT THE POINT-IN-TIME CONTEXT BUILDER AND THE DIRECT-READ FLAG
from so.core.point_in_time import (get_runner_context, get_declared_source_name_list, set_direct_read_blocked_bool,
                                   get_minute_bar_available_ts)
# IMPORT THE FIRST-ENTRY BAR AND THE WINDOW SESSION LIST
from so.core.backtest_simulation import get_session_first_entry_idx
from so.core.reentry_simulation import get_window_session_idx_arr
# IMPORT THE DECISION AND FILL INDEXES
from so.features.daily_features import get_session_decision_idx_dict
# IMPORT THE VIEW, THE BUFFERS AND THE PREFLIGHT
from so.runner.view import (get_empty_bar_buffer_dict, fill_bar_buffer_through_decision, get_source_feed_dict,
                            get_decision_view)
from so.runner.preflight import check_design_source
from so.runner.engine import FractionalWeightEngine, get_decision_dict

"""
Daily Streaming Loop (infrastructure step 4a)

Walks one decision moment at a time (end of the 15:58 bar; fill at the 15:59 open). Before each decide() it copies
new bars into empty-started buffers up to that bar, advances each declared source in clock order, and hands the
design a view that slices those buffers. The last session has no design call; the engine sells at the last close.

The engine sees bar prices from the runner's full arrays (trusted shared code). The design never does. The runner
does not load files and does not call so.core.holdout; the caller hands it bar arrays and a DataContext already
loaded. A missing DATA_SOURCE_LIST is ["SPY_1MIN"]. A callable is accepted as decide.

Minute mode (MODE_MINUTE_STR) is 4b: row-local signals, a shuffle check, barrier and trailing-stop engines. This
module only runs daily mode. Direct loader calls are blocked for the duration of the run. The design file is AST-
checked before the first call.
"""

# DAILY MODE IS 4A; MINUTE MODE IS 4B
MODE_DAILY_STR = "daily"
MODE_MINUTE_STR = "minute"


# FUNCTION: CALL design.decide, OR THE OBJECT ITSELF IF IT IS CALLABLE
def get_design_decision_dict(design_in, view_in):
    """
    An object with decide(view) is called that way. A callable is the decide function.

    Args:
        design_in (object | callable): Design
        view_in (DecisionView): View at this moment

    Returns:
        dict: Output of get_decision_dict
    """
    # PREFER AN EXPLICIT DECIDE METHOD
    if hasattr(design_in, "decide"):
        return get_decision_dict(design_in.decide(view_in))
    return get_decision_dict(design_in(view_in))


# FUNCTION: RUN THE DAILY LOOP
def run_daily_dict(design_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, engine_in=None,
                   initial_weight_in=1.0, dead_band_in=0.0, initial_capital_in=config.INITIAL_CAPITAL,
                   entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                   market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                   design_file_path_str_in=None):
    """
    Daily point-in-time replay. Weight 1 throughout with initial_weight 1 reproduces buy-and-hold.

    Args:
        design_in (object | callable): decide(view) -> weight or decision dict
        ohlcv_array_dict_in (dict): Full bar arrays (kept by the runner; not passed to the design)
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        data_context_in (DataContext | None): Loaded sources (None builds a runner context from the bars)
        engine_in (Engine | None): None uses FractionalWeightEngine
        initial_weight_in (float): Weight bought at the first 10:00 open
        dead_band_in (float): Passed to the default engine
        initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Default-engine costs
        design_file_path_str_in (str | None): Design file to AST-check (None uses the object's module)

    Returns:
        dict: trade_pdf, daily_equity_pdf, metric_dict, target_weight_arr, decision_session_list
    """
    # REFUSE A DESIGN FILE THAT CAN REACH AROUND THE VIEW
    check_design_source(design_in, design_file_path_str_in)
    # COLLECT THE WINDOW AND THE DECISION BARS
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    if len(window_session_idx_arr) == 0:
        return {"trade_pdf": pd.DataFrame(), "daily_equity_pdf": pd.DataFrame(),
                "metric_dict": {}, "target_weight_arr": np.array([], dtype=float), "decision_session_list": []}
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    decision_idx_arr, fill_idx_arr = idx_dict["decision_idx_arr"], idx_dict["fill_idx_arr"]
    end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
    open_arr, close_arr, timestamp_index = ohlcv_array_dict_in["open_arr"], ohlcv_array_dict_in["close_arr"], ohlcv_array_dict_in["timestamp_index"]
    # BUILD A CONTEXT FROM THE BARS WHEN THE CALLER DID NOT PASS ONE (THE VIEW NEVER HOLDS IT)
    data_context = data_context_in
    if data_context is None:
        data_context = get_runner_context(ohlcv_array_dict_in, declared_name_list_in=get_declared_source_name_list(design_in))
    bar_buffer_dict = get_empty_bar_buffer_dict(ohlcv_array_dict_in)
    feed_dict = get_source_feed_dict(design_in, ohlcv_array_dict_in, data_context)
    # THE DEFAULT ENGINE IS FRACTIONAL WEIGHT
    engine = engine_in if engine_in is not None else FractionalWeightEngine(dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    target_weight_list = []
    decision_session_list = []
    # BLOCK DIRECT LOADER CALLS FOR THE WHOLE RUN
    set_direct_read_blocked_bool(True)
    try:
        # BUY THE INITIAL WEIGHT AT THE FIRST 10:00 OPEN
        first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, int(window_session_idx_arr[0]))
        engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": timestamp_index[first_entry_idx],
                            "raw_price": float(open_arr[first_entry_idx])}, float(initial_weight_in))
        # ONE SESSION AT A TIME
        for session_pos, session_idx in enumerate(window_session_idx_arr):
            session_idx = int(session_idx)
            decision_idx, fill_idx, end_idx = int(decision_idx_arr[session_idx]), int(fill_idx_arr[session_idx]), int(end_idx_arr[session_idx])
            is_last_session = session_pos == len(window_session_idx_arr) - 1
            session_date = ohlcv_array_dict_in["session_date_list"][session_idx]
            if not is_last_session:
                # COPY NEW BARS UP TO THE DECISION BAR, THEN HAND THE DESIGN A SLICE OF THE BUFFER
                fill_bar_buffer_through_decision(bar_buffer_dict, ohlcv_array_dict_in, session_idx, decision_idx)
                decision_ts = get_minute_bar_available_ts(timestamp_index[decision_idx])
                for feed in feed_dict.values():
                    feed.advance_to_ts(decision_ts)
                view = get_decision_view(bar_buffer_dict, session_idx, decision_idx, feed_dict)
                decision_dict = get_design_decision_dict(design_in, view)
                for feed in feed_dict.values():
                    feed.mark_call_boundary()
                target_weight_list.append(float(decision_dict["target_weight"]))
                decision_session_list.append(session_date)
                engine.apply_decision({"bar_idx": fill_idx, "timestamp": timestamp_index[fill_idx],
                                       "raw_price": float(open_arr[fill_idx])}, decision_dict, float(close_arr[decision_idx]))
            else:
                # NO DESIGN CALL ON THE LAST SESSION
                target_weight_list.append(np.nan)
                decision_session_list.append(session_date)
                engine.close_window({"bar_idx": end_idx, "timestamp": timestamp_index[end_idx],
                                     "raw_price": float(close_arr[end_idx])})
            # MARK AFTER THE OPTIONAL FILL OR THE END SALE
            engine.close_session({"session_date": session_date, "close": float(close_arr[end_idx])})
    finally:
        # ALWAYS UNBLOCK LOADERS
        set_direct_read_blocked_bool(False)
    # ATTACH THE TARGETS THE DESIGN RETURNED
    result_dict = engine.get_result_dict()
    result_dict["target_weight_arr"] = np.asarray(target_weight_list, dtype=float)
    result_dict["decision_session_list"] = list(decision_session_list)
    return result_dict
