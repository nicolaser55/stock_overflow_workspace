import argparse
import re
import sys
from importlib import metadata
from pathlib import Path

"""
Locked Package Check

    python scripts/check_environment.py          # prints the differences; exit 1 when there is one

The lock depends on the platform (judge PR, 2026-11-23): requirements/venv_main_lock.txt on Windows,
requirements/venv_main_lock_linux.txt everywhere else (so-vm; the same versions minus Windows-only and unused packages,
installed with the hashes in requirements/venv_main_hashes_linux.txt by vm/setup_vm.sh). Both locks and the Linux
hash file are part of the judge hash (so/runner/judge_identity.py).

requirements/venv_main_lock.txt is `pip freeze --exclude-editable` of venv-main, written by Nicolas. Every
development run calls check_environment_list first and refuses to start when an installed version differs from the
lock or a locked package is missing, so a result is never produced by a silently upgraded package. Without a lock file
the run prints a warning and goes on. Agents never install, upgrade or remove a package; a change is Nicolas's
(a new lock, committed with the reason).
"""

# THE LOCK FILES (WINDOWS, AND THE LINUX ONE OF so-vm)
REQUIREMENTS_PATH = Path(__file__).resolve().parents[1] / "requirements"
WINDOWS_LOCK_PATH = REQUIREMENTS_PATH / "venv_main_lock.txt"
LINUX_LOCK_PATH = REQUIREMENTS_PATH / "venv_main_lock_linux.txt"


# FUNCTION: THE LOCK OF A PLATFORM
def get_lock_path(platform_str_in=None):
    """
    Args:
        platform_str_in (str | None): sys.platform replacement (tests)

    Returns:
        Path: The Windows lock on Windows, the Linux lock everywhere else
    """
    # ONE LOCK PER OPERATING SYSTEM; THE VERSIONS ARE THE SAME
    platform_str = sys.platform if platform_str_in is None else str(platform_str_in)
    return WINDOWS_LOCK_PATH if platform_str == "win32" else LINUX_LOCK_PATH


# THE LOCK OF THIS MACHINE
LOCK_PATH = get_lock_path()


# FUNCTION: A NORMALIZED PACKAGE NAME
def get_normal_name_str(name_str_in):
    """
    Args:
        name_str_in (str): Distribution name

    Returns:
        str: Lower case, runs of "-", "_" and "." as "-" (PEP 503)
    """
    # ONE SPELLING PER PACKAGE
    return re.sub(r"[-_.]+", "-", str(name_str_in)).lower()


# FUNCTION: READ THE LOCK
def read_lock_dict(lock_path_in=LOCK_PATH):
    """
    Args:
        lock_path_in (Path): Lock file

    Returns:
        dict: normalized name -> version ("name==version" lines; other lines are ignored)
    """
    # PIP FREEZE WRITES name==version
    lock_dict = {}
    for line_str in Path(lock_path_in).read_text(encoding="utf-8-sig").splitlines():
        line_str = line_str.split("#", 1)[0].strip()
        if "==" in line_str:
            name_str, version_str = line_str.split("==", 1)
            lock_dict[get_normal_name_str(name_str)] = version_str.strip()
    return lock_dict


# FUNCTION: THE INSTALLED VERSIONS
def get_installed_dict():
    """
    Returns:
        dict: normalized name -> version of every installed distribution
    """
    # importlib.metadata SEES WHAT pip SEES
    return {get_normal_name_str(dist.metadata["Name"]): dist.version for dist in metadata.distributions()
            if dist.metadata["Name"]}


# FUNCTION: DIFFERENCES BETWEEN THE LOCK AND THE ENVIRONMENT
def check_environment_list(lock_path_in=LOCK_PATH, installed_dict_in=None):
    """
    Locked packages that are missing or at another version. Extra installed packages are not checked (the editable
    workspace and pip itself are not in the lock).

    Args:
        lock_path_in (Path): Lock file
        installed_dict_in (dict | None): Installed versions (tests)

    Returns:
        list[str] | None: Differences, or None when there is no lock file
    """
    # NO LOCK, NOTHING TO CHECK
    if not Path(lock_path_in).is_file():
        return None
    installed_dict = installed_dict_in if installed_dict_in is not None else get_installed_dict()
    difference_list = []
    for name_str, version_str in sorted(read_lock_dict(lock_path_in).items()):
        if name_str not in installed_dict:
            difference_list.append(f"{name_str}: locked {version_str}, not installed")
        elif installed_dict[name_str] != version_str:
            difference_list.append(f"{name_str}: locked {version_str}, installed {installed_dict[name_str]}")
    return difference_list


# RUN
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="Compare installed packages with the lock of this platform (requirements/venv_main_lock.txt on Windows, venv_main_lock_linux.txt elsewhere).")
    parser.parse_args()
    difference_list = check_environment_list()
    if difference_list is None:
        print(f"no lock file at {LOCK_PATH}")
        sys.exit(1)
    if difference_list:
        print("\n".join(difference_list))
        sys.exit(1)
    print("environment matches the lock")
