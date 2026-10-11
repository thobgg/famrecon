"""GEDCOM 5.5.1 aus dem Projekt: Identitaeten als INDI, Familien als FAM, jedes Ereignis mit Quelle.

    famrecon gedcom daten/projekt.db -o ausgabe/projekt.ged

Drei Dinge, jedes mit festem Ort:
    Akt          was im Kirchenbuch steht: die Umschrift des Eintrags (Feld wortlaut), wo die Tabelle eine hat,
                 als Text der Fundstelle des Hauptereignisses (CHR, ersatzweise BIRT, DEAT, MARR): SOUR/DATA/TEXT
    Tabelle      die Zeile des Forschers: in der Projektdatei vollstaendig (feld, zelle); in der GEDCOM nur ueber
                 die Fundstelle (PAGE) und die Spalten ohne Feld, die als "Ueberschrift: Zellinhalt" unter die
                 Umschrift in denselben TEXT kommen. So wird nichts verworfen, und nichts steht doppelt.
    Deutung      nur in Standard-Tags, jeder mit Fundstelle; die Verknuepfung in der Struktur (INDI, FAM, FAMC/FAMS).
                 NOTE nur fuer famrecons eigene Vermerke (und vorerst Paten, Zeugen, Herkunft, Bemerkung, s. u.)

Was wo landet:
    NAME        Vorname /Nachname/; Geburtsname als erster Name, Ehename als zweiter (TYPE married)
                abweichende Schreibungen der Eintraege als weitere NAME mit TYPE aka
    SEX         aus dem Feld geschlecht (auch angekreuzte Spalten), sonst Rolle, sonst Vorname
    BIRT, CHR   aus dem Taufeintrag des Kindes (Datum, Ort), Taufpaten als NOTE unter CHR
    MARR        aus dem Traueintrag (Datum, Ort), Trauzeugen und Pfarrer als NOTE
    DEAT, BURI  aus dem Sterbeeintrag; Todesursache als CAUS; Alter als AGE
    OCCU        je Nennung mit Datum des Eintrags; Herkunft als NOTE
    SOUR/PAGE   je Ereignis: Quelle (Datei, Blatt) und Fundstelle (Buch, Seite, Nummer oder Zitat)
    SOUR/EVEN   Art des Eintrags (CHR, MARR, DEAT, BURI) und mit ROLE die Rolle der Person darin
                (CHIL, FATH, MOTH, HUSB, WIFE, SPOU; sonst beschrieben, etwa "(Braut: Vater)")
    NOTE        Bemerkungen der Eintraege; bei unsicherer Zuordnung ein Vermerk mit den Alternativen

Belege und uebernommene Werte:
    Name            unter NAME (Geburts- und Ehename) die Fundstelle, die ihn nennt: je Register die frueheste.
                    So ist der Geburtsname einer Mutter, die in der Taufe NN heisst, mit der Trauung belegt.
Was famrecon aus einem anderen Eintrag als Ereignis an die Person haengt, traegt die Fundstelle dieses
Eintrags (mit Rolle) und dort den Vermerk "... aus diesem Eintrag uebernommen (Verknuepfung: Stufe)":
    Geburt          ohne eigene Taufe aus Alter oder Geburtsdatum eines anderen Eintrags; ohne Beleg keine BIRT.
                    Das Taufdatum, das die Verknuepfung ersatzweise als Geburt rechnet, wird nie BIRT.
    Tod             aus dem Rueckverweis im Taufeintrag
    Kein QUAY: Gramps liest QUAY 2 als "hoch", also verlaesslicher als ein direkter Beleg.

Beteiligte:
    ASSO        Paten, Trauzeugen, Begraebniszeugen, die beteiligte.py eindeutig einer Person zugeordnet hat:
                beim Taeufling, den Brautleuten, dem Verstorbenen ASSO @Pate@ + RELA Pate|Trauzeuge|Zeuge mit
                Fundstelle; bei der Person selbst die Fundstelle mit ROLE (Pate). Die NOTE "Taufpaten: ..."
                bleibt, sie nennt alle, auch die nicht erkannten.

Geplant:
    Herkunft als RESI nur, wenn die Spalte ausdruecklich Wohnort heisst; sonst bleibt die NOTE
"""
import datetime as dt
import json

