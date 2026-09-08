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
$find={ $p=@("$env:ProgramFiles\Google\Chrome\Application\chrome.exe","${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe")+(Get-ChildItem 'C:\Users\*\AppData\Local\Google\Chrome\Application\chrome.exe' -EA 0).FullName; $p|?{$_ -and (Test-Path $_)}|%{[pscustomobject]@{Path=$_;Ver=(Get-Item $_).VersionInfo.ProductVersion}} }
$i=&$find; $i|%{"FOUND: {0}  {1}" -f $_.Ver,$_.Path}
$m=$i|?{$_.Path -notlike '*\Users\*'}|sort {[version]$_.Ver} -desc|select -f 1
if($m -and [version]$m.Ver -ge $min){"COMPLIANT: $($m.Ver)"}else{
$f=[math]::Round((Get-PSDrive C).Free/1GB,1); "Free: $f GB"
if($f -lt 12){Stop-Service wuauserv,bits -Force -EA 0; Remove-Item C:\Windows\SoftwareDistribution\Download\*,C:\Windows\Temp\*,C:\Users\*\AppData\Local\Temp\* -Recurse -Force -EA 0; Start-Service wuauserv,bits -EA 0; "Freed -> $([math]::Round((Get-PSDrive C).Free/1GB,1)) GB"}
$e="$env:TEMP\cs.exe"; curl.exe -L -s -o $e 'https://dl.google.com/chrome/install/latest/chrome_installer.exe'
Start-Process $e -ArgumentList '/silent','/install','--system-level','--do-not-launch-chrome' -Wait; Start-Sleep 25
$a=(&$find|?{$_.Path -notlike '*\Users\*'}|sort {[version]$_.Ver} -desc|select -f 1).Ver
if($a -and [version]$a -ge $min){"SUCCESS -> $a"}else{"FAILED -> $a"}
if(@(Get-Process chrome -EA 0).Count){"NOTE: Chrome is open - user must restart it"}}
```

Takes about two minutes. **Do not click inside the window while it runs** —
that freezes it. If the title bar starts with `Select`, press `Esc`.

**Paste the whole thing in one go.** Copying it a line at a time does not
work: the `if` at the bottom spans several lines, and PowerShell throws
away a half-finished block. The symptom is that it checks the version,
prints nothing further, and hands you the prompt back.

Some lines print nothing at all. That is normal — only the lines starting
`FOUND:`, `COMPLIANT:`, `SUCCESS`, `FAILED` and `NOTE:` produce output.

## 3. Read the last line

| Output | What it means | What you do |
|---|---|---|
| `COMPLIANT: 152.x` | Already patched | Nothing. Close the ticket. |
| `SUCCESS -> 152.x` | Updated | See step 4. |
| `FAILED -> ...` | Did not update | Escalate — paste the full output. |
| No `FOUND:` line at all | Chrome was not installed | The block installs it. Confirm it should be there. |
| `FOUND: ... \Users\...` | Per-user install | See step 5. |

## 4. If you see `NOTE: Chrome is open`

**The machine is not safe yet.** Files are patched but the user's running
browser still has the old, vulnerable version loaded in memory.

Message the user:

> Chrome has been updated on your machine. Please close Chrome completely
> and reopen it when convenient — the update takes effect on restart. No
> reboot needed.

Don't close it for them without warning; they'll lose unsaved work.

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
