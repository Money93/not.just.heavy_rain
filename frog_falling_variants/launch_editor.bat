@echo off
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
  "%LOCALAPPDATA%\Python\bin\python.exe" generate.py --editor
) else (
  py generate.py --editor
)
if errorlevel 1 pause
