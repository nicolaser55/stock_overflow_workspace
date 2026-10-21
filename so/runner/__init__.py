"""
Point-in-time runner (infrastructure step 4a).

The design sees a DecisionView at each decision moment. The loop is daily. The one engine is fractional weight.
Minute mode and the barrier / trailing-stop engines are 4b.
"""

# RE-EXPORT THE PUBLIC 4A SURFACE
from so.runner.view import DecisionView, get_decision_view
from so.runner.engine import Engine, FractionalWeightEngine, get_decision_dict
from so.runner.loop import MODE_DAILY_STR, MODE_MINUTE_STR, run_daily_dict

# NAMES THE PACKAGE EXPORTS
__all__ = ["DecisionView", "get_decision_view", "Engine", "FractionalWeightEngine", "get_decision_dict",
           "MODE_DAILY_STR", "MODE_MINUTE_STR", "run_daily_dict"]
