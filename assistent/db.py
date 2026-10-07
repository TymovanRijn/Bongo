"""SQLite: één bestand voor de wachtrij, het logboek, het verbruik en de metingen.

Elke bewerking opent een eigen verbinding. Dat is goedkoop bij SQLite en maakt het
veilig om vanuit meerdere threads (webserver, brein) tegelijk te werken.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS voorstellen (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    soort        TEXT NOT NULL,
    samenvatting TEXT NOT NULL,
    gegevens     TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'open',
    resultaat    TEXT,
    bron         TEXT,
    aangemaakt   TEXT NOT NULL,
    afgehandeld  TEXT,
    afgehandeld_via TEXT
);
CREATE INDEX IF NOT EXISTS voorstellen_status ON voorstellen(status);

CREATE TABLE IF NOT EXISTS gebeurtenissen (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tijd    TEXT NOT NULL,
    gesprek TEXT,
    soort   TEXT NOT NULL,
    inhoud  TEXT NOT NULL,
    bron    TEXT
);
CREATE INDEX IF NOT EXISTS gebeurtenissen_gesprek ON gebeurtenissen(gesprek);

CREATE TABLE IF NOT EXISTS verbruik (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    tijd          TEXT NOT NULL,
    datum         TEXT NOT NULL,
    model         TEXT,
    doel          TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_write   INTEGER NOT NULL DEFAULT 0,
    cache_read    INTEGER NOT NULL DEFAULT 0,
    kosten_usd    REAL NOT NULL DEFAULT 0,
    ms            INTEGER
);
CREATE INDEX IF NOT EXISTS verbruik_datum ON verbruik(datum);

CREATE TABLE IF NOT EXISTS metingen (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tijd    TEXT NOT NULL,
    stap    TEXT NOT NULL,
    ms      INTEGER NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS ochtendoverzicht (
    datum  TEXT PRIMARY KEY,
    tekst  TEXT NOT NULL,
    gemaakt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apparaten (
    token_hash    TEXT PRIMARY KEY,
    naam          TEXT NOT NULL,
    aangemaakt    TEXT NOT NULL,
    laatst_gezien TEXT
);
"""


def nu_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, pad: Path):
        self.pad = Path(pad)
        self.pad.parent.mkdir(parents=True, exist_ok=True)
        with self.verbinding() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def verbinding(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.pad, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=10000")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()
