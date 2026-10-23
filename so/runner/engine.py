import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL, BARRIER CONSTANTS)
from so import config
# IMPORT TRADE EXECUTION FUNCTIONS (FEES, SHARE COUNT, BARRIER PRICES, SLIPPAGE)
from so.core.trade_execution import (calculate_side_fee, get_affordable_share_count, get_barrier_price_dict,
                                     get_exit_slippage_arr, get_trade_result_str)
# IMPORT PERFORMANCE METRICS AND THE TRAILING-STOP METRIC BLOCK
from so.core.performance_metrics import get_sharpe_ratio, get_max_drawdown
from so.core.reentry_simulation import get_stop_reentry_metric_dict
# IMPORT THE COMPILED SESSION LOOPS
from so.runner.engine_kernels import (get_trailing_stop_hit_tuple, get_barrier_exit_tuple, REASON_STOP_INT,
                                      REASON_TP_INT, REASON_TL_INT)

"""
Engine Interface (infrastructure steps 4a and 4b-2a)

The design decides. The position engine turns decisions into trades. Anything that needs memory across minutes
(being in a position, the entry price, a trailing high, take-profit and stop-loss) lives here, not in design code.
An engine sees the fill or mark it is given and its own state only.

    open_window      buy initial_weight at the first 10:00 open
    apply_decision   rebalance / enter / flatten at the 15:59 fill (daily mode)
    process_bars     intra-session trailing stops or barrier exits (numba); no-op for fractional
    process_bar      one-bar wrapper around process_bars
    close_session    mark cash + shares x session close
    close_window     sell everything at the last close
    get_state_dict   read-only snapshot for the view (in position, shares, last exit, cash sessions)
    get_result_dict  trades, daily equity, metrics

A fill event has bar_idx, timestamp, raw_price (the open, except END which is the close), and may carry close,
decision_ts, session_idx and session_end_idx. A mark event has session_date and close. A bar-range event has
bar_idx_arr, timestamp_index, open_arr, high_arr, low_arr, close_arr, session_date.

Fractional weight matches so.core.fractional_exposure. BarrierEngine matches so.core.trade_execution and
so.core.backtest_simulation.simulate_decision_trading_dict. TrailingStopEngine matches
so.core.reentry_simulation.simulate_stop_reentry_dict. A float decision is target_weight. NaN or a missing
weight means keep.
"""

# ENGINE NAMES A DESIGN MODULE MAY SET ON ENGINE_NAME
ENGINE_FRACTIONAL_STR = "fractional"
ENGINE_TRAILING_STOP_STR = "trailing_stop"
ENGINE_BARRIER_STR = "barrier"
# KEYS A DECISION MAY CARRY
DECISION_KEY_LIST = ["target_weight", "stop_price", "take_profit_price", "trail_multiple", "flatten_bool",
                     "volatility", "delta", "exit_block_sessions", "require_fresh_exit", "reentry_reason"]
# FLOAT KEYS COMPARED WITH NaN-EQUAL AND NUMERIC_TOLERANCE
FLOAT_DECISION_KEY_LIST = ["target_weight", "stop_price", "take_profit_price", "trail_multiple", "volatility", "delta"]

# FUNCTION: A FLOAT OR NONE TO A DECISION FIELD (NONE STAYS NONE)
def get_optional_float(value_in):
    """
    None stays None. Anything else is float (NaN if it is not finite).

    Args:
        value_in: Raw field

    Returns:
        float | None: Converted value
    """
    # MISSING STAYS MISSING
    if value_in is None:
        return None
    return float(value_in)


# FUNCTION: NORMALIZE A DESIGN RETURN TO A DECISION DICT
def get_decision_dict(decision_in):
    """
    A float is target_weight. None or a missing weight is NaN (keep). Extra 4b fields default to None / False / 0.

    Args:
        decision_in (float | dict | None): Design return

    Returns:
        dict: Every key in DECISION_KEY_LIST
    """
    # EMPTY DEFAULTS
    empty_dict = {"target_weight": np.nan, "stop_price": None, "take_profit_price": None, "trail_multiple": None,
                  "flatten_bool": False, "volatility": None, "delta": None, "exit_block_sessions": 0,
                  "require_fresh_exit": False, "reentry_reason": "model"}
    if decision_in is None:
        return dict(empty_dict)
    if isinstance(decision_in, (int, float, np.integer, np.floating)):
        empty_dict["target_weight"] = float(decision_in)
        return empty_dict
    # A DICT KEEPS UNKNOWN KEYS OUT; MISSING WEIGHT MEANS KEEP
    decision_dict = dict(decision_in)
    target_weight = decision_dict.get("target_weight", np.nan)
    empty_dict["target_weight"] = np.nan if target_weight is None else float(target_weight)
    empty_dict["stop_price"] = get_optional_float(decision_dict.get("stop_price"))
    empty_dict["take_profit_price"] = get_optional_float(decision_dict.get("take_profit_price"))
    empty_dict["trail_multiple"] = get_optional_float(decision_dict.get("trail_multiple"))
    empty_dict["flatten_bool"] = bool(decision_dict.get("flatten_bool", False))
    empty_dict["volatility"] = get_optional_float(decision_dict.get("volatility"))
    empty_dict["delta"] = get_optional_float(decision_dict.get("delta"))
    empty_dict["exit_block_sessions"] = int(decision_dict.get("exit_block_sessions") or 0)
    empty_dict["require_fresh_exit"] = bool(decision_dict.get("require_fresh_exit", False))
    empty_dict["reentry_reason"] = str(decision_dict.get("reentry_reason") or "model")
    return empty_dict


# FUNCTION: THE EMPTY ENGINE SNAPSHOT THE VIEW HOLDS
def get_empty_engine_state_dict():
    """
    Args:
        None

    Returns:
        dict: in_position, share_count, last_exit_session, last_exit_reason, last_exit_fill_price, cash_session_count
    """
    # NOTHING IS OPEN
    return {"in_position": False, "share_count": 0, "last_exit_session": None, "last_exit_reason": None,
            "last_exit_fill_price": None, "cash_session_count": 0}


