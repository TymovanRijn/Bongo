"""De wachtrij: alles met gevolgen wacht hier op Tymo's bevestiging.

Claude kan alleen voorstellen *aanmaken*. Uitvoeren gebeurt uitsluitend via
`approve()`, en die wordt alleen aangeroepen door een mens: een tik op het scherm,
een knop in de webapp, `/ja` in de CLI, of (als dat aan staat) een hardop "ja".
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

from .db import Database, nu_iso

log = logging.getLogger(__name__)

Uitvoerder = Callable[[dict], str]


class WachtrijFout(Exception):
    pass


@dataclass
class Voorstel:
    id: int
    soort: str
    samenvatting: str
    gegevens: dict
    status: str
    resultaat: str | None
    bron: str | None
    aangemaakt: str
    afgehandeld: str | None
    afgehandeld_via: str | None

    @classmethod
    def uit_rij(cls, rij) -> "Voorstel":
        d = dict(rij)
        d["gegevens"] = json.loads(d["gegevens"])
        return cls(**d)

    def als_dict(self) -> dict:
        return dict(self.__dict__)


class Wachtrij:
    def __init__(self, db: Database, uitvoerders: dict[str, Uitvoerder], bij_wijziging: Callable[[], None] | None = None):
        self.db = db
        self.uitvoerders = uitvoerders
        self.bij_wijziging = bij_wijziging

    def _gewijzigd(self) -> None:
        if self.bij_wijziging:
            try:
                self.bij_wijziging()
            except Exception:  # een melding mag de wachtrij nooit breken
                log.exception("bij_wijziging faalde")

    def voorstel(self, soort: str, samenvatting: str, gegevens: dict, bron: str | None = None) -> Voorstel:
        if soort not in self.uitvoerders:
            raise WachtrijFout(f"onbekende soort voorstel: {soort}")
        with self.db.verbinding() as con:
            cur = con.execute(
                "INSERT INTO voorstellen (soort, samenvatting, gegevens, bron, aangemaakt) VALUES (?, ?, ?, ?, ?)",
                (soort, samenvatting, json.dumps(gegevens, ensure_ascii=False), bron, nu_iso()),
            )
            nieuw_id = cur.lastrowid
        self._gewijzigd()
        return self.get(nieuw_id)

    def get(self, voorstel_id: int) -> Voorstel:
        with self.db.verbinding() as con:
            rij = con.execute("SELECT * FROM voorstellen WHERE id = ?", (voorstel_id,)).fetchone()
        if rij is None:
            raise WachtrijFout(f"voorstel #{voorstel_id} bestaat niet")
        return Voorstel.uit_rij(rij)

    def open(self) -> list[Voorstel]:
        with self.db.verbinding() as con:
            rijen = con.execute("SELECT * FROM voorstellen WHERE status = 'open' ORDER BY id").fetchall()
        return [Voorstel.uit_rij(r) for r in rijen]

    def afgehandeld(self, limiet: int = 30) -> list[Voorstel]:
        with self.db.verbinding() as con:
            rijen = con.execute(
                "SELECT * FROM voorstellen WHERE status != 'open' ORDER BY id DESC LIMIT ?", (limiet,)
            ).fetchall()
        return [Voorstel.uit_rij(r) for r in rijen]

    def approve(self, voorstel_id: int, via: str = "onbekend") -> Voorstel:
        """Keur een voorstel goed en voer het uit. Precies één keer, ook bij twee tikken tegelijk."""
        with self.db.verbinding() as con:
            geclaimd = con.execute(
                "UPDATE voorstellen SET status = 'bezig', afgehandeld_via = ? WHERE id = ? AND status = 'open'",
                (via, voorstel_id),
            ).rowcount
        if not geclaimd:
            huidig = self.get(voorstel_id)
            raise WachtrijFout(f"voorstel #{voorstel_id} is niet meer open (status: {huidig.status})")

        voorstel = self.get(voorstel_id)
        try:
            resultaat = self.uitvoerders[voorstel.soort](voorstel.gegevens)
            status = "uitgevoerd"
        except Exception as e:
            log.exception("uitvoeren van voorstel #%s mislukt", voorstel_id)
            resultaat = f"Mislukt: {e}"
            status = "mislukt"
        with self.db.verbinding() as con:
            con.execute(
                "UPDATE voorstellen SET status = ?, resultaat = ?, afgehandeld = ? WHERE id = ?",
                (status, resultaat, nu_iso(), voorstel_id),
            )
        self._gewijzigd()
        return self.get(voorstel_id)

    def reject(self, voorstel_id: int, via: str = "onbekend") -> Voorstel:
        with self.db.verbinding() as con:
            geweigerd = con.execute(
                "UPDATE voorstellen SET status = 'afgewezen', afgehandeld = ?, afgehandeld_via = ?"
                " WHERE id = ? AND status = 'open'",
                (nu_iso(), via, voorstel_id),
            ).rowcount
        if not geweigerd:
            huidig = self.get(voorstel_id)
            raise WachtrijFout(f"voorstel #{voorstel_id} is niet meer open (status: {huidig.status})")
        self._gewijzigd()
        return self.get(voorstel_id)
