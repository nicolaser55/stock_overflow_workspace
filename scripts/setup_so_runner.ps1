# Stock Overflow: set up the so_runner Windows account (Nicolas only, in an administrator PowerShell)
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_so_runner.ps1 `
#       -DataRoot D:\stock_overflow\data -RunnerWorkspace D:\stock_overflow\runner_workspace `
#       -NicolasWorkspace D:\stock_overflow\workspace -QuarantineRoot D:\stock_overflow\quarantine `
#       [-HoldoutPath D:\stock_overflow\holdout] [-RegisterTask] `
#       [-SmtpHost smtp.gmail.com -SmtpPort 587 -SmtpUser you@gmail.com -EmailTo you@gmail.com]
#
# so_runner is the only account that runs development runs and writes their results (audit S4, 2026-10-25). This
# script reproduces the machine as it was rebuilt by hand on 2026-10-26 and checked on 2026-11-04 (roadmap R7): an
# ALLOW-LIST. No write-deny entries anywhere: a deny of icacls "W" also holds SYNCHRONIZE and READ_CONTROL and stops
# the account from opening any file (Python included); an account that is not granted something simply cannot do it.
# The only denies are full denies on the quarantine and the holdout (a full deny cannot half-block, and it guards
# against a later grant by mistake). It can be run again; it only adds, removes or replaces so_runner's own entries,
# the common root protection, and the control folder's list.
#
#   0. Saves the ACLs of the root and of its first level (icacls /save) into the ACL backup folder.
#   1. Creates the local standard user so_runner if it does not exist (asks for a password).
#   2. The root (the folder that holds the data root, D:\stock_overflow): inheritance from the drive removed, so the
#      drive's "Users" and "Authenticated Users" entries never reach it; nico, Administrators and SYSTEM full control,
#      inherited by everything below; so_runner may list this folder only.
#   3. Data root: read everything (inherited); store04_experiments: modify (runs, trial log, run index, queue,
#      visible\). The control folder (kill switch): its own list, not inherited: nico, Administrators and SYSTEM full
#      control, so_runner read (setup_so_agent.ps1 adds so_agent read). Only nico can create or remove STOP.
#   4. Quarantine root and holdout results folder: every access denied.
#   5. Nicolas's workspace (venv-main and the code it imports) and the base Python that venv-main points to (the "home"
#      line of venv-main\pyvenv.cfg): read and run.
#   6. The runner workspace (its own git clone; job worktrees go under .worktrees): full control, owned by so_runner
#      (git refuses a clone owned by another account).
#   7. The "Log on as a batch job" right (the scheduled task needs it).
#   8. User environment of so_runner: SO_DATA_PATH, SO_QUEUE_PYTHON (venv-main), no holdout variables; the SMTP
#      settings only when -SmtpHost is given (the password is asked for and stored in so_runner's environment only).
#   9. With -RegisterTask only: the scheduled task "SO queue runner" (run_queue.py watch as so_runner at startup,
#      restarted every 5 minutes if it stops, no time limit). Without it the existing task is left untouched.
#  10. Reads everything back and stops with an error when the machine differs from the above.
# Then, as so_runner (runas /user:so_runner powershell), from the runner workspace:
#   <NicolasWorkspace>\venv-main\Scripts\python.exe scripts\check_agent_access.py --role runner --sample-list <file> `
#       --quarantine <folder> --nicolas-workspace <folder> --holdout <folder>
# Every line must say OK.
#
# Undo: icacls D:\ /restore <AclBackupFolder>\acl_root_<timestamp>.txt restores the root's own ACL, and
# icacls <root> /restore <AclBackupFolder>\acl_root_children_<timestamp>.txt its first level;
# Unregister-ScheduledTask "SO queue runner"; icacls <folder> /remove:g so_runner /remove:d so_runner /T /C for each
# folder above; Remove-LocalUser so_runner.

