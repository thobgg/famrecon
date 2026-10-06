"""Oberflaeche: Server starten, Projekt anlegen, Tabellen hochladen, Zuordnung speichern, bauen, Seiten, GEDCOM."""
import re
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

from famrecon.web import server

B = Path(__file__).resolve().parent.parent / "beispiel"


def multipart(felder, dateien):
    grenze = uuid.uuid4().hex
    body = b""
    for k, v in felder.items():
        body += f"--{grenze}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    for name, inhalt in dateien:
        body += f"--{grenze}\r\nContent-Disposition: form-data; name=\"dateien\"; filename=\"{name}\"\r\nContent-Type: application/octet-stream\r\n\r\n".encode() + inhalt + b"\r\n"
    body += f"--{grenze}--\r\n".encode()
    return body, f"multipart/form-data; boundary={grenze}"


class Oberflaeche(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        server.DATEN = Path(cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        import gc
        gc.collect()                      # Windows: keine offene Verbindung darf die Dateien halten
        cls.tmp.cleanup()

    def hole(self, pfad, daten=None, ctype=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{pfad}", data=daten, method="POST" if daten is not None else "GET")
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            self.fail(f"{pfad}: HTTP {e.code}\n" + re.sub(r"<[^>]+>", "", e.read().decode("utf-8", "replace"))[-1500:])

    def test_durchlauf(self):
        body, ctype = multipart({"name": "kirchenbuchstil"}, [("kirchenbuchstil.xlsx", (B / "kirchenbuchstil.xlsx").read_bytes())])
        st, html = self.hole("/neu", body, ctype)          # landet auf der Zuordnungsseite
        self.assertIn("kirchenbuchstil.xlsx", html)
        self.assertIn('name="f0:A"', html)
        self.assertIn("sicher,", html)                       # Bilanz je Blatt
        # Register umschalten: Feldliste des neuen Registers
        st, html2 = self.hole("/p/kirchenbuchstil/zuordnung?r0=tod")
        self.assertIn('value="verstorbener_name"', html2)
        # alle Auswahlfelder mit ihrem Vorschlag abschicken
        form = {}
        for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*>', html):
            v = re.search(r'value="([^"]*)"', m.group(0))
            form[m.group(1)] = v.group(1) if v else ""
        for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
            sel = re.search(r'<option value="([^"]*)" selected', m.group(2))
            form[m.group(1)] = sel.group(1) if sel else ""
        form["leer"] = "k.A., —"
        st, html = self.hole("/p/kirchenbuchstil/zuordnung", urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded")
        self.assertIn("Zuordnung gespeichert", html)
        st, html = self.hole("/p/kirchenbuchstil/bauen", b"", "application/x-www-form-urlencoded")
        self.assertIn("92 Personen", html)
        st, html = self.hole("/p/kirchenbuchstil/personen?q=Haag")
        self.assertIn("Nicolaus", html)
        st, html = self.hole("/p/kirchenbuchstil/familien?q=Eberle")
        self.assertIn("Leybold", html)
        st, html = self.hole("/p/kirchenbuchstil/pruefliste?alle=1")
        self.assertIn("ist diese Person", html)
        # eine Entscheidung treffen: erste Person der Pruefliste als eigene Person
        person = re.search(r'name="person" value="(\d+)"', html).group(1)
        st, html = self.hole("/p/kirchenbuchstil/entscheidung", f"person={person}&neu=1".encode(), "application/x-www-form-urlencoded")
        self.assertIn("von Hand: neu", self.hole("/p/kirchenbuchstil/pruefliste?alle=1")[1])
        st, html = self.hole("/p/kirchenbuchstil/entscheidung", f"person={person}&loeschen=1".encode(), "application/x-www-form-urlencoded")
        self.assertNotIn("von Hand", self.hole("/p/kirchenbuchstil/pruefliste?alle=1")[1])
        st, html = self.hole("/p/kirchenbuchstil/gedcom")
        self.assertIn("<b>0 Fehler</b>", html)
        # zweites Projekt: bauen ohne gespeicherte Zuordnung, Seiten vor dem Bau
        body, ctype = multipart({"name": "ohne"}, [("k.xlsx", (B / "kirchenbuchstil.xlsx").read_bytes())])
        self.hole("/neu", body, ctype)
        self.assertIn("Zuerst bauen", self.hole("/p/ohne/familien")[1])
        st, html = self.hole("/p/ohne/bauen", b"", "application/x-www-form-urlencoded")
        self.assertIn("Zuordnung bestätigen und bauen", html)   # ohne bestaetigte Zuordnung: erst der Dialog
        form = {}
        for m in re.finditer(r'<input[^>]*name="([^"]+)"[^>]*>', html):
            v = re.search(r'value="([^"]*)"', m.group(0)); form[m.group(1)] = v.group(1) if v else ""
        for m in re.finditer(r'<select[^>]*name="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
            sel = re.search(r'<option value="([^"]*)" selected', m.group(2)); form[m.group(1)] = sel.group(1) if sel else ""
        form["bauen"] = "1"
        st, html = self.hole("/p/ohne/zuordnung", urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded")
        self.assertIn("92 Personen", html)
        st, ged = self.hole("/p/kirchenbuchstil/projekt.ged")
        self.assertTrue(ged.startswith("0 HEAD"))
        self.assertIn("0 TRLR", ged)

    def test_hilfe_und_rahmen(self):
        st, html = self.hole("/hilfe")
        for abschnitt in ("ueberblick", "start", "projekt", "zuordnung", "personen", "familien", "pruefliste", "gedcom", "faq", "fehler"):
            self.assertIn(f'<h2 id="{abschnitt}">', html)
            self.assertIn(f'href="#{abschnitt}"', html)                 # Inhaltsverzeichnis
        self.assertIn("Prüfliste", html)
        st, html = self.hole("/p/kirchenbuchstil")                      # jede Seite verweist auf ihren Abschnitt
        self.assertIn('href="/hilfe?p=kirchenbuchstil#projekt"', html)
        st, html = self.hole("/hilfe?p=kirchenbuchstil")                 # Projektleiste und Zurueck bleiben
        self.assertIn('href="/p/kirchenbuchstil/pruefliste"', html)
        self.assertIn('href="/p/kirchenbuchstil" onclick', html)
        self.assertIn('href="/" onclick', self.hole("/hilfe")[1])
        self.assertIn('action="/beenden"', html)
        st, text = self.hole("/ping")
        self.assertTrue(text.startswith("famrecon "))
        self.assertEqual(server.laeuft_schon(self.port), server.__version__)
        self.assertIsNone(server.laeuft_schon(1))

    def test_gleichzeitige_schreibzugriffe(self):
        """Doppelklick auf 'Beispielprojekt anlegen': zwei Anfragen zugleich duerfen nicht kollidieren
        (frueher: FOREIGN KEY constraint failed / database is locked)."""
        ergebnisse = []

        def anlegen():
            req = urllib.request.Request(f"http://127.0.0.1:{self.port}/beispiele", data=b"", method="POST")
            try:
                with urllib.request.urlopen(req) as r:
                    ergebnisse.append(r.status)
            except urllib.error.HTTPError as e:
                ergebnisse.append(e.code)
        faeden = [threading.Thread(target=anlegen) for _ in range(2)]
        for f in faeden:
            f.start()
        for f in faeden:
            f.join(120)
        self.assertEqual(ergebnisse, [200, 200])
        st, html = self.hole("/p/beispiel-falkenrath/familien?q=Falkenrath")
        self.assertIn("Falkenrath", html)

    def test_beenden(self):
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}/beenden", data=b"", method="POST")
        with urllib.request.urlopen(req) as r:
            self.assertIn("beendet", r.read().decode("utf-8"))
        t.join(5)
        self.assertFalse(t.is_alive())                                  # serve_forever ist zurueckgekehrt
        srv.server_close()

    def test_alte_version_abloesen(self):
        """Nach einem Update: ein laufendes aelteres famrecon wird beendet, der Port uebernommen."""
        from unittest import mock
        srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        echt = server.laeuft_schon                                       # der alte Server meldet im Test dieselbe Version:
        with mock.patch.object(server, "laeuft_schon", lambda p: "0.0.1" if echt(p) else None):   # als aelter ausgeben
            neu, url = server.vorbereiten(port, self.tmp.name)
        self.assertIsNotNone(neu)
        self.assertEqual(neu.server_address[1], port)                    # derselbe Port, der alte ist weg
        neu.server_close()
        srv.server_close()

    def test_vorbereiten_port_belegt(self):
        # der Testserver haelt self.port: vorbereiten erkennt das laufende famrecon
        srv, url = server.vorbereiten(self.port, self.tmp.name)
        if srv is not None:
            srv.server_close()
        self.assertIsNone(srv)
        self.assertIn(str(self.port), url)
        # ein fremder Port-Belegung ohne famrecon: Ausweichen auf einen freien Port
        import socket
        fremd = socket.socket(); fremd.bind(("127.0.0.1", 0)); fremd.listen(1)
        try:
            srv, url = server.vorbereiten(fremd.getsockname()[1], self.tmp.name)
            self.assertIsNotNone(srv)
            self.assertNotIn(str(fremd.getsockname()[1]), url)
            srv.server_close()
        finally:
            fremd.close()


if __name__ == "__main__":
    unittest.main()
