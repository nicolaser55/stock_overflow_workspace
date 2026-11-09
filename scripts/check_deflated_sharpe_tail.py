import argparse
import datetime
import json
import math
import multiprocessing
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE AND THIS FOLDER TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parent))
import numpy as np
from statistics import NormalDist
# IMPORT THE CONFIGURATION, THE DATA PATHS, THE BASELINE ENGINE AND THE VERDICT'S OWN STATISTICS
from so import config
from so.paths import get_named_data_path_str
from so.runner.baselines import get_random_timing_seed_list, get_random_timing_weight_arr, run_weight_path_dict
from so.core.multiple_testing import get_quarter_excess_arr, get_sharpe_float, get_moment_tuple, get_deflated_sharpe_dict
from check_random_timing_tail import get_rebuilt_prior_only_tuple, get_report_basis_bundle_dict

"""
Deflated-Sharpe Tail Check (diagnostic; judge v1 freeze, roadmap "counted check of the deflated Sharpe ratio", 2026-11-09)

The multiple-testing part of the verdict passes a path only if its deflated Sharpe ratio (DSR) is at least 0.95. The
DSR (so.core.multiple_testing.get_deflated_sharpe_dict, Bailey and Lopez de Prado 2014) is a normal-type approximation:
it corrects the Sharpe ratio of the quarterly excess returns over buy-and-hold for skewness and kurtosis, and for the
number of designs tried N through the expected maximum of N Sharpe ratios (from the trial log's variance V). Whether
that approximation is fair here is an assumption; the random-timing test's normal fit, checked the same way, was about
18 times too lenient (check_random_timing_tail.py, 2026-11-02).

What a fair DSR promises: a design with no timing skill passes with probability about alpha / N per design (alpha 0.05),
so that the best of N such designs passes with probability about alpha. This script measures it for one finished run:

    1. rebuilds the run's prior-only path and its 100 registered random-timing draws on the report's own return basis
       (proof that it reproduces the referee);
    2. extends them to --draws draws on the same exposure path: designs with the run's exposure and no timing skill;
    3. computes each draw's DSR exactly as the verdict does (quarterly excess over buy-and-hold, its skewness and
       kurtosis, the report's N and V), and counts the draws at or above 0.95, against the expected draws x alpha / N;
    4. repeats step 3 with the draws "centered": each quarter's excess minus that quarter's mean over all draws. A
       random-timing design that is invested less than buy-and-hold loses on average while the market rises, so its raw
       DSR is low for a reason that has nothing to do with the DSR's calibration; the centered draws have no average
       edge or handicap, which is the null the DSR is built for. The centered count is the one that decides.

Reading: a centered count near or below the expected count means the DSR is fair or conservative here, and the
verdict keeps it. Clearly more (for example three times or more) means it is too lenient, and a core change follows
(for example a counted DSR, as for random timing). Changes nothing; writes deflated_sharpe_tail_<run id>.md and .json
to --output. Daily experiments only. The design module is loaded from the current workspace, which must hold the same
experiment code the run used (the script compares the rebuilt return with the report).

    python scripts/check_deflated_sharpe_tail.py exp04_trend_exit_20261028190530034569 --draws 10000 --processes 4

Run it as Nicolas (it reads the development bars). It never reads the holdout or the quarantine.
"""

# THE PROCESS-LOCAL BARS, SPAN, EXPOSURE AND BUY-AND-HOLD DAILY RETURNS OF A WORKER
_WORKER_STATE_DICT = {}


# FUNCTION: SET A WORKER'S STATE
def init_worker(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in, buy_hold_return_pdf_in):
    _WORKER_STATE_DICT.update({"ohlcv": ohlcv_array_dict_in, "date1": date1_in, "date2": date2_in,
                               "exposure": exposure_arr_in, "buy_hold": buy_hold_return_pdf_in})


