#!/usr/bin/env python3
"""Regressionstest: viele Projekte neu bauen, verknuepfen und auf Widersprueche pruefen;
Fehler je 1.000 Personen gegen einen frueheren Lauf vergleichen.

    python3 werkzeuge/regression.py LISTE --name "vor Tod-Sperre"   alle Projekte rechnen
    python3 werkzeuge/regression.py LISTE --nur a,b --jobs 2         nur einige, zwei zugleich
    python3 werkzeuge/regression.py LISTE --bericht [--gegen NAME]   nur die Tabelle zeigen

LISTE ist eine Textdatei mit einer Zeile je Projektordner (relativ zur Liste, `#` kommentiert).
Ein Projektordner enthaelt zuordnung.toml und die dort genannten Tabellen. Liegt dort auch
referenz.ged, misst `famrecon vergleiche` zusaetzlich Praezision und Vollstaendigkeit; eine
Datei referenz.txt kann Optionen dafuer nennen (z. B. `--inhalt --ab 1747`), vorne auch eine
andere GEDCOM-Datei des Ordners (`familienbuch.ged --inhalt`).

Die Projektordner bleiben unberuehrt (Urteile in einer vorhandenen projekt.db gehen nicht
verloren): alles Erzeugte landet neben der Liste in laeufe/<projekt>/. Jeder Lauf haengt seine
Zahlen an laeufe/laeufe.csv an. Verglichen wird mit dem ersten Lauf dieser Projekte, sonst mit --gegen NAME.

Die Pruefregeln kommen aus pruefungen/plausibilitaet.py. Sie brauchen keine Wahrheit: sie
zaehlen Widersprueche im Ergebnis (Tod vor Taufe, Kind nach dem Tod der Mutter, Ehepartner
als Elter und Kind ...). Verschmelzungen ohne Widerspruch sehen sie nicht; dafuer die
Projekte mit referenz.ged.
"""
import argparse
import csv
import datetime
import os
import re
import subprocess
import sys
import time
import tomllib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WURZEL, "pruefungen"))
import plausibilitaet  # noqa: E402

FELDER = ["name", "zeit", "commit", "projekt", "groesse", "wert"]


def projekte_lesen(liste):
    """Zeilen der Liste -> [(kurzname, ordner)]; der Kurzname ist der Pfad mit '-' statt '/'."""
    basis = os.path.dirname(os.path.abspath(liste))
    erg = []
    for zeile in open(liste, encoding="utf-8"):
        zeile = zeile.split("#")[0].strip()
        if zeile:
            ordner = os.path.normpath(os.path.join(basis, zeile))
            kurz = os.path.relpath(ordner, basis) if ordner.startswith(basis + os.sep) else os.path.basename(ordner)
            erg.append((kurz.replace(os.sep, "-"), ordner))
    return erg


def tabellen(ordner):
    """Die in zuordnung.toml genannten Dateien; ohne Dateinamen alle Tabellen des Ordners
    (famrecon nimmt dann aus jeder nur die Blaetter, die die Zuordnung kennt)."""
    with open(os.path.join(ordner, "zuordnung.toml"), "rb") as fh:
        z = tomllib.load(fh)
    namen = [r["datei"] for r in z.get("register", {}).values() if isinstance(r, dict) and r.get("datei")]
    if namen and len(namen) == len([r for r in z.get("register", {}).values() if isinstance(r, dict)]):
        return [os.path.join(ordner, n) for n in dict.fromkeys(namen)]
    return sorted(os.path.join(ordner, n) for n in os.listdir(ordner)
                  if n.lower().endswith((".csv", ".tsv", ".xlsx")) and not n.startswith("~$"))


def famrecon(*args):
    """Ein famrecon-Befehl aus diesem Repo; Ausgabe als Text, Fehler als Ausnahme."""
    r = subprocess.run([sys.executable, "-m", "famrecon", *args], cwd=WURZEL,
                       capture_output=True, text=True, env=dict(os.environ, PYTHONPATH=WURZEL))
    if r.returncode:
        raise RuntimeError(f"famrecon {args[0]}: {(r.stderr or r.stdout)[-400:]}")
    return r.stdout


