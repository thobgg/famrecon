"""SQLite oeffnen und das Schema anlegen."""
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql")


def oeffnen(pfad):
    """timeout: ein zweiter Schreiber wartet, statt sofort 'database is locked' zu melden.
    WAL: Leser (eine Seite, die gerade den Stand zeigt) blockieren keinen Schreiber."""
    con = sqlite3.connect(pfad, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))
    return con