from . import __version__

MON = "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split()
HAUPTPFAD = {"taufe": ("kind",), "ehe": ("braeutigam", "braut"), "tod": ("verstorbener",)}   # wer das ASSO traegt
EVEN = {"taufe": "CHR", "ehe": "MARR", "tod": "DEAT"}      # Art des Eintrags in der Fundstelle (SOUR/EVEN)
ROLLE = {"kind": "CHIL", "vater": "FATH", "mutter": "MOTH", "braeutigam": "HUSB", "braut": "WIFE",
         "verstorbener_ehepartner": "SPOU"}              # GEDCOM-Rollen; alle anderen als (Beschreibung)
ROLLENWORT = {"kind": "Kind", "vater": "Vater", "mutter": "Mutter", "braeutigam": "Bräutigam", "braut": "Braut",
              "verstorbener": "Verstorbener", "ehepartner": "Ehepartner", "vorehe": "voriger Ehepartner"}


def rolle(pfad):
    """'mutter' -> 'MOTH'; 'braut_vater' -> '(Braut: Vater)'; 'verstorbener' -> '(Verstorbener)'."""
    if pfad in ROLLE:
        return ROLLE[pfad]
    return "(" + ": ".join(ROLLENWORT.get(t, t) for t in pfad.split("_")) + ")"


def datum(j, m=None, t=None, praefix=None):
    """GEDCOM-Datum aus Jahr, Monat, Tag und Praefix (ABT, BEF, CAL): '31 AUG 1778', 'AUG 1778', 'CAL 1750'."""
    if not j:
        return None
    s = f"{t} " if t else ""
    s += f"{MON[m - 1]} " if m else ""
    s += str(j)
    return f"{praefix} {s}" if praefix else s


def z(stufe, tag, wert=None):
    """Eine GEDCOM-Zeile; lange Werte werden mit CONC umgebrochen, Zeilenumbrueche mit CONT."""
    out = []
    if wert is None or wert == "":
        return [f"{stufe} {tag}"]
    teile = str(wert).replace("\r", "").split("\n")
    for n, teil in enumerate(teile):
        t = "CONT" if n else tag
        s = stufe + 1 if n else stufe
        while len(teil.encode("utf-8")) > 240:
            schnitt = 200
            out.append(f"{s} {t} {teil[:schnitt]}")
            teil, t, s = teil[schnitt:], "CONC", stufe + 1
        out.append(f"{s} {t} {teil}")
    return out


