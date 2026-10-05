#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Plausibilitätsprüfung für Ortsfamilienbücher; die Regeln stehen in pruefregeln.txt.

    python3 plausibilitaet.py blank.db                  SQLite mit OFB-Schema
    python3 plausibilitaet.py schorndorfer-familien.ged GEDCOM 5.5.1
    python3 plausibilitaet.py blank.db --zeigen 10      je Regel bis zu 10 Treffer
    python3 plausibilitaet.py blank.db --nur 01         nur Regeln, deren Id so beginnt
    python3 plausibilitaet.py blank.db --tsv treffer.csv   alle Treffer als Tabelle (;-getrennt)
    python3 plausibilitaet.py blank.db --messreihe listen/messreihe.csv --kommentar "Regel 2"
                                                        eine Zeile je Lauf anhaengen, je Regel eine Spalte
    python3 plausibilitaet.py --katalog                 Regeldatei als Markdown-Tabelle
    python3 plausibilitaet.py --selbsttest              eingebaute Fälle je Regel
    --trocken: Tabelle `pruefliste` der SQLite-DB nicht schreiben

Exit-Code 1, sobald eine Bau-Regel der Schwere `fehler` trifft; Regeln mit
`aufloesung` „original" messen Widersprüche der Vorlage und sperren nicht.
Regeldatei: eine Zeile je Regel `id | art | schwere | grenzwert | frage | herkunft`,
`id` verbindet sie mit `regel_<id>(m, g)` hier, `#` schaltet sie aus; jede Regel
braucht einen Fall in SELBSTTEST_FAELLE.
"""
import os
import re
import sqlite3
import sys
from collections import defaultdict

HIER = os.path.dirname(os.path.abspath(__file__))
REGELDATEI = os.path.join(HIER, "pruefregeln.txt")
JETZT = 2026


# =========================================================================
#  Datum
# =========================================================================
RE_DMY = re.compile(r"^\s*(\d{1,2})\.\s*(\d{1,2})\.?\s*(\d{4})\s*$")
RE_MY = re.compile(r"^\s*(\d{1,2})\.\s*(\d{4})\s*$")
RE_ISO = re.compile(r"^\s*(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?\s*$")
RE_JAHR = re.compile(r"(\d{4})")
MON = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
       "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
RE_GED = re.compile(r"(?:(\d{1,2})\s+)?([A-Z]{3})\s+(\d{4})")


def datum(s):
    """Datum in D.M.YYYY, M.YYYY, ISO, blossem Jahr oder GEDCOM-Form -> (jahr, monat, tag), unbekannte Teile None."""
    if not s:
        return None
    s = str(s).strip()
    m = RE_DMY.match(s)
    if m:
        d, mo, y = (int(x) for x in m.groups())
        return (y, mo, d)                     # auch Unmögliches erhalten, Regel 018 findet es
    m = RE_ISO.match(s)
    if m:
        y, mo, d = m.groups()
        return (int(y), int(mo) if mo else None, int(d) if d else None)
    m = RE_MY.match(s)
    if m:
        mo, y = (int(x) for x in m.groups())
        return (y, mo, None)
    m = RE_GED.search(s.upper())
    if m and m.group(2) in MON:
        d, mo, y = m.groups()
        return (int(y), MON[mo], int(d) if d else None)
    m = RE_JAHR.search(s)
    return (int(m.group(1)), None, None) if m else None


def voll(t):
    return t is not None and t[1] is not None and t[2] is not None


def _tage(t):
    y, mo, d = t
    return y * 372 + (mo or 1) * 31 + (d or 1)


def vor(a, b):
    """True, wenn a sicher vor b liegt (gemeinsame Genauigkeit). None ohne Daten."""
    if a is None or b is None:
        return None
    if voll(a) and voll(b):
        return _tage(a) < _tage(b)
    return a[0] < b[0]


def jahre(a, b):
    """b - a in Jahren; Dezimal bei zwei vollen Daten, sonst ganze Jahre."""
    if a is None or b is None:
        return None
    if voll(a) and voll(b):
        return (_tage(b) - _tage(a)) / 372.0
    return float(b[0] - a[0])


def monate(a, b):
    """b - a in Monaten, nur wenn beide mindestens monatsgenau."""
    if a is None or b is None or a[1] is None or b[1] is None:
        return None
    return (b[0] - a[0]) * 12 + (b[1] - a[1]) + ((b[2] or 1) - (a[2] or 1)) / 31.0


def dtxt(t):
    if t is None:
        return "?"
    y, mo, d = t
    return f"{d}.{mo}.{y}" if voll(t) else (f"{mo}.{y}" if mo else str(y))


def schaltjahr(y):
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def datum_unmoeglich(t):
    if t is None or t[1] is None:
        return False
    y, mo, d = t
    if not 1 <= mo <= 12:
        return True
    if d is None:
        return False
    if d < 1 or d > 31:
        return True
    if mo in (4, 6, 9, 11) and d > 30:
        return True
    if mo == 2 and d > (29 if schaltjahr(y) else 28):
        return True
    return False


# =========================================================================
#  Modell
# =========================================================================
class Person:
    __slots__ = ("id", "vn", "fn", "geschlecht", "geb", "taufe", "tod", "begr",
                 "beruf", "notiz", "ort", "ehen", "eltern", "alias", "sterbealter", "rolle",
                 "artikel")

    def __init__(self, id):
        self.id = id
        self.vn = self.fn = ""
        self.geschlecht = "u"
        self.geb = self.taufe = self.tod = self.begr = None
        self.beruf = self.notiz = self.ort = ""
        self.ehen, self.eltern, self.alias = [], [], set()
        self.sterbealter = None
        self.rolle = ""
        self.artikel = None        # nur aus SQLite

    def name(self):
        return f"{self.vn} {self.fn}".strip() or "(ohne Namen)"


class Familie:
    __slots__ = ("id", "vater", "mutter", "heirat", "kinder", "notiz")

    def __init__(self, id):
        self.id = id
        self.vater = self.mutter = None
        self.heirat = None
        self.kinder = []
        self.notiz = ""


class Modell:
    def __init__(self):
        self.p = {}          # id -> Person
        self.f = {}          # id -> Familie
        self.quelle = ""
        self.hat_rohtext = False
        self.verschmolzen = []   # Paare aus ofb_person_kanon mit Sterbedaten, nur aus SQLite

    def person(self, pid):
        return self.p.get(pid)

    def partner(self, f):
        return [self.p[x] for x in (f.vater, f.mutter) if x in self.p]

    def kinder(self, f):
        return [self.p[x] for x in f.kinder if x in self.p]

    def vater(self, f):
        return self.p.get(f.vater)

    def mutter(self, f):
        return self.p.get(f.mutter)

    def selbe_person(self, a, b):
        return a.id == b.id or b.id in a.alias or a.id in b.alias


# ------------------------------------------------------------ SQLite ----
RE_ALTER = re.compile(r"\(\s*(\d{1,3})\s*J(?:ahre?)?\.?(?:\s*(\d{1,2})\s*M)?(?:\s*(\d{1,2})\s*T)?")


def sterbealter_aus_text(roh, tod_text):
    """'+ 15.5. 1787 (81 J 2 M 10 T)' -> 81.19; None wenn nicht da."""
    if not roh or not tod_text:
        return None
    pos = roh.find(str(tod_text).strip())
    if pos < 0:
        return None
    m = RE_ALTER.match(roh[pos + len(str(tod_text).strip()):].lstrip())
    if not m:
        return None
    j, mo, t = m.groups()
    return int(j) + (int(mo) if mo else 0) / 12.0 + (int(t) if t else 0) / 365.0


def lies_sqlite(pfad):
    """OFB-Schema lesen: ofb_individuum, ofb_familie, ofb_familie_kind, optional blank_artikel (Rohtext)."""
    con = sqlite3.connect(pfad)
    con.row_factory = sqlite3.Row
    m = Modell()
    m.quelle = pfad
    spalten = {r[1] for r in con.execute("PRAGMA table_info(ofb_individuum)")}
    tabellen = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    hat_art = "blank_artikel" in tabellen and "artikel_id" in spalten
    m.hat_rohtext = hat_art
    # Nebenzeilen verschmolzener Personen sind keine Personen, nur die kanonische Zeile zaehlt
    nur_kanon =("WHERE i.id NOT IN (SELECT id FROM ofb_person_kanon)"
                 if "ofb_person_kanon" in tabellen else "")
    opt = lambda c: c if c in spalten else "NULL"
    if "ofb_person_kanon" in tabellen:
        for r in con.execute(f"""SELECT k.kanon_id, k.id AS nebenzeile, k.quelle,
                                        a.tod_iso AS tod_kanon, b.tod_iso AS tod_neben,
                                        a.{opt('artikel_id')} AS art_kanon,
                                        b.{opt('artikel_id')} AS art_neben
                                 FROM ofb_person_kanon k
                                 JOIN ofb_individuum a ON a.id = k.kanon_id
                                 JOIN ofb_individuum b ON b.id = k.id"""):
            m.verschmolzen.append(dict(r))
    sql = f"""SELECT i.id, i.vn_kanonisch vn, i.fn_kanonisch fn, i.geschlecht,
                     i.geburt_iso, i.tod_iso, i.beruf, i.notiz, {opt('ort')} ort,
                     {opt('rolle')} rolle, {opt('artikel_id')} artikel_id,
                     {opt('eigenes_artikel_id')} eig, {opt('eltern_artikel_id')} elt
                     {', a.roh_text roh' if hat_art else ''}
              FROM ofb_individuum i
              {'LEFT JOIN blank_artikel a ON a.id = i.artikel_id' if hat_art else ''}
              {nur_kanon}"""
    nach_artikel = defaultdict(list)     # artikel_id -> [Kopf-Ids]
    verweise = []
    for r in con.execute(sql):
        p = Person(r["id"])
        p.vn, p.fn = (r["vn"] or "").strip(), (r["fn"] or "").strip()
        p.geschlecht = r["geschlecht"] if r["geschlecht"] in ("m", "w") else "u"
        p.geb, p.tod = datum(r["geburt_iso"]), datum(r["tod_iso"])
        p.beruf, p.notiz, p.ort = (r["beruf"] or ""), (r["notiz"] or ""), (r["ort"] or "")
        p.rolle = r["rolle"] or ""
        p.artikel = r["artikel_id"]
        if hat_art:
            p.sterbealter = sterbealter_aus_text(r["roh"], r["tod_iso"])
        m.p[p.id] = p
        if r["artikel_id"] is not None and p.rolle == "kopf":
            nach_artikel[r["artikel_id"]].append(p.id)
        if r["eig"] is not None:
            verweise.append((p.id, r["eig"]))
        if r["elt"] is not None and r["artikel_id"] is not None:
            verweise.append((p.id, None, r["elt"], r["artikel_id"]))
    # Kopf/Kind-Doppelführung: Kind mit eigenes_artikel_id = Kopf jenes Artikels
    for v in verweise:
        if len(v) == 2:
            for kopf in nach_artikel.get(v[1], []):
                m.p[v[0]].alias.add(kopf)
                m.p[kopf].alias.add(v[0])
    for r in con.execute("SELECT id, vater_id, mutter_id, heirat_iso, notiz FROM ofb_familie"):
        f = Familie(r["id"])
        f.vater, f.mutter = r["vater_id"], r["mutter_id"]
        f.heirat = datum(r["heirat_iso"])
        f.notiz = r["notiz"] or ""
        m.f[f.id] = f
        for pid in (f.vater, f.mutter):
            if pid in m.p:
                m.p[pid].ehen.append(f.id)
    for r in con.execute("SELECT familie_id, individuum_id FROM ofb_familie_kind "
                         "ORDER BY familie_id, COALESCE(geburtsreihe, 9999), individuum_id"):
        f = m.f.get(r["familie_id"])
        if f is None:
            f = Familie(r["familie_id"])       # Verweis ins Leere, Regel 218 findet es
            m.f[f.id] = f
        f.kinder.append(r["individuum_id"])
        if r["individuum_id"] in m.p:
            m.p[r["individuum_id"]].eltern.append(f.id)
    for p in m.p.values():                 # Ehen chronologisch
        p.ehen.sort(key=lambda fid: (m.f[fid].heirat is None, _tage(m.f[fid].heirat) if m.f[fid].heirat else 0))
    con.close()
    return m


# ------------------------------------------------------------ GEDCOM ----
def lies_gedcom(pfad):
    """GEDCOM 5.5.1 lesen (INDI und FAM mit den gaengigen Tags); Ids sind die Zeiger ohne @."""
    m = Modell()
    m.quelle = pfad
    saetze = []                            # (typ, id, [(level, tag, wert)])
    akt = None
    with open(pfad, encoding="utf-8-sig", errors="replace") as fh:
        for zeile in fh:
            zeile = zeile.rstrip("\r\n")
            if not zeile:
                continue
            teile = zeile.split(" ", 2)
            try:
                lvl = int(teile[0])
            except ValueError:
                continue
            if lvl == 0:
                if len(teile) >= 3 and teile[1].startswith("@"):
                    akt = (teile[2].strip(), teile[1].strip("@"), [])
                    saetze.append(akt)
                else:
                    akt = None
                continue
            if akt is None:
                continue
            tag = teile[1] if len(teile) > 1 else ""
            wert = teile[2] if len(teile) > 2 else ""
            akt[2].append((lvl, tag, wert))

    def ereignis(zeilen, ev):
        """Datum des Ereignisses ev (erste DATE-Zeile unter Level 1 ev)."""
        offen = False
        for lvl, tag, wert in zeilen:
            if lvl == 1:
                offen = (tag == ev)
            elif offen and lvl == 2 and tag == "DATE":
                return datum(wert)
        return None

    for typ, gid, zeilen in saetze:
        if typ == "INDI":
            p = Person(gid)
            for lvl, tag, wert in zeilen:
                if lvl != 1:
                    continue
                if tag == "NAME" and not p.vn and not p.fn:
                    mm = re.match(r"^(.*?)\s*/(.*?)/\s*(.*)$", wert)
                    if mm:
                        p.vn, p.fn = mm.group(1).strip(), mm.group(2).strip()
                    else:
                        p.vn = wert.strip()
                elif tag == "SEX":
                    p.geschlecht = {"M": "m", "F": "w"}.get(wert.strip().upper(), "u")
                elif tag == "OCCU":
                    p.beruf = p.beruf or wert
                elif tag == "NOTE":
                    p.notiz = (p.notiz + " " + wert).strip()
                elif tag == "FAMS":
                    p.ehen.append(wert.strip("@"))
                elif tag == "FAMC":
                    p.eltern.append(wert.strip("@"))
            # Fortsetzungen (CONT/CONC) der Notiz
            offen = False
            for lvl, tag, wert in zeilen:
                if lvl == 1:
                    offen = (tag == "NOTE")
                elif offen and tag in ("CONT", "CONC"):
                    p.notiz = (p.notiz + (" " if tag == "CONT" else "") + wert).strip()
            p.geb, p.taufe = ereignis(zeilen, "BIRT"), ereignis(zeilen, "CHR")
            p.tod, p.begr = ereignis(zeilen, "DEAT"), ereignis(zeilen, "BURI")
            m.p[p.id] = p
        elif typ == "FAM":
            f = Familie(gid)
            for lvl, tag, wert in zeilen:
                if lvl != 1:
                    continue
                if tag == "HUSB":
                    f.vater = wert.strip("@")
                elif tag == "WIFE":
                    f.mutter = wert.strip("@")
                elif tag == "CHIL":
                    f.kinder.append(wert.strip("@"))
            f.heirat = ereignis(zeilen, "MARR")
            m.f[f.id] = f
    # FAMS/FAMC aus Sicht der Familien vervollständigen (einseitige Links)
    for f in m.f.values():
        for pid in (f.vater, f.mutter):
            if pid in m.p and f.id not in m.p[pid].ehen:
                m.p[pid].ehen.append(f.id)
        for kid in f.kinder:
            if kid in m.p and f.id not in m.p[kid].eltern:
                m.p[kid].eltern.append(f.id)
    for p in m.p.values():
        p.ehen = [x for x in p.ehen if x in m.f]
        p.ehen.sort(key=lambda fid: (m.f[fid].heirat is None, _tage(m.f[fid].heirat) if m.f[fid].heirat else 0))
    return m


def lies(pfad):
    with open(pfad, "rb") as fh:
        kopf = fh.read(16)
    if kopf.startswith(b"SQLite format 3"):
        return lies_sqlite(pfad)
    return lies_gedcom(pfad)


# =========================================================================
#  Regeln  -  regel_<id>(m, g) -> [(person_id, familie_id, detail)]
#  g = Grenzwert aus der Regeldatei (float oder None)
# =========================================================================
def _paare_elter_kind(m, wer):
    """(kind, elter, familie) für alle Kinder mit vorhandenem Vater/Mutter."""
    for f in m.f.values():
        e = m.vater(f) if wer == "v" else m.mutter(f)
        if e is None:
            continue
        for k in m.kinder(f):
            yield k, e, f


# ---- 0xx Chronologie -----------------------------------------------------
def regel_010(m, g):   # Tod vor Geburt
    return [(p.id, None, f"geb {dtxt(p.geb)} / tod {dtxt(p.tod)}")
            for p in m.p.values() if vor(p.tod, p.geb)]


def regel_011(m, g):   # Heirat vor Geburt
    return [(p.id, f.id, f"heirat {dtxt(f.heirat)} / geb {dtxt(p.geb)}")
            for f in m.f.values() for p in m.partner(f) if vor(f.heirat, p.geb)]


def regel_012(m, g):   # Heirat nach Tod
    return [(p.id, f.id, f"heirat {dtxt(f.heirat)} / tod {dtxt(p.tod)}")
            for f in m.f.values() for p in m.partner(f) if vor(p.tod, f.heirat)]


def regel_013(m, g):   # Kind vor Mutter geboren
    return [(k.id, f.id, f"kind {dtxt(k.geb)} / mutter {dtxt(e.geb)}")
            for k, e, f in _paare_elter_kind(m, "m") if vor(k.geb, e.geb)]


def regel_014(m, g):   # Kind vor Vater geboren
    return [(k.id, f.id, f"kind {dtxt(k.geb)} / vater {dtxt(e.geb)}")
            for k, e, f in _paare_elter_kind(m, "v") if vor(k.geb, e.geb)]


def _kind_nach_tod(m, wer, grenz_monate):
    out = []
    for k, e, f in _paare_elter_kind(m, wer):
        if k.geb is None or e.tod is None:
            continue
        if voll(k.geb) and voll(e.tod):
            if monate(e.tod, k.geb) > grenz_monate:
                out.append((k.id, f.id, f"kind {dtxt(k.geb)} / tod {'mutter' if wer == 'm' else 'vater'} {dtxt(e.tod)}"))
        elif jahre(e.tod, k.geb) > 1:
            out.append((k.id, f.id, f"kind {dtxt(k.geb)} / tod {'mutter' if wer == 'm' else 'vater'} {dtxt(e.tod)}"))
    return out


def regel_015(m, g):   # Kind nach Tod der Mutter (Grenze in Monaten, Standard 0)
    return _kind_nach_tod(m, "m", g if g is not None else 0)


def regel_016(m, g):   # Kind nach Tod des Vaters (posthum erlaubt: 9,5 Monate)
    return _kind_nach_tod(m, "v", g if g is not None else 9.5)


def regel_017(m, g):   # Kind vor der Ehe der Eltern (Grenze in Jahren)
    g = g if g is not None else 1
    return [(k.id, f.id, f"kind {dtxt(k.geb)} / heirat {dtxt(f.heirat)}")
            for f in m.f.values() if f.vater and f.mutter and f.heirat
            for k in m.kinder(f) if k.geb and jahre(k.geb, f.heirat) is not None and jahre(k.geb, f.heirat) > g]


def regel_018(m, g):   # Datum, das es nicht gibt
    out = []
    for p in m.p.values():
        for art, t in (("geb", p.geb), ("tod", p.tod), ("taufe", p.taufe), ("begr", p.begr)):
            if datum_unmoeglich(t):
                out.append((p.id, None, f"{art} {dtxt(t)}"))
    for f in m.f.values():
        if datum_unmoeglich(f.heirat):
            out.append((None, f.id, f"heirat {dtxt(f.heirat)}"))
    return out


def regel_019(m, g):   # Datum in der Zukunft
    return [(p.id, None, f"geb {dtxt(p.geb)} tod {dtxt(p.tod)}")
            for p in m.p.values()
            if (p.geb and p.geb[0] > JETZT) or (p.tod and p.tod[0] > JETZT)]


def regel_020(m, g):   # Taufe vor Geburt
    return [(p.id, None, f"taufe {dtxt(p.taufe)} / geb {dtxt(p.geb)}")
            for p in m.p.values() if vor(p.taufe, p.geb)]


def regel_021(m, g):   # Begräbnis vor Tod
    return [(p.id, None, f"begr {dtxt(p.begr)} / tod {dtxt(p.tod)}")
            for p in m.p.values() if vor(p.begr, p.tod)]


def regel_022(m, g):   # Geburtsdatum = Heiratsdatum
    return [(p.id, f.id, f"geb = heirat {dtxt(p.geb)}")
            for f in m.f.values() for p in m.partner(f)
            if voll(p.geb) and voll(f.heirat) and p.geb == f.heirat]


def regel_023(m, g):   # Kinder nicht chronologisch
    out = []
    for f in m.f.values():
        ks = [k for k in m.kinder(f) if voll(k.geb)]
        for a, b in zip(ks, ks[1:]):
            if _tage(a.geb) > _tage(b.geb):
                out.append((b.id, f.id, f"{a.name()} {dtxt(a.geb)} steht vor {b.name()} {dtxt(b.geb)}"))
                break
    return out


# ---- 1xx Altersgrenzen -----------------------------------------------------
def regel_110(m, g):   # Lebensalter
    g = g if g is not None else 110
    return [(p.id, None, f"geb {dtxt(p.geb)} tod {dtxt(p.tod)} = {jahre(p.geb, p.tod):.0f} J")
            for p in m.p.values() if p.geb and p.tod and jahre(p.geb, p.tod) > g]


def _elter_alter(m, wer, unter=None, ueber=None):
    out = []
    for k, e, f in _paare_elter_kind(m, wer):
        a = jahre(e.geb, k.geb)
        if a is None:
            continue
        if (unter is not None and 0 <= a < unter) or (ueber is not None and a > ueber):
            out.append((k.id, f.id, f"{'mutter' if wer == 'm' else 'vater'} geb {dtxt(e.geb)}, kind geb {dtxt(k.geb)} = {a:.0f} J"))
    return out


def regel_111(m, g):   # Mutter zu jung
    return _elter_alter(m, "m", unter=g if g is not None else 14)


def regel_112(m, g):   # Mutter zu alt
    return _elter_alter(m, "m", ueber=g if g is not None else 55)


def regel_113(m, g):   # Vater zu jung
    return _elter_alter(m, "v", unter=g if g is not None else 14)


def regel_114(m, g):   # Vater zu alt
    return _elter_alter(m, "v", ueber=g if g is not None else 75)


def _heirat_alter(m, unter=None, ueber=None):
    out = []
    for f in m.f.values():
        for p in m.partner(f):
            a = jahre(p.geb, f.heirat)
            if a is None:
                continue
            if (unter is not None and 0 <= a < unter) or (ueber is not None and a > ueber):
                out.append((p.id, f.id, f"geb {dtxt(p.geb)}, heirat {dtxt(f.heirat)} = {a:.0f} J"))
    return out


def regel_115(m, g):   # Heirat zu jung
    return _heirat_alter(m, unter=g if g is not None else 15)


def regel_116(m, g):   # Heirat zu alt
    return _heirat_alter(m, ueber=g if g is not None else 90)


def regel_117(m, g):   # Altersdifferenz Ehepartner
    g = g if g is not None else 40
    out = []
    for f in m.f.values():
        v, w = m.vater(f), m.mutter(f)
        if v and w and v.geb and w.geb and abs(jahre(v.geb, w.geb)) > g:
            out.append((v.id, f.id, f"vater {dtxt(v.geb)} / mutter {dtxt(w.geb)}"))
    return out


def regel_118(m, g):   # Geschwister zu dicht (Monate); Zwillinge = gleicher Tag
    g = g if g is not None else 8
    out = []
    for f in m.f.values():
        ks = [k for k in m.kinder(f) if voll(k.geb)]
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                d = abs(monate(a.geb, b.geb))
                if 0.1 <= d <= g and not m.selbe_person(a, b):
                    out.append((a.id, f.id, f"{a.name()} {dtxt(a.geb)} / {b.name()} {dtxt(b.geb)}"))
    return out


def regel_119(m, g):   # Spanne aller Kinder
    g = g if g is not None else 30
    out = []
    for f in m.f.values():
        js = [k.geb[0] for k in m.kinder(f) if k.geb]
        if js and max(js) - min(js) > g:
            out.append((None, f.id, f"spanne {max(js) - min(js)} J"))
    return out


def regel_227(m, g):   # derselbe Quellentext bei mehr als einer Person eines Artikels
    """Ein Notiz-Abschnitt, der bei zwei Personen desselben Artikels steht, ist doppelt erfasst."""
    out = []
    je_artikel = defaultdict(list)
    for p in m.p.values():
        if p.notiz and getattr(p, "artikel", None):
            je_artikel[p.artikel].append(p)
    for aid, leute in je_artikel.items():
        for a in leute:
            for teil in (t.strip() for t in a.notiz.split(";")):
                if len(teil) <= 12:
                    continue
                for b in leute:
                    # Zwillinge tragen denselben Hinweis absichtlich
                    if a.geb and a.geb == b.geb:
                        continue
                    if b.id != a.id and teil in b.notiz and a.id < b.id:
                        out.append((a.id, None, teil[:70]))
                        break
    return out


def regel_226(m, g):   # dasselbe Elternpaar als zwei Familien
    paare = {}
    out = []
    for f in m.f.values():
        if not (f.vater and f.mutter):
            continue
        k = (f.vater, f.mutter)
        if k in paare:
            a = paare[k]
            if a.heirat == f.heirat or not a.heirat or not f.heirat:
                out.append((None, f.id, f"wie Familie {a.id}" + (f" (oo {dtxt(f.heirat)})" if f.heirat else "")))
        else:
            paare[k] = f
    return out


def regel_124(m, g):   # Luecke zwischen aufeinanderfolgenden Geschwistern (Jahre)
    g = g if g is not None else 12
    out = []
    for f in m.f.values():
        js = sorted(((k.geb[0], k) for k in m.kinder(f) if k.geb), key=lambda t: t[0])
        for (ja, a), (jb, b) in zip(js, js[1:]):
            if jb - ja > g:
                out.append((b.id, f.id, f"{a.name()} {dtxt(a.geb)} / {b.name()} {dtxt(b.geb)}: {jb - ja} J Abstand"))
    return out


def regel_120(m, g):   # zu viele Kinder
    g = g if g is not None else 20
    return [(None, f.id, f"{len(f.kinder)} Kinder") for f in m.f.values() if len(f.kinder) > g]


def regel_123(m, g):   # zu viele Kinder je Mutter ueber alle Ehen
    g = g if g is not None else 20
    out = []
    for p in m.p.values():
        if p.geschlecht == "m":
            continue
        kids = set()
        for fid in p.ehen:
            f = m.f[fid]
            if f.mutter == p.id:
                kids.update(f.kinder)
        if len(kids) > g:
            out.append((p.id, None, f"{len(kids)} Kinder in {len(p.ehen)} Ehe(n)"))
    return out


def regel_121(m, g):   # zu viele Ehen
    g = g if g is not None else 5
    return [(p.id, None, f"{len(p.ehen)} Ehen") for p in m.p.values() if len(p.ehen) > g]


def regel_125(m, g):   # Hochzeit nach dem eigenen Tod
    """Eigene Heirat nach dem eigenen Tod; Regel 122 prueft nur die Wiederheirat nach dem Tod des Partners."""
    out = []
    for p in m.p.values():
        if not voll(p.tod):
            continue
        for f in p.ehen:
            fam = m.f.get(f) if not hasattr(f, "heirat") else f
            if fam and voll(fam.heirat) and monate(p.tod, fam.heirat) > 0:
                out.append((p.id, fam.id, f"tod {dtxt(p.tod)}, heirat {dtxt(fam.heirat)}"))
    return out


def regel_122(m, g):   # Wiederheirat zu früh nach Tod des Partners (Monate)
    g = g if g is not None else 2
    out = []
    for p in m.p.values():
        for f1, f2 in zip(p.ehen, p.ehen[1:]):
            alt = [q for q in m.partner(m.f[f1]) if q.id != p.id]
            neu = m.f[f2]
            if alt and voll(alt[0].tod) and voll(neu.heirat):
                d = monate(alt[0].tod, neu.heirat)
                if 0 <= d <= g:
                    out.append((p.id, f2.id if hasattr(f2, "id") else f2, f"tod partner {dtxt(alt[0].tod)}, neue heirat {dtxt(neu.heirat)}"))
    return out


# ---- 2xx Struktur ------------------------------------------------------------
def _leer(p):
    return (not p.vn and p.fn in ("", "NN") and not p.geb and not p.tod
            and not p.beruf and not p.notiz)


def regel_210(m, g):   # Person ohne alles
    return [(p.id, None, f"rolle {p.rolle or '?'}") for p in m.p.values()
            if _leer(p) and not p.ehen and not p.eltern]


def regel_211(m, g):   # ohne Verbindung
    return [(p.id, None, p.name()) for p in m.p.values() if not p.ehen and not p.eltern]


def regel_212(m, g):   # NN-Partner ohne jede Angabe in kinderloser Ehe
    out = []
    for f in m.f.values():
        if f.kinder:
            continue
        for p in m.partner(f):
            if _leer(p) and not p.ort:
                out.append((p.id, f.id, f"rolle {p.rolle or '?'}"))
    return out


def regel_213(m, g):   # Kind in zwei Familien
    return [(p.id, p.eltern[0], "familien " + ",".join(str(x) for x in p.eltern))
            for p in m.p.values() if len(p.eltern) > 1]


def regel_214(m, g):   # Kind und Elter derselben Familie
    return [(p.id, fid, "kind und elter zugleich") for p in m.p.values()
            for fid in p.eltern if fid in p.ehen]


def regel_215(m, g):   # gleiches Geschlecht
    out = []
    for f in m.f.values():
        v, w = m.vater(f), m.mutter(f)
        if v and w and v.geschlecht in ("m", "w") and v.geschlecht == w.geschlecht:
            out.append((v.id, f.id, f"vater {v.geschlecht} ({v.vn}), mutter {w.geschlecht} ({w.vn})"))
    return out


def regel_216(m, g):   # Frau als Vater / Mann als Mutter
    out = []
    for f in m.f.values():
        v, w = m.vater(f), m.mutter(f)
        if v and v.geschlecht == "w":
            out.append((v.id, f.id, f"vater ist w ({v.vn})"))
        if w and w.geschlecht == "m":
            out.append((w.id, f.id, f"mutter ist m ({w.vn})"))
    return out


def regel_217(m, g):   # Familie ohne Inhalt
    return [(None, f.id, "familie ohne partner und kinder") for f in m.f.values()
            if f.vater is None and f.mutter is None and not f.kinder]


def regel_218(m, g):   # Verweis ins Leere
    out = []
    for f in m.f.values():
        for pid in (f.vater, f.mutter, *f.kinder):
            if pid is not None and pid not in m.p:
                out.append((None, f.id, f"fehlende person {pid}"))
    return out


KEIN_NAME = {"", "NN", "Anonymus", "Anonyma"}      # Platzhalter, keine Rufnamen


def regel_219(m, g):   # Dublette: gleicher Name + volles Geburtsdatum, keine Alias-Paare
    gruppen = defaultdict(list)
    for p in m.p.values():
        if voll(p.geb) and p.fn not in ("", "NN") and p.vn not in KEIN_NAME:
            gruppen[(p.vn, p.fn, p.geb)].append(p)
    out = []
    for (vn, fn, geb), ps in gruppen.items():
        for i, a in enumerate(ps):
            for b in ps[i + 1:]:
                if not m.selbe_person(a, b):
                    out.append((a.id, None, f"{vn} {fn} {dtxt(geb)} = #{b.id}"))
    return out


def _geschwister(m, p):
    s = set()
    for fid in p.eltern:
        s.update(m.f[fid].kinder)
    s.discard(p.id)
    return s


def regel_220(m, g):   # Ehe unter Geschwistern
    out = []
    for f in m.f.values():
        v, w = m.vater(f), m.mutter(f)
        if v and w and w.id in _geschwister(m, v):
            out.append((v.id, f.id, f"{v.name()} und {w.name()} sind Geschwister"))
    return out


def regel_221(m, g):   # Ehe Elter/Kind
    out = []
    for f in m.f.values():
        v, w = m.vater(f), m.mutter(f)
        if not (v and w):
            continue
        for fid in w.eltern:
            if v.id in (m.f[fid].vater, m.f[fid].mutter):
                out.append((v.id, f.id, f"{v.name()} ist Elter von {w.name()}"))
        for fid in v.eltern:
            if w.id in (m.f[fid].vater, m.f[fid].mutter):
                out.append((w.id, f.id, f"{w.name()} ist Elter von {v.name()}"))
    return out


def regel_222(m, g):   # Bigamie: neue Heirat, während der vorige Partner sicher noch lebt
    out = []
    for p in m.p.values():
        for f1, f2 in zip(p.ehen, p.ehen[1:]):
            alt = [q for q in m.partner(m.f[f1]) if q.id != p.id]
            neu = m.f[f2]
            if alt and alt[0].tod and neu.heirat and vor(neu.heirat, alt[0].tod):
                out.append((p.id, f2, f"heirat {dtxt(neu.heirat)}, voriger partner {alt[0].name()} stirbt erst {dtxt(alt[0].tod)}"))
    return out


def regel_223(m, g):   # Ehepaar mit gleichem Nachnamen
    out = []
    for f in m.f.values():
        v, w = m.vater(f), m.mutter(f)
        if v and w and v.fn and v.fn == w.fn and v.fn != "NN":
            out.append((v.id, f.id, f"beide {v.fn}"))
    return out


def regel_224(m, g):   # zwei lebende Geschwister mit gleichem Vornamen
    out = []
    for f in m.f.values():
        ks = m.kinder(f)
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                if a.vn not in KEIN_NAME and a.vn == b.vn and a.geb and b.geb and not m.selbe_person(a, b):
                    frueh, spaet = (a, b) if (vor(a.geb, b.geb) is not False) else (b, a)
                    if frueh.tod is None or vor(spaet.geb, frueh.tod):
                        out.append((spaet.id, f.id, f"{a.vn}: {dtxt(frueh.geb)} (tod {dtxt(frueh.tod)}) und {dtxt(spaet.geb)}"))
    return out


def regel_225(m, g):   # Ahnenkreis: jemand ist sein eigener Vorfahr
    out = []
    eltern_von = {}
    for p in m.p.values():
        s = set()
        for fid in p.eltern:
            f = m.f[fid]
            s.update(x for x in (f.vater, f.mutter) if x is not None)
        eltern_von[p.id] = s
    for start in m.p:
        gesehen, stapel = set(), list(eltern_von[start])
        while stapel:
            x = stapel.pop()
            if x == start:
                out.append((start, None, "eigener Vorfahr"))
                break
            if x in gesehen or x not in eltern_von:
                continue
            gesehen.add(x)
            stapel.extend(eltern_von[x])
    return out


# ---- 3xx Felder --------------------------------------------------------------
WEIBLICHE_RUFNAMEN = {
    "Walburga", "Walpurga", "Maria", "Anna", "Catharina", "Katharina", "Margaretha", "Margarethe",
    "Barbara", "Elisabetha", "Elisabeth", "Magdalena", "Agnes", "Ursula", "Christina", "Christine",
    "Rosina", "Regina", "Dorothea", "Sophia", "Sophie", "Johanna", "Eva", "Susanna", "Agatha",
    "Apollonia", "Veronica", "Sibylla", "Salome", "Judith", "Justina", "Friederike", "Wilhelmine",
    "Louise", "Luise", "Caroline", "Charlotte", "Jacobina", "Jacobine", "Philippina", "Christiana",
    "Beata", "Benigna", "Euphrosina", "Helena", "Ottilia", "Sabina", "Sara", "Rebecca", "Esther",
    "Hanna", "Lydia", "Martha", "Emilie", "Pauline", "Mathilde", "Auguste", "Ernestine", "Henriette",
    "Theresia"}
RE_FLOSKEL = re.compile(r"(?i)\b(keine? angaben?|unbekannt|ohne namen|findelkind|spurius|spuria|anonym|kein nachname|tochter|sohn|witwe|wittib|kind)\b")
RE_ORT_IM_VN = re.compile(r"(?i)\b(zu|von|aus|in|nacher|bey|bei) [A-ZÄÖÜ][a-zäöüß]{3,}|\b(Tübingen|Stuttgart|Esslingen|Schorndorf|Winterbach|Waiblingen|Göppingen|Backnang|Lorch|Welzheim|Gmünd|Heilbronn|Ulm|Ludwigsburg|Kirchheim|Nürtingen|Reutlingen|Urach|Böblingen|Herrenberg|Calw|Marbach|Weinsberg|Cannstatt|Plüderhausen|Urbach|Beutelsbach|Grunbach|Geradstetten|Hebsack|Schnait|Endersbach|Fellbach|Haubersbronn|Miedelsbach|Schlichten|Oberberken|Baiereck|Steinenberg|Rudersberg|Buhlbronn|Hohengehren|Schornbach)\b")
RE_VERKLEBT = re.compile(r"[a-zäöüß][A-ZÄÖÜ][a-zäöüß]")
RE_MEHRERE_FN = re.compile(r"^[A-ZÄÖÜ][a-zäöüß]+([ ,/]+[A-ZÄÖÜ][a-zäöüß]+)+$")
RE_FN_PARTIKEL = re.compile(r"(?i)(^| )(von|van|de|zu|auf|der|dem|und|genannt|gen\.)( |$)")
RE_DATUM_IM_NAMEN = re.compile(r"\d{4}|\d{1,2}\.\s*\d{1,2}\.")
RE_BERUF_NAME = re.compile(r"^(Hans|Johann|Johannes|Georg|Jerg|Jacob|Michael|Conrad|Caspar|Martin|Christoph|Friedrich|Ludwig|Wilhelm|Christian|Gottlieb|Andreas|Philipp|Jakob|Anna|Maria|Catharina|Margaretha|Barbara)\b")
# Regel 317: in Notizen steht nur Quellentext; das Muster nennt Verfahrenswoerter,
# nicht einzelne Formulierungen, sonst rutschen neue Bau-Saetze durch.
RE_META = re.compile(
    r"Prüfhinweis|Pruefhinweis|Zuordnung durch die Auswertung|Aus dem Namensfeld übernommen"
    r"|Beim Einlesen|bis zur Klärung|bis zur Klaerung"
    r"|\b(?:Fliesstext|Fließtext|Parser|Regel \d|Auswertung|Einlesen|Import|Export|Zuordnung"
    r"|automatisch|maschinell|Skript|Datenbank)\b")
RE_ORT_IM_FN = re.compile(r"(?i)\b(zu|aus|in|bey|bei|nacher) [A-ZÄÖÜ]")


def regel_310(m, g):
    return [(p.id, None, f"fn = {p.fn}") for p in m.p.values() if p.fn in WEIBLICHE_RUFNAMEN]


def regel_311(m, g):
    return [(p.id, None, f"vn = {p.vn} / fn = {p.fn}") for p in m.p.values()
            if RE_FLOSKEL.search(p.vn) or re.search(r"(?i)\b(keine? angaben?|unbekannt|ohne namen|angaben)\b", p.fn)]


def regel_312(m, g):
    return [(p.id, None, f"vn = {p.vn}") for p in m.p.values() if RE_ORT_IM_VN.search(p.vn)]


def regel_313(m, g):
    return [(p.id, None, f"vn = {p.vn} / fn = {p.fn}") for p in m.p.values()
            if RE_VERKLEBT.search(p.fn) or RE_VERKLEBT.search(p.vn)]


def regel_314(m, g):
    return [(p.id, None, f"fn = {p.fn}") for p in m.p.values()
            if RE_MEHRERE_FN.match(p.fn) and not RE_FN_PARTIKEL.search(p.fn)]


def regel_315(m, g):
    return [(p.id, None, f"vn = {p.vn} / fn = {p.fn}") for p in m.p.values()
            if RE_DATUM_IM_NAMEN.search(p.vn) or RE_DATUM_IM_NAMEN.search(p.fn)]


def regel_316(m, g):
    return [(p.id, None, f"beruf = {p.beruf}") for p in m.p.values() if p.beruf and RE_BERUF_NAME.match(p.beruf)]


def regel_317(m, g):
    out = [(p.id, None, p.notiz[:80]) for p in m.p.values() if RE_META.search(p.notiz)]
    out += [(None, f.id, f.notiz[:80]) for f in m.f.values() if RE_META.search(f.notiz)]
    return out


def regel_318(m, g):
    return [(p.id, None, f"fn = {p.fn}") for p in m.p.values() if RE_ORT_IM_FN.search(p.fn)]


# Regeln 320/321 lesen den Vornamen-Atlas; der Selbsttest setzt _ATLAS_VN direkt
_ATLAS_VN = None
RE_KLAMMER = re.compile(r"\(([^)]*)\)?")
RE_WORT = re.compile(r"[\wäöüßÄÖÜ-]+")


def _atlas_lesen(name):
    """(verworfen, bestaetigt-oder-vorschlag) eines Atlas."""
    import csv
    verworfen, bestaetigt = set(), set()
    pfad = os.path.join(HIER, "..", "atlas", f"{name}.csv")
    if os.path.exists(pfad):
        for r in csv.DictReader(open(pfad, encoding="utf-8"), delimiter=";"):
            if r.get("status") == "verworfen":
                verworfen.add(r["original"])
            elif r.get("status") in ("bestaetigt", "vorschlag"):
                bestaetigt.add(r["original"])
    return verworfen, bestaetigt


def atlas_vornamen():
    global _ATLAS_VN
    if _ATLAS_VN is None:
        _ATLAS_VN = _atlas_lesen("vornamen")
    return _ATLAS_VN


_ATLAS_NN = None


def atlas_nachnamen():
    global _ATLAS_NN
    if _ATLAS_NN is None:
        _ATLAS_NN = _atlas_lesen("nachnamen")
    return _ATLAS_NN


def regel_323(m, g):   # verworfene Atlas-Form im Nachnamensfeld (Spiegel von 320)
    verworfen, _ = atlas_nachnamen()
    return [(p.id, None, f"vn = {p.vn} / fn = {p.fn}") for p in m.p.values() if p.fn and p.fn in verworfen]


def regel_320(m, g):   # verworfene Atlas-Form im Vornamensfeld
    verworfen, _ = atlas_vornamen()
    out = []
    for p in m.p.values():
        treffer = sorted(set(RE_WORT.findall(p.vn)) & verworfen)
        if treffer:
            out.append((p.id, None, f"vn = {p.vn} [{', '.join(treffer)}]"))
    return out


def regel_321(m, g):   # Klammerzusatz im Vornamensfeld, der kein Vorname ist
    _, bestaetigt = atlas_vornamen()
    out = []
    for p in m.p.values():
        if "(" not in p.vn and ")" not in p.vn:
            continue
        inhalt = RE_KLAMMER.findall(p.vn)
        woerter = [w for teil in inhalt for w in RE_WORT.findall(teil)]
        if woerter and all(w in bestaetigt for w in woerter):
            continue                       # Namensklammer wie „(Maria) Magdalena“
        out.append((p.id, None, f"vn = {p.vn}"))
    return out


_ATLAS_ORTE = None


def atlas_orte():
    global _ATLAS_ORTE
    if _ATLAS_ORTE is None:
        import csv
        pfad = os.path.join(HIER, "..", "atlas", "orte.csv")
        _ATLAS_ORTE = set()
        if os.path.exists(pfad):
            for r in csv.DictReader(open(pfad, encoding="utf-8"), delimiter=";"):
                if r.get("status") in ("bestaetigt", "vorschlag", "mehrheit"):
                    _ATLAS_ORTE.add(r["original"])
    return _ATLAS_ORTE


def regel_322(m, g):   # Ortsname im Nachnamensfeld
    # Ein Ort, der nie Artikelnachname ist, steht im Nachnamensfeld nur durch einen abgeschnittenen Partnernamen
    orte = atlas_orte()
    kopf_fn = {p.fn for p in m.p.values() if p.rolle == "kopf"}
    if not kopf_fn:
        # GEDCOM kennt keine Artikelrolle, dort sind die Ehemaenner die Koepfe
        kopf_fn ={p.fn for f in m.f.values() for p in m.partner(f) if p.geschlecht == "m"}
    return [(p.id, None, f"vn = {p.vn} / fn = {p.fn}") for p in m.p.values()
            if p.fn and p.fn in orte and p.fn not in kopf_fn]


def regel_319(m, g):   # Partner mit unbekanntem Geschlecht
    return [(p.id, f.id, p.name()) for f in m.f.values() for p in m.partner(f) if p.geschlecht == "u"]


# ---- 4xx Quellen / projektspezifisch ------------------------------------------
def regel_410(m, g):   # Sterbealter im Text widerspricht den Daten (Jahre)
    g = g if g is not None else 1
    if not m.hat_rohtext:
        return []
    out = []
    for p in m.p.values():
        if p.sterbealter is None or not (p.geb and p.tod):
            continue
        a = jahre(p.geb, p.tod)
        if a is not None and abs(a - p.sterbealter) > g:
            out.append((p.id, None, f"tod {dtxt(p.tod)}: alter lt. text {p.sterbealter:.1f} J, lt. daten {a:.1f} J"))
    return out


_RE_TAGDATUM = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?(1[3-9]\d\d)$")


def regel_411(m, g):   # verschmolzene Person, zwei verschiedene Sterbetage
    """Zwei verschmolzene Artikel nennen dieselbe Person mit verschiedenem Sterbetag; die Karte zeigt nur den kanonischen."""
    out = []
    for v in m.verschmolzen:
        ta = re.sub(r"\s+", "", v.get("tod_kanon") or "")
        tb = re.sub(r"\s+", "", v.get("tod_neben") or "")
        if not (_RE_TAGDATUM.match(ta) and _RE_TAGDATUM.match(tb)) or ta == tb:
            continue
        wo = f" (Artikel {v['art_kanon']} / {v['art_neben']})" if v.get("art_kanon") else ""
        out.append((v["kanon_id"], None,
                    f"in der Vorlage zwei Sterbetage: {v['tod_kanon']} / {v['tod_neben']}{wo}"))
    return out


# =========================================================================
#  Regeldatei lesen, Lauf, Ausgabe
# =========================================================================
def lies_regeln(pfad=REGELDATEI):
    regeln = []
    for nr, zeile in enumerate(open(pfad, encoding="utf-8"), 1):
        z = zeile.strip()
        if not z or z.startswith("#"):
            continue
        teile = [t.strip() for t in z.split("|")]
        # Zeilen ohne Spalte 'art' gelten als 'unmoeglich'
        art = "unmoeglich"
        if len(teile) > 1 and teile[1].lower() in ("unmoeglich", "muss"):
            art = teile[1].lower()
            teile = teile[:1] + teile[2:]
        if len(teile) < 4:
            print(f"  !! pruefregeln.txt Zeile {nr}: erwartet 'id | art | schwere | grenzwert | frage | herkunft'")
            continue
        rid, schwere, grenz = teile[0], teile[1].lower(), teile[2]
        frage = teile[3]
        herkunft = teile[4] if len(teile) > 4 else ""
        aufloesung = teile[5] if len(teile) > 5 else ""
        gw = None
        if grenz:
            mm = re.match(r"^\s*([\d.,]+)\s*([A-Za-z]*)", grenz)
            if mm:
                gw = float(mm.group(1).replace(",", "."))
        regeln.append({"id": rid, "art": art, "schwere": schwere, "grenz": grenz, "gw": gw,
                       "frage": frage, "herkunft": herkunft, "aufloesung": aufloesung,
                       "fn": globals().get(f"regel_{rid}")})
    return regeln


def ist_vorlage(regel):
    """Misst die Regel Widersprüche der Vorlage (Katalogspalte `aufloesung` nennt „original")?"""
    return "original" in (regel.get("aufloesung") or "")


def schreibe_messreihe(pfad, db, ergebnis, kommentar=""):
    """Eine Zeile je Lauf anhaengen (Datum, DB, Kommentar, Summen, je Regel eine Spalte)."""
    import csv
    import datetime
    # `vergleichbar` zaehlt nur Regeln der vorigen Zeile (Qualitaetsmass), `neue_regeln` den Rest
    zeile ={"datum": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), "db": os.path.basename(db),
             "kommentar": kommentar,
             "fehler": sum(len(r) for c, r in ergebnis if r and c["schwere"] == "fehler"),
             "warnungen": sum(len(r) for c, r in ergebnis if r and c["schwere"] != "fehler"),
             # nur fehler_bau sperrt den Export
             "fehler_bau": sum(len(r) for c, r in ergebnis
                               if r and c["schwere"] == "fehler" and not ist_vorlage(c)),
             "fehler_vorlage": sum(len(r) for c, r in ergebnis
                                   if r and c["schwere"] == "fehler" and ist_vorlage(c))}
    for c, rows in ergebnis:
        zeile[c["id"]] = len(rows) if rows is not None else ""
    alt = []
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8", newline="") as fh:
            alt = list(csv.DictReader(fh, delimiter=";"))
    if alt:
        vorige = {k for k, v in alt[-1].items() if k[:1].isdigit() and (v or "").strip()}
        zeile["vergleichbar"] = sum(len(r) for c, r in ergebnis
                                    if r is not None and c["id"] in vorige)
        zeile["neue_regeln"] = sum(len(r) for c, r in ergebnis
                                   if r is not None and c["id"] not in vorige)
        zeile["vergleichbar_vorher"] = sum(int(alt[-1][k]) for k in vorige
                                           if (alt[-1].get(k) or "").strip().isdigit()
                                           and k in {c["id"] for c, r in ergebnis if r is not None})
        # gestiegene/gefallene Regeln gegen den vorigen Lauf derselben Datei
        vorige_zeile =next((r for r in reversed(alt) if r.get("db") == zeile["db"]), None)
        if vorige_zeile:
            hoch, runter = [], []
            for c, rows in ergebnis:
                if rows is None or not (vorige_zeile.get(c["id"]) or "").strip().isdigit():
                    continue
                d = len(rows) - int(vorige_zeile[c["id"]])
                (hoch if d > 0 else runter).append((c["id"], d, c["schwere"] == "fehler")) if d else None
            print(f"Gegen den vorigen Lauf ({vorige_zeile['datum']}, {vorige_zeile['kommentar'][:50]}):")
            if not hoch and not runter:
                print("  keine Regel veraendert")
            for k, liste in (("HOCH", hoch), ("runter", runter)):
                for rid, d, ist_f in sorted(liste, key=lambda t: -abs(t[1])):
                    print(f"  {k:6} {rid} {d:+5}  {'F' if ist_f else 'w'}")
            if hoch:
                print(f"  -> {len(hoch)} Regel(n) gestiegen: jede im Commit/NEUBAU.md erklaeren oder Aenderung zuruecknehmen")
    felder = ["datum", "db", "kommentar", "fehler", "warnungen",
              "vergleichbar", "vergleichbar_vorher", "neue_regeln", "fehler_bau", "fehler_vorlage"]
    for r in alt + [zeile]:
        for k in r:
            if k not in felder:
                felder.append(k)
    with open(pfad, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=felder, delimiter=";", lineterminator="\n")
        w.writeheader()
        for r in alt + [zeile]:
            w.writerow({f: r.get(f, "") for f in felder})


