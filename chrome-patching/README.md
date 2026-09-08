# chrome-patching

Tooling to audit and remediate Google Chrome versions on Windows endpoints
when RMM patching fails. Written for any tech in the office to run against
any endpoint.

## Layout

    CLAUDE.md              Project context — environment constraints and the
                           five failure modes this tooling exists to handle.
                           Claude Code reads this automatically.
    RUNBOOK.md             Step-by-step for techs. No PowerShell needed.
    scripts/
      Update-Chrome.ps1    Check and remediate a single machine.

## Quick start

Run locally on the target (Backstage, a Ninja automation, or PsExec):

    .\scripts\Update-Chrome.ps1               # check, update if needed
    .\scripts\Update-Chrome.ps1 -CheckOnly    # report only, changes nothing
    .\scripts\Update-Chrome.ps1 -RepairBroken # also fix a corrupt installer
                                              # registration (removes and
                                              # reinstalls; profiles kept)

Current target version is `152.0.7977.82`, set as `$MinVersion` in the script.

## Remote audit without WinRM

WinRM is off across this fleet, but admin shares work. To read versions
without executing anything remotely:

    $pcs = 'PC-01','PC-02','PC-03'      # put your own machine names here
    foreach ($c in $pcs) {
      $v = (Get-Item "\\$c\c`$\Program Files\Google\Chrome\Application\chrome.exe" -EA 0).VersionInfo.ProductVersion
      "{0,-16} {1}" -f $c, $(if($v){$v}else{'unreachable / not found'})
    }

## Logs

Every run appends to `C:\ProgramData\ChromeUpdate\history.csv` as
`timestamp, computer, before, after, status`.

## Ideas / not built yet

- Fleet audit script that writes a single CSV across all machines
- Ninja-shaped variant with exit codes for alerting and custom field write-back
- Detect the corrupt-installer-cache condition proactively rather than on failure
