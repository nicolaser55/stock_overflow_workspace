# Stock Overflow: set up the so_agent Windows account (Nicolas only, in an administrator PowerShell)
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_so_agent.ps1 `
#       -DataRoot D:\stock_overflow\data -AgentWorkspace D:\stock_overflow\agent_workspace `
#       -NicolasWorkspace D:\stock_overflow\workspace -QuarantineRoot <quarantine folder> [-HoldoutPath <folder>] `
#       [-AclBackupFolder D:\stock_overflow\backup_records] [-Owner nico]
#
# -Owner names the account that keeps control of the data tree (nico; the Windows CI job passes its own account).
# -AccountPassword (a SecureString) answers the password question without a prompt; only the Windows CI job uses it
# (roadmap R7, 2026-11-08: throwaway accounts on a throwaway machine). On nicodesktop leave it out and type the password.
#
# Results visible only as grades (roadmap R4, 2026-11-03), on the allow-list model of the machine (rebuilt by hand on
# 2026-10-26, scripted on 2026-11-04, roadmap R7): so_agent can do only what it is granted. No write-deny entries: a
# deny of icacls "W" also holds SYNCHRONIZE and READ_CONTROL and stops the account from opening any file (Python
# included). The only denies are full denies on the quarantine and the holdout. Run scripts\setup_so_runner.ps1 first:
# it removes the drive's inheritance from the root that holds the data root, which this script checks.
# What it does (it can be run again; it only adds, removes or replaces entries of so_agent and of the two reader
# groups, and never touches nico, Administrators, SYSTEM or so_runner):
#   0. Saves the current ACLs of the data root tree (icacls /save) into the ACL backup folder, outside the data root.
#   1. Creates the local standard user so_agent if it does not exist (asks for a password), and the local groups
#      so_grade_readers (the planner reads grades) and so_status_readers (the coder reads technical status). In stage 1
#      so_agent is a member of both (one account for planner and coder, decided 2026-11-03); R5 gives the planner its own
#      account and changes only the memberships. A new membership takes effect at so_agent's next logon.
#   2. Data root: so_agent loses every entry on the data root and on store01-store04 (no read of market data, runs,
#      the trial log, the run index, the queue folders, checks, VIEW.json). It keeps, by explicit grants:
#        store04_experiments\queue\pending      read, list and create files (it adds jobs; it cannot delete or rename)
#        store04_experiments\visible            so_grade_readers and so_status_readers: read this folder and the files
#                                               directly in it (state.json), not grades\ or status\ (no propagation)
#        store04_experiments\visible\grades     so_grade_readers: read (one grade per run, no numbers)
#        store04_experiments\visible\status     so_status_readers: read (one technical status per job, no numbers)
#        control                                read (the kill switch STOP); the control folder's own list is not
#                                               otherwise changed, so only nico can write it
#      Parents need no grant: "bypass traverse checking" (on for every user by default) lets an account open a granted
#      folder below folders it cannot list.
#   3. Quarantine root and holdout results folder: every access denied (a full deny).
#   4. The root (D:\stock_overflow): list this folder only. Nicolas's workspace (venv-main and the code it imports) and
#      the base Python venv-main points to (the "home" line of venv-main\pyvenv.cfg): read and run, nothing else (no
#      write grant, so no write; no deny).
#   5. The agent workspace (its own git clone): full control, owned by so_agent (git refuses a clone owned by another
#      account).
#   6. Sets SO_DATA_PATH for so_agent; SO_QUARANTINE_PATH, SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set.
#   7. Reads the ACLs back and stops with an error when an expected entry is missing, so_agent still has an entry where
#      it must have none, or it has a deny other than the two full denies.
# Then (see the end of the script for the exact lines):
#   as nico:      venv-main\Scripts\python.exe scripts\check_agent_access.py --make-sample-list <DataRoot>\control\access_samples.txt
#   as so_agent:  runas /user:so_agent powershell, then from the agent workspace
#                 <NicolasWorkspace>\venv-main\Scripts\python.exe scripts\check_agent_access.py --sample-list <that file> ...
#   as so_runner: the same check with --role runner
#   as nico:      remove the sample list
# Every line must say OK. The sample list (paths of real files, no contents) goes in the control folder: both accounts
# can read it, only nico can write it, and it never lands in a git clone (it was left in the agent's clone until
# 2026-11-08).
#
# Undo: icacls <DataRoot parent> /restore <AclBackupFolder>\acl_data_<timestamp>.txt restores the saved data-root tree;
# or, entry by entry, icacls <folder> /remove:g so_agent /remove:d so_agent /T /C for each folder above (and the same
# for so_grade_readers and so_status_readers); then Remove-LocalGroup so_grade_readers, so_status_readers and
# Remove-LocalUser so_agent.

