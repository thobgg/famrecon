"""Abgleich gegen eine Referenz-GEDCOM: an Falkenrath muss die Rekonstitution der Ursprungs-GEDCOM nahekommen."""
import tempfile
import unittest
from pathlib import Path

from famrecon import db, kern, lesen, simulation, vergleich, verknuepfen, zuordnung

GED = Path(__file__).resolve().parent.parent / "beispiel" / "falkenrath.ged"


class Vergleich(unittest.TestCase):
    def test_falkenrath_gegen_sich_selbst(self):
        with tempfile.TemporaryDirectory() as d:
            xlsx = Path(d) / "r.xlsx"; simulation.simulieren(GED, xlsx, 0.0)
            toml = Path(d) / "z.toml"; toml.write_text(zuordnung.toml_text(str(xlsx), zuordnung.vorschlagen(xlsx)), encoding="utf-8")
            con = db.oeffnen(":memory:"); lesen.einlesen(con, lesen.zuordnung_laden(toml), [xlsx]); kern.personen_bauen(con); verknuepfen.verknuepfen(con)
            v = vergleich.vergleichen(con, GED, kopplung="inhalt")
            self.assertGreater(v["gemeinsam"], 500)
            self.assertGreaterEqual(v["praezision"], 0.97, v["falsch"][:3])
            self.assertGreaterEqual(v["vollstaendigkeit"], 0.95, v["verpasst"][:3])
            self.assertIn("gleich", v["eltern"])
            text = vergleich.bericht(v, 2)
            self.assertIn("Präzision", text)
            n = vergleich.tabelle(v, Path(d) / "a.xlsx")
            self.assertEqual(n, len(v["falsch"]) + len(v["verpasst"]))


if __name__ == "__main__":
    unittest.main()
