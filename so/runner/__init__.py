"""
Point-in-time runner (infrastructure steps 4a, 4b-1 and 4b-2a).

At each decision moment the design is shown only what could have been seen then. The runner walks time forward,
fills NaN/NaT buffers up to that moment, and calls the design with a DecisionView that slices those buffers. The
position engine turns the decision into trades. Daily mode is 4a (15:58 decision, 15:59 fill). 4b-1 adds candidate
streams, period scores, pooled prior-only selection, trial logging, checkpoints, parallel runs, baselines, the
shared verdict, look-ahead and holdout through the same stream. 4b-2a adds the barrier and trailing-stop engines
(numba session loops) and an engine-state snapshot on the view. Minute mode is 4b-2b.
"""

# RE-EXPORT THE PUBLIC 4A, 4B-1A, 4B-1B, 4B-1C AND 4B-1D SURFACE
from so.runner.view import DecisionView, get_decision_view
from so.runner.engine import (Engine, FractionalWeightEngine, TrailingStopEngine, BarrierEngine, get_decision_dict,
                              ENGINE_FRACTIONAL_STR, ENGINE_TRAILING_STOP_STR, ENGINE_BARRIER_STR)
from so.runner.loop import MODE_DAILY_STR, MODE_MINUTE_STR, run_daily_dict, run_engine_decisions_dict, DailyLoop
from so.runner.preflight import check_design_file, check_design_source
from so.runner.periods import check_quarantine_refused, get_development_run_period_pdf
from so.runner.selection import (get_runner_selection_pdf, get_governing_candidate_dict,
                                 run_prior_only_from_decisions_dict, get_buy_hold_period_return_dict)
from so.runner.run import (run_development_dict, run_holdout_dict, get_trial_id_str, MAX_CANDIDATE_PROCESS_COUNT,
                           check_clean_tree, RESUME_IDENTITY_MESSAGE_STR, CLEAN_TREE_MESSAGE_STR, get_code_hash_str,
                           get_guarded_code_folder_list)
from so.runner.baselines import (get_runner_baseline_dict, get_random_timing_weight_arr, get_random_timing_seed_list,
                                 run_weight_path_dict)
from so.runner.verdict import (get_runner_verdict_dict, get_return_verdict_dict, get_consistency_verdict_dict,
                               get_baseline_verdict_dict, LOOK_AHEAD_PENDING_STR, LOOK_AHEAD_PASS_STR,
                               LOOK_AHEAD_FAIL_STR, EMAIL_WORTHY_STR, NOT_EMAIL_WORTHY_STR, MANIFEST_FILE_STR)
from so.runner.lookahead import (run_lookahead_check_dict, get_lookahead_cut_date_list, LOOKAHEAD_FILE_STR,
                                 KIND_TRUNCATION_STR, KIND_PERTURBATION_STR)

# NAMES THE PACKAGE EXPORTS
__all__ = ["DecisionView", "get_decision_view", "Engine", "FractionalWeightEngine", "TrailingStopEngine",
           "BarrierEngine", "get_decision_dict", "ENGINE_FRACTIONAL_STR", "ENGINE_TRAILING_STOP_STR",
           "ENGINE_BARRIER_STR",
           "MODE_DAILY_STR", "MODE_MINUTE_STR", "run_daily_dict", "run_engine_decisions_dict", "DailyLoop",
           "check_design_file", "check_design_source", "check_quarantine_refused", "get_development_run_period_pdf",
           "get_runner_selection_pdf", "get_governing_candidate_dict", "run_prior_only_from_decisions_dict",
           "get_buy_hold_period_return_dict", "run_development_dict", "run_holdout_dict", "get_trial_id_str",
           "MAX_CANDIDATE_PROCESS_COUNT",
           "check_clean_tree", "RESUME_IDENTITY_MESSAGE_STR", "CLEAN_TREE_MESSAGE_STR", "get_code_hash_str",
           "get_guarded_code_folder_list", "get_runner_baseline_dict", "get_random_timing_weight_arr",
           "get_random_timing_seed_list", "run_weight_path_dict", "get_runner_verdict_dict", "get_return_verdict_dict",
           "get_consistency_verdict_dict", "get_baseline_verdict_dict", "LOOK_AHEAD_PENDING_STR", "LOOK_AHEAD_PASS_STR",
           "LOOK_AHEAD_FAIL_STR", "EMAIL_WORTHY_STR", "NOT_EMAIL_WORTHY_STR", "MANIFEST_FILE_STR",
           "run_lookahead_check_dict", "get_lookahead_cut_date_list", "LOOKAHEAD_FILE_STR",
           "KIND_TRUNCATION_STR", "KIND_PERTURBATION_STR"]
