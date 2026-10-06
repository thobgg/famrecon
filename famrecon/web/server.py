"""Die Oberflaeche: ein lokaler Server aus der Standardbibliothek, Seiten als HTML-Dateien.

    famrecon start [--port 8765] [--daten daten]    -> http://127.0.0.1:8765

Ein Projekt ist ein Ordner unter daten/: hochgeladene Tabellen, zuordnung.toml,
projekt.db, projekt.ged. Jede Seite ruft dieselben Module wie die Kommandozeile;
die Oberflaeche entscheidet nichts selbst. Entscheidungen aus der Pruefliste
landen in der Tabelle `entscheidung` und gelten beim naechsten Verknuepfen.
"""
import html
import json
import os
import re
import shutil
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template

from .. import __version__, db, gedcom, katalog, kern, lesen, messen, pruefe, verknuepfen, zuordnung
from ..i18n import _, SPRACHE

HIER = Path(__file__).parent
STATIC, VORLAGEN, HILFE = HIER / "static", HIER / "vorlagen", HIER / "hilfe"
h = html.escape


def wurzel():
    """Wo die Daten liegen: neben der Einzeldatei (Paket), im Quelltext das Arbeitsverzeichnis.

    Liegt das Paket an einem Systemort (/usr/bin aus der .deb, im Mac-Programmpaket .app,
    "Program Files") oder ist der Ordner nicht beschreibbar, dann der Datenordner des Benutzers:
    ~/.local/share/famrecon, ~/Library/Application Support/famrecon, %APPDATA%\\famrecon."""
    if not getattr(sys, "frozen", False):
        return Path.cwd()
    ordner = Path(sys.executable).parent
    systemort = (".app/Contents/" in sys.executable or str(ordner).startswith(("/usr", "/opt", "/bin", "/snap"))
                 or "Program Files" in str(ordner) or "WindowsApps" in str(ordner))
    if not systemort and os.access(ordner, os.W_OK):
        return ordner
    if sys.platform == "win32":
        basis = Path(os.environ.get("APPDATA") or Path.home())
    elif sys.platform == "darwin":
        basis = Path.home() / "Library" / "Application Support"
    else:
        basis = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return basis / "famrecon"


def beispiele_ordner():
    """Die mitgelieferten Beispiele: im Paket entpackt (_MEIPASS), sonst neben dem Code."""
    basis = Path(getattr(sys, "_MEIPASS", HIER.parent.parent))
    return basis / "beispiel"


DATEN = wurzel() / "daten"


def seite(name, **werte):
    kopf = (VORLAGEN / "rahmen.html").read_text(encoding="utf-8")
    roh = (VORLAGEN / f"{name}.html").read_text(encoding="utf-8")
    werte.setdefault("hilfe", f'<a class="hilfe-link" href="/hilfe#{name}">{_("Mehr in der Hilfe")} →</a>')
    inhalt = Template(re.sub(r"\{\{(.+?)\}\}", lambda m: _(m.group(1)), roh)).safe_substitute(**werte)
    kopf = re.sub(r"\{\{(.+?)\}\}", lambda m: _(m.group(1)), kopf)
    pr = werte.get("projekt", "")
    nav = "".join(f'<a href="/p/{pr}/{w}">{t}</a>' for w, t in (("", pr), ("zuordnung", _("Zuordnung")), ("personen", _("Personen")), ("familien", _("Familien")), ("pruefliste", _("Prüfliste")), ("gedcom", "GEDCOM"))) if pr else ""
    return Template(kopf).safe_substitute(inhalt=inhalt, titel=werte.get("titel", "famrecon"), projekt_nav=nav, hilfe_ziel=f"/hilfe#{name}")


def projekte():
    return sorted(p.name for p in DATEN.iterdir() if p.is_dir() and not p.name.startswith(".")) if DATEN.exists() else []


