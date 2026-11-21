#!/usr/bin/env python3
"""
vm/data_manifest.py (2026-11-21): SHA-256 manifests of the data trees, the same code on Windows and on so-vm (step 4 of
claude/DESIGN_2026-11-18_linux_vm.md). Standard library only. It reads file bytes to hash them and prints nothing of
their content; nobody needs to read a manifest (compare does that).

    python -I vm/data_manifest.py scan    <root> <tree>...                 counts, sizes, links, long or non-ASCII names
    python -I vm/data_manifest.py make    <root> <tree>... --out <file>     the manifest (--jobs N threads, default 4)
    python -I vm/data_manifest.py compare <manifest A> <manifest B>         A = the source (Windows), B = the copy (VM)

<root> is the folder that holds the trees (D:\\stock_overflow on Windows, /srv/so on the VM); <tree> is a folder name
in it (data, quarantine, holdout). A manifest holds, sorted by path (forward slashes, relative to <root>):
    D<TAB><TAB><TAB><path>               a folder
    F<TAB><sha256><TAB><size><TAB><path> a regular file
    L<TAB><TAB><TAB><path>               anything else (a link, a junction, a device): never followed
and two header lines (format, trees). No host, time or root path, so the same data gives the same manifest bytes on
both systems. make prints the counts and the manifest's own SHA-256.

compare PASSes when the trees are the same, no L line exists, every file has the same size and hash, every folder of A
is in B, and every folder only in B is empty in B (the folders vm/setup_vm.sh makes). Exit 0 PASS, 1 FAIL, 2 usage.
"""
import argparse
import concurrent.futures
import hashlib
import os
import sys

FORMAT_LINE_STR = "# so-data-manifest 1"
CHUNK_INT = 8 * 1024 * 1024
LONG_PATH_INT = 240


def walk_tree(root_str, tree_str):
    """Yields (kind, rel path, absolute path, size) for the tree and everything in it, folders first per level."""
    top_str = os.path.join(root_str, tree_str)
    if not os.path.isdir(top_str) or os.path.islink(top_str):
        raise SystemExit(f"STOP: {top_str} is not a folder")
    stack_list = [(top_str, tree_str)]
    yield ("D", tree_str, top_str, 0)
    while stack_list:
        abs_dir_str, rel_dir_str = stack_list.pop()
        with os.scandir(abs_dir_str) as entry_iter:
            entry_list = sorted(entry_iter, key=lambda e: e.name)
        for entry in entry_list:
            rel_str = f"{rel_dir_str}/{entry.name}"
            is_junction_bool = bool(getattr(entry, "is_junction", lambda: False)())
            if entry.is_symlink() or is_junction_bool:
                yield ("L", rel_str, entry.path, 0)
            elif entry.is_dir(follow_symlinks=False):
                yield ("D", rel_str, entry.path, 0)
                stack_list.append((entry.path, rel_str))
            elif entry.is_file(follow_symlinks=False):
                yield ("F", rel_str, entry.path, entry.stat(follow_symlinks=False).st_size)
            else:
                yield ("L", rel_str, entry.path, 0)


def hash_file(path_str):
    hasher = hashlib.sha256()
    with open(path_str, "rb") as file_obj:
        while True:
            chunk_bytes = file_obj.read(CHUNK_INT)
            if not chunk_bytes:
                break
            hasher.update(chunk_bytes)
    return hasher.hexdigest()


def cmd_scan(args):
    total = {"D": 0, "F": 0, "L": 0}
    for tree_str in args.trees:
        count = {"D": 0, "F": 0, "L": 0}
        size_int, long_list, ascii_list, link_list, longest_int = 0, [], [], [], 0
        for kind_str, rel_str, abs_str, entry_size_int in walk_tree(args.root, tree_str):
            count[kind_str] += 1
            size_int += entry_size_int
            longest_int = max(longest_int, len(abs_str))
            if len(abs_str) > LONG_PATH_INT:
                long_list.append(rel_str)
            if not rel_str.isascii():
                ascii_list.append(rel_str.encode("ascii", "backslashreplace").decode())
            if kind_str == "L":
                link_list.append(rel_str)
        for k in total:
            total[k] += count[k]
        print(f"{tree_str}: {count['F']} files, {count['D']} folders, {size_int} bytes ({size_int / 1e9:.1f} GB), "
              f"{count['L']} links or other items, longest full path {longest_int} characters, "
              f"{len(long_list)} paths over {LONG_PATH_INT}, {len(ascii_list)} non-ASCII names")
        for label_str, item_list in (("link or other item", link_list), (f"path over {LONG_PATH_INT}", long_list),
                                     ("non-ASCII name", ascii_list)):
            for rel_str in item_list[:5]:
                print(f"    {label_str}: {rel_str}")
    return 1 if total["L"] else 0


