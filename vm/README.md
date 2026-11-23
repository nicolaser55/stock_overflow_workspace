# vm/: setting up so-vm (the Linux VM on nicodesktop)

Step 3 of `claude/DESIGN_2026-11-18_linux_vm.md` (project docs), with the decisions of 2026-11-19. Every file here is
protected (`protected_paths.txt`: `vm/**`) and kept with LF line endings (`vm/.gitattributes`). Nothing here is part of
the judge hash (`so/runner/judge_identity.py` hashes protected `.py` files under `so/` and `scripts/` only).

| File | Installed as | Purpose |
|---|---|---|
| `setup_vm.sh` | (run from a clone) | Idempotent setup: accounts, folders and ACLs, sshd, Python, proxies, mail relay, egress rules, git, Claude Code, runner service. Ends with the check |
| `check_vm_access.sh` | (run from a clone) | Every account tries every path, port and host; exits 1 on any FAIL |
| `data_acl.conf`, `data_acl.sh` | (sourced) | Owners, modes and ACLs of the data folders and of everything below them; one table for the setup, the permission step and its check |
| `set_data_permissions.sh` | (run from a clone) | After a data copy (step 4, and the store04 copy at the switch): applies `data_acl.conf` to every item, checks it, tries the accounts' access |
| `check_data_permissions.py` | (run from a clone) | Owner, group, mode bits and ACL of every item under the data folders against `data_acl.conf` (metadata only) |
| `data_manifest.py` | (run from a clone, Windows and VM) | SHA-256 manifests of the data trees (`scan`, `make`, `compare`), standard library only |
| `check_hashes.py` | (run from a clone, Windows and VM) | Step 5: judge hash, design folder and helper hashes against the trial log and `registered_versions.csv`, reset marker; same output on both systems |
| `versions.env` | | Pinned versions and hashes: uv, CPython 3.12.0, Claude Code, the agent's git identity |
| `nftables/so_egress.nft` | `/etc/nftables.d/so_egress.nft` | Outbound rules per account (table `inet so_egress`); reload, never restart |
| `ssh/00-so-hardening.conf`, `ssh/99-so-agent.conf` | `/etc/ssh/sshd_config.d/` | Key-only sshd for nico, so_agent and so_host; so_agent may only forward to the VM's loopback (Cursor Remote-SSH) |
| `ssh/98-so-host.conf`, `host_status_receive.py` | `/etc/ssh/sshd_config.d/`, `/usr/local/lib/so/so-host-status` | The host status feed (2026-11-23): so_host's key (`/etc/so/ssh/so_host_authorized_keys`, root-owned, `from=` nicodesktop, `restrict`) may only run the receiver, which checks one JSON object and writes `/srv/so/data/control/host_status/host_status.json` for the update guard |
| `proxy/*.conf`, `proxy/*.allow`, `systemd/so-proxy@.service` | `/etc/so/proxy/`, `/etc/systemd/system/` | tinyproxy allow-lists: planner (Anthropic hosts, 3129), git (GitHub, 3130) |
| `apparmor/tinyproxy.local` | `/etc/apparmor.d/local/tinyproxy` | Lets Ubuntu's AppArmor profile for tinyproxy read the two proxies' config and allow-list files |
| `postfix/main.cf` | `/etc/postfix/main.cf` | Local mail relay: loopback only, one recipient, relays to Gmail with the mailbot login |
| `so_git_helper.py`, `sudoers/so-git-helper` | `/usr/local/lib/so/so-git-helper`, `/etc/sudoers.d/` | The agent's only way to GitHub: `so-git fetch-main`, `so-git push agent/<name>`, `so-git pr agent/<name> "<title>"` |
| `claude/managed-settings.json` | `/etc/claude-code/managed-settings.json` | The planner's Claude Code: no shell, no web, no connectors, proxy, no updates |
| `dbus/so-no-resolve.conf`, `systemd/dropins/*` | `/etc/dbus-1/system.d/`, unit drop-ins | No name lookups and no tailscaled socket for the service accounts |
| `systemd/so-queue-runner.service` | `/etc/systemd/system/` | The judge on the VM: installed, **not enabled** until the switch |
| `needrestart/so.conf`, `apt/no-snapd.pref` | `/etc/needrestart/conf.d/`, `/etc/apt/preferences.d/` | Never auto-restart the runner; snapd and hwctl stay removed |

Accounts: `so_runner` (the judge; design code runs as its child), `so_agent` (Cursor coder, SSH key only),
`so_planner` (Claude Code, `sudo -iu so_planner`), `so_git` (push helper, no login), `so_host` (system; receives the
host's Windows Update facts from nicodesktop's task "SO VM status", `stock_overflow_infra/vm_status/`; no network, no
data access except writing `control/host_status/`). Python packages:
`requirements/venv_main_lock_linux.txt` (what must be installed) and `requirements/venv_main_hashes_linux.txt` (the
same versions with hashes, used for the install).

The install and test steps are in the project runbooks `claude/RUNBOOK_2026-11-19_step3_setup_vm.md` (setup) and
`claude/RUNBOOK_2026-11-21_step4_5_data_copy.md` (data copy, manifests, hash checks).

## Notes

- **Host status feed.** The writer is nicodesktop's scheduled task "SO VM status" (SYSTEM, every 5 minutes; in the
  infra repository, `vm_status/`). The file `control/host_status/host_status.json` exists only on the VM: a manifest
  comparison with Windows must leave `control/host_status` out. The update guard on Linux (judge PR) reads it and fails
  closed when it is missing, malformed or older than 15 minutes by the VM's own clock (`received_utc`).
- **Postfix warning (accepted, 2026-11-23).** At a start, Postfix copies `/etc/resolv.conf` into its chroot and then
  warns "not owned by root: /var/spool/postfix/etc/resolv.conf" (the copy keeps the owner of systemd-resolved's stub).
  Harmless: the file is only read, the relay works (test mail of 2026-11-21). Left as it is.
