import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

"""
Archived Experiment Reproduction (Nicolas only)

Only Nicolas may run this script. Agents must not (research-integrity.mdc, rule 1). It re-executes the archived
notebooks of exp01-exp08, exp12 and exp13 from copies, in a temporary experiment zone, and compares the printed
headline numbers with records/archived_reproduction_expected.csv.

It refuses to start unless SO_ALLOW_LEGACY_REPRODUCTION is exactly "1". It never writes the real experiment zone or
the real trial log: SO_EXPERIMENT_ZONE_PATH is pointed at a new temporary folder for the run (the trial log moves
with that zone). Raw data and pipeline caches stay in the normal data folder. Committed notebooks are copied and the
copies are executed; the committed files are not overwritten.

The run reads market data through 2026-05-13. That date sits inside the span the rolling holdout protects once a
window is opened. The run only recomputes numbers already recorded. It is not a holdout evaluation and it writes no
shared trial-log row.

exp09-exp11 were skipped and have no notebooks. exp13 reads exp12 step 02's replay periods from the experiment zone,
so a run that includes exp13 also runs that notebook. exp04-exp07 compare their quarters with exp03's saved schedule
only when that file is present; --only exp05 does not run exp03.
"""

# DEFINE THE WORKSPACE AND THE REAL EXPERIMENT ZONE (THE ZONE THIS SCRIPT MUST NOT WRITE)
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
REAL_EXPERIMENT_ZONE_STR = "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments"
EXPECTED_CSV_PATH = WORKSPACE_PATH / "records" / "archived_reproduction_expected.csv"
# DEFINE THE LEGACY FLAG (EXACT STRING; ANYTHING ELSE REFUSES)
LEGACY_FLAG_NAME_STR = "SO_ALLOW_LEGACY_REPRODUCTION"
LEGACY_FLAG_VALUE_STR = "1"
# DEFINE THE EXIT CODES (0 ONLY WHEN EVERY FIGURE MATCHES)
EXIT_OK_INT = 0
EXIT_MISMATCH_INT = 1
EXIT_REFUSED_INT = 2

