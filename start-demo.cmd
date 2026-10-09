@echo off
rem Starts the backend (API + worker) and the frontend together. Ctrl+C stops everything.
rem Extra arguments are passed on, e.g.:  start-demo --prod
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [demo] Python virtual environment not found at .venv - see README.md for setup.
  exit /b 1
)
".venv\Scripts\python.exe" demo.py %*
