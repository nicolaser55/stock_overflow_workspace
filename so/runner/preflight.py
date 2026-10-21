import ast
import inspect
import os

"""
Design-file preflight (infrastructure step 4a)

The loop reads the design file as AST before the first decide() call and refuses names that reach around the view:
.base, __closure__, __self__, __globals__, __dict__, gc, inspect, sys._getframe, ctypes, and imports of so.runner,
so.core.point_in_time or so.core.holdout. The runner itself may use those; a design file may not.
"""

# ATTRIBUTE NAMES THAT REACH PAST THE VIEW
BANNED_ATTR_SET = {"base", "__closure__", "__self__", "__globals__", "__dict__", "_getframe"}
# BARE NAMES THAT LOAD ESCAPE HATCHES
BANNED_NAME_SET = {"gc", "inspect", "ctypes"}
# MODULES A DESIGN MUST NOT IMPORT
BANNED_MODULE_SET = {"so.runner", "so.core.point_in_time", "so.core.holdout"}


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


# FUNCTION: REFUSE A DESIGN FILE THAT CAN REACH AROUND THE VIEW
def check_design_file(file_path_str_in):
    """
    Parses the file and raises if a banned attribute, name or import is present.

    Args:
        file_path_str_in (str): Path of the design file

    Returns:
        None
    """
    # READ AS TEXT; THE FILE IS NOT EXECUTED
    source_str = open(file_path_str_in, "r", encoding="utf-8").read()
    tree = ast.parse(source_str, filename=file_path_str_in)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in BANNED_ATTR_SET:
            raise ValueError(f"design file uses banned name .{node.attr}: {file_path_str_in}")
        if isinstance(node, ast.Name) and node.id in BANNED_NAME_SET:
            raise ValueError(f"design file uses banned name {node.id}: {file_path_str_in}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for module_str in get_import_name_list(node):
                banned_str = get_banned_module_match_str(module_str)
                if banned_str is not None:
                    raise ValueError(f"design file imports {banned_str}: {file_path_str_in}")
                if module_str in BANNED_NAME_SET or module_str.split(".")[0] in BANNED_NAME_SET:
                    raise ValueError(f"design file uses banned name {module_str.split('.')[0]}: {file_path_str_in}")


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


# FUNCTION: RUN THE PREFLIGHT WHEN THE FILE IS A DESIGN FILE
def check_design_source(design_in, design_file_path_str_in=None):
    """
    Checks the named file always. Checks a resolved module file unless it is under tests/.

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
