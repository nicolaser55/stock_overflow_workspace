# Queue one development run, only at the deployed commit (review 2026-11-17, B4; finding A1).
#
# Run as nico, from any folder, after the preregister pull request is merged (scripts\nico_merge.ps1) and deployed
# (scripts\deploy_runner.ps1 as so_runner):
#     powershell -NoProfile -ExecutionPolicy Bypass -File D:\stock_overflow\workspace\scripts\nico_queue.ps1 `
#         -Experiment expNN_<name> -Note "<why this run>"
# Optional: -Workspace <folder> (default D:\stock_overflow\workspace), -DataRoot <folder> (default SO_DATA_PATH, else
# D:\stock_overflow\data), -Python <python.exe> (default <Workspace>\venv-main\Scripts\python.exe).
#
# Why: run_queue.py add records HEAD of the clone it runs in, and neither add nor the runner compares that commit with
# the deployed judge. A job on an older commit is accepted and runs the older copy of the design (A1): trial rows for the
# wrong code, version 1.0 locked to the wrong folder hash. This wrapper refuses unless, after a fetch:
#   1. the account is nico, -Experiment and -Note are given, and the clone has no uncommitted change to tracked files;
#   2. HEAD = origin/main = "deployed_commit" of <DataRoot>\store04_experiments\visible\state.json (the key that
#      run_queue.py write_state_dict writes: refs/deployed of the runner's clone);
#   3. experiments\<Experiment>\design.py exists;
#   4. scripts\check_experiment_ready.py passes with --require-trial-log (nico can read the trial log, so the runner's
#      full pre-registration check, check_preregistration_dict, runs here with the trial log, as the run will);
#   5. you type the experiment name: queueing is the moment N is spent (the HAND lines of the check must be done).
# Then it runs: run_queue.py add experiments/<Experiment> --commit <HEAD> --note <Note>, and checks that the job's
# commit is HEAD. Native commands run with their exit code checked (their stderr is not an error, D6).
param(
    [string]$Experiment = "",
    [string]$Note = "",
    [string]$Workspace = "D:\stock_overflow\workspace",
    [string]$DataRoot = "",
    [string]$Python = ""
)
$ErrorActionPreference = "Stop"

# THE ACCOUNT AND THE ARGUMENTS ARE EXPLICIT
$NicoAccount = "nico"
if ($env:USERNAME -ne $NicoAccount) {
    Write-Host "STOP: queue runs as $NicoAccount (this window runs as $env:USERNAME)"
    exit 1
}
if ($Experiment -notmatch "^exp\d+_[A-Za-z0-9_]+$") {
    Write-Host "STOP: name the experiment folder: -Experiment expNN_<name> (got '$Experiment')"
    exit 1
}
if (-not $Note.Trim()) {
    Write-Host "STOP: give the reason for the run: -Note ""<why>"""
    exit 1
}
if ($Note.Contains('"')) {
    Write-Host "STOP: the note may not contain double quotes"
    exit 1
}
if (-not $DataRoot) { $DataRoot = if ($env:SO_DATA_PATH) { $env:SO_DATA_PATH } else { "D:\stock_overflow\data" } }
if (-not $env:SO_DATA_PATH) { $env:SO_DATA_PATH = $DataRoot }
if (-not $Python) { $Python = Join-Path $Workspace "venv-main\Scripts\python.exe" }
if (-not (Test-Path $Python)) { Write-Host "STOP: no Python at $Python"; exit 1 }
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

# FUNCTION: RUN A NATIVE PROGRAM WITH ITS OUTPUT ON THE CONSOLE; RETURNS THE EXIT CODE
function Invoke-NativeLive {
    param([string]$FilePath, [string[]]$ArgumentList)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $FilePath @ArgumentList 2>&1 | ForEach-Object { "$_" } | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousPreference
    }
}

# FUNCTION: ONE LINE OF GIT OUTPUT, OR "" WHEN GIT FAILS
function Get-GitLine {
    param([string[]]$ArgumentList)
    $result = Invoke-Native "git" $ArgumentList
    if ($result.Code -ne 0 -or @($result.Out).Count -eq 0) { return "" }
    return "$(@($result.Out)[0])".Trim()
}