class Projekt:
    def __init__(self, name):
        if not re.fullmatch(r"[\w\-]+", name):
            raise ValueError(name)
        self.name, self.ordner = name, DATEN / name
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.toml, self.dbpfad, self.ged = self.ordner / "zuordnung.toml", self.ordner / "projekt.db", self.ordner / "projekt.ged"

    def tabellen(self):
        return sorted(p for p in self.ordner.iterdir() if p.suffix.lower() in (".xlsx", ".xlsm", ".csv", ".tsv"))

    def con(self):
        """Verbindung fuer eine Anfrage; schliessen() macht sie zu. Unter Windows blockiert eine
        offene Verbindung das Loeschen und Ersetzen der Datei."""
        c = db.oeffnen(self.dbpfad)
        self._cons = getattr(self, "_cons", []) + [c]
        return c

    def schliessen(self):
        for c in getattr(self, "_cons", []):
            try:
                c.close()
            except Exception:
                pass
        self._cons = []

    def stand(self):
        st = dict(tabellen=[t.name for t in self.tabellen()], zuordnung=self.toml.exists(), db=self.dbpfad.exists(),
                  ged=self.ged.exists(), eintraege={}, personen=0, identitaeten=0, familien=0, stufen={}, offen=0)
        if st["db"]:
            con = self.con()
            st["eintraege"] = dict(con.execute("SELECT register, COUNT(*) FROM eintrag GROUP BY register"))
            st["personen"] = con.execute("SELECT COUNT(*) FROM person").fetchone()[0]
            st["identitaeten"] = con.execute("SELECT COUNT(*) FROM identitaet").fetchone()[0]
            st["familien"] = con.execute("SELECT COUNT(*) FROM familie").fetchone()[0]
            st["stufen"] = dict(con.execute("SELECT stufe, COUNT(*) FROM zuordnung GROUP BY stufe"))
            st["offen"] = con.execute("SELECT COUNT(*) FROM zuordnung z WHERE z.stufe='unsicher' AND z.person NOT IN (SELECT person FROM entscheidung)").fetchone()[0]
        return st


# ------------------------------------------------------------------ Seiten
def s_start(meldung=""):
    zeilen = "".join(f'<li><a href="/p/{h(n)}">{h(n)}</a></li>' for n in projekte()) or "<li>" + _("noch keines") + "</li>"
    return seite("start", projekte=zeilen, meldung=h(meldung), daten=h(str(DATEN.resolve())))


BEISPIELE = {   # erfundener Stammbaum (CC0); echte Daten einzelner Autoren gehoeren nicht ins Programm
    "beispiel-falkenrath": (["falkenrath-taufen.csv", "falkenrath-ehen.csv", "falkenrath-tote.csv"], None),
}


def beispiele_anlegen():
    """Die mitgelieferten Beispiele als Projekte anlegen und bauen."""
    q = beispiele_ordner()
    for name, (dateien, toml) in BEISPIELE.items():
        pr = Projekt(name)
        for d in dateien:
            shutil.copy(q / d, pr.ordner / d)
        if toml:
            shutil.copy(q / toml, pr.toml)
        else:
            blaetter = [b for d in dateien for b in zuordnung.vorschlagen(pr.ordner / d)]
            pr.toml.write_text(zuordnung.toml_text(", ".join(dateien), blaetter, mit_datei=True), encoding="utf-8")
        con = pr.con()
        lesen.einlesen(con, lesen.zuordnung_laden(pr.toml), pr.tabellen())
        kern.personen_bauen(con)
        verknuepfen.verknuepfen(con)
        pr.schliessen()


def s_projekt(pr, meldung=""):
    st = pr.stand()
    schritte = []
    schritte.append((_("Tabellen"), ", ".join(st["tabellen"]) or _("keine hochgeladen"), bool(st["tabellen"])))
    schritte.append((_("Zuordnung"), _("liegt vor") if st["zuordnung"] else _("fehlt"), st["zuordnung"]))
    schritte.append((_("Projektdatei"), ", ".join(f"{k} {v}" for k, v in st["eintraege"].items()) + f"; {st['personen']} " + _("Personen") if st["db"] else _("fehlt"), st["db"]))
    schritte.append((_("Verknüpfung"), f"{st['identitaeten']} " + _("Personen") + f", {st['familien']} " + _("Familien") + "; " + ", ".join(f"{k} {v}" for k, v in st["stufen"].items()) if st["identitaeten"] else _("fehlt"), bool(st["identitaeten"])))
    schritte.append((_("Prüfliste"), f"{st['offen']} " + _("offen") if st["identitaeten"] else "–", st["identitaeten"] and not st["offen"]))
    schritte.append(("GEDCOM", _("liegt vor") if st["ged"] else _("fehlt"), st["ged"]))
    liste = "".join(f'<tr class="{"ok" if ok else ""}"><th>{h(t)}</th><td>{h(w)}</td></tr>' for t, w, ok in schritte)
    return seite("projekt", projekt=pr.name, titel=pr.name, schritte=liste, meldung=h(meldung),
                 ged_link=f'<a class="knopf" href="/p/{pr.name}/projekt.ged" download>" + _("GEDCOM herunterladen") + "</a>' if st["ged"] else "")


