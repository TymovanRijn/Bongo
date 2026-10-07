"""Alles aan elkaar knopen. De kern, de tests en scripts gebruiken dit."""

from __future__ import annotations

import logging
import logging.handlers
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import anthropic

from .brain import Brain
from .calendar_backend import AgendaBackend, maak_agenda
from .config import Instellingen
from .db import Database
from .executors import maak_uitvoerders
from .geheugen import Geheugen
from .logboek import Logboek
from .tools import ToolUitvoerder
from .wachtrij import Wachtrij


@dataclass
class Onderdelen:
    inst: Instellingen
    db: Database
    logboek: Logboek
    geheugen: Geheugen
    agenda: AgendaBackend
    wachtrij: Wachtrij
    tools: ToolUitvoerder
    brain: Brain


def maak_onderdelen(inst: Instellingen, client=..., agenda: AgendaBackend | None = None, bij_wijziging=None) -> Onderdelen:
    """`client=...` betekent: maak een echte Anthropic-client als er een sleutel is."""
    db = Database(inst.db_pad)
    logboek = Logboek(db)
    geheugen = Geheugen(inst.geheugen_pad)
    agenda = agenda or maak_agenda(inst)
    wachtrij = Wachtrij(db, maak_uitvoerders(agenda, geheugen), bij_wijziging=bij_wijziging)
    tools = ToolUitvoerder(agenda, wachtrij, geheugen, ZoneInfo(inst.tijdzone))
    if client is ...:
        client = anthropic.Anthropic(api_key=inst.anthropic_api_key, timeout=60.0) if inst.anthropic_api_key else None
    brain = Brain(client, inst, tools, geheugen, logboek)
    return Onderdelen(inst, db, logboek, geheugen, agenda, wachtrij, tools, brain)


def stel_logging_in(inst: Instellingen, naam: str, console_niveau: int = logging.INFO) -> None:
    """Naar de console (journald) en naar een bestand van maximaal 1 MB x 5.

    De CLI zet `console_niveau` hoger, zodat logregels niet door het gesprek heen lopen.
    """
    inst.log_dir.mkdir(parents=True, exist_ok=True)
    opmaak = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    bestand = logging.handlers.RotatingFileHandler(inst.log_dir / f"{naam}.log", maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    bestand.setFormatter(opmaak)
    console = logging.StreamHandler()
    console.setLevel(console_niveau)
    console.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [bestand, console]
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
