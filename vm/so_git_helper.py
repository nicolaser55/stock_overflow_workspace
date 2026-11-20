#!/opt/so/venvs/main/bin/python -IS
# so-git-helper (vm/so_git_helper.py, 2026-11-19): the only way so_agent's work reaches GitHub.
#
# Installed root-owned at /usr/local/lib/so/so-git-helper; so_agent runs it as so_git through one sudo rule
# (/etc/sudoers.d/so-git-helper), usually through the wrapper /usr/local/bin/so-git. so_agent has no internet; so_git
# reaches github.com and api.github.com only, through the allow-list proxy 127.0.0.1:3130. The agent's token
# (classic, scope public_repo, account nicolaser55-agent) is in /etc/so/git/agent_token (root:so_git 0640) and is
# never printed or put on a command line.
#
#   so-git fetch-main            update main in the mirror /srv/so/git/stock_overflow_workspace.git from GitHub
#                                (then, in the agent clone: git fetch origin)
#   so-git push agent/<name>     push that branch from the inbox (/srv/so/git/agent_inbox.git, where the agent's
#                                git push lands) to GitHub. Refused: a branch outside agent/, a push that is not a
#                                fast-forward of the branch on GitHub, and a branch whose changes against main touch a
#                                path in main's protected_paths.txt (protected files change only through Nicolas)
#   so-git pr agent/<name> "<title>" < body.md
#                                open a pull request from that branch into main (body from standard input)
#
# It never deletes a branch, never force-pushes and never pushes to main. Every call is logged to
# /var/log/so/git-helper.log (time, caller, command, branch, commit, result).
import base64
import datetime
import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request

REPO_SLUG_STR = "nicolaser55/stock_overflow_workspace"
GITHUB_URL_STR = f"https://github.com/{REPO_SLUG_STR}.git"
API_URL_STR = f"https://api.github.com/repos/{REPO_SLUG_STR}"
MIRROR_STR = "/srv/so/git/stock_overflow_workspace.git"
INBOX_STR = "/srv/so/git/agent_inbox.git"
TOKEN_FILE_STR = "/etc/so/git/agent_token"
TOKEN_USER_STR = "nicolaser55-agent"
LOG_FILE_STR = "/var/log/so/git-helper.log"
PROXY_STR = "http://127.0.0.1:3130"
BRANCH_PATTERN = re.compile(r"^agent/[A-Za-z0-9][A-Za-z0-9._-]{0,80}(/[A-Za-z0-9][A-Za-z0-9._-]{0,80}){0,3}$")
MAX_BODY_BYTES_INT = 65536
MAX_TITLE_CHARS_INT = 200

# EXIT CODES: 0 DONE, 1 REFUSED (THE REQUEST BREAKS A RULE), 2 FAILED (GIT, NETWORK, TOKEN), 3 USAGE
EXIT_REFUSED_INT = 1
EXIT_FAILED_INT = 2
EXIT_USAGE_INT = 3


class HelperError(Exception):
    def __init__(self, message_str_in, exit_int_in):
        super().__init__(message_str_in)
        self.exit_int = exit_int_in


# FUNCTION: A FIXED ENVIRONMENT FOR GIT (NOTHING FROM THE CALLER)
def get_git_environment_dict(token_header_str_in=""):
    environment_dict = {"PATH": "/usr/bin:/bin", "HOME": "/var/lib/so_git", "LANG": "C.UTF-8",
                        "GIT_TERMINAL_PROMPT": "0",
                        "https_proxy": PROXY_STR, "HTTPS_PROXY": PROXY_STR, "GIT_ASKPASS": "/bin/false"}
    if token_header_str_in:
        # THE HEADER TRAVELS IN THE ENVIRONMENT (READABLE ONLY BY so_git AND ROOT), NOT ON THE COMMAND LINE
        environment_dict.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                                 "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {token_header_str_in}"})
    return environment_dict


# FUNCTION: RUN GIT IN A REPOSITORY
def run_git_str(repo_str_in, argument_list_in, token_header_str_in="", check_bool_in=True):
    result = subprocess.run(["git", "-C", repo_str_in, *argument_list_in], capture_output=True, text=True,
                            env=get_git_environment_dict(token_header_str_in), cwd="/", timeout=600)
    if check_bool_in and result.returncode != 0:
        raise HelperError(f"git {' '.join(argument_list_in[:2])} failed: {result.stderr.strip()[-400:]}", EXIT_FAILED_INT)
    return result.stdout.strip() if check_bool_in else result


