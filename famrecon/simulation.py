"""Aus einer sauberen GEDCOM die drei Register rueckwaerts erzeugen: die Wahrheit zum Messen.

    famrecon simuliere datei.ged -o ordner/      schreibt ordner/register.xlsx (Taufen, Ehen, Tote)

Jede Person mit Geburt oder Taufe wird eine Taufzeile mit Vater und Mutter aus
der Elternfamilie; jede Familie mit Trauung eine Ehezeile mit den Eltern der
Brautleute; jeder Tod eine Totenzeile mit Vater, Ehepartner, Familienstand und
dem Alter, wie ein Pfarrer es geschrieben haette ("59 J 10 M 4 T"). Jede
genannte Person traegt in einer Ref-Spalte ihre GEDCOM-Kennung. Die Spalte
wird beim Verknuepfen nicht benutzt, nur von `famrecon messen`.

Was dabei absichtlich fehlt: Lesefehler, Schreibvarianten, Luecken. Eine
GEDCOM ist sauberer als ein Kirchenbuch. Die Messung gilt der Verknuepfung,
nicht der Normalform. Rauschen laesst sich mit --rauschen zuschalten:
Vornamenvarianten, fehlende Muetter, Namensendungen, Luecken bei Daten.
"""
import datetime as dt
import random
import re
from pathlib import Path

import openpyxl

MON = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}


def lesen(pfad):
    """GEDCOM -> (indis, fams): dicts nach xref, Werte als verschachtelte Listen."""
    stapel, records = [], {}
    for zeile in Path(pfad).read_text(encoding="utf-8-sig").splitlines():
        m = re.match(r"(\d+)\s+(@[^@]+@\s+)?(\w+)\s?(.*)$", zeile.rstrip("\r"))
        if not m:
            continue
        lvl, xref, tag, wert = int(m.group(1)), (m.group(2) or "").strip(), m.group(3), m.group(4)
        knoten = dict(tag=tag, wert=wert, xref=xref, kinder=[])
        if lvl == 0:
            records[xref or tag] = knoten
            stapel = [knoten]
        else:
            stapel = stapel[:lvl]
            stapel[-1]["kinder"].append(knoten)
            stapel.append(knoten)
    indis = {k: v for k, v in records.items() if v["tag"] == "INDI"}
    fams = {k: v for k, v in records.items() if v["tag"] == "FAM"}
    return indis, fams


def sub(knoten, tag):
    return [k for k in knoten["kinder"] if k["tag"] == tag]


def wert(knoten, *pfad):
    for tag in pfad:
        k = sub(knoten, tag)
        if not k:
            return None
        knoten = k[0]
    return knoten["wert"] or None


def datum_iso(text):
    """'14 MAR 1985' -> '1985-03-14'; 'ABT 1750' -> 'um 1750'; 'MAR 1985' -> '1985-03-00'."""
    if not text:
        return None
    t = text.strip().upper()
    praefix = ""
    for p, d in (("ABT", "um "), ("EST", "etwa "), ("CAL", "err. "), ("BEF", "vor "), ("AFT", "nach ")):
        if t.startswith(p + " "):
            praefix, t = d, t[len(p) + 1:]
    m = re.match(r"(?:(\d{1,2}) )?(?:([A-Z]{3}) )?(\d{4})$", t)
    if not m:
        return text
    tag, mon, jahr = m.groups()
    if praefix:
        return f"{praefix}{jahr}"
    return f"{jahr}-{MON.get(mon, 0):02d}-{int(tag or 0):02d}" if mon else jahr


def datum_obj(text):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})$", datum_iso(text) or "")
    if not m or "00" in (m.group(2), m.group(3)):
        return None
    return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))


def alter_text(geb, tod):
    """Alter wie im Kirchenbuch: '59 J 10 M 4 T', bei Saeuglingen '24 Wochen' oder '10 T'."""
    if not geb or not tod or tod < geb:
        return None
    tage = (tod - geb).days
    if tage < 60:
        return f"{tage} T"
    if tage < 365:
        return f"{tage // 7} Wochen"
    j = tod.year - geb.year - ((tod.month, tod.day) < (geb.month, geb.day))
    rest = tod - dt.date(geb.year + j, geb.month, min(geb.day, 28))
    m, t = rest.days // 30, rest.days % 30
    return f"{j} J {m} M {t} T"


