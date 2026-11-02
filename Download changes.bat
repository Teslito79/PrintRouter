@echo off
rem Downloads the latest version of PrintRouter from GitHub.
cd /d "%~dp0"
echo === Download latest changes from GitHub ===
echo.

git pull
if errorlevel 1 (
    echo.
    echo Could not download. If it mentions local changes, run "Upload changes.bat" first, then try again.
    pause
    exit /b 1
)

echo.
echo Done. You have the latest version.
pause