param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$RunnerWorkspace,
    [Parameter(Mandatory = $true)][string]$NicolasWorkspace,
    [Parameter(Mandatory = $true)][string]$QuarantineRoot,
    [string]$HoldoutPath = "",
    [string]$Owner = "nico",
    [string]$AclBackupFolder = "",
    [switch]$RegisterTask,
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
$DataRoot = (Resolve-Path $DataRoot).Path.TrimEnd("\")
$Root = Split-Path $DataRoot -Parent
$python = Join-Path $NicolasWorkspace "venv-main\Scripts\python.exe"
if (-not (Test-Path $python)) { throw "venv-main not found: $python" }
$pyvenvLine = Get-Content (Join-Path $NicolasWorkspace "venv-main\pyvenv.cfg") | Where-Object { $_ -match "^\s*home\s*=" } | Select-Object -First 1
if (-not $pyvenvLine) { throw "no 'home' line in venv-main\pyvenv.cfg" }
$PythonHome = ($pyvenvLine -split "=", 2)[1].Trim()
if (-not (Test-Path (Join-Path $PythonHome "python.exe"))) { throw "base Python not found: $PythonHome" }
if ($AclBackupFolder -eq "") { $AclBackupFolder = Join-Path $Root "backup_records" }
New-Item -ItemType Directory -Force -Path $AclBackupFolder | Out-Null
New-Item -ItemType Directory -Force -Path $RunnerWorkspace | Out-Null
$experimentZone = Join-Path $DataRoot "store04_experiments"
$controlFolder = Join-Path $DataRoot "control"
New-Item -ItemType Directory -Force -Path (Join-Path $experimentZone "queue\pending") | Out-Null
New-Item -ItemType Directory -Force -Path $controlFolder | Out-Null

# FUNCTION: RUN ICACLS AND STOP ON AN ERROR
function Set-Acl-Entry([string]$Path, [string[]]$Arguments) {
    $output = & icacls $Path @Arguments /C 2>&1
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $Path ($($Arguments -join ' ')): $output" }
    Write-Host "icacls $Path $($Arguments -join ' ')"
}

# FUNCTION: THE ACCESS RULES OF ONE IDENTITY ON ONE PATH (EXPLICIT AND INHERITED)
function Get-Identity-Rule-List([string]$Path, [string]$Name) {
    $acl = Get-Acl -LiteralPath $Path
    return @($acl.Access | Where-Object { $_.IdentityReference.Value -match "\\$([regex]::Escape($Name))$" -or $_.IdentityReference.Value -eq $Name })
}

# FUNCTION: STOP WHEN AN IDENTITY HAS NO ALLOW ENTRY WITH THE GIVEN RIGHT BITS ON A PATH
function Assert-Allow-Entry([string]$Path, [string]$Name, [int64]$Mask, [string]$What) {
    $ruleList = @(Get-Identity-Rule-List $Path $Name | Where-Object {
        $_.AccessControlType -eq "Allow" -and ((([int64]$_.FileSystemRights) -band $Mask) -ne 0) })
    if ($ruleList.Count -eq 0) { throw "check failed: $Name cannot $What $Path" }
    Write-Host "checked: $Name can $What $Path"
}

# FUNCTION: STOP WHEN AN IDENTITY HAS A DENY THAT IS NOT A FULL DENY (A PARTIAL DENY CAN BLOCK OPENING FILES)
function Assert-No-Partial-Deny([string]$Path, [string]$Name) {
    $ruleList = @(Get-Identity-Rule-List $Path $Name | Where-Object {
        $_.AccessControlType -eq "Deny" -and $_.FileSystemRights -ne [Security.AccessControl.FileSystemRights]::FullControl })
    if ($ruleList.Count -gt 0) { throw "check failed: $Name has a partial deny on $Path" }
    Write-Host "checked: no partial deny of $Name on $Path"
}

# FUNCTION: STOP WHEN AN IDENTITY HAS NO FULL DENY ON A PATH
function Assert-Full-Deny([string]$Path, [string]$Name) {
    $ruleList = @(Get-Identity-Rule-List $Path $Name | Where-Object {
        $_.AccessControlType -eq "Deny" -and $_.FileSystemRights -eq [Security.AccessControl.FileSystemRights]::FullControl })
    if ($ruleList.Count -eq 0) { throw "check failed: $Name is not fully denied on $Path" }
    Write-Host "checked: $Name is fully denied on $Path"
}

# 0. SAVE THE ACLS OF THE ROOT AND ITS FIRST LEVEL (THE TREES BELOW INHERIT; setup_so_agent.ps1 SAVES THE DATA TREE)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$aclRootFile = Join-Path $AclBackupFolder "acl_root_$stamp.txt"
$aclChildFile = Join-Path $AclBackupFolder "acl_root_children_$stamp.txt"
& icacls $Root /save $aclRootFile /C /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls /save failed for $Root" }
& icacls "$Root\*" /save $aclChildFile /C /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls /save failed for $Root\*" }
Write-Host "saved the ACLs of $Root to $aclRootFile and of its first level to $aclChildFile"

# 1. THE ACCOUNT (THE PASSWORD IS ASKED FOR ONLY WHEN IT IS NEEDED: A NEW ACCOUNT, OR -RegisterTask)
$password = $null
if (-not (Get-LocalUser -Name $Runner -ErrorAction SilentlyContinue)) {
    $password = Read-Host -AsSecureString "Password for the new account $Runner"
    New-LocalUser -Name $Runner -Password $password -FullName "Stock Overflow runner" -Description "Runs queued development runs" -PasswordNeverExpires | Out-Null
    Add-LocalGroupMember -Group "Users" -Member $Runner
    Write-Host "created $Runner"
} else {
    Write-Host "$Runner exists"
}
$sid = (Get-LocalUser -Name $Runner).SID.Value

# 2. THE ROOT: NO INHERITANCE FROM THE DRIVE; OWNER, ADMINISTRATORS AND SYSTEM FULL CONTROL; so_runner LISTS IT ONLY.
# THE FULL-CONTROL GRANTS COME FIRST, SO REMOVING THE INHERITED ENTRIES CAN NEVER LOCK ANYONE OUT
foreach ($fullName in @($Owner, "*S-1-5-32-544", "*S-1-5-18")) {
    Set-Acl-Entry $Root @("/grant", "${fullName}:(OI)(CI)F")
}
Set-Acl-Entry $Root @("/inheritance:r")
foreach ($broad in @("*S-1-5-32-545", "*S-1-5-11", "*S-1-1-0")) {
    Set-Acl-Entry $Root @("/remove:g", $broad)
}
Set-Acl-Entry $Root @("/remove:g", $Runner, "/remove:d", $Runner)
Set-Acl-Entry $Root @("/grant", "${Runner}:RX")

# 3. DATA ROOT, store04_experiments, AND THE CONTROL FOLDER'S OWN LIST
foreach ($folder in @($DataRoot, $experimentZone, $controlFolder)) {
    Set-Acl-Entry $folder @("/remove:g", $Runner, "/remove:d", $Runner)
}
foreach ($zone in @("store01_rawzone", "store02_workzone", "store03_goldzone")) {
    $zonePath = Join-Path $DataRoot $zone
    if (Test-Path $zonePath) { Set-Acl-Entry $zonePath @("/remove:g", $Runner, "/remove:d", $Runner) }
}
Set-Acl-Entry $DataRoot @("/grant", "${Runner}:(OI)(CI)RX")
Set-Acl-Entry $experimentZone @("/grant", "${Runner}:(OI)(CI)M")
foreach ($fullName in @($Owner, "*S-1-5-32-544", "*S-1-5-18")) {
    Set-Acl-Entry $controlFolder @("/grant", "${fullName}:(OI)(CI)F")
}
Set-Acl-Entry $controlFolder @("/inheritance:r")
Set-Acl-Entry $controlFolder @("/grant", "${Runner}:(OI)(CI)RX")

# 4. QUARANTINE AND HOLDOUT RESULTS: NO ACCESS (A FULL DENY)
$deniedList = @($QuarantineRoot)
if ($HoldoutPath -ne "") {
    if (-not (Test-Path $HoldoutPath -PathType Container)) { throw "Folder not found: $HoldoutPath" }
    $deniedList += $HoldoutPath
}
foreach ($folder in $deniedList) {
    Set-Acl-Entry $folder @("/remove:g", $Runner, "/remove:d", $Runner)
    Set-Acl-Entry $folder @("/deny", "${Runner}:(OI)(CI)F")
}

# 5. NICOLAS'S WORKSPACE AND THE BASE PYTHON: READ AND RUN ONLY (NO WRITE GRANT, SO NO WRITE; NO DENY)
foreach ($folder in @($NicolasWorkspace, $PythonHome)) {
    Set-Acl-Entry $folder @("/remove:g", $Runner, "/remove:d", $Runner)
    Set-Acl-Entry $folder @("/grant", "${Runner}:(OI)(CI)RX")
}

# 6. THE RUNNER'S OWN CLONE, OWNED BY so_runner
Set-Acl-Entry $RunnerWorkspace @("/remove:d", $Runner)
Set-Acl-Entry $RunnerWorkspace @("/grant", "${Runner}:(OI)(CI)F")
Set-Acl-Entry $RunnerWorkspace @("/setowner", $Runner, "/T")

# 7. "LOG ON AS A BATCH JOB" (secedit: EXPORT, ADD THE SID WHEN MISSING, APPLY ONLY THE USER-RIGHTS AREA)
$policyFile = Join-Path $env:TEMP "so_runner_rights_$stamp.inf"
$policyDb = Join-Path $env:TEMP "so_runner_rights_$stamp.sdb"
& secedit /export /cfg $policyFile /areas USER_RIGHTS | Out-Null
$policyText = Get-Content $policyFile
$batchLine = $policyText | Where-Object { $_ -match "^SeBatchLogonRight\s*=" } | Select-Object -First 1
if ($batchLine -and ($batchLine -match "(^|[=,]\s*)(\*$sid|$Runner)(\s*,|\s*$)")) {
    Write-Host "$Runner already has 'Log on as a batch job'"
} else {
    $newLine = if ($batchLine) { "$($batchLine.TrimEnd()),*$sid" } else { "SeBatchLogonRight = *$sid" }
    $rightsText = @("[Unicode]", "Unicode=yes", "[Version]", 'signature="$CHICAGO$"', "Revision=1", "[Privilege Rights]", $newLine)
    Set-Content -Path $policyFile -Value $rightsText -Encoding Unicode
    & secedit /configure /db $policyDb /cfg $policyFile /areas USER_RIGHTS | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "secedit could not grant 'Log on as a batch job' to $Runner" }
    Write-Host "granted 'Log on as a batch job' to $Runner"
}
Remove-Item $policyFile, $policyDb -ErrorAction SilentlyContinue

