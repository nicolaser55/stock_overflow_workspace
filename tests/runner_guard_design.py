import numpy as np
# IMPORT THE SHARED CONFIGURATION AND A CACHE READER THE DESIGN SHOULD NOT REACH (TEST-ONLY DESIGNS)
from so import config as so_config
from so.core.local_file_management import read_csv_file_from_path

"""
Synthetic designs for the design-code guard tests (audit B2). They live under tests/, so the AST preflight skips them
and only the runtime guard stands in their way.
"""

# THE FILE A READING DESIGN TRIES TO OPEN (SET BY THE TEST)
TARGET_FILE_PATH_STR = None


# CLASS: OPENS A DATA FILE FROM decide()
class ReadingDesign:
    """Reads a CSV under the data root through a shared helper."""

    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: READ AROUND THE VIEW
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: Weight
        """
        # THE GUARD MUST REFUSE THIS
        read_csv_file_from_path(TARGET_FILE_PATH_STR, alert_in=False)
        return 1.0


# CLASS: REWRITES A SHARED CONSTANT FROM decide()
class RewritingDesign:
    """Sets the entry slippage to zero on its first call."""

    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: CHANGE THE COSTS EVERY RUN USES
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: Weight
        """
        # THE MODULE GUARD MUST STOP THE RUN
        so_config.ENTRY_SLIPPAGE_PER_SHARE = 0.0
        return 1.0


# CLASS: A CLEAN DESIGN
class CleanDesign:
    """Always fully invested."""

    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: WEIGHT 1
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: Weight
        """
        # NOTHING OUTSIDE THE VIEW
        return float(np.float64(1.0))
