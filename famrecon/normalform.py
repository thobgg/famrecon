"""Normalform: was in den Zellen steht, in Werte verwandeln, mit denen man rechnen kann.

Personenzeile   "Haag, Nicolaus, weyl., gewesener adelicher Kutscher"
                -> name Haag, vorname Nicolaus, verstorben, beruf "gewesener adelicher Kutscher"
Marker          (W) (Witwe) verwitwet · (in) weibliche Endung · geb. X Geburtsname
                N. NN. NN unbekannt · ? (?) (??) unsicher · weyl. weil. + † verstorben
                "Rosenfeld von" -> "von Rosenfeld" · "Mädchen - totgeboren" -> Totgeburt
Alter           "59 J 10 M 4 T", "3 J., 7 M., 14 T", "24 Wochen", "1 Monat", "0" -> Tage
Datum           "1778-08-31", "1699-08-00", "12.03.1778", "1750" -> (jahr, monat, tag)
Schluessel      Koelner Phonetik fuer Nachnamen (Haag/Hag, Kriehmann/Kriemann treffen sich),
                Vornamen vereinheitlicht (Nicolaus/Nikolaus, Catharina/Katharina)

Nichts hier entscheidet etwas. Es liefert Merkmale, die das Verknuepfen benutzt,
und behaelt den Rohwert daneben.
"""
import re

TOTGEBURT = re.compile(r"\b(tot|tod)\s*-?\s*geb\w*", re.I)
ANONYM = re.compile(r"\banonym\w*", re.I)
GESCHLECHT_WORT = {"mädchen": "F", "töchterlein": "F", "tochter": "F", "knabe": "M", "söhnlein": "M", "sohn": "M", "knäblein": "M"}


def _leer(t):
    return t is None or not str(t).strip()


# ----------------------------------------------------------------- Namen
def person_zerlegen(text):
    """Eine Personenangabe (eine Zelle) -> dict mit name, vorname, beruf, Markern.

    Schreibweise im Kirchenbuchstil: "Nachname, Vorname, Zusatz, Zusatz". Alles
    hinter dem Vornamen ist Zusatz (Beruf, Herkunft, Stand). Marker werden aus
    den Teilen herausgezogen und als Flags geliefert.
    """
    p = dict(name=None, vorname=None, beruf=None, geburtsname=None, stand=None,
             verstorben=False, unsicher=False, unbekannt=False, totgeburt=False,
             geschlecht=None, alternative=None, roh=text)
    if _leer(text):
        return p
    t = re.sub(r"\s+", " ", str(text)).strip()
    teile = [x.strip() for x in t.split(",")]
    kopf, rest = teile[0], teile[1:]
    kopf, flags = marker(kopf)
    p.update(flags)
    if TOTGEBURT.search(kopf) or TOTGEBURT.search(t):
        p["totgeburt"] = True
        kopf = geschlechtswort_entfernen(TOTGEBURT.sub("", kopf))
    p["name"] = kopf or None
    if rest:
        vn, flags = marker(rest[0])
        for k, v in flags.items():
            if v:
                p[k] = v
        if TOTGEBURT.search(vn):
            p["totgeburt"] = True
            vn = geschlechtswort_entfernen(TOTGEBURT.sub("", vn))
        p["vorname"] = vn or None
        rest = rest[1:]
    partikel_umsetzen(p)
    zusatz = []
    for z in rest:
        z2, flags = marker(z)
        for k, v in flags.items():
            if v:
                p[k] = v
        if z2:
            zusatz.append(z2)
    if zusatz:
        p["beruf"] = ", ".join(zusatz)
    return p


