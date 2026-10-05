"""
Create a Python 3.12 virtual environment, install requirements files and (optionally) register it as a Jupyter kernel.

Interactive:
    python setup_venv.py

Non-interactive (repeatable):
    python setup_venv.py --name venv-ml --requirements venv_main_requirements.txt venv_market_requirements.txt --kernel

Requirements files are looked up in this directory and in its requirements/ folder.

After the requirements, the workspace itself is installed in the venv in editable mode (pip install -e .), so that the
shared library (so) and the experiments (experiments.expNN_<name>) can be imported from any notebook folder. The editable
install points to this folder: code changes are picked up after a kernel restart, without reinstalling.

Changes compared with the previous version:
    - requirements files are listed (this directory + requirements/) and can be picked by number or by name;
    - optional command line arguments for a repeatable, non-interactive setup;
    - pip is upgraded before installing;
    - the Python version of an existing venv is checked (a reused venv must also be 3.12);
    - optional registration of the venv as a Jupyter kernel (the notebooks can then select it).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


# DEFINE THE REQUIRED PYTHON VERSION
PYTHON_VERSION = "3.12"
# DEFINE THE VALID VENV NAME PATTERN
VALID_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# DEFINE THE WORDS THAT END THE REQUIREMENTS PROMPT
DONE_WORDS = {"done", "finish", "finished", "quit", "exit", "q"}
# DEFINE THE REQUIREMENTS FOLDER NAME
REQUIREMENTS_DIR_NAME = "requirements"


# FUNCTION: CHECK THAT A VENV NAME IS SAFE
def is_valid_venv_name(name: str) -> bool:
    """Return True when the name is safe to use as a local directory name."""
    # RETURN TRUE IF THE NAME MATCHES THE PATTERN AND IS NOT A PATH
    return (
        bool(name)
        and VALID_NAME_PATTERN.fullmatch(name) is not None
        and name not in {".", ".."}
        and "/" not in name
        and "\\" not in name
    )


# FUNCTION: PROMPT FOR A VENV NAME
def prompt_for_venv_name() -> str:
    """Ask for a venv name until a valid one is entered."""
    # LOOP UNTIL A VALID NAME IS ENTERED
    while True:
        # READ THE NAME
        venv_name = input("Enter venv name: ").strip()
        # IF THE NAME IS VALID
        if is_valid_venv_name(venv_name):
            # RETURN THE NAME
            return venv_name
        # DISPLAY INFORMATION
        print("Invalid venv name. Use only letters, numbers, underscores, hyphens, and dots. Do not include paths.")


# FUNCTION: GET THE PYTHON 3.12 COMMAND
def python_312_command() -> list[str]:
    """Return the command that starts Python 3.12 on this platform."""
    # IF THE PLATFORM IS WINDOWS
    if sys.platform == "win32":
        # USE THE PYTHON LAUNCHER
        return ["py", f"-{PYTHON_VERSION}"]
    # USE THE VERSIONED EXECUTABLE
    return [f"python{PYTHON_VERSION}"]


# FUNCTION: CREATE THE VENV
def create_venv(venv_path: Path) -> None:
    """Create the virtual environment with Python 3.12."""
    # RUN THE VENV MODULE
    subprocess.run([*python_312_command(), "-m", "venv", str(venv_path)], check=True)


# FUNCTION: GET THE VENV PYTHON PATH
def venv_python_path(venv_path: Path) -> Path:
    """Return the Python executable inside the venv."""
    # IF THE PLATFORM IS WINDOWS
    if sys.platform == "win32":
        # RETURN THE WINDOWS EXECUTABLE
        return venv_path / "Scripts" / "python.exe"
    # RETURN THE POSIX EXECUTABLE
    return venv_path / "bin" / "python"


# FUNCTION: GET THE PYTHON VERSION OF THE VENV
def venv_python_version(venv_path: Path) -> str:
    """Return the 'major.minor' version of the venv Python (empty string if it cannot be run)."""
    # TRY TO RUN THE VENV PYTHON
    try:
        # COLLECT THE VERSION
        result = subprocess.run([str(venv_python_path(venv_path)), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
                                check=True, capture_output=True, text=True)
        # RETURN THE VERSION
        return result.stdout.strip()
    # IF THE VENV PYTHON CANNOT BE RUN
    except (OSError, subprocess.CalledProcessError):
        # RETURN AN EMPTY STRING
        return ""


# FUNCTION: LIST THE AVAILABLE REQUIREMENTS FILES
def list_requirements_files(base_dir: Path) -> list[Path]:
    """Return the .txt files of the base directory and of its requirements/ folder."""
    # COLLECT THE SEARCH DIRECTORIES
    search_dir_list = [base_dir, base_dir / REQUIREMENTS_DIR_NAME]
    # RETURN THE SORTED .TXT FILES
    return sorted({path for search_dir in search_dir_list if search_dir.is_dir() for path in search_dir.glob("*.txt")})


# FUNCTION: RESOLVE A REQUIREMENTS FILE NAME
def resolve_requirements_file(base_dir: Path, file_name: str) -> Path | None:
    """Find a requirements file by name in the base directory or its requirements/ folder."""
    # IF A PATH WAS GIVEN INSTEAD OF A NAME
    if Path(file_name).name != file_name:
        # RETURN NOTHING
        return None
    # ITERATE OVER THE SEARCH DIRECTORIES
    for search_dir in [base_dir, base_dir / REQUIREMENTS_DIR_NAME]:
        # DEFINE THE CANDIDATE PATH
        candidate_path = search_dir / file_name
        # IF THE CANDIDATE IS A .TXT FILE
        if candidate_path.suffix.lower() == ".txt" and candidate_path.is_file():
            # RETURN THE PATH
            return candidate_path
    # RETURN NOTHING
    return None


# FUNCTION: PROMPT FOR REQUIREMENTS FILES
def prompt_for_requirements_files(base_dir: Path) -> list[Path]:
    """Ask for requirements files (by number or name) until 'done' is entered."""
    # COLLECT THE AVAILABLE FILES
    available_list = list_requirements_files(base_dir)
    # DISPLAY THE AVAILABLE FILES
    print("Available requirements files:")
    for idx, path in enumerate(available_list, 1):
        print(f"  [{idx}] {path.relative_to(base_dir)}")
    print("Enter a number or a file name, one at a time. Type 'done' when finished.")
    # LIST TO HOLD THE SELECTED FILES
    requirements_files: list[Path] = []
    # LOOP UNTIL DONE
    while True:
        # READ THE ENTRY
        entry = input("Requirements file: ").strip()
        # IF THE ENTRY ENDS THE PROMPT
        if entry.lower() in DONE_WORDS:
            # RETURN THE SELECTED FILES
            return requirements_files
        # IF THE ENTRY IS A NUMBER
        if entry.isdigit() and 1 <= int(entry) <= len(available_list):
            # SELECT THE NUMBERED FILE
            requirements_path = available_list[int(entry) - 1]
        # IF THE ENTRY IS A NAME
        else:
            # RESOLVE THE NAME
            requirements_path = resolve_requirements_file(base_dir, entry)
        # IF THE FILE WAS NOT FOUND
        if requirements_path is None:
            # DISPLAY INFORMATION
            print(f"Could not find '{entry}'. Enter a listed number or a .txt file name (no paths).")
            continue
        # IF THE FILE WAS ALREADY SELECTED
        if requirements_path in requirements_files:
            # DISPLAY INFORMATION
            print(f"'{requirements_path.name}' is already selected.")
            continue
        # ADD THE FILE
        requirements_files.append(requirements_path)
        # DISPLAY INFORMATION
        print(f"Added '{requirements_path.name}'.")


# FUNCTION: INSTALL THE REQUIREMENTS
def install_requirements(venv_path: Path, requirements_files: list[Path]) -> None:
    """Upgrade pip, then install every requirements file in order."""
    # COLLECT THE VENV PYTHON
    python_path = venv_python_path(venv_path)
    # IF THE VENV PYTHON DOES NOT EXIST
    if not python_path.is_file():
        # DISPLAY INFORMATION AND EXIT
        print(f"Could not find the venv Python executable at: {python_path}", file=sys.stderr)
        raise SystemExit(1)
    # UPGRADE PIP
    print("Upgrading pip...")
    subprocess.run([str(python_path), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    # ITERATE OVER THE REQUIREMENTS FILES
    for requirements_path in requirements_files:
        # DISPLAY INFORMATION
        print(f"Installing packages from '{requirements_path.name}'...")
        # INSTALL THE FILE
        subprocess.run([str(python_path), "-m", "pip", "install", "-r", str(requirements_path)], check=True)


# FUNCTION: INSTALL THE WORKSPACE PACKAGE IN EDITABLE MODE
def install_workspace_package(venv_path: Path, base_dir: Path) -> None:
    """Install this workspace (pyproject.toml: packages so and experiments) in editable mode."""
    # COLLECT THE VENV PYTHON
    python_path = str(venv_python_path(venv_path))
    # DISPLAY INFORMATION
    print("Installing the workspace (so, experiments) in editable mode...")
    # INSTALL THE WORKSPACE
    subprocess.run([python_path, "-m", "pip", "install", "-e", str(base_dir)], check=True)


# FUNCTION: REGISTER THE VENV AS A JUPYTER KERNEL
def register_jupyter_kernel(venv_path: Path, venv_name: str) -> None:
    """Register the venv as a Jupyter kernel (installs ipykernel if it is missing)."""
    # COLLECT THE VENV PYTHON
    python_path = str(venv_python_path(venv_path))
    # INSTALL IPYKERNEL (NO-OP IF ALREADY INSTALLED)
    subprocess.run([python_path, "-m", "pip", "install", "ipykernel"], check=True)
    # REGISTER THE KERNEL
    subprocess.run([python_path, "-m", "ipykernel", "install", "--user", "--name", venv_name,
                    "--display-name", f"Python {PYTHON_VERSION} ({venv_name})"], check=True)
    # DISPLAY INFORMATION
    print(f"Registered Jupyter kernel '{venv_name}'.")


# FUNCTION: PARSE THE COMMAND LINE ARGUMENTS
def parse_args() -> argparse.Namespace:
    """Parse the optional command line arguments (missing values are asked interactively)."""
    # CREATE THE PARSER
    parser = argparse.ArgumentParser(description="Create a Python 3.12 venv and install requirements files.")
    parser.add_argument("--name", help="venv directory name (created next to this script)")
    parser.add_argument("--requirements", nargs="*", help="requirements .txt file names (this directory or requirements/)")
    parser.add_argument("--kernel", action="store_true", help="register the venv as a Jupyter kernel")
    # RETURN THE ARGUMENTS
    return parser.parse_args()


# FUNCTION: MAIN
def main() -> None:
    """Create or reuse the venv, install the requirements and optionally register the kernel."""
    # PARSE THE ARGUMENTS
    args = parse_args()
    # DEFINE THE BASE DIRECTORY
    base_dir = Path(__file__).resolve().parent
    # DEFINE THE VENV NAME
    venv_name = args.name if args.name and is_valid_venv_name(args.name) else prompt_for_venv_name()
    venv_path = base_dir / venv_name
    # IF THE VENV DOES NOT EXIST
    if not venv_path.exists():
        # DISPLAY INFORMATION
        print(f"Creating virtual environment '{venv_name}' with Python {PYTHON_VERSION}...")
        # TRY TO CREATE THE VENV
        try:
            create_venv(venv_path)
        # IF PYTHON 3.12 IS NOT FOUND
        except FileNotFoundError:
            print("Could not find Python 3.12. Install Python 3.12 or make sure the Python launcher can find it.", file=sys.stderr)
            raise SystemExit(1)
        # IF THE CREATION FAILED
        except subprocess.CalledProcessError as exc:
            print(f"Failed to create virtual environment: {exc}", file=sys.stderr)
            raise SystemExit(exc.returncode) from exc
        # DISPLAY INFORMATION
        print(f"Virtual environment created at: {venv_path}")
    # IF THE VENV ALREADY EXISTS
    else:
        # CHECK THE PYTHON VERSION OF THE EXISTING VENV
        existing_version = venv_python_version(venv_path)
        # IF THE VERSION IS NOT THE REQUIRED VERSION
        if existing_version != PYTHON_VERSION:
            print(f"Existing venv '{venv_name}' uses Python '{existing_version or 'unknown'}', not {PYTHON_VERSION}. "
                  "Delete it or choose another name.", file=sys.stderr)
            raise SystemExit(1)
        # DISPLAY INFORMATION
        print(f"Virtual environment '{venv_name}' already exists (Python {existing_version}). Reusing it.")
    # COLLECT THE REQUIREMENTS FILES
    if args.requirements:
        # RESOLVE THE GIVEN FILE NAMES
        requirements_files = []
        for file_name in args.requirements:
            requirements_path = resolve_requirements_file(base_dir, file_name)
            if requirements_path is None:
                print(f"Could not find '{file_name}' in {base_dir} or {base_dir / REQUIREMENTS_DIR_NAME}.", file=sys.stderr)
                raise SystemExit(1)
            requirements_files.append(requirements_path)
    else:
        # ASK FOR THE REQUIREMENTS FILES
        requirements_files = prompt_for_requirements_files(base_dir)
    # IF THERE ARE REQUIREMENTS FILES
    if requirements_files:
        # TRY TO INSTALL THE REQUIREMENTS
        try:
            install_requirements(venv_path, requirements_files)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to install requirements: {exc}", file=sys.stderr)
            raise SystemExit(exc.returncode) from exc
        # DISPLAY INFORMATION
        print("Finished installing requirements.")
    # IF THERE ARE NO REQUIREMENTS FILES
    else:
        print("No requirements files selected. Nothing to install.")
    # INSTALL THE WORKSPACE PACKAGE (EDITABLE)
    try:
        install_workspace_package(venv_path, base_dir)
    except subprocess.CalledProcessError as exc:
        print(f"Failed to install the workspace package: {exc}", file=sys.stderr)
        raise SystemExit(exc.returncode) from exc
    # DEFINE WHETHER THE KERNEL MUST BE REGISTERED
    register_kernel_bool = args.kernel or (args.name is None and input("Register as a Jupyter kernel? [y/N]: ").strip().lower() in {"y", "yes"})
    # IF THE KERNEL MUST BE REGISTERED
    if register_kernel_bool:
        # TRY TO REGISTER THE KERNEL
        try:
            register_jupyter_kernel(venv_path, venv_name)
        except subprocess.CalledProcessError as exc:
            print(f"Failed to register the Jupyter kernel: {exc}", file=sys.stderr)
            raise SystemExit(exc.returncode) from exc


# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # RUN THE MAIN FUNCTION
    main()
