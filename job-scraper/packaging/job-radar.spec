# PyInstaller recipe for the one-file Job Radar program.
# Build from the job-scraper folder:  pyinstaller packaging/job-radar.spec
import sys
from pathlib import Path

root = Path(SPECPATH).parent

a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root)],
    datas=[(str(root / "jobscraper" / "web"), "jobscraper/web")],
    excludes=["tkinter", "unittest", "pydoc"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="JobRadar",
    console=True,  # the window shows the app is running; closing it quits
    upx=False,
    icon=str(root / "packaging" / "icon.ico") if sys.platform == "win32" else None,
)
