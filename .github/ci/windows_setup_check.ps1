# Stock Overflow: check both setup scripts on a throwaway Windows machine (CI only; roadmap R7, decided 2026-11-05)
#
# Run by the windows-setup job of .github/workflows/ci.yml on windows-latest, in Windows PowerShell 5.1 as the runner's
# administrator account. NEVER run it on nicodesktop: it creates the accounts so_runner and so_agent with random
# passwords, builds a fake tree under C:\so_ci and changes its ACLs.
#
#   1. A fake tree like nicodesktop's: C:\so_ci\{data, quarantine, holdout, archive, move_logs}, Nicolas's workspace (a
#      clone of the checkout with venv-main), the runner's and the agent's clones; a few fake files in the data root so
#      the access check has real files to try (no market data; the contents are placeholders).
#   2. setup_so_runner.ps1 (creates so_runner), one logon as so_runner (creates its profile), setup_so_runner.ps1 again
#      with -RegisterTask (environment, the task; a second run also checks the script can be run again).
#   3. setup_so_agent.ps1 the same way. so_agent gets "Log on as a batch job" here only, so this check can run as it
#      through a scheduled task; nicodesktop runs the check through runas instead and does not need the right.
#   4. The queue task starts as so_runner and must write visible\state.json and queue\logs\runner_watch.log; it is
#      stopped again.
#   5. The sample list is written by this (owner) account in control\; the access check runs as so_agent and as
#      so_runner. Every line must say OK.
# Exit 1 on any failure (each step throws).

param(
    [string]$Checkout = $env:GITHUB_WORKSPACE,
    [string]$Base = "C:\so_ci",
    [string]$OutFolder = "C:\so_ci_out"
)

$ErrorActionPreference = "Stop"
$Owner = $env:USERNAME
$DataRoot = Join-Path $Base "data"
$Quarantine = Join-Path $Base "quarantine"
$Holdout = Join-Path $Base "holdout"
$NicolasWorkspace = Join-Path $Base "workspace"
$RunnerWorkspace = Join-Path $Base "runner_workspace"
$AgentWorkspace = Join-Path $Base "agent_workspace"
$Python = Join-Path $NicolasWorkspace "venv-main\Scripts\python.exe"
$Zone = Join-Path $DataRoot "store04_experiments"

# FUNCTION: RUN A NATIVE COMMAND AND STOP ON A NON-ZERO EXIT (ITS STDERR, SUCH AS A pip NOTICE, IS NOT AN ERROR)
function Invoke-Native([string]$What, [scriptblock]$Block) {
    $ErrorActionPreference = "Continue"
    & $Block
    if ($LASTEXITCODE -ne 0) { throw "$What failed (exit $LASTEXITCODE)" }
}

# FUNCTION: A RANDOM PASSWORD THAT MEETS THE WINDOWS COMPLEXITY RULES; MASKED IN THE LOG
function New-Random-Password {
    $plain = "So!" + [guid]::NewGuid().ToString("N") + "aZ9"
    Write-Host "::add-mask::$plain"
    return $plain
}

# FUNCTION: RUN ONE COMMAND LINE AS ANOTHER ACCOUNT THROUGH A ONE-OFF SCHEDULED TASK; RETURN ITS EXIT CODE
function Invoke-As-User([string]$User, [string]$Plain, [string]$CommandLine, [int]$TimeoutSeconds = 900) {
    $name = "so_ci_" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    $action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $CommandLine"
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds $TimeoutSeconds)
    Register-ScheduledTask -TaskName $name -Action $action -Settings $settings -User $User -Password $Plain -RunLevel Limited | Out-Null
    Start-ScheduledTask -TaskName $name
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds + 60)
    # 267011 = HAS NOT RUN YET, 267009 = RUNNING
    do {
        Start-Sleep -Seconds 2
        $info = Get-ScheduledTaskInfo -TaskName $name
    } while ((@(267011, 267009) -contains $info.LastTaskResult) -and (Get-Date) -lt $deadline)
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    if (@(267011, 267009) -contains $info.LastTaskResult) { throw "the task as $User did not finish in time" }
    return [int]$info.LastTaskResult
}

