"""
Workspace Tests: total returns (R4b; so.runner.total_return and the engines' open_session)

Run from the workspace root:   python tests/test_total_return.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only: invented prices, dividends and rates. The data root is a temporary folder. records/holdout_windows.csv
is not written. SO_HOLDOUT_PATH, SO_HOLDOUT_EVALUATION_TOKEN and SO_QUARANTINE_PATH are not set. No real-data run.
"""

import os
import sys
import tempfile
import numpy as np
import pandas as pd

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
_CURRENT_DATA_PATH_STR = os.environ.get("SO_DATA_PATH", "").strip()
_TEMP_DIR_STR = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
if _CURRENT_DATA_PATH_STR and os.path.normcase(os.path.abspath(_CURRENT_DATA_PATH_STR)).startswith(_TEMP_DIR_STR + os.sep):
    TEMP_ROOT_STR = _CURRENT_DATA_PATH_STR
else:
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_total_return_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

from so import config
from so.core.trade_execution import get_ohlcv_array_dict
from so.core.reentry_simulation import get_buy_and_hold_result_dict, get_window_session_idx_arr
from so.core.holdout import get_truncated_ohlcv_dict, get_perturbed_ohlcv_dict
from so.core.external_data import SPY_DIVIDENDS_COLUMN_STR_LIST, TBILL_3M_COLUMN_STR_LIST
from so.runner import TrailingStopEngine, BarrierEngine
from so.runner.engine import FractionalWeightEngine
from so.runner.baselines import run_weight_path_dict, get_runner_baseline_dict
from so.runner.total_return import (get_investment_yield_arr, get_total_return_schedule_dict, get_bundle_with_schedule_dict,
                                    get_total_return_bundle_dict, get_zero_schedule_dict, TOTAL_RETURN_BASIS_STR)
from so.runner.verdict import get_report_markdown_str
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE SYNTHETIC SPAN
DATE1_STR, DATE2_STR = "2010-01-04", "2010-06-30"


# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")


# FUNCTION: THE SYNTHETIC BUNDLE (PRICE-ONLY)
def get_price_bundle_dict():
    return get_ohlcv_array_dict(get_synthetic_ohlcv_pdf(DATE1_STR, DATE2_STR, seed_in=7))


# FUNCTION: A DIVIDEND FRAME AS THE LOADER RETURNS IT (TYPED)
def get_dividend_pdf(row_list_in):
    return pd.DataFrame([{"ex_date": pd.Timestamp(ex_str).date(), "amount_usd": float(amount), "vintage_kind": kind_str} for ex_str, amount, kind_str in row_list_in],
                        columns=["ex_date", "amount_usd", "vintage_kind"])


# FUNCTION: A RATE FRAME AS THE LOADER RETURNS IT (TYPED; NaN = FRED'S ".")
def get_rate_pdf(row_list_in):
    return pd.DataFrame([{"observation_date": pd.Timestamp(day_str).date(), "value_pct": value, "vintage_kind": kind_str} for day_str, value, kind_str in row_list_in],
                        columns=["observation_date", "value_pct", "vintage_kind"])


