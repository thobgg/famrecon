"""Kommandozeile: famrecon <befehl> ..."""
import argparse
import sys

from . import __version__, db, gedcom, katalog, kern, lesen, messen, pruefe, simulation, verknuepfen, zuordnung
from .i18n import _


def cmd_spalten(args):
    """Blaetter und Ueberschriften einer Tabelle zeigen."""
    for blatt, zeilen, kopf in lesen.blaetter(args.datei):
        print(_("Blatt '{blatt}': {zeilen} Zeilen").format(blatt=blatt, zeilen=zeilen))
        for buchstabe, titel in kopf:
            print(f"  {buchstabe:>3}  {titel}")


def cmd_zuordnung(args):
    """Spaltenzuordnung vorschlagen und als TOML ausgeben."""
    blaetter = [b for d in args.dateien for b in zuordnung.vorschlagen(d)]
    if not blaetter:
        sys.exit(_("Kein Blatt der Zuordnung in den Dateien gefunden."))
    text = zuordnung.toml_text(", ".join(args.dateien), blaetter, mit_datei=len(args.dateien) > 1)
    if args.out:
        open(args.out, "w", encoding="utf-8").write(text)
        for blatt, register, zu, _lw, *_rest in blaetter:
            n = sum(1 for _, s in zu if s["feld"])
            print(f"{register:8} {blatt!r}: {n}/{len(zu)} " + _("Spalten zugeordnet"))
        print(f"-> {args.out}")
    else:
        print(text, end="")


def cmd_bau(args):
    """Tabellen nach Zuordnung einlesen und die Normalform bauen (ohne Verknuepfen)."""
    z = lesen.zuordnung_laden(args.zuordnung)
    for register, feld in lesen.unbekannte_felder(z):
        print(_("Warnung: Feld '{feld}' in [register.{register}] kennt der Katalog nicht.").format(feld=feld, register=register), file=sys.stderr)
    con = db.oeffnen(args.db)
    zaehler = lesen.einlesen(con, z, args.dateien)
    if not zaehler:
        sys.exit(_("Kein Blatt der Zuordnung in den Dateien gefunden."))
    for register, n in zaehler.items():
        print(f"{register:8} {n:>7} " + _("Eintraege"))
    personen = kern.personen_bauen(con)
    print(_("Personen in Normalform:") + " " + ", ".join(f"{r} {n}" for r, n in personen.items()))
    print(f"-> {args.db}")


def cmd_stand(args):
    """Was in der Projektdatei steht: Eintraege, Nennungen, Marker."""
    con = db.oeffnen(args.db)
    for r in con.execute("SELECT register, COUNT(*) n, MIN(jahr) von, MAX(jahr) bis "
                         "FROM eintrag GROUP BY register ORDER BY register"):
        print(f"{r['register']:8} {r['n']:>7} " + _("Eintraege") + f"  {r['von']}–{r['bis']}")
    q = con.execute("SELECT COUNT(*) FROM eintrag WHERE jahr IS NULL").fetchone()[0]
    if q:
        print(_("ohne Jahr: {n}").format(n=q))
    r = con.execute("SELECT COUNT(*) n, SUM(unbekannt) nn, SUM(unsicher) u, SUM(verstorben) v, SUM(totgeburt) t, "
                    "SUM(geschlecht IS NULL) og FROM person").fetchone()
    if r["n"]:
        print(_("Personen: {n}, davon Name unbekannt {nn}, unsicher {u}, als verstorben genannt {v}, Totgeburt {t}, ohne Geschlecht {og}")
              .format(n=r["n"], nn=r["nn"], u=r["u"], v=r["v"], t=r["t"], og=r["og"]))


def cmd_verknuepfen(args):
    """Personen und Familien bilden; --kennungen nutzt das Feld ref als Vorgabe."""
    con = db.oeffnen(args.db)
    verknuepfen.verknuepfen(con, kennungen=True if args.kennungen else None)
    st = verknuepfen.statistik(con)
    print(_("{personen} Personen in Eintraegen -> {identitaeten} Identitaeten, {familien} Familien ({familien_mit_kindern} mit Kindern, {kinder} Kinder)").format(**st))
    print(_("Zuordnungen:") + " " + ", ".join(f"{k} {v}" for k, v in st["stufen"].items()))


def cmd_familien(args):
    """Familien mit Kindern zeigen."""
    verknuepfen.familien_zeigen(db.oeffnen(args.db), args.limit)


def cmd_pruefliste(args):
    """Offene Faelle zeigen (--alle: auch 'wahrscheinlich')."""
    verknuepfen.pruefliste_zeigen(db.oeffnen(args.db), "alle" if args.alle else None)


def cmd_simuliere(args):
    """Aus einer GEDCOM die drei Register erzeugen, mit versteckten Kennungen zum Messen."""
    zaehler, n_i, n_f = simulation.simulieren(args.ged, args.out, args.rauschen, args.saat)
    print(f"{n_i} Personen, {n_f} Familien -> " + ", ".join(f"{k} {v}" for k, v in zaehler.items()) + f" -> {args.out}")


