#!/usr/bin/env bash
# vm/check_vm_access.sh (2026-11-19): every account tries every access on so-vm; prints OK or FAIL per line and exits 1
# on any FAIL. Run as root (vm/setup_vm.sh runs it at its end; run it again any time):
#
#   sudo bash vm/check_vm_access.sh --mail-to <address> --agent-key <nicosls_sovm_agent.pub>
#        [--expect-agent-fingerprint SHA256:...] [--ci] [--send-test-mail]
#        [--status-from <address>] [--status-key <so_vm_status_ed25519.pub>]
#
# A refusal counts only when the system says "Permission denied" (or the network refuses): a missing path is a FAIL,
# as in scripts/check_agent_access.py. It writes small probe files (.so_access_probe) and removes them again; it opens
# no data file. --send-test-mail also sends one real email through the relay to --mail-to (on so-vm, not in CI).
set -uo pipefail

CI_MODE=0
MAIL_TO=""
AGENT_KEY_FILE=""
EXPECT_FPR=""
SEND_MAIL=0
STATUS_FROM="100.123.162.2"
STATUS_KEY_FILE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --ci) CI_MODE=1 ;;
        --mail-to) MAIL_TO="${2:-}"; shift ;;
        --agent-key) AGENT_KEY_FILE="${2:-}"; shift ;;
        --expect-agent-fingerprint) EXPECT_FPR="${2:-}"; shift ;;
        --send-test-mail) SEND_MAIL=1 ;;
        --status-from) STATUS_FROM="${2:-}"; shift ;;
        --status-key) STATUS_KEY_FILE="${2:-}"; shift ;;
        *) echo "unknown argument: $1" >&2; exit 3 ;;
    esac
    shift
done
[ "$(id -u)" -eq 0 ] || { echo "run with sudo" >&2; exit 3; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=vm/versions.env
. "$REPO_DIR/vm/versions.env"
DATA=/srv/so/data
ZONE4=$DATA/store04_experiments
MIRROR=/srv/so/git/stock_overflow_workspace.git
INBOX=/srv/so/git/agent_inbox.git
RUNNER_WS=/srv/so/runner_workspace
AGENT_WS=/home/so_agent/agent_workspace
PLANNER_DIR=/home/so_planner/planner
VENV=/opt/so/venvs/main
PROBE=.so_access_probe
HOST_STATUS_DIR=$DATA/control/host_status
RECEIVER=/usr/local/lib/so/so-host-status
STATUS_KEYS=/etc/so/ssh/so_host_authorized_keys

ok_count=0
fail_count=0
ok() { ok_count=$((ok_count + 1)); printf 'OK    %s\n' "$*"; }
fail() { fail_count=$((fail_count + 1)); printf 'FAIL  %s\n' "$*"; }
section() { printf '\n--- %s\n' "$*"; }

# Run a command as an account, with a login-like clean environment (no caller variables)
as_user() {
    local user_str="$1"; shift
    runuser -u "$user_str" -- env -i HOME="$(getent passwd "$user_str" | cut -d: -f6)" PATH=/usr/bin:/bin LANG=C.UTF-8 "$@"
}

# expect <allowed|denied> <account> <what> <label>: what = list:<dir> | read:<file> | write:<dir> | exec:<file>
expect() {
    local want_str="$1" user_str="$2" what_str="$3" label_str="$4" kind_str path_str out_str rc_int got_str
    kind_str="${what_str%%:*}"; path_str="${what_str#*:}"
    case "$kind_str" in
        list) out_str="$(as_user "$user_str" ls -A "$path_str" 2>&1 >/dev/null)"; rc_int=$? ;;
        read) out_str="$(as_user "$user_str" head -c 1 "$path_str" 2>&1 >/dev/null)"; rc_int=$? ;;
        write) out_str="$(as_user "$user_str" sh -c 'f="$1/.so_access_write.$$" && : > "$f" && rm -f "$f"' sh "$path_str" 2>&1)"; rc_int=$? ;;
        exec) out_str="$(as_user "$user_str" "$path_str" -c 'pass' 2>&1)"; rc_int=$? ;;
        *) fail "bad check $what_str"; return ;;
    esac
    if [ "$rc_int" -eq 0 ]; then got_str=allowed
    elif printf '%s' "$out_str" | grep -qi "permission denied"; then got_str=denied
    else got_str="error: $(printf '%s' "$out_str" | head -1)"; fi
    if [ "$got_str" = "$want_str" ]; then ok "$user_str $kind_str $label_str: $got_str"
    else fail "$user_str $kind_str $label_str: expected $want_str, got $got_str"; fi
}

# A probe file in a folder, created by the account that normally writes there (so inherited ACLs are what is tested)
make_probe() {
    local user_str="$1" dir_str="$2"
    as_user "$user_str" sh -c 'umask 027; printf probe > "$1"' sh "$dir_str/$PROBE" 2>/dev/null \
        || { fail "could not create the probe in $dir_str as $user_str"; return 1; }
}

# tcp <allowed|refused> <account> <host> <port> <label>: a plain TCP connect from bash
tcp() {
    local want_str="$1" user_str="$2" host_str="$3" port_int="$4" label_str="$5" got_str
    if as_user "$user_str" timeout 8 bash -c 'exec 3<>/dev/tcp/$1/$2' bash "$host_str" "$port_int" 2>/dev/null; then got_str=allowed
    else got_str=refused; fi
    if [ "$got_str" = "$want_str" ]; then ok "$user_str tcp $label_str ($host_str:$port_int): $got_str"
    else fail "$user_str tcp $label_str ($host_str:$port_int): expected $want_str, got $got_str"; fi
}

