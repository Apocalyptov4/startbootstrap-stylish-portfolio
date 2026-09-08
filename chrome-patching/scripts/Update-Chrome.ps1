<#
======================================================================
 Update-Chrome.ps1
======================================================================
 Checks and updates Google Chrome on the machine it runs on.
 Designed to be run locally -- from Ninja Backstage, a Ninja
 automation, PsExec, or an elevated PowerShell window.

 USAGE
   .\Update-Chrome.ps1              Check, and update if needed
   .\Update-Chrome.ps1 -CheckOnly   Report only, change nothing
   .\Update-Chrome.ps1 -RepairBroken  Also fix a corrupt installer
                                      registration (removes and
                                      reinstalls Chrome; profiles kept)

 WHY THIS EXISTS
   Chrome patch failures in our environment have had several distinct
   causes that all look identical from the RMM console. This script
   checks for each one and names it, instead of just failing:

     * Chrome installed somewhere other than Program Files
       (32-bit in Program Files (x86), or per-user in AppData)
     * Low disk space -- MSI installs die with error 1603
     * Corrupt Windows Installer cache -- the cached MSI for the
       existing Chrome is damaged, so RemoveExistingProducts fails
       (MSI internal error 2725) and every MSI upgrade fails forever
     * Chrome running -- files patch on disk but the loaded browser
       keeps the old, vulnerable code until it is restarted
     * The stub installer needing internet access as SYSTEM

 NOTES
   Prefers Google's EXE installer over the MSI, because the EXE does
   not touch the Windows Installer cache and therefore survives the
   corrupt-cache condition that breaks MSI upgrades.
======================================================================
#>

[CmdletBinding()]
param(
    [version]$MinVersion  = '152.0.7977.82',
    [switch] $CheckOnly,
    [switch] $RepairBroken,
    [switch] $SkipCleanup,
    [int]    $MinFreeGB   = 12
)

$ErrorActionPreference = 'Continue'
$script:Notes  = @()
$script:LogDir = 'C:\ProgramData\ChromeUpdate'
$StubUrl = 'https://dl.google.com/chrome/install/latest/chrome_installer.exe'
$MsiUrl  = 'https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi'

if (-not (Test-Path $script:LogDir)) {
    New-Item -Path $script:LogDir -ItemType Directory -Force | Out-Null
}

function Say  { param($m,$c='Gray')  Write-Host "  $m" -ForegroundColor $c }
function Head { param($m) Write-Host ''; Write-Host "  $m" -ForegroundColor Cyan }
function Note { param($m) $script:Notes += $m }