def cmd_messen(args):
    """Verknuepfung gegen die Kennungen der Simulation messen."""
    messen.bericht(db.oeffnen(args.db), args.zeigen)


def cmd_gedcom(args):
    """GEDCOM 5.5.1 schreiben."""
    from pathlib import Path
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    st = gedcom.schreiben(db.oeffnen(args.db), args.out)
    print(_("{indi} Personen, {fam} Familien, {sour} Quellen, {zeilen} Zeilen -> {out}").format(out=args.out, **st))


def cmd_pruefe(args):
    """GEDCOM gegen die Eintraege abgleichen: ist jede Zeile angekommen?"""
    sys.exit(pruefe.main(db.oeffnen(args.db), args.ged))


def cmd_start(args):
    """Oberflaeche im Browser starten."""
    from .web import server
    server.start(args.port, args.daten, not args.kein_browser)


def cmd_personen(args):
    """Nennungen in Normalform zeigen."""
    con = db.oeffnen(args.db)
    kern.zeigen(con, args.register, args.limit)


def main(argv=None):
    p = argparse.ArgumentParser(prog="famrecon",
                                description=_("Familien aus Tauf-, Ehe- und Sterberegistern in Tabellenform."))
    p.add_argument("--version", action="version", version=f"famrecon {__version__}")
    sub = p.add_subparsers(dest="befehl", required=True)

    s = sub.add_parser("spalten", help=_("Blaetter und Ueberschriften einer Tabelle zeigen"))
    s.add_argument("datei")
    s.set_defaults(fn=cmd_spalten)

    s = sub.add_parser("zuordnung", help=_("Spaltenzuordnung aus Ueberschriften und Beispielwerten vorschlagen"))
    s.add_argument("dateien", nargs="+")
    s.add_argument("-o", "--out", help="TOML-Datei schreiben statt auf stdout")
    s.set_defaults(fn=cmd_zuordnung)

    s = sub.add_parser("bau", help=_("Tabellen nach Zuordnung in die Projektdatei einlesen"))
    s.add_argument("zuordnung", help=_("TOML mit der Spaltenzuordnung"))
    s.add_argument("dateien", nargs="+", help="xlsx-Dateien")
    s.add_argument("-o", "--db", default="daten/projekt.db")
    s.set_defaults(fn=cmd_bau)

    s = sub.add_parser("personen", help=_("Personen in Normalform zeigen"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.add_argument("--register", choices=["taufe", "ehe", "tod"])
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(fn=cmd_personen)

    s = sub.add_parser("verknuepfen", help=_("Personen und Familien aus den Eintraegen bilden"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.add_argument("--kennungen", action="store_true", help=_("Kennungen (Feld ref) als Vorgabe: gleiche Kennung ist dieselbe Person"))
    s.set_defaults(fn=cmd_verknuepfen)

    s = sub.add_parser("familien", help=_("Familien mit Kindern zeigen"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.add_argument("--limit", type=int, default=200)
    s.set_defaults(fn=cmd_familien)

    s = sub.add_parser("pruefliste", help=_("Unsichere Zuordnungen zeigen"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.add_argument("--alle", action="store_true", help="auch 'wahrscheinlich'")
    s.set_defaults(fn=cmd_pruefliste)

    s = sub.add_parser("simuliere", help=_("Aus einer GEDCOM die drei Register erzeugen (Wahrheit zum Messen)"))
    s.add_argument("ged")
    s.add_argument("-o", "--out", default="daten/register.xlsx")
    s.add_argument("--rauschen", type=float, default=0.0, help="0..1: Vornamenvarianten, Luecken, Endungen")
    s.add_argument("--saat", type=int, default=1)
    s.set_defaults(fn=cmd_simuliere)

    s = sub.add_parser("messen", help=_("Verknuepfung gegen die Ref-Spalten messen"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.add_argument("--zeigen", type=int, default=10)
    s.set_defaults(fn=cmd_messen)

    s = sub.add_parser("gedcom", help=_("GEDCOM 5.5.1 schreiben"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.add_argument("-o", "--out", default="ausgabe/projekt.ged")
    s.set_defaults(fn=cmd_gedcom)

    s = sub.add_parser("pruefe", help=_("GEDCOM gegen die Eintraege abgleichen: jede Zeile angekommen?"))
    s.add_argument("db")
    s.add_argument("ged")
    s.set_defaults(fn=cmd_pruefe)

    s = sub.add_parser("start", help=_("Oberflaeche im Browser starten"))
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--daten", default=None, help="Projektordner; sonst daten/ neben famrecon")
    s.add_argument("--kein-browser", action="store_true")
    s.set_defaults(fn=cmd_start)

    s = sub.add_parser("stand", help=_("Was in der Projektdatei steht"))
    s.add_argument("db", nargs="?", default="daten/projekt.db")
    s.set_defaults(fn=cmd_stand)

    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