def partikel_umsetzen(p):
    """'Rebenfels' + 'Maria Magdalena von' -> 'von Rebenfels' + 'Maria Magdalena'."""
    vn = p.get("vorname") or ""
    m = re.match(r"^(von der|von dem|von|zu|de|v\.)\s+(.+)$", vn) or re.match(r"^(.+?)\s+(von der|von dem|von|zu|de|v\.)$", vn)
    if m:
        partikel, rest = (m.group(1), m.group(2)) if m.group(1) in ("von der", "von dem", "von", "zu", "de", "v.") else (m.group(2), m.group(1))
        p["vorname"] = rest.strip() or None
        if p.get("name") and not p["name"].lower().startswith(partikel):
            p["name"] = f"{partikel} {p['name']}"
    if p.get("vorname") and ANONYM.search(p["vorname"]):
        p["vorname"] = ANONYM.sub("", p["vorname"]).strip() or None
        p["unbekannt_vorname"] = True


def geschlechtswort_entfernen(t):
    """'Mädchen - totgeboren' -> '': Geschlechtswoerter aus einer Namenszelle streichen, Rest bereinigen."""
    for wort in GESCHLECHT_WORT:
        t = re.sub(rf"\b{wort}\b", "", t, flags=re.I)
    return re.sub(r"[\s\-–,;]+", " ", t).strip(" -–,;") or ""


def marker(teil):
    """Marker aus einem Namensteil ziehen -> (bereinigter Teil, flags)."""
    f = dict(verstorben=False, unsicher=False, unbekannt=False, stand=None,
             geburtsname=None, geschlecht=None, alternative=None)
    t = teil.strip()
    if re.fullmatch(r"(weyl|weil|weiland|sel|seel|selig|seelig|gest|verst)\.?", t, re.I) or t in ("+", "†"):
        f["verstorben"] = True
        return "", f
    if re.match(r"(weyl|weil|weiland)\.?\s", t, re.I):
        f["verstorben"] = True
        t = re.sub(r"^(weyl|weil|weiland)\.?\s*", "", t, flags=re.I)
    if re.search(r"^\+\s|\s\+\s|†", t):
        f["verstorben"] = True
        t = re.sub(r"(^\+\s|\s\+\s|†)", " ", t).strip()
    if re.search(r"\((W|Witwe|Witwer|Wwe|Wwer)\)", t, re.I) or re.search(r"\bWitt?we(r)?\b", t):
        f["stand"] = "verwitwet"
        t = re.sub(r"\((W|Witwe|Witwer|Wwe|Wwer)\)", "", t, flags=re.I)
        t = re.sub(r",?\s*\bWitt?we(r)?\b", "", t).strip()
    m = re.search(r"\bgeb\.?\s+([^\s(,]+(?:\s[^\s(,]+)?)", t)
    if m:
        f["geburtsname"] = re.sub(r"\(in\)$", "", m.group(1)).strip()
        t = (t[:m.start()] + t[m.end():]).strip()
    m = re.search(r"\(\?\??\)\s*=\s*(\S+)|=\s*(\S+)\s*$", t)
    if m:
        f["alternative"] = m.group(1) or m.group(2)
        t = t[:m.start()].strip()
    if re.search(r"\?", t):
        f["unsicher"] = True
        t = re.sub(r"\s*\(\?+\)|\s*\?+", "", t).strip()
    if re.search(r"\(in\)$|\(in\)", t):
        f["geschlecht"] = "F"
        t = re.sub(r"\(in\)", "", t).strip()
    if re.fullmatch(r"N\.?N?\.?|NN\.?|N\. N\.|unbekannt|unknown", t, re.I):
        f["unbekannt"] = True
        return "", f
    m = re.fullmatch(r"(.+?)\s+(von|v\.|de|zu|von der|von dem)", t)
    if m:
        t = f"{m.group(2)} {m.group(1)}"
    for wort, g in GESCHLECHT_WORT.items():
        if re.search(rf"\b{wort}\b", t, re.I):
            f["geschlecht"] = g
    t = re.sub(r"\s+", " ", t).strip(" ,;")
    return t, f


