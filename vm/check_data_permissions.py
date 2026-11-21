#!/usr/bin/env python3
"""
vm/check_data_permissions.py (2026-11-21): checks that every folder and file under the managed data folders has the
owner, group, mode bits and ACL that vm/data_acl.conf gives it (see that file's header for the rule below a managed
folder). Run as root; it reads metadata only (getfacl -R), never a file's content.

    sudo python3 -I vm/check_data_permissions.py              # every managed folder
    sudo python3 -I vm/check_data_permissions.py --max-show 50

Prints one line per kind of mismatch (the first --max-show paths of each), then "N items checked, M FAIL", and exits 1
on any FAIL. A missing managed folder is a FAIL.
"""
import argparse
import os
import re
import subprocess
import sys

CONF_PATH_STR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_acl.conf")
TAG_DICT = {"u": "user", "g": "group", "o": "other", "m": "mask"}


def read_rows(conf_path_str):
    """Rows of data_acl.conf: list of (path, owner, group, mode int, access entries, default entries)."""
    row_list = []
    with open(conf_path_str, "r", encoding="utf-8") as conf_file:
        for line_str in conf_file:
            line_str = line_str.strip()
            if not line_str or line_str.startswith("#"):
                continue
            path_str, owner_group_str, mode_str, access_str, default_str = line_str.split("|")
            owner_str, group_str = owner_group_str.split(":")
            row_list.append((path_str, owner_str, group_str, int(mode_str, 8),
                             [e for e in access_str.split(",") if e], [e for e in default_str.split(",") if e]))
    return row_list


def norm_entry(entry_str):
    """'g:so_data:r-x' -> ('group', 'so_data', 'r-x')."""
    tag_str, name_str, perm_str = entry_str.split(":")
    return (TAG_DICT.get(tag_str, tag_str), name_str, perm_str)


def perm_union(perm_list):
    """Union of 'r-x' style permissions."""
    return "".join(c if any(p[i] == c for p in perm_list) else "-" for i, c in enumerate("rwx"))


def with_mask(entry_set):
    """Adds the mask setfacl computes (union of the group class) when there are named entries."""
    named_list = [e for e in entry_set if e[0] in ("user", "group") and e[1]]
    if not named_list:
        return frozenset(entry_set)
    group_class_list = [e[2] for e in entry_set if e[0] == "group" or (e[0] == "user" and e[1])]
    return frozenset(set(entry_set) | {("mask", "", perm_union(group_class_list))})


def mode_entries(mode_int):
    """The three base entries of a mode."""
    def bits(shift_int):
        v = (mode_int >> shift_int) & 7
        return ("r" if v & 4 else "-") + ("w" if v & 2 else "-") + ("x" if v & 1 else "-")
    return {("user", "", bits(6)), ("group", "", bits(3)), ("other", "", bits(0))}


def no_x(entry_set):
    return {(t, n, p[:2] + "-") for t, n, p in entry_set}


def expected_dict(row, is_top_bool, is_dir_bool):
    """owner, group, setgid flag, access entry set, default entry set for an item."""
    path_str, owner_str, group_str, mode_int, access_list, default_list = row
    default_set = {norm_entry(e) for e in default_list}
    if is_top_bool:
        access_set = mode_entries(mode_int) | {norm_entry(e) for e in access_list}
        return {"owner": owner_str, "group": group_str, "setgid": bool(mode_int & 0o2000),
                "access": with_mask(access_set), "default": with_mask(default_set) if default_set else frozenset()}
    if default_set:
        if is_dir_bool:
            return {"owner": owner_str, "group": group_str, "setgid": bool(mode_int & 0o2000),
                    "access": with_mask(default_set), "default": with_mask(default_set)}
        return {"owner": owner_str, "group": group_str, "setgid": False, "access": with_mask(no_x(default_set)),
                "default": frozenset()}
    base_set = mode_entries(mode_int) if is_dir_bool else no_x(mode_entries(mode_int))
    return {"owner": owner_str, "group": group_str, "setgid": bool(mode_int & 0o2000) and is_dir_bool,
            "access": frozenset(base_set), "default": frozenset()}


