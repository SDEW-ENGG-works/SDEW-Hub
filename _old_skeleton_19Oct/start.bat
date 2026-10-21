@echo off
cd /d "%~dp0"
if not exist legacy (
  echo First run: copying the existing apps into legacy\ ...
  python tools\setup_from_existing.py
)
start "" http://localhost:8050
python server.py
pause
