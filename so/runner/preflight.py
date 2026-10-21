import ast
import inspect
import os

"""
Design-file preflight (infrastructure step 4a)

The loop reads the design file as AST before the first decide() call and refuses names that reach around the view or
read data off the view. It also walks every module the design imports from experiments/, transitively, and any
helper sitting next to the design file. The runner itself may use these names; a design file may not.
"""

# ATTRIBUTE NAMES THAT REACH PAST THE VIEW
BANNED_ATTR_SET = {"base", "__closure__", "__self__", "__globals__", "__dict__", "_getframe", "load", "fromfile",
                   "loadtxt", "genfromtxt"}
# BARE NAMES THAT LOAD ESCAPE HATCHES OR OPEN FILES
BANNED_NAME_SET = {"gc", "inspect", "ctypes", "open", "eval", "exec", "__import__", "vars"}
# MODULES A DESIGN MUST NOT IMPORT
BANNED_MODULE_SET = {"so.runner", "so.core.point_in_time", "so.core.holdout", "os", "pathlib", "glob", "shutil", "io",
                     "pickle", "joblib", "importlib", "so.paths", "so.core.local_file_management", "so.core.raw_data",
                     "pandas.io", "pd.io"}
# NAMES THAT ARE PANDAS WHEN FOLLOWED BY .io
PANDAS_IO_NAME_SET = {"pd", "pandas"}
# GETATTR / SETATTR NAMES THAT ARE THE SAME ESCAPE HATCHES
BANNED_GETATTR_SET = BANNED_ATTR_SET | BANNED_NAME_SET
# WORKSPACE ROOT AND THE EXPERIMENTS PACKAGE
WORKSPACE_PATH_STR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXPERIMENTS_PATH_STR = os.path.join(WORKSPACE_PATH_STR, "experiments")


# FUNCTION: WHETHER AN ATTRIBUTE NAME IS BANNED
def get_banned_attr_bool(attr_str_in):
    """
    True for .base, .load, .fromfile, .loadtxt, .genfromtxt, and any attribute starting with read_.

    Args:
        attr_str_in (str): Attribute name

    Returns:
        bool: True if banned
    """
    # pd.read_csv, np.load AND np.loadtxt ARE DATA ACCESS
    return attr_str_in in BANNED_ATTR_SET or attr_str_in.startswith("read_")


# FUNCTION: WHETHER AN ATTRIBUTE NODE IS pd.io OR pandas.io
def get_pandas_io_attr_bool(node_in):
    """
    True for pd.io and pandas.io (any submodule reached as an attribute).

    Args:
        node_in (ast.AST): One node

    Returns:
        bool: True if this is pandas I/O
    """
    # pd.io.csv AND pandas.io.parsers BOTH START AT .io ON pd OR pandas
    if not isinstance(node_in, ast.Attribute) or node_in.attr != "io":
        return False
    return isinstance(node_in.value, ast.Name) and node_in.value.id in PANDAS_IO_NAME_SET


# FUNCTION: WHETHER AN IMPORT NAME IS A BANNED MODULE
def get_banned_module_match_str(module_name_str_in):
    """
    Returns the banned module if module_name_str_in is that module or a submodule of it.

    Args:
        module_name_str_in (str): Dotted import name

    Returns:
        str | None: The banned module, or None
    """
    # PREFIX MATCH SO so.runner.view IS ALSO REFUSED
    for banned_str in BANNED_MODULE_SET:
        if module_name_str_in == banned_str or module_name_str_in.startswith(banned_str + "."):
            return banned_str
    return None


# FUNCTION: IMPORT NAMES FROM ONE AST NODE
def get_import_name_list(node_in):
    """
    Dotted names an Import or ImportFrom node binds.

    Args:
        node_in (ast.AST): Import node

    Returns:
        list[str]: Module names
    """
    # import a.b  AND  from a.b import c  (COUNTED AS a.b AND a.b.c)
    if isinstance(node_in, ast.Import):
        return [alias.name for alias in node_in.names]
    if isinstance(node_in, ast.ImportFrom):
        base_str = node_in.module or ""
        name_list = [base_str] if base_str else []
        for alias in node_in.names:
            name_list.append(f"{base_str}.{alias.name}" if base_str else alias.name)
        return name_list
    return []


