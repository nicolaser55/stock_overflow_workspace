#!/usr/bin/env bash
# vm/set_data_permissions.sh (2026-11-21): after a data copy into so-vm (step 4 of claude/DESIGN_2026-11-18_linux_vm.md,
# and the store04 copy at the switch), gives every folder and file under the data folders the owner, mode and ACL of
# vm/data_acl.conf, then checks them. Reads no file's content.
#
#   sudo bash vm/set_data_permissions.sh          (on so-vm)
#   sudo bash vm/set_data_permissions.sh --ci     (the linux-setup CI job: any host name)
#   sudo bash vm/set_data_permissions.sh --check-only
#
# Steps: 1. checks (root, host, the runner service not running); 2. vm/data_acl.sh on every managed folder and
# everything below it; 3. vm/check_data_permissions.py (owner, group, mode bits and ACL of every item, from getfacl);
# 4. what the accounts can do, tried as the accounts with find's -readable/-writable/-executable (access checks, no
# reads): the runner reads every pipeline file and the control folder (with host_status/), writes everywhere in store04
# except judge/; so_host reaches no data zone; nobody but nico reaches the quarantine or the holdout. Exits 1 on any
# FAIL. vm/check_vm_access.sh is run separately.
set -uo pipefail
umask 022

VM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CI_MODE=0
CHECK_ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --ci) CI_MODE=1 ;;
        --check-only) CHECK_ONLY=1 ;;
        -h|--help) sed -n '2,15p' "$0"; exit 3 ;;
        *) echo "unknown argument: $1" >&2; exit 3 ;;
    esac
    shift
done

die() { printf 'STOP: %s\n' "$*" >&2; exit 1; }
fail_count=0
ok_count=0
ok() { ok_count=$((ok_count + 1)); printf 'OK    %s\n' "$*"; }
fail() { fail_count=$((fail_count + 1)); printf 'FAIL  %s\n' "$*"; }

DATA=/srv/so/data
ZONE4=$DATA/store04_experiments

printf '=== 1. Checks\n'
[ "$(id -u)" -eq 0 ] || die "run with sudo"
if [ "$CI_MODE" -eq 0 ]; then
    [ "$(hostname)" = "so-vm" ] || die "this is $(hostname), not so-vm"
fi
systemctl is-active --quiet so-queue-runner.service 2>/dev/null && die "so-queue-runner.service is running; stop it first"
for user_str in nico so_runner so_agent so_planner so_git so_host; do
    id "$user_str" >/dev/null 2>&1 || die "account $user_str missing (run vm/setup_vm.sh first)"
done
command -v setfacl >/dev/null && command -v getfacl >/dev/null || die "acl tools missing (run vm/setup_vm.sh first)"
printf '    ok\n'

if [ "$CHECK_ONLY" -eq 0 ]; then
    printf '\n=== 2. Owners, modes and ACLs (vm/data_acl.conf)\n'
    # shellcheck source=vm/data_acl.sh
    . "$VM_DIR/data_acl.sh"
    so_data_acl_apply || die "permissions not set (see above)"
fi

printf '\n=== 3. Every item against vm/data_acl.conf\n'
if python3 -I "$VM_DIR/check_data_permissions.py"; then ok "owners, modes and ACLs"; else fail "owners, modes and ACLs (see above)"; fi

printf '\n=== 4. What the accounts can do (access checks; nothing is read)\n'
# From / (2026-11-23, step-4 bug 1): runuser keeps the caller's folder, and find run by an account that cannot enter it
# prints "Failed to restore initial working directory", which counted as a FAIL
cd / || die "cannot change to /"
# as_find <account> <description> <folder> <find test...>: the account runs find on the folder and prints what matches
# the test; any output line or error is a FAIL
as_find() {
    local user_str="$1" label_str="$2" root_str="$3" out_str; shift 3
    out_str="$(runuser -u "$user_str" -- find "$root_str" \( "$@" \) -print 2>&1 | head -3)"
    if [ -z "$out_str" ]; then ok "$user_str: $label_str"
    else fail "$user_str: $label_str; first: $(printf '%s' "$out_str" | tr '\n' ' ')"; fi
}
# denied <account> <folder>: the account cannot list the folder
denied() {
    if runuser -u "$1" -- ls -A "$2" >/dev/null 2>&1; then fail "$1 can list $2"; else ok "$1 cannot list $2"; fi
}
for zone_str in store01_rawzone store02_workzone store03_goldzone; do
    as_find so_runner "reads every file and enters every folder of $zone_str" "$DATA/$zone_str" \
        \( -type f ! -readable \) -o \( -type d \( ! -readable -o ! -executable \) \)
    as_find so_runner "writes nothing in $zone_str" "$DATA/$zone_str" -writable
done
as_find so_runner "reads and writes everything in store04 outside judge/" "$ZONE4" \
    ! -path "$ZONE4/judge" ! -path "$ZONE4/judge/*" \( \( -type f \( ! -readable -o ! -writable \) \) -o \( -type d \( ! -readable -o ! -writable -o ! -executable \) \) \)
as_find so_runner "reads judge/ and writes nothing there" "$ZONE4/judge" ! -readable -o -writable
as_find so_runner "reads control/ (STOP) and writes nothing there" "$DATA/control" ! -readable -o -writable
for user_str in so_agent so_planner so_git so_host; do
    denied "$user_str" "$DATA/store01_rawzone"
    denied "$user_str" "$ZONE4/runs"
done
as_find so_agent "reads visible/status" "$ZONE4/visible/status" -type f ! -readable
as_find so_planner "reads visible/grades" "$ZONE4/visible/grades" -type f ! -readable
denied so_agent "$ZONE4/visible/grades"
denied so_planner "$ZONE4/visible/status"
as_find so_runner "reads control/host_status (the update guard's file) and writes nothing there" "$DATA/control/host_status" ! -readable -o -writable
for user_str in so_runner so_agent so_planner so_git so_host; do
    denied "$user_str" /srv/so/quarantine
    denied "$user_str" /srv/so/holdout
done
for root_str in /srv/so/quarantine /srv/so/holdout; do
    as_find nico "reads every file and enters every folder of $root_str" "$root_str" \
        \( -type f ! -readable \) -o \( -type d \( ! -readable -o ! -executable \) \)
done

printf '\n%d OK, %d FAIL\n' "$ok_count" "$fail_count"
[ "$fail_count" -eq 0 ]