# FUNCTION: GRANT "LOG ON AS A BATCH JOB" (THE SAME secedit STEPS AS setup_so_runner.ps1 STEP 7)
function Grant-Batch-Logon([string]$User) {
    $sid = (Get-LocalUser -Name $User).SID.Value
    $policyFile = Join-Path $env:TEMP "so_ci_rights.inf"
    $policyDb = Join-Path $env:TEMP "so_ci_rights.sdb"
    Invoke-Native "secedit export" { secedit /export /cfg $policyFile /areas USER_RIGHTS | Out-Null }
    $batchLine = Get-Content $policyFile | Where-Object { $_ -match "^SeBatchLogonRight\s*=" } | Select-Object -First 1
    $newLine = if ($batchLine) { "$($batchLine.TrimEnd()),*$sid" } else { "SeBatchLogonRight = *$sid" }
    Set-Content -Path $policyFile -Encoding Unicode -Value @("[Unicode]", "Unicode=yes", "[Version]", 'signature="$CHICAGO$"',
        "Revision=1", "[Privilege Rights]", $newLine)
    Invoke-Native "secedit configure" { secedit /configure /db $policyDb /cfg $policyFile /areas USER_RIGHTS | Out-Null }
    Remove-Item $policyFile, $policyDb -ErrorAction SilentlyContinue
    Write-Host "granted 'Log on as a batch job' to $User (CI only)"
}

# FUNCTION: RUN THE ACCESS CHECK AS AN ACCOUNT; PRINT ITS LINES; STOP UNLESS EVERY LINE SAYS OK
function Invoke-Access-Check([string]$User, [string]$Plain, [string]$Workspace, [string]$Role) {
    $outFile = Join-Path $OutFolder "access_$Role.txt"
    $line = "cd /d $Workspace && $Python scripts\check_agent_access.py --role $Role --sample-list $DataRoot\control\access_samples.txt " +
            "--quarantine $Quarantine --holdout $Holdout --nicolas-workspace $NicolasWorkspace > $outFile 2>&1"
    $exitCode = Invoke-As-User $User $Plain $line
    Write-Host "=== access check as $User (role $Role), exit $exitCode ==="
    $textList = @(Get-Content $outFile)
    $textList | ForEach-Object { Write-Host $_ }
    $failList = @($textList | Where-Object { $_ -notmatch "^OK " })
    if ($exitCode -ne 0 -or $failList.Count -gt 0 -or $textList.Count -lt 20) { throw "access check as $User failed" }
    Write-Host "access check as ${User}: $($textList.Count) checks OK"
}

# 1. THE FAKE TREE
Write-Host "=== 1. fake tree under $Base ==="
foreach ($folder in @($Quarantine, $Holdout, (Join-Path $Base "archive"), (Join-Path $Base "move_logs"), $OutFolder,
                      (Join-Path $DataRoot "store01_rawzone\SPY"), (Join-Path $DataRoot "store02_workzone\features"),
                      (Join-Path $DataRoot "store03_goldzone\daily"), (Join-Path $Zone "runs\ci_run_1"),
                      (Join-Path $Zone "queue\done"), (Join-Path $Zone "queue\logs"), (Join-Path $Zone "checks"))) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}
$fakeFileDict = @{ "store01_rawzone\SPY\bars.csv" = "placeholder"; "store02_workzone\features\f.csv" = "placeholder";
                   "store03_goldzone\daily\d.csv" = "placeholder"; "VIEW.json" = "{}"; "view_manifest.json" = "{}";
                   "store04_experiments\runs\ci_run_1\report.json" = "{}"; "store04_experiments\runs\ci_run_1\manifest.json" = "{}";
                   "store04_experiments\run_index.csv" = "run_id"; "store04_experiments\trial_log.csv" = "trial_id";
                   "store04_experiments\queue\done\ci_job.json" = "{}"; "store04_experiments\queue\logs\ci_run_1_attempt1.log" = "placeholder" }
