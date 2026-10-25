import contextlib
import os
import sys

"""
Design-Code Guard (audit B2, 2026-10-25)

The runner calls design code in its own process: the design module's import, get_candidate_design, decide, fit,
fit_shared, finish_fit and signal. Python cannot sandbox that code, so two runtime checks stand behind the view and
the AST preflight:

    file guard     While design code runs, a process audit hook (sys.addaudithook) refuses to open, list, create,
                   rename or delete anything under the data root (SO_DATA_PATH), the quarantine
                   (SO_QUARANTINE_PATH) or the holdout folder (SO_HOLDOUT_PATH), and refuses subprocesses and
                   network connections. Every disk route around the view fails, whichever helper module it goes
                   through. The runner's own file work (loading, checkpoints, trial rows, fit cache) happens outside
                   the guarded calls.
    module guard   A snapshot of every so.* module (the identity of each function, class and module attribute, and
                   the value of each public UPPERCASE constant) is taken before the design is imported. The runner
                   compares it after the import, after each period and at the end of a stream. A design that
                   rewrites so.config (costs, the label horizon) or replaces a shared function stops the run.

Private names (a leading underscore) are runner state that the runner itself sets and are not compared.
"""

# AUDIT EVENTS THAT TOUCH THE FILE SYSTEM, WITH THE ARGUMENT POSITIONS THAT HOLD PATHS
PATH_EVENT_ARG_DICT = {"open": (0,), "os.listdir": (0,), "os.scandir": (0,), "os.remove": (0,), "os.rmdir": (0,),
                       "os.mkdir": (0,), "os.rename": (0, 1), "os.replace": (0, 1), "shutil.rmtree": (0,),
                       "shutil.copyfile": (0, 1), "shutil.move": (0, 1), "os.truncate": (0,), "os.chmod": (0,)}
# AUDIT EVENTS REFUSED OUTRIGHT WHILE DESIGN CODE RUNS
# (ctypes.dlopen IS NOT REFUSED: A LAZY IMPORT INSIDE A FIT, FOR EXAMPLE SCIKIT-LEARN OR LIGHTGBM ON WINDOWS, LOADS ITS
# DLLs THROUGH IT; THE PREFLIGHT ALREADY REFUSES ctypes IN DESIGN FILES)
REFUSED_EVENT_SET = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.startfile",
                     "socket.connect", "socket.getaddrinfo", "urllib.Request"}
# THE ENVIRONMENT VARIABLES WHOSE FOLDERS ARE CLOSED TO DESIGN CODE
GUARDED_ROOT_ENV_LIST = ["SO_DATA_PATH", "SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH"]

# HOW MANY GUARDED CALLS ARE OPEN IN THIS PROCESS, AND THE ROOTS THEY CLOSE
_GUARD_DEPTH_INT = 0
_GUARD_ROOT_LIST = []
# WHETHER THE AUDIT HOOK IS INSTALLED IN THIS PROCESS (A HOOK CANNOT BE REMOVED)
_HOOK_INSTALLED_BOOL = False


# FUNCTION: A NORMALIZED ABSOLUTE PATH, OR None FOR A FILE DESCRIPTOR
def get_normal_path_str(path_in):
    """
    Args:
        path_in (str | bytes | os.PathLike | int): Path argument of an audit event

    Returns:
        str | None: normcase(abspath(path)), or None when the argument is not a path
    """
    # A FILE DESCRIPTOR IS NOT A PATH
    if path_in is None or isinstance(path_in, int):
        return None
    try:
        path_str = os.fsdecode(os.fspath(path_in))
    except TypeError:
        return None
    return os.path.normcase(os.path.abspath(path_str))


# FUNCTION: THE FOLDERS CLOSED TO DESIGN CODE
def get_guarded_root_list():
    """
    Args:
        None

    Returns:
        list[str]: Normalized folders from SO_DATA_PATH, SO_QUARANTINE_PATH and SO_HOLDOUT_PATH that are set
    """
    # ONLY THE VARIABLES THAT ARE SET
    root_list = []
    for env_str in GUARDED_ROOT_ENV_LIST:
        value_str = os.environ.get(env_str, "").strip()
        if value_str:
            root_list.append(get_normal_path_str(value_str).rstrip("\\/"))
    return root_list


# FUNCTION: WHETHER A PATH IS INSIDE A CLOSED FOLDER
def get_guarded_path_bool(path_str_in, root_list_in):
    """
    Args:
        path_str_in (str | None): Normalized path
        root_list_in (list[str]): Normalized folders

    Returns:
        bool: True when the path is a folder of the list or below one
    """
    # NOT A PATH
    if path_str_in is None:
        return False
    for root_str in root_list_in:
        if path_str_in == root_str or path_str_in.startswith(root_str + os.sep):
            return True
    return False


