@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python 3.11 virtual environment first; see README.md.
  exit /b 1
)
".venv\Scripts\python.exe" -m cockpit.launch
exit /b %errorlevel%
