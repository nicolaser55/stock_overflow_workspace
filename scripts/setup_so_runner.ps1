# Stock Overflow: set up the so_runner Windows account and its queue task (Nicolas only, in an administrator PowerShell)
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_so_runner.ps1 `
#       -DataRoot D:\stock_overflow\data -RunnerWorkspace D:\stock_overflow\runner_workspace `
#       -NicolasWorkspace D:\stock_overflow\workspace -QuarantineRoot <quarantine folder> [-HoldoutPath <folder>] `
#       [-SmtpHost smtp.gmail.com -SmtpPort 587 -SmtpUser you@gmail.com -EmailTo you@gmail.com]
#
# so_runner is the only account that runs development runs and writes their results (audit S4, 2026-10-25).
# Agents (so_agent) only add jobs to store04_experiments\queue\pending. What this script does (it can be run again;
# it only adds or replaces so_runner's own entries):
#   1. Creates the local standard user so_runner if it does not exist (asks for a password).
#   2. Data root: read everything; store01-03 write and delete denied; store04_experiments modify (runs, trial log,
#      run index, queue, state).
#   3. Quarantine root and holdout results folder: every access denied.
#   4. Nicolas's workspace: read and run (venv-main), write denied.
#   5. The runner workspace (its own git clone; job worktrees go under .worktrees): full control.
#   6. User environment of so_runner: SO_DATA_PATH, SO_QUEUE_PYTHON (venv-main), and the SMTP settings when given
#      (the SMTP password is asked for and stored in so_runner's own environment only).
#   7. A scheduled task "SO queue runner" that starts "run_queue.py watch" as so_runner at system startup and
#      restarts it if it stops.
# Then, as so_runner (runas /user:so_runner powershell): clone the repository into the runner workspace and run
#   <NicolasWorkspace>\venv-main\Scripts\python.exe scripts\check_agent_access.py --role runner --quarantine <folder> --nicolas-workspace <folder>
# Every line must say OK. Then start the task once: Start-ScheduledTask -TaskName "SO queue runner".
#
# Undo: Unregister-ScheduledTask "SO queue runner"; icacls <folder> /remove:g so_runner /remove:d so_runner /T /C for
# each folder above; Remove-LocalUser so_runner.

param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$RunnerWorkspace,
    [Parameter(Mandatory = $true)][string]$NicolasWorkspace,
    [Parameter(Mandatory = $true)][string]$QuarantineRoot,
    [string]$HoldoutPath = "",
    [string]$SmtpHost = "",
    [string]$SmtpPort = "587",
    [string]$SmtpUser = "",
    [string]$EmailTo = ""
)

$ErrorActionPreference = "Stop"
$Runner = "so_runner"
$TaskName = "SO queue runner"

# REQUIRE AN ADMINISTRATOR SHELL
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script in an administrator PowerShell."
}

# REQUIRE THE FOLDERS THAT MUST EXIST
foreach ($folder in @($DataRoot, $NicolasWorkspace, $QuarantineRoot)) {
    if (-not (Test-Path $folder -PathType Container)) { throw "Folder not found: $folder" }
}
New-Item -ItemType Directory -Force -Path $RunnerWorkspace | Out-Null
$python = Join-Path $NicolasWorkspace "venv-main\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv-main not found: $python" }

# 1. THE ACCOUNT (THE PASSWORD IS ALSO NEEDED FOR THE SCHEDULED TASK)
$password = Read-Host -AsSecureString "Password for $Runner (new, or its current one)"
if (-not (Get-LocalUser -Name $Runner -ErrorAction SilentlyContinue)) {
    New-LocalUser -Name $Runner -Password $password -FullName "Stock Overflow runner" -Description "Runs queued development runs" -PasswordNeverExpires | Out-Null
    Add-LocalGroupMember -Group "Users" -Member $Runner
    Write-Host "created $Runner"
} else {
    Write-Host "$Runner exists"
}

# FUNCTION: RUN ICACLS AND STOP ON AN ERROR
function Set-Acl-Entry([string]$Path, [string[]]$Arguments) {
    & icacls $Path @Arguments /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $Path ($($Arguments -join ' '))" }
    Write-Host "icacls $Path $($Arguments -join ' ')"
}

# START FROM NO so_runner ENTRIES ON THESE FOLDERS
$experimentZone = Join-Path $DataRoot "store04_experiments"
New-Item -ItemType Directory -Force -Path (Join-Path $experimentZone "queue\pending") | Out-Null
foreach ($folder in @($DataRoot, $NicolasWorkspace, $QuarantineRoot, $RunnerWorkspace, $experimentZone)) {
    Set-Acl-Entry $folder @("/remove:g", $Runner, "/remove:d", $Runner)
}

