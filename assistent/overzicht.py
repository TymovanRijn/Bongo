"""Agenda voor het scherm en het ochtendoverzicht."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .brain import Brain, BreinFout
from .calendar_backend import AgendaBackend
from .tools import datum_uitgeschreven, tijd_uitgeschreven

log = logging.getLogger(__name__)


def agenda_per_dag(agenda: AgendaBackend, tz: ZoneInfo, dagen: int = 2, vanaf: date | None = None) -> list[dict]:
    """[{datum, label, afspraken: [...]}, ...] voor vandaag en de volgende dagen."""
    vanaf = vanaf or datetime.now(tz).date()
    begin = datetime.combine(vanaf, time.min, tz)
    eind = begin + timedelta(days=dagen)
    afspraken = agenda.afspraken(begin, eind)
    uit = []
    for i in range(dagen):
        dag = vanaf + timedelta(days=i)
        dag_begin = datetime.combine(dag, time.min, tz)
        dag_eind = dag_begin + timedelta(days=1)
        items = []
        for a in afspraken:
            if a.start < dag_eind and a.eind > dag_begin:
                items.append(
                    {
                        "titel": a.titel,
                        "tijd": "hele dag" if a.hele_dag else tijd_uitgeschreven(max(a.start, dag_begin)),
                        "eind": None if a.hele_dag else tijd_uitgeschreven(a.eind) if a.eind <= dag_eind else None,
                        "locatie": a.locatie,
                        "hele_dag": a.hele_dag,
                        "start_iso": a.start.isoformat(),
                        "eind_iso": a.eind.isoformat(),
                    }
                )
        label = {0: "Vandaag", 1: "Morgen"}.get(i, datum_uitgeschreven(dag).split(" ")[0].capitalize())
        uit.append({"datum": dag.isoformat(), "label": label, "lang": datum_uitgeschreven(dag), "afspraken": items})
    return uit


def eenvoudig_overzicht(dag: dict, naam: str) -> str:
    """Zonder Claude: werkt ook als het internet of de API het niet doet."""
    items = dag["afspraken"]
    groet = f"Goedemorgen {naam}! Het is {dag['lang']}."
    if not items:
        return f"{groet} Je agenda is vandaag leeg."
    delen = [f"{a['titel']} ({a['tijd']})" for a in items]
    if len(delen) == 1:
        return f"{groet} Je hebt vandaag één afspraak: {delen[0]}."
    return f"{groet} Je hebt vandaag {len(delen)} afspraken: " + ", ".join(delen[:-1]) + f" en {delen[-1]}."


def maak_ochtendoverzicht(
    brain: Brain, agenda: AgendaBackend, tz: ZoneInfo, naam: str, vanaf: date | None = None
) -> tuple[str, float]:
    dagen = agenda_per_dag(agenda, tz, dagen=2, vanaf=vanaf)
    vandaag, morgen = dagen[0], dagen[1]
    regels = [f"- {a['tijd']}{'-' + a['eind'] if a['eind'] else ''}: {a['titel']}" + (f" ({a['locatie']})" if a["locatie"] else "")
              for a in vandaag["afspraken"]]
    vroeg_morgen = [a for a in morgen["afspraken"] if not a["hele_dag"] and a["tijd"] < "10:00"]
    opdracht = (
        f"Maak het ochtendoverzicht voor {naam}. Vandaag is {vandaag['lang']}.\n"
        "Afspraken vandaag:\n" + ("\n".join(regels) if regels else "- geen") + "\n"
        + ("Morgen vroeg: " + ", ".join(f"{a['tijd']} {a['titel']}" for a in vroeg_morgen) + "\n" if vroeg_morgen else "")
        + "Schrijf het als een korte, vriendelijke ochtendgroet van hooguit vijf zinnen die je hardop kunt voorlezen. "
        "Noem de afspraken in volgorde, wijs op krappe overgangen of een volle dag, en verzin niets dat hier niet staat."
    )
    try:
        return brain.eenmalig(opdracht, doel="ochtendoverzicht")
    except BreinFout as e:
        log.warning("ochtendoverzicht via Claude mislukt (%s), ik gebruik de eenvoudige versie", e.technisch)
        return eenvoudig_overzicht(vandaag, naam), 0.0
