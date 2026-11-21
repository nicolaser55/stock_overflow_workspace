# vm/data_acl.sh (2026-11-21): applies vm/data_acl.conf. Sourced by vm/setup_vm.sh (step 5) and
# vm/set_data_permissions.sh; run as root. Defines:
#   so_data_acl_apply        every managed folder (created if missing), then everything below it
#   so_data_acl_managed_list the managed folders, one per line
# Below a managed folder it replaces whatever a copy or an account left (tar sets each item's mode from the archive,
# which rewrites an ACL's mask and drops the setgid bit): see the header of vm/data_acl.conf for the rule. It never
# follows a link; a link or any other item that is neither a folder nor a regular file stops it (exit 1).

SO_DATA_ACL_CONF="${SO_DATA_ACL_CONF:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/data_acl.conf}"

# The table's rows (no comments, no blank lines)
so_data_acl_rows() {
    grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$SO_DATA_ACL_CONF"
}

so_data_acl_managed_list() {
    so_data_acl_rows | cut -d'|' -f1
}

# "u::rwx,g:x:r-x" -> "u::rw-,g:x:r--" (files get no x)
so_data_acl_no_x() {
    printf '%s' "$1" | sed -E 's/x(,|$)/-\1/g'
}

# "u::rwx,g::r-x" -> "d:u::rwx,d:g::r-x"
so_data_acl_as_default() {
    printf '%s' "$1" | sed -E 's/(^|,)/\1d:/g'
}

# A managed folder itself: replaces its ACL (not its children's)
so_data_acl_top() {
    local path_str="$1" owner_str="$2" mode_str="$3" access_str="$4" default_str="$5"
    mkdir -p "$path_str"
    chown "$owner_str" "$path_str"
    setfacl -b "$path_str"
    chmod "$mode_str" "$path_str"
    [ -z "$access_str" ] || setfacl -m "$access_str" "$path_str"
    [ -z "$default_str" ] || setfacl -d -m "$default_str" "$path_str"
}

# Everything below a managed folder, except deeper managed folders (they have their own row)
so_data_acl_below() {
    local path_str="$1" owner_str="$2" mode_str="$3" default_str="$4" tmp_str other_str prune_list=(-false) q_str
    local dir_count_int file_count_int file_mode_str
    while IFS= read -r q_str; do
        case "$q_str" in "$path_str"/*) prune_list+=(-o -path "$q_str") ;; esac
    done < <(so_data_acl_managed_list)
    tmp_str="$(mktemp -d)"
    find "$path_str" -mindepth 1 \( "${prune_list[@]}" \) -prune -o -type d -print0 > "$tmp_str/dirs"
    find "$path_str" -mindepth 1 \( "${prune_list[@]}" \) -prune -o -type f -print0 > "$tmp_str/files"
    find "$path_str" -mindepth 1 \( "${prune_list[@]}" \) -prune -o ! -type d ! -type f -print > "$tmp_str/other"
    other_str="$(sed -n '1,5p' "$tmp_str/other")"   # no early-exit pipe (set -o pipefail, gotcha: exit 141)
    if [ -n "$other_str" ]; then
        rm -rf -- "$tmp_str"
        printf 'STOP: items that are neither folders nor regular files below %s (first ones):\n%s\n' "$path_str" "$other_str" >&2
        return 1
    fi
    dir_count_int="$(tr -cd '\0' < "$tmp_str/dirs" | wc -c)"
    file_count_int="$(tr -cd '\0' < "$tmp_str/files" | wc -c)"
    xargs -0 -r chown -h -- "$owner_str" < "$tmp_str/dirs"
    xargs -0 -r chown -h -- "$owner_str" < "$tmp_str/files"
    if [ -n "$default_str" ]; then
        xargs -0 -r setfacl --set="$default_str,$(so_data_acl_as_default "$default_str")" -- < "$tmp_str/dirs"
        xargs -0 -r chmod u-s,o-t -- < "$tmp_str/dirs"
        case "$mode_str" in 2*) xargs -0 -r chmod g+s -- < "$tmp_str/dirs" ;; *) xargs -0 -r chmod g-s -- < "$tmp_str/dirs" ;; esac
        xargs -0 -r setfacl --set="$(so_data_acl_no_x "$default_str")" -- < "$tmp_str/files"
    else
        file_mode_str="$(printf '%o' $(( 8#$mode_str & 8#0666 )))"
        xargs -0 -r setfacl -b -- < "$tmp_str/dirs"
        xargs -0 -r chmod "$mode_str" -- < "$tmp_str/dirs"
        xargs -0 -r setfacl -b -- < "$tmp_str/files"
        xargs -0 -r chmod "$file_mode_str" -- < "$tmp_str/files"
    fi
    xargs -0 -r chmod ug-s,o-t -- < "$tmp_str/files"
    rm -rf -- "$tmp_str"
    printf '    %s: %s folders and %s files below set\n' "$path_str" "$dir_count_int" "$file_count_int"
}

so_data_acl_apply() {
    local path_str owner_str mode_str access_str default_str
    [ "$(id -u)" -eq 0 ] || { echo "STOP: so_data_acl_apply needs root" >&2; return 1; }
    while IFS='|' read -r path_str owner_str mode_str access_str default_str; do
        so_data_acl_top "$path_str" "$owner_str" "$mode_str" "$access_str" "$default_str"
    done < <(so_data_acl_rows)
    while IFS='|' read -r path_str owner_str mode_str access_str default_str; do
        so_data_acl_below "$path_str" "$owner_str" "$mode_str" "$default_str" || return 1
    done < <(so_data_acl_rows)
}