# FUNCTION: A .py FILE FOR A DOTTED NAME UNDER A DIRECTORY
def get_module_file_path_str(root_dir_str_in, dotted_name_str_in):
    """
    root/a/b.py or root/a/b/__init__.py, or None.

    Args:
        root_dir_str_in (str): Directory to resolve from
        dotted_name_str_in (str): a.b.c

    Returns:
        str | None: File path
    """
    # EMPTY NAMES DO NOT RESOLVE
    if not dotted_name_str_in:
        return None
    rel_str = os.path.join(*dotted_name_str_in.split("."))
    file_path_str = os.path.join(root_dir_str_in, rel_str + ".py")
    init_path_str = os.path.join(root_dir_str_in, rel_str, "__init__.py")
    if os.path.isfile(file_path_str):
        return os.path.abspath(file_path_str)
    if os.path.isfile(init_path_str):
        return os.path.abspath(init_path_str)
    return None


# FUNCTION: PARENT PACKAGE __init__ FILES UNDER experiments/
def get_experiments_init_path_list(dotted_name_str_in):
    """
    experiments/__init__.py and each package on the way to dotted_name_str_in.

    Args:
        dotted_name_str_in (str): Dotted import name

    Returns:
        list[str]: Existing __init__.py paths
    """
    # ONLY THE experiments PACKAGE TREE
    part_list = dotted_name_str_in.split(".")
    if part_list[0] != "experiments":
        return []
    init_path_list = []
    for idx in range(1, len(part_list)):
        prefix_str = ".".join(part_list[:idx])
        init_path_str = get_module_file_path_str(WORKSPACE_PATH_STR, prefix_str)
        if init_path_str is not None and os.path.basename(init_path_str) == "__init__.py":
            init_path_list.append(init_path_str)
    return init_path_list


# FUNCTION: RESOLVE ONE DOTTED NAME FROM THE FILE'S DIRECTORY OR THE WORKSPACE
def get_dotted_resolve_path_str(dotted_name_str_in, current_dir_str_in):
    """
    experiments.* from the workspace root; otherwise a sibling module of the current file.

    Args:
        dotted_name_str_in (str): Dotted import name
        current_dir_str_in (str): Directory of the file that imported it

    Returns:
        str | None: File path
    """
    # EXPERIMENTS PACKAGES ARE ALWAYS THE ONES IN THIS REPO
    if dotted_name_str_in == "experiments" or dotted_name_str_in.startswith("experiments."):
        return get_module_file_path_str(WORKSPACE_PATH_STR, dotted_name_str_in)
    return get_module_file_path_str(current_dir_str_in, dotted_name_str_in)


# FUNCTION: .py FILES AN IMPORT NODE MAY LOAD UNDER experiments/ OR NEXT TO THE DESIGN
def get_import_follow_path_list(current_file_str_in, node_in):
    """
    Resolves Import and ImportFrom to files. Relative imports walk up from the current file.

    Args:
        current_file_str_in (str): File that contains the import
        node_in (ast.AST): Import node

    Returns:
        list[str]: Candidate file paths
    """
    # ONLY IMPORT NODES
    path_list = []
    current_dir_str = os.path.dirname(os.path.abspath(current_file_str_in))
    if isinstance(node_in, ast.Import):
        for alias in node_in.names:
            path_str = get_dotted_resolve_path_str(alias.name, current_dir_str)
            if path_str is not None:
                path_list.append(path_str)
            path_list.extend(get_experiments_init_path_list(alias.name))
        return path_list
    if not isinstance(node_in, ast.ImportFrom):
        return path_list
    level_int = int(node_in.level or 0)
    if level_int > 0:
        pkg_dir_str = current_dir_str
        for _ in range(level_int - 1):
            pkg_dir_str = os.path.dirname(pkg_dir_str)
        if node_in.module:
            path_str = get_module_file_path_str(pkg_dir_str, node_in.module)
            if path_str is not None:
                path_list.append(path_str)
            for alias in node_in.names:
                if alias.name == "*":
                    continue
                sub_path_str = get_module_file_path_str(pkg_dir_str, f"{node_in.module}.{alias.name}")
                if sub_path_str is not None:
                    path_list.append(sub_path_str)
        else:
            for alias in node_in.names:
                if alias.name == "*":
                    init_path_str = os.path.join(pkg_dir_str, "__init__.py")
                    if os.path.isfile(init_path_str):
                        path_list.append(os.path.abspath(init_path_str))
                    continue
                path_str = get_module_file_path_str(pkg_dir_str, alias.name)
                if path_str is not None:
                    path_list.append(path_str)
        return path_list
    base_str = node_in.module or ""
    if base_str:
        path_str = get_dotted_resolve_path_str(base_str, current_dir_str)
        if path_str is not None:
            path_list.append(path_str)
        path_list.extend(get_experiments_init_path_list(base_str))
        for alias in node_in.names:
            if alias.name == "*":
                continue
            sub_path_str = get_dotted_resolve_path_str(f"{base_str}.{alias.name}", current_dir_str)
            if sub_path_str is not None:
                path_list.append(sub_path_str)
    return path_list