# FUNCTION: THE TOKEN AS A BASIC-AUTH VALUE
def read_token_str():
    try:
        with open(TOKEN_FILE_STR, encoding="ascii") as token_file:
            token_str = token_file.read().strip()
    except OSError as error:
        raise HelperError(f"no token: {TOKEN_FILE_STR} cannot be read ({error.strerror})", EXIT_FAILED_INT)
    if not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token_str):
        raise HelperError(f"no token: {TOKEN_FILE_STR} does not hold one token on one line", EXIT_FAILED_INT)
    return token_str


# FUNCTION: APPEND ONE LINE TO THE LOG
def write_log(command_str_in, branch_str_in, commit_str_in, result_str_in):
    caller_str = os.environ.get("SUDO_USER", "") or str(os.getuid())
    line_str = "\t".join([datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), caller_str, command_str_in,
                          branch_str_in, commit_str_in, result_str_in.replace("\n", " ")[:500]])
    try:
        with open(LOG_FILE_STR, "a", encoding="utf-8") as log_file:
            log_file.write(line_str + "\n")
    except OSError:
        print(f"warning: could not write {LOG_FILE_STR}", file=sys.stderr)


# FUNCTION: REFUSE A BRANCH NAME OUTSIDE agent/
def check_branch_str(branch_str_in):
    if not BRANCH_PATTERN.match(branch_str_in) or ".." in branch_str_in or branch_str_in.endswith((".lock", ".")):
        raise HelperError(f"refused: {branch_str_in!r} is not a branch name of the form agent/<name>", EXIT_REFUSED_INT)
    return branch_str_in


# FUNCTION: UPDATE main IN THE MIRROR
def fetch_main_str():
    run_git_str(MIRROR_STR, ["fetch", "--quiet", "--no-tags", GITHUB_URL_STR, "+refs/heads/main:refs/heads/main"])
    return run_git_str(MIRROR_STR, ["rev-parse", "refs/heads/main"])


# FUNCTION: THE PROTECTED GLOBS FROM main's protected_paths.txt (THE AGENT CANNOT CHANGE THIS COPY)
def get_protected_glob_list():
    text_str = run_git_str(MIRROR_STR, ["show", "refs/heads/main:protected_paths.txt"])
    glob_list = []
    for line_str in text_str.splitlines():
        entry_str = line_str.split("#", 1)[0].strip()
        if entry_str:
            glob_list.append(entry_str[len("append:"):].strip() if entry_str.startswith("append:") else entry_str)
    return glob_list


# FUNCTION: WHETHER A PATH IS PROTECTED (THE RULE OF scripts/check_protected_paths.py get_protected_bool)
def get_protected_bool(path_str_in, glob_list_in):
    for glob_str in glob_list_in:
        if glob_str.endswith("/**"):
            if path_str_in.startswith(glob_str[:-2]):
                return True
        elif fnmatch.fnmatchcase(path_str_in, glob_str):
            return True
    return False


# FUNCTION: PUSH ONE AGENT BRANCH FROM THE INBOX TO GITHUB
def push_str(branch_str_in):
    branch_str = check_branch_str(branch_str_in)
    main_commit_str = fetch_main_str()
    # TAKE THE BRANCH FROM THE INBOX INTO so_git's OWN REPOSITORY, WHERE main CANNOT BE FORGED
    inbox_ref_str = f"refs/so-inbox/{branch_str}"
    result = run_git_str(MIRROR_STR, ["fetch", "--quiet", "--no-tags", INBOX_STR, f"+refs/heads/{branch_str}:{inbox_ref_str}"],
                         check_bool_in=False)
    if result.returncode != 0:
        raise HelperError(f"refused: the inbox has no branch {branch_str} (git push origin {branch_str} first)", EXIT_REFUSED_INT)
    tip_str = run_git_str(MIRROR_STR, ["rev-parse", inbox_ref_str])
    # NO FORCE PUSH: THE BRANCH ON GITHUB, IF ANY, MUST BE AN ANCESTOR OF THE NEW TIP
    remote_ref_str = f"refs/so-remote/{branch_str}"
    result = run_git_str(MIRROR_STR, ["fetch", "--quiet", "--no-tags", GITHUB_URL_STR, f"+refs/heads/{branch_str}:{remote_ref_str}"],
                         check_bool_in=False)
    if result.returncode == 0:
        remote_tip_str = run_git_str(MIRROR_STR, ["rev-parse", remote_ref_str])
        ancestor = run_git_str(MIRROR_STR, ["merge-base", "--is-ancestor", remote_tip_str, tip_str], check_bool_in=False)
        if ancestor.returncode != 0:
            raise HelperError(f"refused: {branch_str} on GitHub ({remote_tip_str[:12]}) is not an ancestor of {tip_str[:12]}; "
                              "no force pushes", EXIT_REFUSED_INT)
    # NO PROTECTED PATH: THE CHANGES OF THE BRANCH AGAINST main (FROM THEIR MERGE BASE)
    base_str = run_git_str(MIRROR_STR, ["merge-base", "refs/heads/main", tip_str])
    changed_list = [p for p in run_git_str(MIRROR_STR, ["diff", "--name-only", "--no-renames", base_str, tip_str]).splitlines() if p]
    glob_list = get_protected_glob_list()
    protected_list = [path_str for path_str in changed_list if get_protected_bool(path_str, glob_list)]
    if protected_list:
        raise HelperError("refused: the branch changes protected paths (only Nicolas changes these): "
                          + ", ".join(protected_list[:20]), EXIT_REFUSED_INT)
    if not changed_list:
        raise HelperError(f"refused: {branch_str} has no changes against main ({main_commit_str[:12]})", EXIT_REFUSED_INT)
    token_header_str = base64.b64encode(f"{TOKEN_USER_STR}:{read_token_str()}".encode("ascii")).decode("ascii")
    run_git_str(MIRROR_STR, ["push", "--quiet", "--no-verify", GITHUB_URL_STR, f"{tip_str}:refs/heads/{branch_str}"],
                token_header_str_in=token_header_str)
    return tip_str, len(changed_list)


