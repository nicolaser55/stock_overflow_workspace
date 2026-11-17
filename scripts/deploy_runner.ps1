# Deploy main to the runner: the runner clone moves to origin/main and that commit becomes the judge of new jobs.
#
# Run as so_runner:   runas /user:so_runner powershell    then, from the runner clone (D:\stock_overflow\runner_workspace):
#     powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_runner.ps1 -ExpectCommit <sha>
# (so_runner's execution policy blocks scripts; the bypass applies to this one process only, 2026-11-15). <sha> is the
# merge commit you just merged (scripts\nico_merge.ps1 prints it); the deploy stops unless origin/main is that commit.
# Optional: -RunnerWorkspace <folder> (default D:\stock_overflow\runner_workspace), -DataRoot <folder> (default
# D:\stock_overflow\data), -TaskName <name> (default "SO queue runner"), -Python <python.exe> (default SO_QUEUE_PYTHON,
# the runner's venv-main), -Force (deploy while a job is running; the restart then stops that job, which the next start
# resumes under the same run id and its pinned judge).
#
# The judge (design 4.2, roadmap R2): the queue scores every new job with the commit in the ref refs/deployed of this
# clone, which only this script sets. A merge to main changes nothing until it is deployed. This clone also holds the
# queue script itself, so the deploy moves HEAD first and refs/deployed second, and checks at the end that both name
# the same commit; a deploy that stops between the two (or is cancelled) moves HEAD back to where it was. state.json
# shows "queue_commit" (the commit the running watch started from; the task restart below refreshes it) and
# "deployed_commit"; "git reflog refs/deployed" in this clone lists every deployment with its time and account.
#
# What the deploy shows (review 2026-11-17, B3): the judge hash (so.runner.judge_identity) of the commit deployed
# before and of the new one, computed from the git objects of each commit, and the protected files changed between
# them. When the judge hash changes, or on a first deploy, it asks you to type the first 8 characters of the new hash:
# the deploy is the point where a judge change must be seen (results under a new judge are not directly comparable).
#
# Native commands (git, python) run through Invoke-Native: Windows PowerShell 5 turns a native program's stderr into
# an error record, which with $ErrorActionPreference = "Stop" ended the script half way (D6, 2026-11-13). The exit code
# ($LASTEXITCODE) decides instead.
#
# core.autocrlf of this clone is "true" (recorded 2026-11-17). The design-folder hash reads raw bytes, so a changed
# setting would make every registered version look like changed code (runs would fail closed). Never change it; the
# deploy warns when it differs.
#
# PowerShell reads this file before running it: when a merge changes this script itself, run it twice (the first run
# still uses the old script; a version without -ExpectCommit refuses that argument, so run the old command first).
param(
    [string]$ExpectCommit = "",
    [string]$RunnerWorkspace = "D:\stock_overflow\runner_workspace",
    [string]$DataRoot = "D:\stock_overflow\data",
    [string]$TaskName = "SO queue runner",
    [string]$Python = $env:SO_QUEUE_PYTHON,
    [switch]$Force
)
$ErrorActionPreference = "Stop"

# THE ACCOUNT AND THE COMMIT ARE EXPLICIT
$RunnerAccount = "so_runner"
$RecordedAutoCrlf = "true"
if ($env:USERNAME -ne $RunnerAccount) {
    Write-Host "STOP: run the deploy as $RunnerAccount (this window runs as $env:USERNAME): runas /user:$RunnerAccount powershell"
    exit 1
}
if ($ExpectCommit -notmatch "^[0-9a-fA-F]{7,40}$") {
    Write-Host "STOP: give the commit you expect to deploy: -ExpectCommit <sha> (the merge commit nico_merge.ps1 printed)"
    exit 1
}
if (-not $Python -or -not (Test-Path $Python)) {
    Write-Host "STOP: no Python for the judge hash (-Python, or SO_QUEUE_PYTHON of $RunnerAccount): '$Python'"
    exit 1
}
Set-Location $RunnerWorkspace

