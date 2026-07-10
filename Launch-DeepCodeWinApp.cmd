@echo off
setlocal
cd /d "%~dp0"
python run_app.py
if errorlevel 1 pause
