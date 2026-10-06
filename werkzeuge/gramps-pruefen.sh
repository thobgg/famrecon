#!/bin/bash
# gramps-pruefen.sh - unabhaengige Strukturpruefung der GEDCOM durch Gramps (lokal), uebernommen aus db-blank:
# eigene Pruefregeln und Ahnenblatt-Simulator pruefen Daten und Plausibilitaet, nicht die Dateistruktur.
#
#   ./gramps-pruefen.sh [datei.ged]      Import-Pruefung (Pflicht vor Weitergabe)
#   ./gramps-pruefen.sh datei.ged -voll  zusaetzlich die Plausibilitaetspruefung
set -u
DATEI="${1:-ausgabe/projekt.ged}"
VOLL="${2:-}"
HIER="$(cd "$(dirname "$0")" && pwd)"
export GRAMPSHOME="$HIER/tmp/gramps-pruefung"
rm -rf "$GRAMPSHOME"; mkdir -p "$GRAMPSHOME"
LOG="$HIER/tmp/gramps-pruefung.log"

[[ -f "$DATEI" ]] || { echo "Datei fehlt: $DATEI" >&2; exit 2; }
command -v gramps >/dev/null || { echo "gramps ist nicht installiert (apt install gramps)" >&2; exit 2; }

echo "Gramps liest $DATEI (dauert ein paar Minuten) …"
gramps -q -C "Pruefung" -i "$DATEI" > "$LOG" 2>&1
FEHLER=$(grep -cE "^Fehler:" "$LOG" || true)
if grep -qE "Keine Fehler entdeckt|0 Fehler entdeckt|Importbericht: 0 " "$LOG" || ! grep -qE "Fehler entdeckt" "$LOG"; then
    echo "✓ Struktur in Ordnung: Gramps meldet keine Fehler."
elif grep -qE "Traceback|Error" "$LOG"; then
    # Ein Absturz ist kein Freispruch.
    echo "✗ Gramps ist abgestuerzt, keine Aussage. Letzte Zeilen:"
    grep -vE "Gtk|Glade" "$LOG" | tail -3
    FEHLER=1
else
    echo "✗ Gramps meldet $FEHLER Strukturfehler. Auszug:"
    grep -E "^Fehler:|nicht in sich geschlossen" "$LOG" | head -10
    [[ "$FEHLER" == "0" ]] && FEHLER=1
fi

if [[ "$VOLL" == "-voll" ]]; then
    echo; echo "Plausibilitaetspruefung von Gramps (eigene Regeln, zum Vergleich):"
    gramps -q -O "Pruefung" -a tool -p name=verify > "$HIER/tmp/gramps-verify.log" 2>&1
    python3 - "$HIER/tmp/gramps-verify.log" <<'PY'
import sys, re, collections
k = collections.Counter()
for z in open(sys.argv[1], encoding="utf-8"):
    m = re.match(r"^([EW]): ([^,]+),", z.strip())
    if m:
        k[(m.group(1), m.group(2))] += 1
print(f"   {sum(k.values())} Befunde")
for (sw, t), n in k.most_common(12):
    print(f"   {n:5} {sw}  {t[:60]}")
PY
fi
rm -rf "$GRAMPSHOME"
[[ "$FEHLER" == "0" ]] || exit 1
