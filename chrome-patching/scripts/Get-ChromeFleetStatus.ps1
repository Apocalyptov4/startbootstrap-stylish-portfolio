<#
======================================================================
 Get-ChromeFleetStatus.ps1
======================================================================
 Reads the installed Chrome version from every machine in a list and
 writes one CSV plus an on-screen summary.

 READ-ONLY. Nothing is installed, downloaded, changed, or executed on
 any endpoint. Versions are read straight off the admin share
 (\\PC\c$), which needs no remote execution at all -- this is the only
 audit method that works here, because WinRM is switched off.

 USAGE
   .\Get-ChromeFleetStatus.ps1
       Reads machine names from ..\computers.txt

   .\Get-ChromeFleetStatus.ps1 -ComputerName PC-01,PC-02
       Checks just those machines

   .\Get-ChromeFleetStatus.ps1 -SitePrefix 'SITE-'
       If a bare name does not answer, retries it with the prefix
       (and a prefixed name retried without it), because hostnames
       in this fleet are inconsistent.

 RUN IT AS
   A domain admin (or any account with admin rights on the targets),
   from your own workstation. Not from Backstage -- SYSTEM on one
   endpoint has no rights to the others.

 WHAT THE STATUSES MEAN
   Compliant     Every machine-wide install is at or above MinVersion.
   Outdated      A machine-wide install is below it. Run
                 Update-Chrome.ps1 on this machine.
   NoChrome      Reachable, share readable, genuinely no Chrome found.
   AccessDenied  Machine answered but the share would not open. This
                 is a permissions problem, NOT "Chrome is missing" --
                 the difference matters, see CLAUDE.md failure mode 1.
   Unreachable   No answer on port 445. Offline, or the name is wrong.
======================================================================
#>

[CmdletBinding()]
param(
    [string[]]$ComputerName,
    [string]  $InputFile  = (Join-Path $PSScriptRoot '..\computers.txt'),
    [version] $MinVersion = '152.0.7977.82',
    [string]  $SitePrefix = '',
    [string]  $OutputCsv,
    [int]     $TimeoutMs  = 1500
)

$ErrorActionPreference = 'Continue'
$LogDir = 'C:\ProgramData\ChromeUpdate'

if (-not $OutputCsv) {
    $OutputCsv = Join-Path $LogDir "fleet_$(Get-Date -f yyyyMMdd_HHmmss).csv"
}
$outDir = Split-Path $OutputCsv -Parent
if ($outDir -and -not (Test-Path $outDir)) {
    New-Item -Path $outDir -ItemType Directory -Force | Out-Null
}

function Say  { param($m,$c='Gray') Write-Host "  $m" -ForegroundColor $c }
function Head { param($m) Write-Host ''; Write-Host "  $m" -ForegroundColor Cyan }

# ---------------------------------------------------------------------
# Where the machine names come from.
# ---------------------------------------------------------------------
if (-not $ComputerName) {
    if (-not (Test-Path $InputFile)) {
        Write-Host ''
        Say "No machine list found at: $InputFile" 'Red'
        Say 'Copy computers.example.txt to computers.txt and put your own' 'Yellow'
        Say 'machine names in it, one per line. Or pass -ComputerName PC-01,PC-02.' 'Yellow'
        Write-Host ''
        return
    }
    $ComputerName = Get-Content $InputFile |
                    ForEach-Object { $_.Trim() } |
                    Where-Object   { $_ -and -not $_.StartsWith('#') }
}

$ComputerName = $ComputerName | Sort-Object -Unique
if (-not $ComputerName) { Say 'The machine list is empty.' 'Red'; return }

