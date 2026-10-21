@echo off
cd /d "%~dp0"
rem The first start copies all data from the old apps by itself (see the window).
start "" http://localhost:8050
python server.py
pause