def s_zuordnung(pr, wahl=None):
    """wahl: {"r0": "tod", ...} aus der Adresse, wenn der Nutzer ein Register umgeschaltet hat."""
    wahl = wahl or {}
    blaetter = []
    for t in pr.tabellen():
        blaetter += [(b, r, zu, lw, t.name) for b, r, zu, lw, *_rest in zuordnung.vorschlagen(t)]
    vorhanden = {}
    if pr.toml.exists():
        try:
            z = lesen.zuordnung_laden(pr.toml)
            for reg, d in z["register"].items():
                vorhanden[(d.get("datei"), d["blatt"])] = (reg, {k: v for k, v in d["spalten"].items()})
        except Exception:
            pass
    bloecke = []
    for n, (blatt, reg, zu, lw, datei) in enumerate(blaetter):
        alt = vorhanden.get((datei, blatt)) or vorhanden.get((None, blatt))
        reg = wahl.get(f"r{n}") or (alt[0] if alt else reg)
        if wahl.get(f"r{n}"):                                  # umgeschaltet: Vorschlag fuer das neue Register
            kopf = [(b, s["titel"]) for b, s in zu if "-" not in b]
            zeilen = [r for _nr, r in lesen.zeilen_lesen(pr.ordner / datei, blatt)][:200]
            zu = zuordnung.blatt_zuordnen(blatt, kopf, zeilen, reg)
            alt = None
        felder = katalog.felder(reg)
        zeilen = []
        for b, s in zu:
            gewaehlt = (alt[1].get(b) if alt else None) or s["feld"] or ""
            opts = ['<option value="">– ' + _("nicht übernehmen") + ' –</option>']
            for name, (rang, art, hilfe, _syn) in felder.items():
                opts.append(f'<option value="{name}" {"selected" if name == gewaehlt else ""}>{name} · {h(hilfe)}</option>')
                if name + "_kb" == gewaehlt:
                    opts.append(f'<option value="{name}_kb" selected>{name}_kb · {_("Kirchenbuchform")}</option>')
            bsp = "".join(f"<div>{h(x)}</div>" for x in s["werte"]) or "<i>" + _("leer") + "</i>"
            zeilen.append(f'<tr><td class="sp">{h(b)}</td><td>{h(s["titel"].strip())}</td><td class="bsp">{bsp}</td>'
                          f'<td><select name="f{n}:{h(b)}">{"".join(opts)}</select></td><td class="{s["stufe"] or ""}">{s["stufe"] or ""}</td></tr>')
        regopts = "".join(f'<option value="{r}" {"selected" if r == reg else ""}>{_(r)}</option>' for r in ("taufe", "ehe", "tod"))
        bloecke.append(f'<h2>{h(datei)} · Blatt „{h(blatt)}“ <select name="r{n}" onchange="umschalten(this)" title="{_("Register umschalten: die Feldliste wird neu geladen")}">{regopts}</select>'
                       f'<input type="hidden" name="d{n}" value="{h(datei)}"><input type="hidden" name="b{n}" value="{h(blatt)}"></h2>'
                       f'<table class="zu"><tr class="gruppe"><th colspan="3">{_("Deine Tabelle")}</th><th colspan="2">{_("Feld in famrecon")}</th></tr>'
                       f'<tr><th>Sp.</th><th>{_("Überschrift")}</th><th>{_("Beispiele")}</th><th>{_("Feld")}</th><th>{_("Vorschlag")}</th></tr>{"".join(zeilen)}</table>')
    leer = sorted({w for *_rest, lw, _datei in blaetter for w in lw})
    bilanz = []
    for blatt, reg, zu, lw, datei in blaetter:
        n_s = sum(1 for _b, x in zu if x["stufe"] == "sicher"); n_w = sum(1 for _b, x in zu if x["stufe"] == "wahrscheinlich")
        n_u = sum(1 for _b, x in zu if x["stufe"] == "unsicher"); n_0 = sum(1 for _b, x in zu if not x["feld"] and x["n"])
        bilanz.append(f"<b>{h(blatt)}</b> ({_(reg)}): " + _("{s} sicher, {w} wahrscheinlich, {u} unsicher, {n} nicht erkannt").format(s=n_s, w=n_w, u=n_u, n=n_0))
    return seite("zuordnung", projekt=pr.name, titel=_("Zuordnung"), bloecke="".join(bloecke), anzahl=len(blaetter), leer=h(", ".join(leer)),
                 bilanz=" · ".join(bilanz))


