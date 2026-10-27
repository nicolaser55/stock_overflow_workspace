# Deploy main to the runner clone (the queue script itself) and restart the queue task.
#
# Run as so_runner:   runas /user:so_runner powershell    then    .\scripts\deploy_runner.ps1   (from the runner clone)
# Optional: -RunnerWorkspace <folder> (default D:\stock_overflow\runner_workspace), -DataRoot <folder> (default
# D:\stock_overflow\data), -TaskName <name> (default "SO queue runner"), -Force (deploy while a job is running; the
# restart then stops that job, which the next start resumes under the same run id).
#
# The judge of a run does not come from this clone: the queue builds each run from the tip of origin/main. This clone
# holds the queue script, so it has to follow main too. state.json shows its commit as "queue_commit".
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
$target = (git rev-parse --verify "origin/main^{commit}").Trim()
$current = (git rev-parse HEAD).Trim()
if ($current -eq $target) {
    Write-Host "already at origin/main ($($target.Substring(0, 8)))"
} else {
    git checkout --force --detach $target
    if ($LASTEXITCODE -ne 0) { Write-Host "STOP: checkout failed"; return }
    Write-Host "runner clone now at $(git log -1 --format='%h %s')"
}

# 3. RESTART THE TASK SO THE NEW QUEUE SCRIPT RUNS
try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "task '$TaskName' restarted"
} catch {
    Write-Host "could not restart the task ($($_.Exception.Message)); restart it from an administrator prompt: Start-ScheduledTask -TaskName '$TaskName'"
}