# ------------------------------------------------------------------ Alter
EINHEIT = [(r"j(ahre?|\.)?", 365), (r"m(o|onate?|\.)?", 30), (r"w(o|ochen?|\.)?", 7), (r"t(age?|\.)?", 1), (r"st(unden?|d\.?)?", 0)]


def alter_tage(text):
    """'59 J 10 M 4 T', '24 Wochen', '1 Monat', '0' -> Tage (int) oder None."""
    if _leer(text):
        return None
    t = str(text).strip().lower().replace("½", " 0.5")
    if re.fullmatch(r"\d+", t):
        return int(t)                           # nackte Zahl: Jahre, nur 0 heisst 0
    tage, gefunden = 0, False
    for zahl, einheit in re.findall(r"(\d+(?:[.,]\d+)?)\s*([a-zäöü.]+)", t):
        for muster, faktor in EINHEIT:
            if re.fullmatch(muster, einheit.rstrip(".")):
                tage += float(zahl.replace(",", ".")) * faktor
                gefunden = True
                break
    if not gefunden:
        m = re.fullmatch(r"(\d+)\s*j.*", t)
        return int(m.group(1)) * 365 if m else None
    return int(round(tage))


# ------------------------------------------------------------------ Datum
def _gueltig(j, mo, ta):
    """Unmoegliche Monate oder Tage (Tippfehler wie 1793-93-04) gelten als unbekannt, das Jahr bleibt."""
    mo = mo if mo and 1 <= mo <= 12 else None
    ta = ta if ta and 1 <= ta <= 31 and mo else None
    return j, mo, ta


def datum_zerlegen(text):
    """-> (jahr, monat|None, tag|None) oder None. 00 heisst unbekannt; unmoegliche Werte ebenso."""
    if _leer(text):
        return None
    t = str(text).strip()
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        j, mo, ta = (int(x) for x in m.groups())
        return _gueltig(j, mo, ta)
    m = re.match(r"(\d{4})-(\d{1,2})$", t)
    if m:
        return _gueltig(int(m.group(1)), int(m.group(2)), None)
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t)
    if m:
        return _gueltig(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"\b(1[5-9]\d\d|20\d\d)\b", t)
    return (int(m.group(1)), None, None) if m else None


def datum_praefix(text):
    """'um 1750', 'vor 1800', 'CAL' -> GEDCOM-Praefix oder None."""
    t = str(text or "").strip().lower()
    for muster, p in ((r"^(um|ca|etwa|abt)", "ABT"), (r"^(vor|bef)", "BEF"), (r"^(nach|aft)", "AFT"), (r"^(err|cal|berechnet)", "CAL"), (r"^(est|gesch)", "EST")):
        if re.match(muster, t):
            return p
    return None


def tage_seit(jmt):
    """Ordinal eines (jahr, monat, tag) mit Ersatz fuer Unbekanntes (Mitte)."""
    import datetime as dt
    j, m, t = jmt
    try:
        return dt.date(j, m or 6, t or 15).toordinal()
    except ValueError:                                       # 31. Februar, Monat 93 und aehnliche Schreibfehler
        return dt.date(j, m if m and 1 <= m <= 12 else 6, 1).toordinal()


def datum_minus_tage(jmt, tage):
    """Kalenderdatum `tage` vor dem Datum (Jahr, Monat, Tag): Geburt aus Sterbedatum und Alter."""
    import datetime as dt
    return dt.date.fromordinal(tage_seit(jmt) - tage)