def zuordnung_speichern(pr, form):
    n, z = 0, ["# Spaltenzuordnung, in der Oberflaeche bestaetigt", "", "[allgemein]",
               "leer = [" + ", ".join(f'"{w.strip()}"' for w in form.get("leer", "").split(",") if w.strip()) + "]"]
    while f"r{n}" in form:
        reg, datei, blatt = form[f"r{n}"], form[f"d{n}"], form[f"b{n}"]
        z += ["", f"[register.{reg}]", f'blatt = "{blatt}"', f'datei = "{datei}"',
              "leitdatum = [" + ", ".join(f'"{f}"' for f in katalog.LEITDATUM[reg]) + "]", "", f"[register.{reg}.spalten]"]
        for k, v in form.items():
            if k.startswith(f"f{n}:") and v:
                sp = k.split(":", 1)[1]
                z.append(f'{sp if "-" not in sp else chr(34) + sp + chr(34)} = "{v}"')
        n += 1
    pr.toml.write_text("\n".join(z) + "\n", encoding="utf-8")


def s_personen(pr, q, register):
    con = pr.con()
    sql = ("SELECT e.register, e.jahr, p.id, p.pfad, p.name, p.vorname, p.geschlecht, p.beruf, p.stand, p.unsicher, p.unbekannt, p.totgeburt, p.verstorben, "
           "p.geburt_jahr, p.geburt_praefix, p.roh, z.ident, z.stufe FROM person p JOIN eintrag e ON e.id=p.eintrag LEFT JOIN zuordnung z ON z.person=p.id WHERE 1=1")
    par = []
    if register:
        sql += " AND e.register=?"; par.append(register)
    if q:
        sql += " AND (p.name LIKE ? OR p.vorname LIKE ? OR p.roh LIKE ?)"; par += [f"%{q}%"] * 3
    sql += " ORDER BY e.jahr, e.id, p.id LIMIT 500"
    zeilen = []
    for r in con.execute(sql, par):
        marker = " ".join(m for m, f in (("†", r["verstorben"]), ("?", r["unsicher"]), ("NN", r["unbekannt"]), ("Totgeburt", r["totgeburt"])) if f)
        geb = f"*{r['geburt_praefix'] or ''}{r['geburt_jahr']}" if r["geburt_jahr"] else ""
        ident = f'<a href="/p/{pr.name}/familien#i{r["ident"]}">[{r["ident"]}]</a>' if r["ident"] else ""
        zeilen.append(f'<tr><td>{r["register"]}</td><td>{r["jahr"] or ""}</td><td>{r["pfad"]}</td><td>{h(r["name"] or "–")}</td><td>{h(r["vorname"] or "–")}</td>'
                      f'<td>{r["geschlecht"] or ""}</td><td>{marker}</td><td>{geb}</td><td>{h(r["stand"] or "")}</td><td>{h(r["beruf"] or "")}</td><td>{ident} {r["stufe"] or ""}</td></tr>')
    return seite("personen", projekt=pr.name, titel=_("Personen"), zeilen="".join(zeilen), q=h(q), register=register or "",
                 anzahl=len(zeilen))


