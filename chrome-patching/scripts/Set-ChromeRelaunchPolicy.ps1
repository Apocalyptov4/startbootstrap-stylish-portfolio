<#
======================================================================
 Set-ChromeRelaunchPolicy.ps1
======================================================================
 Makes Chrome finish its own updates, so nobody has to chase the user.

 THE PROBLEM THIS SOLVES
   Patching the files on disk does not make a machine safe. Chrome keeps
   the old binaries loaded until the browser is restarted, and users
   leave Chrome open for weeks. Under Backstage the patch is invisible
   to them, so they never think to restart it.

   Killing Chrome for them "solves" this by destroying whatever they had
   open -- half-written emails, unsubmitted forms, unsaved work in web
   apps. That generates more tickets than the patch was worth.

 WHAT THIS DOES INSTEAD
   Sets Chrome's own relaunch policy. When an update is pending, Chrome
   warns the user, escalates the warning, and then relaunches itself
   when the timer expires -- RESTORING THEIR TABS. No lost work, no
   surprise, and no conversation needed.

 USAGE
   .\Set-ChromeRelaunchPolicy.ps1              4 hours, required
   .\Set-ChromeRelaunchPolicy.ps1 -Hours 1     shortest Chrome allows
   .\Set-ChromeRelaunchPolicy.ps1 -Mode Recommended
                                               nags, never forces
   .\Set-ChromeRelaunchPolicy.ps1 -CheckOnly   report, change nothing
   .\Set-ChromeRelaunchPolicy.ps1 -Remove      undo it

 RUN IT
   Locally on the target, elevated -- Backstage, a Ninja automation, or
   PsExec. Run it AFTER Update-Chrome.ps1: the timer starts when Chrome
   sees a pending update, so patch first, then set this.

 SCOPE
   This writes a machine-wide policy under HKLM. Users cannot override
   it. It is per-machine -- doing this fleet-wide is a GPO or Chrome
   Browser Cloud Management job, which needs access this operator does
   not have. Per-machine via Backstage does not.
======================================================================
#>

[CmdletBinding()]
param(
    [ValidateRange(1,168)]
    [int]    $Hours = 4,
    [ValidateSet('Required','Recommended')]
    [string] $Mode  = 'Required',
    [switch] $Remove,
    [switch] $CheckOnly
)

$ErrorActionPreference = 'Continue'
$LogDir = 'C:\ProgramData\ChromeUpdate'
$Key    = 'HKLM:\SOFTWARE\Policies\Google\Chrome'

if (-not (Test-Path $LogDir)) {
    New-Item -Path $LogDir -ItemType Directory -Force | Out-Null
}

function Say  { param($m,$c='Gray') Write-Host "  $m" -ForegroundColor $c }
function Head { param($m) Write-Host ''; Write-Host "  $m" -ForegroundColor Cyan }

function Get-Policy {
    $p = Get-ItemProperty -Path $Key -ErrorAction SilentlyContinue
    $mode = switch ($p.RelaunchNotification) {
        1       { 'Recommended' }
        2       { 'Required' }
        default { 'not set' }
    }
    $period = if ($p.RelaunchNotificationPeriod) {
        "{0} hours" -f [math]::Round($p.RelaunchNotificationPeriod / 3600000, 1)
    } else { 'not set' }
    [pscustomobject]@{ Mode = $mode; Period = $period; Raw = $p.RelaunchNotificationPeriod }
}

# =====================================================================
Clear-Host
Write-Host ''
Write-Host '  ==================================================' -ForegroundColor Cyan
Write-Host '   CHROME RELAUNCH POLICY' -ForegroundColor Cyan
Write-Host "   Computer : $env:COMPUTERNAME" -ForegroundColor Cyan
Write-Host '  ==================================================' -ForegroundColor Cyan

$before = Get-Policy
Head 'Current setting'
Say "Mode   : $($before.Mode)"
Say "Period : $($before.Period)"

if ($CheckOnly) {
    Write-Host ''
    return
}

if ($Remove) {
    Head 'Removing the policy'
    Remove-ItemProperty -Path $Key -Name RelaunchNotification       -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $Key -Name RelaunchNotificationPeriod -ErrorAction SilentlyContinue
    $after = Get-Policy
    Say "Mode   : $($after.Mode)" 'Yellow'
    Say "Period : $($after.Period)" 'Yellow'
    Say 'Chrome is back to its default: it will nag eventually, but never force.' 'Yellow'

    "$(Get-Date -f s),$env:COMPUTERNAME,$($before.Period),$($after.Period),RelaunchPolicyRemoved" |
        Add-Content "$LogDir\history.csv"
    Write-Host ''
    return
}

# Chrome ignores anything under one hour.
$ms = $Hours * 3600000
$notify = if ($Mode -eq 'Required') { 2 } else { 1 }

Head "Setting: $Mode, $Hours hour(s)"
if (-not (Test-Path $Key)) { New-Item -Path $Key -Force | Out-Null }
Set-ItemProperty -Path $Key -Name RelaunchNotification       -Value $notify -Type DWord
Set-ItemProperty -Path $Key -Name RelaunchNotificationPeriod -Value $ms     -Type DWord

$after = Get-Policy
if ($after.Mode -eq $Mode -and $after.Raw -eq $ms) {
    Say "Mode   : $($after.Mode)" 'Green'
    Say "Period : $($after.Period)" 'Green'
} else {
    Say 'The policy did not stick. Are you running elevated / as SYSTEM?' 'Red'
    Say "Mode   : $($after.Mode)" 'Red'
    Say "Period : $($after.Period)" 'Red'
}

Head 'What happens now'
if ($Mode -eq 'Required') {
    Say "When Chrome has a pending update, the user gets escalating prompts"
    Say "for $Hours hour(s), then Chrome relaunches itself and restores their tabs."
} else {
    Say 'The user will be prompted to relaunch, but never forced.'
    Say 'Use -Mode Required if the machine must actually end up patched.' 'Yellow'
}

$running = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
if ($running -gt 0) {
    Say ''
    Say "Chrome is open right now ($running processes)." 'Yellow'
    Say 'A running Chrome can take up to an hour to notice a new policy.' 'Yellow'
    Say 'To confirm sooner: chrome://policy -> Reload policies.' 'Yellow'
} else {
    Say ''
    Say 'Chrome is not running. It will pick the policy up on next launch.'
}

"$(Get-Date -f s),$env:COMPUTERNAME,$($before.Period),$($after.Period),RelaunchPolicySet" |
    Add-Content "$LogDir\history.csv"

Head 'Log'
Say "$LogDir\history.csv"
Write-Host ''