# DEFINE THE NOTEBOOKS IN DEPENDENCY ORDER (SHORT NAME, PATH RELATIVE TO THE WORKSPACE)
NOTEBOOK_LIST = [
    ("exp01", "experiments/exp01_minute_entry/step01_model_dataset.ipynb"),
    ("exp01", "experiments/exp01_minute_entry/step02_signal_check.ipynb"),
    ("exp01", "experiments/exp01_minute_entry/step03_walk_forward.ipynb"),
    ("exp01", "experiments/exp01_minute_entry/step04_multivariate_check.ipynb"),
    ("exp02", "experiments/exp02_stop_reentry/step01_mechanism_check.ipynb"),
    ("exp02", "experiments/exp02_stop_reentry/step02_signal_check.ipynb"),
    ("exp02", "experiments/exp02_stop_reentry/step03_walk_forward.ipynb"),
    ("exp03", "experiments/exp03_ath_exit/step01_exploration.ipynb"),
    ("exp03", "experiments/exp03_ath_exit/step02_walk_forward.ipynb"),
    ("exp04", "experiments/exp04_trend_exit/step01_exploration.ipynb"),
    ("exp04", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb"),
    ("exp05", "experiments/exp05_vol_scaled_exposure/step01_exploration.ipynb"),
    ("exp05", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb"),
    ("exp06", "experiments/exp06_capped_regret_reentry/step01_exploration.ipynb"),
    ("exp06", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb"),
    ("exp07", "experiments/exp07_warning_lights_exit/step01_exploration.ipynb"),
    ("exp07", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb"),
    ("exp08", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb"),
    ("exp12", "experiments/exp12_vix_fear_reentry/step01_exploration.ipynb"),
    ("exp12", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb"),
    ("exp13", "experiments/exp13_e1m1_robustness/step01_stress_2005_2014.ipynb"),
    ("exp13", "experiments/exp13_e1m1_robustness/step02_neighbourhood.ipynb"),
    ("exp13", "experiments/exp13_e1m1_robustness/step03_placebo.ipynb"),
    ("exp13", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb"),
]
# DEFINE NOTEBOOKS A LATER EXPERIMENT READS FROM THE EXPERIMENT ZONE (ADDED WHEN THAT EXPERIMENT IS SELECTED)
REQUIRED_NOTEBOOK_DICT = {
    "exp13": ["experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb"],
}

# DEFINE ONE REGEX PER HEADLINE FIGURE (ONE CAPTURE GROUP; THE CELL TEXT MUST CONTAIN IT EXACTLY ONCE)
# THE EXPECTED VALUE AND ITS PRECISION LIVE IN records/archived_reproduction_expected.csv, COPIED FROM THE COMMITTED OUTPUTS
FIGURE_LIST = [
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step01_model_dataset.ipynb", "cell03", "dataset files", r"\(([0-9,]+) files\)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step02_signal_check.ipynb", "cell07", "test count", r"test_count:\t([0-9]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step02_signal_check.ipynb", "cell07", "training passes", r"train_pass_count:\t([0-9]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step02_signal_check.ipynb", "cell07", "signal count", r"(?m)^signal_count:\t([0-9]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step02_signal_check.ipynb", "cell07", "signal bins", r"(?m)^signal_bin_count:\t([0-9]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step02_signal_check.ipynb", "cell07", "null max signal bins", r"null_max_signal_bin_count:\t([0-9]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step02_signal_check.ipynb", "cell07", "p-value", r"null_p_value:\t([0-9.]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step03_walk_forward.ipynb", "cell08", "prior-only total return", r"Prior-only path \(\d+ quarters\):\t([0-9.]+)% vs buy & hold"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step03_walk_forward.ipynb", "cell08", "buy-and-hold total return", r"Prior-only path \(\d+ quarters\):\t[0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step03_walk_forward.ipynb", "cell08", "sign-test p-value", r"one-sided sign test p = ([0-9.]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step04_multivariate_check.ipynb", "cell05", "mean AUC", r"Real mean AUC over 21 distances:\t([0-9.]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step04_multivariate_check.ipynb", "cell06", "null max mean AUC", r"null_max_mean_auc:\t([0-9.]+)"),
    ("exp01_minute_entry", "experiments/exp01_minute_entry/step04_multivariate_check.ipynb", "cell06", "p-value", r"null_p_value:\t([0-9.]+)"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step01_mechanism_check.ipynb", "cell04", "buy-and-hold total return", r"Buy & hold:\ttotal return ([0-9.]+)%"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step01_mechanism_check.ipynb", "cell04", "buy-and-hold Sharpe", r"\| Sharpe ([0-9.]+) \|"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step01_mechanism_check.ipynb", "cell04", "buy-and-hold max drawdown", r"\| max drawdown (-?[0-9.]+)%"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step02_signal_check.ipynb", "cell05", "test count", r"test_count:\t([0-9]+)"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step02_signal_check.ipynb", "cell05", "signal count", r"(?m)^signal_count:\t([0-9]+)"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step03_walk_forward.ipynb", "cell08", "prior-only total return", r"Prior-only path \(\d+ quarters\):\t([0-9.]+)% vs buy & hold"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step03_walk_forward.ipynb", "cell08", "buy-and-hold total return", r"Prior-only path \(\d+ quarters\):\t[0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step03_walk_forward.ipynb", "cell08", "random re-entry median total return (fraction)", r"random_\* \(median of runs\)\s+([0-9.]+)"),
    ("exp02_stop_reentry", "experiments/exp02_stop_reentry/step03_walk_forward.ipynb", "cell08", "random re-entry runs beaten (share)", r"random_\* \(median of runs\)\s+[0-9.]+\s+([0-9.]+)"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step01_exploration.ipynb", "cell05", "buy-and-hold total return", r"Buy & hold:\ttotal return ([0-9.]+)%"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step02_walk_forward.ipynb", "cell08", "prior-only total return", r"Prior-only path \(\d+ quarters\):\t([0-9.]+)% vs buy & hold"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step02_walk_forward.ipynb", "cell08", "buy-and-hold total return", r"Prior-only path \(\d+ quarters\):\t[0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step02_walk_forward.ipynb", "cell08", "random-buyback median total return (fraction)", r"random_buyback_\* \(median of runs\)\s+([0-9.]+)"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step02_walk_forward.ipynb", "cell08", "random-buyback runs beaten (share)", r"(?m)^2\s+([0-9.]+)\s+20\.0"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step02_walk_forward.ipynb", "cell08", "random-exit median total return (fraction)", r"random_exit_\* \(median of runs\)\s+([0-9.]+)"),
    ("exp03_ath_exit", "experiments/exp03_ath_exit/step02_walk_forward.ipynb", "cell08", "random-exit runs beaten (share)", r"(?m)^3\s+([0-9.]+)\s+20\.0"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step01_exploration.ipynb", "cell04", "buy-and-hold total return", r"Buy & hold:\ttotal return ([0-9.]+)%"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step01_exploration.ipynb", "cell04", "exploration total return x=0 n=1 (fraction)", r"0\.00\s+1\s+([0-9.]+)\s+"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step01_exploration.ipynb", "cell05", "exploration exits x=0 n=1", r"x = 0%, n = 1:\t([0-9]+) episodes"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "prior-only total return", r"Total return:\tpath ([0-9.]+)% \| buy & hold"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "buy-and-hold total return", r"Total return:\tpath [0-9.]+% \| buy & hold ([0-9.]+)%"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "annualized log excess", r"Annualized log excess:\t(-?[0-9.]+)\t"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "log-excess interval low", r"6-month blocks\) \[(-?[0-9.]+),"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "log-excess interval high", r"6-month blocks\) \[-?[0-9.]+, (-?[0-9.]+)\]"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "random-exit median total return", r"Random exit \(median of 20\):\t([0-9.]+)%"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "random-exit runs beaten (percent)", r"Random exit \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "random-reentry median total return", r"Random re-entry \(median of 20\):\t([0-9.]+)%"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell06", "random-reentry runs beaten (percent)", r"Random re-entry \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp04_trend_exit", "experiments/exp04_trend_exit/step02_continuous_replay.ipynb", "cell07", "exits", r"Episodes:\t([0-9]+)"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step01_exploration.ipynb", "cell04", "Spearman correlation", r"Spearman correlation:\t([0-9.]+)"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "prior-only total return", r"Total return:\tpath ([0-9.]+)% \| buy & hold"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "buy-and-hold total return", r"Total return:\tpath [0-9.]+% \| buy & hold ([0-9.]+)%"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "mean weight", r"Mean weight in SPY:\t([0-9.]+)%"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "max drawdown", r"Max drawdown:\tpath (-?[0-9.]+)%"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "buy-and-hold max drawdown", r"Max drawdown:\tpath -?[0-9.]+% \| buy & hold (-?[0-9.]+)%"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "constant exposure total return", r"Constant exposure at [0-9.]+%:\t([0-9.]+)%"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "random-shift median total return", r"Random shifts \(median of 20\):\t([0-9.]+)%"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "random-shift runs beaten (percent)", r"Random shifts \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "annualized log excess", r"Annualized log excess:\t(-?[0-9.]+)\t"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "log-excess interval low", r"6-month blocks\) \[(-?[0-9.]+),"),
    ("exp05_vol_scaled_exposure", "experiments/exp05_vol_scaled_exposure/step02_continuous_replay.ipynb", "cell06", "log-excess interval high", r"6-month blocks\) \[-?[0-9.]+, (-?[0-9.]+)\]"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "prior-only total return", r"Total return:\tpath ([0-9.]+)% \| buy & hold"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "buy-and-hold total return", r"Total return:\tpath [0-9.]+% \| buy & hold ([0-9.]+)%"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "annualized log excess", r"Annualized log excess:\t(-?[0-9.]+)\t"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "log-excess interval low", r"6-month blocks\) \[(-?[0-9.]+),"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "log-excess interval high", r"6-month blocks\) \[-?[0-9.]+, (-?[0-9.]+)\]"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "random-exit median total return", r"Random exit \(median of 20\):\t([0-9.]+)%"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "random-exit runs beaten (percent)", r"Random exit \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "random-reentry median total return", r"Random re-entry \(median of 20\):\t([0-9.]+)%"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "random-reentry runs beaten (percent)", r"Random re-entry \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "buy-stop exits", r"buy-stop:\t([0-9]+)"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "episodes", r"Episodes:\t([0-9]+)\tbuy-stop:"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "right-exit gain term", r"\(1 - q\) x G = ([0-9.]+)"),
    ("exp06_capped_regret_reentry", "experiments/exp06_capped_regret_reentry/step02_continuous_replay.ipynb", "cell06", "wrong-exit cost term", r"q x \|L\| = ([0-9.]+)"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step01_exploration.ipynb", "cell04", "buy-and-hold total return", r"Buy & hold:\ttotal return ([0-9.]+)%"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step01_exploration.ipynb", "cell04", "exploration total return k=5 (fraction)", r"(?m)^2\s+2\s+5\s+([0-9.]+)\s+"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell05", "optimistic k=4 total return", r"\{'light_k': 4\}: total ([0-9.]+)% vs buy & hold"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell05", "optimistic buy-and-hold total return", r"\{'light_k': 4\}: total [0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "prior-only total return", r"Total return:\tpath ([0-9.]+)% \| buy & hold"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "buy-and-hold total return", r"Total return:\tpath [0-9.]+% \| buy & hold ([0-9.]+)%"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "annualized log excess", r"Annualized log excess:\t(-?[0-9.]+)\t"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "log-excess interval low", r"6-month blocks\) \[(-?[0-9.]+),"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "log-excess interval high", r"6-month blocks\) \[-?[0-9.]+, (-?[0-9.]+)\]"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "random-exit median total return", r"Random exit \(median of 20\):\t([0-9.]+)%"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "random-exit runs beaten (percent)", r"Random exit \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "random-reentry median total return", r"Random re-entry \(median of 20\):\t([0-9.]+)%"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell06", "random-reentry runs beaten (percent)", r"Random re-entry \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp07_warning_lights_exit", "experiments/exp07_warning_lights_exit/step02_continuous_replay.ipynb", "cell07", "exits", r"Episodes:\t([0-9]+)"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell06", "G1 signal bins", r"S1 = ([0-9]+) signal pairs"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell06", "G1 null max", r"max ([0-9]+)\s+p ="),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell06", "G1 p-value", r"max [0-9]+\s+p = ([0-9.]+)"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell07", "G2 dAUC", r"\tdAUC ([0-9.]+) \["),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell07", "G2 null max", r"G2 null:.*?max ([0-9.]+)"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell07", "G2 p-value", r"G2 null:.*?p = ([0-9.]+)"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell08", "G3 difference", r"D ([0-9.]+) \["),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell08", "G3 interval low", r"D [0-9.]+ \[([0-9.]+),"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell08", "G3 interval high", r"D [0-9.]+ \[[0-9.]+, ([0-9.]+)\]"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell09", "G4 training mean forward return", r"training:.*?mean ([0-9.]+)%"),
    ("exp08_vix_signal_check", "experiments/exp08_vix_signal_check/step01_vix_gate.ipynb", "cell09", "G4 validation mean forward return", r"validation:.*?mean ([0-9.]+)%"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "unmodified E1 total return", r"e1_total_pct': np\.float64\(([0-9.]+)\)"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "unmodified E1 exits", r"e1_exit_count': ([0-9]+)"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "unmodified E2 total return", r"e2_total_pct': np\.float64\(([0-9.]+)\)"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "unmodified E2 exits", r"e2_exit_count': ([0-9]+)"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "full-span buy-and-hold total return", r"buy_hold_full_pct': ([0-9.]+)"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "unmodified prior-only total return", r"Unmodified prior-only path:\t([0-9.]+)% vs buy & hold"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell05", "unmodified prior-only buy-and-hold total return", r"Unmodified prior-only path:\t[0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell06", "optimistic total return", r"AFTER THE FACT \(optimistic\):\tE1M1\t([0-9.]+)% vs buy & hold"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell06", "optimistic buy-and-hold total return", r"AFTER THE FACT \(optimistic\):\tE1M1\t[0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "prior-only total return", r"Total return:\tpath ([0-9.]+)% \| buy & hold"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "buy-and-hold total return", r"Total return:\tpath [0-9.]+% \| buy & hold ([0-9.]+)%"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "annualized log excess", r"Annualized log excess:\t(-?[0-9.]+)\t"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "log-excess interval low", r"6-month blocks\) \[(-?[0-9.]+),"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "log-excess interval high", r"6-month blocks\) \[-?[0-9.]+, (-?[0-9.]+)\]"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "random-exit median total return", r"Random exit \(median of 20\):\t([0-9.]+)%"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "random-exit runs beaten (percent)", r"Random exit \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "random-reentry median total return", r"Random re-entry \(median of 20\):\t([0-9.]+)%"),
    ("exp12_vix_fear_reentry", "experiments/exp12_vix_fear_reentry/step02_continuous_replay.ipynb", "cell07", "random-reentry runs beaten (percent)", r"Random re-entry \(median of 20\):\t[0-9.]+%\tpath beats ([0-9]+)% of runs"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "stress total return", r"R1 STRESS:\tE1M1 ([0-9.]+)% vs buy & hold"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "stress buy-and-hold total return", r"R1 STRESS:\tE1M1 [0-9.]+% vs buy & hold ([0-9.]+)%"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "variants beating buy-and-hold on DEV", r"([0-9]+) of 36 beat buy & hold on DEV"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "variants beating buy-and-hold on STRESS", r"of 36 beat buy & hold on DEV \(need 24\), ([0-9]+) on STRESS"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "p2", r"p2 = ([0-9.]+)"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "equity ratio without the best episode", r"equity ratio without the best episode ([0-9.]+)"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "delayed total return", r"delayed ([0-9.]+)%"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "five-cent total return", r"5-cent ([0-9.]+)%"),
    ("exp13_e1m1_robustness", "experiments/exp13_e1m1_robustness/step04_execution_and_episodes.ipynb", "cell07", "execution buy-and-hold total return", r"5-cent [0-9.]+% vs buy & hold ([0-9.]+)%"),
]


# FUNCTION: TELL WHETHER THE LEGACY FLAG IS SET FOR THIS PROCESS
def check_legacy_flag_bool():
    """
    True only when SO_ALLOW_LEGACY_REPRODUCTION is exactly "1".

    Returns:
        bool: Whether Nicolas has set the flag for this process
    """
    # COMPARE THE PROCESS ENVIRONMENT WITH THE REQUIRED STRING
    return os.environ.get(LEGACY_FLAG_NAME_STR) == LEGACY_FLAG_VALUE_STR


# FUNCTION: NORMALIZE A FOLDER PATH FOR COMPARISON
def get_normalized_path_str(path_str_in):
    """
    Absolute path with the trailing slash removed, compared case-insensitively on Windows.

    Args:
        path_str_in (str): Folder path

    Returns:
        str: Normalized path
    """
    # ABSOLUTE, CASE-FOLDED, NO TRAILING SLASH
    return os.path.normcase(os.path.abspath(path_str_in.rstrip("/\\")))


# FUNCTION: GET THE EXPERIMENT ZONE THAT SO_EXPERIMENT_ZONE_PATH MUST NOT BE
def get_default_experiment_zone_str():
    """
    store04_experiments under the data root (SO_DATA_PATH, or the nicodesktop folder).

    Returns:
        str: Default experiment zone, no trailing slash
    """
    # THE SAME DEFAULT so.paths USES WHEN THE OVERRIDE IS UNSET
    data_root_str = os.environ.get("SO_DATA_PATH", "C:/Users/nico/Desktop/stock_overflow_data").replace("\\", "/").rstrip("/")
    return data_root_str + "/store04_experiments"


# FUNCTION: TELL WHETHER A ZONE IS THE REAL OR THE DEFAULT EXPERIMENT FOLDER
def check_zone_is_safe_bool(zone_str_in):
    """
    False when the zone is the default store04_experiments or the real nicodesktop experiment folder.

    Args:
        zone_str_in (str): Proposed experiment zone

    Returns:
        bool: True when writes would not reach those folders
    """
    # REFUSE BOTH THE COMPUTED DEFAULT AND THE REAL FOLDER ON NICODESKTOP
    zone_norm_str = get_normalized_path_str(zone_str_in)
    default_norm_str = get_normalized_path_str(get_default_experiment_zone_str())
    real_norm_str = get_normalized_path_str(REAL_EXPERIMENT_ZONE_STR)
    return zone_norm_str != default_norm_str and zone_norm_str != real_norm_str


# FUNCTION: POINT THE EXPERIMENT ZONE AT A TEMPORARY FOLDER
def prepare_experiment_zone_str():
    """
    Sets SO_EXPERIMENT_ZONE_PATH to a new temporary folder, or keeps one that is already a safe override.

    Returns:
        str: Zone path ending in "/"

    Raises:
        SystemExit: The override is the real or the default experiment zone
    """
    # USE THE CALLER'S FOLDER WHEN IT IS SET; OTHERWISE MAKE A NEW ONE
    override_str = os.environ.get("SO_EXPERIMENT_ZONE_PATH", "").strip()
    if not override_str:
        override_str = tempfile.mkdtemp(prefix="so_archived_reproduction_")
    zone_str = override_str.replace("\\", "/").rstrip("/") + "/"
    # REFUSE THE REAL ZONE BEFORE ANY NOTEBOOK STARTS
    if not check_zone_is_safe_bool(zone_str):
        print("Refusing to run: SO_EXPERIMENT_ZONE_PATH is the real or the default experiment zone.")
        print("Point it at a new temporary folder. The real trial log was not written.")
        raise SystemExit(EXIT_REFUSED_INT)
    # CREATE THE FOLDER AND PUBLISH IT FOR THE NOTEBOOK KERNEL
    os.makedirs(zone_str, exist_ok=True)
    os.environ["SO_EXPERIMENT_ZONE_PATH"] = zone_str
    trial_log_path = Path(zone_str) / "trial_log.csv"
    if trial_log_path.exists():
        print(f"This temporary zone already has a trial log ({trial_log_path}). A re-run adds rows there only.")
    print(f"Experiment zone: {zone_str}")
    return zone_str


# FUNCTION: READ THE STDOUT AND TEXT/PLAIN OF ONE CELL
def get_notebook_cell_text_str(notebook_path_in, cell_id_str_in, notebook_cache_dict_in=None):
    """
    Joins the cell's stdout streams and text/plain results. HTML is left out (it repeats the text).

    Args:
        notebook_path_in (str | Path): Notebook path
        cell_id_str_in (str): Cell id
        notebook_cache_dict_in (dict | None): Optional path -> notebook dict, so a notebook is parsed once

    Returns:
        str | None: The text, or None when the cell is missing
    """
    # READ THE NOTEBOOK ONCE PER PATH
    cache_key_str = str(notebook_path_in)
    if notebook_cache_dict_in is not None and cache_key_str in notebook_cache_dict_in:
        notebook_dict = notebook_cache_dict_in[cache_key_str]
    else:
        notebook_dict = json.loads(Path(notebook_path_in).read_text(encoding="utf-8"))
        if notebook_cache_dict_in is not None:
            notebook_cache_dict_in[cache_key_str] = notebook_dict
    # FIND THE CELL
    for cell_dict in notebook_dict["cells"]:
        if cell_dict.get("id") != cell_id_str_in:
            continue
        part_list = []
        for output_dict in cell_dict.get("outputs", []):
            # STDOUT OF A PRINT
            if output_dict.get("output_type") == "stream" and output_dict.get("name") == "stdout":
                text = output_dict.get("text", "")
                part_list.append("".join(text) if isinstance(text, list) else text)
            # TEXT VERSION OF A DISPLAYED TABLE
            elif output_dict.get("output_type") in ("execute_result", "display_data"):
                plain = output_dict.get("data", {}).get("text/plain")
                if plain:
                    part_list.append("".join(plain) if isinstance(plain, list) else plain)
        return "\n".join(part_list)
    # THE CELL IS NOT IN THIS NOTEBOOK
    return None


# FUNCTION: PULL THE SINGLE CAPTURED NUMBER OUT OF A CELL
def get_extracted_value_str(cell_text_str_in, pattern_str_in):
    """
    The one match of a pattern that has one capture group. Zero or several matches return None.

    Args:
        cell_text_str_in (str | None): Cell text
        pattern_str_in (str): Regular expression with one group

    Returns:
        str | None: The captured text, or None
    """
    # A MISSING CELL CANNOT MATCH
    if cell_text_str_in is None:
        return None
    # REQUIRE EXACTLY ONE MATCH SO A LOOSE PATTERN CANNOT PICK A NEIGHBOUR
    found_list = re.findall(pattern_str_in, cell_text_str_in, flags=re.MULTILINE)
    if len(found_list) != 1 or isinstance(found_list[0], tuple):
        return None
    return found_list[0]


# FUNCTION: ROUND A PRINTED NUMBER TO A RECORDED PRECISION
def get_quantized_decimal(value_str_in, precision_int_in):
    """
    The printed number rounded half-up to the recorded number of decimal places. Commas are removed.

    Args:
        value_str_in (str): Printed number, optional thousands commas
        precision_int_in (int): Decimal places

    Returns:
        Decimal: The rounded number
    """
    # DROP THOUSANDS SEPARATORS AND ROUND HALF UP
    cleaned_str = value_str_in.replace(",", "").strip()
    quantum_str = "1" if int(precision_int_in) <= 0 else "0." + "0" * (int(precision_int_in) - 1) + "1"
    return Decimal(cleaned_str).quantize(Decimal(quantum_str), rounding=ROUND_HALF_UP)


# FUNCTION: COMPARE AN EXPECTED NUMBER WITH A REPRODUCED NUMBER
def check_values_match_bool(expected_str_in, reproduced_str_in, precision_int_in):
    """
    True when both numbers round to the same value at the recorded precision.

    Args:
        expected_str_in (str): Expected printed number
        reproduced_str_in (str | None): Number taken from the executed notebook
        precision_int_in (int): Decimal places

    Returns:
        bool: Whether they match
    """
    # A MISSING EXTRACTION IS A MISMATCH
    if reproduced_str_in is None or str(reproduced_str_in).strip() == "":
        return False
    return get_quantized_decimal(expected_str_in, precision_int_in) == get_quantized_decimal(reproduced_str_in, precision_int_in)


# FUNCTION: READ THE EXPECTED TABLE
def read_expected_row_list(csv_path_in):
    """
    Rows of the expected CSV. Values stay strings so trailing zeros are kept.

    Args:
        csv_path_in (str | Path): CSV path

    Returns:
        list[dict]: Rows
    """
    # READ EVERY ROW
    with open(csv_path_in, newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


# FUNCTION: MAP (NOTEBOOK, CELL, LABEL) TO ITS REGEX
def get_figure_pattern_dict(figure_list_in=None):
    """
    The headline patterns shipped with this script.

    Args:
        figure_list_in (list | None): Replacement list (the synthetic tests pass a small one)

    Returns:
        dict: (notebook, cell id, label) -> regex
    """
    # THE SHIPPED LIST, UNLESS A TEST PASSES ITS OWN
    source_list = FIGURE_LIST if figure_list_in is None else figure_list_in
    return {(notebook_str, cell_id_str, label_str): pattern_str for _, notebook_str, cell_id_str, label_str, pattern_str in source_list}


# FUNCTION: CHOOSE THE NOTEBOOKS FOR THIS RUN
def get_selected_notebook_list(only_list_in):
    """
    The dependency-ordered notebooks. --only keeps those experiments and the notebooks a kept experiment reads.

    Args:
        only_list_in (list[str] | None): Short names such as exp05, or full folder names

    Returns:
        list[tuple]: (short name, relative path)
    """
    # THE FULL ORDER WHEN NOTHING WAS ASKED FOR
    if not only_list_in:
        return list(NOTEBOOK_LIST)
    # ACCEPT exp05 AND exp05_vol_scaled_exposure
    wanted_set = set()
    for token_str in only_list_in:
        short_str = token_str.split("_", 1)[0]
        known_set = {short_str for short_str, _ in NOTEBOOK_LIST}
        if short_str not in known_set:
            print(f"Unknown experiment {token_str}. Known: {', '.join(sorted(known_set))}")
            raise SystemExit(EXIT_REFUSED_INT)
        wanted_set.add(short_str)
    # ADD A NOTEBOOK A SELECTED EXPERIMENT READS FROM THE EXPERIMENT ZONE
    extra_set = set()
    for short_str in wanted_set:
        for notebook_str in REQUIRED_NOTEBOOK_DICT.get(short_str, []):
            extra_set.add(notebook_str)
            print(f"Including {notebook_str} because {short_str} reads it from the experiment zone.")
    # KEEP THE MASTER ORDER
    return [(short_str, notebook_str) for short_str, notebook_str in NOTEBOOK_LIST if short_str in wanted_set or notebook_str in extra_set]


# FUNCTION: FIND THE JUPYTER EXECUTABLE
def get_jupyter_command_list(notebook_path_in):
    """
    nbconvert on one notebook: no timeout, kernel venv-main.

    Args:
        notebook_path_in (Path): The copy to execute

    Returns:
        list[str]: Command
    """
    # PREFER THE VENV JUPYTER; OTHERWISE THE INTERPRETER'S JUPYTER MODULE
    jupyter_path = WORKSPACE_PATH / "venv-main" / "Scripts" / "jupyter.exe"
    argument_list = ["nbconvert", "--to", "notebook", "--execute", "--inplace", "--ExecutePreprocessor.timeout=-1",
                     "--ExecutePreprocessor.kernel_name=venv-main", str(notebook_path_in)]
    if jupyter_path.exists():
        return [str(jupyter_path)] + argument_list
    return [sys.executable, "-m", "jupyter"] + argument_list


# FUNCTION: EXECUTE ONE NOTEBOOK COPY
def execute_notebook_copy_bool(source_path_in, copy_path_in):
    """
    Runs nbconvert on the copy. The source bytes must be unchanged afterwards.

    Args:
        source_path_in (Path): Committed notebook
        copy_path_in (Path): Copy that may be overwritten with outputs

    Returns:
        bool: True when nbconvert exited 0 and the committed file is unchanged
    """
    # HASH THE COMMITTED FILE BEFORE THE RUN
    before_bytes = source_path_in.read_bytes()
    command_list = get_jupyter_command_list(copy_path_in)
    # THE KERNEL INHERITS THE ZONE AND THE LEGACY FLAG
    result = subprocess.run(command_list, cwd=str(WORKSPACE_PATH), env=os.environ.copy(), capture_output=True, text=True, encoding="utf-8", errors="replace")
    after_bytes = source_path_in.read_bytes()
    # A CHANGE TO THE COMMITTED NOTEBOOK IS A FAILURE EVEN IF NBCONVERT SAID IT SUCCEEDED
    if after_bytes != before_bytes:
        print(f"The committed notebook changed during the run: {source_path_in}")
        return False
    if result.returncode != 0:
        print(f"nbconvert failed ({result.returncode}) for {copy_path_in}")
        tail_str = (result.stderr or result.stdout or "")[-2000:]
        if tail_str:
            print(tail_str)
        return False
    return True


# FUNCTION: COMPARE ONE TABLE OF FIGURES WITH NOTEBOOK OUTPUTS
def compare_figure_row_list(expected_row_list_in, notebook_root_path_in, pattern_dict_in):
    """
    Extracts each expected figure from the notebook under the root and records expected, reproduced, match.

    Args:
        expected_row_list_in (list[dict]): Expected rows (value and precision are strings)
        notebook_root_path_in (Path): Workspace, or a fixture folder
        pattern_dict_in (dict): (notebook, cell id, label) -> regex

    Returns:
        list[dict]: Comparison rows
    """
    # CACHE EACH NOTEBOOK AND EACH CELL'S TEXT
    notebook_cache_dict = {}
    cell_text_dict = {}
    comparison_row_list = []
    for expected_row in expected_row_list_in:
        notebook_str = expected_row["notebook"]
        cell_id_str = expected_row["cell_id"]
        label_str = expected_row["label"]
        # A FIXTURE MAY CARRY ITS OWN PATTERN; THE ARCHIVED TABLE USES THE SHIPPED LIST
        pattern_str = expected_row.get("pattern") or pattern_dict_in.get((notebook_str, cell_id_str, label_str))
        cache_key = (notebook_str, cell_id_str)
        if cache_key not in cell_text_dict:
            cell_text_dict[cache_key] = get_notebook_cell_text_str(notebook_root_path_in / notebook_str, cell_id_str, notebook_cache_dict)
        reproduced_str = None if not pattern_str else get_extracted_value_str(cell_text_dict[cache_key], pattern_str)
        match_bool = bool(pattern_str) and check_values_match_bool(expected_row["value"], reproduced_str, expected_row["precision"])
        comparison_row_list.append({
            "experiment": expected_row["experiment"],
            "notebook": notebook_str,
            "cell_id": cell_id_str,
            "label": label_str,
            "expected": expected_row["value"],
            "reproduced": "" if reproduced_str is None else reproduced_str,
            "precision": expected_row["precision"],
            "match": "True" if match_bool else "False",
        })
    return comparison_row_list


# FUNCTION: WRITE THE COMPARISON CSV
def write_comparison_csv(comparison_row_list_in, report_path_in):
    """
    Writes expected, reproduced and match for every figure.

    Args:
        comparison_row_list_in (list[dict]): Comparison rows
        report_path_in (Path): Output CSV

    Returns:
        None
    """
    # CREATE THE FOLDER AND WRITE CRLF ROWS
    report_path_in.parent.mkdir(parents=True, exist_ok=True)
    field_list = ["experiment", "notebook", "cell_id", "label", "expected", "reproduced", "precision", "match"]
    with open(report_path_in, "w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=field_list, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(comparison_row_list_in)


# FUNCTION: PRINT MATCHES AND MISMATCHES PER EXPERIMENT
def print_comparison_summary(comparison_row_list_in):
    """
    One line per experiment, then the totals. The caller prints the run time.

    Args:
        comparison_row_list_in (list[dict]): Comparison rows

    Returns:
        bool: True when every row matches
    """
    # COUNT BY EXPERIMENT, KEEPING THE TABLE ORDER
    summary_dict = {}
    for row_dict in comparison_row_list_in:
        count_dict = summary_dict.setdefault(row_dict["experiment"], {"match": 0, "mismatch": 0})
        if row_dict["match"] == "True":
            count_dict["match"] += 1
        else:
            count_dict["mismatch"] += 1
    # PRINT EACH EXPERIMENT
    for experiment_str, count_dict in summary_dict.items():
        print(f"{experiment_str}: {count_dict['match']} match, {count_dict['mismatch']} mismatch")
    match_int = sum(count_dict["match"] for count_dict in summary_dict.values())
    mismatch_int = sum(count_dict["mismatch"] for count_dict in summary_dict.values())
    print(f"Total: {match_int} match, {mismatch_int} mismatch, {len(comparison_row_list_in)} numbers")
    return mismatch_int == 0 and len(comparison_row_list_in) > 0


# FUNCTION: RUN THE ARCHIVED NOTEBOOKS AND COMPARE THEM
def run_archived_reproduction_int(only_list_in, report_path_in):
    """
    Copies each selected notebook, executes the copy, and compares the figures those notebooks print.

    Args:
        only_list_in (list[str] | None): --only tokens
        report_path_in (Path): Comparison CSV

    Returns:
        int: 0 when everything matches, 1 otherwise
    """
    # THE ZONE IS SET BEFORE ANY NOTEBOOK PROCESS STARTS
    prepare_experiment_zone_str()
    print("This run reads market data through 2026-05-13, inside the new holdout window, to recompute numbers already recorded.")
    print("It is not a holdout evaluation and it does not write the shared trial log.")
    selected_list = get_selected_notebook_list(only_list_in)
    copy_root_path = Path(tempfile.mkdtemp(prefix="so_archived_notebook_"))
    print(f"Notebook copies: {copy_root_path}")
    failed_notebook_str = ""
    # EXECUTE IN DEPENDENCY ORDER; STOP AT THE FIRST FAILURE
    for short_str, notebook_str in selected_list:
        source_path = WORKSPACE_PATH / notebook_str
        copy_path = copy_root_path / f"{short_str}__{source_path.name}"
        shutil.copy2(source_path, copy_path)
        print(f"Executing {notebook_str}")
        if not execute_notebook_copy_bool(source_path, copy_path):
            failed_notebook_str = notebook_str
            break
        # KEEP THE EXECUTED COPY UNDER THE NAME THE EXPECTED TABLE USES
        named_path = copy_root_path / notebook_str
        named_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(copy_path, named_path)
    # COMPARE EVERY FIGURE WHOSE NOTEBOOK FINISHED
    executed_set = {notebook_str for _, notebook_str in selected_list if (copy_root_path / notebook_str).exists()}
    expected_row_list = [row_dict for row_dict in read_expected_row_list(EXPECTED_CSV_PATH) if row_dict["notebook"] in executed_set]
    comparison_row_list = compare_figure_row_list(expected_row_list, copy_root_path, get_figure_pattern_dict()) if expected_row_list else []
    # A FAILED NOTEBOOK IS A MISMATCH EVEN WHEN THE FIGURES ALREADY COMPARED MATCHED
    if failed_notebook_str:
        comparison_row_list.append({
            "experiment": failed_notebook_str.split("/")[1],
            "notebook": failed_notebook_str,
            "cell_id": "",
            "label": "notebook execution",
            "expected": "exit 0",
            "reproduced": "nbconvert failed",
            "precision": "0",
            "match": "False",
        })
    if not comparison_row_list:
        print("Nothing was compared.")
        return EXIT_MISMATCH_INT
    write_comparison_csv(comparison_row_list, report_path_in)
    print(f"Report: {report_path_in}")
    matched_bool = print_comparison_summary(comparison_row_list)
    return EXIT_OK_INT if matched_bool and not failed_notebook_str else EXIT_MISMATCH_INT


# FUNCTION: COMPARE A FIXTURE FOLDER WITHOUT EXECUTING ANYTHING
def run_fixture_comparison_int(fixture_path_in, report_path_in):
    """
    Compares notebooks that already have outputs. Used by the synthetic tests. Does not call nbconvert.

    Args:
        fixture_path_in (Path): Folder with expected.csv and the notebooks it names
        report_path_in (Path): Comparison CSV

    Returns:
        int: 0 when every row matches
    """
    # STILL REFUSE A ZONE THAT IS THE REAL EXPERIMENT FOLDER
    prepare_experiment_zone_str()
    expected_row_list = read_expected_row_list(fixture_path_in / "expected.csv")
    comparison_row_list = compare_figure_row_list(expected_row_list, fixture_path_in, get_figure_pattern_dict())
    write_comparison_csv(comparison_row_list, report_path_in)
    print(f"Report: {report_path_in}")
    return EXIT_OK_INT if print_comparison_summary(comparison_row_list) else EXIT_MISMATCH_INT


# FUNCTION: DEFAULT REPORT PATH
def get_default_report_path():
    """
    records/archived_reproduction_<YYYYMMDD_HHMM>.csv

    Returns:
        Path: Report path
    """
    # LOCAL TIME, MINUTE RESOLUTION, AS THE RECORD NAME
    stamp_str = time.strftime("%Y%m%d_%H%M")
    return WORKSPACE_PATH / "records" / f"archived_reproduction_{stamp_str}.csv"


# FUNCTION: PARSE ARGUMENTS AND RUN
def main(argv_list_in=None):
    """
    Refuses without the legacy flag. --list prints the order. --fixtures compares a synthetic folder.

    Args:
        argv_list_in (list[str] | None): Arguments, without the program name

    Returns:
        int: Process exit code
    """
    # UTF-8 SO THE SUMMARY CAN BE PIPED ON WINDOWS
    sys.stdout.reconfigure(encoding="utf-8")
    print("Only Nicolas may run scripts/reproduce_archived.py. Agents must not.")
    # THE FLAG IS CHECKED BEFORE ANY FOLDER IS CREATED AND BEFORE ANY NOTEBOOK IS READ FOR EXECUTION
    if not check_legacy_flag_bool():
        print('Refusing to run: set SO_ALLOW_LEGACY_REPRODUCTION=1 for this process only.')
        print("No notebook was executed. The real experiment zone and the real trial log were not written.")
        return EXIT_REFUSED_INT
    parser = argparse.ArgumentParser(description="Reproduce the archived experiments (Nicolas only).")
    parser.add_argument("--list", action="store_true", help="Print the notebooks in dependency order and exit")
    parser.add_argument("--only", nargs="+", default=None, help="Short names, for example: --only exp05 exp06")
    parser.add_argument("--fixtures", default=None, help="Compare a folder of already-executed notebooks (synthetic tests)")
    parser.add_argument("--report", default=None, help="Comparison CSV path")
    argument_ns = parser.parse_args(argv_list_in)
    start_time = time.perf_counter()
    # LISTING DOES NOT CREATE A ZONE AND DOES NOT EXECUTE
    if argument_ns.list:
        for short_str, notebook_str in get_selected_notebook_list(argument_ns.only):
            print(f"{short_str}\t{notebook_str}")
        return EXIT_OK_INT
    # FIXTURES ARE ALREADY EXECUTED; THE REAL RUN CALLS NBCONVERT ON COPIES
    if argument_ns.fixtures:
        fixture_path = Path(argument_ns.fixtures)
        report_path = Path(argument_ns.report) if argument_ns.report else fixture_path / "report.csv"
        exit_int = run_fixture_comparison_int(fixture_path, report_path)
    else:
        report_path = Path(argument_ns.report) if argument_ns.report else get_default_report_path()
        exit_int = run_archived_reproduction_int(argument_ns.only, report_path)
    # THE RUN TIME COVERS THE NOTEBOOKS, OR THE FIXTURE COMPARISON
    print(f"Run time: {time.perf_counter() - start_time:.1f} s")
    return exit_int


# RUN THE SCRIPT
if __name__ == "__main__":
    sys.exit(main())
