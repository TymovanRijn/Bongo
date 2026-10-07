"""Wat er gebeurt nadat Tymo een voorstel heeft goedgekeurd. Alleen de wachtrij roept dit aan."""

from __future__ import annotations

from datetime import datetime

from .calendar_backend import AgendaBackend
from .geheugen import Geheugen


def maak_uitvoerders(agenda: AgendaBackend, geheugen: Geheugen, bij_geheugen_wijziging=None) -> dict:
    def afspraak(g: dict) -> str:
        uid = agenda.voeg_toe(
            titel=g["titel"],
            start=datetime.fromisoformat(g["start"]),
            eind=datetime.fromisoformat(g["eind"]),
            locatie=g.get("locatie"),
            notitie=g.get("notitie"),
            hele_dag=bool(g.get("hele_dag")),
        )
        return f"Toegevoegd aan de agenda (uid {uid})"

    def onthouden(g: dict) -> str:
        regel = geheugen.voeg_toe(g["feit"])
        if bij_geheugen_wijziging:
            bij_geheugen_wijziging()
        return f"Onthouden: {regel}"

    def vergeten(g: dict) -> str:
        regel = geheugen.verwijder(g["feit"])
        if bij_geheugen_wijziging:
            bij_geheugen_wijziging()
        return f"Vergeten: {regel}"

    return {"afspraak": afspraak, "onthouden": onthouden, "vergeten": vergeten}