# TEST: THE YIELD CONVERSION AND THE SCHEDULE RULES
def test_schedule_rules():
    # 5% DISCOUNT -> 365 x 0.05 / (360 - 91 x 0.05) = 0.05134336...
    assert abs(float(get_investment_yield_arr([5.0])[0]) - 365 * 0.05 / (360 - 91 * 0.05)) < 1e-15
    assert abs(float(get_investment_yield_arr([5.0])[0]) - 0.0513433675) < 1e-9
    session_list = [pd.Timestamp(day_str).date() for day_str in ("2010-01-07", "2010-01-08", "2010-01-11", "2010-01-12", "2010-01-14")]
    # RATES: A FIRST RELEASE, A LATER REVISION (IGNORED), A "." DAY (CARRIED), A BACKFILLED ROW
    rate_pdf = get_rate_pdf([("2010-01-06", 2.0, "rule_based_backfill"), ("2010-01-07", 3.0, "first_seen"), ("2010-01-07", 9.0, "revision"),
                             ("2010-01-08", np.nan, "first_seen"), ("2010-01-11", 4.0, "first_seen"), ("2010-01-12", 5.0, "first_seen")])
    # DIVIDENDS: ONE ON A SESSION, ONE ON A DAY WITH NO SESSION IN THE DATA (-> THE NEXT SESSION), A REVISION (IGNORED), ONE BEFORE THE SPAN
    dividend_pdf = get_dividend_pdf([("2010-01-08", 0.5, "first_seen"), ("2010-01-08", 0.7, "revision"), ("2010-01-13", 0.25, "first_seen"),
                                     ("2009-12-18", 0.4, "first_seen")])
    schedule_dict = get_total_return_schedule_dict(session_list, dividend_pdf, rate_pdf)
    assert schedule_dict["total_return_basis_str"] == TOTAL_RETURN_BASIS_STR
    assert schedule_dict["dividend_per_share_arr"].tolist() == [0.0, 0.5, 0.0, 0.0, 0.25]
    # NIGHTS: 01-07 -> 01-08 (1 DAY AT 3%), 01-08 -> 01-11 (3 DAYS, 01-08 IS "." -> CARRIES 3%), 01-11 -> 01-12 (1 DAY AT 4%),
    # 01-12 -> 01-14 (2 DAYS AT 5%); THE FIRST SESSION EARNS NOTHING
    yield_arr = get_investment_yield_arr([3.0, 3.0, 4.0, 5.0])
    expected_arr = np.array([0.0] + list(yield_arr * np.array([1, 3, 1, 2]) / 365.0))
    assert np.allclose(schedule_dict["cash_growth_arr"], expected_arr, rtol=0, atol=1e-18), (schedule_dict["cash_growth_arr"], expected_arr)
    # NO RATE BEFORE THE FIRST NIGHT RAISES
    try:
        get_total_return_schedule_dict(session_list, dividend_pdf, get_rate_pdf([("2010-01-12", 5.0, "first_seen")]))
        raise AssertionError("a span with no earlier rate was accepted")
    except ValueError:
        pass
    passed("schedule: 91-day investment yield, first releases only, '.' carried, calendar days, dividend on the next session if none")


# TEST: A ZERO SCHEDULE CHANGES NOTHING (THE REGRESSION GUARD FOR EVERY ENGINE AND BUY-AND-HOLD)
def test_zero_schedule_identical():
    price_dict = get_price_bundle_dict()
    session_count = len(price_dict["session_date_list"])
    zero_dict = get_bundle_with_schedule_dict(price_dict, {**get_zero_schedule_dict(session_count), "total_return_basis_str": TOTAL_RETURN_BASIS_STR})
    window_count = len(get_window_session_idx_arr(price_dict, DATE1_STR, DATE2_STR))
    weight_arr = np.where(np.arange(window_count) % 7 < 4, 1.0, 0.3)
    for label_str, call in (("fractional path", lambda bundle: run_weight_path_dict(bundle, DATE1_STR, DATE2_STR, weight_arr, 1.0, 0.05)),
                            ("buy-and-hold", lambda bundle: get_buy_and_hold_result_dict(bundle, DATE1_STR, DATE2_STR))):
        left_pdf, right_pdf = call(price_dict)["daily_equity_pdf"], call(zero_dict)["daily_equity_pdf"]
        assert left_pdf.equals(right_pdf), label_str
    passed("a zero schedule gives the price-return results exactly (fractional path, buy-and-hold)")


# FUNCTION: A BUNDLE WITH A HAND-MADE SCHEDULE
def get_scheduled_bundle_dict(dividend_session_pos_in=None, dividend_in=0.0, growth_in=0.0):
    price_dict = get_price_bundle_dict()
    schedule_dict = get_zero_schedule_dict(len(price_dict["session_date_list"]))
    schedule_dict["total_return_basis_str"] = TOTAL_RETURN_BASIS_STR
    if dividend_session_pos_in is not None:
        schedule_dict["dividend_per_share_arr"][int(dividend_session_pos_in)] = float(dividend_in)
    schedule_dict["cash_growth_arr"][1:] = float(growth_in)
    return get_bundle_with_schedule_dict(price_dict, schedule_dict)


# TEST: INTEREST ON CASH (ALL-CASH PATH: EQUITY = CAPITAL x PRODUCT OF (1 + GROWTH))
def test_interest_on_cash():
    bundle_dict = get_scheduled_bundle_dict(growth_in=0.0001)
    window_count = len(get_window_session_idx_arr(bundle_dict, DATE1_STR, DATE2_STR))
    result_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, np.zeros(window_count), 0.0, 0.0)
    expected_float = config.INITIAL_CAPITAL * (1.0001 ** (window_count - 1))
    final_float = float(result_dict["daily_equity_pdf"]["equity"].iloc[-1])
    assert abs(final_float - expected_float) < 1e-4, (final_float, expected_float)
    assert result_dict["trade_pdf"].empty and abs(result_dict["income_dict"]["interest_income"] - (expected_float - config.INITIAL_CAPITAL)) < 1e-4
    assert result_dict["income_dict"]["dividend_income"] == 0.0
    passed("interest: an all-cash path compounds the schedule exactly; the first session earns nothing")


