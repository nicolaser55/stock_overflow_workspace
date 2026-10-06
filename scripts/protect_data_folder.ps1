<#
Protect The Existing Files Of The Data Folder (run ONCE by Nicolas, before the autonomous agent starts)

What it does (Windows NTFS permissions for the current user, who is also the user the Cursor agent runs as):
    1. Every file and folder that exists NOW in the data folder gets an explicit "deny Delete" and "deny Delete child"
       entry: it can be read and (where allowed) written, but not deleted, moved or renamed.
       The entries are not inherited, so files and folders created LATER (by the agent or a notebook) stay fully
       modifiable and deletable.
    2. The raw data and the pipeline caches of steps 00-05 additionally get "deny Write": they become read-only.
    3. A test file proves the result: it cannot be deleted but can still be written.

Limits: this protects against mistakes, not against a determined process running as the same user (the owner of a
file can change its permissions back). The agent's rules forbid changing permissions.

Undo (removes every deny entry of the current user under the data folder, e.g. before cleaning up yourself):
    icacls "C:\Users\nico\Desktop\stock_overflow_data" /remove:d "$env:USERDOMAIN\$env:USERNAME" /T /C /Q

Usage (PowerShell, from the workspace folder; takes a few minutes for ~40,000 files):
    powershell -ExecutionPolicy Bypass -File scripts\protect_data_folder.ps1
#>
param([string]$DataPath = "C:\Users\nico\Desktop\stock_overflow_data")

# STOP AT THE FIRST ERROR
$ErrorActionPreference = "Stop"
# DEFINE THE ACCOUNT THE AGENT RUNS AS (THE CURRENT USER)
$Account = "$env:USERDOMAIN\$env:USERNAME"
# CHECK THAT THE DATA FOLDER EXISTS
if (-not (Test-Path $DataPath)) { throw "Data folder not found: $DataPath" }
# DEFINE THE TEST FILE (CREATED BEFORE THE PROTECTION, SO IT IS PROTECTED LIKE EVERY EXISTING FILE)
$TestFile = Join-Path $DataPath "store04_experiments\_protection_test.txt"
# CREATE THE TEST FILE
New-Item -ItemType Directory -Force (Split-Path $TestFile) | Out-Null
Set-Content -Path $TestFile -Value "protection test, created $(Get-Date -Format s)"

# DISPLAY INFORMATION
Write-Host "Denying delete on every existing file and folder of $DataPath for $Account ..."
# DENY DELETE (DE) AND DELETE CHILD (DC) ON EVERYTHING THAT EXISTS NOW (NO INHERITANCE FLAGS: NEW FILES ARE NOT AFFECTED)
icacls $DataPath /deny "${Account}:(DE,DC)" /T /C /Q
# CHECK THE RESULT OF ICACLS
if ($LASTEXITCODE -ne 0) { throw "icacls failed (delete protection), exit code $LASTEXITCODE" }

# DEFINE THE FOLDERS THAT ARE NEVER REWRITTEN (RAW DATA AND PIPELINE CACHES OF STEPS 00-05)
$ReadOnlyList = @(
    "store01_rawzone",
    "store02_workzone\step00_data_quality_report",
    "store02_workzone\step01_PA_ohlcv_data",
    "store02_workzone\step02_TSIND_data",
    "store02_workzone\step03_TSSEG_data",
    "store02_workzone\step04_TSCTX_data",
    "store03_goldzone\step05_TSBAR_data"
)
# ITERATE OVER THE READ-ONLY FOLDERS
foreach ($Folder in $ReadOnlyList) {
    # DEFINE THE FOLDER PATH
    $FolderPath = Join-Path $DataPath $Folder
    # SKIP A FOLDER THAT DOES NOT EXIST
    if (-not (Test-Path $FolderPath)) { Write-Host "Not found (skipped): $FolderPath"; continue }
    # DISPLAY INFORMATION
    Write-Host "Making read-only: $FolderPath"
    # DENY WRITE (W) ON THE FOLDER AND EVERYTHING IN IT
    icacls $FolderPath /deny "${Account}:(W)" /T /C /Q
    # CHECK THE RESULT OF ICACLS
    if ($LASTEXITCODE -ne 0) { throw "icacls failed (read-only) on $FolderPath, exit code $LASTEXITCODE" }
}

# TEST 1: THE EXISTING TEST FILE MUST NOT BE DELETABLE
$DeleteBlockedBool = $false
try { Remove-Item -Path $TestFile -ErrorAction Stop } catch { $DeleteBlockedBool = $true }
# TEST 2: THE EXISTING TEST FILE MUST STILL BE OVERWRITABLE AND APPENDABLE (PANDAS REWRITES THE TRIAL LOG AND OUTPUTS THIS WAY)
$WriteAllowedBool = $true
try { [System.IO.File]::WriteAllText($TestFile, "overwrite test $(Get-Date -Format s)"); Add-Content -Path $TestFile -Value "append test" -ErrorAction Stop } catch { $WriteAllowedBool = $false }
# TEST 3: A NEW FILE MUST BE CREATABLE AND DELETABLE
$NewFile = Join-Path $DataPath "store04_experiments\_protection_new_file_test.txt"
$NewFileOkBool = $true
try { Set-Content -Path $NewFile -Value "new" -ErrorAction Stop; Remove-Item -Path $NewFile -ErrorAction Stop } catch { $NewFileOkBool = $false }
# TEST 4: A RAW FILE MUST NOT BE WRITABLE
$RawFile = Get-ChildItem -Path (Join-Path $DataPath "store01_rawzone") -File -Recurse | Select-Object -First 1
$RawReadOnlyBool = $true
if ($RawFile) { try { $Stream = [System.IO.File]::Open($RawFile.FullName, "Open", "ReadWrite"); $Stream.Close(); $RawReadOnlyBool = $false } catch { $RawReadOnlyBool = $true } }

# DISPLAY THE RESULTS
Write-Host ""
Write-Host "Existing file cannot be deleted:   $DeleteBlockedBool"
Write-Host "Existing file can still be written: $WriteAllowedBool"
Write-Host "New file can be created and deleted: $NewFileOkBool"
Write-Host "Raw data is read-only:               $RawReadOnlyBool"
# FAIL IF ANY TEST FAILED
if (-not ($DeleteBlockedBool -and $WriteAllowedBool -and $NewFileOkBool -and $RawReadOnlyBool)) { throw "Protection test FAILED: do not start the agent; see the values above." }
# DISPLAY THE CONCLUSION
Write-Host "Protection in place. (The test file store04_experiments\_protection_test.txt stays; it is harmless.)"