# FUNCTION: ONE DRAW: TOTAL RETURN AND QUARTERLY EXCESS OVER BUY-AND-HOLD (THE BASELINE'S OWN LOOP BODY)
def get_draw_tuple(seed_int_in):
    """
    Args:
        seed_int_in (int): Seed

    Returns:
        tuple: (total return, quarterly excess returns as a list)
    """
    from so.runner.verdict import get_equity_daily_return_pdf
    state_dict = _WORKER_STATE_DICT
    random_arr = get_random_timing_weight_arr(state_dict["exposure"], int(seed_int_in))
    initial_weight = float(random_arr[0]) if len(random_arr) and np.isfinite(random_arr[0]) else 0.0
    result_dict = run_weight_path_dict(state_dict["ohlcv"], state_dict["date1"], state_dict["date2"], random_arr, initial_weight, 0.0,
                                       config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE)
    excess_arr = get_quarter_excess_arr(get_equity_daily_return_pdf(result_dict["daily_equity_pdf"]), state_dict["buy_hold"])
    return float(result_dict["metric_dict"]["total_return"]), [float(value) for value in excess_arr]


# FUNCTION: ALL DRAWS, IN SEED ORDER
def get_draw_tuple_list(seed_list_in, ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in, buy_hold_return_pdf_in, process_count_int_in=1):
    # ONE PROCESS: RUN HERE; SEVERAL: SPAWN WORKERS (WINDOWS) WITH ONE COPY OF THE BARS EACH
    if int(process_count_int_in) <= 1:
        init_worker(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in, buy_hold_return_pdf_in)
        return [get_draw_tuple(seed_int) for seed_int in seed_list_in]
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=int(process_count_int_in), initializer=init_worker,
                  initargs=(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in, buy_hold_return_pdf_in)) as pool:
        return list(pool.map(get_draw_tuple, list(seed_list_in), chunksize=50))


# FUNCTION: THE DSR OF EACH ROW OF A DRAWS x QUARTERS MATRIX (THE VERDICT'S FUNCTION, ROW BY ROW)
def get_dsr_arr(excess_matrix_in, variance_float_in, design_count_int_in):
    dsr_list = []
    for excess_arr in excess_matrix_in:
        skew_float, kurtosis_float = get_moment_tuple(excess_arr)
        dsr_list.append(get_deflated_sharpe_dict(get_sharpe_float(excess_arr), len(excess_arr), skew_float, kurtosis_float,
                                                 variance_float_in, design_count_int_in)["probability"])
    return np.asarray(dsr_list, dtype=float)


# FUNCTION: THE COUNTS FOR ONE N
def get_count_dict(excess_matrix_in, variance_float_in, design_count_int_in, alpha_in):
    """
    Args:
        excess_matrix_in (np.ndarray): Draws x quarters, quarterly excess over buy-and-hold
        variance_float_in (float): V from the run's report
        design_count_int_in (int): N
        alpha_in (float): Family-wise alpha

    Returns:
        dict: raw and centered DSR counts at or above the minimum, the expected count, and their ratio
    """
    # RAW DRAWS, THEN DRAWS WITH EACH QUARTER'S CROSS-DRAW MEAN REMOVED
    minimum_float = float(config.RUNNER_DSR_MIN_PROBABILITY)
    centered_matrix = excess_matrix_in - excess_matrix_in.mean(axis=0, keepdims=True)
    raw_dsr_arr = get_dsr_arr(excess_matrix_in, variance_float_in, design_count_int_in)
    centered_dsr_arr = get_dsr_arr(centered_matrix, variance_float_in, design_count_int_in)
    expected_float = len(excess_matrix_in) * float(alpha_in) / max(1, int(design_count_int_in))
    centered_int = int(np.sum(centered_dsr_arr >= minimum_float))
    return {"design_count": int(design_count_int_in), "expected_count": expected_float,
            "raw_count": int(np.sum(raw_dsr_arr >= minimum_float)), "centered_count": centered_int,
            "centered_ratio": (centered_int / expected_float) if expected_float > 0 else float("nan"),
            "raw_dsr_quantile_list": [float(np.quantile(raw_dsr_arr, level)) for level in (0.5, 0.99, 0.999)],
            "centered_dsr_quantile_list": [float(np.quantile(centered_dsr_arr, level)) for level in (0.5, 0.99, 0.999)],
            "centered_dsr_max": float(centered_dsr_arr.max())}