# FUNCTION: WHETHER A RESOLVED FILE IS IN THE DESIGN'S TREE OR IN experiments/
def get_follow_path_bool(file_path_str_in, start_dir_str_in):
    """
    True when the file is under experiments/ or under the directory of the file the preflight started from.

    Args:
        file_path_str_in (str): Resolved module path
        start_dir_str_in (str): Directory of the original design file

    Returns:
        bool: True if this file is part of the design
    """
    # NORMALIZE SO WINDOWS AND POSIX SEPARATORS MATCH
    path_str = os.path.normcase(os.path.abspath(file_path_str_in))
    experiments_str = os.path.normcase(os.path.abspath(EXPERIMENTS_PATH_STR))
    start_str = os.path.normcase(os.path.abspath(start_dir_str_in))
    if path_str == experiments_str or path_str.startswith(experiments_str + os.sep):
        return True
    return path_str == start_str or path_str.startswith(start_str + os.sep)


# FUNCTION: STRING LITERAL NAME PASSED TO getattr OR setattr
def get_getattr_literal_str(node_in):
    """
    The name argument when it is a string constant.

    Args:
        node_in (ast.Call): getattr or setattr call

    Returns:
        str | None: The literal name
    """
    # POSITIONAL NAME IS THE SECOND ARGUMENT
    if len(node_in.args) >= 2 and isinstance(node_in.args[1], ast.Constant) and isinstance(node_in.args[1].value, str):
        return node_in.args[1].value
    for keyword in node_in.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


# FUNCTION: REFUSE ONE FILE'S AST
def check_design_tree_node(node_in, file_path_str_in):
    """
    Raises if this node uses a banned attribute, name, call or import.

    Args:
        node_in (ast.AST): One node
        file_path_str_in (str): File being checked

    Returns:
        None
    """
    # ATTRIBUTES: .base, .read_*, np.load, np.loadtxt, pd.io
    if isinstance(node_in, ast.Attribute) and get_banned_attr_bool(node_in.attr):
        raise ValueError(f"design file uses banned name .{node_in.attr}: {file_path_str_in}")
    if get_pandas_io_attr_bool(node_in):
        raise ValueError(f"design file uses banned name pandas.io: {file_path_str_in}")
    # BARE NAMES: open, eval, gc, ...
    if isinstance(node_in, ast.Name) and isinstance(node_in.ctx, ast.Load) and node_in.id in BANNED_NAME_SET:
        raise ValueError(f"design file uses banned name {node_in.id}: {file_path_str_in}")
    # getattr(x, "base") AND setattr(x, "read_csv", ...)
    if isinstance(node_in, ast.Call):
        func_name_str = node_in.func.id if isinstance(node_in.func, ast.Name) else (node_in.func.attr if isinstance(node_in.func, ast.Attribute) else None)
        if func_name_str in {"getattr", "setattr"}:
            literal_str = get_getattr_literal_str(node_in)
            if literal_str is not None and (literal_str in BANNED_GETATTR_SET or get_banned_attr_bool(literal_str)):
                raise ValueError(f"design file uses banned name {literal_str}: {file_path_str_in}")
    # IMPORTS OF BANNED MODULES AND BANNED NAMES
    if isinstance(node_in, (ast.Import, ast.ImportFrom)):
        for module_str in get_import_name_list(node_in):
            banned_str = get_banned_module_match_str(module_str)
            if banned_str is not None:
                raise ValueError(f"design file imports {banned_str}: {file_path_str_in}")
            first_str = module_str.split(".")[0]
            last_str = module_str.split(".")[-1]
            if first_str in BANNED_NAME_SET or last_str in BANNED_NAME_SET:
                raise ValueError(f"design file uses banned name {last_str if last_str in BANNED_NAME_SET else first_str}: {file_path_str_in}")
            experiments_bool = module_str == "experiments" or module_str.startswith("experiments.")
            if get_banned_attr_bool(last_str) and not experiments_bool:
                raise ValueError(f"design file uses banned name .{last_str}: {file_path_str_in}")


