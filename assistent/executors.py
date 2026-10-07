"""Wat er gebeurt nadat Tymo een voorstel heeft goedgekeurd. Alleen de wachtrij roept dit aan.

Per soort voorstel zijn er twee functies:
- een uitvoerder, die het voorstel echt uitvoert;
- een controle, die na een stroomstoring nagaat of het uitvoeren al gelukt was
  (True), zeker niet gelukt was (False) of dat dat niet te zeggen is (None).
"""

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
            uid=g.get("uid"),
            agenda=g.get("agenda"),  # leeg bij voorstellen van voor de agendakeuze: dan de standaard
        )
        return f"Toegevoegd aan {g.get('agenda') or 'de agenda'} (uid {uid})"

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


def maak_controles(agenda: AgendaBackend, geheugen: Geheugen) -> dict:
    def afspraak(g: dict) -> bool | None:
        if not g.get("uid"):
            return None  # een voorstel van voor de uid in de gegevens zat
        start, eind = datetime.fromisoformat(g["start"]), datetime.fromisoformat(g["eind"])
        return any(a.uid == g["uid"] for a in agenda.afspraken(start, eind))

    def onthouden(g: dict) -> bool:
        return geheugen.zoek_regel(g["feit"]) is not None

    def vergeten(g: dict) -> bool:
        return geheugen.zoek_regel(g["feit"]) is None

    return {"afspraak": afspraak, "onthouden": onthouden, "vergeten": vergeten}
