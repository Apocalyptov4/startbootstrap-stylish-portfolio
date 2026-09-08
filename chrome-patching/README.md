# chrome-patching

Tooling to audit and remediate Google Chrome versions on Windows endpoints
when RMM patching fails. Written for any tech in the office to run against
any endpoint.

## Layout

    CLAUDE.md                    Project context — environment constraints and
                                 the five failure modes this tooling exists to
                                 handle. Claude Code reads this automatically.
    RUNBOOK.md                   Step-by-step for techs. No PowerShell needed.
    computers.example.txt        Template for your machine list. Copy it to
                                 computers.txt (git-ignored).
    scripts/
      Update-Chrome.ps1          Check and remediate a single machine.
      Get-ChromeFleetStatus.ps1  Read-only audit across many machines.

## Quick start

Run locally on the target (Backstage, a Ninja automation, or PsExec):

    .\scripts\Update-Chrome.ps1               # check, update if needed
    .\scripts\Update-Chrome.ps1 -CheckOnly    # report only, changes nothing
    .\scripts\Update-Chrome.ps1 -RepairBroken # also fix a corrupt installer
                                              # registration (removes and
                                              # reinstalls; profiles kept)

Current target version is `152.0.7977.82`, set as `$MinVersion` in the script.

## Fleet audit — who is actually out of date

WinRM is off across this fleet, but admin shares work, so versions can be
read without executing anything remotely. Run this from your own
workstation as an account with admin rights on the targets — not from
Backstage, since SYSTEM on one endpoint has no rights to the others.

    copy computers.example.txt computers.txt     # then edit in your names
    .\scripts\Get-ChromeFleetStatus.ps1

    .\scripts\Get-ChromeFleetStatus.ps1 -ComputerName PC-01,PC-02
    .\scripts\Get-ChromeFleetStatus.ps1 -SitePrefix 'SITE-'

It is read-only: nothing is installed, downloaded, or changed on any
endpoint. It prints a summary and writes a CSV to
`C:\ProgramData\ChromeUpdate\fleet_<timestamp>.csv`.

Statuses are deliberately distinct, because in the RMM they all looked the
same:

| Status | Meaning |
|---|---|
| `Compliant` | Every machine-wide install is current |
| `Outdated` | Run `Update-Chrome.ps1` on this machine |
| `NoChrome` | Reachable and readable, genuinely no Chrome |
| `AccessDenied` | Answered, but the share would not open — a rights problem, **not** a missing Chrome |
| `Unreachable` | No answer on port 445 — offline or wrong name |

`computers.txt` is git-ignored. Real machine names must not land in this
repo.

## Logs

Every run appends to `C:\ProgramData\ChromeUpdate\history.csv` as
`timestamp, computer, before, after, status`.

## Ideas / not built yet

- Ninja-shaped variant with exit codes for alerting and custom field write-back
- Detect the corrupt-installer-cache condition proactively rather than on failure
