@echo off
rem Rechtsklick -> "Als Administrator ausfuehren". Installiert Python und Git ueber winget; Protokoll: einrichten.log daneben.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows-einrichten.ps1"
echo.
echo Beendet mit Code %ERRORLEVEL%. Protokoll: %~dp0einrichten.log
pause