# FUNCTION: OPEN A PULL REQUEST
def open_pr_str(branch_str_in, title_str_in, body_str_in):
    branch_str = check_branch_str(branch_str_in)
    if not title_str_in.strip() or len(title_str_in) > MAX_TITLE_CHARS_INT or re.search(r"[\x00-\x1f\x7f]", title_str_in):
        raise HelperError(f"refused: the title must be one line of 1 to {MAX_TITLE_CHARS_INT} characters", EXIT_REFUSED_INT)
    request = urllib.request.Request(f"{API_URL_STR}/pulls", method="POST",
                                     data=json.dumps({"title": title_str_in.strip(), "head": branch_str, "base": "main",
                                                      "body": body_str_in}).encode("utf-8"),
                                     headers={"Authorization": f"token {read_token_str()}",
                                              "Accept": "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "so-git-helper"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"https": PROXY_STR}))
    try:
        with opener.open(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))["html_url"]
    except urllib.error.HTTPError as error:
        detail_str = error.read().decode("utf-8", "replace")[:400]
        raise HelperError(f"GitHub refused the pull request (HTTP {error.code}): {detail_str}", EXIT_FAILED_INT)
    except (urllib.error.URLError, OSError) as error:
        raise HelperError(f"GitHub could not be reached: {error}", EXIT_FAILED_INT)


# FUNCTION: MAIN
def main_int(argument_list_in):
    usage_str = ("usage: so-git fetch-main | so-git push agent/<name> | so-git pr agent/<name> \"<title>\" < body.md")
    if not argument_list_in:
        print(usage_str, file=sys.stderr)
        return EXIT_USAGE_INT
    command_str, branch_str, commit_str = argument_list_in[0], "", ""
    try:
        if command_str == "fetch-main" and len(argument_list_in) == 1:
            commit_str = fetch_main_str()
            print(f"main is {commit_str} in the mirror; in your clone run: git fetch origin")
        elif command_str == "push" and len(argument_list_in) == 2:
            branch_str = argument_list_in[1]
            commit_str, count_int = push_str(branch_str)
            print(f"pushed {branch_str} at {commit_str} to GitHub ({count_int} changed files against main)")
        elif command_str == "pr" and len(argument_list_in) == 3:
            branch_str = argument_list_in[1]
            body_bytes = sys.stdin.buffer.read(MAX_BODY_BYTES_INT + 1) if not sys.stdin.isatty() else b""
            if len(body_bytes) > MAX_BODY_BYTES_INT:
                raise HelperError(f"refused: the body is longer than {MAX_BODY_BYTES_INT} bytes", EXIT_REFUSED_INT)
            url_str = open_pr_str(branch_str, argument_list_in[2], body_bytes.decode("utf-8", "replace"))
            commit_str = url_str
            print(f"opened {url_str}")
        else:
            print(usage_str, file=sys.stderr)
            write_log(command_str[:40], "", "", "usage error")
            return EXIT_USAGE_INT
    except HelperError as error:
        print(str(error), file=sys.stderr)
        write_log(command_str, branch_str[:120], commit_str, str(error))
        return error.exit_int
    except subprocess.TimeoutExpired:
        print("failed: git took longer than 10 minutes", file=sys.stderr)
        write_log(command_str, branch_str[:120], commit_str, "timeout")
        return EXIT_FAILED_INT
    write_log(command_str, branch_str, commit_str, "ok")
    return 0


if __name__ == "__main__":
    os.umask(0o027)
    sys.exit(main_int(sys.argv[1:]))
