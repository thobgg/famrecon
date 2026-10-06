@echo off
rem Doppelklick: neuen Stand aus dem Bundle holen und famrecon direkt starten - ohne exe, ohne Installation.
rem Fuer Rueckmelde-Runden. Beenden ueber den Knopf in der Oberflaeche; Protokoll: starten.log daneben.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-starten.ps1"
echo.
echo Beendet mit Code %ERRORLEVEL%. Protokoll: %~dp0starten.log
pause
