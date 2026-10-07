"""Knip binnenkomende tekst in zinnen, zodat Piper kan beginnen zodra de eerste zin af is.

Claude stuurt zijn antwoord in stukjes van een paar woorden. Wacht je op het hele antwoord,
dan duurt het langer voor Bongo iets zegt; spreek je elk stukje los uit, dan klinkt het
gehakt en verkeerd beklemtoond. Een hele zin is het kleinste stuk dat natuurlijk klinkt.
"""

from __future__ import annotations

import re

# Een punt, uitroepteken, vraagteken of beletselteken, eventueel gevolgd door een
# aanhalingsteken of haakje, en dan witruimte: daar eindigt een zin.
EINDE = re.compile(r"[.!?…]+[\"'’”)\]]*\s+|\n+")

# Na deze woorden is een punt geen einde van de zin.
AFKORTINGEN = {
    "bijv", "bv", "o.a", "d.w.z", "m.a.w", "z.s.m", "ca", "nr", "dr", "mr", "ir", "ing",
    "st", "etc", "enz", "evt", "incl", "excl", "max", "min", "o.b.v", "t.o.v", "i.p.v", "n.a.v",
    "a.s", "m.b.t", "t.e.m", "feb", "mrt", "apr", "jun", "jul", "aug", "sep", "sept", "okt", "nov", "dec",
}


class Zinnensplitser:
    def __init__(self):
        self._buffer = ""

    def voeg_toe(self, stukje: str) -> list[str]:
        """Voeg tekst toe. Geeft de zinnen terug die nu af zijn (vaak geen, soms meer dan één)."""
        self._buffer += stukje
        zinnen = []
        begin = 0
        for einde in EINDE.finditer(self._buffer):
            zin = self._buffer[begin : einde.end()].strip()
            if einde.group().startswith((".",)) and self._is_afkorting(zin):
                continue
            if zin:
                zinnen.append(zin)
            begin = einde.end()
        self._buffer = self._buffer[begin:]
        return zinnen

    def klaar(self) -> list[str]:
        """Het bericht is af: wat er nog over is, is ook een zin (bijvoorbeeld zonder punt)."""
        rest, self._buffer = self._buffer.strip(), ""
        return [rest] if rest else []

    @staticmethod
    def _is_afkorting(zin: str) -> bool:
        laatste = zin.rstrip(".\"'’”)] ").rsplit(" ", 1)[-1].lower()
        return laatste in AFKORTINGEN or (len(laatste) == 1 and laatste.isalpha())
