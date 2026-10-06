@echo off
rem Doppelklick genuegt (kein Administrator noetig). Startet windows-bauen.ps1; Protokoll: bauen.log daneben.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-bauen.ps1"
echo.
echo Beendet mit Code %ERRORLEVEL%. Protokoll: %~dp0bauen.log
pause
