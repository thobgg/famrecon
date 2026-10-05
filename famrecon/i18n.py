"""Anzeigetexte: Deutsch im Code, Uebersetzungen in sprachen/<xx>/LC_MESSAGES/famrecon.po.

    FAMRECON_SPRACHE=en famrecon stand     erzwingt eine Sprache
    sonst entscheidet die Systemsprache (LANGUAGE, LC_ALL, LANG)

Neue Sprache: famrecon.po kopieren, uebersetzen, mit `make sprachen` (msgfmt)
uebersetzen lassen. Fehlt die .mo-Datei, bleibt es bei Deutsch.
"""
import gettext
import os
from pathlib import Path

ORDNER = Path(__file__).with_name("sprachen")
_sprachen = [os.environ["FAMRECON_SPRACHE"]] if os.environ.get("FAMRECON_SPRACHE") else None
_t = gettext.translation("famrecon", localedir=ORDNER, languages=_sprachen, fallback=True)
_ = _t.gettext
