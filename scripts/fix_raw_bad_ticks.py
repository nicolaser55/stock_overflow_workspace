# IMPORT THE BAD TICK MODULE
from so.core.bad_ticks import main

"""
Command line entry of the bad tick correction (logic and documentation in so/core/bad_ticks.py).

    python scripts/fix_raw_bad_ticks.py              # dry run
    python scripts/fix_raw_bad_ticks.py --apply      # back up, correct, verify, log
"""

# RUN THE SCRIPT
if __name__ == "__main__":
    # CALL THE MAIN FUNCTION
    main()