def unescape(path_str):
    """getfacl writes some bytes as \\ooo; turn them back."""
    raw_bytes = re.sub(rb"\\([0-7]{3})", lambda m: bytes([int(m.group(1), 8)]), path_str.encode("utf-8", "surrogateescape"))
    return raw_bytes.decode("utf-8", "surrogateescape")


def read_getfacl(root_str):
    """getfacl -R -p -E on a tree: path -> dict(owner, group, flags, access set, default set)."""
    out_bytes = subprocess.run(["getfacl", "-R", "-P", "-p", "-E", root_str], check=True, stdout=subprocess.PIPE).stdout
    item_dict, cur = {}, None
    for line_str in out_bytes.decode("utf-8", "surrogateescape").splitlines():
        if line_str.startswith("# file: "):
            cur = {"owner": "", "group": "", "flags": "", "access": set(), "default": set()}
            item_dict[unescape(line_str[len("# file: "):])] = cur
        elif cur is None or not line_str:
            continue
        elif line_str.startswith("# owner: "):
            cur["owner"] = line_str[len("# owner: "):]
        elif line_str.startswith("# group: "):
            cur["group"] = line_str[len("# group: "):]
        elif line_str.startswith("# flags: "):
            cur["flags"] = line_str[len("# flags: "):]
        elif line_str.startswith("default:"):
            cur["default"].add(tuple(line_str[len("default:"):].split(":")))
        else:
            cur["access"].add(tuple(line_str.split(":")))
    return item_dict


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--conf", default=CONF_PATH_STR)
    parser.add_argument("--max-show", type=int, default=10)
    args = parser.parse_args()
    row_list = read_rows(args.conf)
    managed_dict = {row[0]: row for row in row_list}
    fail_dict, checked_int = {}, 0

    def fail(kind_str, path_str):
        fail_dict.setdefault(kind_str, []).append(path_str)

    root_list = [p for p in managed_dict if not any(p.startswith(q + "/") for q in managed_dict if q != p)]
    for root_str in root_list:
        if not os.path.isdir(root_str):
            fail("managed folder missing", root_str)
            continue
        for dir_str, dir_name_list, file_name_list in os.walk(root_str):
            for name_str in dir_name_list + file_name_list:
                entry_str = os.path.join(dir_str, name_str)
                if os.path.islink(entry_str) or not (os.path.isdir(entry_str) or os.path.isfile(entry_str)):
                    fail("not a folder or regular file", entry_str)
        item_dict = read_getfacl(root_str)
        for path_str, got in item_dict.items():
            checked_int += 1
            st = os.lstat(path_str)
            is_dir_bool = os.path.isdir(path_str) and not os.path.islink(path_str)
            if os.path.islink(path_str) or not (is_dir_bool or os.path.isfile(path_str)):
                continue
            # The managed folder that rules this item: itself, or the deepest one above it
            if path_str in managed_dict:
                row, is_top_bool = managed_dict[path_str], True
            else:
                owner_list = [q for q in managed_dict if path_str.startswith(q + "/")]
                row, is_top_bool = managed_dict[max(owner_list, key=len)], False
            want = expected_dict(row, is_top_bool, is_dir_bool)
            if got["owner"] != want["owner"] or got["group"] != want["group"]:
                fail(f"owner:group not {want['owner']}:{want['group']}", path_str)
            if bool(st.st_mode & 0o2000) != want["setgid"]:
                fail(f"setgid bit not {'set' if want['setgid'] else 'clear'}", path_str)
            if st.st_mode & (0o4000 | 0o1000) or (not is_dir_bool and st.st_mode & 0o2000):
                fail("setuid or sticky bit set", path_str)
            if frozenset(got["access"]) != want["access"]:
                fail("access ACL differs", path_str)
            if frozenset(got["default"]) != want["default"]:
                fail("default ACL differs", path_str)
    for kind_str, path_list in sorted(fail_dict.items()):
        shown_str = "\n      ".join(path_list[:args.max_show])
        more_str = f"\n      ... and {len(path_list) - args.max_show} more" if len(path_list) > args.max_show else ""
        print(f"FAIL  {kind_str}: {len(path_list)}\n      {shown_str}{more_str}")
    fail_int = sum(len(v) for v in fail_dict.values())
    print(f"{checked_int} items checked under {len(root_list)} roots, {fail_int} FAIL")
    return 1 if fail_int else 0


if __name__ == "__main__":
    sys.exit(main())