def rechnen(kurz, ordner, aus):
    """Ein Projekt: bauen, verknuepfen, GEDCOM, Pruefregeln, ggf. Abgleich -> {groesse: wert}."""
    ziel = os.path.join(aus, kurz)
    os.makedirs(ziel, exist_ok=True)
    db, ged = os.path.join(ziel, "projekt.db"), os.path.join(ziel, "projekt.ged")
    for alt in (db, db + "-wal", db + "-shm"):
        if os.path.exists(alt):
            os.remove(alt)
    t0 = time.time()
    famrecon("bau", os.path.join(ordner, "zuordnung.toml"), *tabellen(ordner), "-o", db)
    out = famrecon("verknuepfen", db)
    sek = time.time() - t0
    famrecon("gedcom", db, "-o", ged)
    w = {"sekunden": round(sek, 1)}
    m = re.search(r"-> (\d+) Identitaeten, (\d+) Familien", out)
    if m:
        w["familien"] = int(m.group(2))
    w["personen"] = sum(1 for z in open(ged, encoding="utf-8") if re.match(r"0 @[^@]+@ INDI", z))
    # Pruefregeln still laufen lassen, Treffer als Tabelle fuer die Durchsicht behalten
    treffer = os.path.join(ziel, "treffer.csv")
    subprocess.run([sys.executable, os.path.join(WURZEL, "pruefungen", "plausibilitaet.py"), ged, "--tsv", treffer],
                   capture_output=True, text=True)        # eigener Prozess: die Laeufe teilen sich kein stdout
    zaehler = defaultdict(int)
    with open(treffer, encoding="utf-8") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            zaehler[r["regel"]] += 1
    for regel in plausibilitaet.lies_regeln():
        w["R" + regel["id"]] = zaehler.get(regel["id"], 0)
    ref, opt = os.path.join(ordner, "referenz.ged"), []
    if os.path.exists(os.path.join(ordner, "referenz.txt")):
        opt = open(os.path.join(ordner, "referenz.txt"), encoding="utf-8").read().split()
        if opt and opt[0].lower().endswith(".ged"):        # andere Referenzdatei als referenz.ged
            ref, opt = os.path.join(ordner, opt[0]), opt[1:]
    if os.path.exists(ref):
        v = famrecon("vergleiche", db, ref, *opt, "--xlsx", os.path.join(ziel, "abweichungen.xlsx"))
        n = re.search(r"(\d+) gemeinsame Einträge", v)
        m = re.search(r"Präzision ([\d.]+), Vollständigkeit ([\d.]+)", v)
        if not n or not int(n.group(1)):        # ohne Kopplung waeren 1,000/1,000 eine leere Aussage
            raise RuntimeError("Abgleich ohne gemeinsame Einträge; referenz.txt pruefen (--inhalt?)")
        if m:
            w["praezision"], w["vollstaendigkeit"] = float(m.group(1)), float(m.group(2))
    return w


def git_commit():
    """Kurzer Commit-Stand, mit * wenn der Arbeitsstand davon abweicht."""
    k = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=WURZEL, capture_output=True, text=True).stdout.strip()
    d = subprocess.run(["git", "status", "--porcelain", "famrecon"], cwd=WURZEL, capture_output=True, text=True).stdout
    return k + ("*" if d.strip() else "")


def laeufe_lesen(pfad):
    """laeufe.csv -> {name: {projekt: {groesse: wert}}} in Reihenfolge der Laeufe."""
    erg = {}
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as fh:
            for r in csv.DictReader(fh, delimiter=";"):
                erg.setdefault(r["name"], {}).setdefault(r["projekt"], {})[r["groesse"]] = float(r["wert"])
    return erg