# FUNCTION: THE EXPERIMENT PACKAGE FOLDER OF A FILE UNDER experiments/
def get_experiments_package_folder_str(file_path_str_in):
    """
    experiments/<name> when the file lives in that package directory. A file sitting directly under experiments/
    is not a package folder.

    Args:
        file_path_str_in (str): File the preflight walked

    Returns:
        str | None: Absolute package folder, or None
    """
    # ONLY FILES UNDER THIS REPO'S experiments/ TREE
    path_str = os.path.abspath(file_path_str_in)
    experiments_str = os.path.abspath(EXPERIMENTS_PATH_STR)
    if path_str == experiments_str:
        return None
    prefix_str = experiments_str + os.sep
    if not path_str.startswith(prefix_str):
        return None
    rel_str = path_str[len(prefix_str):]
    first_str = rel_str.split(os.sep, 1)[0]
    package_str = os.path.join(experiments_str, first_str)
    if os.path.isdir(package_str):
        return package_str
    return None


# FUNCTION: FILES THE PREFLIGHT WALKS FROM A DESIGN FILE
def get_design_follow_path_list(file_path_str_in):
    """
    The design file and every experiments/ (or same-folder) module it imports, transitively. Same walk as
    check_design_file, without the banned-name check.

    Args:
        file_path_str_in (str): Path of the design file

    Returns:
        list[str]: Absolute file paths, in walk order
    """
    # THE STARTING DIRECTORY LIMITS WHICH SIBLING HELPERS ARE FOLLOWED
    start_dir_str = os.path.dirname(os.path.abspath(file_path_str_in))
    seen_set = set()
    path_list = []
    stack_list = [os.path.abspath(file_path_str_in)]
    while stack_list:
        path_str = stack_list.pop()
        if path_str in seen_set:
            continue
        seen_set.add(path_str)
        path_list.append(path_str)
        source_str = open(path_str, "r", encoding="utf-8").read()
        tree = ast.parse(source_str, filename=path_str)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for follow_path_str in get_import_follow_path_list(path_str, node):
                    if follow_path_str not in seen_set and get_follow_path_bool(follow_path_str, start_dir_str):
                        stack_list.append(follow_path_str)
    return path_list


# FUNCTION: REFUSE A DESIGN FILE AND THE experiments/ MODULES IT IMPORTS
def check_design_file(file_path_str_in):
    """
    Parses the file and every experiments/ (or same-folder) module it imports, transitively.

    Args:
        file_path_str_in (str): Path of the design file

    Returns:
        None
    """
    # THE SAME FILES THE FOLDER GUARDS HASH AND CHECK FOR A DIRTY TREE
    for path_str in get_design_follow_path_list(file_path_str_in):
        source_str = open(path_str, "r", encoding="utf-8").read()
        tree = ast.parse(source_str, filename=path_str)
        check_minute_signal_tree(tree, path_str)
        for node in ast.walk(tree):
            check_design_tree_node(node, path_str)


# FUNCTION: THE FILE A DESIGN OBJECT WAS LOADED FROM
def get_design_file_path_str(design_in, design_file_path_str_in=None):
    """
    An explicit path wins. Otherwise the object's module __file__, then inspect.getfile.

    Args:
        design_in (object | callable): Design
        design_file_path_str_in (str | None): Path the caller named

    Returns:
        str | None: File path
    """
    # THE CALLER CAN NAME A FILE THAT IS NOT THE CLASS'S MODULE (THE PREFLIGHT TEST)
    if design_file_path_str_in:
        return str(design_file_path_str_in)
    if hasattr(design_in, "__file__") and design_in.__file__:
        return str(design_in.__file__)
    try:
        return inspect.getfile(design_in if inspect.isfunction(design_in) or inspect.ismodule(design_in) or inspect.isclass(design_in) else design_in.__class__)
    except TypeError:
        return None


