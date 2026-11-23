#!/usr/bin/env bash
# vm/setup_vm.sh (2026-11-19): set up so-vm for Stock Overflow (step 3 of claude/DESIGN_2026-11-18_linux_vm.md).
#
#   sudo bash vm/setup_vm.sh --agent-key <nicosls_sovm_agent.pub> --mail-to <address> --relay-user <mailbot address>
#        [--status-key <so_vm_status_ed25519.pub>] [--status-from <address>]
#   sudo bash vm/setup_vm.sh --ci --agent-key <throwaway.pub> --mail-to <address>      (the linux-setup CI job)
#
# --status-key installs the key of nicodesktop's task "SO VM status" for so_host (2026-11-23), limited to
# --status-from (default 100.123.162.2, nicodesktop's tailnet address). Without --status-key an installed key is kept.
#
# Run from a clone of the repository (any folder; the script finds the repository from its own path). It can be run
# again: every step checks what is there and only adds or corrects. It ends with vm/check_vm_access.sh, which tries
# every access as every account and exits 1 on any FAIL. Nothing here touches the Windows runner, the data copy
# (step 4) or the judge: refs/deployed is not set and the runner service is installed but not enabled.
#
# What it does, in order:
#    1. Checks: root, Ubuntu 26.04, host so-vm (not in CI), the runner service not running, the arguments.
#    2. Packages: acl, nftables, tinyproxy, postfix, ssl-cert, git, curl, gnupg (apt).
#    3. snapd and hwctl removed and pinned away (not in CI), after checking that nothing else needs them.
#    4. Accounts: so_runner, so_agent, so_planner (login shells, no password), so_git (system, no shell); groups
#       so_data (nico, so_runner), so_grade_readers (so_planner), so_status_readers (so_agent), so_git_readers
#       (nico, so_runner, so_agent), so_inbox (so_agent, so_git). so_agent is in no grades group (decided 2026-11-19). umask 027 for all of them.
#       so_host (system, 2026-11-23): receives the host's Windows Update facts; in no project group.
#    5. Folders, owners, modes and ACLs (design section 3, with the decisions of 2026-11-19); the data folders from
#       vm/data_acl.conf, applied to everything below them too (vm/data_acl.sh, 2026-11-21).
#    6. sshd: AllowUsers nico so_agent so_host, the so_agent and so_host Match blocks, so_agent's key, the status
#       receiver /usr/local/lib/so/so-host-status and so_host's key file (root-owned, outside its home).
#    7. Python: uv (pinned, hash-checked) installs CPython 3.12.0 into /opt/so/python; the venv /opt/so/venvs/main gets
#       requirements/venv_main_hashes_linux.txt with --require-hashes --no-deps.
#    8. The allow-list proxies (so-proxy@planner, so-proxy@git) and the local mail relay (Postfix).
#    9. No DNS and no tailscaled socket for the service accounts; then the nftables egress table.
#   10. git: the mirror, the agent's inbox, the push helper and its sudo rule, the runner clone (core.autocrlf true)
#       and the agent clone.
#   11. Claude Code for so_planner (signed apt repository, pinned and held) and its managed settings.
#   12. needrestart rule, the runner service (installed, not enabled) and /etc/so/runner.env.
#   13. vm/check_vm_access.sh.
set -euo pipefail
umask 022

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_DIR="$REPO_DIR/vm"
# shellcheck source=vm/versions.env
. "$VM_DIR/versions.env"

CI_MODE=0
AGENT_KEY_FILE=""
MAIL_TO=""
RELAY_USER=""
SKIP_PYTHON=0
SKIP_CHECK=0
STATUS_KEY_FILE=""
STATUS_FROM="100.123.162.2"

usage() {
    sed -n '3,9p' "$0"
    exit 3
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ci) CI_MODE=1 ;;
        --agent-key) AGENT_KEY_FILE="${2:-}"; shift ;;
        --mail-to) MAIL_TO="${2:-}"; shift ;;
        --relay-user) RELAY_USER="${2:-}"; shift ;;
        --status-key) STATUS_KEY_FILE="${2:-}"; shift ;;
        --status-from) STATUS_FROM="${2:-}"; shift ;;
        --skip-python) SKIP_PYTHON=1 ;;
        --skip-check) SKIP_CHECK=1 ;;
        -h|--help) usage ;;
        *) echo "unknown argument: $1" >&2; usage ;;
    esac
    shift
done

step() { printf '\n=== %s\n' "$*"; }
info() { printf '    %s\n' "$*"; }
die() { printf 'STOP: %s\n' "$*" >&2; exit 1; }

DATA=/srv/so/data
ZONE4=$DATA/store04_experiments
MIRROR=/srv/so/git/stock_overflow_workspace.git
INBOX=/srv/so/git/agent_inbox.git
RUNNER_WS=/srv/so/runner_workspace
AGENT_WS=/home/so_agent/agent_workspace
PLANNER_DIR=/home/so_planner/planner
VENV=/opt/so/venvs/main

# -------------------------------------------------------------------------------------------------------------------
step "1. Checks"
[ "$(id -u)" -eq 0 ] || die "run with sudo"
. /etc/os-release
[ "${ID:-}" = "ubuntu" ] && [ "${VERSION_ID:-}" = "26.04" ] || die "Ubuntu 26.04 expected, found ${PRETTY_NAME:-unknown}"
if [ "$CI_MODE" -eq 0 ]; then
    [ "$(hostname)" = "so-vm" ] || die "this is $(hostname), not so-vm (gotcha #50)"