# FUNCTION: ENGINE BASE (4B ENGINES SUBCLASS THIS)
class Engine:
    """
    Fills and marks. process_bar is a no-op so a 4b engine can override it without a 4a loop change.
    """

    # FUNCTION: START OF THE WINDOW
    def open_window(self, fill_event_dict_in, initial_weight_in):
        """
        Buy initial_weight at the first allowed open of the window.

        Args:
            fill_event_dict_in (dict): bar_idx, timestamp, raw_price
            initial_weight_in (float): Weight bought at the window start

        Returns:
            None
        """
        # 4A ENGINES IMPLEMENT THIS
        raise NotImplementedError("open_window")

    # FUNCTION: A DAILY FILL AFTER A DECISION
    def apply_decision(self, fill_event_dict_in, decision_dict_in, decision_close_in):
        """
        Rebalance at the fill when the decision asks for a weight outside the dead band.

        Args:
            fill_event_dict_in (dict): bar_idx, timestamp, raw_price of the fill bar
            decision_dict_in (dict): Output of get_decision_dict
            decision_close_in (float): Close of the decision bar (for w_now)

        Returns:
            None
        """
        # 4A ENGINES IMPLEMENT THIS
        raise NotImplementedError("apply_decision")

    # FUNCTION: ONE BAR FOR WORKING STOPS (4B)
    def process_bar(self, bar_event_dict_in):
        """
        One-bar wrapper around process_bars. Fractional ignores it.

        Args:
            bar_event_dict_in (dict): bar_idx, timestamp, open, high, low, close, session_date

        Returns:
            None
        """
        # BUILD A ONE-BAR RANGE AND DELEGATE
        bar_idx = int(bar_event_dict_in["bar_idx"])
        timestamp = bar_event_dict_in["timestamp"]
        range_dict = {"bar_idx_arr": np.asarray([bar_idx], dtype=np.int64),
                      "timestamp_index": [timestamp],
                      "open_arr": np.asarray([float(bar_event_dict_in["open"])], dtype=np.float64),
                      "high_arr": np.asarray([float(bar_event_dict_in["high"])], dtype=np.float64),
                      "low_arr": np.asarray([float(bar_event_dict_in["low"])], dtype=np.float64),
                      "close_arr": np.asarray([float(bar_event_dict_in["close"])], dtype=np.float64),
                      "session_date": bar_event_dict_in.get("session_date")}
        self.process_bars(range_dict)

    # FUNCTION: A RANGE OF BARS FOR WORKING STOPS (4B)
    def process_bars(self, bar_event_dict_in):
        """
        No-op in the fractional engine. Barrier and trailing-stop engines fill intra-session exits here.

        Args:
            bar_event_dict_in (dict): bar_idx_arr, timestamp_index, open/high/low/close arrays, session_date

        Returns:
            None
        """
        # FRACTIONAL WEIGHT HAS NO INTRA-SESSION WORK
        return None

    # FUNCTION: TRAILING-STOP PARAMETERS FOR THE NEXT BAR RANGE
    def set_stop_params(self, trail_multiple_in, volatility_in):
        """
        No-op except on TrailingStopEngine.

        Args:
            trail_multiple_in (float | None): k
            volatility_in (float | None): Daily volatility

        Returns:
            None
        """
        # FRACTIONAL AND BARRIER IGNORE THESE
        return None

    # FUNCTION: SESSION END INDEXES FOR A BARRIER HORIZON
    def set_session_bounds(self, session_end_idx_arr_in, bar_count_in):
        """
        No-op except on BarrierEngine.

        Args:
            session_end_idx_arr_in (np.ndarray): Last bar of every session
            bar_count_in (int): Number of bars in the window

        Returns:
            None
        """
        # FRACTIONAL AND TRAILING IGNORE THESE
        return None

    # FUNCTION: READ-ONLY ACCOUNT SNAPSHOT FOR THE VIEW
    def get_state_dict(self):
        """
        A copy the design may read. The engine never shows anything after the decision moment; the loop snapshots
        this after processing bars through the decision bar and before apply_decision.

        Args:
            None

        Returns:
            dict: in_position, share_count, last_exit_session, last_exit_reason, last_exit_fill_price, cash_session_count
        """
        # DEFAULT: NOTHING OPEN
        return get_empty_engine_state_dict()

    # FUNCTION: MARK THE ACCOUNT AT THE SESSION CLOSE
    def close_session(self, mark_event_dict_in):
        """
        Append one daily equity row at the session close.

        Args:
            mark_event_dict_in (dict): session_date, close

        Returns:
            None
        """
        # 4A ENGINES IMPLEMENT THIS
        raise NotImplementedError("close_session")

    # FUNCTION: END OF THE WINDOW
    def close_window(self, fill_event_dict_in):
        """
        Sell every share at the last close.

        Args:
            fill_event_dict_in (dict): bar_idx, timestamp, raw_price of the last close

        Returns:
            None
        """
        # 4A ENGINES IMPLEMENT THIS
        raise NotImplementedError("close_window")

    # FUNCTION: TRADES, MARKS AND METRICS
    def get_result_dict(self):
        """
        The path after close_window.

        Args:
            None

        Returns:
            dict: trade_pdf, daily_equity_pdf, metric_dict
        """
        # 4A ENGINES IMPLEMENT THIS
        raise NotImplementedError("get_result_dict")