# FUNCTION: SUMMARY AS MARKDOWN
def get_markdown_str(run_id_str_in, summary_dict_in):
    s = summary_dict_in
    line_list = [f"# Deflated-Sharpe tail check: {run_id_str_in}", "",
                 f"Written {datetime.datetime.now().isoformat(timespec='seconds')}. Return basis {s['return_basis_str']}. "
                 f"{s['draw_count']} random-timing draws on the run's exposure path ({s['quarter_count']} quarters).",
                 f"Reproduced: rebuilt prior-only return {s['rebuilt_return']:.6f} = report; the {s['registered_count']} registered draws "
                 f"(largest difference {s['max_abs_difference']:.2e}).",
                 f"The run's own DSR: {s['report_dsr']:.4f} at N = {s['report_design_count']}, V = {s['trial_sharpe_variance']:.6g} "
                 f"({s['trial_sharpe_variance_source_str']}).", "",
                 "| N | expected at or above 0.95 | raw draws | centered draws | centered / expected | centered DSR 50% / 99% / 99.9% / max |",
                 "|---|---|---|---|---|---|"]
    for row in s["count_list"]:
        quantile_str = " / ".join(f"{value:.4f}" for value in row["centered_dsr_quantile_list"] + [row["centered_dsr_max"]])
        line_list.append(f"| {row['design_count']} | {row['expected_count']:.2f} | {row['raw_count']} | {row['centered_count']} | "
                         f"{row['centered_ratio']:.2f} | {quantile_str} |")
    line_list += ["", "Centered draws carry no average edge or handicap: their count is the one that decides. Near or below the",
                  "expected count: fair or conservative, keep the DSR. Clearly above (three times or more): too lenient, a core change follows."]
    return "\n".join(line_list) + "\n"


