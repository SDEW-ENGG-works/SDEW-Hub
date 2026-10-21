@echo off
rem Creates 5 DUMMY Sales invoices in the Tally company whose name contains TEST (never the real books).
rem   tally_dummy.bat          -> create
rem   tally_dummy.bat delete   -> delete them again
cd /d "%~dp0"
if "%1"=="delete" (python tools\tally_dummy.py delete) else (python tools\tally_dummy.py create)
echo.
pause
