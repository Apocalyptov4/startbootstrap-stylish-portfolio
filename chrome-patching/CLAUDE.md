# Chrome patching — project context

Context for Claude Code. Read this before changing anything in `scripts/`.

## What this project is

Tooling to check and remediate Google Chrome versions on Windows endpoints
where the RMM's own patching is failing. Built after a live incident where
NinjaOne reported `Failed software patch — ChromeEnterprise (X64)` on every
machine in a batch of seven. It is written to be run by any tech in the
office against any endpoint, not just the machines from that incident.

**Current required version: `152.0.7977.82` or higher.** Anything below is
considered vulnerable. This value will change over time — it is defined once
as `$MinVersion` in `scripts/Update-Chrome.ps1`.

It will now go stale **fast**. As of Chrome 153 (8 September 2026) Google
moved to a **two-week major release cadence**, twice the old rate. Two
consequences:

- A machine can legitimately be a whole major version ahead of the target.
  Seen live: an endpoint with `153.0.8010.37` staged while `$MinVersion`
  was still `152.0.7977.82`. Comparisons must stay `-ge`, never `-eq` or a
  string match on the major.
- Whoever owns this tooling needs a habit of revisiting `$MinVersion`, or
  it silently degrades into passing machines that are months behind.
  Check <https://chromereleases.googleblog.com/> against the current
  security advisory rather than assuming.

## Environment constraints — these are load-bearing

These are the realities the tooling is written around. Do not "simplify" the
scripts in ways that break them:

- **WinRM is not enabled** on endpoints. `Invoke-CimMethod`, `Invoke-Command`,
  and anything else defaulting to WS-Man will fail with
  `HRESULT 0x80338012`. Use `Invoke-WmiMethod` (DCOM/RPC), `schtasks /s`,
  or run locally on the target instead.
- **Admin shares (`\\PC\c$`) do work.** Reading a remote file's version this
  way needs no remote execution at all and is the cheapest audit method.
- **The operator does not have NinjaOne admin access.** They cannot change
  patch policies or create automations. They *do* have **Backstage**, which
  gives a background terminal on the endpoint running as **SYSTEM**.
