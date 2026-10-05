# famrecon - Windows-Datei (famrecon.exe) auf dem eigenen Laptop bauen.
# Dasselbe Muster wie windows-bauen.ps1 in app4webtrees: Quelltext aus einem Bundle oder Klon,
# Bau ausserhalb des NAS-Abgleichs, Protokoll in bauen.log neben dem Skript.
#
# Voraussetzungen: Python 3.11 oder neuer (python.org, "Add to PATH" anhaken) und Git.
# Erwartet famrecon.bundle neben dem Skript (git bundle create famrecon.bundle main) oder einen
# geklonten Ordner unter C:\famrecon\famrecon. Ergebnis: C:\famrecon\famrecon\dist\famrecon.exe
$ErrorActionPreference = "Stop"
Start-Transcript -Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "bauen.log") -Force | Out-Null
try {
$hier = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = "C:\famrecon\famrecon"
$bundle = Join-Path $hier "famrecon.bundle"

$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python nicht gefunden - von python.org installieren (3.11 oder neuer) und 'Add python.exe to PATH' anhaken." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "Git nicht gefunden - von git-scm.com installieren." }
Write-Host "Python: $($py.Source)"

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
Write-Host "== Python-Umgebung (einmalig: openpyxl, pyinstaller)" -ForegroundColor Cyan
if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py.Source -3 -m venv .venv 2>$null; if (-not (Test-Path ".venv\Scripts\python.exe")) { & $py.Source -m venv .venv } }
& ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip openpyxl pyinstaller
Write-Host "== Tests" -ForegroundColor Cyan
& ".venv\Scripts\python.exe" -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "Tests schlagen fehl - nicht bauen." }
Write-Host "== Bauen" -ForegroundColor Cyan
Remove-Item -Recurse -Force "dist","build" -ErrorAction SilentlyContinue
& ".venv\Scripts\python.exe" -m PyInstaller werkzeuge\famrecon.spec --noconfirm
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { throw "PyInstaller ist fehlgeschlagen (Code $code) - siehe oben." }

Write-Host ""
Write-Host "== Ergebnis" -ForegroundColor Green
$exe = "$repo\dist\famrecon.exe"
Write-Host $exe
Copy-Item $exe (Join-Path $hier "famrecon.exe") -Force
Write-Host "Kopie neben dem Skript: $(Join-Path $hier 'famrecon.exe')"
} catch {
    Write-Host ""
    Write-Host "FEHLER: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
} finally {
    Stop-Transcript | Out-Null
}
