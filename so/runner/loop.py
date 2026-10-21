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
Daily Streaming Loop (infrastructure step 4a, stream pause in 4b-1a)

Walks one decision moment at a time (end of the 15:58 bar; fill at the 15:59 open). Before each decide() it copies
new bars into empty-started buffers up to that bar, advances each declared source in clock order, and hands the
design a view that slices those buffers. The last session has no design call; the engine sells at the last close.

The engine sees bar prices from the runner's full arrays (trusted shared code). The design never does. The runner
does not load files and does not call so.core.holdout; the caller hands it bar arrays and a DataContext already
loaded. A missing DATA_SOURCE_LIST is ["SPY_1MIN"]. A callable is accepted as decide.

A candidate stream (4b-1a) uses DailyLoop: run_through_date stops at a period end without selling, a checkpoint
restores the design and the engine, and buffers are warmed by copying bars without calling decide(). Direct loader
calls are blocked for the duration of each run_through_date. The design file is AST-checked before the first call.

Minute mode (MODE_MINUTE_STR) is 4b-2: row-local signals, a shuffle check, barrier and trailing-stop engines. This
module only runs daily mode.
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


# FUNCTION: THE EMPTY RESULT OF A WINDOW WITH NO SESSIONS
def get_empty_daily_result_dict():
    """
    The 4a empty-window payload, plus the decision dict list used by a candidate stream.

    Args:
        None

    Returns:
        dict: Empty trades, equity, metrics, targets and decisions
    """
    # NOTHING WAS TRADED
    return {"trade_pdf": pd.DataFrame(), "daily_equity_pdf": pd.DataFrame(), "metric_dict": {},
            "target_weight_arr": np.array([], dtype=float), "decision_session_list": [], "decision_dict_list": []}


