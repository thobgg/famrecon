"""Einlesen der Kirchenbuchstil- Beispieldatei: Zaehler, Sammelfelder, Leerwoerter."""
import unittest
from pathlib import Path

from famrecon import db, lesen

HIER = Path(__file__).resolve().parent.parent
XLSX = HIER / "beispiel" / "kirchenbuchstil.xlsx"
TOML = HIER / "beispiel" / "kirchenbuchstil.toml"


class Einlesen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = db.oeffnen(":memory:")
        cls.zaehler = lesen.einlesen(cls.con, lesen.zuordnung_laden(TOML), [XLSX])

    def feld(self, register, feldname, **wo):
        bed, par = [], []
        for k, v in wo.items():
            bed.append("e.id IN (SELECT eintrag FROM feld WHERE name=? AND wert=?)")
            par += [k, v]
        sql = ("SELECT f.wert, f.roh FROM eintrag e JOIN feld f ON f.eintrag=e.id "
               f"WHERE e.register=? AND f.name=? AND {' AND '.join(bed)}")
        return self.con.execute(sql, [register, feldname] + par).fetchone()

    def test_zaehler(self):
        self.assertEqual(self.zaehler, {"taufe": 7, "ehe": 14, "tod": 14})

    def test_jahre(self):
        r = self.con.execute("SELECT register, MIN(jahr), MAX(jahr) FROM eintrag "
                             "GROUP BY register ORDER BY register").fetchall()
        self.assertEqual([tuple(x) for x in r],
                         [("ehe", 1732, 1804), ("taufe", 1727, 1815), ("tod", 1722, 1815)])
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM eintrag WHERE jahr IS NULL").fetchone()[0], 0)

    def test_paten_gesammelt(self):
        wert, roh = self.feld("taufe", "paten", kind_name="Haag")
        self.assertEqual(len(wert.split(lesen.TRENNER)), 5)
        self.assertTrue(wert.startswith("Weiß, Christoph Friedrich"))

    def test_leerwort_bleibt_roh(self):
        wert, roh = self.feld("ehe", "braut_vater", braeutigam_name="Feldmann")
        self.assertIsNone(wert)
        self.assertEqual(roh, "k.A.")
        wert, roh = self.feld("taufe", "paten", kind_name="Ebel")
        self.assertIsNone(wert)
        self.assertEqual(roh, "—")

    def test_zwei_spalten_ein_feld(self):
        wert, _ = self.feld("ehe", "bemerkung", braeutigam_name="Obermüller (W)")
        self.assertEqual(len(wert.split(lesen.TRENNER)), 1)      # nur Bemerkung 2 gefuellt
        wert, _ = self.feld("ehe", "bemerkung", braeutigam_name="Rosenfeld von")
        self.assertTrue(wert.startswith("nach diesem Eintrag"))

    def test_zeilenumbruch_im_kb(self):
        wert, _ = self.feld("taufe", "kb", kind_name="Arst")
        self.assertEqual(wert, "Taufen 1738-1758")

    def test_alter_null_als_text(self):
        wert, _ = self.feld("tod", "verstorbener_alter", verstorbener_name="Ebel")
        self.assertEqual(wert, "0")


if __name__ == "__main__":
    unittest.main()


class CSV(unittest.TestCase):
    """CSV mit Semikolon und BOM, wie deutsches Excel es schreibt: ein Blatt je Datei."""

    def test_falkenrath_csv(self):
        b = lesen.blaetter(HIER / "beispiel" / "falkenrath-taufen.csv")
        self.assertEqual(len(b), 1)
        blatt, zeilen, kopf = b[0]
        self.assertEqual((blatt, zeilen), ("falkenrath-taufen", 492))
        self.assertEqual(kopf[0], ("A", "Geburtsdatum"))
        erste = next(lesen.zeilen_lesen(HIER / "beispiel" / "falkenrath-taufen.csv", "falkenrath-taufen"))
        self.assertEqual(erste[0], 2)
        self.assertRegex(str(erste[1][0]), r"^\d{4}-\d{2}-\d{2}$")


class ZweiBlaetterEinRegister(unittest.TestCase):
    """Zwei Taufblaetter (zwei Baende) in einer Mappe: die Zuordnung muss eindeutige Abschnitte schreiben
    (taufe, taufe_2) und das Einlesen beide als Register taufe lesen."""

    def test_zwei_taufblaetter(self):
        import openpyxl, tempfile
        from famrecon import zuordnung as zu
        quelle = openpyxl.load_workbook(XLSX)
        with tempfile.TemporaryDirectory() as d:
            ziel = Path(d) / "zwei.xlsx"
            wb = openpyxl.Workbook(); wb.remove(wb.active)
            for titel, von in (("Taufen 1700", "Taufen"), ("Taufen 1750", "Taufen"), ("Ehen", "Ehen"), ("Tote", "Tote")):
                ws = wb.create_sheet(titel)
                for row in quelle[von].iter_rows(values_only=True):
                    ws.append(list(row))
            wb.save(ziel)
            text = zu.toml_text(str(ziel), zu.vorschlagen(ziel))
            self.assertIn("[register.taufe_2]", text)
            self.assertIn('register = "taufe"', text)
            toml = Path(d) / "z.toml"; toml.write_text(text, encoding="utf-8")
            z = lesen.zuordnung_laden(toml)                                # kein 'Cannot declare twice' mehr
            self.assertEqual(sorted(r["register"] for r in z["register"].values()), ["ehe", "taufe", "taufe", "tod"])
            con = db.oeffnen(":memory:")
            n = lesen.einlesen(con, z, [ziel])
            self.assertEqual(n["taufe"], 14)                               # 7 Taufen je Blatt, beide gelesen
            self.assertEqual(con.execute("SELECT COUNT(*) FROM quelle WHERE register='taufe'").fetchone()[0], 2)