# https <allowed|refused> <account> <url> <proxy or -> <label>: an HTTPS request; any HTTP answer counts as reached
https() {
    local want_str="$1" user_str="$2" url_str="$3" proxy_str="$4" label_str="$5" code_str got_str
    if [ "$proxy_str" = "-" ]; then
        code_str="$(as_user "$user_str" curl -s -o /dev/null -m 15 -w '%{http_code}' --noproxy '*' "$url_str" 2>/dev/null)"
    else
        code_str="$(as_user "$user_str" curl -s -o /dev/null -m 15 -w '%{http_code}' -x "$proxy_str" "$url_str" 2>/dev/null)"
    fi
    if [ -n "$code_str" ] && [ "$code_str" != "000" ]; then got_str=allowed; else got_str=refused; fi
    if [ "$got_str" = "$want_str" ]; then ok "$user_str https $label_str: $got_str (HTTP ${code_str:-none})"
    else fail "$user_str https $label_str: expected $want_str, got $got_str (HTTP ${code_str:-none})"; fi
}

# ---------------------------------------------------------------------------------------------------------------------
section "Probe files (removed at the end, also when the check is interrupted)"
# The folders that get a probe; the trap removes probes (and the write-test files) from all of them on any exit
PROBE_DIR_LIST=($DATA $DATA/store01_rawzone $DATA/store02_workzone $DATA/store03_goldzone $ZONE4 $ZONE4/judge
    $ZONE4/queue/pending $ZONE4/runs $ZONE4/visible $ZONE4/visible/grades $ZONE4/visible/status $DATA/control $HOST_STATUS_DIR
    /srv/so/quarantine /srv/so/holdout $PLANNER_DIR/brief $PLANNER_DIR/plans /home/nico)
tmp_clone=""
tmp_status=""
cleanup_probes() {
    local dir_str
    for dir_str in "${PROBE_DIR_LIST[@]}"; do
        [ -d "$dir_str" ] && find "$dir_str" -maxdepth 1 -type f \( -name "$PROBE" -o -name '.so_access_write.*' \) -delete 2>/dev/null
    done
    case "$tmp_clone" in /home/so_agent/.so_access_clone.*) rm -rf -- "$tmp_clone" ;; esac
    case "$tmp_status" in /var/tmp/.so_status_check.*) rm -rf -- "$tmp_status" ;; esac
    return 0
}
trap cleanup_probes EXIT
trap 'echo "interrupted: probes removed" >&2; exit 130' INT TERM HUP
probe_dir_list=()
add_probe() { make_probe "$1" "$2" && probe_dir_list+=("$2"); }
add_probe nico $DATA
add_probe nico $DATA/store01_rawzone
add_probe nico $DATA/store02_workzone
add_probe nico $DATA/store03_goldzone
add_probe so_runner $ZONE4
add_probe nico $ZONE4/judge
add_probe nico $ZONE4/queue/pending
add_probe so_runner $ZONE4/runs
add_probe so_runner $ZONE4/visible
add_probe so_runner $ZONE4/visible/grades
add_probe so_runner $ZONE4/visible/status
add_probe nico $DATA/control
add_probe so_host $HOST_STATUS_DIR
add_probe nico /srv/so/quarantine
add_probe nico /srv/so/holdout
add_probe nico $PLANNER_DIR/brief
add_probe so_planner $PLANNER_DIR/plans
add_probe nico /home/nico
ok "probes written in ${#probe_dir_list[@]} folders"

# ---------------------------------------------------------------------------------------------------------------------
section "Data root and experiment zone"
expect allowed so_runner list:$DATA "data root"
expect allowed so_runner read:$DATA/store01_rawzone/$PROBE "store01 file"
expect denied  so_runner write:$DATA/store01_rawzone "store01"
expect allowed so_runner read:$ZONE4/$PROBE "store04 file"
expect allowed so_runner write:$ZONE4 "store04"
expect allowed so_runner read:$ZONE4/judge/$PROBE "judge file"
expect denied  so_runner write:$ZONE4/judge "judge/"
expect allowed so_runner write:$ZONE4/queue/pending "queue/pending"
expect allowed so_runner write:$ZONE4/visible/grades "visible/grades"
expect allowed so_runner read:$DATA/control/$PROBE "control file"
expect denied  so_runner write:$DATA/control "control/"
for user_str in so_agent so_planner; do
    expect denied $user_str list:$DATA "data root"
    expect denied $user_str read:$DATA/$PROBE "data root file"
    expect denied $user_str list:$DATA/store01_rawzone "store01"
    expect denied $user_str read:$DATA/store01_rawzone/$PROBE "store01 file"
    expect denied $user_str read:$DATA/store02_workzone/$PROBE "store02 file"
    expect denied $user_str read:$DATA/store03_goldzone/$PROBE "store03 file"
    expect denied $user_str list:$ZONE4 "store04"
    expect denied $user_str read:$ZONE4/$PROBE "store04 file (trial log, run index)"
    expect denied $user_str read:$ZONE4/judge/$PROBE "judge file"
    expect denied $user_str list:$ZONE4/queue/pending "queue/pending"
    expect denied $user_str write:$ZONE4/queue/pending "queue/pending"
    expect denied $user_str read:$ZONE4/queue/pending/$PROBE "queue/pending file"
    expect denied $user_str read:$ZONE4/runs/$PROBE "runs file"
    expect allowed $user_str list:$ZONE4/visible "visible/"
    expect allowed $user_str read:$ZONE4/visible/$PROBE "visible file (state.json)"
    expect denied $user_str write:$ZONE4/visible "visible/"
    expect allowed $user_str read:$DATA/control/$PROBE "control file (STOP)"
    expect denied $user_str write:$DATA/control "control/"