# 2. DATA ROOT: READ EVERYTHING, WRITE store04_experiments
Set-Acl-Entry $DataRoot @("/grant", "${Runner}:(OI)(CI)RX")
foreach ($zone in @("store01_rawzone", "store02_workzone", "store03_goldzone")) {
    $zonePath = Join-Path $DataRoot $zone
    if (Test-Path $zonePath) { Set-Acl-Entry $zonePath @("/deny", "${Runner}:(OI)(CI)(W,D,DC)") }
}
Set-Acl-Entry $experimentZone @("/grant", "${Runner}:(OI)(CI)M")

# 3. QUARANTINE AND HOLDOUT RESULTS: NO ACCESS
Set-Acl-Entry $QuarantineRoot @("/deny", "${Runner}:(OI)(CI)F")
if ($HoldoutPath -ne "") {
    if (-not (Test-Path $HoldoutPath -PathType Container)) { throw "Folder not found: $HoldoutPath" }
    Set-Acl-Entry $HoldoutPath @("/remove:g", $Runner, "/remove:d", $Runner)
    Set-Acl-Entry $HoldoutPath @("/deny", "${Runner}:(OI)(CI)F")
}

# 4. NICOLAS'S WORKSPACE: READ AND RUN ONLY
Set-Acl-Entry $NicolasWorkspace @("/grant", "${Runner}:(OI)(CI)RX")
Set-Acl-Entry $NicolasWorkspace @("/deny", "${Runner}:(OI)(CI)(W,D,DC)")

# 5. THE RUNNER'S OWN CLONE
Set-Acl-Entry $RunnerWorkspace @("/grant", "${Runner}:(OI)(CI)F")

# 6. THE RUNNER'S ENVIRONMENT (USER VARIABLES OF so_runner, WRITTEN IN ITS REGISTRY HIVE)
$sid = (Get-LocalUser -Name $Runner).SID.Value
$hiveLoaded = $false
if (-not (Test-Path "Registry::HKEY_USERS\$sid")) {
    $profilePath = (Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $sid }).LocalPath
    if (-not $profilePath) {
        Write-Host "so_runner has no profile yet: log on once as so_runner (runas /user:so_runner cmd), then run this script again for step 6."
    } else {
        & reg load "HKU\$sid" (Join-Path $profilePath "NTUSER.DAT") | Out-Null
        $hiveLoaded = $true
    }
}
if (Test-Path "Registry::HKEY_USERS\$sid") {
    $envKey = "Registry::HKEY_USERS\$sid\Environment"
    Set-ItemProperty -Path $envKey -Name "SO_DATA_PATH" -Value $DataRoot
    Set-ItemProperty -Path $envKey -Name "SO_QUEUE_PYTHON" -Value $python
    foreach ($name in @("SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN")) {
        Remove-ItemProperty -Path $envKey -Name $name -ErrorAction SilentlyContinue
    }
    if ($SmtpHost -ne "") {
        $smtpSecret = Read-Host -AsSecureString "SMTP app password for $SmtpUser"
        $smtpPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($smtpSecret))
        Set-ItemProperty -Path $envKey -Name "SO_SMTP_HOST" -Value $SmtpHost
        Set-ItemProperty -Path $envKey -Name "SO_SMTP_PORT" -Value $SmtpPort
        Set-ItemProperty -Path $envKey -Name "SO_SMTP_USER" -Value $SmtpUser
        Set-ItemProperty -Path $envKey -Name "SO_SMTP_PASSWORD" -Value $smtpPlain
        Set-ItemProperty -Path $envKey -Name "SO_EMAIL_TO" -Value $EmailTo
        Write-Host "SMTP settings stored for $Runner"
    }
    Write-Host "SO_DATA_PATH=$DataRoot and SO_QUEUE_PYTHON=$python set for $Runner"
}
if ($hiveLoaded) { [gc]::Collect(); & reg unload "HKU\$sid" | Out-Null }

# 7. THE QUEUE TASK: run_queue.py watch AS so_runner AT STARTUP, RESTARTED IF IT STOPS
$plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))
$action = New-ScheduledTaskAction -Execute $python -Argument "-u scripts\run_queue.py watch" -WorkingDirectory $RunnerWorkspace
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $Runner -Password $plainPassword -RunLevel Limited | Out-Null
Write-Host "registered task '$TaskName' (starts at boot as $Runner; not started now)"

Write-Host ""
Write-Host "Done. Next, as so_runner (runas /user:so_runner powershell):"
Write-Host "  git clone https://github.com/nicolaser55/stock_overflow_workspace.git $RunnerWorkspace"
Write-Host "  cd $RunnerWorkspace"
Write-Host "  $python scripts\check_agent_access.py --role runner --quarantine $QuarantineRoot --nicolas-workspace $NicolasWorkspace"
Write-Host "Then, here: Start-ScheduledTask -TaskName '$TaskName'"
