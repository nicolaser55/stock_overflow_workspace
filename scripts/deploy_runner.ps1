# Deploy main to the runner: the runner clone moves to origin/main and that commit becomes the judge of new jobs.
#
# Run as so_runner:   runas /user:so_runner powershell    then    .\scripts\deploy_runner.ps1   (from the runner clone)
# Optional: -RunnerWorkspace <folder> (default D:\stock_overflow\runner_workspace), -DataRoot <folder> (default
# D:\stock_overflow\data), -TaskName <name> (default "SO queue runner"), -Force (deploy while a job is running; the
# restart then stops that job, which the next start resumes under the same run id and its pinned judge).
#
# The judge (design 4.2, roadmap R2): the queue scores every new job with the commit in the ref refs/deployed of this
# clone, which only this script sets. A merge to main changes nothing until it is deployed. This clone also holds the
# queue script itself, so HEAD and refs/deployed always move together. state.json shows both ("queue_commit",
# "deployed_commit"); "git reflog refs/deployed" in this clone lists every deployment with its time and account.
param(
    [string]$RunnerWorkspace = "D:\stock_overflow\runner_workspace",
    [string]$DataRoot = "D:\stock_overflow\data",
    [string]$TaskName = "SO queue runner",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
Set-Location $RunnerWorkspace

# 1. WHAT IS RUNNING
$statePath = Join-Path $DataRoot "store04_experiments\state.json"
if ((Test-Path $statePath) -and -not $Force) {
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    if ($null -ne $state.running) {
        Write-Host "STOP: a job is running ($($state.running.run_id)). Wait for it, or use -Force."
        return
    }
}

# 2. FETCH AND MOVE THE CLONE TO origin/main
git fetch --quiet origin
if ($LASTEXITCODE -ne 0) { Write-Host "STOP: git fetch failed"; return }
$target = (git rev-parse --verify "origin/main^{commit}").Trim()
$current = (git rev-parse HEAD).Trim()
if ($current -eq $target) {
    Write-Host "clone already at origin/main ($($target.Substring(0, 8)))"
} else {
    git checkout --force --detach $target
    if ($LASTEXITCODE -ne 0) { Write-Host "STOP: checkout failed"; return }
    Write-Host "runner clone now at $(git log -1 --format='%h %s')"
}

# 3. THE JUDGE: refs/deployed = THE COMMIT JUST CHECKED OUT (WITH A REFLOG ENTRY: WHEN AND BY WHOM)
git config core.logAllRefUpdates always
$previous = (git rev-parse --verify --quiet "refs/deployed^{commit}")
$stamp = Get-Date -Format "yyyy-MM-ddTHH:mm:ss"
git update-ref -m "deploy $stamp by $env:USERNAME" refs/deployed $target
if ($LASTEXITCODE -ne 0) { Write-Host "STOP: could not set refs/deployed"; return }
if ($previous -and ($previous.Trim() -eq $target)) {
    Write-Host "judge unchanged: refs/deployed = $($target.Substring(0, 8))"
} elseif ($previous) {
    Write-Host "judge deployed: refs/deployed $($previous.Trim().Substring(0, 8)) -> $($target.Substring(0, 8))"
} else {
    Write-Host "judge deployed (first time): refs/deployed = $($target.Substring(0, 8))"
}

# 4. RESTART THE TASK SO THE NEW QUEUE SCRIPT RUNS
try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "task '$TaskName' restarted"
} catch {
    Write-Host "could not restart the task ($($_.Exception.Message)); restart it from an administrator prompt: Start-ScheduledTask -TaskName '$TaskName'"
}