done
expect denied  so_agent list:$ZONE4/visible/grades "visible/grades"
expect denied  so_agent read:$ZONE4/visible/grades/$PROBE "visible/grades file"
expect allowed so_agent read:$ZONE4/visible/status/$PROBE "visible/status file"
expect allowed so_planner read:$ZONE4/visible/grades/$PROBE "visible/grades file"
expect denied  so_planner read:$ZONE4/visible/status/$PROBE "visible/status file"
expect denied  so_git list:$DATA "data root"
expect allowed nico write:$ZONE4/judge "judge/"
expect allowed nico write:$DATA/control "control/"
# control/host_status/ (2026-11-23): only so_host writes; the runner's group reads (the update guard)
expect allowed so_runner read:$HOST_STATUS_DIR/$PROBE "host_status file"
expect denied  so_runner write:$HOST_STATUS_DIR "control/host_status/"
expect allowed nico read:$HOST_STATUS_DIR/$PROBE "host_status file"
expect denied  nico write:$HOST_STATUS_DIR "control/host_status/"
expect allowed so_host write:$HOST_STATUS_DIR "control/host_status/"
expect denied  so_host write:$DATA/control "control/ (STOP)"
expect denied  so_host read:$DATA/control/$PROBE "control file (STOP)"
expect denied  so_host list:$DATA "data root"
expect denied  so_host list:$ZONE4 "store04"
expect denied  so_host read:$DATA/store01_rawzone/$PROBE "store01 file"
for user_str in so_agent so_planner so_git; do
    expect denied $user_str read:$HOST_STATUS_DIR/$PROBE "host_status file"
done

section "Quarantine, holdout, homes and clones"
for user_str in so_runner so_agent so_planner so_git so_host; do
    expect denied $user_str read:/srv/so/quarantine/$PROBE "quarantine file"
    expect denied $user_str read:/srv/so/holdout/$PROBE "holdout file"
    expect denied $user_str read:/home/nico/$PROBE "nico's home"
done
expect allowed so_runner write:$RUNNER_WS "runner clone"
expect denied  so_agent list:$RUNNER_WS "runner clone"
expect denied  so_planner list:$RUNNER_WS "runner clone"
expect allowed nico read:$RUNNER_WS/README.md "runner clone"
expect allowed so_agent write:$AGENT_WS "agent clone"
expect denied  so_runner list:$AGENT_WS "agent clone"
expect denied  so_planner list:$AGENT_WS "agent clone"
expect denied  so_git list:$AGENT_WS "agent clone"
expect allowed nico read:$AGENT_WS/README.md "agent clone"
expect allowed so_planner read:$PLANNER_DIR/brief/$PROBE "brief file"
expect denied  so_planner write:$PLANNER_DIR/brief "brief/"
expect allowed so_planner write:$PLANNER_DIR/plans "plans/"
expect allowed nico read:$PLANNER_DIR/plans/$PROBE "plans file"
for user_str in so_runner so_agent so_git; do
    expect denied $user_str read:$PLANNER_DIR/brief/$PROBE "brief file"
done

section "git: mirror, inbox, token, helper"
expect allowed so_runner read:$MIRROR/HEAD "mirror"
expect allowed so_agent read:$MIRROR/HEAD "mirror"
expect denied  so_runner write:$MIRROR/refs/heads "mirror refs"
expect denied  so_agent write:$MIRROR/refs/heads "mirror refs"
expect denied  so_planner read:$MIRROR/HEAD "mirror"
expect allowed so_agent write:$INBOX/refs/heads "inbox refs"
expect denied  so_agent write:$INBOX "inbox top folder (config, hooks)"
expect denied  so_agent write:$INBOX/hooks "inbox hooks"
expect denied  so_runner read:$INBOX/HEAD "inbox"
expect allowed so_git read:$INBOX/HEAD "inbox"
if [ -f /etc/so/git/agent_token ]; then
    expect allowed so_git read:/etc/so/git/agent_token "agent token"
    for user_str in so_runner so_agent so_planner nico; do expect denied $user_str read:/etc/so/git/agent_token "agent token"; done
else
    ok "agent token not installed yet (the push and pr tests below stop before it)"
fi
for user_str in so_runner so_agent so_planner nico; do expect denied $user_str read:/etc/postfix/sasl_passwd "relay login"; done
autocrlf_str="$(as_user so_runner git -C $RUNNER_WS config core.autocrlf || true)"
[ "$autocrlf_str" = "true" ] && ok "runner clone core.autocrlf true" || fail "runner clone core.autocrlf is '${autocrlf_str}', expected true"
[ -z "$(git config --system core.autocrlf || true)" ] && ok "no system-wide core.autocrlf" || fail "/etc/gitconfig sets core.autocrlf"
[ "$(as_user so_agent git -C $AGENT_WS remote get-url --push origin)" = "$INBOX" ] && ok "agent clone pushes to the inbox" || fail "agent clone push URL is not the inbox"
# The agent clone's origin/main (open item 1, 2026-11-21): it exists and is the mirror's main or an older commit of it
agent_main_str="$(as_user so_agent git -C $AGENT_WS rev-parse --verify -q refs/remotes/origin/main 2>/dev/null || true)"
mirror_main_str="$(as_user so_git git --git-dir=$MIRROR rev-parse --verify -q refs/heads/main 2>/dev/null || true)"
if [ -z "$agent_main_str" ]; then fail "agent clone has no origin/main"
elif [ "$agent_main_str" = "$mirror_main_str" ]; then ok "agent clone origin/main = mirror main (${agent_main_str:0:7})"
elif as_user so_git git --git-dir=$MIRROR merge-base --is-ancestor "$agent_main_str" refs/heads/main 2>/dev/null; then
    ok "agent clone origin/main ${agent_main_str:0:7} is behind the mirror's main ${mirror_main_str:0:7} (the agent fetches with git fetch)"
