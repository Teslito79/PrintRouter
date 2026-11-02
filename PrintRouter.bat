@echo off
rem Opens the PrintRouter window (no console window stays open).
rem Uses Python 3.14, where the requirements are installed.
cd /d "%~dp0"

rem Get the latest version from GitHub first. With no internet, no git, or a
rem local change in the way, the app just starts the version it already has.
where git >nul 2>&1
if not errorlevel 1 (
    echo Checking for updates...
    set GIT_TERMINAL_PROMPT=0
    set GCM_INTERACTIVE=never
    git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=10 pull -q --ff-only
    if errorlevel 1 (
        echo Could not update. Starting the current version.
        timeout /t 3 >nul
    )
)

start "" pyw -3.14 app.py