# 1. FETCH; NO UNCOMMITTED CHANGE TO TRACKED FILES
$fetch = Invoke-Native "git" @("fetch", "--quiet", "origin")
if ($fetch.Code -ne 0) { Write-Host "STOP: git fetch failed: $($fetch.Text)"; exit 1 }
$status = Invoke-Native "git" @("status", "--porcelain", "--untracked-files=no")
if ($status.Code -ne 0) { Write-Host "STOP: git status failed: $($status.Text)"; exit 1 }
if (@($status.Out | Where-Object { $_.Trim() }).Count -gt 0) {
    Write-Host "STOP: uncommitted changes in $Workspace (commit, stash or discard them first):"
    $status.Out | ForEach-Object { Write-Host "  $_" }
    exit 1
}

# 2. HEAD = origin/main = THE DEPLOYED JUDGE
$head = Get-GitLine @("rev-parse", "HEAD")
$originMain = Get-GitLine @("rev-parse", "--verify", "origin/main^{commit}")
$statePath = Join-Path $DataRoot "store04_experiments\visible\state.json"
if (-not (Test-Path $statePath)) { Write-Host "STOP: no $statePath (is the runner up?)"; exit 1 }
try {
    $deployed = "$((Get-Content $statePath -Raw | ConvertFrom-Json).deployed_commit)".Trim()
} catch {
    Write-Host "STOP: cannot read deployed_commit from $statePath ($($_.Exception.Message))"
    exit 1
}
Write-Host "HEAD             $head"
Write-Host "origin/main      $originMain"
Write-Host "deployed_commit  $(if ($deployed) { $deployed } else { '(none)' })   ($statePath)"
if (-not $deployed) { Write-Host "STOP: nothing is deployed (state.json deployed_commit is empty)"; exit 1 }
if ($head -ne $originMain) {
    Write-Host "STOP: HEAD is not origin/main. Run: git checkout main; git pull --ff-only (or scripts\nico_merge.ps1)"
    exit 1
}
if ($head -ne $deployed) {
    Write-Host "STOP: HEAD is not the deployed commit. Deploy origin/main first (as so_runner):"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\deploy_runner.ps1 -ExpectCommit $originMain"
    Write-Host "  (if state.json was written before the deploy, wait for the runner's next heartbeat and run this again)"
    exit 1
}

# 3. THE DESIGN FOLDER
$folderRel = "experiments/$Experiment"
if (-not (Test-Path (Join-Path $Workspace "experiments\$Experiment\design.py"))) {
    Write-Host "STOP: experiments\$Experiment\design.py does not exist at $($head.Substring(0, 8))"
    exit 1
}

# 4. THE READINESS CHECK WITH THE TRIAL LOG (THE RUNNER'S PRE-REGISTRATION CHECK, BEFORE THE JOB EXISTS)
Write-Host ""
Write-Host "readiness check (scripts\check_experiment_ready.py --require-trial-log):"
$readyCode = Invoke-NativeLive $Python @("scripts\check_experiment_ready.py", $folderRel, "--require-trial-log")
if ($readyCode -ne 0) {
    Write-Host "STOP: the readiness check failed (exit $readyCode). Nothing queued."
    exit 1
}

# 5. THE DELIBERATE ACT: N IS SPENT WHEN THE JOB RUNS
Write-Host ""
Write-Host "About to queue $Experiment at $head"
Write-Host "  note: $Note"
$typed = Read-Host "HAND lines checked? Type the experiment name to queue it (anything else cancels)"
if ("$typed".Trim() -ne $Experiment) {
    Write-Host "CANCELLED: nothing queued."
    exit 1
}

# 6. ADD THE JOB AT HEAD, THEN CHECK ITS COMMIT
$add = Invoke-Native $Python @("scripts\run_queue.py", "add", $folderRel, "--commit", $head, "--note", $Note)
if ($add.Code -ne 0) {
    Write-Host "STOP: run_queue.py add failed (exit $($add.Code)):"
    Write-Host $add.Text
    exit 1
}
try {
    $job = (@($add.Out) -join "`n") | ConvertFrom-Json
} catch {
    Write-Host "WARNING: the job was probably added, but its output is not JSON:"
    Write-Host $add.Text
    exit 1
}
Write-Host ""
Write-Host "queued job $($job.job_id)"
Write-Host "  design $($job.design)"
Write-Host "  commit $($job.commit)"
if ("$($job.commit)" -ne $head) {
    Write-Host "WARNING: the job's commit is not HEAD ($head). Remove queue\pending\$($job.job_id).json before the runner takes it."
    exit 1
}
Write-Host "job commit = HEAD = origin/main = deployed commit"