foreach ($relative in $fakeFileDict.Keys) { Set-Content -Path (Join-Path $DataRoot $relative) -Value $fakeFileDict[$relative] }
# EVERY ACCOUNT MAY WRITE THE OUTPUT FOLDER (IT IS OUTSIDE THE TREE)
Invoke-Native "grant on $OutFolder" { icacls $OutFolder /grant "*S-1-1-0:(OI)(CI)M" | Out-Null }
# NICOLAS'S WORKSPACE, venv-main AND THE TWO CLONES
Invoke-Native "clone workspace" { git clone --quiet $Checkout $NicolasWorkspace }
Invoke-Native "clone runner workspace" { git clone --quiet $Checkout $RunnerWorkspace }
Invoke-Native "clone agent workspace" { git clone --quiet $Checkout $AgentWorkspace }
Invoke-Native "venv-main" { python -m venv (Join-Path $NicolasWorkspace "venv-main") }
Invoke-Native "pip" { & $Python -m pip install --quiet -r (Join-Path $NicolasWorkspace "requirements\ci_requirements.txt") }
Invoke-Native "editable install" { & $Python -m pip install --quiet -e $NicolasWorkspace --no-deps }

# 2. THE RUNNER ACCOUNT: CREATE, LOG ON ONCE (PROFILE), RUN AGAIN WITH THE TASK
Write-Host "=== 2. setup_so_runner.ps1 ==="
$runnerPlain = New-Random-Password
$runnerSecure = ConvertTo-SecureString $runnerPlain -AsPlainText -Force
$runnerArgs = @{ DataRoot = $DataRoot; RunnerWorkspace = $RunnerWorkspace; NicolasWorkspace = $NicolasWorkspace;
                 QuarantineRoot = $Quarantine; HoldoutPath = $Holdout; Owner = $Owner; AccountPassword = $runnerSecure }
& (Join-Path $Checkout "scripts\setup_so_runner.ps1") @runnerArgs
if ((Invoke-As-User "so_runner" $runnerPlain "whoami > $OutFolder\whoami_runner.txt") -ne 0) { throw "first logon as so_runner failed" }
& (Join-Path $Checkout "scripts\setup_so_runner.ps1") @runnerArgs -RegisterTask

# 3. THE AGENT ACCOUNT: THE SAME
Write-Host "=== 3. setup_so_agent.ps1 ==="
$agentPlain = New-Random-Password
$agentSecure = ConvertTo-SecureString $agentPlain -AsPlainText -Force
$agentArgs = @{ DataRoot = $DataRoot; AgentWorkspace = $AgentWorkspace; NicolasWorkspace = $NicolasWorkspace;
                QuarantineRoot = $Quarantine; HoldoutPath = $Holdout; Owner = $Owner; AccountPassword = $agentSecure }
& (Join-Path $Checkout "scripts\setup_so_agent.ps1") @agentArgs
Grant-Batch-Logon "so_agent"
if ((Invoke-As-User "so_agent" $agentPlain "whoami > $OutFolder\whoami_agent.txt") -ne 0) { throw "first logon as so_agent failed" }
& (Join-Path $Checkout "scripts\setup_so_agent.ps1") @agentArgs

# 4. THE QUEUE TASK RUNS AS so_runner: state.json AND THE WATCH LOG APPEAR
Write-Host "=== 4. the queue task ==="
Start-ScheduledTask -TaskName "SO queue runner"
$statePath = Join-Path $Zone "visible\state.json"
$watchLogPath = Join-Path $Zone "queue\logs\runner_watch.log"
$deadline = (Get-Date).AddSeconds(180)
while (-not ((Test-Path $statePath) -and (Test-Path $watchLogPath)) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
Stop-ScheduledTask -TaskName "SO queue runner"
if (-not (Test-Path $statePath)) { throw "the queue task wrote no state.json" }
if (-not (Select-String -Path $watchLogPath -Pattern "watch started" -Quiet)) { throw "runner_watch.log has no 'watch started'" }
Get-Content $statePath | ForEach-Object { Write-Host $_ }
Get-Content $watchLogPath | ForEach-Object { Write-Host $_ }

# 5. THE ACCESS CHECKS (SAMPLE LIST IN control\, WRITTEN BY THE OWNER)
Write-Host "=== 5. access checks ==="
$env:SO_DATA_PATH = $DataRoot
Invoke-Native "sample list" { & $Python (Join-Path $NicolasWorkspace "scripts\check_agent_access.py") --make-sample-list (Join-Path $DataRoot "control\access_samples.txt") }
Remove-Item Env:\SO_DATA_PATH
Invoke-Access-Check "so_agent" $agentPlain $AgentWorkspace "agent"
Invoke-Access-Check "so_runner" $runnerPlain $RunnerWorkspace "runner"
Write-Host "windows setup check passed"
