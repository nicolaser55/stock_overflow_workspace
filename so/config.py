"""
Stock Overflow (SO) Shared Configuration

Every constant shared by the data pipeline (steps 00-06) and by more than one experiment lives here: price-action,
indicator and context feature constants, the execution and cost rules, the simulation constants, the statistics
constants, the walk-forward conventions, the research discipline dates and the daily feature definitions.

Experiment-specific constants (sampling, model, grids, selection, baselines) live in each experiment's own config.py
(experiments/expNN_<name>/config.py). The configuration hash of a trial covers BOTH files (so.core.trial_log).

Conventions:
    - Windows and orders are counted in BARS (rows), not in clock minutes, unless the name says SESSIONS or MONTHS.
    - Prices and price deltas are in US dollars unless the name ends with "_PCT" (fraction, 0.01 = 1%).
    - Changing a value here changes the meaning of every cached dataset that was generated with the old value
      (steps 01-05 caches). Regenerate the affected steps (see pipeline/README.md) and start new experiment versions.
"""

"""
Price Action (PA) Constants (step01 / add_PA_cols)
"""

# DEFINE THE AVERAGE TRUE RANGE (ATR) PERIOD (bars)
PA_ATR_PERIOD = 10
# DEFINE THE SMOOTH PRICE ROLLING WINDOW (bars, shifted forward by window - 3)
PA_SMOOTH_WINDOW = 4
# DEFINE THE EXTREMA ORDER (bars on each side of a candidate swing)
PA_EXTREMA_ORDER = 3
# DEFINE THE COMPOSITE PRICE BIAS (weight of smooth_price, the remainder goes to extremas_pp; chosen visually)
PA_COMPOSITE_BIAS = 0.4
# DEFINE THE TREND SLOPE LIMIT (dollars per bar; NOTE: absolute dollars, to be revisited with scaling)
PA_TREND_SLOPE_LIMIT = 0.01

"""
Indicator Constants (step02 TSIND / tf_ohlcv_tools.py)
"""

# DEFINE THE STOCHASTIC OSCILLATOR WINDOWS (bars)
STOCH_K_WINDOW = 14
STOCH_D_WINDOW = 3
# DEFINE THE MACD EXPONENTIAL MOVING AVERAGE SPANS (bars)
MACD_FAST_SPAN = 12
MACD_SLOW_SPAN = 26
MACD_SIGNAL_SPAN = 9
# DEFINE THE RSI WINDOW (bars, simple moving average RSI)
RSI_WINDOW = 14
# DEFINE THE BOLLINGER BANDS WINDOW (bars) AND STANDARD DEVIATION MULTIPLIER
BB_WINDOW = 20
BB_STD_MULTIPLIER = 2
# DEFINE THE DONCHIAN CHANNEL WINDOW (bars)
DC_WINDOW = 20

"""
Context Feature Constants (step04 / context_features.py)
"""

# DEFINE THE NUMBER OF PRIOR SESSIONS USED FOR THE DAILY VOLATILITY FEATURE
CTX_DAILY_VOLATILITY_SESSIONS = 20
# DEFINE THE NUMBER OF PRIOR SESSIONS USED FOR THE RELATIVE VOLUME FEATURE (same minute of the day)
CTX_RELATIVE_VOLUME_SESSIONS = 20
# DEFINE THE MINIMUM NUMBER OF PRIOR SESSIONS REQUIRED BEFORE THE RELATIVE VOLUME IS DEFINED
CTX_RELATIVE_VOLUME_MIN_SESSIONS = 5

"""
Trading Window Constants
"""

# DEFINE THE DELAY AFTER THE MARKET OPEN BEFORE THE FIRST ENTRY IS ALLOWED (minutes; 30 -> first entry at the 10:00 open)
TRADING_START_DELAY_MINUTES = 30
# DEFINE THE DECISION TO ENTRY OFFSET (bars; the feature row at t is paired with the entry at the open of bar t+1)
DECISION_TO_ENTRY_BAR_OFFSET = 1

"""
Barrier Target Constants (step05 / barrier_labels.py)
"""

