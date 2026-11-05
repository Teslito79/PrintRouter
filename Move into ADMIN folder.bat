@echo off
rem One time: moves PrintRouter into an ADMIN subfolder and leaves a PrintRouter shortcut here.
rem This file is moved too, so it runs from a copy in the TEMP folder.
if /i "%~1"=="--temp" goto run
copy /y "%~f0" "%TEMP%\PrintRouter_move_admin.bat" >nul
copy /y "%~dp0tools\move_into_admin.ps1" "%TEMP%\PrintRouter_move_admin.ps1" >nul
"%TEMP%\PrintRouter_move_admin.bat" --temp "%~dp0."

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\PrintRouter_move_admin.ps1" -Root "%~2"
if not defined NOPAUSE pause
