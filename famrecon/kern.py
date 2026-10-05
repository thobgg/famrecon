"""Der Kern: aus den Feldern eines Eintrags die Personen in Normalform bauen.

Der Katalog kennt viele Felder, damit jede Spalte einen Platz findet. Der
Kern rechnet nur mit diesen Merkmalen je Person:

    name, vorname (plus Kirchenbuchform _kb), geschlecht, beruf, herkunft,
    alter, stand, geburt_datum, konfession, geburtsname, bemerkung
    und die Marker verstorben / unsicher / unbekannt / totgeburt

und je Eintrag mit dem Leitdatum (jahr, monat, tag). Alles andere wird
mitgefuehrt und spaeter ausgegeben, entscheidet aber nichts.

    famrecon bau ...        ruft personen_bauen() nach dem Einlesen
    famrecon personen db    zeigt die Personen eines Projekts
"""
from . import katalog, normalform

KERN = ["name", "vorname", "geschlecht", "beruf", "herkunft", "alter", "stand", "geburt_datum", "konfession",
        "geburtsname", "bemerkung", "totgeburt", "verzogen"]
GESCHLECHT_ROLLE = {"vater": "M", "mutter": "F", "braeutigam": "M", "braut": "F"}
GESCHLECHT_WERT = {"m": "M", "f": "F", "w": "F", "männlich": "M", "weiblich": "F", "male": "M", "female": "F"}


def pfade(register):
    out = []
    for h in katalog.HAUPTROLLEN[register]:
        out.append(h)
        out += [f"{h}_{u}" for u in katalog.UNTERROLLEN[h]]
    return out


def person_aus_feldern(pfad, felder, register):
    """felder: {feldname: (wert, roh)} des Eintrags -> dict oder None, wenn nichts da ist."""
    def w(merkmal):
        return (felder.get(f"{pfad}_{merkmal}") or (None, None))[0]
    roh = []
    p = normalform.person_zerlegen((felder.get(pfad) or (None, None))[0])
    if p["roh"]:
        roh.append(p["roh"])
    for merkmal in ("name", "vorname"):
        wert = w(merkmal)
        roh_wert = (felder.get(f"{pfad}_{merkmal}") or (None, None))[1]
        if not wert and roh_wert and normalform.marker(roh_wert)[1]["unbekannt"]:
            p["unbekannt"] = True                            # "NN" stand als Leerwort in der Zuordnung
        if wert:
            roh.append(wert)
            bereinigt, flags = normalform.marker(wert)
            if normalform.TOTGEBURT.search(wert):
                p["totgeburt"] = True
                bereinigt = normalform.geschlechtswort_entfernen(normalform.TOTGEBURT.sub("", wert))
            for k, v in flags.items():
                if v:
                    p[k] = v
            p[merkmal] = bereinigt or None
    p["name_kb"] = w("name_kb")
    p["vorname_kb"] = w("vorname_kb")
    if p["name"] is None and p["name_kb"] and not p["unbekannt"]:
        p["name"] = normalform.marker(p["name_kb"])[0] or None
    if p["vorname"] is None and p["vorname_kb"] and not p.get("unbekannt_vorname"):
        p["vorname"] = normalform.marker(p["vorname_kb"])[0] or None
    normalform.partikel_umsetzen(p)
    for merkmal in ("beruf", "herkunft", "stand", "konfession", "bemerkung", "verzogen"):
        wert = w(merkmal)
        if wert:
            if merkmal in ("beruf", "herkunft"):             # "Bauknecht, Wittwer": Stand und Sterbevermerk herausziehen
                wert, flags = normalform.marker(wert)
                for k in ("stand", "verstorben"):
                    if flags[k]:
                        p[k] = flags[k]
            if wert:
                p[merkmal] = f"{p[merkmal]}; {wert}" if p.get(merkmal) and merkmal in ("beruf", "bemerkung") else wert
    if w("totgeburt") and str(w("totgeburt")).lower() in ("t", "x", "ja", "1", "totgeburt", "todgeburt"):
        p["totgeburt"] = True
    stand = (p.get("stand") or "").lower()
    if stand in ("verstorben", "gestorben", "tot"):
        p["verstorben"] = True
    # Geschlecht: Feld > Marker > Rolle > Vorname
    g = GESCHLECHT_WERT.get(str(w("geschlecht") or "").lower())
    rolle = pfad.split("_")[-1]
    p["geschlecht"] = g or p.get("geschlecht") or GESCHLECHT_ROLLE.get(rolle) or normalform.geschlecht_aus_vorname(p["vorname"])
    if pfad.endswith("_vorehe"):
        p["geschlecht"] = "M" if pfad.startswith("braut") else "F"
    # Alter und Geburt
    p["alter_tage"] = normalform.alter_tage(w("alter") or w("alter_kb"))
    gd = normalform.datum_zerlegen(w("geburt_datum"))
    p["geburt"] = gd
    p["geburt_praefix"] = (w("geburt_datum_praefix") or "").upper() or normalform.datum_praefix(w("geburt_datum")) if gd else None
    p["ref"] = w("ref")
    if any([p["name"], p["vorname"], p["unbekannt"], p["totgeburt"], p["beruf"]]):
        p["roh"] = " | ".join(roh) or None
        return p
    return None


