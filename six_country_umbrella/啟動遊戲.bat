@echo off
cd /d "%~dp0"
start "俚雨遊戲" http://127.0.0.1:8766/index.html
python main.py
if errorlevel 1 pause