# ---------------------------------------------------------------------
# Reachability. A TCP check on 445 with a short timeout, because
# Test-Path against a dead host blocks for a long time and ICMP is
# often filtered.
# ---------------------------------------------------------------------
function Test-Smb {
    param($Computer, $Timeout)
    $client = New-Object Net.Sockets.TcpClient
    try {
        $ar = $client.BeginConnect($Computer, 445, $null, $null)
        if (-not $ar.AsyncWaitHandle.WaitOne($Timeout, $false)) { return $false }
        $client.EndConnect($ar)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# Hostnames here are inconsistent: some carry a site prefix, some do not.
# Try the name as given, then the other form, before calling it offline.
function Resolve-Target {
    param($Name, $Prefix, $Timeout)
    $tries = @($Name)
    if ($Prefix) {
        if ($Name -like "$Prefix*") {
            $tries += ($Name -replace "^$([regex]::Escape($Prefix))", '')
        } else {
            $tries += "$Prefix$Name"
        }
    }
    foreach ($t in $tries) {
        if ($t -and (Test-Smb -Computer $t -Timeout $Timeout)) { return $t }
    }
    return $null
}

function ConvertTo-Version {
    param($Text)
    $v = $null
    if ($Text -and [version]::TryParse($Text, [ref]$v)) { return $v }
    return $null
}

# ---------------------------------------------------------------------
# Every Chrome on the box, not just the one in Program Files.
# ---------------------------------------------------------------------
function Get-RemoteChrome {
    param($Computer)
    $root  = "\\$Computer\c$"
    $paths = @(
        "$root\Program Files\Google\Chrome\Application\chrome.exe",
        "$root\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    )
    $paths += (Get-ChildItem "$root\Users\*\AppData\Local\Google\Chrome\Application\chrome.exe" `
               -ErrorAction SilentlyContinue).FullName

    $paths | Where-Object { $_ -and (Test-Path $_ -ErrorAction SilentlyContinue) } |
        Sort-Object -Unique | ForEach-Object {
            if ($_ -match '\\Users\\([^\\]+)\\AppData') {
                $scope = "PerUser:$($matches[1])"
            } elseif ($_ -like '*Program Files (x86)*') {
                $scope = 'Machine(32-bit)'
            } else {
                $scope = 'Machine(64-bit)'
            }
            [pscustomobject]@{
                Scope   = $scope
                Version = (Get-Item $_ -ErrorAction SilentlyContinue).VersionInfo.ProductVersion
            }
        }
}

# =====================================================================
#  START
# =====================================================================
Clear-Host
Write-Host ''
Write-Host '  ==================================================' -ForegroundColor Cyan
Write-Host '   CHROME FLEET AUDIT  (read-only)' -ForegroundColor Cyan
Write-Host "   Machines : $($ComputerName.Count)" -ForegroundColor Cyan
Write-Host "   Required : $MinVersion or higher" -ForegroundColor Cyan
Write-Host '  ==================================================' -ForegroundColor Cyan
Write-Host ''

$stamp   = Get-Date -f s
$results = @()
$n       = 0

foreach ($name in $ComputerName) {
    $n++
    Write-Host ("  [{0}/{1}] {2,-20} " -f $n, $ComputerName.Count, $name) -NoNewline

    $row = [pscustomobject]@{
        Timestamp      = $stamp
        Computer       = $name
        ResolvedAs     = ''
        Status         = 'Unreachable'
        MachineVersion = ''
        AllMachine     = ''
        PerUser        = ''
        Detail         = ''
    }

    $target = Resolve-Target -Name $name -Prefix $SitePrefix -Timeout $TimeoutMs
    if (-not $target) {
        $row.Detail = 'No answer on port 445 (offline, or wrong name)'
        Write-Host 'UNREACHABLE' -ForegroundColor DarkGray
        $results += $row
        continue
    }

    $row.ResolvedAs = $target

    # Confirm the share actually opens. Without this check a permissions
    # failure looks identical to "Chrome is not installed".
    if (-not (Test-Path "\\$target\c$\Windows" -ErrorAction SilentlyContinue)) {
        $row.Status = 'AccessDenied'
        $row.Detail = "Reachable, but \\$target\c$ would not open (rights?)"
        Write-Host 'ACCESS DENIED' -ForegroundColor Magenta
        $results += $row
        continue
    }

    $installs = @(Get-RemoteChrome -Computer $target)
    $machine  = @($installs | Where-Object { $_.Scope -like 'Machine*' })
    $perUser  = @($installs | Where-Object { $_.Scope -like 'PerUser*' })

    $row.AllMachine = ($machine | ForEach-Object { "$($_.Scope)=$($_.Version)" }) -join '; '
    $row.PerUser    = ($perUser | ForEach-Object { "$($_.Scope)=$($_.Version)" }) -join '; '

    if (-not $machine) {
        if ($perUser) {
            $row.Status = 'Outdated'
            $row.MachineVersion = 'none'
            $row.Detail = 'Only per-user copies exist. A machine-wide install will not update them.'
            Write-Host 'PER-USER ONLY' -ForegroundColor Yellow
        } else {
            $row.Status = 'NoChrome'
            $row.Detail = 'No chrome.exe in Program Files, Program Files (x86), or any user profile'
            Write-Host 'NO CHROME' -ForegroundColor Yellow
        }
        $results += $row
        continue
    }

    # Compliance is decided by the OLDEST machine-wide copy. If a box has
    # both 32-bit and 64-bit installed, the stale one is the exposure.
    $lowest = $machine |
              Sort-Object { ConvertTo-Version $_.Version } |
              Select-Object -First 1
    $row.MachineVersion = $lowest.Version
    $lv = ConvertTo-Version $lowest.Version

    if ($lv -and $lv -ge $MinVersion) {
        $row.Status = 'Compliant'
        Write-Host "OK   $($lowest.Version)" -ForegroundColor Green
    } else {
        $row.Status = 'Outdated'
        Write-Host "OLD  $($lowest.Version)" -ForegroundColor Red
    }

    if ($perUser) {
        $row.Detail = 'Also has per-user copies -- these need the user, not a machine-wide update.'
    }

    $results += $row
}

# ------------------------------------------------- summary
$results | Export-Csv -Path $OutputCsv -NoTypeInformation -Encoding UTF8

$compliant = @($results | Where-Object { $_.Status -eq 'Compliant' })
$outdated  = @($results | Where-Object { $_.Status -eq 'Outdated' })
$noChrome  = @($results | Where-Object { $_.Status -eq 'NoChrome' })
$denied    = @($results | Where-Object { $_.Status -eq 'AccessDenied' })
$offline   = @($results | Where-Object { $_.Status -eq 'Unreachable' })
$withUser  = @($results | Where-Object { $_.PerUser })

Head 'SUMMARY'
Say ("Compliant      {0}" -f $compliant.Count) 'Green'
Say ("Outdated       {0}" -f $outdated.Count)  $(if($outdated.Count){'Red'}else{'Gray'})
Say ("No Chrome      {0}" -f $noChrome.Count)  'Gray'
Say ("Access denied  {0}" -f $denied.Count)    $(if($denied.Count){'Magenta'}else{'Gray'})
Say ("Unreachable    {0}" -f $offline.Count)   'DarkGray'

if ($outdated.Count) {
    Head 'NEEDS UPDATING - run Update-Chrome.ps1 on these'
    foreach ($r in $outdated) {
        Say ("{0,-20} {1}" -f $r.Computer, $(if($r.MachineVersion){$r.MachineVersion}else{'none'})) 'Red'
    }
}

if ($withUser.Count) {
    Head 'PER-USER INSTALLS - a machine-wide update will NOT fix these'
    foreach ($r in $withUser) { Say ("{0,-20} {1}" -f $r.Computer, $r.PerUser) 'Yellow' }
    Say 'Contact those users directly, or have the per-user copy removed.' 'Yellow'
}

if ($denied.Count) {
    Head 'COULD NOT READ - not the same as "no Chrome"'
    foreach ($r in $denied) { Say ("{0,-20} {1}" -f $r.Computer, $r.Detail) 'Magenta' }
}

if ($offline.Count) {
    Head 'NO ANSWER'
    foreach ($r in $offline) { Say $r.Computer 'DarkGray' }
    if (-not $SitePrefix) {
        Say 'If these names should carry a site prefix, re-run with -SitePrefix.' 'DarkGray'
    }
}

Head 'CSV'
Say $OutputCsv
Write-Host ''