# 8. THE RUNNER'S ENVIRONMENT (USER VARIABLES OF so_runner, WRITTEN IN ITS REGISTRY HIVE)
$hiveLoaded = $false
if (-not (Test-Path "Registry::HKEY_USERS\$sid")) {
    $profilePath = (Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $sid }).LocalPath
    if (-not $profilePath) {
        Write-Host "so_runner has no profile yet: log on once as so_runner (runas /user:so_runner cmd), then run this script again for step 8."
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
    } else {
        $smtpNameList = @((Get-Item $envKey).Property | Where-Object { $_ -like "SO_SMTP_*" -or $_ -eq "SO_EMAIL_TO" })
        Write-Host "SMTP settings left as they are ($($smtpNameList.Count) of 5 present; pass -SmtpHost to change them)"
    }
    Write-Host "SO_DATA_PATH=$DataRoot and SO_QUEUE_PYTHON=$python set for $Runner"
}
if ($hiveLoaded) { [gc]::Collect(); & reg unload "HKU\$sid" | Out-Null }

# 9. THE QUEUE TASK (ONLY WITH -RegisterTask)
if ($RegisterTask) {
    if ($null -eq $password) { $password = Read-Host -AsSecureString "Password of $Runner (for the scheduled task)" }
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($password))
    $action = New-ScheduledTaskAction -Execute $python -Argument "-u scripts\run_queue.py watch" -WorkingDirectory $RunnerWorkspace
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -User $Runner -Password $plainPassword -RunLevel Limited | Out-Null
    Write-Host "registered task '$TaskName' (starts at boot as $Runner; not started now: Start-ScheduledTask -TaskName '$TaskName')"
} else {
    $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $existingTask) {
        Write-Host "warning: no task '$TaskName'; run this script again with -RegisterTask"
    } else {
        Write-Host "task '$TaskName' left untouched (state $($existingTask.State)); pass -RegisterTask to recreate it"
    }
}

