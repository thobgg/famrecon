"""Seite "Verfahren" im Buch: Schema und Zahlen des Bestands."""
import tempfile
import unittest
from pathlib import Path

from famrecon import buch, db, gedcom, kern, lesen, verknuepfen

B = Path(__file__).resolve().parent.parent / "beispiel"


class Verfahren(unittest.TestCase):
    def test_seite(self):
        d = Path(tempfile.mkdtemp())
        con = db.oeffnen(d / "p.db")
        lesen.einlesen(con, lesen.zuordnung_laden(B / "kirchenbuchstil.toml"), [B / "kirchenbuchstil.xlsx"])
        kern.personen_bauen(con)
        verknuepfen.verknuepfen(con)
        gedcom.schreiben(con, d / "p.ged")
        buch.bauen(con, d / "buch", {"titel": "Test", "untertitel": "", "einleitung": "", "erfasser": "", "bearbeiter": "",
                                     "impressum": "", "datenschutz": "", "noindex": True}, d / "p.ged", "test")
        s = (d / "buch" / "verfahren.html").read_text(encoding="utf-8")
        for teil in ('<ol class="schema">', "1. Register", "3. Verknüpfen", "5. Offen lassen statt raten", "7. Kontrolle", "Grenzen"):
            self.assertIn(teil, s)
        n = con.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0]
        self.assertIn(f'<span class="zahl">{n}</span>Einträge', s)
        self.assertIn('href="verfahren.html"', (d / "buch" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