else fail "agent clone origin/main ${agent_main_str:0:7} is not on the mirror's main ${mirror_main_str:0:7}"; fi
sudo_list_str="$(runuser -u so_agent -- sudo -n -l 2>&1 || true)"
if printf '%s' "$sudo_list_str" | grep -q "/usr/local/lib/so/so-git-helper" && ! printf '%s' "$sudo_list_str" | grep -qE '\(ALL|\(root|NOPASSWD: ALL'; then
    ok "so_agent sudo: only the push helper as so_git"
else fail "so_agent sudo rights: $(printf '%s' "$sudo_list_str" | tr '\n' ' ' | cut -c1-200)"; fi
runuser -u so_agent -- sudo -n -u so_git /bin/true >/dev/null 2>&1 && fail "so_agent can run /bin/true as so_git" || ok "so_agent cannot run other commands as so_git"
runuser -u so_agent -- sudo -n -u root /bin/true >/dev/null 2>&1 && fail "so_agent can run commands as root" || ok "so_agent cannot run commands as root"
for user_str in so_runner so_planner; do
    runuser -u "$user_str" -- sudo -n -u so_git /usr/local/lib/so/so-git-helper fetch-main >/dev/null 2>&1 \
        && fail "$user_str can run the push helper" || ok "$user_str cannot run the push helper"
done
# The helper's own refusals (none of these needs the token)
helper() { runuser -u so_agent -- env -i HOME=/home/so_agent PATH=/usr/local/bin:/usr/bin:/bin /usr/local/bin/so-git "$@"; }
for bad_str in main refs/heads/main agent/../main agent/ "agent/x;rm" ../agent/x; do
    helper push "$bad_str" >/dev/null 2>&1; rc_int=$?
    [ "$rc_int" -eq 1 ] && ok "helper refuses push '$bad_str'" || fail "helper push '$bad_str' exited $rc_int (expected 1, refused)"
done
helper delete agent/x >/dev/null 2>&1; [ $? -eq 3 ] && ok "helper has no delete command" || fail "helper accepted a delete command"
# A branch that touches a protected file is refused; a clean one gets as far as the token
test_branch="agent/so-access-check-$$"
tmp_clone="$(as_user so_agent mktemp -d /home/so_agent/.so_access_clone.XXXXXX)"   # removed by cleanup_probes too
if as_user so_agent git clone --quiet "$MIRROR" "$tmp_clone/c" 2>/dev/null; then
    as_user so_agent sh -c 'cd "$1/c" && git checkout --quiet -b "$2" && echo "x" >> protected_paths.txt \
        && git -c user.name=check -c user.email=check@localhost commit --quiet -am "access check: protected change" \
        && git push --quiet "$3" "$2"' sh "$tmp_clone" "$test_branch" "$INBOX" 2>/dev/null
    out_str="$(helper push "$test_branch" 2>&1)"; rc_int=$?
    if [ "$rc_int" -eq 1 ] && printf '%s' "$out_str" | grep -q "protected_paths.txt"; then ok "helper refuses a branch that changes protected_paths.txt"
    else fail "helper push of a protected change: exit $rc_int, $(printf '%s' "$out_str" | head -1)"; fi
    clean_branch="$test_branch-clean"
    as_user so_agent sh -c 'cd "$1/c" && git checkout --quiet -B "$2" origin/main && mkdir -p experiments/_so_access_check \
        && echo x > experiments/_so_access_check/x.txt && git add experiments/_so_access_check \
        && git -c user.name=check -c user.email=check@localhost commit --quiet -m "access check: clean change" \
        && git push --quiet "$3" "$2"' sh "$tmp_clone" "$clean_branch" "$INBOX" 2>/dev/null
    if [ -f /etc/so/git/agent_token ]; then
        ok "token installed: the clean push is not tried here (it would reach GitHub); test it by hand (runbook)"
    else
        out_str="$(helper push "$clean_branch" 2>&1)"; rc_int=$?
        if [ "$rc_int" -eq 2 ] && printf '%s' "$out_str" | grep -q "no token"; then ok "helper takes a clean branch as far as the token"
        else fail "helper push of a clean branch: exit $rc_int, $(printf '%s' "$out_str" | head -1)"; fi
    fi
    # Remove the test branches from the inbox and the mirror (as so_git; the agent cannot delete)
    for b_str in "$test_branch" "$clean_branch"; do
        as_user so_git git -C "$INBOX" update-ref -d "refs/heads/$b_str" 2>/dev/null
        as_user so_git git -C "$MIRROR" update-ref -d "refs/so-inbox/$b_str" 2>/dev/null
    done
else
    fail "so_agent could not clone the mirror"
