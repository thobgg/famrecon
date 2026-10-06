# famrecon - Windows-Rechner zum Bauen einrichten (Schritt 1 der LIESMICH.md). Einmal als Administrator
# ueber windows-einrichten.cmd starten. Installiert Python 3.12 und Git ueber winget; mehr braucht famrecon nicht.
$ErrorActionPreference = "Stop"
Start-Transcript -Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "einrichten.log") -Force | Out-Null
try {
function Schritt($t) { Write-Host ""; Write-Host "== $t" -ForegroundColor Cyan }
Schritt "1/2 Python 3.12 und Git ueber winget"
winget install --id Python.Python.3.12 -e --accept-package-agreements --accept-source-agreements
winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
Schritt "2/2 Pruefen (neues Fenster noetig, damit der PATH greift)"
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) { & $py.Source -3 --version } else { Write-Host "py-Starter noch nicht im PATH - nach dem Schliessen dieses Fensters ist er da." -ForegroundColor Yellow }
if (Test-Path "C:\Program Files\Git\cmd\git.exe") { & "C:\Program Files\Git\cmd\git.exe" --version }
Write-Host ""
Write-Host "Fertig. Dieses Fenster schliessen, dann windows-bauen.cmd (exe bauen) oder windows-starten.cmd (ohne exe starten)." -ForegroundColor Green
} catch {
    Write-Host ""
    Write-Host "FEHLER: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