def s_familien(pr, q):
    con = pr.con()

    def wer(i):
        if not i:
            return "—"
        r = con.execute("SELECT * FROM identitaet WHERE id=?", (i,)).fetchone()
        geb = f" *{r['geb_praefix'] or ''}{r['geb_jahr']}" if r["geb_jahr"] else ""
        tod = f" †{r['tod_jahr']}" if r["tod_jahr"] else ""
        name = r["name"] or ("NN" if r["unbekannt"] else "—")
        if r["ehename"]:
            name += f" (verh. {r['ehename']})"
        return f'<span id="i{r["id"]}">{h(name)}, {h(r["vorname"] or "—")}{geb}{tod} <small>[{r["id"]}]</small></span>'
    sql = "SELECT f.* FROM familie f"
    par = []
    if q:
        sql += (" WHERE f.mann IN (SELECT id FROM identitaet WHERE name LIKE ? OR vorname LIKE ?) OR f.frau IN (SELECT id FROM identitaet WHERE name LIKE ? OR vorname LIKE ?)"
                " OR f.id IN (SELECT familie FROM kind k JOIN identitaet i ON i.id=k.ident WHERE i.name LIKE ? OR i.vorname LIKE ?)")
        par = [f"%{q}%"] * 6
    sql += " ORDER BY COALESCE(tr_jahr, (SELECT MIN(geb_jahr) FROM kind k JOIN identitaet i ON i.id=k.ident WHERE k.familie=f.id), 9999), f.id LIMIT 300"
    bloecke = []
    for f in con.execute(sql, par):
        tr = f" ⚭ {f['tr_jahr']}" if f["tr_jahr"] else " (" + _("Ehe erschlossen") + ")" if f["art"] == "eltern" else ""
        kinder = "".join(f"<li>{wer(k['ident'])}</li>" for k in con.execute("SELECT k.ident FROM kind k JOIN identitaet i ON i.id=k.ident WHERE k.familie=? ORDER BY i.geb_jahr", (f["id"],)))
        bloecke.append(f'<div class="fam"><b>F{f["id"]}</b>{tr}: {wer(f["mann"])} &amp; {wer(f["frau"])}<ul>{kinder}</ul></div>')
    return seite("familien", projekt=pr.name, titel=_("Familien"), bloecke="".join(bloecke), q=h(q), anzahl=len(bloecke))


def s_pruefliste(pr, alle=False):
    con = pr.con()
    sql = ("SELECT z.*, p.pfad, p.roh, e.register, e.jahr, i.name iname, i.vorname ivorname, i.geb_jahr, i.tod_jahr, i.id iid, en.art hart, en.ziel hziel "
           "FROM zuordnung z JOIN person p ON p.id=z.person JOIN eintrag e ON e.id=p.eintrag JOIN quelle q ON q.id=e.quelle JOIN identitaet i ON i.id=z.ident "
           "LEFT JOIN entscheidung en ON en.schluessel = q.datei||'|'||q.blatt||'|'||e.zeile||'|'||p.pfad "
           "WHERE z.stufe IN ('unsicher'" + (",'wahrscheinlich'" if alle else "") + ") ORDER BY (en.art IS NOT NULL), e.jahr")

    def belege(ident):
        out = []
        for r in con.execute("SELECT e.register, e.jahr, p.pfad, p.roh, p.id FROM zuordnung z JOIN person p ON p.id=z.person JOIN eintrag e ON e.id=p.eintrag WHERE z.ident=? ORDER BY e.jahr", (ident,)):
            out.append(f'<li><small>{r["register"]} {r["jahr"]} · {r["pfad"]}</small> {h(r["roh"] or "")} <small>#{r["id"]}</small></li>')
        return "".join(out)
    bloecke = []
    for r in con.execute(sql):
        erledigt = f'<span class="hand">{_("von Hand")}: {r["hart"]}{(" = " + h(r["hziel"].split("|")[2] + " " + r["hziel"].split("|")[3])) if r["hziel"] else ""}</span>' if r["hart"] else ""
        kandidaten = [(r["iid"], r["punkte"], r["grund"])] + [tuple(a) for a in json.loads(r["alternativen"] or "[]")]
        karten = []
        for iid, punkte, grund in kandidaten:
            i = con.execute("SELECT name, vorname, geb_jahr, tod_jahr FROM identitaet WHERE id=?", (iid,)).fetchone()
            ziel = con.execute("SELECT person FROM zuordnung WHERE ident=? AND person<>? ORDER BY person LIMIT 1", (iid, r["person"])).fetchone()
            knopf = f'<button name="gleich" value="{ziel[0]}">{_("ist diese Person")}</button>' if ziel else ""
            karten.append(f'<div class="kand"><b>{h(i["name"] or "NN")}, {h(i["vorname"] or "–")}</b> *{i["geb_jahr"] or "?"} †{i["tod_jahr"] or "?"} <small>[{iid}] {punkte} Punkte ({h(grund)})</small>'
                          f'<ul>{belege(iid)}</ul>{knopf}</div>')
        bloecke.append(f'<form method="post" action="/p/{pr.name}/entscheidung" class="fall"><input type="hidden" name="person" value="{r["person"]}">'
                       f'<h3>{r["register"]} {r["jahr"]} · {r["pfad"]}: {h(r["roh"] or "")} <small>#{r["person"]} · {r["stufe"]}</small> {erledigt}</h3>'
                       f'<div class="kandidaten">{"".join(karten)}</div>'
                       f'<p><button name="neu" value="1">{_("eigene Person (keiner davon)")}</button> <button name="loeschen" value="1" class="leise">{_("Entscheidung zurücknehmen")}</button></p></form>')
    return seite("pruefliste", projekt=pr.name, titel=_("Prüfliste"), bloecke="".join(bloecke) or "<p>" + _("Keine offenen Fälle.") + "</p>", anzahl=len(bloecke),
                 alle_link=f'<a href="/p/{pr.name}/pruefliste?alle=1">" + _("auch „wahrscheinlich“ zeigen") + "</a>' if not alle else f'<a href="/p/{pr.name}/pruefliste">" + _("nur „unsicher“") + "</a>')


