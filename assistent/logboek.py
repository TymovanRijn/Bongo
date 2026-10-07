"""Logboek: wat er gezegd en gedaan is, wat het kostte en hoe snel het ging."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from .db import Database, nu_iso

# Prijzen in dollar per miljoen tokens: (input, output, cache schrijven 5 min, cache lezen).
PRIJZEN: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 5.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 6.25, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 6.25, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00, 2.50, 0.20),
    "claude-sonnet-5": (2.00, 10.00, 2.50, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 1.25, 0.10),
    "claude-fable-5-1": (10.00, 50.00, 12.50, 0.25),
}


def prijs_voor(model: str) -> tuple[float, float, float, float]:
    for naam, prijs in PRIJZEN.items():
        if model == naam or model.startswith(naam + "-"):
            return prijs
    return PRIJZEN["claude-opus-5-5"]


def bereken_kosten(model: str, inp: int, out: int, cache_write: int, cache_read: int) -> float:
    p_in, p_out, p_write, p_read = prijs_voor(model)
    return (inp * p_in + out * p_out + cache_write * p_write + cache_read * p_read) / 1_000_000


class Logboek:
    def __init__(self, db: Database):
        self.db = db

    # ---- gesprekken en toolaanroepen -------------------------------------------------
    def schrijf(self, soort: str, inhoud: Any, gesprek: str | None = None, bron: str | None = None) -> None:
        tekst = inhoud if isinstance(inhoud, str) else json.dumps(inhoud, ensure_ascii=False, default=str)
        with self.db.verbinding() as con:
            con.execute(
                "INSERT INTO gebeurtenissen (tijd, gesprek, soort, inhoud, bron) VALUES (?, ?, ?, ?, ?)",
                (nu_iso(), gesprek, soort, tekst, bron),
            )

    def recent(self, limiet: int = 100, gesprek: str | None = None) -> list[dict]:
        with self.db.verbinding() as con:
            if gesprek:
                rijen = con.execute(
                    "SELECT * FROM gebeurtenissen WHERE gesprek = ? ORDER BY id DESC LIMIT ?", (gesprek, limiet)
                ).fetchall()
            else:
                rijen = con.execute("SELECT * FROM gebeurtenissen ORDER BY id DESC LIMIT ?", (limiet,)).fetchall()
        return [dict(r) for r in reversed(rijen)]

    def opruimen(self, dagen: int = 180) -> int:
        grens = (date.today() - timedelta(days=dagen)).isoformat()
        with self.db.verbinding() as con:
            weg = con.execute("DELETE FROM gebeurtenissen WHERE tijd < ?", (grens,)).rowcount
            con.execute("DELETE FROM metingen WHERE tijd < ?", (grens,))
        return weg

    # ---- verbruik --------------------------------------------------------------------
    def verbruik(self, model: str, usage: Any, doel: str, ms: int | None = None) -> float:
        inp = getattr(usage, "input_tokens", 0) or 0
        out = getattr(usage, "output_tokens", 0) or 0
        cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cr = getattr(usage, "cache_read_input_tokens", 0) or 0
        kosten = bereken_kosten(model, inp, out, cw, cr)
        with self.db.verbinding() as con:
            con.execute(
                "INSERT INTO verbruik (tijd, datum, model, doel, input_tokens, output_tokens, cache_write,"
                " cache_read, kosten_usd, ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (nu_iso(), date.today().isoformat(), model, doel, inp, out, cw, cr, kosten, ms),
            )
        return kosten

    def kosten_per_dag(self, dagen: int = 30) -> list[dict]:
        grens = (date.today() - timedelta(days=dagen - 1)).isoformat()
        with self.db.verbinding() as con:
            rijen = con.execute(
                "SELECT datum, COUNT(*) AS aanroepen, SUM(input_tokens) AS input_tokens,"
                " SUM(output_tokens) AS output_tokens, SUM(cache_write) AS cache_write,"
                " SUM(cache_read) AS cache_read, SUM(kosten_usd) AS kosten_usd"
                " FROM verbruik WHERE datum >= ? GROUP BY datum ORDER BY datum DESC",
                (grens,),
            ).fetchall()
        return [dict(r) for r in rijen]

    # ---- metingen (milliseconden per stap van de spraakketen) -----------------------
    def meting(self, stap: str, ms: int, details: Any = None) -> None:
        with self.db.verbinding() as con:
            con.execute(
                "INSERT INTO metingen (tijd, stap, ms, details) VALUES (?, ?, ?, ?)",
                (nu_iso(), stap, int(ms), json.dumps(details, ensure_ascii=False) if details else None),
            )

    def metingen_samenvatting(self, dagen: int = 7) -> list[dict]:
        grens = (date.today() - timedelta(days=dagen)).isoformat()
        with self.db.verbinding() as con:
            rijen = con.execute(
                "SELECT stap, COUNT(*) AS aantal, CAST(AVG(ms) AS INTEGER) AS gemiddeld,"
                " MIN(ms) AS snelst, MAX(ms) AS traagst FROM metingen WHERE tijd >= ?"
                " GROUP BY stap ORDER BY stap",
                (grens,),
            ).fetchall()
        return [dict(r) for r in rijen]