- **Running as SYSTEM means no mapped drives and no user profile.** Network
  shares are reached as the *machine* account (`DOMAIN\COMPUTER$`), so a
  share must grant read to `Domain Computers`. Do not write logs to a
  desktop path; use `C:\ProgramData\`.
- **Hostnames are inconsistent.** Some are bare hardware serials, others
  carry a site prefix. If a name does not resolve, retry with the site
  prefix before concluding the machine is offline.
- **Some machines in the list are domain controllers.** Never force-close
  applications or reboot one as part of a bulk operation. Check the role
  before running anything against a server.

## Failure modes we actually hit — and what they look like

All five of these surface in the RMM as the same generic "failed patch."
The scripts detect and name each one rather than returning a bare error.

### 1. Chrome installed somewhere other than `Program Files`
A check that only looks at `$env:ProgramFiles\Google\Chrome\Application\chrome.exe`
returns empty for 32-bit installs (`Program Files (x86)`) and for per-user
installs (`C:\Users\<u>\AppData\Local\Google\Chrome\...`). An empty result
reads as "not installed" when it actually means "we looked in one place."

**Per-user installs are not fixed by a `--system-level` install.** They must
be reported separately so the user can be dealt with directly.

### 2. Low disk space → MSI error 1603
One endpoint was at **2.9% free (6.8 GB)**. Windows Installer needs room for
the package, the extracted payload, *and* a rollback copy. Clearing caches
(`SoftwareDistribution\Download`, `Windows\Temp`, per-user `Temp`,
Delivery Optimization, recycle bin) took it to 18.2 GB.

Note: clearing disk space did **not** fix that machine — see below. Both
conditions were present. Do not stop diagnosing at the first cause found.

### 3. Corrupt Windows Installer cache → MSI error 2725
The real root cause on the one endpoint we fully diagnosed. Verbose MSI
log showed:

```
Original package ==> C:\WINDOWS\Installer\a75f6db.msi
Note: 1: 2725
Fatal error during installation.
Action ended: RemoveExistingProducts. Return value 3.
```

The cached MSI for the *currently installed* Chrome is damaged, so the
upgrade's `RemoveExistingProducts` step fails, so every MSI-based upgrade
fails — forever, no matter how many times the RMM retries. The MSI being
downloaded is fine; signature and length verify.

**Fix: use Google's EXE installer**, which does not touch the Installer
cache. This is why the tooling prefers EXE over MSI. If the EXE also fails,
`-RepairBroken` removes the broken registration with Chrome's own
`setup.exe --uninstall --system-level --force-uninstall` and reinstalls.
User profiles survive (they live in AppData; only `--delete-profile`
removes them).

### 4. Chrome running → patched on disk, still vulnerable in memory
Chrome keeps the old binaries loaded until the process ends. Patching files
while the user has Chrome open leaves them running vulnerable code. Under
Backstage this is invisible to the user, so they never think to restart.

**Any "success" report must say whether Chrome was running.** This is the
step most likely to be skipped and it decides whether the machine is
actually safe.

**It also breaks verification.** An install run while Chrome is open is
*staged*: the new build is written to `Application\<version>\` and the
launcher keeps reporting the old version until the browser closes. A
verify step that only re-reads `chrome.exe` therefore reports `FAILED` on
an update that actually succeeded. Seen live on a machine sitting at
`152.0.7977.77` with 99 GB free — nothing was wrong with it. Always check
for a staged version folder before calling an update failed, or techs will
escalate healthy machines.

The fix for the underlying problem is not to kill Chrome — that destroys
unsaved work and costs more time in tickets than the patch saved. Set
Chrome's own relaunch policy (`Set-ChromeRelaunchPolicy.ps1`) and it
restarts itself, restoring the user's tabs.

### 5. Stub installer needs network as SYSTEM
`chrome_installer.exe` is ~12 MB because it downloads Chrome at install
time. It needs outbound access from the SYSTEM context. An authenticating
proxy will break it. The full MSI (~158 MB) is self-contained but hits
failure mode 3.

## Gotchas that cost time during the incident

- **`Invoke-WebRequest` on PowerShell 5.1 is throttled by its own progress
  bar** — a 158 MB download took over ten minutes. With
  `$ProgressPreference = 'SilentlyContinue'`, or using `curl.exe`, the same
  transfer took **9 seconds**. Always use `curl.exe` when present.
- **QuickEdit mode freezes the console.** Clicking inside a Windows console
  window pauses the running process and prefixes the title with `Select`.
  This looks exactly like a hung installer. Press `Esc` to resume.
- **`Remove-Item C:\Users\*\AppData\...` errors on `C:\Users\Default User`** —
  a legacy junction. Harmless; suppress with `-EA SilentlyContinue`.
- **Don't write MSI logs to `C:\Windows\Temp`** if the script also cleans
  that directory. We deleted our own log this way.
- `msiexec` with `/qn` prints nothing while running. A blank cursor for
  1–3 minutes is normal. Distinguish a real hang by the console title bar.

## Conventions

- Scripts run **locally on the target** (Backstage, a Ninja automation, or
  PsExec). Remote-execution variants exist but WinRM being off makes them
  fragile.
- Always **check before installing** and exit early if compliant — techs run
  these against machines that may already be fine.
- Always **verify after installing** by re-reading the version from disk.
  Never report success from an installer exit code alone.
- Prefer **naming the cause** over returning an error number. The whole
  point of this tooling is that `1603` told us nothing.
- Log every run to `C:\ProgramData\ChromeUpdate\history.csv`
  (`timestamp, computer, before, after, status`).

## Open items

- Most of the machines from the original batch are not yet verified. Keep
  the working list somewhere internal, not in this repo.
- Unknown whether the corrupt-installer-cache condition is fleet-wide or
  specific to the one machine where we found it. If it is fleet-wide, no
  NinjaOne policy change will fix it and that needs escalating.
- The recurring fix is Chrome's `RelaunchNotificationPeriod` policy, which
  forces a browser relaunch after a set window. Chrome self-updates fine;
  machines sit on vulnerable builds because nobody ever restarts the
  browser. Fleet-wide this needs GPO or Chrome Browser Cloud Management,
  which the current operator does not have — but **per-machine it is just
  a registry key under `HKLM\SOFTWARE\Policies\Google\Chrome`, and
  Backstage can write it.** `Set-ChromeRelaunchPolicy.ps1` does this. Worth
  pushing for the fleet-wide version, since doing it per-machine does not
  cover new or rebuilt endpoints.
