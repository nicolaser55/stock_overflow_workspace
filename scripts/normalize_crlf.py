import sys
from pathlib import Path

"""
CRLF Normalizer (code-conventions.mdc: .py and .md files use CRLF line endings)

Usage: venv-main/Scripts/python.exe scripts/normalize_crlf.py <file> [<file> ...]
Every given file is rewritten with CRLF line endings (LF and CRLF inputs both give CRLF; content is otherwise unchanged).
"""

# FUNCTION: NORMALIZE THE LINE ENDINGS OF A FILE TO CRLF
def normalize_crlf_bool(file_path_str_in):
    """
    Rewrites a file with CRLF line endings.

    Args:
        file_path_str_in (str): File path

    Returns:
        bool: True if the file was changed
    """
    # READ THE BYTES
    file_path = Path(file_path_str_in)
    old_bytes = file_path.read_bytes()
    # CONVERT EVERY LINE ENDING TO CRLF
    new_bytes = old_bytes.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    # WRITE THE FILE IF IT CHANGED
    if new_bytes != old_bytes:
        file_path.write_bytes(new_bytes)
    # RETURN WHETHER IT CHANGED
    return new_bytes != old_bytes

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # NORMALIZE EVERY GIVEN FILE
    for file_path_str in sys.argv[1:]:
        print(f"{'changed' if normalize_crlf_bool(file_path_str) else 'unchanged'}\t{file_path_str}")
