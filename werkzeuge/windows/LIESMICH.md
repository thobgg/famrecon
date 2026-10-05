# famrecon.exe auf dem eigenen Windows-Rechner bauen

Zwei Wege führen zur Windows-Datei:

1. **GitHub** (ohne eigenen Windows-Rechner): Actions → „Pakete“ → „Run workflow“. Nach ein paar
   Minuten liegt `famrecon-windows.exe` unter „Artifacts“; bei einem veröffentlichten Release hängt
   der Workflow sie automatisch an.
2. **Laptop** (wie wtWin in app4webtrees): `windows-bauen.ps1` doppelklicken oder in PowerShell
   ausführen. Es erwartet `famrecon.bundle` neben sich (am Linux-Rechner: `git bundle create
   famrecon.bundle main`) oder einen Klon unter `C:\famrecon\famrecon`. Braucht Python 3.11+ und Git.
   Ergebnis: `C:\famrecon\famrecon\dist\famrecon.exe`, Kopie neben dem Skript. Protokoll in `bauen.log`.

Die exe ist nicht signiert; Windows warnt beim ersten Start vor einem unbekannten Herausgeber
(„Weitere Informationen“ → „Trotzdem ausführen“). Beim ersten Start entsteht `daten\` neben der exe.
