"""GEDCOM-Ausgabe: Struktur, Ereignisse, Quellen; Abgleich gegen die Eintraege ohne Fehler."""
import tempfile
import unittest
from pathlib import Path

from famrecon import db, gedcom, kern, lesen, pruefe, simulation, verknuepfen

B = Path(__file__).resolve().parent.parent / "beispiel"


class Kirchenbuchstil(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = db.oeffnen(":memory:")
        lesen.einlesen(cls.con, lesen.zuordnung_laden(B / "kirchenbuchstil.toml"), [B / "kirchenbuchstil.xlsx"])
        kern.personen_bauen(cls.con)
        verknuepfen.verknuepfen(cls.con)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ged = Path(cls.tmp.name) / "k.ged"
        cls.st = gedcom.schreiben(cls.con, cls.ged)
        cls.indis, cls.fams = simulation.lesen(cls.ged)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def indi(self, nachname, vorname):
        t = [r for r in self.indis.values() if simulation.wert(r, "NAME") == f"{vorname} /{nachname}/"]
        self.assertEqual(len(t), 1, (nachname, vorname, len(t)))
        return t[0]

    def test_zaehler(self):
        self.assertEqual((self.st["indi"], self.st["fam"], self.st["sour"]), (len(self.indis), len(self.fams), 3))
        self.assertEqual(self.st["indi"], 76)

    def test_fundstelle_mit_art_und_rolle(self):
        r = self.indi("Haag", "Christoph Georg")
        self.assertEqual((simulation.wert(r, "CHR", "SOUR", "EVEN"), simulation.wert(r, "CHR", "SOUR", "EVEN", "ROLE")), ("CHR", "CHIL"))
        text = self.ged.read_text(encoding="utf-8")
        for rolle in ("FATH", "HUSB", "SPOU", "(Verstorbener)", "(Braut: Vater)"):
            self.assertIn(f"4 ROLE {rolle}\n", text)
        self.assertEqual(gedcom.rolle("mutter_mutter"), "(Mutter: Mutter)")

    def test_kind_mit_taufe_paten_und_rueckverweis(self):
        r = self.indi("Haag", "Christoph Georg")
        self.assertEqual(simulation.wert(r, "BIRT", "DATE"), "31 AUG 1778")
        self.assertEqual(simulation.wert(r, "CHR", "DATE"), "1 SEP 1778")
        self.assertTrue(simulation.wert(r, "CHR", "NOTE").startswith("Taufpaten: Weiß, Christoph Friedrich"))
        self.assertEqual(simulation.wert(r, "DEAT", "DATE"), "27 MAY 1845")
        self.assertEqual(simulation.wert(r, "CHR", "SOUR", "PAGE"), "Taufbuch 1771-1778 S. 585 Nr. 2")
        self.assertEqual(simulation.wert(r, "FAMC"), "@F24@")

    def test_verstorbene_mit_alter_und_cal_geburt(self):
        r = self.indi("Kugel", "Luise Dorothee")
        self.assertEqual(simulation.wert(r, "DEAT", "AGE"), "59 J 10 M 4 T")
        self.assertEqual(simulation.wert(r, "BIRT", "DATE"), "CAL 1739")
        namen = [k["wert"] for k in r["kinder"] if k["tag"] == "NAME"]
        self.assertEqual(namen, ["Luise Dorothee /Kugel/", "Luise Dorothee /Lutz/"])

    def test_reihenfolge_der_ereignisse(self):
        r = self.indi("Eberlin", "Christoph Erhard")
        tags = [k["tag"] for k in r["kinder"] if k["tag"] in ("BIRT", "CHR", "OCCU", "DEAT", "BURI")]
        self.assertEqual(tags, sorted(tags, key=["BIRT", "CHR", "OCCU", "DEAT", "BURI"].index))

    def test_schreibvariante_als_kb_name(self):
        r = self.indi("Eberle", "Sophia Eleonora Eva")
        aka = [k["wert"] for k in r["kinder"] if k["tag"] == "NAME" and simulation.wert(k, "TYPE") == "aka"]
        self.assertIn("Sophia Eleonora Eva /Eberlein/", aka)

    def test_familie_mit_trauung(self):
        f = [x for x in self.fams.values() if simulation.wert(x, "MARR", "DATE") == "26 JUL 1768"]
        self.assertEqual(len(f), 1)
        self.assertEqual(len(simulation.sub(f[0], "CHIL")), 1)

    def test_abgleich_ohne_fehler(self):
        n, fehler = pruefe.pruefen(self.con, self.ged)
        self.assertEqual((n, fehler), ({"taufe": 7, "ehe": 14, "tod": 14}, []))


if __name__ == "__main__":
    unittest.main()


class Belege(unittest.TestCase):
    """Erfunden: Trauung 1780, Taufe 1781 mit Mutter NN und ohne Geburtsdatum, Tod des Vaters 1801 mit Alter."""
    DATEIEN = {
        "ehen.csv": "Datum;Br Vorname;Br Name;Braut Vorname;Braut Name\n1780-05-02;Jakob;Kessler;Maria;Bühler\n",
        "taufen.csv": "Taufdatum;Vorname;Name;Vater Vorname;Vater Name;Mutter Vorname;Mutter Name\n1781-03-04;Anna;Kessler;Jakob;Kessler;Maria;NN\n",
        "tote.csv": "Sterbedatum;Vorname;Name;Alter;Ehefrau\n1801-11-20;Jakob;Kessler;50 Jahre;Bühler, Maria\n"}
    TOML = """[allgemein]
leer = ["NN"]
[register.ehe]
blatt = "ehen"
datei = "ehen.csv"
leitdatum = ["trauung_datum"]
[register.ehe.spalten]
A = "trauung_datum"
B = "braeutigam_vorname"
C = "braeutigam_name"
D = "braut_vorname"
E = "braut_name"
[register.taufe]
blatt = "taufen"
datei = "taufen.csv"
leitdatum = ["tauf_datum"]
[register.taufe.spalten]
A = "tauf_datum"
B = "kind_vorname"
C = "kind_name"
D = "vater_vorname"
E = "vater_name"
F = "mutter_vorname"
G = "mutter_name"
[register.tod]
blatt = "tote"
datei = "tote.csv"
leitdatum = ["sterbe_datum"]
[register.tod.spalten]
A = "sterbe_datum"
B = "verstorbener_vorname"
C = "verstorbener_name"
D = "verstorbener_alter"
E = "verstorbener_ehepartner"
"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        for n, t in cls.DATEIEN.items():
            (d / n).write_text(t, encoding="utf-8")
        (d / "z.toml").write_text(cls.TOML, encoding="utf-8")
        cls.con = db.oeffnen(":memory:")
        lesen.einlesen(cls.con, lesen.zuordnung_laden(d / "z.toml"), [d / n for n in cls.DATEIEN])
        kern.personen_bauen(cls.con)
        verknuepfen.verknuepfen(cls.con)
        gedcom.schreiben(cls.con, d / "b.ged")
        cls.indis, _ = simulation.lesen(d / "b.ged")

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        cls.tmp.cleanup()

    def indi(self, name):
        t = [r for r in self.indis.values() if simulation.wert(r, "NAME") == name]
        self.assertEqual(len(t), 1, name)
        return t[0]

    def test_name_der_mutter_aus_der_trauung_belegt(self):
        r = self.indi("Maria /Bühler/")
        name = simulation.sub(r, "NAME")[0]
        self.assertIn(("MARR", "WIFE"), [(simulation.wert(q, "EVEN"), simulation.wert(q, "EVEN", "ROLE")) for q in simulation.sub(name, "SOUR")])

    def test_taufdatum_wird_nicht_geburt(self):
        r = self.indi("Anna /Kessler/")
        self.assertIsNone(simulation.wert(r, "BIRT"))
        self.assertEqual(simulation.wert(r, "CHR", "DATE"), "4 MAR 1781")

    def test_geburt_aus_dem_alter_mit_vermerk(self):
        r = self.indi("Jakob /Kessler/")
        self.assertTrue(simulation.wert(r, "BIRT", "DATE").startswith("CAL"))
        q = simulation.sub(simulation.sub(r, "BIRT")[0], "SOUR")[0]
        self.assertEqual((simulation.wert(q, "EVEN"), simulation.wert(q, "EVEN", "ROLE")), ("DEAT", "(Verstorbener)"))
        self.assertTrue(simulation.wert(q, "NOTE").startswith("Geburt errechnet aus dem Alter, aus diesem Eintrag übernommen"))
