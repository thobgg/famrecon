@echo off
cd /d "%~dp0"
py -3 -m famrecon start || python -m famrecon start
pause
