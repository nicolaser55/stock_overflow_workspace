import argparse
import datetime
import json
import multiprocessing
import os
import sys
from pathlib import Path
from statistics import NormalDist

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
# IMPORT THE CONFIGURATION, THE DATA PATHS AND THE BASELINE ENGINE
from so import config
from so.paths import get_named_data_path_str
from so.runner.baselines import get_random_timing_seed_list, get_random_timing_weight_arr, run_weight_path_dict

"""
Random-Timing Tail Check (one-off; roadmap R3, audit S4, 2026-10-29)

The multiple-testing part of the verdict (so.core.multiple_testing.get_random_timing_p_float) fits a normal
distribution to the 100 registered random-timing draws and asks whether the path's total return is beyond the
1 - alpha / N point of that normal (alpha 0.05, N the designs tried: about 1.9e-4 for N = 260). 100 draws cannot show
a tail that far out, so the normal shape is an assumption. If the true distribution has a heavier right tail (a few
draws that happen to miss a crash), the normal is too lenient: a path could pass by luck more often than alpha / N.

This script measures it for one finished run. It reads the run's report.json and strategy_daily_equity.csv, loads the
development bars, and

    1. recomputes the 100 registered draws and checks they equal the report's (proof that it reproduces the referee);
    2. extends them to --draws draws (default 10,000; seeds config.RANDOM_SEED + 0 .. draws - 1);
    3. compares the empirical tail with the normal fit: quantiles 95 / 99 / 99.9 / 99.99 %, skewness, excess kurtosis,
       and how many draws exceed the normal's critical value for alpha / N (expected about draws * alpha / N).

Many more exceedances than expected mean the normal approximation is too lenient for this path; about as many or fewer
mean it is fair or conservative. Changes nothing; writes random_timing_tail_<run id>.md and .json to --output.
Only runs whose exposure is the realized position (trailing-stop and barrier engines: every daily experiment except
exp05) are supported, because their equity file holds that exposure.

    python scripts/check_random_timing_tail.py exp04_trend_exit_20261028190530034569 --draws 10000 --processes 4

Run it as Nicolas (it reads the development bars). It never reads the holdout or the quarantine.
"""

# THE PROCESS-LOCAL BARS AND SPAN OF A WORKER
_WORKER_STATE_DICT = {}


