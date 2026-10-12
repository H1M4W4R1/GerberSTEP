@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Install first: py -3.12 -m venv .venv
  echo Then: .venv\Scripts\python.exe -m pip install -e .
  pause
  exit /b 1
)
start "GerberSTEP" ".venv\Scripts\pythonw.exe" "main.py" %*
