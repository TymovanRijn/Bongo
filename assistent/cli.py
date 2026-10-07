"""Praat met Bongo in de terminal: `python -m assistent`.

Zo kun je het brein, de agenda en de wachtrij gebruiken voordat er een scherm, een
microfoon of een webapp is. Opdrachten beginnen met een schuine streep (typ /hulp).
Met een vraag erachter stelt hij die ene vraag en stopt hij weer:
`python -m assistent "wat heb ik morgen?"`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from zoneinfo import ZoneInfo

from .brain import BreinFout
from .calendar_backend import AgendaFout
from .config import laad_instellingen
from .opbouw import Onderdelen, maak_onderdelen, stel_logging_in
from .overzicht import agenda_per_dag, maak_ochtendoverzicht
from .wachtrij import Voorstel, WachtrijFout

HULP = """Opdrachten:
  /ja <nummer>    keur een voorstel goed
  /nee <nummer>   wijs een voorstel af
  /wachtrij       laat de open voorstellen zien
  /agenda         afspraken van vandaag en morgen
  /geheugen       laat zien wat {naam} over je weet
  /ochtend        maak het ochtendoverzicht
  /kosten         wat Claude de afgelopen week kostte
  /nieuw          begin een nieuw gesprek
  /stop           afsluiten (of Ctrl+D)