# FUNCTION: WHETHER THE PATH IS THIS REPO'S TESTS PACKAGE
def get_tests_path_bool(file_path_str_in):
    """
    True when the file lives under the workspace tests folder. In-process helper designs in test_runner.py are not
    experiment design files.

    Args:
        file_path_str_in (str): Path

    Returns:
        bool: True if under tests/
    """
    # NORMALIZE SO WINDOWS AND POSIX SEPARATORS MATCH
    norm_str = os.path.normcase(os.path.abspath(file_path_str_in))
    tests_str = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests")))
    return norm_str.startswith(tests_str + os.sep)


# FUNCTION: REFUSE A signal THAT IS A METHOD, A CLOSURE OR A LAMBDA
def check_minute_signal(design_module_in):
    """
    Minute mode requires a module-level function signal(rows, model). A bound method, a nested function that
    closes over cells, or a lambda is refused.

    Args:
        design_module_in (module): Design module

    Returns:
        None
    """
    # THE NAME ON THE MODULE IS WHAT THE RUNNER CALLS
    design_name_str = str(getattr(design_module_in, "EXPERIMENT_NAME",
                                  getattr(design_module_in, "__name__", "minute_design")))
    if not hasattr(design_module_in, "signal"):
        raise ValueError(f"minute design {design_name_str} is missing signal")
    signal_func = design_module_in.signal
    if inspect.ismethod(signal_func):
        raise ValueError(f"minute signal must be a module-level function, not a method: {design_name_str}")
    if inspect.ismethoddescriptor(signal_func) or inspect.isbuiltin(signal_func):
        raise ValueError(f"minute signal must be a module-level function, not a method: {design_name_str}")
    if not inspect.isfunction(signal_func):
        raise ValueError(f"minute signal must be a module-level function: {design_name_str}")
    if signal_func.__name__ == "<lambda>":
        raise ValueError(f"minute signal must be a module-level function, not a lambda: {design_name_str}")
    if signal_func.__closure__ is not None:
        raise ValueError(f"minute signal must not be a closure: {design_name_str}")
    qual_str = str(getattr(signal_func, "__qualname__", signal_func.__name__))
    if "." in qual_str:
        raise ValueError(f"minute signal must be a module-level function, not a method: {design_name_str}")


# FUNCTION: REFUSE A signal DEFINED AS A METHOD OR ASSIGNED AS A LAMBDA IN THE DESIGN FILE
def check_minute_signal_tree(tree_in, file_path_str_in):
    """
    A FunctionDef named signal inside a class is a method. An assignment of a lambda to signal is not a function.

    Args:
        tree_in (ast.AST): Parsed module
        file_path_str_in (str): File being checked

    Returns:
        None
    """
    # ONLY THE MODULE BODY (NOT HELPERS NESTED INSIDE signal)
    for node in tree_in.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "signal":
                    raise ValueError(f"signal must be a module-level function, not a method: {file_path_str_in}")
        if isinstance(node, ast.Assign):
            name_bool = any(isinstance(target, ast.Name) and target.id == "signal" for target in node.targets)
            if name_bool and isinstance(node.value, ast.Lambda):
                raise ValueError(f"signal must be a module-level function, not a lambda: {file_path_str_in}")


# FUNCTION: RUN THE PREFLIGHT WHEN THE FILE IS A DESIGN FILE
def check_design_source(design_in, design_file_path_str_in=None):
    """
    Checks the named file always, including the experiments/ modules it imports. Checks a resolved module file unless
    it is under tests/.

    Args:
        design_in (object | callable): Design
        design_file_path_str_in (str | None): Explicit design file

    Returns:
        None
    """
    # AN EXPLICIT PATH IS ALWAYS CHECKED (INCLUDING TEMP FILES IN THE PREFLIGHT TEST)
    if design_file_path_str_in:
        check_design_file(str(design_file_path_str_in))
        return
    file_path_str = get_design_file_path_str(design_in, None)
    if file_path_str is None or get_tests_path_bool(file_path_str):
        return
    check_design_file(file_path_str)