# 10. READ BACK
$rootRuleList = @((Get-Acl -LiteralPath $Root).Access)
if (@($rootRuleList | Where-Object { $_.IsInherited }).Count -gt 0) { throw "check failed: $Root still inherits entries from the drive" }
foreach ($broad in @("Users", "Authenticated Users", "Everyone")) {
    if ((Get-Identity-Rule-List $Root $broad).Count -gt 0) { throw "check failed: $broad has an entry on $Root" }
}
Write-Host "checked: $Root inherits nothing and gives Users, Authenticated Users and Everyone nothing"
Assert-Allow-Entry $Root $Owner 0x40000 "fully control"
Assert-Allow-Entry $Root $Runner 0x1 "list"
Assert-Allow-Entry $DataRoot $Runner 0x1 "read"
Assert-Allow-Entry (Join-Path $DataRoot "store01_rawzone") $Runner 0x1 "read"
Assert-Allow-Entry $experimentZone $Runner 0x2 "write"
Assert-Allow-Entry $controlFolder $Runner 0x1 "read"
Assert-Allow-Entry $controlFolder $Owner 0x40000 "fully control"
if (@((Get-Acl -LiteralPath $controlFolder).Access | Where-Object { $_.IsInherited }).Count -gt 0) { throw "check failed: $controlFolder inherits entries" }
if (@(Get-Identity-Rule-List $controlFolder $Runner | Where-Object { $_.AccessControlType -eq "Allow" -and ((([int64]$_.FileSystemRights) -band 0x2) -ne 0) }).Count -gt 0) {
    throw "check failed: $Runner can write $controlFolder"
}
Write-Host "checked: $Runner cannot write $controlFolder"
Assert-Allow-Entry $NicolasWorkspace $Runner 0x1 "read"
Assert-Allow-Entry $PythonHome $Runner 0x20 "run programs in"
Assert-Allow-Entry $RunnerWorkspace $Runner 0x40000 "fully control"
if ((Get-Acl -LiteralPath $RunnerWorkspace).Owner -notmatch "\\$Runner$") { throw "check failed: $RunnerWorkspace is not owned by $Runner" }
Write-Host "checked: $RunnerWorkspace is owned by $Runner"
foreach ($folder in @($Root, $DataRoot, $experimentZone, $controlFolder, $NicolasWorkspace, $PythonHome, $RunnerWorkspace)) {
    Assert-No-Partial-Deny $folder $Runner
}
foreach ($folder in $deniedList) { Assert-Full-Deny $folder $Runner }

Write-Host ""
Write-Host "Done. Then, as so_runner (runas /user:so_runner powershell), from $RunnerWorkspace :"
Write-Host "  $python scripts\check_agent_access.py --role runner --sample-list <file> --quarantine $QuarantineRoot --nicolas-workspace $NicolasWorkspace$(if ($HoldoutPath -ne '') { " --holdout $HoldoutPath" })"
