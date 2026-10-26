# Stock Overflow: set up the so_agent Windows account (Nicolas only, in an administrator PowerShell)
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup_so_agent.ps1 `
#       -DataRoot D:\stock_overflow\data -AgentWorkspace D:\stock_overflow\agent_workspace `
#       -NicolasWorkspace D:\stock_overflow\workspace -QuarantineRoot <quarantine folder> [-HoldoutPath <folder>]
#
# What it does (it can be run again; it only adds or replaces so_agent's own entries):
#   1. Creates the local standard user so_agent if it does not exist (asks for a password).
#   2. Data root: so_agent may read everything and may write only store04_experiments\queue\pending (it adds jobs;
#      the runner account so_runner runs them and alone writes runs, the trial log and the run index).
#      store01_rawzone, store02_workzone and store03_goldzone: write and delete denied.
#   3. Quarantine root and holdout results folder: every access denied.
#   4. Nicolas's workspace: read and run (venv-main) allowed, write and delete denied. records\ is only read.
#   5. The agent workspace (its own git clone): full control.
#   6. Sets SO_DATA_PATH for so_agent; SO_QUARANTINE_PATH, SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set.
# Then, as so_agent (runas /user:so_agent powershell), from the agent workspace:
#   <NicolasWorkspace>\venv-main\Scripts\python.exe -m ipykernel install --user --name venv-main   (the notebook test)
#   <NicolasWorkspace>\venv-main\Scripts\python.exe scripts\check_agent_access.py --quarantine <folder> --nicolas-workspace <folder>
# Every line must say OK.
#
# Undo: icacls <folder> /remove:g so_agent /remove:d so_agent /T /C for each folder above, then
# Remove-LocalUser so_agent.

param(
    [Parameter(Mandatory = $true)][string]$DataRoot,
    [Parameter(Mandatory = $true)][string]$AgentWorkspace,
    [Parameter(Mandatory = $true)][string]$NicolasWorkspace,
    [Parameter(Mandatory = $true)][string]$QuarantineRoot,
    [string]$HoldoutPath = ""
)

$ErrorActionPreference = "Stop"
$Agent = "so_agent"

# REQUIRE AN ADMINISTRATOR SHELL
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script in an administrator PowerShell."
}

# REQUIRE THE FOLDERS THAT MUST EXIST
foreach ($folder in @($DataRoot, $NicolasWorkspace, $QuarantineRoot)) {
    if (-not (Test-Path $folder -PathType Container)) { throw "Folder not found: $folder" }
}
New-Item -ItemType Directory -Force -Path $AgentWorkspace | Out-Null

# 1. THE ACCOUNT
if (-not (Get-LocalUser -Name $Agent -ErrorAction SilentlyContinue)) {
    $password = Read-Host -AsSecureString "Password for $Agent"
    New-LocalUser -Name $Agent -Password $password -FullName "Stock Overflow agent" -Description "Runs agent sessions" -PasswordNeverExpires | Out-Null
    Add-LocalGroupMember -Group "Users" -Member $Agent
    Write-Host "created $Agent"
} else {
    Write-Host "$Agent exists"
}

# FUNCTION: RUN ICACLS AND STOP ON AN ERROR
function Set-Acl-Entry([string]$Path, [string[]]$Arguments) {
    & icacls $Path @Arguments /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "icacls failed on $Path ($($Arguments -join ' '))" }
    Write-Host "icacls $Path $($Arguments -join ' ')"
}

# START FROM NO so_agent ENTRIES ON THESE FOLDERS (store04 TOO: AN EARLIER VERSION GRANTED IT MODIFY THERE)
$experimentZone = Join-Path $DataRoot "store04_experiments"
$pendingFolder = Join-Path $experimentZone "queue\pending"
New-Item -ItemType Directory -Force -Path $pendingFolder | Out-Null
foreach ($folder in @($DataRoot, $NicolasWorkspace, $QuarantineRoot, $AgentWorkspace, $experimentZone, $pendingFolder)) {
    Set-Acl-Entry $folder @("/remove:g", $Agent, "/remove:d", $Agent)
}

# 2. DATA ROOT: READ EVERYTHING, WRITE ONLY THE PENDING QUEUE
Set-Acl-Entry $DataRoot @("/grant", "${Agent}:(OI)(CI)RX")
foreach ($zone in @("store01_rawzone", "store02_workzone", "store03_goldzone", "store04_experiments")) {
    $zonePath = Join-Path $DataRoot $zone
    if (Test-Path $zonePath) { Set-Acl-Entry $zonePath @("/deny", "${Agent}:(OI)(CI)(W,D,DC)") }
}
# THE PENDING FOLDER: CREATE AND WRITE NEW JOB FILES (THE store04 DENY ABOVE COVERS DELETE)
Set-Acl-Entry $pendingFolder @("/grant", "${Agent}:(OI)(CI)(RX,W)")

# 3. QUARANTINE AND HOLDOUT RESULTS: NO ACCESS
Set-Acl-Entry $QuarantineRoot @("/deny", "${Agent}:(OI)(CI)F")
if ($HoldoutPath -ne "") {
    if (-not (Test-Path $HoldoutPath -PathType Container)) { throw "Folder not found: $HoldoutPath" }
    Set-Acl-Entry $HoldoutPath @("/remove:g", $Agent, "/remove:d", $Agent)
    Set-Acl-Entry $HoldoutPath @("/deny", "${Agent}:(OI)(CI)F")
}

# 4. NICOLAS'S WORKSPACE: READ AND RUN ONLY
Set-Acl-Entry $NicolasWorkspace @("/grant", "${Agent}:(OI)(CI)RX")
Set-Acl-Entry $NicolasWorkspace @("/deny", "${Agent}:(OI)(CI)(W,D,DC)")

# 5. THE AGENT'S OWN CLONE
Set-Acl-Entry $AgentWorkspace @("/grant", "${Agent}:(OI)(CI)F")

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

Write-Host ""
Write-Host "Done. Next, as so_agent (runas /user:so_agent powershell): clone the repository into $AgentWorkspace, then from there run"
Write-Host "  $NicolasWorkspace\venv-main\Scripts\python.exe -m ipykernel install --user --name venv-main"
Write-Host "  $NicolasWorkspace\venv-main\Scripts\python.exe scripts\check_agent_access.py --quarantine $QuarantineRoot --nicolas-workspace $NicolasWorkspace"