# DEFINE THE TRAINING DELTA LIST (log-spaced from 0.10% to 1.00%)
TRAIN_DELTA_LIST = [round(0.001 * 10**(k / 20), 4) for k in range(21)]
# DEFINE THE FULL DELTA LIST (diagnostic deltas below and above the training deltas)
FULL_DELTA_LIST = [
    0.0005, 0.0006, 0.0007, 0.0008, 0.0009,                     # diagnostic (5 pts)
    0.0010, 0.0011, 0.0013, 0.0014, 0.0016, 0.0018, 0.0020,     # TRAIN
    0.0022, 0.0025, 0.0028, 0.0032, 0.0035, 0.0040, 0.0045,     # TRAIN
    0.0050, 0.0056, 0.0063, 0.0071, 0.0079, 0.0089, 0.0100,     # TRAIN (21 pts)
    0.0112, 0.0126, 0.0141, 0.0158, 0.0178, 0.0200,             # diagnostic (6 pts)
]
# DEFINE THE RISK REWARD RATIO (SL distance = delta * RR_RATIO; 1 means symmetric SL and TP)
RR_RATIO = 1.0
# DEFINE THE NUMBER OF DECIMALS USED TO ROUND THE STOP LOSS AND TAKE PROFIT PRICES (kept from the step12 target code of the previous workspace)
SLTP_PRICE_DECIMALS = 3
# DEFINE THE MAXIMUM HOLDING PERIOD (trading days, the entry day counts as day 1; exit at the close of the last bar of the last day)
MAX_HOLD_TRADING_DAYS = 10
# DEFINE THE PRICE TICK (dollars)
PRICE_TICK = 0.01
# DEFINE THE NUMBER OF TICKS THE PRICE MUST TRADE THROUGH A TAKE PROFIT LIMIT BEFORE IT COUNTS AS FILLED
TP_THROUGH_TICKS = 1
# DEFINE THE EXIT REASON STRINGS
EXIT_REASON_TP = "TP"           # take profit filled
EXIT_REASON_SL = "SL"           # stop loss filled
EXIT_REASON_TL = "TL"           # time limit reached (sold at the close of the last bar of the last holding day)
EXIT_REASON_NA = "NA"           # unresolved (the data ends before the holding period ends) -> excluded from labels
EXIT_REASON_END = "END"         # simulator only: position closed at the last available bar because the data ended
# DEFINE THE TRADE RESULT STRINGS (based on the net profit after costs)
RESULT_WIN = "WIN"
RESULT_LOSS = "LOSS"
RESULT_NULL = "NULL"
# DEFINE THE ABSOLUTE NET PROFIT BELOW WHICH A TRADE IS LABELED NULL (dollars)
RESULT_NULL_TOLERANCE = 0.005

"""
Execution Cost Constants
"""

# DEFINE THE ENTRY SLIPPAGE (dollars per share added to the open price; covers spread and slippage)
ENTRY_SLIPPAGE_PER_SHARE = 0.01
# DEFINE THE MARKET EXIT SLIPPAGE (dollars per share subtracted on stop loss and time limit exits)
MARKET_EXIT_SLIPPAGE_PER_SHARE = 0.01
# DEFINE THE LIMIT EXIT SLIPPAGE (dollars per share subtracted on take profit exits)
LIMIT_EXIT_SLIPPAGE_PER_SHARE = 0.0
# DEFINE THE IBKR FIXED FEE STRUCTURE (applied per side: buy and sell are separate orders)
FEE_PER_SHARE_PER_SIDE = 0.005
FEE_MINIMUM_PER_SIDE = 1.0
FEE_MAXIMUM_PCT_PER_SIDE = 0.01
# DEFINE THE SLIPPAGE SENSITIVITY LIST (dollars per share applied to entry and market exits)
COST_SENSITIVITY_SLIPPAGE_LIST = [0.00, 0.01, 0.02]

"""
Simulation Constants
"""