def lauf(pfad, nur=None, zeigen=0, trocken=False, tsv=None, regeldatei=REGELDATEI, messreihe=None, kommentar=""):
    m = lies(pfad)
    regeln = [r for r in lies_regeln(regeldatei) if not nur or r["id"].startswith(nur)]
    art = "SQLite" if m.hat_rohtext or isinstance(next(iter(m.p), 0), int) else "GEDCOM"
    print(f"{os.path.basename(pfad)} ({art}): {len(m.p)} Personen, {len(m.f)} Familien, {len(regeln)} Regeln")
    ergebnis, fehler, fehler_bau = [], 0, 0
    for r in regeln:
        if r["fn"] is None:
            print(f"  !! Regel {r['id']}: keine Funktion regel_{r['id']} im Motor")
            ergebnis.append((r, None))
            continue
        rows = r["fn"](m, r["gw"])
        if r["schwere"] == "fehler":
            fehler += len(rows)
            if not ist_vorlage(r):
                fehler_bau += len(rows)
        ergebnis.append((r, rows))
        mark = "F" if r["schwere"] == "fehler" else "w"
        print(f"  {mark} {r['id']} {len(rows):>6}   {r['frage']}" + (f"  [{r['grenz']}]" if r["grenz"] else "")
              + ("  (Vorlage)" if r["schwere"] == "fehler" and ist_vorlage(r) else ""))
        for row in rows[:zeigen]:
            print(f"        p={row[0]} f={row[1]}  {row[2]}")
    gesamt = sum(len(x) for _, x in ergebnis if x)
    print(f"Treffer gesamt: {gesamt}, davon Fehler: {fehler} (Bau {fehler_bau}, Vorlage {fehler - fehler_bau})"
          f"  ->  Export {'GESPERRT' if fehler_bau else 'frei'}"
          + (f" ({fehler_bau} Bau-Fehler)" if fehler_bau else f" ({fehler - fehler_bau} Vorlage-Widersprüche bleiben sichtbar)"))
    if art == "SQLite" and not trocken and not nur:
        schreibe_pruefliste(pfad, ergebnis)
    if tsv:
        art = {}
        try:                                   # Artikel je Person, damit die Liste ohne DB lesbar ist
            con = sqlite3.connect(f"file:{pfad}?mode=ro", uri=True)
            art = {i: a for i, a in con.execute("SELECT id, artikel_id FROM ofb_individuum")}
            con.close()
        except Exception:
            art = {}
        with open(tsv, "w", encoding="utf-8") as fh:
            fh.write("regel;schwere;frage;person_id;familie_id;artikel_id;detail\n")
            for r, rows in ergebnis:
                for row in rows or []:
                    fh.write(f"{r['id']};{r['schwere']};{r['frage']};{row[0] or ''};{row[1] or ''};"
                             f"{art.get(row[0], '') or ''};{str(row[2]).replace(';', ',')}\n")
    if messreihe:
        schreibe_messreihe(messreihe, pfad, ergebnis, kommentar)
    return fehler_bau


