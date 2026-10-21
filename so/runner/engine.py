import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL)
from so import config
# IMPORT TRADE EXECUTION FUNCTIONS (FEES AND SHARE COUNT)
from so.core.trade_execution import calculate_side_fee, get_affordable_share_count
# IMPORT PERFORMANCE METRICS
from so.core.performance_metrics import get_sharpe_ratio, get_max_drawdown

"""
Engine Interface (infrastructure step 4a)

The design decides. The position engine turns decisions into trades. Anything that needs memory across minutes
(being in a position, the entry price, a trailing high, take-profit and stop-loss) lives here, not in design code.
An engine sees the fill or mark it is given and its own state only.

    open_window      buy initial_weight at the first 10:00 open
    apply_decision   rebalance at the 15:59 fill (daily mode)
    process_bar      no-op in 4a; 4b barrier and trailing-stop engines fill intra-session stops here
    close_session    mark cash + shares x session close
    close_window     sell everything at the last close
    get_result_dict  trades, daily equity, metrics

A fill event has bar_idx, timestamp, raw_price (the open, except END which is the close). A mark event has
session_date and close. A bar event (4b) has bar_idx, timestamp, open, high, low, close.

4a ports fractional weight from so.core.fractional_exposure and must reproduce it exactly. 4b ports barrier trades
from so.core.trade_execution / so.core.backtest_simulation, and trailing stop and re-entry from
so.core.reentry_simulation. A float decision is target_weight. NaN or a missing weight means keep.
stop_price, take_profit_price, trail_multiple and flatten_bool are reserved for 4b and are ignored here.
"""

# KEYS A DECISION MAY CARRY (4B FIELDS ARE IGNORED BY THE FRACTIONAL ENGINE)
DECISION_KEY_LIST = ["target_weight", "stop_price", "take_profit_price", "trail_multiple", "flatten_bool"]

# FUNCTION: NORMALIZE A DESIGN RETURN TO A DECISION DICT
def get_decision_dict(decision_in):
    """
    A float is target_weight. None or a missing weight is NaN (keep). 4b fields default to None / False.

    Args:
        decision_in (float | dict | None): Design return

    Returns:
        dict: target_weight, stop_price, take_profit_price, trail_multiple, flatten_bool
    """
    # A BARE NUMBER IS THE DAILY TARGET WEIGHT
    if decision_in is None:
        return {"target_weight": np.nan, "stop_price": None, "take_profit_price": None, "trail_multiple": None, "flatten_bool": False}
    if isinstance(decision_in, (int, float, np.integer, np.floating)):
        return {"target_weight": float(decision_in), "stop_price": None, "take_profit_price": None, "trail_multiple": None, "flatten_bool": False}
    # A DICT KEEPS UNKNOWN KEYS OUT; MISSING WEIGHT MEANS KEEP
    decision_dict = dict(decision_in)
    target_weight = decision_dict.get("target_weight", np.nan)
    target_weight = np.nan if target_weight is None else float(target_weight)
    return {"target_weight": target_weight,
            "stop_price": decision_dict.get("stop_price"),
            "take_profit_price": decision_dict.get("take_profit_price"),
            "trail_multiple": decision_dict.get("trail_multiple"),
            "flatten_bool": bool(decision_dict.get("flatten_bool", False))}


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
        No-op in 4a. A barrier or trailing-stop engine fills intra-session exits here.

        Args:
            bar_event_dict_in (dict): bar_idx, timestamp, open, high, low, close

        Returns:
            None
        """
        # DAILY MODE DOES NOT CALL THIS
        return None

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