# FUNCTION: A DAILY LOOP THAT CAN STOP AT A PERIOD END AND RESUME
class DailyLoop:
    """
    One design, one engine, one window. Buffers start empty. run_through_date walks sessions in order. A restored
    engine already holds the position; warmup fills buffers up to the resume session without calling decide().
    """

    # FUNCTION: COLLECT THE WINDOW, THE BUFFERS AND THE ENGINE
    def __init__(self, design_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, engine_in=None,
                 initial_weight_in=1.0, dead_band_in=0.0, initial_capital_in=config.INITIAL_CAPITAL,
                 entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                 market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE, design_file_path_str_in=None,
                 check_source_bool_in=True):
        """
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
            check_source_bool_in (bool): False when the caller already ran the preflight
        """
        # REFUSE A DESIGN FILE THAT CAN REACH AROUND THE VIEW
        if check_source_bool_in:
            check_design_source(design_in, design_file_path_str_in)
        self.design = design_in
        self.ohlcv_array_dict = ohlcv_array_dict_in
        self.initial_weight_float = float(initial_weight_in)
        self.window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
        self.empty_bool = len(self.window_session_idx_arr) == 0
        self.next_session_pos_int = 0
        self.window_opened_bool = False
        self.target_weight_list = []
        self.decision_session_list = []
        self.decision_dict_list = []
        if self.empty_bool:
            self.engine = engine_in
            self.bar_buffer_dict = None
            self.feed_dict = {}
            return
        # INDEXES THE SESSION BODY READS
        idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
        self.decision_idx_arr = idx_dict["decision_idx_arr"]
        self.fill_idx_arr = idx_dict["fill_idx_arr"]
        self.end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
        self.open_arr = ohlcv_array_dict_in["open_arr"]
        self.close_arr = ohlcv_array_dict_in["close_arr"]
        self.timestamp_index = ohlcv_array_dict_in["timestamp_index"]
        data_context = data_context_in
        if data_context is None:
            data_context = get_runner_context(ohlcv_array_dict_in, declared_name_list_in=get_declared_source_name_list(design_in))
        self.bar_buffer_dict = get_empty_bar_buffer_dict(ohlcv_array_dict_in)
        self.feed_dict = get_source_feed_dict(design_in, ohlcv_array_dict_in, data_context)
        self.engine = engine_in if engine_in is not None else FractionalWeightEngine(dead_band_in, initial_capital_in,
                                                                                    entry_slippage_in, market_exit_slippage_in)

    # FUNCTION: COPY BARS AND ADVANCE FEEDS FOR SESSIONS ALREADY IN THE ENGINE
    def warmup_buffers(self, session_count_int_in):
        """
        Fills buffers through the decision bar of the first session_count_int_in window sessions. Does not call
        decide() and does not touch the engine.

        Args:
            session_count_int_in (int): Number of window sessions already completed

        Returns:
            None
        """
        # NOTHING TO COPY
        if self.empty_bool or int(session_count_int_in) <= 0:
            return
        for session_pos in range(int(session_count_int_in)):
            session_idx = int(self.window_session_idx_arr[session_pos])
            is_last_session = session_pos == len(self.window_session_idx_arr) - 1
            if is_last_session:
                continue
            decision_idx = int(self.decision_idx_arr[session_idx])
            fill_bar_buffer_through_decision(self.bar_buffer_dict, self.ohlcv_array_dict, session_idx, decision_idx)
            decision_ts = get_minute_bar_available_ts(self.timestamp_index[decision_idx])
            for feed in self.feed_dict.values():
                feed.advance_to_ts(decision_ts)
            for feed in self.feed_dict.values():
                feed.mark_call_boundary()

    # FUNCTION: RESTORE A CHECKPOINT (DESIGN AND ENGINE ALREADY ON THIS OBJECT)
    def restore_progress(self, next_session_pos_in, target_weight_list_in, decision_session_list_in, decision_dict_list_in):
        """
        Continues after next_session_pos_in sessions. The engine already holds those sessions.

        Args:
            next_session_pos_in (int): First window session still to run
            target_weight_list_in, decision_session_list_in, decision_dict_list_in (list): Recorded so far

        Returns:
            None
        """
        # THE ENGINE WAS PICKLED AFTER OPEN_WINDOW
        self.next_session_pos_int = int(next_session_pos_in)
        self.target_weight_list = list(target_weight_list_in)
        self.decision_session_list = list(decision_session_list_in)
        self.decision_dict_list = list(decision_dict_list_in)
        self.window_opened_bool = True
        self.warmup_buffers(self.next_session_pos_int)

    # FUNCTION: BUY THE INITIAL WEIGHT AT THE FIRST 10:00 OPEN
    def open_window_if_needed(self):
        """
        One buy at the first allowed open. A restored engine skips this.

        Args:
            None

        Returns:
            None
        """
        # ALREADY OPEN, OR NOTHING TO OPEN
        if self.empty_bool or self.window_opened_bool:
            return
        first_entry_idx = get_session_first_entry_idx(self.ohlcv_array_dict, int(self.window_session_idx_arr[0]))
        self.engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": self.timestamp_index[first_entry_idx],
                                 "raw_price": float(self.open_arr[first_entry_idx])}, float(self.initial_weight_float))
        self.window_opened_bool = True

    # FUNCTION: ONE SESSION (DECIDE, FILL, OR THE END SALE)
    def step_session(self, session_pos_in):
        """
        The 4a session body. The last window session has no design call.

        Args:
            session_pos_in (int): Position in the window session list

        Returns:
            None
        """
        # INDEXES FOR THIS SESSION
        session_pos = int(session_pos_in)
        session_idx = int(self.window_session_idx_arr[session_pos])
        decision_idx = int(self.decision_idx_arr[session_idx])
        fill_idx = int(self.fill_idx_arr[session_idx])
        end_idx = int(self.end_idx_arr[session_idx])
        is_last_session = session_pos == len(self.window_session_idx_arr) - 1
        session_date = self.ohlcv_array_dict["session_date_list"][session_idx]
        if not is_last_session:
            fill_bar_buffer_through_decision(self.bar_buffer_dict, self.ohlcv_array_dict, session_idx, decision_idx)
            decision_ts = get_minute_bar_available_ts(self.timestamp_index[decision_idx])
            for feed in self.feed_dict.values():
                feed.advance_to_ts(decision_ts)
            view = get_decision_view(self.bar_buffer_dict, session_idx, decision_idx, self.feed_dict)
            decision_dict = get_design_decision_dict(self.design, view)
            for feed in self.feed_dict.values():
                feed.mark_call_boundary()
            self.target_weight_list.append(float(decision_dict["target_weight"]))
            self.decision_session_list.append(session_date)
            self.decision_dict_list.append(dict(decision_dict))
            self.engine.apply_decision({"bar_idx": fill_idx, "timestamp": self.timestamp_index[fill_idx],
                                        "raw_price": float(self.open_arr[fill_idx])}, decision_dict, float(self.close_arr[decision_idx]))
        else:
            self.target_weight_list.append(np.nan)
            self.decision_session_list.append(session_date)
            self.decision_dict_list.append(get_decision_dict(None))
            self.engine.close_window({"bar_idx": end_idx, "timestamp": self.timestamp_index[end_idx],
                                      "raw_price": float(self.close_arr[end_idx])})
        self.engine.close_session({"session_date": session_date, "close": float(self.close_arr[end_idx])})

    # FUNCTION: WALK FROM THE NEXT SESSION THROUGH A DATE
    def run_through_date(self, through_date_in):
        """
        Processes window sessions with session_date <= through_date_in, starting at next_session_pos_int.

        Args:
            through_date_in (datetime.date | str): Last session to process (inclusive)

        Returns:
            None
        """
        # NOTHING IN THE WINDOW
        if self.empty_bool:
            return
        self.open_window_if_needed()
        through_date = pd.Timestamp(through_date_in).date()
        while self.next_session_pos_int < len(self.window_session_idx_arr):
            session_idx = int(self.window_session_idx_arr[self.next_session_pos_int])
            session_date = self.ohlcv_array_dict["session_date_list"][session_idx]
            if pd.Timestamp(session_date).date() > through_date:
                break
            self.step_session(self.next_session_pos_int)
            self.next_session_pos_int += 1

    # FUNCTION: TRADES, MARKS, TARGETS AND DECISIONS
    def get_result_dict(self):
        """
        The path after the sessions that have been run.

        Args:
            None

        Returns:
            dict: trade_pdf, daily_equity_pdf, metric_dict, target_weight_arr, decision_session_list, decision_dict_list
        """
        # THE EMPTY WINDOW HAS NO ENGINE RESULT
        if self.empty_bool:
            return get_empty_daily_result_dict()
        result_dict = self.engine.get_result_dict()
        result_dict["target_weight_arr"] = np.asarray(self.target_weight_list, dtype=float)
        result_dict["decision_session_list"] = list(self.decision_session_list)
        result_dict["decision_dict_list"] = list(self.decision_dict_list)
        return result_dict


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
        dict: trade_pdf, daily_equity_pdf, metric_dict, target_weight_arr, decision_session_list, decision_dict_list
    """
    # REFUSE A DESIGN FILE THAT CAN REACH AROUND THE VIEW
    check_design_source(design_in, design_file_path_str_in)
    loop = DailyLoop(design_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in, engine_in, initial_weight_in,
                     dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in, design_file_path_str_in,
                     check_source_bool_in=False)
    if loop.empty_bool:
        return get_empty_daily_result_dict()
    # BLOCK DIRECT LOADER CALLS FOR THE WHOLE RUN
    set_direct_read_blocked_bool(True)
    try:
        loop.run_through_date(date2_in)
    finally:
        set_direct_read_blocked_bool(False)
    return loop.get_result_dict()


# FUNCTION: ONE ENGINE PASS OVER RECORDED DECISIONS (NO DESIGN CALL)
def run_engine_decisions_dict(ohlcv_array_dict_in, date1_in, date2_in, decision_dict_list_in, engine_in=None,
                              initial_weight_in=1.0, dead_band_in=0.0, initial_capital_in=config.INITIAL_CAPITAL,
                              entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                              market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Applies one recorded decision per session at the 15:59 fill. The last session sells at the close. The position is
    carried across the whole window. No view is built and decide() is not called.

    Args:
        ohlcv_array_dict_in (dict): Full bar arrays
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        decision_dict_list_in (list[dict]): One get_decision_dict output per window session
        engine_in (Engine | None): None uses a fresh FractionalWeightEngine
        initial_weight_in (float): Weight bought at the first 10:00 open
        dead_band_in (float): Passed to the default engine
        initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Default-engine costs

    Returns:
        dict: trade_pdf, daily_equity_pdf, metric_dict, target_weight_arr, decision_session_list, decision_dict_list
    """
    # THE SAME WINDOW AS THE DAILY LOOP
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    if len(window_session_idx_arr) == 0:
        return get_empty_daily_result_dict()
    if len(decision_dict_list_in) != len(window_session_idx_arr):
        raise ValueError("recorded decisions must cover every window session.")
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    decision_idx_arr, fill_idx_arr = idx_dict["decision_idx_arr"], idx_dict["fill_idx_arr"]
    end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
    open_arr, close_arr, timestamp_index = ohlcv_array_dict_in["open_arr"], ohlcv_array_dict_in["close_arr"], ohlcv_array_dict_in["timestamp_index"]
    engine = engine_in if engine_in is not None else FractionalWeightEngine(dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, int(window_session_idx_arr[0]))
    engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": timestamp_index[first_entry_idx],
                        "raw_price": float(open_arr[first_entry_idx])}, float(initial_weight_in))
    target_weight_list, decision_session_list, decision_dict_list = [], [], []
    for session_pos, session_idx in enumerate(window_session_idx_arr):
        session_idx = int(session_idx)
        decision_idx, fill_idx, end_idx = int(decision_idx_arr[session_idx]), int(fill_idx_arr[session_idx]), int(end_idx_arr[session_idx])
        is_last_session = session_pos == len(window_session_idx_arr) - 1
        session_date = ohlcv_array_dict_in["session_date_list"][session_idx]
        decision_dict = get_decision_dict(decision_dict_list_in[session_pos])
        decision_dict_list.append(dict(decision_dict))
        decision_session_list.append(session_date)
        if not is_last_session:
            target_weight_list.append(float(decision_dict["target_weight"]))
            engine.apply_decision({"bar_idx": fill_idx, "timestamp": timestamp_index[fill_idx],
                                   "raw_price": float(open_arr[fill_idx])}, decision_dict, float(close_arr[decision_idx]))
        else:
            target_weight_list.append(np.nan)
            engine.close_window({"bar_idx": end_idx, "timestamp": timestamp_index[end_idx],
                                 "raw_price": float(close_arr[end_idx])})
        engine.close_session({"session_date": session_date, "close": float(close_arr[end_idx])})
    result_dict = engine.get_result_dict()
    result_dict["target_weight_arr"] = np.asarray(target_weight_list, dtype=float)
    result_dict["decision_session_list"] = list(decision_session_list)
    result_dict["decision_dict_list"] = list(decision_dict_list)
    return result_dict
