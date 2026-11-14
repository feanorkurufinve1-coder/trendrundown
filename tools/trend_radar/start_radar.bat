@echo off
cd /d "%~dp0"
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if not defined PY (python --version >nul 2>nul && set PY=python)
if not defined PY (
  echo Python not found. Install it from https://www.python.org/downloads/
  pause
  exit /b
)
echo Using Python: %PY%
echo Trend radar is running. Do not close this window.
%PY% trend_radar.py
pause