# ---------------------------------------------------------------------
# Find every Chrome on the box, not just the one in Program Files.
# ---------------------------------------------------------------------
function Get-ChromeInstalls {
    $paths = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
    )
    $paths += (Get-ChildItem 'C:\Users\*\AppData\Local\Google\Chrome\Application\chrome.exe' `
               -ErrorAction SilentlyContinue).FullName

    $paths | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique | ForEach-Object {
        $scope = if ($_ -like '*\Users\*')          { "PerUser:$($_.Split('\')[2])" }
                 elseif ($_ -like '*Program Files (x86)*') { 'Machine(32-bit)' }
                 else                                { 'Machine(64-bit)' }
        [pscustomobject]@{
            Scope   = $scope
            Version = (Get-Item $_ -ErrorAction SilentlyContinue).VersionInfo.ProductVersion
            Path    = $_
        }
    }
}

# ---------------------------------------------------------------------
# A patch applied while Chrome is open is STAGED, not active: the new
# build lands in Application\<version>\ and the launcher keeps reporting
# the old version until the browser closes. Without this check a staged
# -- i.e. successful -- update reads as FAILED and gets escalated.
# ---------------------------------------------------------------------
function Get-StagedVersion {
    param($ChromeExePath)
    if (-not $ChromeExePath) { return $null }
    $appDir = Split-Path $ChromeExePath -Parent
    if (-not (Test-Path $appDir)) { return $null }

    Get-ChildItem $appDir -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^\d+\.\d+\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Name } -Descending |
        Select-Object -First 1 -ExpandProperty Name
}

function Get-FreeGB {
    $d = Get-PSDrive C -ErrorAction SilentlyContinue
    if ($d) { [math]::Round($d.Free / 1GB, 1) } else { -1 }
}

function Get-FreePct {
    $d = Get-PSDrive C -ErrorAction SilentlyContinue
    if ($d -and ($d.Free + $d.Used) -gt 0) {
        [math]::Round($d.Free / ($d.Free + $d.Used) * 100, 1)
    } else { -1 }
}

# ---------------------------------------------------------------------
# Free up space. Caches only -- nothing a user would miss.
# ---------------------------------------------------------------------
function Invoke-DiskCleanup {
    Say 'Freeing disk space (caches only)...' 'Yellow'
    Stop-Service wuauserv,bits -Force -ErrorAction SilentlyContinue

    $targets = @(
        'C:\Windows\SoftwareDistribution\Download\*',
        'C:\Windows\Temp\*',
        'C:\Users\*\AppData\Local\Temp\*',
        'C:\Windows\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\*'
    )
    foreach ($t in $targets) {
        Remove-Item $t -Recurse -Force -ErrorAction SilentlyContinue
    }

    Start-Service wuauserv,bits -ErrorAction SilentlyContinue
    Clear-RecycleBin -Force -ErrorAction SilentlyContinue
    Say "Free space now: $(Get-FreeGB) GB" 'Yellow'
}

# ---------------------------------------------------------------------
# curl.exe is dramatically faster than Invoke-WebRequest on PS 5.1,
# where drawing the progress bar throttles the transfer.
# ---------------------------------------------------------------------
function Get-File {
    param($Url, $Dest)
    if (Test-Path $Dest) { Remove-Item $Dest -Force -ErrorAction SilentlyContinue }

    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L -s -o $Dest $Url
    } else {
        $old = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'   # <-- without this it crawls
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing -ErrorAction Stop
        } catch {
            Note "Download failed: $($_.Exception.Message)"
        } finally { $ProgressPreference = $old }
    }
    return (Test-Path $Dest)
}

# ---------------------------------------------------------------------
# Read an MSI log and name the failure in English.
# ---------------------------------------------------------------------
function Get-MsiFailureReason {
    param($LogPath)
    if (-not (Test-Path $LogPath)) { return $null }
    $c = Get-Content $LogPath -ErrorAction SilentlyContinue

    if ($c | Select-String -Pattern 'RemoveExistingProducts.*Return value 3' -Quiet) {
        if ($c | Select-String -Pattern 'Note: 1: 2725' -Quiet) {
            return 'CORRUPT_CACHE'
        }
        return 'REMOVE_EXISTING_FAILED'
    }
    if ($c | Select-String -Pattern 'out of disk space|1: 1603.*disk' -Quiet) { return 'DISK' }
    if ($c | Select-String -Pattern 'Return value 3' -Quiet)                  { return 'UNKNOWN_MSI' }
    return $null
}

# =====================================================================
#  START
# =====================================================================
Clear-Host
Write-Host ''
Write-Host '  ==================================================' -ForegroundColor Cyan
Write-Host '   CHROME VERSION CHECK / UPDATE' -ForegroundColor Cyan
Write-Host "   Computer : $env:COMPUTERNAME" -ForegroundColor Cyan
Write-Host "   Required : $MinVersion or higher" -ForegroundColor Cyan
Write-Host '  ==================================================' -ForegroundColor Cyan

# ------------------------------------------------- 1. what is installed
Head 'Installed copies of Chrome'
$installs = Get-ChromeInstalls

if (-not $installs) {
    Say 'No Chrome found anywhere on this machine.' 'Yellow'
    Note 'Chrome was not installed before this run.'
} else {
    foreach ($i in $installs) {
        $ok = $i.Version -and ([version]$i.Version -ge $MinVersion)
        Say ("{0,-20} {1,-18} {2}" -f $i.Scope, $i.Version, $(if($ok){'OK'}else{'OLD'})) $(if($ok){'Green'}else{'Yellow'})
    }
}

$perUser = $installs | Where-Object { $_.Scope -like 'PerUser*' -and [version]$_.Version -lt $MinVersion }
if ($perUser) {
    Note "PER-USER INSTALLS FOUND -- a machine-wide update will NOT fix these:"
    foreach ($p in $perUser) { Note "   $($p.Scope)  $($p.Version)" }
    Note "   Those users must update Chrome themselves, or have it removed."
}

# ------------------------------------------------- 2. is Chrome running
$running = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
if ($running -gt 0) {
    Note "Chrome is running ($running processes). Files can be patched, but the"
    Note "   open browser keeps the OLD version loaded until the user restarts it."
}

# ------------------------------------------------- 3. machine-wide state
$machine = $installs | Where-Object { $_.Scope -like 'Machine*' } |
           Sort-Object { [version]$_.Version } | Select-Object -First 1

if ($machine -and [version]$machine.Version -ge $MinVersion) {
    Head 'RESULT'
    Say "COMPLIANT - $($machine.Version)" 'Green'
    if ($running -gt 0) { Say 'User must restart Chrome to load the patched version.' 'Yellow' }
    foreach ($n in $script:Notes) { Say $n 'Yellow' }
    "$(Get-Date -f s),$env:COMPUTERNAME,$($machine.Version),$($machine.Version),Compliant" |
        Add-Content "$script:LogDir\history.csv"
    return
}

if ($CheckOnly) {
    Head 'RESULT'
    Say "NEEDS UPDATE - current: $(if($machine){$machine.Version}else{'not installed'})" 'Red'
    foreach ($n in $script:Notes) { Say $n 'Yellow' }
    return
}

$before = if ($machine) { $machine.Version } else { 'none' }

# ------------------------------------------------- 4. disk space gate
Head 'Disk space'
$free = Get-FreeGB
Say "$free GB free ($(Get-FreePct)%)"

if ($free -lt $MinFreeGB -and -not $SkipCleanup) {
    Note "Low disk space ($free GB) - this is a common cause of install failure."
    Invoke-DiskCleanup
    $free = Get-FreeGB
    if ($free -lt $MinFreeGB) {
        Note "Still only $free GB free after cleanup. This machine needs attention."
    }
}

# ------------------------------------------------- 5. install via EXE
Head 'Installing (EXE installer)'
$exe = "$env:TEMP\chrome_setup.exe"
Say 'Downloading...'
if (Get-File -Url $StubUrl -Dest $exe) {
    Say 'Installing, please wait...'
    Start-Process $exe -ArgumentList '/silent','/install','--system-level','--do-not-launch-chrome' -Wait
    Start-Sleep -Seconds 20
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
} else {
    Note 'Could not download the EXE installer.'
}

$after = (Get-ChromeInstalls | Where-Object { $_.Scope -like 'Machine*' } |
          Sort-Object { [version]$_.Version } -Descending | Select-Object -First 1).Version

# ------------------------------------------------- 6. fall back to MSI
if (-not $after -or [version]$after -lt $MinVersion) {
    Head 'EXE did not succeed - trying MSI'

    $log = "$script:LogDir\msi_$(Get-Date -f yyyyMMdd_HHmmss).log"
    $msi = "$env:TEMP\chrome_enterprise64.msi"

    Say 'Downloading MSI (larger, please wait)...'
    if (Get-File -Url $MsiUrl -Dest $msi) {
        $sig = (Get-AuthenticodeSignature $msi).Status
        if ($sig -ne 'Valid') {
            Note "MSI signature is '$sig' - the download was altered in transit (proxy?)."
        } else {
            Say 'Installing...'
            $p = Start-Process msiexec.exe -ArgumentList "/i `"$msi`" /qn /norestart /l*v `"$log`"" -Wait -PassThru
            Say "msiexec exit code: $($p.ExitCode)"

            if ($p.ExitCode -notin 0,3010) {
                switch (Get-MsiFailureReason -LogPath $log) {
                    'CORRUPT_CACHE' {
                        Note 'CAUSE FOUND: the Windows Installer cache entry for the existing'
                        Note '   Chrome is corrupt (MSI error 2725 in RemoveExistingProducts).'
                        Note '   Every MSI upgrade will fail on this machine until it is cleared.'
                        Note '   Re-run this script with -RepairBroken to remove and reinstall.'
                    }
                    'DISK'    { Note 'CAUSE FOUND: not enough disk space.' }
                    default   { Note "msiexec failed ($($p.ExitCode)). Log: $log" }
                }
            }
        }
        Remove-Item $msi -Force -ErrorAction SilentlyContinue
    }
    $after = (Get-ChromeInstalls | Where-Object { $_.Scope -like 'Machine*' } |
              Sort-Object { [version]$_.Version } -Descending | Select-Object -First 1).Version
}