def s_gedcom(pr):
    con = pr.con()
    st = gedcom.schreiben(con, pr.ged)
    n, fehler = pruefe.pruefen(con, pr.ged)
    return seite("gedcom", projekt=pr.name, titel="GEDCOM", indi=st["indi"], fam=st["fam"], zeilen=st["zeilen"],
                 eintraege=", ".join(f"{k} {v}" for k, v in n.items()), fehler=len(fehler),
                 fehlerliste="".join(f"<li>{h(f)}</li>" for f in fehler[:50]))


def s_hilfe():
    """Die Hilfe: eine HTML-Datei je Sprache in web/hilfe/, Inhaltsverzeichnis aus den h2-Ueberschriften.
    Jede Seite verweist mit /hilfe#<seite> auf ihren Abschnitt."""
    datei = HILFE / f"{SPRACHE}.html"
    text = (datei if datei.exists() else HILFE / "de.html").read_text(encoding="utf-8")
    punkte = re.findall(r'<h2 id="([^"]+)">(.*?)</h2>', text)
    toc = "".join(f'<a href="#{i}">{re.sub("<[^>]+>", "", ueberschrift)}</a>' for i, ueberschrift in punkte)
    return seite("hilfe", titel=_("Hilfe"), text=text, toc=toc, version=__version__)