def bericht(laeufe, jetzt, gegen, projekte):
    """Tabelle: je Projekt Fehler je 1.000 Personen jetzt und vorher, dann je Regel ueber alle."""
    regeln = {r["id"]: r for r in plausibilitaet.lies_regeln()}
    a, b = laeufe[gegen], laeufe[jetzt]
    gemeinsam = [k for k, _ in projekte if k in a and k in b]

    def fehler(w, nur_bau=False):
        return sum(v for g, v in w.items() if g.startswith("R") and regeln.get(g[1:], {}).get("schwere") == "fehler"
                   and not (nur_bau and plausibilitaet.ist_vorlage(regeln[g[1:]])))

    zeilen = [f"Lauf «{jetzt}» gegen «{gegen}», {len(gemeinsam)} Projekte; Fehler je 1.000 Personen", "",
              f"{'Projekt':24} {'Personen':>9} {'vorher':>9} {'Fehler':>7} {'vorher':>7} {'Bau':>6} {'vorher':>6}  P / V"]
    summe = defaultdict(float)
    for k in gemeinsam:
        x, y = a[k], b[k]
        px, py = x.get("personen", 1) or 1, y.get("personen", 1) or 1
        pv = f"  {y['praezision']:.3f}/{y['vollstaendigkeit']:.3f} (vorher {x.get('praezision', 0):.3f}/{x.get('vollstaendigkeit', 0):.3f})" \
            if "praezision" in y else ""
        zeilen.append(f"{k[:24]:24} {py:9.0f} {px:9.0f} {1000 * fehler(y) / py:7.1f} {1000 * fehler(x) / px:7.1f} "
                      f"{1000 * fehler(y, True) / py:6.1f} {1000 * fehler(x, True) / px:6.1f}{pv}")
        for g in set(x) | set(y):
            summe["a" + g] += x.get(g, 0)
            summe["b" + g] += y.get(g, 0)
    pa, pb = summe["apersonen"] or 1, summe["bpersonen"] or 1
    zeilen += ["", f"{'Gesamt':24} {pb:9.0f} {pa:9.0f} "
               f"{1000 * sum(summe['b' + 'R' + i] for i, r in regeln.items() if r['schwere'] == 'fehler') / pb:7.1f} "
               f"{1000 * sum(summe['a' + 'R' + i] for i, r in regeln.items() if r['schwere'] == 'fehler') / pa:7.1f}",
               "", "Regeln, die sich bewegt haben (je 1.000 Personen; F = Fehler, w = Warnung):"]
    bewegt = []
    for i, r in regeln.items():
        va, vb = 1000 * summe["aR" + i] / pa, 1000 * summe["bR" + i] / pb
        if abs(vb - va) >= 0.01:
            bewegt.append((vb - va, i, r, va, vb))
    for d, i, r, va, vb in sorted(bewegt, key=lambda t: t[0], reverse=True):
        zeilen.append(f"  {'HOCH ' if d > 0 else 'runter'} {i} {'F' if r['schwere'] == 'fehler' else 'w'} "
                      f"{va:7.2f} -> {vb:7.2f}  {r['frage'][:70]}")
    if not bewegt:
        zeilen.append("  keine")
    return "\n".join(zeilen)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("liste")
    ap.add_argument("--name", help="Name dieses Laufs (Vorgabe: Commit und Uhrzeit)")
    ap.add_argument("--nur", help="nur diese Projekte (Kurznamen, mit Komma)")
    ap.add_argument("--jobs", type=int, default=4, help="so viele Projekte zugleich (Speicher!)")
    ap.add_argument("--bericht", action="store_true", help="nichts rechnen, nur vergleichen")
    ap.add_argument("--gegen", help="Vergleichslauf (Vorgabe: der erste)")
    a = ap.parse_args(argv)
    projekte = projekte_lesen(a.liste)
    if a.nur:
        projekte = [p for p in projekte if p[0] in a.nur.split(",")]
    aus = os.path.join(os.path.dirname(os.path.abspath(a.liste)), "laeufe")
    os.makedirs(aus, exist_ok=True)
    pfad = os.path.join(aus, "laeufe.csv")
    if not a.bericht:
        commit = git_commit()
        name = a.name or f"{commit} {datetime.datetime.now():%d.%m. %H:%M}"
        zeit = f"{datetime.datetime.now():%Y-%m-%d %H:%M}"
        neu = not os.path.exists(pfad)
        with open(pfad, "a", encoding="utf-8", newline="") as fh, ThreadPoolExecutor(a.jobs) as pool:
            w = csv.DictWriter(fh, FELDER, delimiter=";", lineterminator="\n")
            if neu:
                w.writeheader()
            auftraege = {k: pool.submit(rechnen, k, o, aus) for k, o in projekte}
            for k, f in auftraege.items():
                try:
                    werte = f.result()
                except Exception as e:      # ein kaputtes Projekt haelt die anderen nicht auf
                    print(f"{k}: FEHLER {e}", flush=True)
                    continue
                for g, v in werte.items():
                    w.writerow(dict(name=name, zeit=zeit, commit=commit, projekt=k, groesse=g, wert=v))
                fh.flush()
                print(f"{k}: {werte.get('personen', 0):.0f} Personen, {werte['sekunden']} s", flush=True)
    else:
        name = None
    laeufe = laeufe_lesen(pfad)
    if not laeufe:
        sys.exit("noch kein Lauf gespeichert")
    jetzt = name or list(laeufe)[-1]
    if jetzt not in laeufe:
        sys.exit(f"Lauf «{jetzt}» hat kein Projekt fertig gerechnet")
    kurz = {k for k, _ in projekte}
    gegen = a.gegen or next(n for n, w in laeufe.items() if kurz & set(w))
    text = bericht(laeufe, jetzt, gegen, projekte)
    print(text)
    open(os.path.join(aus, "bericht.txt"), "w", encoding="utf-8").write(text + "\n")


if __name__ == "__main__":
    main()
