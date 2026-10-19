import os
import tempfile

"""
Temporary data root for a test suite.

Every suite calls assert_temporary_data_root at import, after it has pointed SO_DATA_PATH at its own
temporary folder when it uses one. The real data folder is never the root.
"""

# FUNCTION: REQUIRE THE DATA ROOT TO BE INSIDE A TEMPORARY FOLDER
def assert_temporary_data_root():
    """
    Raises if paths.LOCAL_PATH_STR is not inside the process temporary directory.

    Returns:
        None
    """
    # IMPORT ON THE CALL, SO A SUITE CAN SET SO_DATA_PATH BEFORE THE FIRST USE
    from so import paths
    # COMPARE NORMALIZED ABSOLUTE PATHS (THE DATA ROOT USES FORWARD SLASHES)
    data_root_str = os.path.normcase(os.path.abspath(paths.LOCAL_PATH_STR))
    temp_dir_str = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
    # THE ROOT MUST BE INSIDE THE TEMPORARY DIRECTORY, NOT ONLY EQUAL TO IT
    assert data_root_str.startswith(temp_dir_str + os.sep), data_root_str
