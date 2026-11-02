@echo off
rem Opens the PrintRouter window (no console window stays open).
cd /d "%~dp0"
start "" pythonw app.py