def personen_bauen(con):
    """Tabelle person neu fuellen. Gibt {register: anzahl} zurueck."""
    con.execute("DELETE FROM person")
    zaehler = {}
    eintraege = con.execute("SELECT id, register, jahr, monat, tag FROM eintrag").fetchall()
    for e in eintraege:
        felder = {r["name"]: (r["wert"], r["roh"]) for r in
                  con.execute("SELECT name, wert, roh FROM feld WHERE eintrag=?", (e["id"],))}
        for pfad in pfade(e["register"]):
            p = person_aus_feldern(pfad, felder, e["register"])
            if not p:
                continue
            # Verstorbener: Geburt aus Sterbedatum und Alter rechnen, wenn kein Geburtsdatum da ist
            if pfad == "verstorbener":
                rv = normalform.datum_zerlegen((felder.get("geburt_datum_rv") or (None,))[0])
                if rv:
                    p["geburt"], p["geburt_praefix"] = rv, ((felder.get("geburt_datum_rv_praefix") or ("",))[0] or "").upper() or None
                elif p["alter_tage"] is not None and e["jahr"]:
                    d = normalform.datum_minus_tage((e["jahr"], e["monat"], e["tag"]), p["alter_tage"])
                    p["geburt"], p["geburt_praefix"] = (d.year, d.month, d.day), "CAL"
                    if p["alter_tage"] >= 365:              # Jahresangaben sind grob: nur Jahr
                        p["geburt"] = (d.year, None, None)
            if pfad == "kind":
                geb = normalform.datum_zerlegen((felder.get("geburt_datum") or (None,))[0])
                if geb:
                    p["geburt"], p["geburt_praefix"] = geb, None
            gj, gm, gt = p["geburt"] or (None, None, None)
            con.execute(
                "INSERT INTO person(eintrag, pfad, name, vorname, name_kb, vorname_kb, name_schl, vorname_kanon, geschlecht, "
                "beruf, herkunft, stand, konfession, geburtsname, verstorben, unsicher, unbekannt, totgeburt, alter_tage, "
                "geburt_jahr, geburt_monat, geburt_tag, geburt_praefix, bemerkung, ref, roh) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (e["id"], pfad, p["name"], p["vorname"], p["name_kb"], p["vorname_kb"],
                 normalform.koelner(p["name"]) or None, normalform.vorname_kanon(p["vorname"]) or None, p["geschlecht"],
                 p.get("beruf"), p.get("herkunft"), p.get("stand"), p.get("konfession"), p.get("geburtsname"),
                 int(bool(p["verstorben"])), int(bool(p["unsicher"])), int(bool(p["unbekannt"])), int(bool(p["totgeburt"])),
                 p["alter_tage"], gj, gm, gt, p["geburt_praefix"], p.get("bemerkung"), p.get("ref"), p["roh"]))
            zaehler[e["register"]] = zaehler.get(e["register"], 0) + 1
    con.commit()
    return zaehler


def zeigen(con, register=None, limit=50):
    sql = ("SELECT e.register, e.jahr, p.pfad, p.name, p.vorname, p.geschlecht, p.beruf, p.stand, p.geburtsname, "
           "p.verstorben, p.unsicher, p.unbekannt, p.totgeburt, p.alter_tage, p.geburt_jahr, p.geburt_praefix, p.name_schl "
           "FROM person p JOIN eintrag e ON e.id=p.eintrag" + (" WHERE e.register=?" if register else "") +
           " ORDER BY e.register, e.jahr, e.id, p.id LIMIT ?")
    for r in con.execute(sql, ([register] if register else []) + [limit]):
        marker = "".join(m for m, f in (("†", r["verstorben"]), ("?", r["unsicher"]), ("NN", r["unbekannt"]), ("✝geb", r["totgeburt"])) if f)
        geb = f"*{r['geburt_praefix'] or ''}{r['geburt_jahr']}" if r["geburt_jahr"] else ""
        print(f"{r['register']:6} {r['jahr'] or '':4} {r['pfad']:24} {(r['name'] or '-'):22} {(r['vorname'] or '-'):28} "
              f"{r['geschlecht'] or '-'} {marker:5} {geb:9} {r['stand'] or '':10} {r['beruf'] or ''}"[:160])
