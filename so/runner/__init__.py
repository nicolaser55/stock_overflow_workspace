"""
Point-in-time runner (infrastructure step 4a).

At each decision moment the design is shown only what could have been seen then. The runner walks time forward,
fills NaN/NaT buffers up to that moment, and calls the design with a DecisionView that slices those buffers. The
position engine turns the decision into trades. Daily mode is 4a (15:58 decision, 15:59 fill, fractional-weight
engine). Minute mode, barrier and trailing-stop engines, selection, baselines and holdout-through-the-runner are 4b.
"""

# RE-EXPORT THE PUBLIC 4A SURFACE
from so.runner.view import DecisionView, get_decision_view
from so.runner.engine import Engine, FractionalWeightEngine, get_decision_dict
from so.runner.loop import MODE_DAILY_STR, MODE_MINUTE_STR, run_daily_dict
from so.runner.preflight import check_design_file, check_design_source

# NAMES THE PACKAGE EXPORTS
__all__ = ["DecisionView", "get_decision_view", "Engine", "FractionalWeightEngine", "get_decision_dict",
           "MODE_DAILY_STR", "MODE_MINUTE_STR", "run_daily_dict", "check_design_file", "check_design_source"]