class Zufall:
    """Rauschen: Vornamenvarianten, fehlende Angaben, Schreibvarianten; deterministisch je Saat."""
    VARIANTEN = {"Johann": ["Johannes", "Hans"], "Georg": ["Jörg"], "Jakob": ["Jacob"], "Katharina": ["Catharina"],
                 "Friedrich": ["Fridrich", "Friederich"], "Nikolaus": ["Nicolaus"], "Christoph": ["Christof"],
                 "Elisabeth": ["Elisabetha"], "Dorothea": ["Dorothee"], "Karl": ["Carl"], "Konrad": ["Conrad"]}

    def __init__(self, saat, staerke):
        self.r = random.Random(saat)
        self.s = staerke

    def vorname(self, vn):
        if not vn or self.r.random() > self.s:
            return vn
        teile = vn.split()
        if len(teile) > 1 and self.r.random() < 0.5:
            return teile[0]                                   # nur der Rufname
        v = self.VARIANTEN.get(teile[0])
        return (self.r.choice(v) + vn[len(teile[0]):]) if v else vn

    def nachname(self, n, weiblich=False):
        if not n or self.r.random() > self.s:
            return n
        if weiblich and self.r.random() < 0.5:
            return n + "(in)"
        return re.sub(r"(ck|k)$", "ckh", n) if self.r.random() < 0.3 else n.replace("ei", "ey", 1) if "ei" in n else n

    def weg(self):
        return self.r.random() < self.s * 0.4