# ------------------------------------------------------------- Schluessel
def koelner(name):
    """Koelner Phonetik: Haag/Hag -> 0, Kriehmann/Kriemann -> 3566, Eberle/Eberlin -> 0175/01756."""
    if not name:
        return ""
    s = name.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss").replace("ph", "f")
    s = re.sub(r"[^a-z]", "", s)
    if not s:
        return ""
    code = []
    for i, c in enumerate(s):
        prev = s[i - 1] if i else ""
        nxt = s[i + 1] if i + 1 < len(s) else ""
        if c in "aeijouy":
            k = "0"
        elif c == "h":
            k = "-"
        elif c == "b":
            k = "1"
        elif c == "p":
            k = "3" if nxt == "h" else "1"
        elif c in "dt":
            k = "8" if nxt in "csz" else "2"
        elif c in "fvw":
            k = "3"
        elif c in "gkq":
            k = "4"
        elif c == "c":
            if i == 0:
                k = "4" if nxt in "ahkloqrux" else "8"
            elif prev in "sz":
                k = "8"
            elif nxt in "ahkoqux":
                k = "4"
            else:
                k = "8"
        elif c == "x":
            k = "8" if prev in "ckq" else "48"
        elif c == "l":
            k = "5"
        elif c in "mn":
            k = "6"
        elif c == "r":
            k = "7"
        elif c in "sz":
            k = "8"
        else:
            k = ""
        code.append(k)
    raw = "".join(code).replace("-", "")
    out = raw[0] if raw else ""
    for a, b in zip(raw, raw[1:]):
        if b != a:
            out += b
    return out[0] + out[1:].replace("0", "") if out else ""


VORNAME_REGELN = [(r"(?<!s)c(?=[aou])", "k"), (r"ck", "k"), (r"th", "t"), (r"ph", "f"), (r"y", "i"), (r"ie", "i"), (r"ia$", "ia"),
                  (r"(.)\1", r"\1"), (r"dt$", "t"), (r"ae", "ä"), (r"oe", "ö"), (r"ue", "ü"), (r"ß", "ss"),
                  (r"(?<=[^aeiou])a$", "e")]        # weibliche Endung a/e wechselt (Friderica/Friderike, Catharina/Catharine)
VORNAME_TABELLE = {"johannes": "johann", "joannes": "johann", "johan": "johann", "georgius": "georg", "jacobus": "jacob",
                   "jakobus": "jacob", "jakob": "jacob", "nicolaus": "nikolaus", "conrad": "konrad", "carl": "karl", "caspar": "kaspar",
                   "catharina": "katharina", "christoph": "kristof", "christof": "kristof", "christina": "kristina", "christine": "kristina", "christian": "kristian",
                   "hans": "johann", "hanß": "johann", "hanss": "johann", "hanns": "johann", "jerg": "georg", "jörg": "georg", "görg": "georg",
                   "fridrich": "friedrich", "friderich": "friedrich", "friederich": "friedrich",
                   "friderica": "friederike", "friederika": "friederike", "friedrika": "friederike", "friederica": "friederike",
                   "luisa": "luise", "louise": "luise", "luise": "luise", "elisabetha": "elisabeth", "katarina": "katharina",
                   "margretha": "margaretha", "margarete": "margaretha", "magdalene": "magdalena",
                   "dorothee": "dorothea", "sophie": "sophia", "marie": "maria", "rosine": "rosina", "regine": "regina"}


def vorname_kanon(vorname):
    """'Nicolaus Christoph' -> 'nikolaus kristof': Schreibvarianten zusammenziehen."""
    if not vorname:
        return ""
    out = []
    for w in re.split(r"[\s-]+", vorname.lower().strip()):
        w = re.sub(r"[^\wäöüß]", "", w)
        if not w:
            continue
        w = VORNAME_TABELLE.get(w, w)
        for muster, ersatz in VORNAME_REGELN:
            w = re.sub(muster, ersatz, w)
        out.append(w)
    return " ".join(out)


