# Merge one pull request into main and bring nico's clone to the merge commit (review 2026-11-17, B2).
#
# Run as nico, from any folder:
#     powershell -NoProfile -ExecutionPolicy Bypass -File D:\stock_overflow\workspace\scripts\nico_merge.ps1 -Pr <number>
# Optional: -Workspace <folder> (default D:\stock_overflow\workspace), -Repo <owner/name> (default
# nicolaser55/stock_overflow_workspace).
#
# Every gh command names the pull request and the repository, so nothing depends on the branch that happens to be
# checked out (on exp14, "gh pr checks" and "gh pr merge" without a number acted on the wrong branch once, a merge came
# before the checks and a pull before the merge). In order:
#   1. refuse another account, a missing -Pr, and a clone with uncommitted changes to tracked files;
#   2. show the pull request (title, branches, state); refuse unless it is open, not a draft, and based on main;
#   3. wait for the required checks: gh pr checks <n> --watch --required (GitHub still enforces them at the merge);
#   4. by author (since 2026-11-18 main requires 1 approval, with the repository admin as bypass):
#      - nicolaser55-agent (the Cursor agent): shows the files the PR changes, asks you to type the PR number, then
#        approves it as nicolaser55 (gh pr review --approve) and merges it: your approval is the consent to run it;
#      - nicolaser55 (your own PRs, from Claude's zips): you cannot approve your own PR, so it merges with --admin
#        (the bypass), only after step 3 has seen every required check pass (--admin would also skip the checks);
#      - anyone else: refused.
#      Merge commit (main allows merge commits only: a squash would rename a "preregister" commit); the branch is
#      deleted on GitHub;
#   5. git checkout main; git pull --ff-only;
#   6. check that HEAD is the pull request's merge commit (gh pr view <n> --json mergeCommit), print the final state of
#      the checks, and print the merge commit: that is the -ExpectCommit of scripts\deploy_runner.ps1.
# Native commands run with their exit code checked (their stderr is not treated as an error, D6). The merge is still
# Nicolas's decision: running this script is the act of merging.
param(
    [int]$Pr = 0,
    [string]$Workspace = "D:\stock_overflow\workspace",
    [string]$Repo = "nicolaser55/stock_overflow_workspace",
    [string]$OwnerLogin = "nicolaser55",
    [string]$AgentLogin = "nicolaser55-agent"
)
$ErrorActionPreference = "Stop"

# THE ACCOUNT AND THE PULL REQUEST ARE EXPLICIT
$NicoAccount = "nico"
if ($env:USERNAME -ne $NicoAccount) {
    Write-Host "STOP: run the merge as $NicoAccount (this window runs as $env:USERNAME)"
    exit 1
}
if ($Pr -le 0) {
    Write-Host "STOP: name the pull request: -Pr <number>"
    exit 1
}
Set-Location $Workspace

# FUNCTION: RUN A NATIVE PROGRAM AND CAPTURE ITS OUTPUT; ITS EXIT CODE DECIDES
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

