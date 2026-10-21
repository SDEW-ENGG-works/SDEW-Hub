@echo off
rem Lets the SDEW Hub website read the Tally on THIS computer. Keep the window open.
rem First time: run  python tools\tally_bridge.py --startup   to start it with Windows.
cd /d "%~dp0"
python tools\tally_bridge.py %*
pause
