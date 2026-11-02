@echo off
rem Saves every change in this folder and uploads it to GitHub.
cd /d "%~dp0"
echo === Upload changes to GitHub ===
echo.

git add -A
git diff --cached --quiet
if not errorlevel 1 (
    echo No new changes to upload.
    goto push
)

echo Changed files:
git status --short
echo.
set "NOTE="
set /p NOTE=Short note about what you changed, or just press Enter:
if not defined NOTE set "NOTE=Changes from %COMPUTERNAME% %date% %time%"
git commit -q -m "%NOTE%"
if errorlevel 1 goto failed

:push
rem Pick up anything uploaded from the other PC first, so the push isn't rejected.
git pull -q --no-rebase
if errorlevel 1 goto failed
git push -q
if errorlevel 1 goto failed

echo.
echo Done. Your changes are on GitHub.
pause
exit /b 0

:failed
echo.
echo Something went wrong. Read the message above, or ask Claude for help.
pause
exit /b 1