# TEST: WHO GETS THE DIVIDEND (HELD AT THE PREVIOUS CLOSE; BOUGHT ON THE EX-DATE GETS NONE; SOLD AT ITS FILL STILL GETS IT)
def test_dividend_entitlement():
    ex_pos = 20
    window_count = len(get_window_session_idx_arr(get_price_bundle_dict(), DATE1_STR, DATE2_STR))
    bundle_dict = get_scheduled_bundle_dict(ex_pos, 1.0)
    # HELD THROUGH: THE DIVIDEND IS THE SHARES AT THE PREVIOUS CLOSE x 1.00
    held_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, np.ones(window_count), 1.0, 0.5)
    income_pdf = held_dict["income_dict"]["income_pdf"]
    assert len(income_pdf) == 1 and income_pdf["session_date"].iloc[0] == bundle_dict["session_date_list"][ex_pos]
    assert income_pdf["dividend"].iloc[0] == float(income_pdf["share_count"].iloc[0]) * 1.0 and income_pdf["share_count"].iloc[0] > 0
    # BOUGHT AT THE EX-DATE'S FILL (CASH UNTIL THEN): NO DIVIDEND
    late_arr = np.where(np.arange(window_count) >= ex_pos, 1.0, 0.0)
    late_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, late_arr, 0.0, 0.0)
    assert late_dict["income_dict"]["dividend_income"] == 0.0 and (late_dict["trade_pdf"]["reason"] == "rebalance").any()
    # BOUGHT THE SESSION BEFORE (HELD AT ITS CLOSE) AND SOLD AT THE EX-DATE'S FILL: STILL PAID
    early_arr = np.where(np.arange(window_count) == ex_pos - 1, 1.0, 0.0)
    early_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, early_arr, 0.0, 0.0)
    assert early_dict["income_dict"]["dividend_income"] > 0
    passed("dividend: shares held at the previous close are paid; bought on the ex-date are not; sold at its fill still are")


# TEST: BUY-AND-HOLD REINVESTS, AND BOTH BUY-AND-HOLD CALCULATIONS AGREE
def test_buy_hold_reinvests_and_agrees():
    ex_pos = 30
    bundle_dict = get_scheduled_bundle_dict(ex_pos, 2.0, 0.00005)
    simulator_dict = get_buy_and_hold_result_dict(bundle_dict, DATE1_STR, DATE2_STR)
    window_count = len(get_window_session_idx_arr(bundle_dict, DATE1_STR, DATE2_STR))
    engine_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, np.ones(window_count), 1.0, 0.0)
    assert simulator_dict["daily_equity_pdf"]["equity"].equals(engine_dict["daily_equity_pdf"]["equity"])
    assert simulator_dict["income_dict"]["dividend_income"] == engine_dict["income_dict"]["dividend_income"] > 0
    # THE DIVIDEND IS REINVESTED AT THE EX-DATE'S FILL (A BUY ON THAT SESSION)
    buy_pdf = engine_dict["trade_pdf"][engine_dict["trade_pdf"]["reason"] == "rebalance"]
    ex_date = bundle_dict["session_date_list"][ex_pos]
    assert any(pd.Timestamp(ts).date() == ex_date for ts in buy_pdf["trade_ts"]), "the dividend was not reinvested on the ex-date"
    # THE VERDICT'S BASELINES SEE THE SAME BUY-AND-HOLD
    prior_only_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, np.full(window_count, 0.6), 0.6, 0.05)
    baseline_dict = get_runner_baseline_dict(bundle_dict, DATE1_STR, DATE2_STR, prior_only_dict, seed_count_int_in=3)
    assert abs(baseline_dict["buy_hold_total_return"] - simulator_dict["metric_dict"]["total_return"]) < 1e-12
    assert baseline_dict["buy_hold_income_dict"]["dividend_income"] > 0
    passed("buy-and-hold reinvests the dividend at the ex-date fill; the simulator, the engine path and the baselines agree")