Al het andere is een vraag aan {naam}."""


class Terminal:
    """Alles behalve het lezen en printen zelf, zodat de tests het ook kunnen gebruiken."""

    def __init__(self, o: Onderdelen):
        self.o = o
        self.naam = o.inst.assistent_naam
        self.tz = ZoneInfo(o.inst.tijdzone)

    def verwerk(self, regel: str) -> str | None:
        """Geeft de tekst die op het scherm moet, of None om te stoppen."""
        regel = regel.strip()
        if not regel:
            return ""
        if not regel.startswith("/"):
            return self._vraag(regel)

        opdracht, _, rest = regel[1:].partition(" ")
        opdracht = opdracht.lower()
        if opdracht in ("stop", "exit", "quit"):
            return None
        actie = {
            "ja": self._ja,
            "nee": self._nee,
            "wachtrij": self._wachtrij,
            "agenda": self._agenda,
            "geheugen": self._geheugen,
            "ochtend": self._ochtend,
            "kosten": self._kosten,
            "nieuw": self._nieuw,
            "hulp": self._hulp,
            "help": self._hulp,
        }.get(opdracht)
        if actie is None:
            return f"Onbekende opdracht /{opdracht}. Typ /hulp voor het overzicht."
        try:
            return actie(rest.strip())
        except (WachtrijFout, AgendaFout) as e:
            return f"Dat lukt niet: {e}"

    # ---- een vraag aan het brein -----------------------------------------------------
    def _vraag(self, tekst: str) -> str:
        try:
            antwoord = self.o.brain.vraag(tekst, bron="cli")
        except BreinFout as e:
            # In de terminal ook de technische oorzaak: wie hier zit, wil weten wát er misging.
            return f"{self.naam}: {e.melding}" + (f"\n   (technisch: {e.technisch})" if e.technisch != e.melding else "")
        regels = [f"{self.naam}: {antwoord.tekst}"]
        regels += [self._als_regel(self.o.wachtrij.get(vid)) for vid in antwoord.voorstel_ids]
        regels.append(f"   ({antwoord.ms / 1000:.1f} s, $ {antwoord.kosten_usd:.4f})")
        return "\n".join(regels)

    @staticmethod
    def _als_regel(v: Voorstel) -> str:
        return f"   [#{v.id}] {v.samenvatting}   (/ja {v.id} of /nee {v.id})"

    # ---- de wachtrij -----------------------------------------------------------------
    def _ja(self, rest: str) -> str:
        if not rest:
            return self._welk_nummer("ja")
        v = self.o.wachtrij.approve(self._nummer(rest), via="cli")
        if v.status == "uitgevoerd":
            return f"Gedaan. {v.resultaat}"
        return f"Goedgekeurd, maar het uitvoeren mislukte: {v.resultaat}"

    def _nee(self, rest: str) -> str:
        if not rest:
            return self._welk_nummer("nee")
        v = self.o.wachtrij.reject(self._nummer(rest), via="cli")
        return f"Afgewezen: {v.samenvatting}"

    def _welk_nummer(self, opdracht: str) -> str:
        # Bewust altijd met nummer: zo keur je precies het voorstel goed dat je gezien hebt.
        open_ = self.o.wachtrij.open()
        if not open_:
            return "Er staan geen voorstellen open."
        return f"Welk voorstel? Bijvoorbeeld /{opdracht} {open_[-1].id}.\n" + self._wachtrij("")

    @staticmethod
    def _nummer(rest: str) -> int:
        try:
            return int(rest.lstrip("#"))
        except ValueError:
            raise WachtrijFout(f"'{rest}' is geen nummer") from None

    def _wachtrij(self, _: str) -> str:
        open_ = self.o.wachtrij.open()
        if not open_:
            return "Er staan geen voorstellen open."
        return "Open voorstellen:\n" + "\n".join(self._als_regel(v) for v in open_)

    # ---- overige opdrachten ----------------------------------------------------------
    def _agenda(self, _: str) -> str:
        regels = []
        for dag in agenda_per_dag(self.o.agenda, self.tz, dagen=2):
            regels.append(f"{dag['label']} ({dag['lang']}):")
            if not dag["afspraken"]:
                regels.append("   niets")
            for a in dag["afspraken"]:
                tijd = a["tijd"] + (f"-{a['eind']}" if a["eind"] else "")
                regels.append(f"   {tijd:11}  {a['titel']}" + (f" ({a['locatie']})" if a["locatie"] else ""))
        return "\n".join(regels)

    def _geheugen(self, _: str) -> str:
        return f"{self.o.geheugen.lees().rstrip()}\n\n(dit staat in {self.o.geheugen.pad})"

    def _ochtend(self, _: str) -> str:
        tekst, kosten = maak_ochtendoverzicht(self.o.brain, self.o.agenda, self.tz, self.o.inst.gebruiker_naam)
        return f"{self.naam}: {tekst}\n   ($ {kosten:.4f})"

    def _kosten(self, _: str) -> str:
        dagen = self.o.logboek.kosten_per_dag(7)
        if not dagen:
            return "De afgelopen week heeft Claude nog niets gekost."
        regels = ["datum        aanroepen   kosten"]
        regels += [f"{d['datum']}   {d['aanroepen']:9}   $ {d['kosten_usd']:.4f}" for d in dagen]
        regels.append(f"totaal                   $ {sum(d['kosten_usd'] for d in dagen):.4f}")
        return "\n".join(regels)

    def _nieuw(self, _: str) -> str:
        self.o.brain.nieuw_gesprek("handmatig, via de terminal")
        return "Nieuw gesprek begonnen."

    def _hulp(self, _: str) -> str:
        return HULP.format(naam=self.naam)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assistent", description="Praat met Bongo in de terminal.")
    parser.add_argument("vraag", nargs="*", help="stel deze ene vraag (of opdracht) en stop daarna")
    args = parser.parse_args(argv)

    inst = laad_instellingen()
    # Waarschuwingen staan al in het gesprek zelf (de technische regel onder een fout) en in data/logs/.
    stel_logging_in(inst, "cli", console_niveau=logging.ERROR)
    try:
        o = maak_onderdelen(inst)
    except AgendaFout as e:
        print(f"{inst.assistent_naam} kan niet starten: {e}", file=sys.stderr)
        return 1
    terminal = Terminal(o)
    for v in o.wachtrij.herstel_onderbroken():
        print(f"Let op: voorstel #{v.id} werd onderbroken door een herstart en staat nu op '{v.status}': {v.samenvatting}")

    if args.vraag:
        print(terminal.verwerk(" ".join(args.vraag)) or "")
        return 0

    try:
        import readline  # noqa: F401  (pijltjestoetsen en eerdere regels bij input())
    except ImportError:
        pass
    print(f"Hoi! Ik ben {inst.assistent_naam}. Typ /hulp voor de opdrachten en /stop om te stoppen.")
    if o.brain.client is None:
        print("Let op: er staat geen ANTHROPIC_API_KEY in .env. Vragen lukken nog niet, /agenda en /wachtrij wel.")
    while True:
        try:
            regel = input(f"{inst.gebruiker_naam.lower()}> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        try:
            uit = terminal.verwerk(regel)
        except KeyboardInterrupt:  # Ctrl+C terwijl hij nadenkt: alleen deze vraag stoppen
            print("\n(onderbroken)")
            continue
        if uit is None:
            return 0
        if uit:
            print(uit)