fi
if systemctl is-active --quiet so-queue-runner.service 2>/dev/null; then
    die "so-queue-runner.service is running; stop it (no job running) before setup"
fi
id nico >/dev/null 2>&1 || die "the account nico does not exist"
[ -n "$AGENT_KEY_FILE" ] && [ -r "$AGENT_KEY_FILE" ] || die "--agent-key <public key file> is required"
AGENT_KEY_LINE="$(tr -d '\r' < "$AGENT_KEY_FILE" | grep -v '^\s*$' || true)"
[ "$(printf '%s\n' "$AGENT_KEY_LINE" | wc -l)" -eq 1 ] || die "$AGENT_KEY_FILE must hold exactly one key line"
case "$AGENT_KEY_LINE" in ssh-ed25519\ AAAA*) ;; *) die "$AGENT_KEY_FILE is not an ssh-ed25519 public key" ;; esac
case "$AGENT_KEY_LINE" in *PRIVATE*) die "$AGENT_KEY_FILE looks like a private key" ;; esac
[[ "$STATUS_FROM" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]] || die "--status-from must be one IPv4 address (nicodesktop's tailnet address)"
STATUS_KEY_LINE=""
if [ -n "$STATUS_KEY_FILE" ]; then
    [ -r "$STATUS_KEY_FILE" ] || die "cannot read --status-key $STATUS_KEY_FILE"
    STATUS_KEY_LINE="$(tr -d '\r' < "$STATUS_KEY_FILE" | grep -v '^\s*$' || true)"
    [ "$(printf '%s\n' "$STATUS_KEY_LINE" | wc -l)" -eq 1 ] || die "$STATUS_KEY_FILE must hold exactly one key line"
    case "$STATUS_KEY_LINE" in ssh-ed25519\ AAAA*) ;; *) die "$STATUS_KEY_FILE is not an ssh-ed25519 public key" ;; esac
    case "$STATUS_KEY_LINE" in *PRIVATE*) die "$STATUS_KEY_FILE looks like a private key" ;; esac
    [ "$STATUS_KEY_LINE" != "$AGENT_KEY_LINE" ] || die "the status key must not be the agent's key"
