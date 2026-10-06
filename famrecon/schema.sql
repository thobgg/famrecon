-- famrecon: eine SQLite-Datei je Projekt. Alles ist aus den Quelltabellen
-- reproduzierbar; die Datei ist Bauprodukt, kein Original.

CREATE TABLE IF NOT EXISTS quelle (
  id       INTEGER PRIMARY KEY,
  datei    TEXT NOT NULL,            -- Dateiname der Tabelle
  blatt    TEXT,                     -- Tabellenblatt
  register TEXT NOT NULL,            -- taufe | ehe | tod
  zeilen   INTEGER NOT NULL,
  gelesen_am TEXT NOT NULL,
  UNIQUE(datei, blatt)
);

-- Eine Zeile je Kirchenbucheintrag, so wie sie in der Tabelle steht.
CREATE TABLE IF NOT EXISTS eintrag (
  id       INTEGER PRIMARY KEY,
  quelle   INTEGER NOT NULL REFERENCES quelle(id) ON DELETE CASCADE,
  register TEXT NOT NULL,
  zeile    INTEGER NOT NULL,         -- Zeilennummer in der Tabelle (1 = Kopf)
  jahr     INTEGER,                  -- aus dem Leitdatum, fuer Bereichssuchen
  monat    INTEGER,
  tag      INTEGER,
  UNIQUE(quelle, zeile)
);

-- Die Felder des Eintrags nach der Spaltenzuordnung. `roh` ist der
-- Zellinhalt wie er war, `wert` bereinigt (Leerzeichen, Leerwoerter).
CREATE TABLE IF NOT EXISTS feld (
  eintrag  INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE,
  name     TEXT NOT NULL,
  wert     TEXT,
  roh      TEXT,
  PRIMARY KEY (eintrag, name)
);
CREATE INDEX IF NOT EXISTS feld_name ON feld(name, wert);

-- Normalform: je Eintrag und Rolle eine Person mit den Kernmerkmalen.
-- Gefuellt von kern.py aus eintrag/feld; reproduzierbar, nie von Hand.
CREATE TABLE IF NOT EXISTS person (
  id          INTEGER PRIMARY KEY,
  eintrag     INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE,
  pfad        TEXT NOT NULL,          -- kind | vater | braut_vater | verstorbener_ehepartner ...
  name        TEXT,                   -- kanonische Schreibung, wie geliefert oder aus der Zeile gezogen
  vorname     TEXT,
  name_kb     TEXT,                   -- Kirchenbuchform, falls getrennt geliefert
  vorname_kb  TEXT,
  name_schl   TEXT,                   -- Koelner Phonetik des Nachnamens
  vorname_kanon TEXT,                 -- vereinheitlichte Vornamen
  geschlecht  TEXT,                   -- M | F | NULL
  beruf       TEXT,
  herkunft    TEXT,
  stand       TEXT,                   -- ledig | verwitwet | verheiratet | ...
  konfession  TEXT,
  geburtsname TEXT,
  verstorben  INTEGER NOT NULL DEFAULT 0,   -- als verstorben genannt (weyl., +)
  unsicher    INTEGER NOT NULL DEFAULT 0,   -- Lesart mit ?
  unbekannt   INTEGER NOT NULL DEFAULT 0,   -- Name N./NN.
  totgeburt   INTEGER NOT NULL DEFAULT 0,
  alter_tage  INTEGER,
  geburt_jahr INTEGER, geburt_monat INTEGER, geburt_tag INTEGER,
  geburt_praefix TEXT,                -- CAL wenn aus Alter gerechnet
  bemerkung   TEXT,
  ref         TEXT,                   -- Kennung aus der Quelle, nur zum Messen
  roh         TEXT                    -- die Zelle(n), aus denen die Person stammt
);
CREATE INDEX IF NOT EXISTS person_schl ON person(name_schl, vorname_kanon);
CREATE INDEX IF NOT EXISTS person_eintrag ON person(eintrag, pfad);

-- Verknuepfung: reale Personen (identitaet), Familien, Kinder, und je Rolle
-- eines Eintrags die Entscheidung, zu welcher Identitaet sie gehoert.
CREATE TABLE IF NOT EXISTS identitaet (
  id          INTEGER PRIMARY KEY,
  geschlecht  TEXT,
  name        TEXT,                   -- Geburtsname, wenn bekannt, sonst der genannte Name
  vorname     TEXT,
  name_schl   TEXT,
  vorname_kanon TEXT,
  geburtsname TEXT,
  ehename     TEXT,                   -- bei Frauen: Name aus einer Ehe, wenn der Geburtsname bekannt ist
  unbekannt   INTEGER NOT NULL DEFAULT 0,
  geb_jahr INTEGER, geb_monat INTEGER, geb_tag INTEGER, geb_praefix TEXT,
  tod_jahr INTEGER, tod_monat INTEGER, tod_tag INTEGER,
  famc        INTEGER                 -- Elternfamilie
);
CREATE INDEX IF NOT EXISTS identitaet_schl ON identitaet(name_schl);
CREATE TABLE IF NOT EXISTS familie (
  id          INTEGER PRIMARY KEY,
  mann        INTEGER REFERENCES identitaet(id),
  frau        INTEGER REFERENCES identitaet(id),
  trauung_eintrag INTEGER REFERENCES eintrag(id),
  tr_jahr INTEGER, tr_monat INTEGER, tr_tag INTEGER,
  art         TEXT NOT NULL DEFAULT 'ehe'   -- ehe | eltern (nur aus Taufen/Toden erschlossen) | unehelich
);
CREATE TABLE IF NOT EXISTS kind (
  familie INTEGER NOT NULL REFERENCES familie(id) ON DELETE CASCADE,
  ident   INTEGER NOT NULL REFERENCES identitaet(id) ON DELETE CASCADE,
  PRIMARY KEY (familie, ident)
);
CREATE TABLE IF NOT EXISTS zuordnung (
  person   INTEGER PRIMARY KEY REFERENCES person(id) ON DELETE CASCADE,
  ident    INTEGER NOT NULL REFERENCES identitaet(id) ON DELETE CASCADE,
  stufe    TEXT NOT NULL,             -- neu | sicher | wahrscheinlich | unsicher
  punkte   INTEGER NOT NULL DEFAULT 0,
  grund    TEXT,                      -- woran die Entscheidung hing, Klartext
  alternativen TEXT                   -- JSON [[ident, punkte, grund], ...] fuer die Pruefliste
);

-- Einstellungen des Projekts, die das Verknuepfen braucht (aus [allgemein] der Zuordnung).
CREATE TABLE IF NOT EXISTS einstellung (
  name TEXT PRIMARY KEY,
  wert TEXT
);

-- Entscheidungen von Hand aus der Pruefliste. Sie ueberleben jeden Lauf, weil sie
-- an Personenzeilen haengen, nicht an den (bei jedem Lauf neu vergebenen) Identitaeten.
CREATE TABLE IF NOT EXISTS entscheidung (
  schluessel TEXT PRIMARY KEY,        -- "datei|blatt|zeile|pfad" der Nennung; ueberlebt jedes Neu-Einlesen
  art      TEXT NOT NULL,             -- gleich (wie Nennung `ziel`) | neu (eigene Person)
  ziel     TEXT,                      -- Schluessel der anderen Nennung
  angelegt TEXT NOT NULL
);
