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
