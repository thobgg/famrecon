# famrecon auf einem Windows-Rechner bauen oder starten, ohne GitHub

Dasselbe Muster wie bei app4webtrees: Der Quelltext kommt als Git-Bündel, drei Doppelklick-Dateien
erledigen den Rest. Am Linux-Rechner `make bundle` ausführen; das legt `famrecon.bundle` in diesen Ordner. Liegt
`AI-Projects` über die NAS auch auf dem Windows-Rechner, ist das Bündel dort nach dem Abgleich von selbst da;
sonst den ganzen Ordner `werkzeuge/windows` kopieren.

1. **windows-einrichten.cmd**, einmalig, Rechtsklick → „Als Administrator ausführen":
   installiert Python 3.12 und Git über winget. Entfällt, wenn beides schon da ist.
2. **windows-bauen.cmd**, Doppelklick: holt den Stand aus dem Bündle nach `C:\famrecon\famrecon`,
   legt eine Python-Umgebung an, lässt die Tests laufen und baut `famrecon.exe` (PyInstaller, ohne
   Konsolenfenster). Ergebnis in `dist\` und als Kopie neben dem Skript. Protokoll: `bauen.log`.
3. **windows-starten.cmd**, Doppelklick: wie 2, aber ohne exe. Holt den neuen Stand und startet famrecon
   direkt aus dem Quelltext. Für Rückmelde-Runden: neues Bündle kopieren, doppelklicken, fertig.

Die exe ist nicht signiert; Windows warnt beim ersten Start vor einem unbekannten Herausgeber
(„Weitere Informationen" → „Trotzdem ausführen"). Beenden über den Knopf oben rechts in der Oberfläche;
Meldungen stehen in `famrecon.log` im Datenordner.