# DEFINE THE INITIAL CAPITAL (dollars; the account compounds, the absolute size is not important yet)
INITIAL_CAPITAL = 100_000.0
# DEFINE THE INTEREST EARNED ON IDLE CASH (annual fraction; decided: no interest)
CASH_INTEREST_RATE = 0.0
# DEFINE THE NUMBER OF TRADING DAYS PER YEAR (Sharpe ratio annualization)
TRADING_DAYS_PER_YEAR = 252


"""
Statistics Constants (bootstrap intervals, random seed)
"""

# DEFINE THE NUMBER OF BOOTSTRAP ITERATIONS
BOOTSTRAP_ITERATION_COUNT = 1000
# DEFINE THE TWO-SIDED CONFIDENCE LEVEL OF EVERY INTERVAL
CONFIDENCE_LEVEL = 0.95
# DEFINE THE RANDOM SEED
RANDOM_SEED = 42
# DEFINE THE MINIMUM DETECTABLE EFFECT FACTOR (z 0.975 + z 0.80 = 1.96 + 0.84: TWO-SIDED 5% TEST WITH 80% POWER)
MDE_Z_FACTOR = 2.8

"""
Walk-Forward Conventions (so.core.schedule; the embargo and the training windows are set per experiment)
"""

# DEFINE THE TEST AND VALIDATION WINDOW LENGTHS (calendar months)
TEST_WINDOW_MONTHS = 3
VALIDATION_WINDOW_MONTHS = 3
# DEFINE THE WALK-FORWARD STEP (calendar months between consecutive test windows)
WALK_FORWARD_STEP_MONTHS = 3
# DEFINE WHETHER A FOLD REQUIRES EVERY TRAINING WINDOW CANDIDATE TO FIT INSIDE THE DATA
WALK_FORWARD_REQUIRE_ALL_TRAIN_WINDOWS = True

"""
Research Discipline
"""

# DEFINE THE EXPLORATION PERIOD (TRAINING DATA OF EVERY FOLD; NEVER EXTEND IT INTO THE WALK-FORWARD PERIOD)
EXPLORATION_START_DATE_STR = "2005-01-03"
EXPLORATION_END_DATE_STR = "2014-12-31"
# DEFINE THE DATA CUTOFF OF EXPLORATION NOTEBOOKS (END OF THE FIRST FOLD'S TRAINING WINDOW: NO FORWARD VALUE REACHES PAST IT)
EXPLORATION_DATA_CUTOFF_DATE_STR = "2015-03-18"

"""
Daily Feature Constants (step06 TSDAY / so.features.daily_features; used by exp02, exp03 and later daily experiments)
"""

# DEFINE THE DECISION BAR OFFSET FROM THE LAST BAR OF THE SESSION (1 = 15:58 on a full day, the second-to-last bar on half days)
DECISION_BAR_OFFSET_FROM_END = 1
# NOTE: THE FILL IS THE OPEN OF THE BAR AFTER THE DECISION BAR (THE LAST BAR OF THE SESSION, 15:59)
# DEFINE THE NUMBER OF PRIOR SESSIONS USED FOR THE DAILY VOLATILITY (SAME DEFINITION AS TSCTX daily_volatility)
DAILY_VOLATILITY_SESSIONS = CTX_DAILY_VOLATILITY_SESSIONS
# DEFINE THE LONG VOLATILITY WINDOW (VOLATILITY RATIO = 20-SESSION / 60-SESSION)
LONG_VOLATILITY_SESSIONS = 60
# DEFINE THE PAST RETURN LOOKBACKS (SESSIONS)
PAST_RETURN_SESSION_LIST = [5, 20, 60, 120, 250]
# DEFINE THE MOVING AVERAGE WINDOWS (SESSIONS)
MOVING_AVERAGE_SESSION_LIST = [50, 200]
# DEFINE THE ROLLING HIGH WINDOWS (SESSIONS): DISTANCE FROM THE HIGH AND SESSIONS SINCE THE HIGH
ROLLING_HIGH_SESSION_LIST = [60, 250]
# DEFINE THE FORWARD LABEL HORIZON OF THE DAILY TABLE (SESSIONS)
LABEL_HORIZON_SESSIONS = 20
# DEFINE THE DAILY FEATURES (ALL SCALE-FREE; SEE so.features.daily_features.get_daily_feature_pdf FOR THE DEFINITIONS)
DAILY_FEATURE_COL_STR_LIST = [
    "prev_day_return_pct", "prev_day_range_pct", "intraday_return_pct", "daily_volatility", "ath_drawdown_pct",
    "return_5d", "return_20d", "return_60d", "return_120d", "return_250d",
    "ma50_dist_pct", "ma200_dist_pct", "volatility_ratio_20_60",
    "high250_dist_pct", "high60_dist_pct", "sessions_since_high60",
]