def cmd_make(args):
    entry_list = []
    for tree_str in args.trees:
        entry_list.extend(walk_tree(args.root, tree_str))
    entry_list.sort(key=lambda e: e[1])
    file_list = [e for e in entry_list if e[0] == "F"]
    total_int = sum(e[3] for e in file_list)
    print(f"hashing {len(file_list)} files, {total_int / 1e9:.1f} GB, {args.jobs} threads", file=sys.stderr, flush=True)
    hash_dict, done_int, next_report_int, error_list = {}, 0, 5 * 10 ** 9, []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        future_dict = {pool.submit(hash_file, e[2]): e for e in file_list}
        for future in concurrent.futures.as_completed(future_dict):
            e = future_dict[future]
            try:
                hash_dict[e[1]] = future.result()
            except OSError as error:
                error_list.append(f"{e[1]}: {type(error).__name__}")
            done_int += e[3]
            if done_int >= next_report_int:
                print(f"    {done_int / 1e9:.0f} of {total_int / 1e9:.0f} GB", file=sys.stderr, flush=True)
                next_report_int += 5 * 10 ** 9
    if error_list:
        for line_str in error_list[:20]:
            print(f"FAIL  could not read {line_str}")
        print(f"STOP: {len(error_list)} files could not be read; no manifest written")
        return 1
    line_list = [FORMAT_LINE_STR, "# trees: " + " ".join(sorted(args.trees))]
    for kind_str, rel_str, _abs_str, size_int in entry_list:
        if kind_str == "F":
            line_list.append(f"F\t{hash_dict[rel_str]}\t{size_int}\t{rel_str}")
        else:
            line_list.append(f"{kind_str}\t\t\t{rel_str}")
    content_bytes = ("\n".join(line_list) + "\n").encode("utf-8", "surrogateescape")
    with open(args.out, "wb") as out_file:
        out_file.write(content_bytes)
    count = {k: sum(1 for e in entry_list if e[0] == k) for k in "DFL"}
    print(f"{count['F']} files, {count['D']} folders, {count['L']} links or other items, {total_int} bytes")
    print(f"manifest sha256 {hashlib.sha256(content_bytes).hexdigest()}  {os.path.basename(args.out)}")
    return 1 if count["L"] else 0


def read_manifest(path_str):
    with open(path_str, "rb") as in_file:
        line_list = in_file.read().decode("utf-8", "surrogateescape").split("\n")
    if not line_list or line_list[0] != FORMAT_LINE_STR or not line_list[1].startswith("# trees: "):
        raise SystemExit(f"STOP: {path_str} is not a manifest of this format")
    item_dict = {}
    for line_str in line_list[2:]:
        if not line_str:
            continue
        kind_str, hash_str, size_str, rel_str = line_str.split("\t", 3)
        item_dict[rel_str] = (kind_str, hash_str, size_str)
    return line_list[1], item_dict


def cmd_compare(args):
    trees_a_str, a_dict = read_manifest(args.a)
    trees_b_str, b_dict = read_manifest(args.b)
    problem_dict = {}

    def add(label_str, rel_str):
        problem_dict.setdefault(label_str, []).append(rel_str)

    if trees_a_str != trees_b_str:
        add("different trees", f"A {trees_a_str!r}, B {trees_b_str!r}")
    for rel_str, (kind_str, hash_str, size_str) in a_dict.items():
        other = b_dict.get(rel_str)
        if kind_str == "L":
            add("link or other item in A", rel_str)
        elif other is None:
            add("file only in A (missing in the copy)" if kind_str == "F" else "folder only in A (missing in the copy)", rel_str)
        elif other[0] != kind_str:
            add("different kind (file vs folder)", rel_str)
        elif kind_str == "F" and (other[1] != hash_str or other[2] != size_str):
            add("different size or hash", rel_str)
    b_dir_set = set()
    for rel_str, (kind_str, _hash_str, _size_str) in b_dict.items():
        if kind_str == "L":
            add("link or other item in B", rel_str)
        elif rel_str not in a_dict:
            if kind_str == "F":
                add("file only in B (extra in the copy)", rel_str)
            else:
                b_dir_set.add(rel_str)
    # A folder only in B is allowed when nothing in B is below it (an empty folder the setup made)
    allowed_list = []
    for rel_str in sorted(b_dir_set):
        if any(other_str.startswith(rel_str + "/") and other_str not in b_dir_set for other_str in b_dict):
            add("folder only in B that holds files", rel_str)
        else:
            allowed_list.append(rel_str)
    file_int = sum(1 for v in a_dict.values() if v[0] == "F")
    byte_int = sum(int(v[2]) for v in a_dict.values() if v[0] == "F")
    print(f"A: {file_int} files, {sum(1 for v in a_dict.values() if v[0] == 'D')} folders, {byte_int} bytes; "
          f"B: {sum(1 for v in b_dict.values() if v[0] == 'F')} files, {sum(1 for v in b_dict.values() if v[0] == 'D')} folders")
    print(f"INFO  {len(allowed_list)} empty folders only in B (made by vm/setup_vm.sh): {', '.join(allowed_list[:20])}"
          + (" ..." if len(allowed_list) > 20 else ""))
    for label_str, item_list in sorted(problem_dict.items()):
        print(f"FAIL  {label_str}: {len(item_list)}")
        for rel_str in item_list[:20]:
            print(f"      {rel_str}")
    fail_int = sum(len(v) for v in problem_dict.values())
    print("PASS  manifests identical (apart from the empty folders above)" if fail_int == 0 else f"{fail_int} FAIL")
    return 1 if fail_int else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan")
    scan.add_argument("root")
    scan.add_argument("trees", nargs="+")
    make = sub.add_parser("make")
    make.add_argument("root")
    make.add_argument("trees", nargs="+")
    make.add_argument("--out", required=True)
    make.add_argument("--jobs", type=int, default=4)
    compare = sub.add_parser("compare")
    compare.add_argument("a")
    compare.add_argument("b")
    args = parser.parse_args()
    return {"scan": cmd_scan, "make": cmd_make, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
