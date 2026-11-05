@echo off
setlocal
title TailChat - Tailscale Workshop
cd /d "%~dp0"
echo.
echo   TailChat - your team's private space
echo   -----------------------------------
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if errorlevel 1 (
    echo A working Python 3.10 or newer was not found by the py launcher.
    echo The setup helper can download official Python 3.12 for this user.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-python.ps1"
    if errorlevel 1 goto failed
)
py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
if errorlevel 1 (
    echo Python is installed but this console cannot find it yet.
    echo Close this window and double-click start.bat again.
    goto failed
)
if not exist ".venv\Scripts\python.exe" (
    echo Creating the local Python environment...
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
echo Checking dependencies. Internet is needed the first time.
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Local URL: http://localhost:5000
echo On the host, run: tailscale ip -4
echo Give your team: http://YOUR_TAILSCALE_IP:5000
echo Keep this window open. Press Ctrl+C to stop the server.
echo.
".venv\Scripts\python.exe" app.py
if errorlevel 1 goto failed
echo Server stopped.
pause
exit /b 0
:failed
echo.
echo TailChat could not start. Read the error above and README.md.
echo If needed, install Python from https://www.python.org/downloads/windows/
echo Select the Python launcher during installation, then try again.
pause
exit /b 1