# TEST: THE OTHER ENGINES CREDIT THE SAME AMOUNTS FOR THE SAME HOLDINGS
def test_engines_credit_alike():
    event_dict = {"session_idx": 5, "session_date": pd.Timestamp("2010-01-11").date(), "dividend_per_share": 0.5, "cash_growth": 0.001}
    amount_list = []
    for engine in (FractionalWeightEngine(0.0), TrailingStopEngine(), BarrierEngine()):
        engine.cash_float, engine.share_count_int = 1234.5, 80
        engine.open_session(event_dict)
        amount_list.append((engine.cash_float, engine.get_income_dict()["dividend_income"], engine.get_income_dict()["interest_income"]))
    assert len(set(amount_list)) == 1 and amount_list[0] == (1234.5 + 40.0 + 1.2345, 40.0, 1.2345 * 1.0), amount_list
    passed("fractional, trailing-stop and barrier engines credit identical amounts for identical holdings")


# TEST: CUTTING AND PERTURBING A BUNDLE KEEP ITS SCHEDULE; THE LOADER PATH BUILDS ONE FROM THE CONTRACT FILES
def test_bundle_helpers_and_loaders():
    bundle_dict = get_scheduled_bundle_dict(10, 0.3, 0.0002)
    cut_date = bundle_dict["session_date_list"][40]
    cut_dict = get_truncated_ohlcv_dict(bundle_dict, cut_date)
    assert len(cut_dict["dividend_per_share_arr"]) == 41 and cut_dict["total_return_basis_str"] == TOTAL_RETURN_BASIS_STR
    assert np.array_equal(cut_dict["cash_growth_arr"], bundle_dict["cash_growth_arr"][:41])
    perturbed_dict = get_perturbed_ohlcv_dict(bundle_dict, cut_date)
    assert np.array_equal(perturbed_dict["dividend_per_share_arr"], bundle_dict["dividend_per_share_arr"]) and perturbed_dict["total_return_basis_str"] == TOTAL_RETURN_BASIS_STR
    # THE LOADERS READ THE CONTRACT FILES UNDER THE DATA ROOT (GUARD OFF: NO WINDOW IN THIS SUITE)
    root_str = TEMP_ROOT_STR.replace("\\", "/").rstrip("/") + "/"
    os.makedirs(f"{root_str}store01_rawzone/fred_dtb3", exist_ok=True)
    os.makedirs(f"{root_str}store01_rawzone/spy_dividends", exist_ok=True)
    pd.DataFrame([["2010-01-04", "2010-01-04 16:30:00-05:00", "2009-12-31", "0.05", "2010-01-04", "rule_based_backfill", "R1"]],
                 columns=TBILL_3M_COLUMN_STR_LIST).to_csv(f"{root_str}store01_rawzone/fred_dtb3/dtb3.csv", index=False)
    pd.DataFrame([["2010-03-19", "2010-03-19 09:30:00-04:00", "2010-03-19", "2010-03-23", "2010-04-30", "", "0.512800", "regular", "USD", "first_seen", "R1"]],
                 columns=SPY_DIVIDENDS_COLUMN_STR_LIST).to_csv(f"{root_str}store01_rawzone/spy_dividends/spy_dividends.csv", index=False)
    loaded_dict = get_total_return_bundle_dict(get_price_bundle_dict(), DATE2_STR, enforce_holdout_bool_in=False)
    assert loaded_dict["total_return_basis_str"] == TOTAL_RETURN_BASIS_STR
    ex_pos = [pd.Timestamp(day).date() for day in loaded_dict["session_date_list"]].index(pd.Timestamp("2010-03-19").date())
    assert loaded_dict["dividend_per_share_arr"][ex_pos] == 0.5128 and loaded_dict["dividend_per_share_arr"].sum() == 0.5128
    assert np.all(loaded_dict["cash_growth_arr"][1:] > 0) and loaded_dict["cash_growth_arr"][0] == 0.0
    passed("truncation and perturbation keep the schedule; the loaders build it from the contract files")