def register(indis, fams, rauschen=0.0, saat=1):
    z = Zufall(saat, rauschen)

    def name(x, kb=False):
        i = indis.get(x)
        if not i:
            return None, None
        vn, nn = wert(i, "NAME", "GIVN"), wert(i, "NAME", "SURN")
        if not vn or not nn:
            m = re.match(r"(.*?)\s*/(.*)/", wert(i, "NAME") or "")
            vn, nn = (m.group(1).strip() or vn, m.group(2).strip() or nn) if m else (vn, nn)
        if kb:
            vn, nn = z.vorname(vn), z.nachname(nn, wert(i, "SEX") == "F")
        return nn, vn

    def zeile(x, mit_beruf=False, verstorben_vor=None):
        """'Nachname, Vorname[, weyl.]' wie im Kirchenbuch; der Beruf steht in einer eigenen Spalte."""
        if not x or x not in indis:
            return None
        nn, vn = name(x, kb=True)
        teile = [nn or "NN", vn or ""]
        tod = datum_obj(wert(indis[x], "DEAT", "DATE"))
        if verstorben_vor and tod and tod < verstorben_vor:
            teile.append("weyl.")
        return ", ".join(t for t in teile if t)

    def beruf(x):
        return wert(indis[x], "OCCU") if x and x in indis else None

    def eltern(x):
        famc = wert(indis[x], "FAMC")
        f = fams.get(famc) if famc else None
        return (wert(f, "HUSB"), wert(f, "WIFE"), f) if f else (None, None, None)

    taufen, ehen, tote = [], [], []
    for x, i in indis.items():
        geb, chr_ = wert(i, "BIRT", "DATE"), wert(i, "CHR", "DATE")
        if geb or chr_:
            v, m, _ = eltern(x)
            nn, vn = name(x, kb=True)
            paten = "; ".join(zeile(p["wert"]) or p["wert"] for c in sub(i, "CHR") for p in sub(c, "_GODP")) or None
            taufen.append({"Geburtsdatum": datum_iso(geb), "Geburtsort": wert(i, "BIRT", "PLAC"),
                           "Taufdatum": datum_iso(chr_), "Taufort": wert(i, "CHR", "PLAC"),
                           "Name": nn, "Vorname": vn, "Geschlecht": {"M": "m", "F": "w"}.get(wert(i, "SEX")),
                           "Vater": zeile(v), "Vater Beruf": beruf(v), "Mutter": None if (m and z.weg()) else zeile(m),
                           "Paten": paten, "Kind Ref": x, "Vater Ref": v, "Mutter Ref": m})
        tod = wert(i, "DEAT", "DATE") or wert(i, "BURI", "DATE")
        if tod:
            v, m, _ = eltern(x)
            nn, vn = name(x, kb=True)
            todd = datum_obj(wert(i, "DEAT", "DATE")) or datum_obj(wert(i, "BURI", "DATE"))
            ehen_von = [fams[f["wert"]] for f in sub(i, "FAMS") if f["wert"] in fams]
            partner = None
            for f in ehen_von:
                p = wert(f, "WIFE") if wert(f, "HUSB") == x else wert(f, "HUSB")
                if p:
                    partner = (zeile(p, verstorben_vor=todd), p)
            stand = "ledig" if not ehen_von else ("verwitwet" if partner and "weyl." in (partner[0] or "") else "verheiratet")
            gebd = datum_obj(geb)
            tote.append({"Sterbedatum": datum_iso(wert(i, "DEAT", "DATE")), "Begräbnisdatum": datum_iso(wert(i, "BURI", "DATE")),
                         "Name": nn, "Vorname": vn, "Geschlecht": {"M": "m", "F": "w"}.get(wert(i, "SEX")),
                         "Alter": None if z.weg() else alter_text(gebd, todd), "Beruf": wert(i, "OCCU"),
                         "Krankheit": wert(i, "DEAT", "CAUS"), "Familienstand": stand,
                         "Vater": zeile(v, verstorben_vor=todd) if (todd and gebd and (todd - gebd).days < 365 * 30) else None,
                         "Vater Beruf": beruf(v) if (todd and gebd and (todd - gebd).days < 365 * 30) else None,
                         "Mutter": zeile(m) if (todd and gebd and (todd - gebd).days < 365 * 30) else None,
                         "Ehepartner": partner[0] if partner else None, "Ehepartner Beruf": beruf(partner[1]) if partner else None,
                         "Verstorbener Ref": x, "Vater Ref": v if (todd and gebd and (todd - gebd).days < 365 * 30) else None,
                         "Ehepartner Ref": partner[1] if partner else None})
    for fx, f in fams.items():
        if not sub(f, "MARR"):
            continue
        hx, wx = wert(f, "HUSB"), wert(f, "WIFE")
        hv, hm, _ = eltern(hx) if hx in indis else (None, None, None)
        wv, wm, _ = eltern(wx) if wx in indis else (None, None, None)
        trd = datum_obj(wert(f, "MARR", "DATE"))
        hn, hvn = name(hx, kb=True) if hx else (None, None)
        wn, wvn = name(wx, kb=True) if wx else (None, None)
        zeugen = "; ".join(zeile(a["wert"]) or a["wert"] for mr in sub(f, "MARR") for a in sub(mr, "_ASSO") + sub(mr, "_WITN")) or None
        ehen.append({"Trauungsdatum": datum_iso(wert(f, "MARR", "DATE")), "Trauungsort": wert(f, "MARR", "PLAC"),
                     "Bräutigam Name": hn, "Bräutigam Vorname": hvn, "Bräutigam Beruf": wert(indis[hx], "OCCU") if hx in indis else None,
                     "Braut Name": wn, "Braut Vorname": wvn,
                     "Bräutigam Vater": zeile(hv, verstorben_vor=trd), "Bräutigam Vater Beruf": beruf(hv), "Bräutigam Mutter": zeile(hm),
                     "Braut Vater": zeile(wv, verstorben_vor=trd), "Braut Vater Beruf": beruf(wv), "Braut Mutter": zeile(wm),
                     "Zeugen": zeugen, "Bräutigam Ref": hx, "Braut Ref": wx,
                     "Bräutigam Vater Ref": hv, "Bräutigam Mutter Ref": hm, "Braut Vater Ref": wv, "Braut Mutter Ref": wm})
    return taufen, ehen, tote


def schreiben(ziel, taufen, ehen, tote):
    wb = openpyxl.Workbook()
    for i, (titel, zeilen) in enumerate((("Taufen", taufen), ("Ehen", ehen), ("Tote", tote))):
        ws = wb.active if i == 0 else wb.create_sheet()
        ws.title = titel
        if zeilen:
            kopf = list(zeilen[0].keys())
            ws.append(kopf)
            for r in sorted(zeilen, key=lambda r: str(r[kopf[0]] or "9999")):
                ws.append([r.get(k) for k in kopf])
    Path(ziel).parent.mkdir(parents=True, exist_ok=True)
    wb.save(ziel)
    return {"taufe": len(taufen), "ehe": len(ehen), "tod": len(tote)}


def simulieren(ged, ziel, rauschen=0.0, saat=1):
    indis, fams = lesen(ged)
    taufen, ehen, tote = register(indis, fams, rauschen, saat)
    return schreiben(ziel, taufen, ehen, tote), len(indis), len(fams)