# ----------------------------------------------------------------- Server
def formular(body, ctype):
    """application/x-www-form-urlencoded oder multipart/form-data -> (felder, dateien[(name, bytes)])"""
    if ctype.startswith("multipart/form-data"):
        msg = BytesParser(policy=email_default).parsebytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + body)
        felder, dateien = {}, []
        for teil in msg.iter_parts():
            name = teil.get_param("name", header="content-disposition")
            dateiname = teil.get_filename()
            if dateiname:
                dateien.append((Path(dateiname).name, teil.get_payload(decode=True)))
            else:
                felder[name] = teil.get_payload(decode=True).decode("utf-8")
        return felder, dateien
    return {k: v[0] for k, v in urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True).items()}, []


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def antwort(self, text, typ="text/html; charset=utf-8", code=200):
        daten = text.encode("utf-8") if isinstance(text, str) else text
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)

    def weiter(self, ziel):
        self.send_response(303)
        self.send_header("Location", ziel)
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        teile = [t for t in url.path.split("/") if t]
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        pr = None
        try:
            if not teile:
                return self.antwort(s_start(q.get("m", "")))
            if teile == ["hilfe"]:
                return self.antwort(s_hilfe())
            if teile == ["ping"]:                              # fuer den zweiten Start: laeuft hier schon famrecon?
                return self.antwort(f"famrecon {__version__}", "text/plain; charset=utf-8")
            if teile[0] == "static" and len(teile) == 2:
                p = STATIC / teile[1]
                typ = {"css": "text/css", "js": "text/javascript", "svg": "image/svg+xml", "png": "image/png"}.get(p.suffix[1:], "application/octet-stream")
                return self.antwort(p.read_bytes(), typ) if p.exists() else self.antwort("fehlt", code=404)
            if teile[0] == "p" and len(teile) >= 2:
                pr = Projekt(teile[1])
                was = teile[2] if len(teile) > 2 else ""
                if was == "":
                    return self.antwort(s_projekt(pr, q.get("m", "")))
                if was == "zuordnung":
                    return self.antwort(s_zuordnung(pr, {k: v for k, v in q.items() if k.startswith("r") and k[1:].isdigit()}))
                if was in ("personen", "familien", "pruefliste", "gedcom") and not pr.dbpfad.exists():
                    return self.weiter(f"/p/{pr.name}?m=" + urllib.parse.quote(_("Zuerst bauen und verknüpfen.")))
                if was == "zuordnung" and not pr.tabellen():
                    return self.weiter(f"/p/{pr.name}?m=" + urllib.parse.quote(_("Zuerst Tabellen hochladen.")))
                if was == "personen":
                    return self.antwort(s_personen(pr, q.get("q", ""), q.get("register", "")))
                if was == "familien":
                    return self.antwort(s_familien(pr, q.get("q", "")))
                if was == "pruefliste":
                    return self.antwort(s_pruefliste(pr, bool(q.get("alle"))))
                if was == "gedcom":
                    return self.antwort(s_gedcom(pr))
                if was == "projekt.ged" and pr.ged.exists():
                    return self.antwort(pr.ged.read_bytes(), "text/plain; charset=utf-8")
            self.antwort("nicht gefunden", code=404)
        except Exception as e:                                 # die Seite soll den Fehler zeigen, nicht der Server sterben
            import traceback
            self.antwort(f"<pre>{h(traceback.format_exc())}</pre>", code=500)
        finally:
            if pr:
                pr.schliessen()

    def do_POST(self):
        laenge = int(self.headers.get("Content-Length", 0))
        form, dateien = formular(self.rfile.read(laenge), self.headers.get("Content-Type", ""))
        teile = [t for t in self.path.split("/") if t]
        pr = None
        try:
            if teile == ["beenden"]:
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return self.antwort(seite("beendet", titel=_("Beendet")))
            if teile == ["beispiele"]:
                beispiele_anlegen()
                return self.weiter("/?m=" + urllib.parse.quote(_("Beispielprojekt angelegt")))
            if teile == ["neu"]:
                pr = Projekt(form.get("name", "").strip() or "projekt")
                for name, inhalt in dateien:
                    (pr.ordner / name).write_bytes(inhalt)
                return self.weiter(f"/p/{pr.name}/zuordnung" if dateien else f"/p/{pr.name}")
            if teile[0] == "p" and len(teile) == 3:
                pr, was = Projekt(teile[1]), teile[2]
                if was == "hochladen":
                    for name, inhalt in dateien:
                        (pr.ordner / name).write_bytes(inhalt)
                    return self.weiter(f"/p/{pr.name}/zuordnung")
                if was == "zuordnung":
                    zuordnung_speichern(pr, form)
                    if form.get("bauen"):
                        self.path = f"/p/{pr.name}/bauen"
                        return self._bauen(pr)
                    return self.weiter(f"/p/{pr.name}?m=" + urllib.parse.quote(_("Zuordnung gespeichert")))
                if was == "verknuepfen":
                    if not pr.dbpfad.exists():
                        return self.weiter(f"/p/{pr.name}?m=" + urllib.parse.quote(_("Zuerst bauen und verknüpfen.")))
                    con = pr.con()
                    verknuepfen.verknuepfen(con)
                    return self.weiter(f"/p/{pr.name}/pruefliste")
                if was == "entscheidung":
                    con = pr.con()
                    person = int(form["person"])
                    if form.get("loeschen"):
                        verknuepfen.entscheiden_von_hand(con, person, None)
                    elif form.get("neu"):
                        verknuepfen.entscheiden_von_hand(con, person, "neu")
                    elif form.get("gleich"):
                        verknuepfen.entscheiden_von_hand(con, person, "gleich", int(form["gleich"]))
                    verknuepfen.verknuepfen(con)
                    return self.weiter(f"/p/{pr.name}/pruefliste")
                if was == "loeschen":
                    pr.schliessen()
                    shutil.rmtree(pr.ordner)
                    return self.weiter("/?m=" + urllib.parse.quote(_("Projekt gelöscht")))
                if was == "bauen":
                    return self._bauen(pr)
            self.antwort("nicht gefunden", code=404)
        except Exception:
            import traceback
            self.antwort(f"<pre>{h(traceback.format_exc())}</pre>", code=500)
        finally:
            if pr:
                pr.schliessen()

    def _bauen(self, pr):
        try:
            if not pr.tabellen():
                return self.weiter(f"/p/{pr.name}?m=" + urllib.parse.quote(_("Zuerst Tabellen hochladen.")))
            hinweis = ""
            if not pr.toml.exists():
                return self.weiter(f"/p/{pr.name}/zuordnung")
            con = pr.con()
            z = lesen.zuordnung_laden(pr.toml)
            lesen.einlesen(con, z, pr.tabellen())
            kern.personen_bauen(con)
            verknuepfen.verknuepfen(con)
            st = verknuepfen.statistik(con)
            return self.weiter(f"/p/{pr.name}?m=" + urllib.parse.quote(_("{p} Personen -> {i} Identitäten, {f} Familien").format(p=st["personen"], i=st["identitaeten"], f=st["familien"]) + hinweis))
        except Exception:
            import traceback
            self.antwort(f"<pre>{h(traceback.format_exc())}</pre>", code=500)