# TEST: A DESIGN RUN (DailyLoop) CREDITS THE SAME AS ITS REPLAY (THE PRIOR-ONLY PATH) ON A TOTAL-RETURN BUNDLE
def test_design_loop_matches_replay():
    import runner_trailing_design as trail_design
    from so.runner import run_daily_dict
    from so.runner.loop import run_engine_decisions_dict
    price_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2011-01-03", "2011-12-30", seed_in=11))
    schedule_dict = get_zero_schedule_dict(len(price_dict["session_date_list"]))
    schedule_dict["total_return_basis_str"] = TOTAL_RETURN_BASIS_STR
    schedule_dict["dividend_per_share_arr"][[40, 100, 160, 220]] = 1.5
    schedule_dict["cash_growth_arr"][1:] = 0.0001
    bundle_dict = get_bundle_with_schedule_dict(price_dict, schedule_dict)
    date1, date2 = bundle_dict["session_date_list"][0], bundle_dict["session_date_list"][-1]
    stream_dict = run_daily_dict(trail_design.VaryingTrailDesign(), bundle_dict, date1, date2,
                                 engine_in=TrailingStopEngine(trail_design.MAX_CASH_SESSIONS), initial_weight_in=1.0,
                                 design_file_path_str_in=trail_design.__file__)
    replay_dict = run_engine_decisions_dict(bundle_dict, date1, date2, stream_dict["decision_dict_list"],
                                            engine_in=TrailingStopEngine(trail_design.MAX_CASH_SESSIONS), initial_weight_in=1.0)
    assert np.allclose(stream_dict["daily_equity_pdf"]["equity"], replay_dict["daily_equity_pdf"]["equity"], atol=1e-9)
    assert stream_dict["income_dict"]["dividend_income"] == replay_dict["income_dict"]["dividend_income"] > 0
    assert stream_dict["income_dict"]["interest_income"] == replay_dict["income_dict"]["interest_income"] > 0
    # AND THE TOTAL-RETURN PATH ENDS ABOVE THE PRICE-ONLY PATH OF THE SAME DECISIONS
    price_replay_dict = run_engine_decisions_dict(price_dict, date1, date2, stream_dict["decision_dict_list"],
                                                  engine_in=TrailingStopEngine(trail_design.MAX_CASH_SESSIONS), initial_weight_in=1.0)
    assert replay_dict["metric_dict"]["total_return"] > price_replay_dict["metric_dict"]["total_return"]
    passed("design loop and its replay credit the same dividends and interest (trailing-stop design)")


# TEST: THE REPORT STATES THE BASIS (A REAL VERDICT AND BASELINES ON THE SYNTHETIC SPAN)
def test_report_basis_line():
    from so.runner.verdict import get_runner_verdict_dict, get_report_payload_dict, get_equity_daily_return_pdf
    trial_log_path_str = os.path.join(TEMP_ROOT_STR, "report_trial_log.csv")
    for bundle_dict, expected_str in ((get_scheduled_bundle_dict(30, 2.0, 0.00005), "Total returns on both sides"),
                                      (get_price_bundle_dict(), "Price returns: no dividends")):
        window_count = len(get_window_session_idx_arr(bundle_dict, DATE1_STR, DATE2_STR))
        prior_only_dict = run_weight_path_dict(bundle_dict, DATE1_STR, DATE2_STR, np.full(window_count, 0.6), 0.6, 0.05)
        baseline_dict = get_runner_baseline_dict(bundle_dict, DATE1_STR, DATE2_STR, prior_only_dict, seed_count_int_in=3)
        verdict_dict = get_runner_verdict_dict(get_equity_daily_return_pdf(prior_only_dict["daily_equity_pdf"]),
                                               get_equity_daily_return_pdf(baseline_dict["buy_hold_daily_equity_pdf"]), baseline_dict,
                                               trial_log_path_str_in=trial_log_path_str, legacy_path_list_in=[])
        report_dict = get_report_payload_dict(verdict_dict, {
            "return_basis_str": bundle_dict["total_return_basis_str"],
            "income_dict": {"strategy": {key_str: value for key_str, value in prior_only_dict["income_dict"].items() if key_str != "income_pdf"},
                            "buy_hold": dict(baseline_dict["buy_hold_income_dict"])}})
        markdown_str = get_report_markdown_str(report_dict)
        assert expected_str in markdown_str, markdown_str[:600]
        assert ("Credited (dollars)" in markdown_str) == (bundle_dict["total_return_basis_str"] == TOTAL_RETURN_BASIS_STR)
    passed("report: the return section states total or price returns, and the credited dividends and interest")


# RUN THE SUITE
if __name__ == "__main__":
    test_schedule_rules()
    test_zero_schedule_identical()
    test_interest_on_cash()
    test_dividend_entitlement()
    test_buy_hold_reinvests_and_agrees()
    test_engines_credit_alike()
    test_design_loop_matches_replay()
    test_bundle_helpers_and_loaders()
    test_report_basis_line()
    print("\nAll total-return tests passed ✅")