param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$AgentWorkspace,
    [Parameter(Mandatory = $true)][string]$NicolasWorkspace,
    [Parameter(Mandatory = $true)][string]$QuarantineRoot,
    [string]$HoldoutPath = "",
    [string]$AclBackupFolder = "",
    [string]$Owner = "nico",
    [SecureString]$AccountPassword = $null
)

$ErrorActionPreference = "Stop"
$Agent = "so_agent"
$GradeGroup = "so_grade_readers"
$StatusGroup = "so_status_readers"

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
$pyvenvLine = Get-Content (Join-Path $NicolasWorkspace "venv-main\pyvenv.cfg") | Where-Object { $_ -match "^\s*home\s*=" } | Select-Object -First 1
if (-not $pyvenvLine) { throw "no 'home' line in venv-main\pyvenv.cfg" }
$PythonHome = ($pyvenvLine -split "=", 2)[1].Trim()
if (-not (Test-Path (Join-Path $PythonHome "python.exe"))) { throw "base Python not found: $PythonHome" }
if (@((Get-Acl -LiteralPath $Root).Access | Where-Object { $_.IsInherited }).Count -gt 0) {
    throw "$Root still inherits entries from the drive: run scripts\setup_so_runner.ps1 first"
}
if ($AclBackupFolder -eq "") { $AclBackupFolder = Join-Path (Split-Path $DataRoot -Parent) "backup_records" }
New-Item -ItemType Directory -Force -Path $AclBackupFolder | Out-Null
$AclBackupFolder = (Resolve-Path $AclBackupFolder).Path.TrimEnd("\")
if (($AclBackupFolder + "\").StartsWith($DataRoot + "\", [StringComparison]::OrdinalIgnoreCase)) {
    throw "The ACL backup folder must be outside the data root: $AclBackupFolder"
}
New-Item -ItemType Directory -Force -Path $AgentWorkspace | Out-Null

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

# FUNCTION: STOP WHEN AN IDENTITY HAS ANY ENTRY ON A PATH
function Assert-No-Entry([string]$Path, [string]$Name) {
    $ruleList = Get-Identity-Rule-List $Path $Name
    if ($ruleList.Count -gt 0) { throw "check failed: $Name still has an entry on $Path" }
    Write-Host "checked: $Name has no entry on $Path"
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

# FUNCTION: STOP WHEN AN IDENTITY HAS NO ALLOW ENTRY WITH READ ON A PATH
function Assert-Read-Entry([string]$Path, [string]$Name) {
    $ruleList = @(Get-Identity-Rule-List $Path $Name | Where-Object {
        $_.AccessControlType -eq "Allow" -and ((([int64]$_.FileSystemRights) -band 0x80000001) -ne 0) })
    if ($ruleList.Count -eq 0) { throw "check failed: $Name cannot read $Path" }
    Write-Host "checked: $Name can read $Path"
}

# 0. SAVE THE CURRENT ACLS OF THE DATA ROOT TREE (icacls /restore ON THE PARENT PUTS THEM BACK)
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$aclSaveFile = Join-Path $AclBackupFolder "acl_data_$stamp.txt"
& icacls $DataRoot /save $aclSaveFile /T /C /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls /save failed for $DataRoot" }
Write-Host "saved the ACLs of $DataRoot to $aclSaveFile"

# 1. THE ACCOUNT AND THE TWO READER GROUPS
if (-not (Get-LocalUser -Name $Agent -ErrorAction SilentlyContinue)) {
    $password = $AccountPassword
    if ($null -eq $password) { $password = Read-Host -AsSecureString "Password for $Agent" }
    New-LocalUser -Name $Agent -Password $password -FullName "Stock Overflow agent" -Description "Runs agent sessions" -PasswordNeverExpires | Out-Null
    Add-LocalGroupMember -Group "Users" -Member $Agent
    Write-Host "created $Agent"
} else {
    Write-Host "$Agent exists"
}
# A LOCAL GROUP DESCRIPTION MAY HOLD AT MOST 48 CHARACTERS
foreach ($group in @(@($GradeGroup, "SO: may read graded summaries (planner)"),
                     @($StatusGroup, "SO: may read technical status (coder)"))) {
    if (-not (Get-LocalGroup -Name $group[0] -ErrorAction SilentlyContinue)) {
        New-LocalGroup -Name $group[0] -Description $group[1] | Out-Null
        Write-Host "created group $($group[0])"
    }
    $memberList = @(Get-LocalGroupMember -Group $group[0] | Where-Object { $_.Name -match "\\$Agent$" })
    if ($memberList.Count -eq 0) {
        Add-LocalGroupMember -Group $group[0] -Member $Agent
        Write-Host "added $Agent to $($group[0])"
    }
}

# THE FOLDERS (THE RUNNER CREATES THE SAME ONES; HERE THEY MUST EXIST BEFORE THEIR GRANTS)
$experimentZone = Join-Path $DataRoot "store04_experiments"
$pendingFolder = Join-Path $experimentZone "queue\pending"
$visibleFolder = Join-Path $experimentZone "visible"
$gradeFolder = Join-Path $visibleFolder "grades"
$statusFolder = Join-Path $visibleFolder "status"
$controlFolder = Join-Path $DataRoot "control"
foreach ($folder in @($pendingFolder, $gradeFolder, $statusFolder, $controlFolder)) {
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
}

# 2. START FROM NO so_agent AND NO GROUP ENTRIES ON THE DATA TREE'S FOLDERS (THE BROAD READ GRANT GOES HERE)
$zoneList = @(@("store01_rawzone", "store02_workzone", "store03_goldzone", "store04_experiments") |
    ForEach-Object { Join-Path $DataRoot $_ } | Where-Object { Test-Path $_ })
foreach ($folder in @($DataRoot) + $zoneList + @($pendingFolder, $visibleFolder, $gradeFolder, $statusFolder)) {
    Set-Acl-Entry $folder @("/remove:g", $Agent, "/remove:d", $Agent)
    Set-Acl-Entry $folder @("/remove:g", $GradeGroup)
    Set-Acl-Entry $folder @("/remove:g", $StatusGroup)
}
foreach ($folder in @($Root, $NicolasWorkspace, $PythonHome, $QuarantineRoot, $AgentWorkspace)) {
    Set-Acl-Entry $folder @("/remove:g", $Agent, "/remove:d", $Agent)
}

# 2. THE ONLY GRANTS IN THE DATA ROOT
Set-Acl-Entry $pendingFolder @("/grant", "${Agent}:(OI)(CI)(RX,W)")
# (OI)(NP): THIS FOLDER AND THE FILES DIRECTLY IN IT ONLY. A PLAIN (OI) ENTRY WOULD ALSO REACH THE FILES INSIDE grades\ AND
# status\ (WINDOWS PASSES IT TO SUBFOLDERS AS INHERIT-ONLY), SO EACH GROUP COULD READ THE OTHER'S FOLDER
Set-Acl-Entry $visibleFolder @("/grant", "${GradeGroup}:(OI)(NP)RX")
Set-Acl-Entry $visibleFolder @("/grant", "${StatusGroup}:(OI)(NP)RX")
Set-Acl-Entry $gradeFolder @("/grant", "${GradeGroup}:(OI)(CI)RX")
Set-Acl-Entry $statusFolder @("/grant", "${StatusGroup}:(OI)(CI)RX")
# THE KILL SWITCH MUST STAY READABLE: A FLAG THE AGENT CANNOT SEE WOULD LOOK LIKE "NOT SET" TO A CARELESS CHECK
Set-Acl-Entry $controlFolder @("/grant", "${Agent}:(OI)(CI)RX")

# 3. QUARANTINE AND HOLDOUT RESULTS: NO ACCESS (A FULL DENY)
Set-Acl-Entry $QuarantineRoot @("/deny", "${Agent}:(OI)(CI)F")
if ($HoldoutPath -ne "") {
    if (-not (Test-Path $HoldoutPath -PathType Container)) { throw "Folder not found: $HoldoutPath" }
    Set-Acl-Entry $HoldoutPath @("/remove:g", $Agent, "/remove:d", $Agent)
    Set-Acl-Entry $HoldoutPath @("/deny", "${Agent}:(OI)(CI)F")
}

# 4. THE ROOT (LIST THIS FOLDER ONLY), NICOLAS'S WORKSPACE AND THE BASE PYTHON (READ AND RUN ONLY). NO DENY: WITHOUT A
# WRITE GRANT THERE IS NO WRITE, AND A PARTIAL DENY CAN STOP THE ACCOUNT FROM OPENING FILES (FOUND 2026-10-26 AND AGAIN
# 2026-11-04)
Set-Acl-Entry $Root @("/grant", "${Agent}:RX")
Set-Acl-Entry $NicolasWorkspace @("/grant", "${Agent}:(OI)(CI)RX")
Set-Acl-Entry $PythonHome @("/grant", "${Agent}:(OI)(CI)RX")

# 5. THE AGENT'S OWN CLONE, OWNED BY so_agent
Set-Acl-Entry $AgentWorkspace @("/grant", "${Agent}:(OI)(CI)F")
Set-Acl-Entry $AgentWorkspace @("/setowner", $Agent, "/T")

# 6. THE AGENT'S ENVIRONMENT (USER VARIABLES OF so_agent, WRITTEN IN ITS REGISTRY HIVE)
$sid = (Get-LocalUser -Name $Agent).SID.Value
$hiveLoaded = $false
if (-not (Test-Path "Registry::HKEY_USERS\$sid")) {
    $profilePath = (Get-CimInstance Win32_UserProfile | Where-Object { $_.SID -eq $sid }).LocalPath
    if (-not $profilePath) {
        Write-Host "so_agent has no profile yet: log on once as so_agent (runas /user:so_agent cmd), then run this script again for step 6."
    } else {
        & reg load "HKU\$sid" (Join-Path $profilePath "NTUSER.DAT") | Out-Null
        $hiveLoaded = $true
    }
}
if (Test-Path "Registry::HKEY_USERS\$sid") {
    Set-ItemProperty -Path "Registry::HKEY_USERS\$sid\Environment" -Name "SO_DATA_PATH" -Value $DataRoot
    foreach ($name in @("SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN")) {
        Remove-ItemProperty -Path "Registry::HKEY_USERS\$sid\Environment" -Name $name -ErrorAction SilentlyContinue
    }
    Write-Host "SO_DATA_PATH=$DataRoot set for $Agent"
}
if ($hiveLoaded) { [gc]::Collect(); & reg unload "HKU\$sid" | Out-Null }

# 7. READ BACK: NO so_agent ENTRY WHERE IT MUST HAVE NONE (INHERITED ONES INCLUDED), THE GRANTS PRESENT, THE OTHERS KEPT
foreach ($path in @($DataRoot, $experimentZone, (Join-Path $experimentZone "runs"), (Join-Path $experimentZone "queue"),
                    (Join-Path $experimentZone "queue\done"), (Join-Path $experimentZone "queue\failed")) + $zoneList) {
    if (Test-Path $path) { Assert-No-Entry $path $Agent }
}
foreach ($fileName in @("trial_log.csv", "run_index.csv", "state.json")) {
    $filePath = Join-Path $experimentZone $fileName
    if (Test-Path $filePath) { Assert-No-Entry $filePath $Agent }
}
foreach ($pair in @(@($pendingFolder, $Agent), @($visibleFolder, $GradeGroup), @($visibleFolder, $StatusGroup),
                    @($gradeFolder, $GradeGroup), @($statusFolder, $StatusGroup), @($controlFolder, $Agent))) {
    Assert-Read-Entry $pair[0] $pair[1]
}
foreach ($path in @($Root, $NicolasWorkspace, $PythonHome)) { Assert-Read-Entry $path $Agent }
foreach ($path in @($Root, $NicolasWorkspace, $PythonHome, $AgentWorkspace, $pendingFolder, $controlFolder)) {
    Assert-No-Partial-Deny $path $Agent
}
$deniedList = @($QuarantineRoot) + $(if ($HoldoutPath -ne "") { @($HoldoutPath) } else { @() })
foreach ($path in $deniedList) { Assert-Full-Deny $path $Agent }
if ((Get-Acl -LiteralPath $AgentWorkspace).Owner -notmatch "\\$Agent$") { throw "check failed: $AgentWorkspace is not owned by $Agent" }
Write-Host "checked: $AgentWorkspace is owned by $Agent"
Assert-No-Entry $gradeFolder $StatusGroup
Assert-No-Entry $statusFolder $GradeGroup
foreach ($path in @($DataRoot, $experimentZone, $visibleFolder, $controlFolder)) {
    Assert-Read-Entry $path $Owner
}
foreach ($path in @($DataRoot, $experimentZone, $visibleFolder)) {
    if (@(Get-Identity-Rule-List $path "so_runner").Count -eq 0) {
        Write-Host "warning: so_runner has no entry on $path; run scripts\setup_so_runner.ps1 before the runner starts"
    }
}

Write-Host ""
Write-Host "Done. so_agent's new group memberships apply from its next logon (close every so_agent window first)."
$sampleList = Join-Path $controlFolder "access_samples.txt"
Write-Host "Next, as nico (this PowerShell, not elevated is fine), from your workspace:"
Write-Host "  $NicolasWorkspace\venv-main\Scripts\python.exe scripts\check_agent_access.py --make-sample-list $sampleList"
Write-Host "Then as so_agent (runas /user:so_agent powershell), from the agent workspace:"
Write-Host "  $NicolasWorkspace\venv-main\Scripts\python.exe scripts\check_agent_access.py --sample-list $sampleList --quarantine $QuarantineRoot --nicolas-workspace $NicolasWorkspace$(if ($HoldoutPath -ne '') { " --holdout $HoldoutPath" })"
Write-Host "And as so_runner: the same line with --role runner. Then, as nico: Remove-Item $sampleList"