fi
[[ "$MAIL_TO" =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "--mail-to <address> is required"
if [ "$CI_MODE" -eq 0 ] && [ -z "$RELAY_USER" ] && [ ! -s /etc/postfix/sasl_passwd ]; then
    die "--relay-user <mailbot address> is required on the first run (the Gmail account that sends the emails)"
fi
info "repository $REPO_DIR at $(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
info "agent key $(printf '%s\n' "$AGENT_KEY_LINE" | ssh-keygen -lf - | awk '{print $2}')"

# -------------------------------------------------------------------------------------------------------------------
step "2. Packages"
export DEBIAN_FRONTEND=noninteractive
echo "postfix postfix/main_mailer_type select No configuration" | debconf-set-selections
apt-get update -qq
apt-get install -y -qq acl nftables tinyproxy postfix ssl-cert git curl ca-certificates gnupg openssh-server >/dev/null
# The package's own tinyproxy (port 8888) is not used: one instance per allow-list instead (step 8)
systemctl disable --now tinyproxy.service >/dev/null 2>&1 || true
systemctl mask tinyproxy.service >/dev/null 2>&1 || true
info "installed: $(dpkg-query -W -f='${Package} ${Version}, ' tinyproxy postfix nftables acl git | sed 's/, $//')"

# -------------------------------------------------------------------------------------------------------------------
step "3. snapd and hwctl"
if [ "$CI_MODE" -eq 1 ]; then
    info "skipped in CI"
else
    if dpkg-query -W -f='${Status}' snapd 2>/dev/null | grep -q "install ok installed"; then
        # Ask apt what a purge would really remove (rdepends also lists Breaks and Suggests, e.g. apparmor's
        # "Breaks: snapd (<< ...)", which are no dependency). Stop unless it is only snapd, hwctl and the server
        # metapackages.
        purge_list="snapd"
        dpkg-query -W -f='${Status}' hwctl 2>/dev/null | grep -q "install ok installed" && purge_list="snapd hwctl"
        # shellcheck disable=SC2086
        simulated_str="$(apt-get -s purge $purge_list 2>&1)" || die "apt-get -s purge $purge_list failed: $simulated_str"
        removed_list="$(printf '%s\n' "$simulated_str" | awk '$1 == "Purg" || $1 == "Remv" {print $2}' | sort -u)"
        other_list="$(printf '%s\n' "$removed_list" | grep -vxE 'snapd|hwctl|ubuntu-server|ubuntu-server-minimal|' || true)"
        [ -z "$other_list" ] || die "removing snapd would also remove: $(echo $other_list) (send this output to Claude)"
        info "apt would remove: $(echo $removed_list)"
        info "installed snaps:"; snap list 2>/dev/null | sed 's/^/      /' || true
        for snap_str in $(snap list 2>/dev/null | awk 'NR>1 {print $1}' | grep -vxE 'snapd|core[0-9]*|bare' || true); do
            snap remove --purge "$snap_str" || true
        done
        # shellcheck disable=SC2086
        apt-get purge -y -qq $purge_list >/dev/null
        rm -rf /snap /var/snap /var/lib/snapd /var/cache/snapd
    fi
    install -m 644 -o root -g root "$VM_DIR/apt/no-snapd.pref" /etc/apt/preferences.d/no-snapd.pref
    dpkg-query -W -f='${Status}' snapd 2>/dev/null | grep -q "install ok installed" && die "snapd is still installed"
    info "snapd removed and pinned to -1"
fi

# -------------------------------------------------------------------------------------------------------------------
step "4. Accounts and groups"
for group_str in so_data so_grade_readers so_status_readers so_git_readers so_inbox; do
    getent group "$group_str" >/dev/null || groupadd --system "$group_str"
done
for user_str in so_runner so_agent so_planner; do
    if ! id "$user_str" >/dev/null 2>&1; then
        useradd --create-home --shell /bin/bash --user-group "$user_str"
    fi
    passwd -l "$user_str" >/dev/null 2>&1 || true
done
if ! id so_git >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/so_git --create-home --shell /usr/sbin/nologin so_git
fi
# so_host: a shell (sshd runs the forced command with it), no password, a root-owned home it cannot write
if ! id so_host >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/so_host --no-create-home --shell /bin/sh so_host
fi
install -d -m 755 -o root -g root /var/lib/so_host
passwd -l so_host >/dev/null 2>&1 || true
set_members() {  # group, then the only members it may have
    local group_str="$1"; shift
    gpasswd -M "$(IFS=,; echo "$*")" "$group_str" >/dev/null
}
set_members so_data nico so_runner
set_members so_grade_readers so_planner
set_members so_status_readers so_agent
set_members so_git_readers nico so_runner so_agent
set_members so_inbox so_agent so_git
for user_str in so_runner so_agent so_planner; do
    home_str="$(getent passwd "$user_str" | cut -d: -f6)"
    chmod 750 "$home_str"
    profile_str="$home_str/.profile"
    touch "$profile_str"; chown "$user_str:$user_str" "$profile_str"
    sed -i '/# so-vm (vm\/setup_vm.sh)/,/# end so-vm/d' "$profile_str"
    {
        echo "# so-vm (vm/setup_vm.sh)"
        echo "umask 027"
        case "$user_str" in
            so_runner|so_agent) echo "export SO_DATA_PATH=$DATA"; echo "export PATH=$VENV/bin:\$PATH" ;;
        esac
        echo "# end so-vm"
    } >> "$profile_str"
done
info "so_data: $(getent group so_data | cut -d: -f4); so_grade_readers: $(getent group so_grade_readers | cut -d: -f4);" \
     "so_status_readers: $(getent group so_status_readers | cut -d: -f4); so_git_readers: $(getent group so_git_readers | cut -d: -f4)"

# -------------------------------------------------------------------------------------------------------------------
step "5. Folders, owners, modes and ACLs"
# set_acl <path> <owner:group> <mode> <access entries> <default entries>: replaces the path's ACL (not its children)
set_acl() {
    local path_str="$1" owner_str="$2" mode_str="$3" access_str="$4" default_str="$5"
    mkdir -p "$path_str"
    chown "$owner_str" "$path_str"
    setfacl -b "$path_str"
    chmod "$mode_str" "$path_str"
    [ -z "$access_str" ] || setfacl -m "$access_str" "$path_str"
    [ -z "$default_str" ] || setfacl -d -m "$default_str" "$path_str"
}
install -d -m 755 -o root -g root /srv/so /srv/so/git /opt/so /opt/so/venvs /etc/so /var/log/so

# The data folders (data root, zones, judge, queue, visible, control, quarantine, holdout) and everything below them:
# vm/data_acl.conf, applied by vm/data_acl.sh (the same code vm/set_data_permissions.sh runs after a data copy)
# shellcheck source=vm/data_acl.sh
. "$VM_DIR/data_acl.sh"
so_data_acl_apply || die "data folder permissions not set (see above)"
acl_check_str="$(python3 -I "$VM_DIR/check_data_permissions.py")" \
    || { printf '%s\n' "$acl_check_str"; die "data folder permissions differ from vm/data_acl.conf"; }
info "data folders: ${acl_check_str##*$'\n'}"
# The runner's clone: the runner's own; nico reads
set_acl $RUNNER_WS so_runner:so_runner 750 "u:nico:r-x" "u::rwx,g::r-x,u:nico:r-x,o::---"
# The agent: its home and clone are its own; nico passes through and reads the clone
setfacl -m u:nico:--x /home/so_agent
set_acl $AGENT_WS so_agent:so_agent 750 "u:nico:r-x" "u::rwx,g::r-x,u:nico:r-x,o::---"
# The planner: nico writes the brief, the planner writes plans; nobody else
setfacl -m u:nico:--x /home/so_planner
set_acl $PLANNER_DIR so_planner:so_planner 750 "u:nico:r-x" ""
set_acl $PLANNER_DIR/brief nico:so_planner 2750 "" "u::rwx,g::r-x,o::---"
set_acl $PLANNER_DIR/plans so_planner:so_planner 2770 "u:nico:rwx" "u::rwx,g::rwx,u:nico:rwx,o::---"
# nico's own home stays nico's (750 on 26.04; the agents are not in group nico)
chmod 750 /home/nico
info "folders set; $(find /srv/so -maxdepth 3 -type d | wc -l) folders under /srv/so"

# -------------------------------------------------------------------------------------------------------------------
step "6. sshd"
if [ -f /etc/ssh/sshd_config.d/00-so-hardening.conf ] && ! cmp -s /etc/ssh/sshd_config.d/00-so-hardening.conf "$VM_DIR/ssh/00-so-hardening.conf"; then
    # A dated copy (2026-11-23): a later change must not overwrite the copy kept from step 3
    old_copy_str="/etc/ssh/00-so-hardening.conf.before-$(date +%Y%m%d%H%M%S)"
    cp -p /etc/ssh/sshd_config.d/00-so-hardening.conf "$old_copy_str"
    info "changes to 00-so-hardening.conf (old copy in $old_copy_str):"
    diff "$old_copy_str" "$VM_DIR/ssh/00-so-hardening.conf" | sed 's/^/      /' || true
fi
install -m 644 -o root -g root "$VM_DIR/ssh/00-so-hardening.conf" /etc/ssh/sshd_config.d/00-so-hardening.conf
install -m 644 -o root -g root "$VM_DIR/ssh/99-so-agent.conf" /etc/ssh/sshd_config.d/99-so-agent.conf
install -m 644 -o root -g root "$VM_DIR/ssh/98-so-host.conf" /etc/ssh/sshd_config.d/98-so-host.conf
# The status receiver (so_host's forced command) and so_host's key file: root-owned, so so_host can change neither
install -d -m 755 -o root -g root /usr/local/lib/so /etc/so/ssh
install -m 755 -o root -g root "$VM_DIR/host_status_receive.py" /usr/local/lib/so/so-host-status
if [ -n "$STATUS_KEY_LINE" ]; then
    printf 'from="%s",restrict %s\n' "$STATUS_FROM" "$STATUS_KEY_LINE" > /etc/so/ssh/so_host_authorized_keys.new
    chmod 644 /etc/so/ssh/so_host_authorized_keys.new
    [ "$(ssh-keygen -lf /etc/so/ssh/so_host_authorized_keys.new | wc -l)" -eq 1 ] || die "the staged so_host key file does not hold exactly one key"
    mv /etc/so/ssh/so_host_authorized_keys.new /etc/so/ssh/so_host_authorized_keys
elif [ ! -e /etc/so/ssh/so_host_authorized_keys ]; then
    install -m 644 -o root -g root /dev/null /etc/so/ssh/so_host_authorized_keys
fi
chown root:root /etc/so/ssh/so_host_authorized_keys && chmod 644 /etc/so/ssh/so_host_authorized_keys
[ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ] && sed -i 's/^PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf
install -d -m 700 -o so_agent -g so_agent /home/so_agent/.ssh
printf '%s\n' "$AGENT_KEY_LINE" > /home/so_agent/.ssh/authorized_keys.new
chown so_agent:so_agent /home/so_agent/.ssh/authorized_keys.new
chmod 600 /home/so_agent/.ssh/authorized_keys.new
[ "$(ssh-keygen -lf /home/so_agent/.ssh/authorized_keys.new | wc -l)" -eq 1 ] || die "the staged authorized_keys does not hold exactly one key"
mv /home/so_agent/.ssh/authorized_keys.new /home/so_agent/.ssh/authorized_keys
sshd -t || die "sshd -t failed; nothing was reloaded"
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || systemctl restart ssh
info "sshd reloaded; so_agent key $(ssh-keygen -lf /home/so_agent/.ssh/authorized_keys | awk '{print $2}')"
if [ -s /etc/so/ssh/so_host_authorized_keys ]; then
    info "so_host key $(ssh-keygen -lf /etc/so/ssh/so_host_authorized_keys | awk '{print $2}') (from $(grep -o 'from="[^"]*"' /etc/so/ssh/so_host_authorized_keys | cut -d'"' -f2))"
else
    info "so_host has no key yet (run again with --status-key once the host's key exists)"
fi

# -------------------------------------------------------------------------------------------------------------------
step "7. Python $PYTHON_VERSION and the venv"
UV_BIN="/opt/so/uv/$UV_VERSION/uv"
if [ "$SKIP_PYTHON" -eq 1 ]; then
    info "skipped (--skip-python)"
else
    if [ ! -x "$UV_BIN" ]; then
        tmp_dir="$(mktemp -d)"
        curl -fsSL -o "$tmp_dir/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-x86_64-unknown-linux-gnu.tar.gz"
        echo "$UV_SHA256  $tmp_dir/uv.tar.gz" | sha256sum -c --quiet - || die "uv download: hash mismatch"
        tar -xzf "$tmp_dir/uv.tar.gz" -C "$tmp_dir"
        install -d -m 755 "/opt/so/uv/$UV_VERSION"
        install -m 755 -o root -g root "$tmp_dir/uv-x86_64-unknown-linux-gnu/uv" "$UV_BIN"
        rm -rf -- "${tmp_dir:?}"
    fi
    info "$("$UV_BIN" --version)"
    export UV_PYTHON_INSTALL_DIR=/opt/so/python UV_CACHE_DIR=/root/.cache/so-uv UV_NO_CONFIG=1
    "$UV_BIN" python install --quiet "$PYTHON_VERSION"
    base_python="$("$UV_BIN" python find --python-preference only-managed "$PYTHON_VERSION")"
    [ "$("$base_python" -c 'import platform; print(platform.python_version())')" = "$PYTHON_VERSION" ] || die "wrong Python at $base_python"
    chmod -R a+rX,go-w /opt/so/python
    lock_file="$REPO_DIR/requirements/venv_main_lock_linux.txt"
    hash_file="$REPO_DIR/requirements/venv_main_hashes_linux.txt"
    # Both files must list the same name==version pairs
    diff <(grep -v '^#' "$lock_file" | tr -d '\r' | grep '==' | tr 'A-Z_' 'a-z-' | sort) \
         <(grep -v '^#' "$hash_file" | tr -d '\r' | grep '==' | sed 's/ *\\$//' | tr 'A-Z_' 'a-z-' | sort) >/dev/null \
        || die "requirements/venv_main_lock_linux.txt and venv_main_hashes_linux.txt list different versions"
    lock_sum="$(cat "$lock_file" "$hash_file" | tr -d '\r' | sha256sum | cut -c1-16)"
    if [ -f "$VENV/.so_lock_sum" ] && [ "$(cat "$VENV/.so_lock_sum")" = "$lock_sum" ] \
        && [ "$("$VENV/bin/python" -c 'import platform; print(platform.python_version())' 2>/dev/null)" = "$PYTHON_VERSION" ]; then
        info "venv $VENV already matches the lock"
    else
        rm -rf -- "${VENV:?}"
        "$UV_BIN" venv --quiet --seed --python "$base_python" "$VENV"
        tmp_dir="$(mktemp -d)"
        # Split the hash file: build tools first, the two source-only packages (ibapi, skrebate) last
        awk -v out="$tmp_dir" '
            /^#/ {next}
            /^[A-Za-z0-9]/ { name=tolower($1); sub(/==.*/, "", name); gsub(/_/, "-", name)
                             f = (name=="setuptools" || name=="wheel") ? "/1.txt" : (name=="ibapi" || name=="skrebate") ? "/3.txt" : "/2.txt" }
            { print > (out f) }' "$hash_file"
        pip_cmd=("$VENV/bin/python" -m pip install --quiet --no-deps --require-hashes --no-cache-dir --disable-pip-version-check)
        "${pip_cmd[@]}" -r "$tmp_dir/1.txt"
        "${pip_cmd[@]}" --only-binary :all: -r "$tmp_dir/2.txt"
        "${pip_cmd[@]}" --no-build-isolation -r "$tmp_dir/3.txt"
        rm -rf -- "${tmp_dir:?}"
        "$VENV/bin/python" -m pip check || die "pip check found missing or conflicting packages"
        echo "$lock_sum" > "$VENV/.so_lock_sum"
        chmod -R a+rX,go-w "$VENV"
    fi
    info "venv $VENV: Python $("$VENV/bin/python" -c 'import platform; print(platform.python_version())'),"\
         "$("$VENV/bin/python" -m pip list --format=freeze 2>/dev/null | wc -l) distributions, pip $("$VENV/bin/python" -m pip --version | awk '{print $2}')"
fi

# -------------------------------------------------------------------------------------------------------------------
step "8. Allow-list proxies and the mail relay"
install -d -m 755 -o root -g root /etc/so/proxy
for name_str in planner git; do
    install -m 644 -o root -g root "$VM_DIR/proxy/$name_str.conf" "/etc/so/proxy/$name_str.conf"
    install -m 644 -o root -g root "$VM_DIR/proxy/$name_str.allow" "/etc/so/proxy/$name_str.allow"
done
install -m 644 -o root -g root "$VM_DIR/systemd/so-proxy@.service" /etc/systemd/system/so-proxy@.service
# Ubuntu's AppArmor profile for tinyproxy reads only /etc/tinyproxy/tinyproxy.conf: allow our two files, then reload it
if [ -f /etc/apparmor.d/tinyproxy ]; then
    install -d -m 755 /etc/apparmor.d/local
    install -m 644 -o root -g root "$VM_DIR/apparmor/tinyproxy.local" /etc/apparmor.d/local/tinyproxy
    if [ -d /sys/kernel/security/apparmor ] && command -v apparmor_parser >/dev/null; then
        apparmor_parser -r /etc/apparmor.d/tinyproxy || die "AppArmor did not accept the tinyproxy profile with vm/apparmor/tinyproxy.local"
    fi
    info "AppArmor: tinyproxy may read /etc/so/proxy/*.conf and *.allow"
fi
systemctl daemon-reload
# wait_port <port> <unit>: the unit must be listening on 127.0.0.1:<port> within 15 s, or the setup stops with its log
wait_port() {
    local port_str="$1" unit_str="$2"
    for _ in $(seq 1 30); do
        ss -Hltn "sport = :$port_str" 2>/dev/null | grep -q "127.0.0.1:$port_str" && return 0
        sleep 0.5
    done
    # (systemctl status exits non-zero for a failed unit; that must not end the script before the journal is shown)
    { systemctl status "$unit_str" --no-pager -l 2>&1 || true; } | sed 's/^/      /' | head -20 || true
    { journalctl -u "$unit_str" --no-pager -n 30 2>&1 || true; } | sed 's/^/      /' || true
    die "$unit_str is not listening on 127.0.0.1:$port_str"
}
for name_str in planner git; do
    systemctl enable --quiet "so-proxy@$name_str.service"
    systemctl restart "so-proxy@$name_str.service"
done
wait_port 3129 so-proxy@planner.service
wait_port 3130 so-proxy@git.service
# Postfix: our own main.cf; the recipient list and the relay login are written here, never kept in the repository
[ -f /etc/ssl/private/ssl-cert-snakeoil.key ] || make-ssl-cert generate-default-snakeoil
if [ "$CI_MODE" -eq 1 ]; then relay_host=""; sasl_enable=no; tls_level=may
else relay_host="[smtp.gmail.com]:587"; sasl_enable=yes; tls_level=secure; fi
sed -e "s|__RELAYHOST__|$relay_host|" -e "s|__SASL_ENABLE__|$sasl_enable|" -e "s|__SMTP_TLS_LEVEL__|$tls_level|" \
    "$VM_DIR/postfix/main.cf" > /etc/postfix/main.cf.new
chmod 644 /etc/postfix/main.cf.new && mv /etc/postfix/main.cf.new /etc/postfix/main.cf
printf '%s OK\n' "$MAIL_TO" > /etc/postfix/so_recipient_access
postmap /etc/postfix/so_recipient_access
if [ "$CI_MODE" -eq 0 ] && [ -n "$RELAY_USER" ]; then
    if [ ! -s /etc/postfix/sasl_passwd ] || ! grep -q "^\[smtp.gmail.com\]:587 $RELAY_USER:" /etc/postfix/sasl_passwd; then
        read -r -s -p "    Gmail app password of $RELAY_USER (not shown; Enter to finish): " relay_password; echo
        [ -n "$relay_password" ] || die "no password given"
        ( umask 077; printf '[smtp.gmail.com]:587 %s:%s\n' "$RELAY_USER" "$relay_password" > /etc/postfix/sasl_passwd )
        unset relay_password
    fi
fi
[ -f /etc/postfix/sasl_passwd ] || ( umask 077; : > /etc/postfix/sasl_passwd )
chown root:root /etc/postfix/sasl_passwd && chmod 600 /etc/postfix/sasl_passwd
postmap /etc/postfix/sasl_passwd && chmod 600 /etc/postfix/sasl_passwd.db
postfix check
systemctl enable --quiet postfix.service
systemctl restart postfix.service
wait_port 25 postfix.service
info "proxies so-proxy@planner (3129) and so-proxy@git (3130) running; postfix relay ${relay_host:-none (CI)} for $MAIL_TO"

# -------------------------------------------------------------------------------------------------------------------
step "9. No DNS and no tailscaled socket for the service accounts; nftables egress"
install -m 644 -o root -g root "$VM_DIR/dbus/so-no-resolve.conf" /etc/dbus-1/system.d/so-no-resolve.conf
systemctl reload dbus.service 2>/dev/null || systemctl reload dbus-broker.service 2>/dev/null || true
install -d -m 755 /etc/systemd/system/systemd-resolved.service.d
install -m 644 -o root -g root "$VM_DIR/systemd/dropins/systemd-resolved-so.conf" /etc/systemd/system/systemd-resolved.service.d/so.conf
deny_str="u:so_runner:---,u:so_agent:---,u:so_planner:---,u:so_git:---,u:so_host:---"
[ -d /run/systemd/resolve ] && setfacl -m "$deny_str" /run/systemd/resolve
if systemctl list-unit-files tailscaled.service >/dev/null 2>&1 && [ -d /run/tailscale ]; then
    install -d -m 755 /etc/systemd/system/tailscaled.service.d
    install -m 644 -o root -g root "$VM_DIR/systemd/dropins/tailscaled-so.conf" /etc/systemd/system/tailscaled.service.d/so.conf
    setfacl -m "$deny_str" /run/tailscale
    info "tailscaled socket closed to the service accounts"
else
    info "no tailscaled here (CI)"
fi
systemctl daemon-reload
install -d -m 755 -o root -g root /etc/nftables.d
install -m 644 -o root -g root "$VM_DIR/nftables/so_egress.nft" /etc/nftables.d/so_egress.nft
nft -c -f /etc/nftables.d/so_egress.nft || die "nft rejected so_egress.nft"
if [ "$CI_MODE" -eq 1 ]; then
    nft -f /etc/nftables.d/so_egress.nft
else
    grep -q '^include "/etc/nftables.d/so_egress.nft"' /etc/nftables.conf \
        || printf '\n# Stock Overflow: outbound rules per account (vm/nftables/so_egress.nft)\ninclude "/etc/nftables.d/so_egress.nft"\n' >> /etc/nftables.conf
    nft -c -f /etc/nftables.conf || die "nft rejected /etc/nftables.conf"
    # Reload, never restart (gotcha #96)
    systemctl reload nftables.service
fi
nft list table inet so_egress >/dev/null || die "table inet so_egress is not loaded"
info "tables loaded: $(nft list tables | awk '{print $2" "$3}' | paste -sd, -)"

# -------------------------------------------------------------------------------------------------------------------
step "10. git: mirror, inbox, push helper, clones"
cat > /etc/gitconfig.so.new <<'E'
# /etc/gitconfig (vm/setup_vm.sh): the shared repositories under /srv/so/git belong to so_git; the accounts that read
# or push to them trust them. Nothing else here: core.autocrlf is set only in the clones that hash design folders.
[safe]
	directory = /srv/so/git/stock_overflow_workspace.git
	directory = /srv/so/git/agent_inbox.git
E
mv /etc/gitconfig.so.new /etc/gitconfig && chmod 644 /etc/gitconfig
as_user() { local user_str="$1"; shift; runuser -u "$user_str" -- env -i HOME="$(getent passwd "$user_str" | cut -d: -f6)" PATH=/usr/bin:/bin LANG=C.UTF-8 "$@"; }
# The mirror: so_git's own; nico, the runner and the agent read it
if [ ! -d "$MIRROR/objects" ]; then
    install -d -m 2750 -o so_git -g so_git_readers "$MIRROR"
    as_user so_git git init --quiet --bare --initial-branch=main "$MIRROR"
fi
as_user so_git git -C "$MIRROR" config core.sharedRepository 0640
as_user so_git git -C "$MIRROR" config transfer.fsckObjects true
as_user so_git git -C "$MIRROR" config gc.auto 0
chgrp -R so_git_readers "$MIRROR"; chmod -R g+rX,g-w,o-rwx "$MIRROR"; find "$MIRROR" -type d -exec chmod g+s {} +
# The inbox: so_agent's git push lands here; only refs/ and objects/ are writable by it
if [ ! -d "$INBOX/objects" ]; then
    install -d -m 2750 -o so_git -g so_inbox "$INBOX"
    as_user so_git git init --quiet --bare --initial-branch=main "$INBOX"
fi
as_user so_git git -C "$INBOX" config core.sharedRepository 0660
as_user so_git git -C "$INBOX" config receive.fsckObjects true
as_user so_git git -C "$INBOX" config receive.denyDeletes true
as_user so_git git -C "$INBOX" config receive.autogc false
as_user so_git git -C "$INBOX" config gc.auto 0
chown -R so_git:so_inbox "$INBOX"; chmod -R o-rwx "$INBOX"
find "$INBOX" -maxdepth 1 -mindepth 1 ! -name objects ! -name refs -exec chmod -R g-w {} +
chmod -R g+rwX "$INBOX/objects" "$INBOX/refs"; find "$INBOX/objects" "$INBOX/refs" -type d -exec chmod g+s {} +
# The helper, its wrapper, its sudo rule, its log and the token folder
install -d -m 755 -o root -g root /usr/local/lib/so
install -m 755 -o root -g root "$VM_DIR/so_git_helper.py" /usr/local/lib/so/so-git-helper
printf '#!/bin/sh\n# so-git (vm/setup_vm.sh): run the push helper as so_git (see /usr/local/lib/so/so-git-helper)\nexec sudo -n -u so_git /usr/local/lib/so/so-git-helper "$@"\n' > /usr/local/bin/so-git
chmod 755 /usr/local/bin/so-git
install -m 440 -o root -g root "$VM_DIR/sudoers/so-git-helper" /etc/sudoers.d/so-git-helper.new
visudo -c -q -f /etc/sudoers.d/so-git-helper.new || die "the sudo rule did not parse"
mv /etc/sudoers.d/so-git-helper.new /etc/sudoers.d/so-git-helper
install -d -m 750 -o root -g so_git /etc/so/git
[ -f /var/log/so/git-helper.log ] || install -m 640 -o so_git -g so_git /dev/null /var/log/so/git-helper.log
# Fill the mirror from GitHub (public read, through so_git's proxy)
as_user so_git /usr/local/lib/so/so-git-helper fetch-main | sed 's/^/    /'
main_commit="$(git --git-dir="$MIRROR" rev-parse refs/heads/main)"
# The runner's clone: from the mirror, core.autocrlf true before checkout (design section 6)
if [ ! -d "$RUNNER_WS/.git" ]; then
    as_user so_runner git clone --quiet -c core.autocrlf=true "$MIRROR" "$RUNNER_WS"
fi
as_user so_runner git -C "$RUNNER_WS" config core.autocrlf true
as_user so_runner git -C "$RUNNER_WS" remote set-url origin "$MIRROR"
# The agent's clone: fetch from the mirror, push to the inbox; commits under the agent's GitHub identity
if [ ! -d "$AGENT_WS/.git" ]; then
    as_user so_agent git clone --quiet "$MIRROR" "$AGENT_WS"
fi
as_user so_agent git -C "$AGENT_WS" remote set-url origin "$MIRROR"
as_user so_agent git -C "$AGENT_WS" remote set-url --push origin "$INBOX"
as_user so_agent git -C "$AGENT_WS" config user.name "$AGENT_GIT_NAME"
as_user so_agent git -C "$AGENT_WS" config user.email "$AGENT_GIT_EMAIL"
as_user so_agent git -C "$AGENT_WS" config push.default current
# (git refuses to read a clone owned by another account, root included, so ask as the owner)
info "mirror main $main_commit; runner clone at $(as_user so_runner git -C "$RUNNER_WS" rev-parse --short HEAD) (refs/deployed not set);" \
     "agent clone at $(as_user so_agent git -C "$AGENT_WS" rev-parse --short HEAD)"
[ -s /etc/so/git/agent_token ] && info "agent token present" || info "agent token not installed yet (/etc/so/git/agent_token)"

# -------------------------------------------------------------------------------------------------------------------
step "11. Claude Code $CLAUDE_CODE_VERSION for so_planner"
install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://downloads.claude.ai/keys/claude-code.asc -o /etc/apt/keyrings/claude-code.asc.new
# (no early exit in awk: with pipefail, a writer cut off by SIGPIPE would end the script with code 141)
key_fpr="$(gpg --show-keys --with-colons /etc/apt/keyrings/claude-code.asc.new 2>/dev/null | awk -F: '/^fpr:/ && !n++ {print $10}')"
[ "$key_fpr" = "$CLAUDE_CODE_KEY_FINGERPRINT" ] || die "Claude Code signing key fingerprint $key_fpr, expected $CLAUDE_CODE_KEY_FINGERPRINT"
mv /etc/apt/keyrings/claude-code.asc.new /etc/apt/keyrings/claude-code.asc && chmod 644 /etc/apt/keyrings/claude-code.asc
echo "deb [signed-by=/etc/apt/keyrings/claude-code.asc] https://downloads.claude.ai/claude-code/apt/stable stable main" > /etc/apt/sources.list.d/claude-code.list
apt-get update -qq
installed_claude="$(dpkg-query -W -f='${Version}' claude-code 2>/dev/null || true)"
case "$installed_claude" in "$CLAUDE_CODE_VERSION"|"$CLAUDE_CODE_VERSION"-*) ;; *)
    apt_version="$(apt-cache madison claude-code | awk -v v="$CLAUDE_CODE_VERSION" '($3 == v || index($3, v"-") == 1) && !n++ {print $3}')"
    [ -n "$apt_version" ] || die "claude-code $CLAUDE_CODE_VERSION is not in the repository; available: $(apt-cache madison claude-code | awk 'NR <= 5 {print $3}' | paste -sd' ')"
    apt-mark unhold claude-code >/dev/null 2>&1 || true
    apt-get install -y -qq --allow-downgrades "claude-code=$apt_version" >/dev/null ;;