def schreibe_pruefliste(db, ergebnis):
    con = sqlite3.connect(db)
    con.executescript("""
        DROP TABLE IF EXISTS pruefliste;   -- reines Bauprodukt dieses Laufs
        CREATE TABLE pruefliste (
          regel TEXT NOT NULL, schwere TEXT NOT NULL,
          person_id INTEGER, familie_id INTEGER, detail TEXT,
          lauf_am TEXT NOT NULL DEFAULT (datetime('now')));
        CREATE INDEX IF NOT EXISTS idx_pruefliste_regel ON pruefliste(regel);
        CREATE INDEX IF NOT EXISTS idx_pruefliste_person ON pruefliste(person_id);
        DELETE FROM pruefliste;""")
    con.executemany("INSERT INTO pruefliste(regel, schwere, person_id, familie_id, detail) VALUES (?,?,?,?,?)",
                    [(r["id"], r["schwere"], row[0], row[1], row[2])
                     for r, rows in ergebnis for row in (rows or [])])
    con.commit()
    con.close()


def katalog(regeldatei=REGELDATEI):
    print("| Id | Art | Schwere | Grenze | Frage | Herkunft | Auflösung |")
    print("|---|---|:-:|---|---|---|---|")
    for r in lies_regeln(regeldatei):
        s = "**F**" if r["schwere"] == "fehler" else "w"
        print(f"| {r['id']} | {r['art']} | {s} | {r['grenz']} | {r['frage']} | {r['herkunft']} | {r['aufloesung']} |")