# PARSE THE COMMAND
if __name__ == "__main__":
    # THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Compare the deflated Sharpe ratio's pass rate under no skill with alpha / N for one run.")
    parser.add_argument("run_id", help="A finished daily run in store04_experiments/runs")
    parser.add_argument("--draws", type=int, default=10000, help="Random-timing draws (default 10,000)")
    parser.add_argument("--processes", type=int, default=4, help="Worker processes (default 4)")
    parser.add_argument("--design-counts", type=int, nargs="*", default=None, help="Extra N to evaluate (the report's N is always included)")
    parser.add_argument("--output", default=None, help="Output folder (default store04_experiments/checks)")
    arg_dict = parser.parse_args()
    start_time = datetime.datetime.now()
    zone_str = get_named_data_path_str("LOCAL_EXPERIMENTZONE_PATH_STR")
    run_folder_str = os.path.join(zone_str, "runs", arg_dict.run_id)
    report_dict = json.loads(Path(run_folder_str, "report.json").read_text(encoding="utf-8"))
    multiple_dict = report_dict["multiple_testing_dict"]
    experiment_str = str(report_dict["experiment_name_str"])
    # THE DESIGN (CURRENT WORKSPACE) AND THE SAME DEVELOPMENT BARS AS THE RUN (ITS EMBARGO), ON THE REPORT'S RETURN BASIS
    from run_development import load_design_module
    from so.core.development_span import get_development_ohlcv_dict
    from so.runner.baselines import get_exposure_weight_arr
    from so.runner.run import get_realized_exposure_bool
    from so.runner.verdict import get_equity_daily_return_pdf
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    design_module = load_design_module(str(Path(__file__).resolve().parents[1] / "experiments" / experiment_str))
    development_dict = get_development_ohlcv_dict(int(design_module.PERIOD_RULE["embargo_sessions"]))["ohlcv_array_dict"]
    ohlcv_array_dict, basis_str = get_report_basis_bundle_dict(development_dict, report_dict)
    prior_only_dict, date1, date2 = get_rebuilt_prior_only_tuple(design_module, ohlcv_array_dict, run_folder_str, arg_dict.run_id)
    rebuilt_float = float(prior_only_dict["metric_dict"]["total_return"])
    reported_float = float(report_dict["return_dict"]["strategy_total_return"])
    if not abs(rebuilt_float - reported_float) <= 1e-7:
        raise SystemExit(f"the rebuilt prior-only path returns {rebuilt_float} but the report says {reported_float}; "
                         f"is the workspace at the experiment code the run used? nothing written")
    exposure_arr = get_exposure_weight_arr(prior_only_dict, get_realized_exposure_bool(design_module))
    # THE RUN'S OWN DSR, RECOMPUTED, MUST EQUAL THE REPORT'S (SAME BUY-AND-HOLD, SAME N AND V)
    buy_hold_return_pdf = get_equity_daily_return_pdf(get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)["daily_equity_pdf"])
    design_count = int(multiple_dict["design_count"])
    variance_float = float(multiple_dict["trial_sharpe_variance"])
    path_excess_arr = get_quarter_excess_arr(get_equity_daily_return_pdf(prior_only_dict["daily_equity_pdf"]), buy_hold_return_pdf)
    path_dsr_float = float(get_dsr_arr([path_excess_arr], variance_float, design_count)[0])
    if not abs(path_dsr_float - float(multiple_dict["deflated_sharpe_probability"])) <= 1e-9:
        raise SystemExit(f"the run's DSR recomputes to {path_dsr_float}, the report says {multiple_dict['deflated_sharpe_probability']}; nothing written")
    print(f"rebuilt {arg_dict.run_id} on {basis_str}: return {rebuilt_float:.6f}, DSR {path_dsr_float:.4f} (both = report)", flush=True)
    # THE DRAWS; THE REGISTERED ONES MUST BE REPRODUCED
    seed_list = get_random_timing_seed_list(int(arg_dict.draws))
    print(f"{len(seed_list)} draws on {arg_dict.processes} process(es) ...", flush=True)
    draw_list = get_draw_tuple_list(seed_list, ohlcv_array_dict, date1, date2, exposure_arr, buy_hold_return_pdf, arg_dict.processes)
    registered_list = [float(value) for value in report_dict["baseline_dict"]["random_timing_return_list"]]
    difference_float = max((abs(draw[0] - value) for draw, value in zip(draw_list, registered_list)), default=float("nan"))
    if len(draw_list) < len(registered_list) or not difference_float <= 1e-9:
        raise SystemExit(f"the registered draws were not reproduced (largest difference {difference_float}); nothing written")
    excess_matrix = np.asarray([draw[1] for draw in draw_list], dtype=float)
    # THE COUNTS AT THE REPORT'S N AND ANY EXTRA N
    count_list = [get_count_dict(excess_matrix, variance_float, count, float(config.RUNNER_MULTIPLE_TESTING_ALPHA))
                  for count in sorted({design_count, *[int(value) for value in (arg_dict.design_counts or [])]})]
    summary_dict = {"return_basis_str": basis_str, "draw_count": len(draw_list), "quarter_count": int(excess_matrix.shape[1]),
                    "rebuilt_return": rebuilt_float, "registered_count": len(registered_list), "max_abs_difference": difference_float,
                    "report_dsr": path_dsr_float, "report_design_count": design_count, "trial_sharpe_variance": variance_float,
                    "trial_sharpe_variance_source_str": str(multiple_dict.get("trial_sharpe_variance_source_str", "")),
                    "alpha": float(config.RUNNER_MULTIPLE_TESTING_ALPHA), "count_list": count_list}
    output_str = arg_dict.output or os.path.join(zone_str, "checks")
    os.makedirs(output_str, exist_ok=True)
    stem_str = os.path.join(output_str, f"deflated_sharpe_tail_{arg_dict.run_id}")
    Path(stem_str + ".md").write_text(get_markdown_str(arg_dict.run_id, summary_dict), encoding="utf-8")
    Path(stem_str + ".json").write_text(json.dumps({"run_id": arg_dict.run_id, **summary_dict}, indent=1), encoding="utf-8")
    print(Path(stem_str + ".md").read_text(encoding="utf-8"))
    print(f"wrote {stem_str}.md and .json in {(datetime.datetime.now() - start_time).total_seconds() / 60:.1f} minutes")