fi
[ -n "$tmp_clone" ] && case "$tmp_clone" in /home/so_agent/.so_access_clone.*) rm -rf -- "$tmp_clone" ;; esac
grep -q "refused" /var/log/so/git-helper.log && ok "helper log records the refusals" || fail "no refusal in /var/log/so/git-helper.log"
expect denied so_agent write:/var/log/so "helper log folder"

section "Network egress per account"
tcp allowed so_runner 127.0.0.1 25 "mail relay"
tcp refused so_runner 1.1.1.1 443 "internet"
tcp refused so_runner 10.0.2.2 445 "VirtualBox host"
tcp refused so_runner 100.100.100.100 80 "tailnet"
tcp refused so_runner 192.168.10.1 80 "LAN"
tcp refused so_runner 127.0.0.1 3129 "planner proxy"
tcp refused so_runner 127.0.0.1 22 "loopback ssh"
tcp refused so_agent 127.0.0.1 25 "mail relay"
tcp refused so_agent 127.0.0.1 3129 "planner proxy"
tcp refused so_agent 127.0.0.1 3130 "git proxy"
tcp refused so_agent 1.1.1.1 443 "internet"
tcp refused so_agent 10.0.2.2 445 "VirtualBox host"
tcp refused so_agent 100.100.100.100 80 "tailnet"
tcp allowed so_agent 127.0.0.1 22 "own loopback (Cursor's forward)"
https refused so_agent https://github.com/ - "github.com direct"
tcp refused so_planner 127.0.0.1 25 "mail relay"
tcp refused so_planner 127.0.0.1 3130 "git proxy"
tcp refused so_planner 1.1.1.1 443 "internet"
https allowed so_planner https://api.anthropic.com/ http://127.0.0.1:3129 "api.anthropic.com through its proxy"
https allowed so_planner https://platform.claude.com/ http://127.0.0.1:3129 "platform.claude.com through its proxy"
https refused so_planner https://example.com/ http://127.0.0.1:3129 "example.com through its proxy"
https refused so_planner https://github.com/ http://127.0.0.1:3129 "github.com through its proxy"
https refused so_planner https://api.anthropic.com/ - "api.anthropic.com direct"
https allowed so_git https://github.com/ http://127.0.0.1:3130 "github.com through its proxy"
https allowed so_git https://api.github.com/ http://127.0.0.1:3130 "api.github.com through its proxy"
https refused so_git https://raw.githubusercontent.com/ http://127.0.0.1:3130 "raw.githubusercontent.com through its proxy"
https refused so_git https://pypi.org/ http://127.0.0.1:3130 "pypi.org through its proxy"
https refused so_git https://github.com/ - "github.com direct"
tcp refused so_git 127.0.0.1 3129 "planner proxy"
tcp refused so_host 1.1.1.1 443 "internet"
tcp refused so_host 127.0.0.1 25 "mail relay"
tcp refused so_host 127.0.0.1 22 "loopback ssh"
tcp refused so_host 100.100.100.100 80 "tailnet"
for user_str in so_runner so_agent so_planner so_git so_host; do
    if as_user "$user_str" timeout 8 getent ahosts example.com >/dev/null 2>&1; then fail "$user_str resolves names (getent)"
    else ok "$user_str has no name lookups (getent)"; fi
    if as_user "$user_str" timeout 8 "$VENV/bin/python" -c 'import socket; socket.getaddrinfo("example.com", 443)' >/dev/null 2>&1; then
        fail "$user_str resolves names (Python)"; else ok "$user_str has no name lookups (Python)"; fi
done
timeout 8 getent ahosts example.com >/dev/null 2>&1 && ok "root still resolves names" || fail "root cannot resolve names"
if [ -d /run/tailscale ]; then
    for user_str in so_runner so_agent so_planner so_git so_host; do
        as_user "$user_str" timeout 8 tailscale status >/dev/null 2>&1 && fail "$user_str can use tailscaled" || ok "$user_str cannot use tailscaled"
    done
fi
nft list table inet so_egress >/dev/null 2>&1 && ok "nft table inet so_egress loaded" || fail "nft table inet so_egress missing"
if [ "$CI_MODE" -eq 0 ]; then
    nft list table inet so_filter >/dev/null 2>&1 && ok "nft table inet so_filter (input) loaded" || fail "nft table inet so_filter missing"
    # A captured string and bash's own match, no pipe (2026-11-23, step-4 bug 2: grep -q ending early under pipefail gave
    # exit 141 when the match was the first line, a false FAIL)
    tables_str="$(nft list tables 2>/dev/null)"
    tables_re='table ip6? filter'
    [[ "$tables_str" =~ $tables_re ]] && ok "Tailscale's tables still loaded" || fail "Tailscale's tables are missing (was nftables restarted?)"
    grep -q '^include "/etc/nftables.d/so_egress.nft"' /etc/nftables.conf && ok "so_egress included from /etc/nftables.conf" || fail "/etc/nftables.conf lacks the so_egress include"
fi