def schreiben(con, ziel):
    """Die ganze GEDCOM aus der Projektdatei: Kopf, Quellen, je Identitaet ein INDI mit Namen, Ereignissen, Berufen, Notizen und Fundstellen, je Familie ein FAM. Gibt Zaehler zurueck."""
    quellen = {q["id"]: dict(q) for q in con.execute("SELECT * FROM quelle")}
    eintraege = {e["id"]: dict(e) for e in con.execute("SELECT * FROM eintrag")}
    felder = {}
    for f in con.execute("SELECT eintrag, name, wert FROM feld WHERE wert IS NOT NULL"):
        felder.setdefault(f["eintrag"], {})[f["name"]] = f["wert"]
    ohne_feld = {}                                 # Zellen in Spalten ohne Feld, je Eintrag in Spaltenfolge
    for c in con.execute("SELECT z.eintrag, k.titel, z.roh FROM zelle z JOIN eintrag e ON e.id=z.eintrag "
                         "JOIN kopf k ON k.quelle=e.quelle AND k.spalte=z.spalte WHERE NOT k.zugeordnet ORDER BY z.eintrag, z.spalte"):
        ohne_feld.setdefault(c["eintrag"], []).append(f"{c['titel']}: {c['roh'].removesuffix('T00:00:00')}")
    umschrift = {f["eintrag"]: f["roh"].strip() for f in con.execute("SELECT eintrag, roh FROM feld WHERE name='wortlaut' AND wert IS NOT NULL")}
    personen = {p["id"]: dict(p) for p in con.execute("SELECT * FROM person")}
    rollen = {}                                    # ident -> [(person, zuordnung)]
    for r in con.execute("SELECT z.*, p.eintrag, p.pfad FROM zuordnung z JOIN person p ON p.id=z.person"):
        rollen.setdefault(r["ident"], []).append(dict(r))
    idents = {i["id"]: dict(i) for i in con.execute("SELECT * FROM identitaet")}
    fams = {f["id"]: dict(f) for f in con.execute("SELECT * FROM familie")}
    kinder = {}
    for k in con.execute("SELECT k.familie, k.ident, i.geb_jahr, i.geb_monat, i.geb_tag FROM kind k JOIN identitaet i ON i.id=k.ident"):
        kinder.setdefault(k["familie"], []).append((k["geb_jahr"] or 9999, k["geb_monat"] or 0, k["geb_tag"] or 0, k["ident"]))
    fams_von = {}
    for f in fams.values():
        for p in (f["mann"], f["frau"]):
            if p:
                fams_von.setdefault(p, []).append(f["id"])

    # Paten und Zeugen, die beteiligte.py eindeutig einer Person zugeordnet hat: ASSO bei der Hauptperson des
    # Eintrags (Taeufling, Brautleute, Verstorbener), die Fundstelle mit ihrer Rolle bei der Person selbst
    hauptpersonen = {}
    for liste in rollen.values():
        for r in liste:
            if r["pfad"] in HAUPTPFAD.get(eintraege[r["eintrag"]]["register"], ()):
                hauptpersonen.setdefault(r["eintrag"], []).append(r["ident"])
    asso_von, beteiligt_als = {}, {}
    for b in con.execute("SELECT eintrag, art, ident, grund FROM beteiligt WHERE ident IS NOT NULL ORDER BY eintrag, art, nr"):
        e = eintraege[b["eintrag"]]
        for h in hauptpersonen.get(b["eintrag"], []):
            if h != b["ident"]:
                asso_von.setdefault(h, []).append((b["ident"], b["art"], e, b["grund"]))
        beteiligt_als.setdefault(b["ident"], []).append((e, b["art"]))

    def uebernommen(r, was):
        """Vermerk fuer einen Wert, den famrecon aus einem anderen Eintrag an die Person gehaengt hat."""
        return f"{was} aus diesem Eintrag übernommen" + (f" (Verknüpfung: {r['stufe']})" if r["stufe"] != "neu" else "")

    def herkunft(i, passt):
        """Die Nennungen einer Identitaet, deren Person den Wert traegt, je Eintrag einmal, nach Jahr."""
        out, gesehen = [], set()
        for r in sorted(rollen.get(i["id"], []), key=lambda r: (eintraege[r["eintrag"]]["jahr"] or 0, r["eintrag"])):
            if r["eintrag"] not in gesehen and passt(personen[r["person"]], r):
                gesehen.add(r["eintrag"])
                out.append(r)
        return out

    def namensbelege(i, passt):
        """SOUR-Zeilen unter einem NAME: je Register die frueheste Nennung, deren Person diesen Namen traegt."""
        out, register = [], set()
        for r in herkunft(i, lambda p, r: passt(p)):
            e = eintraege[r["eintrag"]]
            if e["register"] not in register:
                register.add(e["register"])
                out += quelle(e, pfad=r["pfad"])
        return out

    def quelle(e, haupt=False, pfad=None, vermerk=None, n=2, rolle_text=None):
        """SOUR-Zeilen (Stufe n) fuer einen Eintrag: PAGE (Fundstelle), EVEN (Art des Eintrags) mit ROLE (Rolle der
        Person darin, aus dem Pfad oder als Text), beim Hauptereignis dazu DATA/TEXT: Umschrift des Eintrags (Feld
        wortlaut), danach Spalten ohne Feld als "Ueberschrift: Zellinhalt"."""
        fl = felder.get(e["id"], {})
        fund = fl.get("zitat") or " ".join(x for x in (fl.get("kb"), f"S. {fl['seite']}" if fl.get("seite") else None,
                                                        f"Nr. {fl['lfd_nr']}" if fl.get("lfd_nr") else None) if x) or f"Zeile {e['zeile']}"
        out = [f"{n} SOUR @S{e['quelle']}@", *z(n + 1, "PAGE", fund)]
        art = "BURI" if e["register"] == "tod" and not fl.get("sterbe_datum") and fl.get("begraebnis_datum") else EVEN.get(e["register"])
        if art:
            out.append(f"{n + 1} EVEN {art}")
            if pfad or rolle_text:
                out += z(n + 2, "ROLE", rolle_text or rolle(pfad))
        if vermerk:
            out += z(n + 1, "NOTE", vermerk)
        text = ([umschrift[e["id"]]] if haupt and e["id"] in umschrift else []) + (ohne_feld.get(e["id"], []) if haupt else [])
        if text:
            out += [f"{n + 1} DATA", *z(n + 2, "TEXT", "\n".join(text))]
        return out

    out = ["0 HEAD", "1 SOUR famrecon", f"2 VERS {__version__}", "2 NAME famrecon", f"1 DATE {datum(dt.date.today().year, dt.date.today().month, dt.date.today().day)}",
           "1 GEDC", "2 VERS 5.5.1", "1 CHAR UTF-8", "1 LANG German"]

    for i in sorted(idents.values(), key=lambda i: i["id"]):
        out.append(f"0 @I{i['id']}@ INDI")
        nachname = i["name"] or ("NN" if i["unbekannt"] else "")
        out += z(1, "NAME", f"{i['vorname'] or ''} /{nachname}/".strip())
        if i["vorname"]:
            out += z(2, "GIVN", i["vorname"])
        if nachname:
            out += z(2, "SURN", nachname)
        if i["name"]:                               # Name belegt, wo er genannt ist: je Register der frueheste Eintrag
            out += namensbelege(i, lambda p: p["geburtsname"] == i["name"] or (p["name"] == i["name"] and not p["geburtsname"]))
        # jede abweichende Schreibung aus den Eintraegen (Kirchenbuchform oder Zelle) als _KB_NAME
        kb_formen = set()
        for r in rollen.get(i["id"], []):
            p = personen[r["person"]]
            n, vn = p["name_kb"] or p["name"], p["vorname_kb"] or p["vorname"]
            if (n or vn) and ((n or "") != (i["name"] or "") and (n or "") != (i["ehename"] or "") or (vn or "") != (i["vorname"] or "")):
                kb_formen.add((n or "", vn or ""))
        if i["ehename"]:
            out += z(1, "NAME", f"{i['vorname'] or ''} /{i['ehename']}/".strip()) + ["2 TYPE married"]
            out += namensbelege(i, lambda p: p["name"] == i["ehename"] and p["geburtsname"])
        for n, vn in sorted(kb_formen, key=str):        # Schreibweise des Kirchenbuchs als weiterer Name
            out += z(1, "NAME", f"{vn} /{n}/".strip()) + ["2 TYPE aka", "2 NOTE Schreibweise im Kirchenbuch"]
        if i["geschlecht"]:
            out.append(f"1 SEX {i['geschlecht']}")
        geb_geschrieben = False
        notizen, berufe, bloecke = [], [], []          # bloecke: (rang, zeilen) -> BIRT 0, CHR 1, OCCU 2, DEAT 3, BURI 4
        out_person, out = out, []
        for r in sorted(rollen.get(i["id"], []), key=lambda r: (eintraege[r["eintrag"]]["jahr"] or 0, r["eintrag"])):
            e, fl, p = eintraege[r["eintrag"]], felder.get(r["eintrag"], {}), personen[r["person"]]
            pfad = r["pfad"]
            if e["register"] == "taufe" and pfad == "kind":
                # Geburt nur, wenn der Eintrag sie nennt; das Taufdatum, das die Verknuepfung ersatzweise als Geburt
                # rechnet, steht bei CHR und wird hier nicht als Geburtsdatum ausgegeben
                if fl.get("geburt_datum") or (p["totgeburt"] and not fl.get("tauf_datum")):
                    out.append("1 BIRT")
                    if fl.get("geburt_datum"):
                        out.append(f"2 DATE {datum(*_jmt(fl['geburt_datum']))}")
                    if fl.get("geburt_ort"):
                        out += z(2, "PLAC", fl["geburt_ort"])
                    if p["totgeburt"]:
                        out += z(2, "NOTE", "Totgeburt")
                    out += quelle(e, haupt=bool(p["totgeburt"] and not fl.get("tauf_datum")), pfad=pfad)   # keine CHR: Text an der Geburt
                    geb_geschrieben = True
                if fl.get("tauf_datum") or not p["totgeburt"]:
                    out.append("1 CHR")
                    if fl.get("tauf_datum"):
                        out.append(f"2 DATE {datum(*_jmt(fl['tauf_datum']))}")
                    if fl.get("tauf_ort") or fl.get("ort"):
                        out += z(2, "PLAC", fl.get("tauf_ort") or fl.get("ort"))
                    if fl.get("paten"):
                        out += z(2, "NOTE", "Taufpaten: " + fl["paten"].replace(" | ", "; "))
                    if fl.get("pfarrer"):
                        out += z(2, "NOTE", "Taufender: " + fl["pfarrer"])
                    out += quelle(e, haupt=True, pfad=pfad)
                if fl.get("unehelich") and str(fl["unehelich"]).lower() in ("u", "unehelich", "ja", "x"):
                    notizen.append("unehelich geboren")
                if p.get("verzogen"):
                    notizen.append("verzogen nach " + p["verzogen"])
            elif e["register"] == "tod" and pfad == "verstorbener":
                out.append("1 DEAT")
                d = datum(e["jahr"], e["monat"], e["tag"]) if fl.get("sterbe_datum") else None
                if d:
                    out.append(f"2 DATE {d}")
                if fl.get("sterbe_ort") or fl.get("ort"):
                    out += z(2, "PLAC", fl.get("sterbe_ort") or fl.get("ort"))
                if fl.get("todesursache"):
                    out += z(2, "CAUS", fl["todesursache"])
                alter = fl.get("verstorbener_alter") or fl.get("verstorbener_alter_kb")
                if alter:
                    out += z(2, "AGE", alter)
                out += quelle(e, haupt=True, pfad=pfad)
                if fl.get("begraebnis_datum"):
                    out.append("1 BURI")
                    out.append(f"2 DATE {datum(*_jmt(fl['begraebnis_datum']))}")
                    if fl.get("begraebnis_ort"):
                        out += z(2, "PLAC", fl["begraebnis_ort"])
                    if fl.get("zeugen"):
                        out += z(2, "NOTE", "Zeugen: " + fl["zeugen"].replace(" | ", "; "))
                    out += quelle(e, pfad=pfad)
                if p["stand"]:
                    notizen.append(f"{p['stand']} ({e['jahr']})")
            if p["beruf"]:
                berufe.append((e, p["beruf"], fl, p["verstorben"], pfad))
            if p["herkunft"]:
                notizen.append(f"Herkunft ({e['register']} {e['jahr']}): {p['herkunft']}")
            if p["bemerkung"]:
                notizen.append(p["bemerkung"])
            if pfad in ("kind", "verstorbener", "braeutigam", "braut") and fl.get("bemerkung"):
                notizen.append(f"Bemerkung ({e['register']} {e['jahr']}): {fl['bemerkung']}")
            if r["stufe"] == "unsicher":
                alt = ", ".join(f"@I{a[0]}@ ({a[1]} P.)" for a in json.loads(r["alternativen"] or "[]"))
                notizen.append(f"famrecon: Zuordnung aus {e['register']} {e['jahr']} unsicher ({r['grund']}); Alternativen: {alt}")
        beleg = herkunft(i, lambda p, r: p["geburt_jahr"] == i["geb_jahr"] and r["pfad"] != "kind") if i["geb_jahr"] else []
        if not geb_geschrieben and beleg:           # Geburt aus einem anderen Eintrag (Alter, Geburtsdatum beim Tod)
            out.append("1 BIRT")
            out.append(f"2 DATE {datum(i['geb_jahr'], i['geb_monat'], i['geb_tag'], i['geb_praefix'])}")
            for r in beleg[:1]:
                was = "Geburt errechnet aus dem Alter," if personen[r["person"]]["geburt_praefix"] == "CAL" else "Geburt"
                out += quelle(eintraege[r["eintrag"]], pfad=r["pfad"], vermerk=uebernommen(r, was))
        if i["tod_jahr"] and not any(l == "1 DEAT" for l in out):
            out.append("1 DEAT")
            out.append(f"2 DATE {datum(i['tod_jahr'], i['tod_monat'], i['tod_tag'])}")
            for r in herkunft(i, lambda p, r: r["pfad"] == "kind" and felder.get(r["eintrag"], {}).get("sterbe_datum_rv"))[:1]:
                out += quelle(eintraege[r["eintrag"]], pfad="kind", vermerk=uebernommen(r, "Tod (Rückverweis im Taufeintrag)"))
        gesehen = set()
        for e, beruf, fl, verstorben, pfad in berufe:
            if beruf in gesehen:
                continue
            gesehen.add(beruf)
            out += z(1, "OCCU", beruf)
            if e["jahr"] and not verstorben:              # "weyl. Wagenmeister" 1763: Nennung nach dem Tod, kein Datum
                out.append(f"2 DATE {datum(e['jahr'], e['monat'], e['tag'])}")
            out += quelle(e, pfad=pfad)
        # Ereignisbloecke in die Reihenfolge BIRT, CHR, OCCU, DEAT, BURI bringen
        rang = {"BIRT": 0, "CHR": 1, "OCCU": 2, "DEAT": 3, "BURI": 4}
        for zeile in out:
            if zeile.startswith("1 "):
                bloecke.append([rang.get(zeile.split()[1], 9), len(bloecke), [zeile]])
            else:
                bloecke[-1][2].append(zeile)
        out = out_person
        for _, _, zeilen in sorted(bloecke, key=lambda b: (b[0], b[1])):
            out += zeilen
        for n in dict.fromkeys(notizen):
            out += z(1, "NOTE", n)
        for pate, art, e, grund in asso_von.get(i["id"], []):
            out += [f"1 ASSO @I{pate}@", f"2 RELA {art}"] + quelle(e, rolle_text=f"({art})", vermerk=grund)
        for e, art in sorted(beteiligt_als.get(i["id"], []), key=lambda ea: (ea[0]["jahr"] or 0, ea[0]["id"])):
            out += quelle(e, n=1, rolle_text=f"({art})")
        if i["famc"]:
            out.append(f"1 FAMC @F{i['famc']}@")
        for fid in fams_von.get(i["id"], []):
            out.append(f"1 FAMS @F{fid}@")

    for f in sorted(fams.values(), key=lambda f: f["id"]):
        out.append(f"0 @F{f['id']}@ FAM")
        if f["mann"]:
            out.append(f"1 HUSB @I{f['mann']}@")
        if f["frau"]:
            out.append(f"1 WIFE @I{f['frau']}@")
        if f["trauung_eintrag"]:
            e, fl = eintraege[f["trauung_eintrag"]], felder.get(f["trauung_eintrag"], {})
            out.append("1 MARR")
            if f["tr_jahr"]:
                out.append(f"2 DATE {datum(f['tr_jahr'], f['tr_monat'], f['tr_tag'])}")
            if fl.get("trauung_ort") or fl.get("ort"):
                out += z(2, "PLAC", fl.get("trauung_ort") or fl.get("ort"))
            if fl.get("zeugen"):
                out += z(2, "NOTE", "Trauzeugen: " + fl["zeugen"].replace(" | ", "; "))
            if fl.get("pfarrer"):
                out += z(2, "NOTE", "Trauender: " + fl["pfarrer"])
            if fl.get("proklamation"):
                out += z(2, "NOTE", "Proklamation: " + fl["proklamation"])
            if fl.get("bemerkung"):
                out += z(2, "NOTE", fl["bemerkung"])
            out += quelle(e, haupt=True)
        elif f["art"] == "eltern":
            out += z(1, "NOTE", "Ehe aus Taufen/Sterbefaellen erschlossen, Traueintrag nicht gefunden")
        for _, _, _, kid in sorted(kinder.get(f["id"], [])):
            out.append(f"1 CHIL @I{kid}@")

    for q in quellen.values():
        out.append(f"0 @S{q['id']}@ SOUR")
        out += z(1, "TITL", f"{q['datei']}, Blatt {q['blatt']} ({q['register']})")
    out.append("0 TRLR")
    with open(ziel, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")
    return dict(indi=len(idents), fam=len(fams), sour=len(quellen), zeilen=len(out))


def _jmt(text):
    from . import normalform
    d = normalform.datum_zerlegen(text)
    return (d[0], d[1], d[2], normalform.datum_praefix(text)) if d else (None,)