# ------------------------------------------------- 7. repair (opt-in)
if ((-not $after -or [version]$after -lt $MinVersion) -and $RepairBroken -and $machine) {
    Head 'Repair: removing broken install, then reinstalling'
    Say 'User profiles (bookmarks, passwords) are preserved.' 'Yellow'

    $setup = Get-ChildItem (Split-Path $machine.Path) -Recurse -Filter 'setup.exe' `
             -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($setup) {
        Start-Process $setup.FullName -ArgumentList '--uninstall','--system-level','--force-uninstall' -Wait
        Start-Sleep -Seconds 15
    }

    if (Get-File -Url $StubUrl -Dest $exe) {
        Start-Process $exe -ArgumentList '/silent','/install','--system-level','--do-not-launch-chrome' -Wait
        Start-Sleep -Seconds 25
        Remove-Item $exe -Force -ErrorAction SilentlyContinue
    }
    $after = (Get-ChromeInstalls | Where-Object { $_.Scope -like 'Machine*' } |
              Sort-Object { [version]$_.Version } -Descending | Select-Object -First 1).Version
}

# ------------------------------------------------- 8. verdict
Head 'RESULT'
$logAfter = $after
if ($after -and [version]$after -ge $MinVersion) {
    Say "SUCCESS  $before  ->  $after" 'Green'
    $status = 'Fixed'
    if ($running -gt 0) {
        Say ''
        Say 'ACTION NEEDED: Chrome is open on this machine. Ask the user to close' 'Yellow'
        Say 'and reopen Chrome -- until then the running browser is still vulnerable.' 'Yellow'
    }
} else {
    # Before calling it a failure, check whether the new build is sitting
    # in Application\<version>\ waiting for Chrome to close.
    $stagedPath = if ($machine) { $machine.Path } else { "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" }
    $staged = Get-StagedVersion -ChromeExePath $stagedPath

    if ($staged -and ([version]$staged -ge $MinVersion)) {
        Say "STAGED   $before  ->  $staged" 'Yellow'
        Say ''
        Say "The patch is installed and waiting. Chrome is holding the old build" 'Yellow'
        Say "open, so the version on disk still reads $after until it restarts." 'Yellow'
        Say 'This is NOT a failure -- do not escalate it.' 'Yellow'
        $status    = 'Staged'
        $logAfter  = $staged
        Note 'Chrome must restart to activate the staged update. Set the relaunch'
        Note '   policy with Set-ChromeRelaunchPolicy.ps1 so it happens on its own.'
    } else {
        Say "FAILED   still at: $(if($after){$after}else{'not installed'})" 'Red'
        $status = 'Failed'
    }
}

if ($script:Notes) {
    Head 'Things to be aware of'
    foreach ($n in $script:Notes) { Say $n 'Yellow' }
}

"$(Get-Date -f s),$env:COMPUTERNAME,$before,$logAfter,$status" |
    Add-Content "$script:LogDir\history.csv"

Head 'Log'
Say "$script:LogDir\history.csv"
Write-Host ''