def app_fenster(url):
    """Eigenes Fenster ohne Adressleiste und Tabs: der App-Modus von Chrome, Chromium, Brave oder Edge.
    Gibt es keinen davon, oeffnet der normale Browser."""
    import os
    import subprocess
    kandidaten = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "brave",
                  "microsoft-edge", "microsoft-edge-stable", "msedge"]
    if sys.platform == "darwin":
        kandidaten += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium",
                       "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    if sys.platform.startswith("win"):
        for basis in (os.environ.get("ProgramFiles", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("LocalAppData", "")):
            kandidaten += [str(Path(basis) / "Google/Chrome/Application/chrome.exe"), str(Path(basis) / "Microsoft/Edge/Application/msedge.exe"),
                           str(Path(basis) / "BraveSoftware/Brave-Browser/Application/brave.exe")]
    for k in kandidaten:
        exe = shutil.which(k) or (k if Path(k).exists() else None)
        if exe:
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1240,860", f"--user-data-dir={DATEN / '.fenster'}"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except OSError:
                continue
    webbrowser.open(url)
    return False


def laeuft_schon(port):
    """Antwortet auf diesem Port bereits ein famrecon? Dann nur das Fenster oeffnen."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as r:
            return r.read().startswith(b"famrecon")
    except Exception:
        return False


def protokoll_umleiten(datei):
    """Ohne Konsole (Programmpaket per Doppelklick) landen Meldungen und Fehler in einer Datei."""
    if sys.stdout is None or sys.stderr is None or getattr(sys, "frozen", False) and not sys.stdout.isatty():
        f = open(datei, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = f
        print(f"\n--- {datetime.now().isoformat(timespec='seconds')} famrecon {__version__}")


def vorbereiten(port=8765, daten=None):
    """Datenordner anlegen, Protokoll umleiten, Server binden. -> (server, url) oder (None, url),
    wenn auf dem Port schon ein famrecon laeuft. Ist der Port anderweitig belegt, nimmt es einen freien."""
    global DATEN
    DATEN = Path(daten) if daten else wurzel() / "daten"
    DATEN.mkdir(parents=True, exist_ok=True)
    protokoll_umleiten(DATEN.parent / "famrecon.log" if DATEN.name == "daten" else DATEN / "famrecon.log")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError:
        if laeuft_schon(port):
            print(_("famrecon läuft bereits auf {url}, Fenster wird geöffnet").format(url=f"http://127.0.0.1:{port}/"))
            return None, f"http://127.0.0.1:{port}/"
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        print(_("Port {port} ist belegt, weiche auf {neu} aus").format(port=port, neu=server.server_address[1]))
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def start(port=8765, daten=None, browser=True):
    server, url = vorbereiten(port, daten)
    if server is None:
        if browser:
            app_fenster(url)
        return
    print(_("famrecon läuft auf {url}  (Strg+C beendet)").format(url=url))
    print(_("Datenordner: {ordner}").format(ordner=DATEN.resolve()))
    if browser:
        threading.Timer(0.6, lambda: app_fenster(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
    print(_("beendet"))