# FUNCTION: FRACTIONAL-WEIGHT ENGINE (SAME RULES AS so.core.fractional_exposure)
class FractionalWeightEngine(Engine):
    """
    Holds a fraction w in [0, 1] of equity in SPY. Rebalances only outside the dead band. process_bar is a no-op.
    """

    # FUNCTION: STORE COSTS AND THE EMPTY ACCOUNT
    def __init__(self, dead_band_in, initial_capital_in=config.INITIAL_CAPITAL,
                 entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                 market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
        """
        Args:
            dead_band_in (float): Rebalance only if |w* - w_now| is greater than this
            initial_capital_in (float): Starting cash
            entry_slippage_in, market_exit_slippage_in (float): Slippage per share of buys and sells
        """
        # COSTS AND THE ACCOUNT
        self.dead_band_float = float(dead_band_in)
        self.initial_capital_float = float(initial_capital_in)
        self.entry_slippage_float = float(entry_slippage_in)
        self.market_exit_slippage_float = float(market_exit_slippage_in)
        self.cash_float = float(initial_capital_in)
        self.share_count_int = 0
        self.trade_dict_list = []
        self.equity_dict_list = []

    # FUNCTION: MOVE TO A TARGET WEIGHT AT A BAR PRICE
    def _rebalance(self, fill_event_dict_in, target_weight_in, reason_str_in, weight_before_in):
        """
        Same share-count and fee rules as so.core.fractional_exposure.

        Args:
            fill_event_dict_in (dict): bar_idx, timestamp, raw_price
            target_weight_in (float): Clamped target in [0, 1]
            reason_str_in (str): window_start, rebalance, or END
            weight_before_in (float): Weight at the decision (or 0 at the window start)

        Returns:
            None
        """
        # EQUITY AT THE RAW PRICE, THEN THE TARGET SHARE COUNT
        raw_price = float(fill_event_dict_in["raw_price"])
        equity = self.cash_float + self.share_count_int * raw_price
        if target_weight_in >= 1:
            target_share_count = self.share_count_int + get_affordable_share_count(self.cash_float, raw_price + self.entry_slippage_float)
        elif target_weight_in <= 0:
            target_share_count = 0
        else:
            target_share_count = int(np.floor(target_weight_in * equity / raw_price))
        # THE ORDER, LIMITED TO WHAT THE CASH CAN BUY
        delta_share_count = target_share_count - self.share_count_int
        if delta_share_count > 0:
            fill_price = raw_price + self.entry_slippage_float
            delta_share_count = min(delta_share_count, get_affordable_share_count(self.cash_float, fill_price))
        else:
            fill_price = raw_price - self.market_exit_slippage_float
        if delta_share_count == 0:
            return
        # PAY OR RECEIVE THE CASH AND THE FEE
        fee = calculate_side_fee(abs(delta_share_count), fill_price)
        self.cash_float -= delta_share_count * fill_price + fee
        self.share_count_int += delta_share_count
        self.trade_dict_list.append({"trade_ts": fill_event_dict_in["timestamp"], "trade_idx": int(fill_event_dict_in["bar_idx"]),
                                     "reason": reason_str_in, "raw_price": float(raw_price), "fill_price": round(float(fill_price), 6),
                                     "delta_share_count": int(delta_share_count), "share_count_after": int(self.share_count_int),
                                     "fee": fee, "slippage_cost": abs(delta_share_count) * abs(fill_price - raw_price),
                                     "weight_before": float(weight_before_in), "target_weight": float(target_weight_in),
                                     "cash_after": round(self.cash_float, 6)})

    # FUNCTION: BUY THE INITIAL WEIGHT
    def open_window(self, fill_event_dict_in, initial_weight_in):
        """
        Buy initial_weight at the first allowed open of the window.

        Args:
            fill_event_dict_in (dict): bar_idx, timestamp, raw_price
            initial_weight_in (float): Weight bought at the window start

        Returns:
            None
        """
        # NO BUY WHEN THE STARTING WEIGHT IS ZERO
        if float(initial_weight_in) > 0:
            self._rebalance(fill_event_dict_in, float(initial_weight_in), "window_start", 0.0)

    # FUNCTION: REBALANCE AT THE FILL WHEN THE TARGET IS OUTSIDE THE DEAD BAND
    def apply_decision(self, fill_event_dict_in, decision_dict_in, decision_close_in):
        """
        Ignores 4b fields. NaN target keeps the position.

        Args:
            fill_event_dict_in (dict): Fill bar
            decision_dict_in (dict): Output of get_decision_dict
            decision_close_in (float): Close of the decision bar

        Returns:
            None
        """
        # KEEP WHEN THE DESIGN DID NOT NAME A WEIGHT
        target_weight = float(decision_dict_in["target_weight"])
        if not np.isfinite(target_weight):
            return
        # CURRENT WEIGHT AT THE DECISION CLOSE
        decision_close = float(decision_close_in)
        decision_equity = self.cash_float + self.share_count_int * decision_close
        weight_now = self.share_count_int * decision_close / decision_equity if decision_equity > 0 else 0.0
        clamped_weight = min(max(target_weight, 0.0), 1.0)
        if abs(clamped_weight - weight_now) > self.dead_band_float:
            self._rebalance(fill_event_dict_in, clamped_weight, "rebalance", weight_now)

    # FUNCTION: MARK TO MARKET
    def close_session(self, mark_event_dict_in):
        """
        Append one daily equity row at the session close.

        Args:
            mark_event_dict_in (dict): session_date, close

        Returns:
            None
        """
        # THE SAME MARK AS so.core.fractional_exposure
        close_price = float(mark_event_dict_in["close"])
        equity = self.cash_float + self.share_count_int * close_price
        self.equity_dict_list.append({"date": mark_event_dict_in["session_date"], "equity": round(equity, 6),
                                      "in_position": self.share_count_int > 0,
                                      "weight": self.share_count_int * close_price / equity if equity > 0 else 0.0})

    # FUNCTION: SELL EVERY SHARE AT THE LAST CLOSE
    def close_window(self, fill_event_dict_in):
        """
        Sell every share at the last close.

        Args:
            fill_event_dict_in (dict): Last close

        Returns:
            None
        """
        # NOTHING TO SELL
        if self.share_count_int <= 0:
            return
        raw_price = float(fill_event_dict_in["raw_price"])
        equity = self.cash_float + self.share_count_int * raw_price
        weight_now = self.share_count_int * raw_price / equity if equity > 0 else 0.0
        self._rebalance(fill_event_dict_in, 0.0, "END", weight_now)

    # FUNCTION: READ-ONLY ACCOUNT SNAPSHOT
    def get_state_dict(self):
        """
        Args:
            None

        Returns:
            dict: in_position, share_count, last_exit_session, last_exit_reason, last_exit_fill_price, cash_session_count
        """
        # FRACTIONAL HAS NO CASH-SESSION COUNTER
        return {"in_position": self.share_count_int > 0, "share_count": int(self.share_count_int),
                "last_exit_session": None, "last_exit_reason": None, "last_exit_fill_price": None,
                "cash_session_count": 0}

    # FUNCTION: TRADES, MARKS AND METRICS
    def get_result_dict(self):
        """
        The path after the last mark. Mean weight excludes the last session (everything is sold at its close).

        Args:
            None

        Returns:
            dict: trade_pdf, daily_equity_pdf, metric_dict
        """
        # THE SAME METRIC KEYS AS so.core.fractional_exposure
        trade_pdf, daily_equity_pdf = pd.DataFrame(self.trade_dict_list), pd.DataFrame(self.equity_dict_list)
        if daily_equity_pdf.empty:
            return {"trade_pdf": trade_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": {}}
        final_equity = float(daily_equity_pdf["equity"].iloc[-1])
        counted_weight_arr = daily_equity_pdf["weight"].to_numpy(dtype=float)[:-1] if len(daily_equity_pdf) > 1 else daily_equity_pdf["weight"].to_numpy(dtype=float)
        metric_dict = {"total_return": round(final_equity / self.initial_capital_float - 1, 8),
                       "sharpe_ratio": get_sharpe_ratio(daily_equity_pdf, self.initial_capital_float),
                       "max_drawdown": get_max_drawdown(daily_equity_pdf, self.initial_capital_float),
                       "final_equity": round(final_equity, 6),
                       "trade_count": int(len(trade_pdf)),
                       "rebalance_count": int((trade_pdf["reason"] == "rebalance").sum()) if not trade_pdf.empty else 0,
                       "mean_weight": float(counted_weight_arr.mean()),
                       "cost_paid": float((trade_pdf["fee"] + trade_pdf["slippage_cost"]).sum()) if not trade_pdf.empty else 0.0}
        return {"trade_pdf": trade_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": metric_dict}


# FUNCTION: A FINITE FLOAT OR NAN
def get_finite_or_nan_float(value_in):
    """
    Args:
        value_in (float | None): Raw value

    Returns:
        float: value, or NaN when missing
    """
    # NONE AND NON-FINITE BECOME NAN
    if value_in is None:
        return np.nan
    value_float = float(value_in)
    return value_float if np.isfinite(value_float) else np.nan


"""
Trailing Stop And Re-entry
"""


# FUNCTION: TRAILING-STOP ENGINE (SAME RULES AS so.core.reentry_simulation)
class TrailingStopEngine(Engine):
    """
    Starts invested at the first 10:00 open. A volatility trailing stop is checked minute by minute. Re-entry is
    target_weight > 0 at the 15:59 fill; flatten_bool is the exit signal. Cooling-off and fresh-exit are engine
    options the design requests on the re-entry decision. Forced re-entry uses max_cash_sessions.
    """

    # FUNCTION: STORE COSTS AND THE EMPTY ACCOUNT
    def __init__(self, max_cash_sessions_in=None, initial_capital_in=config.INITIAL_CAPITAL,
                 entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                 market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
        """
        Args:
            max_cash_sessions_in (int | None): Forced re-entry after this many cash decisions (None = never)
            initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Costs
        """
        # COSTS AND THE ACCOUNT
        self.max_cash_sessions = None if max_cash_sessions_in is None else int(max_cash_sessions_in)
        self.initial_capital_float = float(initial_capital_in)
        self.entry_slippage_float = float(entry_slippage_in)
        self.market_exit_slippage_float = float(market_exit_slippage_in)
        self.cash_float = float(initial_capital_in)
        self.invested_bool = False
        self.share_count_int = 0
        self.entry_idx_int = -1
        self.buy_fill_float = np.nan
        self.buy_fee_float = 0.0
        self.buy_raw_price_float = np.nan
        self.entry_reason_str = ""
        self.decision_ts = pd.NaT
        self.highest_close_float = -np.inf
        self.stop_float = -np.inf
        self.trail_multiple_float = np.nan
        self.volatility_float = np.nan
        self.cash_session_count_int = 0
        self.episode_dict = None
        self.exit_block_until_int = -1
        self.fresh_exit_pending_bool = False
        self.last_exit_session = None
        self.last_exit_reason_str = None
        self.last_exit_fill_price = None
        self._buy_ts = pd.NaT
        self._window_end_ts = pd.NaT
        self._window_end_close_float = np.nan
        self.transaction_dict_list = []
        self.episode_dict_list = []
        self.equity_dict_list = []

    # FUNCTION: STORE k AND VOLATILITY FOR THE NEXT BAR RANGE
    def set_stop_params(self, trail_multiple_in, volatility_in):
        """
        Args:
            trail_multiple_in (float | None): k
            volatility_in (float | None): Daily volatility

        Returns:
            None
        """
        # NAN MEANS NO STOP ON THE NEXT RANGE
        self.trail_multiple_float = get_finite_or_nan_float(trail_multiple_in)
        self.volatility_float = get_finite_or_nan_float(volatility_in)

    # FUNCTION: BUY AT A BAR OPEN
    def _buy(self, fill_event_dict_in, reason_str_in, decision_ts_in):
        """
        Same share-count and fee rules as simulate_stop_reentry_dict.

        Args:
            fill_event_dict_in (dict): bar_idx, timestamp, raw_price, close
            reason_str_in (str): window_start, model, delay, forced, ...
            decision_ts_in: Decision timestamp (NaT at the window start)

        Returns:
            bool: True when shares were bought
        """
        # FILL AND SHARE COUNT
        raw_price = float(fill_event_dict_in["raw_price"])
        fill_price = raw_price + self.entry_slippage_float
        share_count = get_affordable_share_count(self.cash_float, fill_price)
        if share_count <= 0:
            return False
        buy_fee = calculate_side_fee(share_count, fill_price)
        self.cash_float -= share_count * fill_price + buy_fee
        entry_close = float(fill_event_dict_in.get("close", raw_price))
        self.invested_bool = True
        self.share_count_int = int(share_count)
        self.entry_idx_int = int(fill_event_dict_in["bar_idx"])
        self.buy_fill_float = float(fill_price)
        self.buy_fee_float = float(buy_fee)
        self.buy_raw_price_float = float(raw_price)
        self.entry_reason_str = str(reason_str_in)
        self.decision_ts = decision_ts_in
        self._buy_ts = fill_event_dict_in["timestamp"]
        self.highest_close_float = float(entry_close)
        self.stop_float = -np.inf
        self.cash_session_count_int = 0
        self.fresh_exit_pending_bool = False
        # CLOSE THE OPEN EPISODE
        if self.episode_dict is not None:
            self.episode_dict.update({"reentry_ts": fill_event_dict_in["timestamp"], "reentry_fill_price": fill_price,
                                      "reentry_reason": str(reason_str_in)})
            self.episode_dict_list.append(self.episode_dict)
            self.episode_dict = None
        return True

    # FUNCTION: SELL AT A PRICE
    def _sell(self, bar_idx_in, timestamp_in, raw_price_in, reason_str_in, stop_price_in=np.nan, session_date_in=None):
        """
        Args:
            bar_idx_in (int): Exit bar
            timestamp_in: Exit timestamp
            raw_price_in (float): Raw exit price before slippage
            reason_str_in (str): STOP, SIGNAL, END
            stop_price_in (float): Stop that was hit (NaN if not a stop)
            session_date_in: Session of the exit (None keeps the last one)

        Returns:
            None
        """
        # FILL, FEE AND CASH
        raw_price = float(raw_price_in)
        fill_price = raw_price - self.market_exit_slippage_float
        sell_fee = calculate_side_fee(self.share_count_int, fill_price)
        self.cash_float += self.share_count_int * fill_price - sell_fee
        net_profit = self.share_count_int * (fill_price - self.buy_fill_float) - self.buy_fee_float - sell_fee
        self.transaction_dict_list.append({
            "transaction_id": len(self.transaction_dict_list),
            "decision_ts": self.decision_ts,
            "entry_reason": self.entry_reason_str,
            "buy_ts": self._buy_ts,
            "buy_idx": self.entry_idx_int,
            "buy_raw_price": self.buy_raw_price_float,
            "buy_fill_price": round(self.buy_fill_float, 6),
            "share_count": self.share_count_int,
            "buy_fee": self.buy_fee_float,
            "sell_ts": timestamp_in,
            "sell_idx": int(bar_idx_in),
            "sell_raw_price": round(raw_price, 6),
            "sell_fill_price": round(fill_price, 6),
            "sell_fee": sell_fee,
            "exit_reason": str(reason_str_in),
            "SL_price": round(float(stop_price_in), 6) if np.isfinite(stop_price_in) else np.nan,
            "TP_price": np.nan,
            "net_profit": round(net_profit, 6),
            "hold_bar_count": int(bar_idx_in) - self.entry_idx_int,
            "equity_after": round(self.cash_float, 6),
        })
        self.invested_bool = False
        self.share_count_int = 0
        self.entry_idx_int = -1
        self.buy_fill_float = np.nan
        self.buy_fee_float = 0.0
        self.cash_session_count_int = 0
        if session_date_in is not None:
            self.last_exit_session = session_date_in
        self.last_exit_reason_str = str(reason_str_in)
        self.last_exit_fill_price = float(fill_price)
        if reason_str_in != "END":
            self.episode_dict = {"exit_ts": timestamp_in, "exit_reason": str(reason_str_in),
                                 "exit_fill_price": fill_price, "first_cash_session_idx": None, "cash_session_count": 0}

    # FUNCTION: BUY THE INITIAL WEIGHT
    def open_window(self, fill_event_dict_in, initial_weight_in):
        """
        Args:
            fill_event_dict_in (dict): First allowed open
            initial_weight_in (float): Weight bought at the window start

        Returns:
            None
        """
        # NO BUY WHEN THE STARTING WEIGHT IS ZERO
        if float(initial_weight_in) > 0:
            self._buy(fill_event_dict_in, "window_start", pd.NaT)

    # FUNCTION: RE-ENTRY, SIGNAL EXIT, FORCED RE-ENTRY AT THE FILL
    def apply_decision(self, fill_event_dict_in, decision_dict_in, decision_close_in):
        """
        Updates stop parameters, then: if invested, a flatten_bool sells at the fill (cooling-off and fresh-exit
        can ignore it); if in cash, target_weight > 0 re-enters, else max_cash_sessions may force a buy.

        Args:
            fill_event_dict_in (dict): Fill bar
            decision_dict_in (dict): Output of get_decision_dict
            decision_close_in (float): Unused (kept for the engine interface)

        Returns:
            None
        """
        # THIS SESSION'S STOP PARAMETERS APPLY FROM THE FILL ONWARD
        self.set_stop_params(decision_dict_in.get("trail_multiple"), decision_dict_in.get("volatility"))
        session_idx = int(fill_event_dict_in.get("session_idx", -1))
        flatten_bool = bool(decision_dict_in.get("flatten_bool", False))
        decision_ts = fill_event_dict_in.get("decision_ts", fill_event_dict_in["timestamp"])
        # A FRESH SIGNAL IS NEEDED: THE SIGNAL OFF CLEARS THE FLAG
        if self.fresh_exit_pending_bool and self.invested_bool and not flatten_bool:
            self.fresh_exit_pending_bool = False
        # SIGNAL EXIT WHILE INVESTED
        if self.invested_bool and flatten_bool and session_idx > self.exit_block_until_int and not self.fresh_exit_pending_bool:
            self._sell(int(fill_event_dict_in["bar_idx"]), fill_event_dict_in["timestamp"],
                       float(fill_event_dict_in["raw_price"]), "SIGNAL", session_date_in=fill_event_dict_in.get("session_date"))
            return
        # CASH DECISION: COUNT IT, THEN MAYBE RE-ENTER
        if (not self.invested_bool) and self.episode_dict is not None:
            self.cash_session_count_int += 1
            self.episode_dict["cash_session_count"] = self.cash_session_count_int
            if self.episode_dict["first_cash_session_idx"] is None:
                self.episode_dict["first_cash_session_idx"] = int(session_idx)
            target_weight = float(decision_dict_in.get("target_weight", np.nan))
            want_buy_bool = np.isfinite(target_weight) and target_weight > 0.0
            if want_buy_bool:
                block_session_count = int(decision_dict_in.get("exit_block_sessions") or 0)
                fresh_exit_bool = bool(decision_dict_in.get("require_fresh_exit", False))
                reason_str = str(decision_dict_in.get("reentry_reason") or "model")
                if self._buy(fill_event_dict_in, reason_str, decision_ts):
                    self.exit_block_until_int = int(session_idx) + block_session_count
                    self.fresh_exit_pending_bool = fresh_exit_bool and flatten_bool
            elif self.max_cash_sessions is not None and self.cash_session_count_int >= self.max_cash_sessions:
                self._buy(fill_event_dict_in, "forced", decision_ts)

    # FUNCTION: CHECK THE TRAILING STOP ON A RANGE OF BARS
    def process_bars(self, bar_event_dict_in):
        """
        Args:
            bar_event_dict_in (dict): One session range

        Returns:
            None
        """
        # NOTHING TO CHECK
        if not self.invested_bool:
            return
        bar_idx_arr = np.asarray(bar_event_dict_in["bar_idx_arr"], dtype=np.int64)
        if len(bar_idx_arr) == 0:
            return
        start_offset = 0
        while start_offset < len(bar_idx_arr) and int(bar_idx_arr[start_offset]) <= self.entry_idx_int:
            start_offset += 1
        if start_offset >= len(bar_idx_arr):
            return
        open_arr = np.asarray(bar_event_dict_in["open_arr"], dtype=np.float64)[start_offset:]
        low_arr = np.asarray(bar_event_dict_in["low_arr"], dtype=np.float64)[start_offset:]
        close_arr = np.asarray(bar_event_dict_in["close_arr"], dtype=np.float64)[start_offset:]
        hit_int, hit_offset, raw_price, stop_price, new_highest, new_stop = get_trailing_stop_hit_tuple(
            open_arr, low_arr, close_arr, float(self.highest_close_float), float(self.stop_float),
            float(self.trail_multiple_float), float(self.volatility_float))
        if int(hit_int) == 1:
            timestamp_index = bar_event_dict_in["timestamp_index"]
            bar_idx = int(bar_idx_arr[start_offset + int(hit_offset)])
            self._sell(bar_idx, timestamp_index[start_offset + int(hit_offset)], float(raw_price), "STOP",
                       stop_price_in=float(stop_price), session_date_in=bar_event_dict_in.get("session_date"))
            return
        self.highest_close_float = float(new_highest)
        self.stop_float = float(new_stop)

    # FUNCTION: MARK TO MARKET
    def close_session(self, mark_event_dict_in):
        """
        Args:
            mark_event_dict_in (dict): session_date, close

        Returns:
            None
        """
        # CASH PLUS MARKED SHARES
        close_price = float(mark_event_dict_in["close"])
        equity = self.cash_float + self.share_count_int * close_price
        self.equity_dict_list.append({"date": mark_event_dict_in["session_date"], "equity": round(equity, 6),
                                      "in_position": self.share_count_int > 0,
                                      "weight": 1.0 if self.share_count_int > 0 and equity > 0 else 0.0})

    # FUNCTION: SELL AT THE LAST CLOSE
    def close_window(self, fill_event_dict_in):
        """
        Args:
            fill_event_dict_in (dict): Last close

        Returns:
            None
        """
        # KEEP THE LAST CLOSE FOR AN OPEN CASH EPISODE
        self._window_end_ts = fill_event_dict_in["timestamp"]
        self._window_end_close_float = float(fill_event_dict_in["raw_price"])
        if not self.invested_bool:
            # THE LAST SESSION IS STILL A CASH DECISION IN THE OLD SIMULATOR (NO RE-ENTRY)
            if self.episode_dict is not None:
                self.cash_session_count_int += 1
                self.episode_dict["cash_session_count"] = self.cash_session_count_int
                if self.episode_dict["first_cash_session_idx"] is None:
                    session_idx = fill_event_dict_in.get("session_idx")
                    if session_idx is not None:
                        self.episode_dict["first_cash_session_idx"] = int(session_idx)
            return
        self._sell(int(fill_event_dict_in["bar_idx"]), fill_event_dict_in["timestamp"],
                   float(fill_event_dict_in["raw_price"]), "END", session_date_in=fill_event_dict_in.get("session_date"))

    # FUNCTION: READ-ONLY ACCOUNT SNAPSHOT
    def get_state_dict(self):
        """
        cash_session_count includes this decision when the account is already in cash (the first cash decision is 1).

        Args:
            None

        Returns:
            dict: in_position, share_count, last_exit_session, last_exit_reason, last_exit_fill_price, cash_session_count
        """
        # PREVIEW THE INCREMENT THE CASH DECISION WILL APPLY
        cash_session_count = int(self.cash_session_count_int)
        if (not self.invested_bool) and self.episode_dict is not None:
            cash_session_count += 1
        return {"in_position": bool(self.invested_bool), "share_count": int(self.share_count_int),
                "last_exit_session": self.last_exit_session, "last_exit_reason": self.last_exit_reason_str,
                "last_exit_fill_price": getattr(self, "last_exit_fill_price", None),
                "cash_session_count": int(cash_session_count)}

    # FUNCTION: TRADES, EPISODES, MARKS AND METRICS
    def get_result_dict(self):
        """
        Args:
            None

        Returns:
            dict: trade_pdf, episode_pdf, daily_equity_pdf, metric_dict
        """
        # AN OPEN CASH EPISODE IS REPORTED AS WINDOW_END (SAME AS THE OLD SIMULATOR). READ-ONLY: THE RUNNER CALLS THIS
        # AT EVERY PERIOD END OF A STREAM, SO THE OPEN EPISODE MUST STAY OPEN IN THE ENGINE
        episode_dict_list = list(self.episode_dict_list)
        if self.episode_dict is not None:
            open_episode_dict = dict(self.episode_dict)
            open_episode_dict.update({"reentry_ts": self._window_end_ts, "reentry_fill_price": self._window_end_close_float,
                                      "reentry_reason": "window_end"})
            episode_dict_list.append(open_episode_dict)
        trade_pdf = pd.DataFrame(self.transaction_dict_list)
        episode_pdf = pd.DataFrame(episode_dict_list)
        daily_equity_pdf = pd.DataFrame(self.equity_dict_list)
        if not episode_pdf.empty and "exit_fill_price" in episode_pdf.columns and "reentry_fill_price" in episode_pdf.columns:
            episode_pdf["share_gain_pct"] = episode_pdf["exit_fill_price"] / episode_pdf["reentry_fill_price"] - 1
        metric_dict = get_stop_reentry_metric_dict(trade_pdf, episode_pdf, daily_equity_pdf, self.initial_capital_float) if not daily_equity_pdf.empty else {}
        return {"trade_pdf": trade_pdf, "episode_pdf": episode_pdf, "daily_equity_pdf": daily_equity_pdf,
                "metric_dict": metric_dict}


"""
Barrier Trades
"""


# FUNCTION: BARRIER ENGINE (SAME RULES AS so.core.trade_execution / backtest_simulation)
class BarrierEngine(Engine):
    """
    One position at a time. A buy decision enters at the fill-bar open. Take-profit, stop-loss and time-limit follow
    resolve_barrier_exit_dict (same-bar: SL wins). Daily mode fills at 15:59; minute mode (4b-2b) will call the same
    bar loop with minute-level decisions.
    """

    # FUNCTION: STORE COSTS AND THE EMPTY ACCOUNT
    def __init__(self, max_hold_trading_days_in=config.MAX_HOLD_TRADING_DAYS, rr_ratio_in=config.RR_RATIO,
                 initial_capital_in=config.INITIAL_CAPITAL, entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                 market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                 limit_exit_slippage_in=config.LIMIT_EXIT_SLIPPAGE_PER_SHARE):
        """
        Args:
            max_hold_trading_days_in (int): Holding window in trading days (entry day = day 1)
            rr_ratio_in (float): SL distance / TP distance when the decision carries delta
            initial_capital_in, entry_slippage_in, market_exit_slippage_in, limit_exit_slippage_in (float): Costs
        """
        # COSTS AND THE ACCOUNT
        self.max_hold_trading_days_int = int(max_hold_trading_days_in)
        self.rr_ratio_float = float(rr_ratio_in)
        self.initial_capital_float = float(initial_capital_in)
        self.entry_slippage_float = float(entry_slippage_in)
        self.market_exit_slippage_float = float(market_exit_slippage_in)
        self.limit_exit_slippage_float = float(limit_exit_slippage_in)
        self.tp_through_float = float(config.TP_THROUGH_TICKS * config.PRICE_TICK)
        self.cash_float = float(initial_capital_in)
        self.invested_bool = False
        self.share_count_int = 0
        self.entry_idx_int = -1
        self.buy_fill_float = np.nan
        self.buy_fee_float = 0.0
        self.buy_raw_price_float = np.nan
        self.buy_ts = pd.NaT
        self.decision_ts = pd.NaT
        self.delta_float = np.nan
        self.stop_loss_float = np.nan
        self.take_profit_float = np.nan
        self.horizon_end_idx_int = -1
        self.horizon_complete_bool = False
        self.entry_session_idx_int = -1
        self.skipped_decision_count_int = 0
        self.last_exit_session = None
        self.last_exit_reason_str = None
        self.session_end_idx_arr = None
        self.bar_count_int = 0
        self.transaction_dict_list = []
        self.equity_dict_list = []

    # FUNCTION: STORE SESSION ENDS FOR THE HOLDING WINDOW
    def set_session_bounds(self, session_end_idx_arr_in, bar_count_in):
        """
        Args:
            session_end_idx_arr_in (np.ndarray): Last bar of every session
            bar_count_in (int): Number of bars

        Returns:
            None
        """
        # THE HORIZON IS COUNTED IN SESSIONS PRESENT IN THE DATA
        self.session_end_idx_arr = np.asarray(session_end_idx_arr_in, dtype=np.int64)
        self.bar_count_int = int(bar_count_in)

    # FUNCTION: START IN CASH UNLESS A STARTING WEIGHT IS ASKED
    def open_window(self, fill_event_dict_in, initial_weight_in):
        """
        Barrier matching simulate_decision_trading_dict starts in cash (initial_weight 0). A positive weight buys
        without barriers, which is not used by the exact-match tests.

        Args:
            fill_event_dict_in (dict): First allowed open
            initial_weight_in (float): Weight bought at the window start

        Returns:
            None
        """
        # THE OLD SIMULATOR NEVER BUYS AT THE WINDOW START
        if float(initial_weight_in) <= 0:
            return
        self._enter(fill_event_dict_in, {"target_weight": float(initial_weight_in), "delta": None,
                                         "stop_price": None, "take_profit_price": None}, fill_event_dict_in.get("decision_ts", pd.NaT))

    # FUNCTION: ENTER AT THE FILL WHEN FLAT AND THE DECISION IS A BUY
    def apply_decision(self, fill_event_dict_in, decision_dict_in, decision_close_in):
        """
        A buy is target_weight > 0, or a finite delta, or both barrier prices. Buys while a position is open are
        skipped. flatten_bool is ignored (the old simulator has no flatten).

        Args:
            fill_event_dict_in (dict): Fill bar
            decision_dict_in (dict): Output of get_decision_dict
            decision_close_in (float): Unused

        Returns:
            None
        """
        # A BUY REQUEST WHILE INVESTED IS SKIPPED
        buy_bool = get_barrier_buy_bool(decision_dict_in)
        if self.invested_bool:
            if buy_bool:
                self.skipped_decision_count_int += 1
            return
        if not buy_bool:
            return
        self._enter(fill_event_dict_in, decision_dict_in, fill_event_dict_in.get("decision_ts", fill_event_dict_in["timestamp"]))

    # FUNCTION: OPEN A POSITION AT THE FILL OPEN
    def _enter(self, fill_event_dict_in, decision_dict_in, decision_ts_in):
        """
        Args:
            fill_event_dict_in (dict): Fill bar
            decision_dict_in (dict): Decision
            decision_ts_in: Decision timestamp

        Returns:
            None
        """
        # ENTRY FILL AND SHARE COUNT
        raw_price = float(fill_event_dict_in["raw_price"])
        fill_price = raw_price + self.entry_slippage_float
        share_count = get_affordable_share_count(self.cash_float, fill_price)
        if share_count <= 0:
            return
        buy_fee = calculate_side_fee(share_count, fill_price)
        self.cash_float -= share_count * fill_price + buy_fee
        self.invested_bool = True
        self.share_count_int = int(share_count)
        self.entry_idx_int = int(fill_event_dict_in["bar_idx"])
        self.buy_fill_float = float(fill_price)
        self.buy_fee_float = float(buy_fee)
        self.buy_raw_price_float = float(raw_price)
        self.buy_ts = fill_event_dict_in["timestamp"]
        self.decision_ts = decision_ts_in
        self.delta_float = get_finite_or_nan_float(decision_dict_in.get("delta"))
        stop_price = get_optional_float(decision_dict_in.get("stop_price"))
        take_profit_price = get_optional_float(decision_dict_in.get("take_profit_price"))
        if stop_price is not None and take_profit_price is not None:
            self.stop_loss_float = float(stop_price)
            self.take_profit_float = float(take_profit_price)
        else:
            delta_float = 0.0 if not np.isfinite(self.delta_float) else float(self.delta_float)
            barrier_dict = get_barrier_price_dict(raw_price, [delta_float], self.rr_ratio_float)
            self.stop_loss_float = float(barrier_dict["stop_loss_arr"][0])
            self.take_profit_float = float(barrier_dict["take_profit_arr"][0])
        session_idx = int(fill_event_dict_in.get("session_idx", 0))
        self.entry_session_idx_int = session_idx
        self._set_horizon(session_idx)

    # FUNCTION: LAST BAR OF THE HOLDING WINDOW
    def _set_horizon(self, entry_session_idx_in):
        """
        Args:
            entry_session_idx_in (int): Session of the entry bar

        Returns:
            None
        """
        # SAME WINDOW AS get_horizon_window_dict
        end_session_idx = int(entry_session_idx_in) + self.max_hold_trading_days_int - 1
        if self.session_end_idx_arr is not None and end_session_idx < len(self.session_end_idx_arr):
            self.horizon_end_idx_int = int(self.session_end_idx_arr[end_session_idx])
            self.horizon_complete_bool = True
        else:
            self.horizon_end_idx_int = int(self.bar_count_int) - 1 if self.bar_count_int > 0 else -1
            self.horizon_complete_bool = False

    # FUNCTION: CHECK BARRIERS ON A RANGE OF BARS
    def process_bars(self, bar_event_dict_in):
        """
        Args:
            bar_event_dict_in (dict): One session range

        Returns:
            None
        """
        # NOTHING TO CHECK
        if not self.invested_bool:
            return
        bar_idx_arr = np.asarray(bar_event_dict_in["bar_idx_arr"], dtype=np.int64)
        if len(bar_idx_arr) == 0:
            return
        start_offset = 0
        while start_offset < len(bar_idx_arr) and int(bar_idx_arr[start_offset]) <= self.entry_idx_int:
            start_offset += 1
        end_offset = len(bar_idx_arr) - 1
        while end_offset >= start_offset and int(bar_idx_arr[end_offset]) > self.horizon_end_idx_int:
            end_offset -= 1
        if start_offset > end_offset:
            return
        open_arr = np.asarray(bar_event_dict_in["open_arr"], dtype=np.float64)[start_offset:end_offset + 1]
        high_arr = np.asarray(bar_event_dict_in["high_arr"], dtype=np.float64)[start_offset:end_offset + 1]
        low_arr = np.asarray(bar_event_dict_in["low_arr"], dtype=np.float64)[start_offset:end_offset + 1]
        close_arr = np.asarray(bar_event_dict_in["close_arr"], dtype=np.float64)[start_offset:end_offset + 1]
        last_bar_idx = int(bar_idx_arr[end_offset])
        horizon_complete_int = 1 if (self.horizon_complete_bool and last_bar_idx >= self.horizon_end_idx_int) else 0
        hit_offset, raw_price, reason_int = get_barrier_exit_tuple(
            open_arr, high_arr, low_arr, close_arr, float(self.stop_loss_float), float(self.take_profit_float),
            float(self.tp_through_float), int(horizon_complete_int))
        if int(reason_int) == 0:
            return
        reason_str = {REASON_STOP_INT: config.EXIT_REASON_SL, REASON_TP_INT: config.EXIT_REASON_TP,
                      REASON_TL_INT: config.EXIT_REASON_TL}.get(int(reason_int), config.EXIT_REASON_END)
        timestamp_index = bar_event_dict_in["timestamp_index"]
        bar_idx = int(bar_idx_arr[start_offset + int(hit_offset)])
        self._exit(bar_idx, timestamp_index[start_offset + int(hit_offset)], float(raw_price), reason_str,
                   session_date_in=bar_event_dict_in.get("session_date"))

    # FUNCTION: CLOSE THE POSITION AT A RAW PRICE
    def _exit(self, bar_idx_in, timestamp_in, raw_price_in, reason_str_in, session_date_in=None):
        """
        Args:
            bar_idx_in (int): Exit bar
            timestamp_in: Exit timestamp
            raw_price_in (float): Raw exit price
            reason_str_in (str): SL, TP, TL, END
            session_date_in: Session of the exit

        Returns:
            None
        """
        # SLIPPAGE FOLLOWS THE EXIT REASON
        raw_price = float(raw_price_in)
        slippage = float(get_exit_slippage_arr([reason_str_in], self.market_exit_slippage_float, self.limit_exit_slippage_float)[0])
        fill_price = raw_price - slippage
        sell_fee = calculate_side_fee(self.share_count_int, fill_price)
        net_profit = self.share_count_int * (fill_price - self.buy_fill_float) - self.buy_fee_float - sell_fee
        cash_before = self.cash_float + self.share_count_int * self.buy_fill_float + self.buy_fee_float
        self.cash_float += self.share_count_int * fill_price - sell_fee
        self.transaction_dict_list.append({
            "transaction_id": len(self.transaction_dict_list),
            "decision_ts": self.decision_ts,
            "buy_ts": self.buy_ts,
            "buy_open_price": self.buy_raw_price_float,
            "buy_fill_price": round(self.buy_fill_float, 6),
            "share_count": self.share_count_int,
            "delta": self.delta_float,
            "SL_price": float(self.stop_loss_float),
            "TP_price": float(self.take_profit_float),
            "sell_ts": timestamp_in,
            "sell_raw_price": round(raw_price, 6),
            "sell_fill_price": round(fill_price, 6),
            "exit_reason": str(reason_str_in),
            "buy_fee": self.buy_fee_float,
            "sell_fee": sell_fee,
            "net_profit": round(net_profit, 6),
            "net_profit_pct": round(net_profit / cash_before, 8) if cash_before else np.nan,
            "result": get_trade_result_str(net_profit),
            "hold_bar_count": int(bar_idx_in) - self.entry_idx_int,
            "buy_idx": self.entry_idx_int,
            "sell_idx": int(bar_idx_in),
            "equity_after": round(self.cash_float, 6),
        })
        self.invested_bool = False
        self.share_count_int = 0
        self.entry_idx_int = -1
        self.buy_fill_float = np.nan
        self.buy_fee_float = 0.0
        if session_date_in is not None:
            self.last_exit_session = session_date_in
        self.last_exit_reason_str = str(reason_str_in)

    # FUNCTION: MARK TO MARKET
    def close_session(self, mark_event_dict_in):
        """
        Args:
            mark_event_dict_in (dict): session_date, close

        Returns:
            None
        """
        # CASH PLUS MARKED SHARES
        close_price = float(mark_event_dict_in["close"])
        equity = self.cash_float + self.share_count_int * close_price
        self.equity_dict_list.append({"date": mark_event_dict_in["session_date"], "equity": round(equity, 6),
                                      "in_position": self.share_count_int > 0,
                                      "weight": 1.0 if self.share_count_int > 0 and equity > 0 else 0.0})

    # FUNCTION: SELL AT THE LAST CLOSE IF STILL OPEN
    def close_window(self, fill_event_dict_in):
        """
        Args:
            fill_event_dict_in (dict): Last close

        Returns:
            None
        """
        # UNRESOLVED POSITIONS CLOSE AS END
        if not self.invested_bool:
            return
        self._exit(int(fill_event_dict_in["bar_idx"]), fill_event_dict_in["timestamp"],
                   float(fill_event_dict_in["raw_price"]), config.EXIT_REASON_END,
                   session_date_in=fill_event_dict_in.get("session_date"))

    # FUNCTION: READ-ONLY ACCOUNT SNAPSHOT
    def get_state_dict(self):
        """
        Args:
            None

        Returns:
            dict: in_position, share_count, last_exit_session, last_exit_reason, last_exit_fill_price, cash_session_count
        """
        # BARRIER HAS NO CASH-SESSION COUNTER
        return {"in_position": bool(self.invested_bool), "share_count": int(self.share_count_int),
                "last_exit_session": self.last_exit_session, "last_exit_reason": self.last_exit_reason_str,
                "last_exit_fill_price": None, "cash_session_count": 0}

    # FUNCTION: TRADES, MARKS AND METRICS
    def get_result_dict(self):
        """
        Args:
            None

        Returns:
            dict: trade_pdf, daily_equity_pdf, metric_dict, skipped_decision_count
        """
        # THE SAME MARKS THE OLD DAILY EQUITY HELPER WOULD BUILD
        trade_pdf = pd.DataFrame(self.transaction_dict_list)
        daily_equity_pdf = pd.DataFrame(self.equity_dict_list)
        if daily_equity_pdf.empty:
            return {"trade_pdf": trade_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": {},
                    "skipped_decision_count": int(self.skipped_decision_count_int)}
        final_equity = float(daily_equity_pdf["equity"].iloc[-1])
        exit_reason_series = trade_pdf["exit_reason"] if not trade_pdf.empty else pd.Series(dtype=object)
        metric_dict = {"total_return": round(final_equity / self.initial_capital_float - 1, 8),
                       "sharpe_ratio": get_sharpe_ratio(daily_equity_pdf, self.initial_capital_float),
                       "max_drawdown": get_max_drawdown(daily_equity_pdf, self.initial_capital_float),
                       "final_equity": round(final_equity, 6),
                       "trade_count": int(len(trade_pdf)),
                       "tp_count": int((exit_reason_series == config.EXIT_REASON_TP).sum()),
                       "sl_count": int((exit_reason_series == config.EXIT_REASON_SL).sum()),
                       "tl_count": int((exit_reason_series == config.EXIT_REASON_TL).sum()),
                       "skipped_decision_count": int(self.skipped_decision_count_int)}
        return {"trade_pdf": trade_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": metric_dict,
                "skipped_decision_count": int(self.skipped_decision_count_int)}


# FUNCTION: WHETHER A DECISION IS A BARRIER BUY
def get_barrier_buy_bool(decision_dict_in):
    """
    Args:
        decision_dict_in (dict): Output of get_decision_dict

    Returns:
        bool: True when the decision asks to enter
    """
    # TARGET WEIGHT, DELTA, OR BOTH BARRIER PRICES
    target_weight = decision_dict_in.get("target_weight", np.nan)
    if np.isfinite(target_weight) and float(target_weight) > 0.0:
        return True
    delta_float = decision_dict_in.get("delta")
    if delta_float is not None and np.isfinite(float(delta_float)):
        return True
    stop_price = decision_dict_in.get("stop_price")
    take_profit_price = decision_dict_in.get("take_profit_price")
    return stop_price is not None and take_profit_price is not None
