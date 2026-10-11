# IMPORT THE EXPERIMENT CONFIGURATION
from experiments._template import config as exp_config

"""
Holdout Design (template)

A new experiment copies this module. so.core.holdout.run_holdout_evaluation calls fit only on sessions strictly before
the decision session, on the schedule in DESIGN_REFIT_RULE, and decide for the target exposure in [0, 1]. Only Nicolas
runs the evaluation, once per window. This template holds a constant full exposure so the shape of the interface is
visible; replace fit and decide with the experiment's rule.
"""

# DEFINE THE REFIT SCHEDULE (EVERY SESSION, TRAILING 6 MONTHS)
DESIGN_REFIT_RULE = {"every_sessions": 1, "train_window": "6M"}
# COPY THE NAME AND THE PROTOCOL VERSION (THE TRIAL LOG AND THE DESIGN HASH READ THEM)
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION

# FUNCTION: FIT ON DATA STRICTLY BEFORE THE DECISION SESSION
def fit(frame_pdf_in, exclusive_date_in):
    """
    Fits on the frame the runner built (sessions inside the training window and strictly before exclusive_date_in).

    Args:
        frame_pdf_in (pd.DataFrame): Sessions the fit may see (date, ...)
        exclusive_date_in (datetime.date): Decision session, not included

    Returns:
        dict: Model state. last_date_seen, when present, must be strictly before the decision session
    """
    # RECORD THE LAST DATE ACTUALLY IN THE FRAME
    last_date = None if len(frame_pdf_in) == 0 else frame_pdf_in["date"].max()
    # RETURN A CONSTANT-EXPOSURE STATE
    return {"last_date_seen": last_date, "exposure": 1.0}

# FUNCTION: DECIDE THE TARGET EXPOSURE
def decide(model_state_dict_in, session_date_in, feature_dict_in):
    """
    Target exposure in [0, 1] from the model state and from features known before the decision.

    Args:
        model_state_dict_in (dict): Output of fit
        session_date_in (datetime.date): Decision session
        feature_dict_in (dict): Features known before the decision (the runner passes the prior close)

    Returns:
        float: Target exposure
    """
    # RETURN THE STATE'S EXPOSURE
    return float(model_state_dict_in["exposure"])
