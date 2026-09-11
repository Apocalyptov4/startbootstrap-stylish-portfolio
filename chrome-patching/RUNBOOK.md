# Runbook — Chrome version remediation

For techs. No PowerShell knowledge needed.

**Goal:** every machine on Chrome `152.0.7977.82` or higher.

---

## 1. Open a terminal on the machine

NinjaOne → the device → **Backstage** → **Terminal** → **PowerShell**.

Backstage runs in the background as SYSTEM. The user sees nothing and is
not interrupted.

## 2. Paste this, press Enter

```powershell
$min=[version]'152.0.7977.82'
$app="$env:ProgramFiles\Google\Chrome\Application"
$find={ $p=@("$app\chrome.exe","${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe")+(Get-ChildItem 'C:\Users\*\AppData\Local\Google\Chrome\Application\chrome.exe' -EA 0).FullName; $p|?{$_ -and (Test-Path $_)}|%{[pscustomobject]@{Path=$_;Ver=(Get-Item $_).VersionInfo.ProductVersion}} }
$best={ (&$find|?{$_.Path -notlike '*\Users\*'}|sort {[version]$_.Ver} -desc|select -f 1).Ver }
$stg={ (Get-ChildItem $app -Directory -EA 0|?{$_.Name -match '^\d+\.\d+\.\d+\.\d+$'}|sort {[version]$_.Name} -desc|select -f 1).Name }
&$find|%{"FOUND: {0}  {1}" -f $_.Ver,$_.Path}
if(-not ((&$best) -and [version](&$best) -ge $min)){
$f=[math]::Round((Get-PSDrive C).Free/1GB,1); "Free: $f GB"
if($f -lt 12){Stop-Service wuauserv,bits -Force -EA 0; Remove-Item C:\Windows\SoftwareDistribution\Download\*,C:\Windows\Temp\*,C:\Users\*\AppData\Local\Temp\* -Recurse -Force -EA 0; Start-Service wuauserv,bits -EA 0; "Freed -> $([math]::Round((Get-PSDrive C).Free/1GB,1)) GB"}
$e="$env:TEMP\cs.exe"; curl.exe -L -s -o $e 'https://dl.google.com/chrome/install/latest/chrome_installer.exe'
if((Test-Path $e) -and (Get-Item $e).Length -gt 1MB){$p=Start-Process $e -ArgumentList '/silent','/install','--system-level','--do-not-launch-chrome' -Wait -PassThru; "installer exit: $($p.ExitCode)"; Start-Sleep 20}else{"DOWNLOAD FAILED - no outbound internet as SYSTEM"}}
$a=&$best; $s=&$stg
if($a -and [version]$a -ge $min){"SUCCESS -> $a"}elseif($s -and [version]$s -ge $min){"STAGED -> $s  (patched, waiting on a Chrome restart)"}else{"FAILED -> running=$a staged=$s"}
if(@(Get-Process chrome -EA 0).Count){$k='HKLM:\SOFTWARE\Policies\Google\Chrome'; New-Item $k -Force|Out-Null; Set-ItemProperty $k -Name RelaunchNotification -Value 2 -Type DWord; Set-ItemProperty $k -Name RelaunchNotificationPeriod -Value 14400000 -Type DWord; "Chrome open -> relaunch policy set, it will restart itself within 4h and restore tabs"}
```

Takes about two minutes. **Do not click inside the window while it runs** —
that freezes it. If the title bar starts with `Select`, press `Esc`.

**Paste the whole thing in one go.** Copying it a line at a time does not
work: the `if` at the bottom spans several lines, and PowerShell throws
away a half-finished block. The symptom is that it checks the version,
prints nothing further, and hands you the prompt back.

Some lines print nothing at all. That is normal — only the lines starting
`FOUND:`, `SUCCESS`, `STAGED`, `FAILED` and `Chrome open` produce output.

The block also sets the relaunch policy if Chrome is open, so the machine
finishes on its own. You do not have to message the user or close their
browser.

## 3. Read the last line

| Output | What it means | What you do |
|---|---|---|
| `SUCCESS -> 152.x` | Already patched, or patched just now | Nothing. Close the ticket. |
| `STAGED -> 152.x` | Patched, waiting on a Chrome restart | Nothing — the relaunch policy handles it. **Not a failure**, do not escalate. |
| `FAILED -> running=… staged=…` | Genuinely did not update | Escalate — paste the full output including both numbers. |
| `DOWNLOAD FAILED` | No outbound internet as SYSTEM | A proxy is blocking it. Escalate. |
| No `FOUND:` line at all | Chrome was not installed | The block installs it. Confirm it should be there. |
| `FOUND: ... \Users\...` | Per-user install | See step 5. |

## 4. If you see `Chrome open -> relaunch policy set`

Nothing to do. The patch is on disk, and Chrome will warn the user,
escalate, then relaunch itself within four hours and put all their tabs
back. The machine finishes without anyone being chased.

Why it matters: until Chrome restarts, the running browser still has the
old, vulnerable version in memory even though the files are patched. The
policy is what closes that gap.

**Do not kill Chrome to speed this up.** `Stop-Process -Name chrome` works,
but it destroys whatever the user had open — half-written emails,
unsubmitted forms, anything in a web app — and you will spend more time on
the ticket than the patch saved.

To change the window, or to check/undo it:

```powershell
.\scripts\Set-ChromeRelaunchPolicy.ps1 -Hours 1
.\scripts\Set-ChromeRelaunchPolicy.ps1 -CheckOnly
.\scripts\Set-ChromeRelaunchPolicy.ps1 -Remove
```

## 5. If a path under `C:\Users\...` appears

That user has their own private copy of Chrome. The machine-wide update
does not touch it. Contact that user directly to update from
**Chrome → Help → About Google Chrome**, or escalate to have it removed.

---

## Escalation

Include: the computer name, the full output, and which step failed.

Known cause worth mentioning if `FAILED`: some machines have a corrupt
Windows Installer cache entry for Chrome (MSI error 2725), which makes
every MSI-based upgrade fail permanently. The fix is a remove-and-reinstall
via `scripts/Update-Chrome.ps1 -RepairBroken`. Do not run that flag
yourself without checking first — it briefly removes Chrome.

## Do not run this on a domain controller

Check what the machine is before you start. Domain controllers and other
servers get handled deliberately, outside business hours, not as part of a
bulk pass. If you are not sure whether a machine is a server, ask first.