section "Mail relay"
[ "$(postconf -h inet_interfaces)" = "loopback-only" ] && ok "postfix listens on loopback only" || fail "postfix inet_interfaces is $(postconf -h inet_interfaces)"
[ "$(postconf -h authorized_submit_users)" = "root" ] && ok "only root may use the sendmail command" || fail "authorized_submit_users is $(postconf -h authorized_submit_users)"
echo "Subject: check" | as_user so_runner /usr/sbin/sendmail -t "$MAIL_TO" >/dev/null 2>&1 && fail "so_runner can use the sendmail command" || ok "so_runner cannot use the sendmail command"
# The runner's own mail function (scripts/run_queue.py send_email_dict) against the relay, as so_runner
mail_check() {  # <recipient> <expect sent|refused>
    local to_str="$1" want_str="$2" out_str
    out_str="$(as_user so_runner env SO_SMTP_HOST=127.0.0.1 SO_SMTP_PORT=25 SO_EMAIL_TO="$to_str" SO_DATA_PATH=$DATA \
        "$VENV/bin/python" -c '
import sys, tempfile
sys.path[:0] = [sys.argv[1], sys.argv[1] + "/scripts"]
import run_queue
outbox = tempfile.mkdtemp()
result = run_queue.send_email_dict({"outbox": outbox}, "so_access_check", "so-vm access check", sys.argv[2])
print("sent" if result["sent_bool"] else "refused", result["detail"])' "$RUNNER_WS" "$3" 2>&1 | tail -1)"
    if [ "${out_str%% *}" = "$want_str" ]; then ok "runner mail to $to_str: $out_str"
    else fail "runner mail to $to_str: expected $want_str, got: $out_str"; fi
}
if [ "$CI_MODE" -eq 1 ]; then
    mail_check "$MAIL_TO" sent "CI access check"
    # CI has no relay: drop the queued check mail
    postsuper -d ALL >/dev/null 2>&1 || true
elif [ "$SEND_MAIL" -eq 1 ]; then
    mail_check "$MAIL_TO" sent "so-vm: test email from vm/check_vm_access.sh through the local relay. No action needed."
else
    ok "runner mail to $MAIL_TO: not sent (add --send-test-mail to send one real email)"
fi
mail_check "someone.else@example.com" refused "must be refused"

section "sshd"
sshd_t() { sshd -T -C "user=$1,host=check,addr=100.98.9.22" 2>/dev/null | grep -i "^$2 " | cut -d' ' -f2- | paste -sd' ' -; }
check_sshd() {  # user key expected
    local got_str; got_str="$(sshd_t "$1" "$2")"
    [ "$got_str" = "$3" ] && ok "sshd $1 $2 $got_str" || fail "sshd $1 $2: expected '$3', got '$got_str'"
}
check_sshd nico allowtcpforwarding no
check_sshd nico allowagentforwarding no
check_sshd so_agent allowtcpforwarding local
check_sshd so_agent permitopen "127.0.0.1:* localhost:* [::1]:*"
check_sshd so_agent permitlisten none
check_sshd so_agent allowagentforwarding no
check_sshd so_agent allowstreamlocalforwarding no
check_sshd so_agent x11forwarding no
check_sshd so_agent authenticationmethods publickey
check_sshd so_runner allowtcpforwarding no
check_sshd nico passwordauthentication no
check_sshd nico kbdinteractiveauthentication no
check_sshd nico permitrootlogin no
check_sshd nico allowusers "nico so_agent so_host"
key_count_int="$(ssh-keygen -lf /home/so_agent/.ssh/authorized_keys 2>/dev/null | wc -l)"
[ "$key_count_int" -eq 1 ] && ok "so_agent has exactly one authorized key" || fail "so_agent has $key_count_int authorized keys"
if [ -n "$AGENT_KEY_FILE" ]; then
    want_fpr="$(ssh-keygen -lf "$AGENT_KEY_FILE" | awk '{print $2}')"
    [ -n "$EXPECT_FPR" ] && [ "$want_fpr" != "$EXPECT_FPR" ] && fail "the key file's fingerprint $want_fpr is not the expected $EXPECT_FPR"
    got_fpr="$(ssh-keygen -lf /home/so_agent/.ssh/authorized_keys | awk '{print $2}')"
    [ "$got_fpr" = "$want_fpr" ] && ok "so_agent key $got_fpr" || fail "so_agent key $got_fpr, expected $want_fpr"
fi
for user_str in so_runner so_agent so_planner so_git so_host; do
    [ "$(getent shadow "$user_str" | cut -d: -f2 | cut -c1)" = "!" ] || [ "$(getent shadow "$user_str" | cut -d: -f2)" = "*" ] \
        && ok "$user_str has no usable password" || fail "$user_str has a password"
done