esac
apt-mark hold claude-code >/dev/null
install -d -m 755 -o root -g root /etc/claude-code
install -m 644 -o root -g root "$VM_DIR/claude/managed-settings.json" /etc/claude-code/managed-settings.json
# The planner cannot replace its own settings files: root-owned files in root-owned sticky folders it can write to
for dir_str in /home/so_planner/.claude "$PLANNER_DIR/.claude"; do
    install -d -m 1770 -o root -g so_planner "$dir_str"
    chown root:so_planner "$dir_str" && chmod 1770 "$dir_str"
    for file_str in settings.json settings.local.json; do
        [ -f "$dir_str/$file_str" ] && [ "$(stat -c %U "$dir_str/$file_str")" = "root" ] \
            || { echo '{}' > "$dir_str/$file_str"; chown root:root "$dir_str/$file_str"; chmod 644 "$dir_str/$file_str"; }
    done
done
info "$(claude --version 2>/dev/null | awk 'NR == 1') (held); managed settings in /etc/claude-code/managed-settings.json"

# -------------------------------------------------------------------------------------------------------------------
step "12. needrestart, the runner service (not enabled), runner.env"
install -d -m 755 /etc/needrestart/conf.d
install -m 644 -o root -g root "$VM_DIR/needrestart/so.conf" /etc/needrestart/conf.d/so.conf
cat > /etc/so/runner.env.new <<E
# /etc/so/runner.env (vm/setup_vm.sh): environment of so-queue-runner.service. No secrets: the runner hands mail to
# the local relay without a login. Thread settings come with the equivalence RULE (not set yet).
SO_DATA_PATH=$DATA
SO_QUEUE_PYTHON=$VENV/bin/python
SO_SMTP_HOST=127.0.0.1
SO_SMTP_PORT=25
SO_EMAIL_TO=$MAIL_TO
E
chmod 644 /etc/so/runner.env.new && mv /etc/so/runner.env.new /etc/so/runner.env
install -m 644 -o root -g root "$VM_DIR/systemd/so-queue-runner.service" /etc/systemd/system/so-queue-runner.service
systemctl daemon-reload
systemctl disable --quiet so-queue-runner.service 2>/dev/null || true
info "so-queue-runner.service installed, $(systemctl is-enabled so-queue-runner.service 2>/dev/null || true)"

# -------------------------------------------------------------------------------------------------------------------
step "13. Access check"
if [ "$SKIP_CHECK" -eq 1 ]; then
    info "skipped (--skip-check)"
else
    check_args=(--mail-to "$MAIL_TO" --agent-key "$AGENT_KEY_FILE" --status-from "$STATUS_FROM")
    [ -n "$STATUS_KEY_FILE" ] && check_args+=(--status-key "$STATUS_KEY_FILE")
    [ "$CI_MODE" -eq 1 ] && check_args+=(--ci)
    bash "$VM_DIR/check_vm_access.sh" "${check_args[@]}"
fi