# =========================================================================
#  Selbsttest: je Regel ein Mini-Fall (SQLite-Schema im Speicher)
#  Jeder Fall: (SQL zum Befüllen, erwartete person_ids-Menge oder Anzahl)
# =========================================================================
SCHEMA_MIN = """
CREATE TABLE ofb_individuum (id INTEGER PRIMARY KEY, artikel_id INTEGER, rolle TEXT,
  vn_kanonisch TEXT DEFAULT '', fn_kanonisch TEXT DEFAULT '', geschlecht TEXT,
  geburt_iso TEXT, tod_iso TEXT, beruf TEXT, notiz TEXT, ort TEXT,
  eigenes_artikel_id INTEGER, eltern_artikel_id INTEGER);
CREATE TABLE ofb_familie (id INTEGER PRIMARY KEY, vater_id INTEGER, mutter_id INTEGER,
  heirat_iso TEXT, notiz TEXT);
CREATE TABLE ofb_familie_kind (familie_id INTEGER, individuum_id INTEGER, geburtsreihe INTEGER);
CREATE TABLE blank_artikel (id INTEGER PRIMARY KEY, roh_text TEXT);
"""
P_ = "INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch,geschlecht,geburt_iso,tod_iso) VALUES "
F_ = "INSERT INTO ofb_familie(id,vater_id,mutter_id,heirat_iso) VALUES "
K_ = "INSERT INTO ofb_familie_kind VALUES "
SELBSTTEST_FAELLE = {
    "010": (P_ + "(1,'A','X','m','12.5. 1745','3.1. 1740'),(2,'B','X','w','1745','1740'),(3,'C','X','m','12.5. 1745','1745'),(4,'D','X','m','1671-12-15','1671-01-02')", {1, 2, 4}),
    "011": (P_ + "(1,'A','X','m','1700',NULL),(2,'B','Y','w','1690',NULL);" + F_ + "(1,1,2,'3.3. 1695')", {1}),
    "012": (P_ + "(1,'A','X','m',NULL,'1.1. 1700'),(2,'B','Y','w',NULL,NULL);" + F_ + "(1,1,2,'3.3. 1701')", {1}),
    "013": (P_ + "(1,'M','X','w','1720',NULL),(2,'K','X','m','1710',NULL),(3,'K2','X','m','1745',NULL);" + F_ + "(1,NULL,1,NULL);" + K_ + "(1,2,1),(1,3,2)", {2}),
    "014": (P_ + "(1,'V','X','m','1720',NULL),(2,'K','X','m','1710',NULL);" + F_ + "(1,1,NULL,NULL);" + K_ + "(1,2,1)", {2}),
    "015": (P_ + "(1,'M','X','w','1700','3.3. 1730'),(2,'K','X','m','1.1. 1731',NULL),(3,'K2','X','m','1733',NULL),(4,'K3','X','m','2.2. 1730',NULL);" + F_ + "(1,NULL,1,NULL);" + K_ + "(1,2,1),(1,3,2),(1,4,3)", {2, 3}),
    "016": (P_ + "(1,'V','X','m','1700','3.3. 1730'),(2,'K','X','m','1.1. 1731',NULL),(3,'P','X','m','1.12. 1730',NULL),(4,'K3','X','m','1733',NULL);" + F_ + "(1,1,NULL,NULL);" + K_ + "(1,2,1),(1,3,2),(1,4,3)", {2, 4}),
    "017": (P_ + "(1,'V','X','m',NULL,NULL),(2,'M','Y','w',NULL,NULL),(3,'K','X','m','1700',NULL),(4,'K2','X','m','1705',NULL);" + F_ + "(1,1,2,'1704');" + K_ + "(1,3,1),(1,4,2)", {3}),
    "018": (P_ + "(1,'A','X','m','31.4. 1700',NULL),(2,'B','X','m','29.2. 1700',NULL),(3,'C','X','m','29.2. 1704',NULL),(4,'D','X','m','30.2. 1704','5.13. 1750'),(5,'E','X','m','30.4. 1700',NULL)", 4),
    "019": (P_ + "(1,'A','X','m','18.4. 2013',NULL),(2,'B','X','m','18.4. 2113',NULL)", {2}),
    "110": (P_ + "(1,'A','X','m','1600','1720'),(2,'B','X','m','1600','1700')", {1}),
    "111": (P_ + "(1,'M','X','w','1700',NULL),(2,'K','X','m','1712',NULL),(3,'K2','X','m','1716',NULL);" + F_ + "(1,NULL,1,NULL);" + K_ + "(1,2,1),(1,3,2)", {2}),
    "112": (P_ + "(1,'M','X','w','1700',NULL),(2,'K','X','m','1757',NULL),(3,'K2','X','m','1750',NULL);" + F_ + "(1,NULL,1,NULL);" + K_ + "(1,2,1),(1,3,2)", {2}),
    "113": (P_ + "(1,'V','X','m','1700',NULL),(2,'K','X','m','1712',NULL);" + F_ + "(1,1,NULL,NULL);" + K_ + "(1,2,1)", {2}),
    "114": (P_ + "(1,'V','X','m','1700',NULL),(2,'K','X','m','1780',NULL);" + F_ + "(1,1,NULL,NULL);" + K_ + "(1,2,1)", {2}),
    "115": (P_ + "(1,'A','X','w','1700',NULL),(2,'B','Y','m','1680',NULL);" + F_ + "(1,2,1,'1712')", {1}),
    "116": (P_ + "(1,'A','X','w','1600',NULL),(2,'B','Y','m','1680',NULL);" + F_ + "(1,2,1,'1700')", {1}),
    "117": (P_ + "(1,'A','X','m','1600',NULL),(2,'B','Y','w','1650',NULL);" + F_ + "(1,1,2,NULL)", {1}),
    "118": (P_ + "(1,'A','X','m','1.1. 1700',NULL),(2,'B','X','m','1.5. 1700',NULL),(3,'Z','X','m','1.1. 1700',NULL),(4,'C','X','m','1.6. 1701',NULL);" + F_ + "(1,NULL,NULL,NULL);" + K_ + "(1,1,1),(1,2,2),(1,3,3),(1,4,4)", 2),
    "227": (P_ + "(1,'A','X','m',NULL,NULL),(2,'B','X','m',NULL,NULL)", 0),
    "226": (P_ + "(1,'V','X','m',NULL,NULL),(2,'M','X','w',NULL,NULL);" + F_ + "(1,1,2,'1700'),(2,1,2,'1700'),(3,1,2,NULL)", 2),
    "125": (P_ + "(1,'A','X','m','1.1. 1700','1.1. 1750'),(2,'B','Y','w','1.1. 1705',NULL);" + F_ + "(1,1,2,'1.1. 1760')", {1}),
    "124": (P_ + "(1,'A','X','m','1700',NULL),(2,'B','X','m','1715',NULL),(3,'C','X','m','1716',NULL);" + F_ + "(1,NULL,NULL,NULL);" + K_ + "(1,1,1),(1,2,2),(1,3,3)", 1),
    "119": (P_ + "(1,'A','X','m','1700',NULL),(2,'B','X','m','1740',NULL);" + F_ + "(1,NULL,NULL,NULL);" + K_ + "(1,1,1),(1,2,2)", 1),
    "120": (F_ + "(1,NULL,NULL,NULL);" + K_ + ",".join(f"(1,{i},{i})" for i in range(1, 23)), 1),
    "121": (P_ + "(1,'A','X','m',NULL,NULL);" + F_ + ",".join(f"({i},1,NULL,NULL)" for i in range(1, 8)), {1}),
    "123": (P_ + "(1,'M','X','w',NULL,NULL),(2,'M2','X','w',NULL,NULL);" + F_ + "(1,NULL,1,NULL),(2,NULL,1,NULL),(3,NULL,2,NULL);" + K_
            + ",".join(f"(1,{i},{i})" for i in range(10, 21)) + "," + ",".join(f"(2,{i},{i})" for i in range(30, 40)) + "," + ",".join(f"(3,{i},{i})" for i in range(50, 65)), {1}),
    "122": (P_ + "(1,'A','X','m',NULL,NULL),(2,'B','Y','w',NULL,'1.1. 1700'),(3,'C','Z','w',NULL,NULL);" + F_ + "(1,1,2,'1690'),(2,1,3,'1.2. 1700')", {1}),
    "210": (P_ + "(1,'','NN','u',NULL,NULL),(2,'','','u',NULL,NULL),(3,'Hans','NN','m',NULL,NULL),(4,'','NN','u',NULL,NULL);" + F_ + "(1,4,NULL,NULL)", {1, 2}),
    "211": (P_ + "(1,'A','X','m',NULL,NULL),(2,'B','X','m',NULL,NULL);" + F_ + "(1,2,NULL,NULL)", {1}),
    "212": (P_ + "(1,'A','X','m',NULL,NULL),(2,'','NN','u',NULL,NULL);" + F_ + "(1,1,2,NULL)", {2}),
    "213": (P_ + "(1,'K','X','m',NULL,NULL);" + F_ + "(1,NULL,NULL,NULL),(2,NULL,NULL,NULL);" + K_ + "(1,1,1),(2,1,1)", {1}),
    "214": (P_ + "(1,'K','X','m',NULL,NULL);" + F_ + "(1,1,NULL,NULL);" + K_ + "(1,1,1)", {1}),
    "215": (P_ + "(1,'A','X','w',NULL,NULL),(2,'B','Y','w',NULL,NULL),(3,'C','Z','m',NULL,NULL);" + F_ + "(1,1,2,NULL),(2,3,2,NULL)", {1}),
    "216": (P_ + "(1,'A','X','w',NULL,NULL),(2,'B','Y','m',NULL,NULL);" + F_ + "(1,1,2,NULL)", {1, 2}),
    "217": (F_ + "(1,NULL,NULL,NULL),(2,NULL,NULL,'1700');" + P_ + "(1,'A','X','m',NULL,NULL);" + F_ + "(3,1,NULL,NULL)", 2),
    "218": (P_ + "(1,'A','X','m',NULL,NULL);" + F_ + "(1,1,99,NULL)", 1),
    "219": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch,geburt_iso,artikel_id,rolle,eigenes_artikel_id) VALUES "
            "(1,'Johann Georg','Schuler','19.9. 1742',10,'kopf',NULL),(2,'Johann Georg','Schuler','19.9. 1742',11,'kind',10),"
            "(3,'Johann Georg','Schuler','19.9. 1742',12,'kind',NULL),(4,'Johann Georg','Schuler','1742',13,'kopf',NULL)", 2),
    "220": (P_ + "(1,'A','X','m',NULL,NULL),(2,'B','X','w',NULL,NULL),(3,'C','Y','w',NULL,NULL);" + F_ + "(1,NULL,NULL,NULL),(2,1,2,NULL),(3,1,3,NULL);" + K_ + "(1,1,1),(1,2,2)", {1}),
    "221": (P_ + "(1,'V','X','m',NULL,NULL),(2,'T','X','w',NULL,NULL);" + F_ + "(1,1,NULL,NULL),(2,1,2,NULL);" + K_ + "(1,2,1)", {1}),
    "222": (P_ + "(1,'A','X','m',NULL,NULL),(2,'B','Y','w',NULL,'1720'),(3,'C','Z','w',NULL,NULL),(4,'D','W','w',NULL,'1705');" + F_ + "(1,1,2,'1700'),(2,1,3,'1710'),(3,1,4,'1730')", {1}),
    "223": (P_ + "(1,'A','Maier','m',NULL,NULL),(2,'B','Maier','w',NULL,NULL),(3,'C','NN','w',NULL,NULL);" + F_ + "(1,1,2,NULL)", {1}),
    "224": (P_ + "(1,'Hans','X','m','1700','1701'),(2,'Hans','X','m','1702',NULL),(3,'Georg','X','m','1704',NULL),(4,'Georg','X','m','1706',NULL);" + F_ + "(1,NULL,NULL,NULL);" + K_ + "(1,1,1),(1,2,2),(1,3,3),(1,4,4)", {4}),
    "225": (P_ + "(1,'A','X','m',NULL,NULL),(2,'B','X','m',NULL,NULL);" + F_ + "(1,1,NULL,NULL),(2,2,NULL,NULL);" + K_ + "(1,2,1),(2,1,1)", 2),
    "310": (P_ + "(1,'Maria','Walburga','w',NULL,NULL),(2,'Conrad','Walburga','m',NULL,NULL),(3,'Maria','Beringer','w',NULL,NULL)", {1, 2}),
    "311": (P_ + "(1,'Keine','Angaben','u',NULL,NULL),(2,'keine Angabe 1627 Margaretha','','w',NULL,NULL),(3,'Anna Maria','Kindermann','w',NULL,NULL)", {1, 2}),
    "312": (P_ + "(1,'Tübingen Friederike Beate','Rieger','w',NULL,NULL),(2,'Friederike Beate','Rieger','w',NULL,NULL),(3,'Johannes Vogel zu Plüderhausen','','m',NULL,NULL)", {1, 3}),
    "313": (P_ + "(1,'Johannes','DelingerBeck','m',NULL,NULL),(2,'Johannes','Delinger','m',NULL,NULL),(3,'PhilippJacob','Joos','m',NULL,NULL)", {1, 3}),
    "314": (P_ + "(1,'Margaretha','Karch Karg Kuth','w',NULL,NULL),(2,'Hans','von Berg','m',NULL,NULL),(3,'Hans','Berg','m',NULL,NULL),(4,'Hans','Karch, Karg','m',NULL,NULL)", {1, 4}),
    "315": (P_ + "(1,'keine Angabe 1627 Margaretha','','w',NULL,NULL),(2,'Anna','Berg','w',NULL,NULL),(3,'Anna * 12.3.','Berg','w',NULL,NULL)", {1, 3}),
    "316": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch,beruf) VALUES (1,'A','X','Hans Müller'),(2,'B','X','Müller'),(3,'C','X','Johann Georgs Knecht')", {1, 3}),
    "317": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch,notiz) VALUES (1,'A','X','Prüfhinweis: Datum unsicher'),(2,'B','X','Hinweis: Sie ist die Frau des ...'),(3,'C','X','Beim Einlesen ihm zugeordnet')", {1, 3}),
    "318": (P_ + "(1,'A','Maier zu Urbach','m',NULL,NULL),(2,'B','Maier','m',NULL,NULL)", {1}),
    "319": (P_ + "(1,'A','X','u',NULL,NULL),(2,'B','Y','w',NULL,NULL);" + F_ + "(1,1,2,NULL)", {1}),
    "320": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch) VALUES (1,'Barbara (Patin','X'),(2,'Anna Maria','X'),(3,'kein Name','X')", {1, 3}),
    "322": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch,rolle) VALUES (1,'Hans','Kapf','kopf'),(2,'Anna','Kapf','partner'),(3,'Köstlin in','Eßlingen','partner'),(4,'Maria','Maier','partner')", {3}),
    "323": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch) VALUES (1,'Hans','Maier'),(2,'Catharina','Walburga'),(3,'Anna','Ulm')", {2, 3}),
    "321": ("INSERT INTO ofb_individuum(id,vn_kanonisch,fn_kanonisch) VALUES (1,'Anna (Maria) Barbara','X'),(2,'Christina Kassel (früher Beischlaf)','X'),(3,'Johannes (Urbach)','X'),(4,'Barbara Breyn Breinin)','X')", {2, 3, 4}),
    "410": ("INSERT INTO blank_artikel(id, roh_text) VALUES (1, 'Maier Simon' || char(10) || '* 3.1. 1705, + 15.5. 1787 (82 J 7 M)' || char(10) || 'Maier Anna' || char(10) || '* 3.1. 1705, + 16.5. 1787 (81 J 2 M 10 T)');"
            "INSERT INTO ofb_individuum(id,artikel_id,vn_kanonisch,fn_kanonisch,geburt_iso,tod_iso) VALUES (1,1,'Simon','Maier','3.1. 1706','15.5. 1787'),(2,1,'Anna','Maier','3.1. 1706','16.5. 1787')", {1}),
    "411": ("CREATE TABLE ofb_person_kanon (id INTEGER PRIMARY KEY, kanon_id INTEGER, quelle TEXT);"
            + P_ + "(1,'A','X','m','1.1. 1700','8.12. 1727'),(2,'A','X','m','1.1. 1700','28.12. 1727'),"
                   "(3,'B','Y','w','2.2. 1710','1.1. 1750'),(4,'B','Y','w','2.2. 1710','1.1. 1750');"
            + "INSERT INTO ofb_person_kanon VALUES (2,1,'trauung:3.5. 1725'),(4,3,'geburt:2.2. 1710')", {1}),
}


