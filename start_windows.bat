@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Create the Python 3.11 virtual environment first; see README.md.
  exit /b 1
)
echo Dashboard: http://127.0.0.1:8000 ^(open in your browser after startup^).
echo The checked-in dashboard bundle requires no Node process. Press Ctrl+C to stop.
".venv\Scripts\python.exe" -m cockpit.launch
exit /b %errorlevel%