section "Host status feed (so_host, 2026-11-23)"
[ "$(getent passwd so_host | cut -d: -f7)" = "/bin/sh" ] && ok "so_host shell /bin/sh (sshd runs the forced command with it)" || fail "so_host shell is $(getent passwd so_host | cut -d: -f7)"
[ "$(id -Gn so_host)" = "so_host" ] && ok "so_host is in no other group" || fail "so_host groups: $(id -Gn so_host)"
[ "$(stat -c '%U:%G %a' /var/lib/so_host 2>/dev/null)" = "root:root 755" ] && ok "so_host's home is root-owned" || fail "so_host's home: $(stat -c '%U:%G %a' /var/lib/so_host 2>&1)"
[ "$(stat -c '%U:%G %a' $RECEIVER 2>/dev/null)" = "root:root 755" ] && ok "receiver root-owned, 0755" || fail "receiver: $(stat -c '%U:%G %a' $RECEIVER 2>&1)"
cmp -s $RECEIVER "$REPO_DIR/vm/host_status_receive.py" && ok "receiver equals vm/host_status_receive.py" || fail "receiver differs from the repository"
[ "$(stat -c '%U:%G %a' $STATUS_KEYS 2>/dev/null)" = "root:root 644" ] && ok "so_host key file root-owned, 0644" || fail "so_host key file: $(stat -c '%U:%G %a' $STATUS_KEYS 2>&1)"
[ "$(stat -c '%U:%G %a' /etc/so/ssh 2>/dev/null)" = "root:root 755" ] && ok "/etc/so/ssh root-owned, 0755" || fail "/etc/so/ssh: $(stat -c '%U:%G %a' /etc/so/ssh 2>&1)"
if [ -s $STATUS_KEYS ]; then
    status_line_str="$(grep -v '^\s*$' $STATUS_KEYS)"
    [ "$(ssh-keygen -lf $STATUS_KEYS 2>/dev/null | wc -l)" -eq 1 ] && ok "so_host has exactly one key" || fail "so_host key file holds $(ssh-keygen -lf $STATUS_KEYS 2>/dev/null | wc -l) keys"
    case "$status_line_str" in
        "from=\"$STATUS_FROM\",restrict ssh-ed25519 "*) ok "so_host key limited: from=\"$STATUS_FROM\",restrict" ;;
        *) fail "so_host key line does not start with from=\"$STATUS_FROM\",restrict ssh-ed25519" ;;
    esac
    if [ -n "$STATUS_KEY_FILE" ]; then
        want_fpr="$(ssh-keygen -lf "$STATUS_KEY_FILE" | awk '{print $2}')"
        got_fpr="$(ssh-keygen -lf $STATUS_KEYS | awk '{print $2}')"
        [ "$got_fpr" = "$want_fpr" ] && ok "so_host key $got_fpr" || fail "so_host key $got_fpr, expected $want_fpr"
    fi
else
    ok "so_host has no key yet (the host cannot send; the update guard on Linux then fails closed)"
fi
sshd_host() { sshd -T -C "user=so_host,host=check,addr=$STATUS_FROM" 2>/dev/null | grep -i "^$1 " | cut -d' ' -f2- | paste -sd' ' -; }
for pair_str in "forcecommand $RECEIVER" "disableforwarding yes" "permittty no" "permituserrc no" \
                "authorizedkeysfile $STATUS_KEYS" "maxsessions 1" "authenticationmethods publickey"; do
    got_str="$(sshd_host "${pair_str%% *}")"
    [ "$got_str" = "${pair_str#* }" ] && ok "sshd so_host ${pair_str%% *} $got_str" || fail "sshd so_host ${pair_str%% *}: expected '${pair_str#* }', got '$got_str'"
done
[ -z "$(sshd -T -C "user=so_agent,host=check,addr=100.98.9.22" 2>/dev/null | grep -i '^forcecommand ')" ] \
    && ok "the so_host Match block ends with its file (so_agent has no forced command)" || fail "so_agent has a forced command"
# The receiver itself, as so_host, into a scratch folder (never the real file: a test must not write facts)
tmp_status="$(mktemp -d /var/tmp/.so_status_check.XXXXXX)"
chown so_host:so_host "$tmp_status"
receive() { as_user so_host "$RECEIVER" --target-dir "$tmp_status"; }
k1='SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired'
k2='SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing\\RebootPending'
# A restart pending in the sample: even if it were read as real facts, it says "not safe"
good_str='{"schema":"so-host-status/1","host":"check","written_utc":"2026-01-01T00:00:00Z","restart_pending":{"'"$k1"'":true,"'"$k2"'":false},"pause":{"PauseUpdatesExpiryTime":"2026-01-30T13:59:06Z","PauseFeatureUpdatesEndTime":"2026-01-30T13:59:06Z","PauseQualityUpdatesEndTime":null},"errors":[]}'
out_str="$(printf '%s' "$good_str" | receive 2>&1)"; rc_int=$?
if [ "$rc_int" -eq 0 ] && [ "${out_str%% *}" = "ok" ] && [ -f "$tmp_status/host_status.json" ] \
   && python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if d.get("received_utc") and d["restart_pending"] else 1)' "$tmp_status/host_status.json"; then
    ok "receiver takes a valid object and adds received_utc"
else fail "receiver on a valid object: exit $rc_int, $out_str"; fi
[ "$(stat -c '%U %a' "$tmp_status/host_status.json" 2>/dev/null)" = "so_host 640" ] && ok "receiver writes mode 0640" || fail "receiver wrote $(stat -c '%U %a' "$tmp_status/host_status.json" 2>&1)"
before_str="$(sha256sum "$tmp_status/host_status.json" 2>/dev/null)"
bad_check() {  # <label> <input>
    local out_str rc_int
    out_str="$(printf '%s' "$2" | receive 2>&1)"; rc_int=$?
    if [ "$rc_int" -eq 1 ] && [ "${out_str%%:*}" = "refused" ]; then ok "receiver refuses $1"
    else fail "receiver on $1: exit $rc_int, $out_str"; fi
}
bad_check "an extra key" "${good_str%\}},\"x\":1}"
bad_check "a missing key" '{"schema":"so-host-status/1"}'
bad_check "a wrong schema" "${good_str/so-host-status\/1/so-host-status\/2}"
bad_check "a pause time without a zone" "${good_str/2026-01-30T13:59:06Z/2026-01-30T13:59:06}"
bad_check "a restart flag that is not true/false" "${good_str/\":true,/\":1,}"
bad_check "non-ASCII text" "${good_str/check/ch$'\xc3\xa9'ck}"
bad_check "more than 4096 bytes" "$(printf '%s' "$good_str"; head -c 5000 /dev/zero | tr '\0' ' ')x"
bad_check "not JSON" "hello"
out_str="$(printf '%s' "$good_str" | as_user so_host "$RECEIVER" --other 2>&1)"
[ "${out_str%%:*}" = "refused" ] && ok "receiver refuses other arguments" || fail "receiver with --other: $out_str"
[ "$(sha256sum "$tmp_status/host_status.json" 2>/dev/null)" = "$before_str" ] && ok "a refused object leaves the file unchanged" || fail "a refused object changed the file"
[ -z "$(find "$tmp_status" -name '.host_status.json.*' 2>/dev/null)" ] && ok "no temporary file left" || fail "temporary files left in $tmp_status"
rm -rf -- "$tmp_status"; tmp_status=""