# FUNCTION: THE AUDIT HOOK
def design_audit_hook(event_str_in, arg_tuple_in):
    """
    Raises PermissionError for a refused event while a guarded call is open. Does nothing otherwise.

    Args:
        event_str_in (str): Audit event name
        arg_tuple_in (tuple): Event arguments

    Returns:
        None
    """
    # OUTSIDE DESIGN CODE EVERYTHING IS ALLOWED
    if _GUARD_DEPTH_INT <= 0:
        return
    if event_str_in in REFUSED_EVENT_SET:
        raise PermissionError(f"design code may not use {event_str_in} (so.runner.guard)")
    position_tuple = PATH_EVENT_ARG_DICT.get(event_str_in)
    if position_tuple is None:
        return
    for position_int in position_tuple:
        if position_int < len(arg_tuple_in):
            path_str = get_normal_path_str(arg_tuple_in[position_int])
            if get_guarded_path_bool(path_str, _GUARD_ROOT_LIST):
                raise PermissionError(f"design code may not read or write data files directly ({event_str_in} "
                                      f"{path_str}); read data through the view (so.runner.guard)")


# FUNCTION: INSTALL THE HOOK ONCE PER PROCESS
def install_design_audit_hook():
    """
    Args:
        None

    Returns:
        None
    """
    # sys.addaudithook CANNOT BE UNDONE, SO THE HOOK CHECKS THE DEPTH ON EVERY EVENT
    global _HOOK_INSTALLED_BOOL
    if not _HOOK_INSTALLED_BOOL:
        sys.addaudithook(design_audit_hook)
        _HOOK_INSTALLED_BOOL = True


# FUNCTION: RUN A BLOCK OF DESIGN CODE BEHIND THE FILE GUARD
@contextlib.contextmanager
def design_code_guard():
    """
    Context manager around every call into design code. Nested use is allowed.

    Yields:
        None
    """
    # THE ROOTS ARE READ WHEN THE OUTERMOST BLOCK OPENS
    global _GUARD_DEPTH_INT, _GUARD_ROOT_LIST
    install_design_audit_hook()
    if _GUARD_DEPTH_INT == 0:
        _GUARD_ROOT_LIST = get_guarded_root_list()
    _GUARD_DEPTH_INT += 1
    try:
        yield
    finally:
        _GUARD_DEPTH_INT -= 1


# FUNCTION: CALL ONE DESIGN FUNCTION BEHIND THE FILE GUARD
def call_design_func(func_in, *arg_tuple_in, **kwarg_dict_in):
    """
    Args:
        func_in (callable): Design function or method
        *arg_tuple_in, **kwarg_dict_in: Its arguments

    Returns:
        object: Its result
    """
    # ONE GUARDED CALL
    with design_code_guard():
        return func_in(*arg_tuple_in, **kwarg_dict_in)


# FUNCTION: A STABLE FINGERPRINT OF ONE MODULE ATTRIBUTE
def get_attribute_fingerprint(attr_str_in, value_in):
    """
    Functions, classes, modules and other objects by identity; public UPPERCASE constants by value.

    Args:
        attr_str_in (str): Attribute name
        value_in (object): Attribute value

    Returns:
        tuple | None: Fingerprint, or None when the attribute is not compared
    """
    # CONSTANTS BY VALUE (A LIST OR DICT CHANGED IN PLACE IS CAUGHT)
    if attr_str_in.isupper():
        try:
            return ("value", repr(value_in))
        except Exception:
            return ("id", id(value_in))
    if callable(value_in) or isinstance(value_in, type(sys)):
        return ("id", id(value_in))
    return None


# FUNCTION: SNAPSHOT EVERY so.* MODULE
def get_module_snapshot_dict():
    """
    Args:
        None

    Returns:
        dict: (module name, attribute name) -> fingerprint, for the so package and its loaded submodules
    """
    # PRIVATE AND DUNDER NAMES ARE RUNNER STATE
    snapshot_dict = {}
    for module_name_str, module in list(sys.modules.items()):
        if module is None or not (module_name_str == "so" or module_name_str.startswith("so.")):
            continue
        for attr_str, value in list(vars(module).items()):
            if attr_str.startswith("_"):
                continue
            fingerprint = get_attribute_fingerprint(attr_str, value)
            if fingerprint is not None:
                snapshot_dict[(module_name_str, attr_str)] = fingerprint
    return snapshot_dict


# FUNCTION: REFUSE A CHANGED so.* MODULE
def check_module_snapshot(before_dict_in, moment_str_in):
    """
    Attributes present in the snapshot must be unchanged. New modules loaded since (a design importing a helper)
    are not compared.

    Args:
        before_dict_in (dict): Output of get_module_snapshot_dict
        moment_str_in (str): Where the check runs (for the message)

    Returns:
        None
    """
    # COMPARE ONLY WHAT EXISTED BEFORE
    after_dict = get_module_snapshot_dict()
    changed_list = []
    for key_tuple, fingerprint in before_dict_in.items():
        module_name_str = key_tuple[0]
        if module_name_str not in sys.modules:
            continue
        if after_dict.get(key_tuple) != fingerprint:
            changed_list.append(f"{module_name_str}.{key_tuple[1]}")
    if changed_list:
        shown_str = ", ".join(sorted(changed_list)[:10])
        raise RuntimeError(f"shared code or constants changed {moment_str_in}: {shown_str}. A design may not rewrite "
                           f"so.config or replace shared functions (so.runner.guard)")
