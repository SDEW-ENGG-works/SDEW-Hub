@echo off
cd /d "%~dp0"
echo Copies the data of SupplementaryBill (this PC), CHEP and DQMS (their Turso cloud databases) into the hub again.
echo The hub database is backed up first to data\backups\.
python tools\import_from_apps.py
python tools\verify_hub.py
pause