# FUNCTION: RUN A NATIVE PROGRAM WITH ITS OUTPUT ON THE CONSOLE (LONG WAITS); RETURNS THE EXIT CODE
function Invoke-NativeLive {
    param([string]$FilePath, [string[]]$ArgumentList)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @ArgumentList | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

# 1. A CLONE WITHOUT UNCOMMITTED CHANGES TO TRACKED FILES
$status = Invoke-Native "git" @("status", "--porcelain", "--untracked-files=no")
if ($status.Code -ne 0) { Write-Host "STOP: git status failed: $($status.Text)"; exit 1 }
if (@($status.Out | Where-Object { $_.Trim() }).Count -gt 0) {
    Write-Host "STOP: uncommitted changes in $Workspace (commit, stash or discard them first):"
    $status.Out | ForEach-Object { Write-Host "  $_" }
    exit 1
}

# 2. THE PULL REQUEST: OPEN, NOT A DRAFT, INTO main
$view = Invoke-Native "gh" @("pr", "view", "$Pr", "--repo", $Repo, "--json", "number,title,state,isDraft,baseRefName,headRefName,url,author")
if ($view.Code -ne 0) { Write-Host "STOP: gh pr view $Pr failed: $($view.Text)"; exit 1 }
$prInfo = (@($view.Out) -join "`n") | ConvertFrom-Json
$author = "$($prInfo.author.login)"
Write-Host "PR #$($prInfo.number): $($prInfo.title)"
Write-Host "  author: $author"
Write-Host "  $($prInfo.headRefName) -> $($prInfo.baseRefName), $($prInfo.state)$(if ($prInfo.isDraft) { ', draft' })"
Write-Host "  $($prInfo.url)"
if ($prInfo.state -ne "OPEN") { Write-Host "STOP: the pull request is $($prInfo.state), not OPEN"; exit 1 }
if ($prInfo.isDraft) { Write-Host "STOP: the pull request is a draft"; exit 1 }
if ($prInfo.baseRefName -ne "main") { Write-Host "STOP: the pull request goes into $($prInfo.baseRefName), not main"; exit 1 }
if ($author -ne $OwnerLogin -and $author -ne $AgentLogin) { Write-Host "STOP: unknown author '$author' (expected $OwnerLogin or $AgentLogin)"; exit 1 }

# 3. WAIT FOR THE REQUIRED CHECKS OF THIS PULL REQUEST
Write-Host ""
Write-Host "waiting for the required checks of #$Pr ..."
$checksCode = Invoke-NativeLive "gh" @("pr", "checks", "$Pr", "--repo", $Repo, "--watch", "--required")
if ($checksCode -ne 0) {
    Write-Host "STOP: the required checks of #$Pr did not all pass (gh exit $checksCode). Nothing merged."
    exit 1
}

# 4. APPROVE (AGENT PR) OR BYPASS (OWN PR), THEN MERGE COMMIT, BRANCH DELETED ON GITHUB
$mergeArgs = @("pr", "merge", "$Pr", "--repo", $Repo, "--merge", "--delete-branch")
if ($author -eq $AgentLogin) {
    $files = Invoke-Native "gh" @("pr", "diff", "$Pr", "--repo", $Repo, "--name-only")
    if ($files.Code -ne 0) { Write-Host "STOP: gh pr diff $Pr failed: $($files.Text)"; exit 1 }
    Write-Host ""
    Write-Host "files changed by the agent's PR #${Pr}:"
    $files.Out | ForEach-Object { Write-Host "  $_" }
    $typed = Read-Host "Approve and merge? Type the PR number ($Pr) to approve it as $OwnerLogin (anything else cancels)"
    if ("$typed".Trim() -ne "$Pr") { Write-Host "CANCELLED: not approved, not merged."; exit 1 }
    $review = Invoke-Native "gh" @("pr", "review", "$Pr", "--repo", $Repo, "--approve", "--body", "Approved by Nicolas (nico_merge.ps1).")
    if ($review.Code -ne 0) { Write-Host "STOP: gh pr review --approve failed: $($review.Text)"; exit 1 }
    Write-Host "approved #$Pr as $OwnerLogin"
} else {
    $mergeArgs += "--admin"
    Write-Host "own PR: merging with the admin bypass (the required checks passed above)"
}
$merge = Invoke-Native "gh" $mergeArgs
Write-Host $merge.Text
if ($merge.Code -ne 0) { Write-Host "STOP: gh pr merge $Pr failed (exit $($merge.Code))"; exit 1 }

# 5. main OF THIS CLONE, FAST-FORWARD ONLY
$checkout = Invoke-Native "git" @("checkout", "--quiet", "main")
if ($checkout.Code -ne 0) { Write-Host "STOP: git checkout main failed: $($checkout.Text)"; exit 1 }
$pull = Invoke-Native "git" @("pull", "--ff-only", "--quiet")
if ($pull.Code -ne 0) { Write-Host "STOP: git pull --ff-only failed: $($pull.Text)"; exit 1 }

# 6. HEAD = THE MERGE COMMIT OF THIS PULL REQUEST
$merged = Invoke-Native "gh" @("pr", "view", "$Pr", "--repo", $Repo, "--json", "state,mergeCommit")
if ($merged.Code -ne 0) { Write-Host "STOP: gh pr view $Pr failed after the merge: $($merged.Text)"; exit 1 }
$mergedInfo = (@($merged.Out) -join "`n") | ConvertFrom-Json
$mergeCommit = "$($mergedInfo.mergeCommit.oid)"
$head = "$(@((Invoke-Native 'git' @('rev-parse', 'HEAD')).Out)[0])".Trim()
if ($mergedInfo.state -ne "MERGED" -or -not $mergeCommit) {
    Write-Host "STOP: #$Pr is $($mergedInfo.state) with no merge commit yet; check it on GitHub, then: git pull --ff-only"
    exit 1
}
if ($head -ne $mergeCommit) {
    Write-Host "STOP: HEAD is $head, the merge commit of #$Pr is $mergeCommit."
    Write-Host "      (main moved on after the merge, or the pull did not reach it; check: git log --oneline -5 main)"
    exit 1
}
$finalChecks = Invoke-Native "gh" @("pr", "checks", "$Pr", "--repo", $Repo)
Write-Host ""
Write-Host "checks of #${Pr}:"
$finalChecks.Out | ForEach-Object { Write-Host "  $_" }
Write-Host ""
Write-Host "merged #$Pr; main and HEAD at the merge commit:"
Write-Host "  $mergeCommit"
Write-Host "deploy it as so_runner (runas /user:so_runner powershell, in D:\stock_overflow\runner_workspace):"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_runner.ps1 -ExpectCommit $mergeCommit"