def selbsttest(regeldatei=REGELDATEI):
    import tempfile
    global _ATLAS_VN
    _ATLAS_VN = ({"Patin", "Name"}, {"Anna", "Maria", "Barbara"})
    global _ATLAS_ORTE, _ATLAS_NN
    _ATLAS_ORTE = {"Kapf", "Eßlingen"}
    _ATLAS_NN = ({"Walburga", "Ulm"}, {"Maier"})
    regeln = {r["id"]: r for r in lies_regeln(regeldatei)}
    ok = fehl = 0
    for rid, (sql, soll) in sorted(SELBSTTEST_FAELLE.items()):
        r = regeln.get(rid)
        fn = globals().get(f"regel_{rid}")
        if fn is None:
            print(f"  ?? {rid}: keine Funktion")
            fehl += 1
            continue
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            pfad = tf.name
        con = sqlite3.connect(pfad)
        con.executescript(SCHEMA_MIN + sql + ";")
        con.commit()
        con.close()
        m = lies_sqlite(pfad)
        os.unlink(pfad)
        rows = fn(m, r["gw"] if r else None)
        if isinstance(soll, set):
            ist = {row[0] for row in rows if row[0] is not None}
            gut = ist == soll
        else:
            ist = len(rows)
            gut = ist == soll
        if gut:
            ok += 1
        else:
            fehl += 1
            print(f"  FEHL {rid}: erwartet {soll}, bekommen {ist}")
            for row in rows:
                print(f"        {row}")
    ohne = sorted(rid for rid in regeln if rid not in SELBSTTEST_FAELLE)
    print(f"Selbsttest: {ok} ok, {fehl} fehlgeschlagen" + (f"; Regeln ohne Fall: {', '.join(ohne)}" if ohne else ""))
    return fehl


def main(argv):
    if "--selbsttest" in argv:
        return 1 if selbsttest() else 0
    if "--katalog" in argv:
        katalog()
        return 0
    args = [a for a in argv if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    nur = argv[argv.index("--nur") + 1] if "--nur" in argv else None
    zeigen = int(argv[argv.index("--zeigen") + 1]) if "--zeigen" in argv else 0
    tsv = argv[argv.index("--tsv") + 1] if "--tsv" in argv else None
    messreihe = argv[argv.index("--messreihe") + 1] if "--messreihe" in argv else None
    kommentar = argv[argv.index("--kommentar") + 1] if "--kommentar" in argv else ""
    fehler = lauf(args[0], nur=nur, zeigen=zeigen, trocken="--trocken" in argv, tsv=tsv,
                  messreihe=messreihe, kommentar=kommentar)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