# FUNCTION: SET A WORKER'S BARS
def init_worker(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Development bars
        date1_in, date2_in: Span of the run
        exposure_arr_in (np.ndarray): The run's exposure path

    Returns:
        None
    """
    # ONE COPY PER PROCESS
    _WORKER_STATE_DICT.update({"ohlcv": ohlcv_array_dict_in, "date1": date1_in, "date2": date2_in,
                               "exposure": exposure_arr_in})


# FUNCTION: THE TOTAL RETURN OF ONE RANDOM-TIMING DRAW (SAME CODE AS so.runner.baselines.get_runner_baseline_dict)
def get_draw_return_float(seed_int_in, ohlcv_array_dict_in=None, date1_in=None, date2_in=None, exposure_arr_in=None):
    """
    Args:
        seed_int_in (int): Seed
        ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in: The span (None = the worker's)

    Returns:
        float: Total return of the draw
    """
    # THE BASELINE'S OWN LOOP BODY
    ohlcv = ohlcv_array_dict_in if ohlcv_array_dict_in is not None else _WORKER_STATE_DICT["ohlcv"]
    date1 = date1_in if date1_in is not None else _WORKER_STATE_DICT["date1"]
    date2 = date2_in if date2_in is not None else _WORKER_STATE_DICT["date2"]
    exposure_arr = exposure_arr_in if exposure_arr_in is not None else _WORKER_STATE_DICT["exposure"]
    random_arr = get_random_timing_weight_arr(exposure_arr, int(seed_int_in))
    initial_weight = float(random_arr[0]) if len(random_arr) and np.isfinite(random_arr[0]) else 0.0
    result_dict = run_weight_path_dict(ohlcv, date1, date2, random_arr, initial_weight, 0.0, config.INITIAL_CAPITAL,
                                       config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE)
    return float(result_dict["metric_dict"]["total_return"])


# FUNCTION: ALL DRAWS, IN SEED ORDER
def get_draw_return_list(seed_list_in, ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in, process_count_int_in=1):
    """
    Args:
        seed_list_in (list[int]): Seeds
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span
        exposure_arr_in (np.ndarray): Exposure path
        process_count_int_in (int): Worker processes (1 = in this process)

    Returns:
        list[float]: Total returns in seed order
    """
    # SPAWN WORKERS (WINDOWS) WITH ONE COPY OF THE BARS EACH
    if int(process_count_int_in) <= 1:
        return [get_draw_return_float(seed_int, ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in)
                for seed_int in seed_list_in]
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=int(process_count_int_in), initializer=init_worker,
                  initargs=(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in)) as pool:
        return list(pool.map(get_draw_return_float, list(seed_list_in), chunksize=50))


# FUNCTION: COMPARE THE EMPIRICAL TAIL WITH THE NORMAL FIT
def get_tail_summary_dict(return_list_in, path_return_in, design_count_int_in, alpha_in=None):
    """
    Args:
        return_list_in (list[float]): Draw returns
        path_return_in (float): The run's prior-only total return
        design_count_int_in (int): N (designs tried) from the run's report
        alpha_in (float | None): Family-wise alpha (None = config.RUNNER_MULTIPLE_TESTING_ALPHA)

    Returns:
        dict: Moments, quantiles (empirical vs normal), the critical value at alpha / N and its exceedances, p-values
    """
    # A NORMAL FIT EXACTLY AS THE VERDICT DOES (SAMPLE STANDARD DEVIATION)
    value_arr = np.asarray(return_list_in, dtype=float)
    count_int = int(len(value_arr))
    mean_float, std_float = float(value_arr.mean()), float(value_arr.std(ddof=1))
    centered_arr = value_arr - mean_float
    pop_std_float = float(np.sqrt(np.mean(centered_arr ** 2)))
    skew_float = float(np.mean(centered_arr ** 3) / pop_std_float ** 3) if pop_std_float > 0 else float("nan")
    excess_kurtosis_float = float(np.mean(centered_arr ** 4) / pop_std_float ** 4 - 3.0) if pop_std_float > 0 else float("nan")
    normal = NormalDist(mean_float, std_float) if std_float > 0 else None
    quantile_list = []
    for level_float in [0.95, 0.99, 0.999, 0.9999]:
        quantile_list.append({"level": level_float, "empirical": float(np.quantile(value_arr, level_float)),
                              "normal": float(normal.inv_cdf(level_float)) if normal else float("nan"),
                              "draws_beyond_level_expected": count_int * (1.0 - level_float)})
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA if alpha_in is None else alpha_in)
    tail_float = alpha_float / max(1, int(design_count_int_in))
    critical_float = float(normal.inv_cdf(1.0 - tail_float)) if normal else float("nan")
    exceed_int = int(np.sum(value_arr >= critical_float)) if normal else 0
    return {"draw_count": count_int, "mean": mean_float, "std": std_float, "skew": skew_float,
            "excess_kurtosis": excess_kurtosis_float, "max": float(value_arr.max()), "quantile_list": quantile_list,
            "design_count": int(design_count_int_in), "alpha": alpha_float, "tail_probability": tail_float,
            "normal_critical_return": critical_float, "draws_at_or_above_critical": exceed_int,
            "draws_at_or_above_critical_expected": count_int * tail_float,
            "path_return": float(path_return_in),
            "path_p_normal": float(1.0 - normal.cdf(float(path_return_in))) if normal else float("nan"),
            "path_p_empirical": float(np.mean(value_arr >= float(path_return_in)))}


# FUNCTION: A SHORT MARKDOWN REPORT
def get_tail_markdown_str(run_id_str_in, summary_dict_in, reproduced_dict_in):
    """
    Args:
        run_id_str_in (str): Run id
        summary_dict_in (dict): Output of get_tail_summary_dict
        reproduced_dict_in (dict): registered_count, max_abs_difference

    Returns:
        str: Markdown
    """
    # NUMBERS FIRST, THEN THE READING RULE (NO VERDICT IS CHANGED BY THIS FILE)
    s = summary_dict_in
    line_list = [f"# Random-timing tail check: {run_id_str_in}", "",
                 f"*Written {datetime.datetime.now():%Y-%m-%d %H:%M} by scripts/check_random_timing_tail.py. Diagnostic only.*", "",
                 f"Reproduction: the {reproduced_dict_in['registered_count']} registered draws recomputed; largest difference "
                 f"from report.json {reproduced_dict_in['max_abs_difference']:.2e}.", "",
                 f"Draws: {s['draw_count']}. Mean {s['mean']:.4f}, standard deviation {s['std']:.4f}, skewness {s['skew']:.3f}, "
                 f"excess kurtosis {s['excess_kurtosis']:.3f}, maximum {s['max']:.4f}.", "",
                 "| Level | Empirical quantile | Normal-fit quantile | Draws expected beyond |", "|---|---|---|---|"]
    for row_dict in s["quantile_list"]:
        line_list.append(f"| {row_dict['level']:.4f} | {row_dict['empirical']:.4f} | {row_dict['normal']:.4f} | "
                         f"{row_dict['draws_beyond_level_expected']:.1f} |")
    line_list += ["", f"Critical value the verdict uses (alpha {s['alpha']} / N {s['design_count']} = {s['tail_probability']:.2e}): "
                  f"normal fit {s['normal_critical_return']:.4f}. Draws at or above it: **{s['draws_at_or_above_critical']}** "
                  f"(expected if the normal were right: {s['draws_at_or_above_critical_expected']:.1f}).", "",
                  f"The run's own path: total return {s['path_return']:.4f}; p under the normal fit {s['path_p_normal']:.2e}; "
                  f"share of draws at or above it {s['path_p_empirical']:.4f}.", "",
                  "Reading: many more draws above the critical value than expected (or empirical upper quantiles above the "
                  "normal ones) mean the normal approximation is too lenient for this kind of path; about as many or fewer "
                  "mean it is fair or conservative. With 10,000 draws, about 2 exceedances are expected at N = 260, so only "
                  "a clear excess is evidence."]
    return "\n".join(line_list) + "\n"


# PARSE THE COMMAND
if __name__ == "__main__":
    # THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Compare the random-timing tail with its normal approximation for one run.")
    parser.add_argument("run_id", help="A finished run in store04_experiments/runs")
    parser.add_argument("--draws", type=int, default=10000, help="Random-timing draws (default 10,000)")
    parser.add_argument("--processes", type=int, default=4, help="Worker processes (default 4)")
    parser.add_argument("--output", default=None, help="Output folder (default store04_experiments/checks)")
    arg_dict = parser.parse_args()
    zone_str = get_named_data_path_str("LOCAL_EXPERIMENTZONE_PATH_STR")
    run_folder_str = os.path.join(zone_str, "runs", arg_dict.run_id)
    report_dict = json.loads(Path(run_folder_str, "report.json").read_text(encoding="utf-8"))
    baseline_dict = report_dict["baseline_dict"]
    if baseline_dict.get("exposure_source_str") != "realized_position":
        raise SystemExit("only runs whose exposure is the realized position are supported (not the fractional engine)")
    equity_pdf = pd.read_csv(os.path.join(run_folder_str, "strategy_daily_equity.csv"))
    exposure_arr = equity_pdf["in_position"].astype(bool).to_numpy().astype(float)
    exposure_arr[-1] = np.nan
    date1 = pd.Timestamp(report_dict["date1"]).date()
    date2 = pd.Timestamp(report_dict["date2"]).date()
    # THE DEVELOPMENT BARS (EMBARGO 1: A SUPERSET OF ANY RUN'S SPAN; THE ENGINE CUTS TO date1-date2)
    from so.core.development_span import get_development_ohlcv_dict
    ohlcv_array_dict = get_development_ohlcv_dict(1)["ohlcv_array_dict"]
    # 1. THE REGISTERED DRAWS MUST BE REPRODUCED
    registered_list = [float(value) for value in baseline_dict["random_timing_return_list"]]
    seed_list = get_random_timing_seed_list(int(arg_dict.draws))
    print(f"{arg_dict.run_id}: {len(seed_list)} draws on {arg_dict.processes} process(es) ...", flush=True)
    start_time = datetime.datetime.now()
    return_list = get_draw_return_list(seed_list, ohlcv_array_dict, date1, date2, exposure_arr, arg_dict.processes)
    difference_float = max((abs(a - b) for a, b in zip(return_list, registered_list)), default=float("nan"))
    if len(return_list) < len(registered_list) or not difference_float <= 1e-9:
        raise SystemExit(f"the registered draws were not reproduced (largest difference {difference_float}); nothing written")
    # 2-3. THE TAIL
    summary_dict = get_tail_summary_dict(return_list, float(report_dict["return_dict"]["strategy_total_return"]),
                                         int(report_dict["multiple_testing_dict"]["design_count"]))
    reproduced_dict = {"registered_count": len(registered_list), "max_abs_difference": difference_float}
    output_str = arg_dict.output or os.path.join(zone_str, "checks")
    os.makedirs(output_str, exist_ok=True)
    stem_str = os.path.join(output_str, f"random_timing_tail_{arg_dict.run_id}")
    Path(stem_str + ".md").write_text(get_tail_markdown_str(arg_dict.run_id, summary_dict, reproduced_dict), encoding="utf-8")
    Path(stem_str + ".json").write_text(json.dumps({"run_id": arg_dict.run_id, **reproduced_dict, **summary_dict,
                                                    "return_list": return_list}, indent=1), encoding="utf-8")
    print(Path(stem_str + ".md").read_text(encoding="utf-8"))
    print(f"wrote {stem_str}.md and .json in {(datetime.datetime.now() - start_time).total_seconds() / 60:.1f} minutes")