section "Python and packages"
expect allowed so_runner exec:$VENV/bin/python "project python"
expect allowed so_agent exec:$VENV/bin/python "project python"
expect denied  so_runner write:$VENV/lib "venv"
expect denied  so_agent write:$VENV/lib "venv"
version_str="$("$VENV/bin/python" -c 'import platform; print(platform.python_version())' 2>/dev/null)"
[ "$version_str" = "$PYTHON_VERSION" ] && ok "venv Python $version_str" || fail "venv Python is '$version_str', expected $PYTHON_VERSION"
"$VENV/bin/python" -m pip check >/dev/null 2>&1 && ok "pip check clean" || fail "pip check: $("$VENV/bin/python" -m pip check 2>&1 | head -2 | tr '\n' ' ')"
lock_diff_str="$("$VENV/bin/python" -I - "$REPO_DIR/requirements/venv_main_lock_linux.txt" <<'PY'
import sys, re
from importlib import metadata
def norm(n): return re.sub(r"[-_.]+", "-", n).lower()
lock = {}
for line in open(sys.argv[1], encoding="utf-8-sig"):
    line = line.split("#", 1)[0].strip()
    if "==" in line:
        name, version = line.split("==", 1)
        lock[norm(name)] = version.strip()
installed = {norm(d.metadata["Name"]): d.version for d in metadata.distributions()}
out = [f"{n}: lock {v}, installed {installed.get(n, 'missing')}" for n, v in sorted(lock.items()) if installed.get(n) != v]
extra = sorted(set(installed) - set(lock) - {"pip"})
if extra:
    out.append("not in the lock: " + ", ".join(extra))
print("; ".join(out))
PY
)"
[ -z "$lock_diff_str" ] && ok "installed packages equal requirements/venv_main_lock_linux.txt" || fail "packages: $lock_diff_str"

section "Claude Code (planner)"
claude_version_str="$(claude --version 2>/dev/null | awk '{print $1}')"
[ "$claude_version_str" = "$CLAUDE_CODE_VERSION" ] && ok "claude $claude_version_str" || fail "claude is '$claude_version_str', expected $CLAUDE_CODE_VERSION"
apt-mark showhold | grep -qx claude-code && ok "claude-code held" || fail "claude-code is not held"
settings_str=/etc/claude-code/managed-settings.json
[ "$(stat -c '%U %a' $settings_str 2>/dev/null)" = "root 644" ] && ok "managed settings root-owned, 0644" || fail "managed settings: $(stat -c '%U %a' $settings_str 2>&1)"
expect allowed so_planner read:$settings_str "managed settings"
expect denied so_planner write:/etc/claude-code "managed settings folder"
cmp -s $settings_str "$REPO_DIR/vm/claude/managed-settings.json" && ok "managed settings equal vm/claude/managed-settings.json" || fail "managed settings differ from the repository"
for file_str in /home/so_planner/.claude/settings.json $PLANNER_DIR/.claude/settings.json; do
    [ "$(stat -c %U "$file_str" 2>/dev/null)" = "root" ] && ok "$file_str root-owned" || fail "$file_str is not root-owned"
    as_user so_planner sh -c 'mv "$1" "$1.x"' sh "$file_str" 2>/dev/null && { mv "$file_str.x" "$file_str"; fail "so_planner can replace $file_str"; } \
        || ok "so_planner cannot replace $file_str"
done

section "Services"
[ "$(systemctl is-enabled so-queue-runner.service 2>/dev/null)" = "disabled" ] && ok "so-queue-runner.service installed, not enabled" || fail "so-queue-runner.service is $(systemctl is-enabled so-queue-runner.service 2>&1)"
systemctl is-active --quiet so-queue-runner.service && fail "so-queue-runner.service is running" || ok "so-queue-runner.service not running"
for unit_str in so-proxy@planner so-proxy@git postfix; do
    systemctl is-active --quiet "$unit_str" && ok "$unit_str running" || fail "$unit_str not running"
done
[ -f /etc/needrestart/conf.d/so.conf ] && ok "needrestart rule for so-queue-runner present" || fail "needrestart rule missing"
grep -q "^SO_SMTP_USER\|^SO_SMTP_PASSWORD" /etc/so/runner.env && fail "/etc/so/runner.env holds SMTP login values" || ok "/etc/so/runner.env has no SMTP login"
if [ "$CI_MODE" -eq 0 ]; then
    dpkg-query -W -f='${Status}' snapd 2>/dev/null | grep -q "install ok installed" && fail "snapd is installed" || ok "snapd not installed"
    [ "$(hostname)" = "so-vm" ] && ok "host so-vm" || fail "host is $(hostname)"
fi

# ---------------------------------------------------------------------------------------------------------------------
cleanup_probes
printf '\n%d OK, %d FAIL\n' "$ok_count" "$fail_count"
[ "$fail_count" -eq 0 ]