"""
Feature Registry

scale_type:
    absolute    - dollars or shares; scale grows with the price level (excluded from the model until scaling is designed)
    ratio       - unitless fraction or ratio (comparable across years)
    bounded     - fixed range indicator (0-1 or 0-100)
    categorical - discrete labels
    count       - counters (bars, swings, segments)
    time        - time-of-day / calendar position
"""

# DEFINE THE CATEGORY LEVELS FOR CATEGORICAL FEATURES (fixed so that codes are identical in every fold)
CATEGORY_LEVEL_DICT = {
    "trend": [-1.0, 0.0, 1.0],
    "color": [-1, 1],
    "ms_minima_trend": ["bearish", "bullish"],
    "ms_maxima_trend": ["bearish", "bullish"],
    "ms_low_status": ["bearish_BOS", "bearish_CHOCH"],
    "ms_high_status": ["bullish_BOS", "bullish_CHOCH"],
    "ms_trend": ["bearish", "bullish"],
    "day_of_week": [0, 1, 2, 3, 4],
}

# DEFINE THE FEATURE REGISTRY (column -> source step and scale type)
FEATURE_REGISTRY_DICT = {
    # TSIND (step02): RAW BAR
    "open": {"source": "TSIND", "scale_type": "absolute"},
    "high": {"source": "TSIND", "scale_type": "absolute"},
    "low": {"source": "TSIND", "scale_type": "absolute"},
    "close": {"source": "TSIND", "scale_type": "absolute"},
    "volume": {"source": "TSIND", "scale_type": "absolute"},
    "avg_price": {"source": "TSIND", "scale_type": "absolute"},
    # TSIND (step02): PRICE ACTION
    "smooth_price": {"source": "TSIND", "scale_type": "absolute"},
    "extremas_pp": {"source": "TSIND", "scale_type": "absolute"},
    "composite_price": {"source": "TSIND", "scale_type": "absolute"},
    "composite_price_slope": {"source": "TSIND", "scale_type": "absolute"},
    "trend": {"source": "TSIND", "scale_type": "categorical"},
    "segment": {"source": "TSIND", "scale_type": "count"},
    # TSIND (step02): CANDLESTICK
    "atr": {"source": "TSIND", "scale_type": "absolute"},
    "color": {"source": "TSIND", "scale_type": "categorical"},
    "span": {"source": "TSIND", "scale_type": "absolute"},
    "body_span": {"source": "TSIND", "scale_type": "absolute"},
    "bot_wick_pct": {"source": "TSIND", "scale_type": "bounded"},
    "body_pct": {"source": "TSIND", "scale_type": "bounded"},
    "top_wick_pct": {"source": "TSIND", "scale_type": "bounded"},
    # TSIND (step02): OSCILLATORS
    "stoch_k": {"source": "TSIND", "scale_type": "bounded"},
    "stoch_d": {"source": "TSIND", "scale_type": "bounded"},
    "macd": {"source": "TSIND", "scale_type": "absolute"},
    "signal": {"source": "TSIND", "scale_type": "absolute"},
    "histogram": {"source": "TSIND", "scale_type": "absolute"},
    "rsi": {"source": "TSIND", "scale_type": "bounded"},
    # TSIND (step02): BOLLINGER BANDS
    "bb_width": {"source": "TSIND", "scale_type": "absolute"},
    "bb_bot": {"source": "TSIND", "scale_type": "absolute"},
    "bb_mid": {"source": "TSIND", "scale_type": "absolute"},
    "bb_top": {"source": "TSIND", "scale_type": "absolute"},
    "bb_pct": {"source": "TSIND", "scale_type": "ratio"},
    # TSIND (step02): DONCHIAN CHANNEL
    "dc_width": {"source": "TSIND", "scale_type": "absolute"},
    "dc_bot": {"source": "TSIND", "scale_type": "absolute"},
    "dc_mid": {"source": "TSIND", "scale_type": "absolute"},
    "dc_top": {"source": "TSIND", "scale_type": "absolute"},
    "dc_pct": {"source": "TSIND", "scale_type": "bounded"},
    # TSIND (step02): MARKET STRUCTURE
    "current_minima": {"source": "TSIND", "scale_type": "absolute"},
    "current_maxima": {"source": "TSIND", "scale_type": "absolute"},
    "ms_minima_trend": {"source": "TSIND", "scale_type": "categorical"},
    "ms_maxima_trend": {"source": "TSIND", "scale_type": "categorical"},
    "ms_low_status": {"source": "TSIND", "scale_type": "categorical"},
    "ms_high_status": {"source": "TSIND", "scale_type": "categorical"},
    "ms_trend": {"source": "TSIND", "scale_type": "categorical"},
    # TSSEG (step03)
    "cum_max": {"source": "TSSEG", "scale_type": "absolute"},
    "minima_count": {"source": "TSSEG", "scale_type": "count"},
    "maxima_count": {"source": "TSSEG", "scale_type": "count"},
    "prev_seg_delta": {"source": "TSSEG", "scale_type": "absolute"},
    "prev_seg_delta_pct": {"source": "TSSEG", "scale_type": "ratio"},
    "seg_cs_count": {"source": "TSSEG", "scale_type": "count"},
    "seg": {"source": "TSSEG", "scale_type": "count"},
    # TSCTX (step04)
    "minutes_since_open": {"source": "TSCTX", "scale_type": "time"},
    "minutes_to_close": {"source": "TSCTX", "scale_type": "time"},
    "day_of_week": {"source": "TSCTX", "scale_type": "categorical"},
    "overnight_gap_pct": {"source": "TSCTX", "scale_type": "ratio"},
    "prev_day_return_pct": {"source": "TSCTX", "scale_type": "ratio"},
    "prev_day_range_pct": {"source": "TSCTX", "scale_type": "ratio"},
    "prev_day_high_dist_pct": {"source": "TSCTX", "scale_type": "ratio"},
    "prev_day_low_dist_pct": {"source": "TSCTX", "scale_type": "ratio"},
    "intraday_return_pct": {"source": "TSCTX", "scale_type": "ratio"},
    "daily_volatility": {"source": "TSCTX", "scale_type": "ratio"},
    "relative_volume": {"source": "TSCTX", "scale_type": "ratio"},
    "ath_drawdown_pct": {"source": "TSCTX", "scale_type": "ratio"},
}

