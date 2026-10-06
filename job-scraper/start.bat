@echo off
rem Double-click this file on Windows to open Job Radar.
cd /d "%~dp0"
where python >nul 2>nul || (echo Python 3 is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH". & pause & exit /b 1)
python -c "import requests" 2>nul || python -m pip install -r requirements.txt
python -m jobscraper ui %*
pause
