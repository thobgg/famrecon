# famrecon - direkt aus dem Quelltext starten, ohne exe (fuer Rueckmelde-Runden, siehe LIESMICH.md).
# Erwartet famrecon.bundle neben dem Skript oder einen Klon unter C:\famrecon\famrecon. Holt den neuen Stand,
# richtet einmalig eine Python-Umgebung ein und startet die Oberflaeche. Daten liegen in C:\famrecon\famrecon\daten.
$ErrorActionPreference = "Stop"
Start-Transcript -Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "starten.log") -Force | Out-Null
try {
$hier = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = "C:\famrecon\famrecon"
$bundle = Join-Path $hier "famrecon.bundle"
if (-not (Test-Path $bundle) -and (Test-Path (Join-Path $hier "..\..\out\famrecon.bundle"))) { $bundle = Join-Path $hier "..\..\out\famrecon.bundle" }
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python nicht gefunden - windows-einrichten.cmd ausfuehren oder von python.org installieren (3.11 oder neuer)." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git nicht gefunden - windows-einrichten.cmd ausfuehren oder von git-scm.com installieren." }
if (-not (Test-Path "$repo\pyproject.toml")) {
    if (-not (Test-Path $bundle)) { throw "famrecon.bundle liegt nicht neben dem Skript ($hier) und $repo ist kein Klon." }
    Write-Host "== Quelltext aus dem Bundle holen" -ForegroundColor Cyan
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $repo) | Out-Null
    git clone --branch main $bundle $repo
} elseif (Test-Path $bundle) {
    Write-Host "== Neuen Stand aus dem Bundle holen" -ForegroundColor Cyan
    Push-Location $repo
    git fetch $bundle main
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Das Bundle laesst sich nicht lesen." }
    git checkout -q -B main FETCH_HEAD
    Write-Host ("Stand: " + (git log -1 --format="%h %s"))
    Pop-Location
}
Push-Location $repo
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py.Source -3 -m venv .venv 2>$null; if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py.Source -m venv .venv } }
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip openpyxl
Write-Host "== famrecon startet; Beenden ueber den Knopf oben rechts in der Oberflaeche" -ForegroundColor Cyan
& ".venv\Scripts\python.exe" -m famrecon start
Pop-Location
} catch {
    Write-Host ""
    Write-Host "FEHLER: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
