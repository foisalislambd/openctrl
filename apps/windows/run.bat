@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  if errorlevel 1 (
    echo Python 3.12 is required. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install -q -r requirements.txt
if errorlevel 1 (
  echo Could not install OpenCtrl.
  pause
  exit /b 1
)
if not exist .venv\Scripts\pythonw.exe (
  echo This Python install has no windowed interpreter.
  .venv\Scripts\python.exe main.py
  pause
  exit /b 1
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0main.py"
