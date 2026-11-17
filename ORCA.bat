@echo off
rem Opens ORCA (no console window stays open).
rem Uses Python 3.14, where the requirements are installed.
cd /d "%~dp0"
if /i "%~1"=="--no-update" goto start

py -3.14 already_open.py || goto start & rem ORCA is open: no pull under it.
rem Else update from GitHub (no internet/git: start what is here), start it.
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

:start
start "" pyw -3.14 app.py
