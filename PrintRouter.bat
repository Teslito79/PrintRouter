@echo off
rem Opens the PrintRouter window (no console window stays open).
rem Uses Python 3.14, where the requirements are installed.
cd /d "%~dp0"
start "" pyw -3.14 app.py
