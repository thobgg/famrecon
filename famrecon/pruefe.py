"""Abgleich GEDCOM gegen die Eintraege: Ist jede Tabellenzeile in der Ausgabe angekommen?

    famrecon pruefe daten/projekt.db ausgabe/projekt.ged

Je Eintrag wird die Zeile in der GEDCOM gesucht, die sie belegen muss:
    Taufe   ein INDI mit BIRT oder CHR und der Fundstelle dieses Eintrags
    Trauung ein FAM mit MARR und der Fundstelle
    Tod     ein INDI mit DEAT oder BURI und der Fundstelle
Dazu: Namen der Hauptpersonen stehen in diesem Record; HUSB/WIFE/CHIL/FAMC/FAMS zeigen auf
vorhandene Records. Exit 1, wenn etwas fehlt. Das ist die Zusage: nichts geht verloren.
"""
import re
import sys

from . import simulation


def pruefen(con, ged):
    indis, fams = simulation.lesen(ged)
    fehler = []

    def fundstellen(rec):
        return {s["wert"] for ev in rec["kinder"] for s in simulation.sub(ev, "SOUR") for s in simulation.sub(s, "PAGE")} | \
               {s["wert"] for s in simulation.sub(rec, "SOUR") for s in simulation.sub(s, "PAGE")}

    def fund(e, fl):
        return fl.get("zitat") or " ".join(x for x in (fl.get("kb"), f"S. {fl['seite']}" if fl.get("seite") else None,
                                                        f"Nr. {fl['lfd_nr']}" if fl.get("lfd_nr") else None) if x) or f"Zeile {e['zeile']}"

    fund_indi, fund_fam = {}, {}
    for x, r in indis.items():
        for f in fundstellen(r):
            fund_indi.setdefault(f, []).append(x)
    for x, r in fams.items():
        for f in fundstellen(r):
            fund_fam.setdefault(f, []).append(x)
    n = {"taufe": 0, "ehe": 0, "tod": 0}
    for e in con.execute("SELECT * FROM eintrag"):
        fl = {r["name"]: r["wert"] for r in con.execute("SELECT name, wert FROM feld WHERE eintrag=? AND wert IS NOT NULL", (e["id"],))}
        fs = fund(e, fl)
        n[e["register"]] += 1
        if e["register"] == "ehe":
            if fs not in fund_fam:
                fehler.append(f"ehe {e['jahr']} {fs}: keine Familie mit dieser Fundstelle")
            continue
        treffer = fund_indi.get(fs, [])
        tag = ("BIRT", "CHR") if e["register"] == "taufe" else ("DEAT", "BURI")
        if not any(simulation.sub(indis[x], t) for x in treffer for t in tag):
            fehler.append(f"{e['register']} {e['jahr']} {fs}: kein INDI mit {'/'.join(tag)} und dieser Fundstelle")
        # Name der Hauptperson muss im Record stehen
        rolle = "kind" if e["register"] == "taufe" else "verstorbener"
        p = con.execute("SELECT name, vorname FROM person p WHERE p.eintrag=? AND p.pfad=?", (e["id"], rolle)).fetchone()
        if p and treffer:
            namen = " ".join(k["wert"] for x in treffer for k in indis[x]["kinder"] if k["tag"] == "NAME")

            for teil in (p["name"], p["vorname"]):
                if teil and teil not in namen:
                    fehler.append(f"{e['register']} {e['jahr']} {fs}: {teil!r} steht nicht im Namen von {treffer}")
    # Zeiger
    for x, r in indis.items():
        for tag in ("FAMC", "FAMS"):
            for k in simulation.sub(r, tag):
                if k["wert"] not in fams:
                    fehler.append(f"{x} {tag} zeigt auf {k['wert']}, das es nicht gibt")
    for x, r in fams.items():
        for tag in ("HUSB", "WIFE", "CHIL"):
            for k in simulation.sub(r, tag):
                if k["wert"] not in indis:
                    fehler.append(f"{x} {tag} zeigt auf {k['wert']}, das es nicht gibt")
    return n, fehler


def main(con, ged):
    n, fehler = pruefen(con, ged)
    print(f"Eintraege: " + ", ".join(f"{k} {v}" for k, v in n.items()) + f"; Fehler: {len(fehler)}")
    for f in fehler[:40]:
        print("  " + f)
    return 1 if fehler else 0