# FUNCTION: GET THE FEATURE COLUMN LIST FOR A LIST OF SCALE TYPES
def get_feature_col_str_list(scale_type_str_list_in=None, source_str_list_in=None):
    """
    Returns the registered feature columns, optionally filtered by scale type and source step.

    Args:
        scale_type_str_list_in (list[str] | None): Scale types to keep (None keeps every scale type)
        source_str_list_in (list[str] | None): Source steps to keep, e.g. ["TSIND", "TSCTX"] (None keeps every source)

    Returns:
        list[str]: Feature column names in registry order
    """
    # RETURN THE FILTERED FEATURE COLUMN LIST
    return [col_str for col_str, info_dict in FEATURE_REGISTRY_DICT.items()
            if (scale_type_str_list_in is None or info_dict["scale_type"] in scale_type_str_list_in)
            and (source_str_list_in is None or info_dict["source"] in source_str_list_in)]

# FUNCTION: GET THE CONFIGURATION SNAPSHOT DICTIONARY
def get_config_snapshot_dict():
    """
    Collects every uppercase constant of this module into a JSON-serializable dictionary.

    Returns:
        dict: Constant name -> value
    """
    # COLLECT ALL UPPERCASE CONSTANTS
    return {key_str: value for key_str, value in globals().items() if key_str.isupper()}

