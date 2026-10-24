@echo off
cd /d "%~dp0"
python editor_server.py
if errorlevel 1 pause