# FUNCTION: RUN A NATIVE PROGRAM; ITS STDERR IS TEXT, ITS EXIT CODE DECIDES (D6)
function Invoke-Native {
    param([string]$FilePath, [string[]]$ArgumentList)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $all = & $FilePath @ArgumentList 2>&1
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
    $out = @($all | Where-Object { $_ -isnot [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
    $err = @($all | Where-Object { $_ -is [System.Management.Automation.ErrorRecord] } | ForEach-Object { "$_" })
    return [pscustomobject]@{ Code = $code; Out = $out; Err = $err; Text = (@($out) + @($err)) -join "`n" }
}

# FUNCTION: ONE LINE OF GIT OUTPUT, OR "" WHEN GIT FAILS
function Get-GitLine {
    param([string[]]$ArgumentList)
    $result = Invoke-Native "git" $ArgumentList
    if ($result.Code -ne 0 -or @($result.Out).Count -eq 0) { return "" }
    return "$(@($result.Out)[0])".Trim()
}

# FUNCTION: PUT HEAD BACK WHERE IT WAS (A CANCELLED OR FAILED DEPLOY LEAVES HEAD AND refs/deployed TOGETHER)
function Restore-Head {
    param([string]$Commit)
    if (-not $Commit) { return }
    $restore = Invoke-Native "git" @("checkout", "--quiet", "--force", "--detach", $Commit)
    if ($restore.Code -eq 0) {
        Write-Host "HEAD moved back to $($Commit.Substring(0, 8)); refs/deployed unchanged"
    } else {
        Write-Host "WARNING: could not move HEAD back to $Commit ($($restore.Text)); run: git checkout --force --detach $Commit"
    }
}

# 1. WHAT IS RUNNING (SINCE R4 THE QUEUE WRITES store04_experiments\visible\state.json; THE ZONE-ROOT state.json OF
# EARLIER VERSIONS IS READ TOO, FOR A DEPLOY FROM AN OLDER QUEUE). NO READABLE STATE: STOP UNLESS -Force
if (-not $Force) {
    $statePathList = @((Join-Path $DataRoot "store04_experiments\visible\state.json"), (Join-Path $DataRoot "store04_experiments\state.json")) |
        Where-Object { Test-Path $_ }
    if (@($statePathList).Count -eq 0) {
        Write-Host "STOP: no state.json found under $DataRoot\store04_experiments; check that the runner is up, or use -Force."
        exit 1
    }
    foreach ($statePath in $statePathList) {
        $state = Get-Content $statePath -Raw | ConvertFrom-Json
        if ($null -ne $state.running) {
            Write-Host "STOP: a job is running ($($state.running.run_id)). Wait for it, or use -Force."
            exit 1
        }
    }
}

# 2. FETCH; origin/main MUST BE THE EXPECTED COMMIT
$fetch = Invoke-Native "git" @("fetch", "--quiet", "origin")
if ($fetch.Code -ne 0) { Write-Host "STOP: git fetch failed: $($fetch.Text)"; exit 1 }
$target = Get-GitLine @("rev-parse", "--verify", "origin/main^{commit}")
$expected = Get-GitLine @("rev-parse", "--verify", "--quiet", "$ExpectCommit^{commit}")
if (-not $target) { Write-Host "STOP: origin/main does not resolve"; exit 1 }
if (-not $expected) { Write-Host "STOP: the commit $ExpectCommit is not in this clone after the fetch (pushed? merged?)"; exit 1 }
if ($expected -ne $target) {
    Write-Host "STOP: origin/main is $($target.Substring(0, 8)), you expected $($expected.Substring(0, 8)). Nothing changed."
    Write-Host "      (a later merge, or the wrong commit pasted; check with: git log --oneline -5 origin/main)"
    exit 1
}
$current = Get-GitLine @("rev-parse", "HEAD")
$previous = Get-GitLine @("rev-parse", "--verify", "--quiet", "refs/deployed^{commit}")
$autoCrlf = Get-GitLine @("config", "--get", "core.autocrlf")
Write-Host "origin/main       $target (as expected)"
Write-Host "HEAD now          $(if ($current) { $current } else { '(none)' })"
Write-Host "refs/deployed now $(if ($previous) { $previous } else { '(none: first deploy)' })"
if ($autoCrlf -ne $RecordedAutoCrlf) {
    Write-Host "WARNING: core.autocrlf is '$autoCrlf', recorded as '$RecordedAutoCrlf' on 2026-11-17. Registered versions were hashed"
    Write-Host "         with '$RecordedAutoCrlf'; restore it (git config core.autocrlf $RecordedAutoCrlf) before any run."
}

# 3. MOVE THE CLONE TO THE TARGET (QUIET: NO PROGRESS TEXT ON STDERR)
if ($current -ne $target) {
    $checkout = Invoke-Native "git" @("checkout", "--quiet", "--force", "--detach", $target)
    $after = Get-GitLine @("rev-parse", "HEAD")
    if ($checkout.Code -ne 0 -or $after -ne $target) {
        Write-Host "STOP: checkout failed ($($checkout.Text))"
        Restore-Head $current
        exit 1
    }
    Write-Host "runner clone now at $(Get-GitLine @('log', '-1', '--format=%h %s'))"
} else {
    Write-Host "clone already at origin/main ($($target.Substring(0, 8)))"
}

# 4. THE JUDGE BEFORE AND AFTER (so.runner.judge_identity OF THE NEW COMMIT'S CODE, ON THE GIT OBJECTS OF BOTH COMMITS)
$judgeCode = @'
import subprocess
import sys

# THE CLONE'S so/, NOT AN INSTALLED COPY
# "-" = NO EARLIER DEPLOY (WINDOWS POWERSHELL 5 DROPS AN EMPTY ARGUMENT TO A NATIVE PROGRAM)
workspace_str, old_str, new_str = sys.argv[1], sys.argv[2], sys.argv[3]
old_str = "" if old_str == "-" else old_str
sys.path.insert(0, workspace_str)
from so.runner.judge_identity import (PROTECTED_LIST_FILE_STR, get_judge_glob_list, get_judge_glob_match_bool,
                                      get_judge_hash_from_reader_dict, get_judge_rel_path_list)


def get_git_bytes(arg_list_in):
    return subprocess.check_output(["git"] + list(arg_list_in), cwd=workspace_str)


def get_commit_judge_dict(commit_str_in):
    name_list = [name for name in get_git_bytes(["ls-tree", "-r", "--name-only", "-z", commit_str_in]).decode("utf-8").split("\0") if name]
    list_text_str = get_git_bytes(["show", f"{commit_str_in}:{PROTECTED_LIST_FILE_STR}"]).decode("utf-8")
    rel_list = get_judge_rel_path_list(name_list, list_text_str)
    hash_dict = get_judge_hash_from_reader_dict(rel_list, lambda rel_str: get_git_bytes(["show", f"{commit_str_in}:{rel_str}"]))
    return dict(hash_dict, rel_set=set(rel_list), glob_list=get_judge_glob_list(list_text_str))


new_dict = get_commit_judge_dict(new_str)
print(f"NEW_JUDGE_HASH={new_dict['judge_hash']}")
print(f"NEW_JUDGE_FILE_COUNT={new_dict['judge_file_count']}")
if old_str:
    old_dict = get_commit_judge_dict(old_str)
    print(f"OLD_JUDGE_HASH={old_dict['judge_hash']}")
    print(f"OLD_JUDGE_FILE_COUNT={old_dict['judge_file_count']}")
    changed_list = [name for name in get_git_bytes(["diff", "--name-only", "-z", old_str, new_str]).decode("utf-8").split("\0") if name]
    for path_str in changed_list:
        if path_str in old_dict["rel_set"] or path_str in new_dict["rel_set"]:
            print(f"JUDGE_FILE_CHANGED={path_str}")
        elif get_judge_glob_match_bool(path_str, old_dict["glob_list"]) or get_judge_glob_match_bool(path_str, new_dict["glob_list"]):
            print(f"PROTECTED_CHANGED={path_str}")
    print(f"CHANGED_FILE_COUNT={len(changed_list)}")
'@
$judgeScript = Join-Path ([System.IO.Path]::GetTempPath()) "so_deploy_judge_$PID.py"
[System.IO.File]::WriteAllText($judgeScript, $judgeCode, (New-Object System.Text.UTF8Encoding $false))
$judge = Invoke-Native $Python @("-I", $judgeScript, $RunnerWorkspace, $(if ($previous) { $previous } else { "-" }), $target)
Remove-Item $judgeScript -ErrorAction SilentlyContinue
$judgeMap = @{}
$judgeFileList = @()
$protectedList = @()
foreach ($line in @($judge.Out)) {
    if ($line -match "^JUDGE_FILE_CHANGED=(.+)$") { $judgeFileList += $Matches[1] }
    elseif ($line -match "^PROTECTED_CHANGED=(.+)$") { $protectedList += $Matches[1] }
    elseif ($line -match "^([A-Z_]+)=(.*)$") { $judgeMap[$Matches[1]] = $Matches[2] }
}
if ($judge.Code -ne 0 -or -not $judgeMap["NEW_JUDGE_HASH"] -or ($previous -and -not $judgeMap["OLD_JUDGE_HASH"])) {
    Write-Host "STOP: the judge hash could not be computed (python exit $($judge.Code)):"
    Write-Host $judge.Text
    Restore-Head $current
    exit 1
}
$newHash = $judgeMap["NEW_JUDGE_HASH"]
$oldHash = $judgeMap["OLD_JUDGE_HASH"]
Write-Host ""
if ($previous) {
    Write-Host "judge hash before $oldHash ($($judgeMap['OLD_JUDGE_FILE_COUNT']) files, $($previous.Substring(0, 8)))"
}
Write-Host "judge hash after  $newHash ($($judgeMap['NEW_JUDGE_FILE_COUNT']) files, $($target.Substring(0, 8)))"
if ($previous) {
    Write-Host "files changed since the last deploy: $($judgeMap['CHANGED_FILE_COUNT'])"
    Write-Host "  judge files changed:     $(if (@($judgeFileList).Count) { '' } else { 'none' })"
    foreach ($path in $judgeFileList) { Write-Host "    $path" }
    Write-Host "  other protected changed: $(if (@($protectedList).Count) { '' } else { 'none' })"
    foreach ($path in $protectedList) { Write-Host "    $path" }
}
$judgeChanged = (-not $previous) -or ($oldHash -ne $newHash)
if ($judgeChanged) {
    Write-Host ""
    if ($previous) {
        Write-Host "THE JUDGE CHANGES. Results under the new judge are not directly comparable with earlier ones."
    } else {
        Write-Host "FIRST DEPLOY of a judge in this clone."
    }
    $typed = Read-Host "Type the first 8 characters of the new judge hash to deploy it (anything else cancels)"
    if ("$typed".Trim() -ne $newHash.Substring(0, 8)) {
        Write-Host "CANCELLED: nothing deployed."
        Restore-Head $current
        exit 1
    }
} else {
    Write-Host "judge hash unchanged"
}

# 5. THE JUDGE: refs/deployed = THE COMMIT JUST CHECKED OUT (WITH A REFLOG ENTRY: WHEN AND BY WHOM)
$null = Invoke-Native "git" @("config", "core.logAllRefUpdates", "always")
$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
$update = Invoke-Native "git" @("update-ref", "-m", "deploy $stamp by $env:USERNAME judge $($newHash.Substring(0, 12))", "refs/deployed", $target)
if ($update.Code -ne 0) {
    Write-Host "STOP: could not set refs/deployed ($($update.Text))"
    Restore-Head $current
    exit 1
}
$deployedNow = Get-GitLine @("rev-parse", "--verify", "refs/deployed^{commit}")
$headNow = Get-GitLine @("rev-parse", "HEAD")
if ($deployedNow -ne $target -or $headNow -ne $target) {
    Write-Host "STOP: after the deploy HEAD is $headNow and refs/deployed is $deployedNow; both should be $target. Run the deploy again."
    exit 1
}
if ($previous -and ($previous -eq $target)) {
    Write-Host "judge unchanged: refs/deployed = $($target.Substring(0, 8))"
} elseif ($previous) {
    Write-Host "judge deployed: refs/deployed $($previous.Substring(0, 8)) -> $($target.Substring(0, 8))"
} else {
    Write-Host "judge deployed (first time): refs/deployed = $($target.Substring(0, 8))"
}
Write-Host "HEAD and refs/deployed both at $target"

# 6. RESTART THE TASK SO THE NEW QUEUE SCRIPT RUNS
try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "task '$TaskName' restarted"
} catch {
    Write-Host "could not restart the task ($($_.Exception.Message)); restart it from an administrator prompt: Start-ScheduledTask -TaskName '$TaskName'"
}
