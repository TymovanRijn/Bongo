"""Het geheugen: data/over_mij.md. Gaat volledig mee in de systeemprompt."""

from __future__ import annotations

import re
import threading
from datetime import date
from pathlib import Path

SECTIE = "## Door de assistent onthouden"

STANDAARD = """# Over Tymo

Dit bestand is het geheugen van de assistent. Het gaat volledig mee in elk gesprek.
Tymo kan het hier of in de webapp aanpassen. Houd het kort: alles hierin kost bij elke vraag tokens.

## Basis

- Naam: Tymo
- Taal: Nederlands

## Voorkeuren

- (bijvoorbeeld: hoe lang een afspraak standaard duurt, wanneer je liever geen afspraken hebt)

## Door de assistent onthouden
"""


class Geheugen:
    def __init__(self, pad: Path):
        self.pad = Path(pad)
        # RLock: voeg_toe en verwijder houden het slot vast en roepen daarbinnen schrijf() aan.
        self._slot = threading.RLock()
        if not self.pad.exists():
            self.pad.parent.mkdir(parents=True, exist_ok=True)
            self.pad.write_text(STANDAARD, encoding="utf-8")

    def lees(self) -> str:
        return self.pad.read_text(encoding="utf-8")

    def versie(self) -> float:
        """Verandert als het bestand verandert (ook als Tymo het met de hand aanpast)."""
        try:
            return self.pad.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def schrijf(self, tekst: str) -> None:
        with self._slot:
            vorige = self.pad.with_suffix(".md.vorige")
            if self.pad.exists():
                vorige.write_text(self.lees(), encoding="utf-8")
            tmp = self.pad.with_suffix(".tmp")
            tmp.write_text(tekst if tekst.endswith("\n") else tekst + "\n", encoding="utf-8")
            tmp.replace(self.pad)

    def voeg_toe(self, feit: str) -> str:
        feit = " ".join(feit.split())
        regel = f"- {feit} ({date.today().isoformat()})"
        # Lezen, aanpassen en schrijven onder één slot: anders kunnen twee goedkeuringen
        # tegelijk allebei de oude tekst lezen, en overschrijft de tweede het feit van de eerste.
        with self._slot:
            regels = self.lees().rstrip("\n").splitlines()
            if SECTIE not in regels:
                regels += ["", SECTIE]
            # Invoegen aan het eind van de sectie, vóór een eventuele volgende kop.
            eind = len(regels)
            for i in range(regels.index(SECTIE) + 1, len(regels)):
                if regels[i].startswith("#"):
                    eind = i
                    break
            while eind > 0 and not regels[eind - 1].strip() and regels[eind - 1] != SECTIE:
                eind -= 1
            regels.insert(eind, regel)
            self.schrijf("\n".join(regels) + "\n")
        return regel

    @staticmethod
    def _kern(regel: str) -> str:
        regel = " ".join(regel.split()).lower()
        regel = re.sub(r"^[-*]\s*", "", regel)
        return re.sub(r"\s*\(\d{4}-\d{2}-\d{2}\)$", "", regel).rstrip(".")

    def zoek_regel(self, feit: str) -> str | None:
        """Vind de opsommingsregel die bij `feit` hoort (zonder streepje en datum, hoofdletterongevoelig)."""
        doel = self._kern(feit)
        if len(doel) < 3:
            return None
        for regel in self.lees().splitlines():
            if regel.lstrip().startswith(("-", "*")) and self._kern(regel) == doel:
                return regel
        return None

    def verwijder(self, feit: str) -> str:
        with self._slot:
            regel = self.zoek_regel(feit)
            if regel is None:
                raise ValueError(f"Regel niet gevonden in het geheugen: {feit}")
            regels = self.lees().splitlines()
            regels.remove(regel)
            self.schrijf("\n".join(regels) + "\n")
        return regel