MAENNLICH = set("""johann hans georg michael martin jacob jakob christian christoph andreas friedrich adam bernhard
david daniel philipp peter paul konrad conrad leonhard ludwig matthias matthäus nicolaus nikolaus sebastian simon
stephan stefan tobias valentin wilhelm wolf wolfgang zacharias kaspar caspar melchior balthasar gottfried gottlieb
josef joseph karl carl heinrich ernst ferdinand franz lorenz benedikt bartholome bartholomäus jörg ulrich albrecht
alexander anton august eberhard erhard friedlieb israel johannes markus marcus nikolaus vollrad""".split())
WEIBLICH = set("""anna maria margaretha margarete katharina catharina elisabeth elisabetha barbara eva susanna susanne
christina christine dorothea dorothee magdalena agnes ursula rosina regina sabina judith juliana sophia sophie
friederike friederika friderica friedrika johanna justina lucia sara sarah salome helena helene anastasia apollonia
cordula felicitas gertrud hedwig kunigunde kunigunda ottilia sibylla sibilla veronica veronika agatha agathe
brigitte brigitta clara klara eleonora eleonore luisa luise louise eberhardina francisca franziska wilhelmina
wilhelmine augusta auguste karoline caroline charlotte amalia amalie philippina ernestina""".split())


def geschlecht_aus_vorname(vorname):
    """M/F aus bekannten Vornamen (Listen MAENNLICH/WEIBLICH), sonst None."""
    if not vorname:
        return None
    for w in re.split(r"[\s-]+", vorname.lower()):
        w = re.sub(r"[^\wäöüß]", "", w)
        if w in MAENNLICH:
            return "M"
        if w in WEIBLICH:
            return "F"
    return None


def levenshtein(a, b):
    """Schreibdistanz zweier Strings (Einfuegen, Loeschen, Ersetzen), ohne Gross/Klein."""
    a, b = (a or "").lower(), (b or "").lower()
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def namen_aehnlich(a, b, schl_a=None, schl_b=None):
    """Nachnamen gleich genug? Gleicher Koelner Schluessel oder kleine Schreibdistanz."""
    if not a or not b:
        return False
    if a.lower() == b.lower():
        return True
    if (schl_a or koelner(a)) == (schl_b or koelner(b)):
        return True
    d = levenshtein(a, b)                                    # ein Buchstabe immer; zwei nur bei laengeren Namen mit
    return d <= 1 or (d == 2 and max(len(a), len(b)) >= 7 and a[:3].lower() == b[:3].lower())   # gleichem Anfang (Aberle/Aberlin, nicht Weber/Wegmer)




FUELLNAMEN = {w for n in ("Johann", "Johannes", "Hans", "Anna", "Maria") for w in vorname_kanon(n).split()}   # Beinamen, die fast jeder traegt


def vornamen_punkte(a_kanon, b_kanon):
    """100 gleich; einer gegen mehrere: 90 Rufname vorn (Jacob = Jacob Friedrich), 80 Rufname hinten
    (Jacob = Johann Jacob), 60/40 wenn der gemeinsame Name nur Johann/Anna/Maria ist; mehrere gegen mehrere:
    70 zwei gemeinsame, sonst 0 verschieden; None wenn einer fehlt."""
    if not a_kanon or not b_kanon:
        return None
    if a_kanon == b_kanon:
        return 100
    ta, tb = a_kanon.split(), b_kanon.split()
    if len(ta) == 1 or len(tb) == 1:
        einer, mehrere = (ta[0], tb) if len(ta) == 1 else (tb[0], ta)
        if einer == mehrere[0]:
            return 60 if einer in FUELLNAMEN else 90
        if einer in mehrere:
            return 40 if einer in FUELLNAMEN else 80
        return 0
    gemeinsam = [t for t in ta if t in tb]
    return 70 if len(gemeinsam) >= 2 else 0                  # Johann Georg gegen Christoph Georg: verschieden


def vornamen_widerspruch(a_kanon, b_kanon):
    """Echter Widerspruch fuer Vetos: beide bekannt und kein gemeinsamer Namensteil."""
    if not a_kanon or not b_kanon:
        return False
    return not (set(a_kanon.split()) & set(b_kanon.split()))
