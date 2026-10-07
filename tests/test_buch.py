"""Das Buch: statische Site aus der Projektdatei, jede Seite da, Artikel mit Fundstellen und Stufen."""
import tempfile
import unittest
from pathlib import Path

from famrecon import buch, db, gedcom, kern, lesen, verknuepfen

B = Path(__file__).resolve().parent.parent / "beispiel"


class Buch(unittest.TestCase):
    def test_site(self):
        con = db.oeffnen(":memory:")
        lesen.einlesen(con, lesen.zuordnung_laden(B / "kirchenbuchstil.toml"), [B / "kirchenbuchstil.xlsx"])
        kern.personen_bauen(con); verknuepfen.verknuepfen(con)
        with tempfile.TemporaryDirectory() as d:
            ged = Path(d) / "p.ged"; gedcom.schreiben(con, ged)
            konfig = Path(d) / "buch.toml"; konfig.write_text('titel = "OFB Probe"\neinleitung = "Ein Satz."\nerfasser = "Jemand"\n', encoding="utf-8")
            st = buch.bauen(con, Path(d) / "site", konfig, ged, "probe")
            self.assertEqual(st["familien"], con.execute("SELECT COUNT(*) FROM familie").fetchone()[0])
            for name in ("index.html", "familien.html", "personen.html", "orte.html", "berufe.html", "quellen.html", "prueffaelle.html", "stufen.html", "statistik.html", "stil.css", "impressum.html", "datenschutz.html"):
                self.assertTrue((Path(d) / "site" / name).exists(), name)
            index = (Path(d) / "site" / "index.html").read_text(encoding="utf-8")
            self.assertIn("OFB Probe", index); self.assertIn("noindex", index); self.assertIn(".ged", index)
            fam = (Path(d) / "site" / "familien-H.html").read_text(encoding="utf-8")   # Haag/Hag
            self.assertIn("Haag, Nicolaus", fam); self.assertIn("Taufe 1778", fam)    # Fundstelle am Kind
            self.assertIn("Belege", fam); self.assertIn("Ehe erschlossen", fam)


if __name__ == "__main__":
    unittest.main()
