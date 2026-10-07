"""De spraakketen: tik op het gezicht -> luisteren -> verstaan -> nadenken -> praten.

Alles gebeurt op de Pi zelf, behalve het nadenken (Claude). Er gaat dus nooit geluid naar
internet, alleen de tekst die Whisper ervan maakte. En de microfoon staat alleen aan tussen
een tik op het scherm en het einde van je zin: Bongo luistert niet stiekem mee.

Elke stap wordt gemeten (tabel `metingen`, zie Meer > Kosten in de webapp), zodat je ziet
waar de tijd heen gaat. De belangrijkste: `tot_geluid`, van het einde van je zin tot het
eerste geluid van Bongo. Dat is hoe lang het voor jou voelt.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Iterable, Iterator, Protocol

from ..brain import BreinFout

log = logging.getLogger(__name__)

NIET_VERSTAAN = "Sorry, dat verstond ik niet."
NOG_LADEN = "Ik ben mijn oren en stem nog aan het klaarmaken. Probeer het zo nog eens."


class Microfoon(Protocol):
    def neem_op(self): ...
    def stop(self) -> None: ...


class Herkenner(Protocol):
    def herken(self, audio) -> str: ...
    def warm_op(self) -> None: ...


class Stem(Protocol):
    def zinnen(self, tekst: str) -> Iterable[tuple[bytes, int]]: ...
    def warm_op(self) -> None: ...


class Luidspreker(Protocol):
    def speel(self, stukken: Iterable[tuple[bytes, int]]) -> bool: ...
    def stop(self) -> None: ...


def _ms(begin: float) -> int:
    return int((time.monotonic() - begin) * 1000)


class Spraak:
    def __init__(
        self,
        brain,
        logboek,
        microfoon: Microfoon,
        herkenner: Herkenner,
        stem: Stem,
        luidspreker: Luidspreker,
        bij_wijziging: Callable[[], None] | None = None,
        piep: tuple[bytes, int] | None = None,
    ):
        self.brain, self.logboek = brain, logboek
        self.microfoon, self.herkenner, self.stem, self.luidspreker = microfoon, herkenner, stem, luidspreker
        self.bij_wijziging = bij_wijziging or (lambda: None)
        self.piep = piep
        self.toestand = "rust"  # rust | luisteren | denken | praten
        self.ondertitel = ""  # wat Bongo zegt (of net zei)
        self.melding = ""  # wat er misging, voor op het scherm
        self.klaar = False  # zijn de modellen geladen?
        self._laden = False  # worden ze nu geladen (de eerste keer: gedownload)?
        self._slot = threading.Lock()
        self._draad: threading.Thread | None = None

    # ---- voor de kern en het scherm ------------------------------------------------------
    def status(self) -> dict:
        return {"toestand": self.toestand, "ondertitel": self.ondertitel, "melding": self.melding, "klaar": self.klaar}

    def tik(self) -> str:
        """Eén knop voor alles: in rust begint hij te luisteren, tijdens het luisteren is je
        zin klaar, tijdens het praten is hij meteen stil."""
        with self._slot:
            if self.toestand == "rust" and self._laden:
                # Anders hangt hij minutenlang op "denken" terwijl Whisper nog downloadt.
                self.melding = NOG_LADEN
                self.bij_wijziging()
            elif self.toestand == "rust":
                self._start(self._beurt, "luisteren")
            elif self.toestand == "luisteren":
                self.microfoon.stop()
            elif self.toestand == "praten":
                self.luidspreker.stop()
            return self.toestand

    def zeg(self, tekst: str) -> bool:
        """Iets uitspreken zonder dat erom gevraagd is (het ochtendoverzicht). Alleen als hij niets doet."""
        with self._slot:
            if self.toestand != "rust":
                return False
            self._start(lambda: self._praat(tekst), "praten")
            return True

    def warm_op(self) -> None:
        """Laad de modellen op de achtergrond. De eerste keer worden ze gedownload: dat kan minuten duren."""

        def laden():
            begin = time.monotonic()
            try:
                self.herkenner.warm_op()
                self.stem.warm_op()
                self.klaar = True
                self.melding = ""
                log.info("spraak klaar (modellen geladen in %.1f s)", (time.monotonic() - begin))
            except Exception as e:
                log.exception("spraakmodellen laden mislukt")
                self.melding = f"Spraak werkt niet: {e}"
            finally:
                self._laden = False
            self.bij_wijziging()

        self._laden = True
        threading.Thread(target=laden, name="spraak-laden", daemon=True).start()

    def wacht(self, timeout: float | None = None) -> None:
        """Wacht tot de huidige beurt klaar is (voor de tests)."""
        if self._draad is not None:
            self._draad.join(timeout)

    # ---- de beurt ----------------------------------------------------------------------
    def _start(self, werk: Callable[[], None], eerste_toestand: str) -> None:
        def draai():
            try:
                werk()
            except Exception as e:
                log.exception("spraakbeurt mislukt")
                self.melding = str(e) or "Er ging iets mis met de spraak."
            finally:
                self._zet("rust")

        self.toestand = eerste_toestand  # meteen, zodat een tweede tik niet nog een beurt start
        self._draad = threading.Thread(target=draai, name="spraak", daemon=True)
        self._draad.start()
        self.bij_wijziging()

    def _zet(self, toestand: str, ondertitel: str | None = None) -> None:
        self.toestand = toestand
        if ondertitel is not None:
            self.ondertitel = ondertitel
        self.bij_wijziging()

    def _meet(self, stap: str, ms: int, details: dict | None = None) -> None:
        try:
            self.logboek.meting(stap, ms, details)
        except Exception:
            log.exception("meting opslaan mislukt")

    def _beurt(self) -> None:
        self.melding = ""
        self._zet("luisteren", "")
        if self.piep:
            self.luidspreker.speel([self.piep])  # nu mag je praten
        begin = time.monotonic()
        audio = self.microfoon.neem_op()
        self._meet("opnemen", _ms(begin))
        if audio is None:
            return  # niets gezegd (of meteen weer getikt)
        einde_zin = time.monotonic()

        self._zet("denken")
        begin = time.monotonic()
        tekst = self.herkenner.herken(audio)
        self._meet("verstaan", _ms(begin), {"tekst": tekst, "seconden_geluid": round(len(audio) / 16_000, 1)})
        if not tekst:
            self._praat(NIET_VERSTAAN, einde_zin)
            return

        begin = time.monotonic()
        try:
            antwoord = self.brain.vraag(tekst, bron="spraak").tekst
        except BreinFout as e:
            antwoord = e.melding
        self._meet("nadenken", _ms(begin))
        self._praat(antwoord, einde_zin)

    def _praat(self, tekst: str, einde_zin: float | None = None) -> None:
        self._zet("praten", tekst)
        begin = time.monotonic()
        afgemaakt = self.luidspreker.speel(self._gemeten(self.stem.zinnen(tekst), einde_zin))
        self._meet("praten", _ms(begin), {"afgemaakt": afgemaakt, "tekens": len(tekst)})

    def _gemeten(self, zinnen: Iterable[tuple[bytes, int]], einde_zin: float | None) -> Iterator[tuple[bytes, int]]:
        """Geef de zinnen door, en meet hoe lang het duurde tot de eerste klonk."""
        begin = time.monotonic()
        for i, zin in enumerate(zinnen):
            if i == 0:
                self._meet("eerste_zin_gemaakt", _ms(begin))
                if einde_zin is not None:
                    self._meet("tot_geluid", _ms(einde_zin))
            yield zin


def maak_spraak(o, bij_wijziging: Callable[[], None] | None = None) -> Spraak | None:
    """De echte spraakketen, of None als spraak uit staat of de pakketten ontbreken."""
    inst = o.inst
    if not inst.spraak:
        return None
    try:
        from .audio import Luidspreker as AlsaLuidspreker
        from .audio import Microfoon as AlsaMicrofoon
        from .audio import piep
        from .stem import PiperStem
        from .verstaan import WhisperHerkenner
    except ImportError as e:
        log.warning("spraak staat uit: het pakket '%s' ontbreekt (.venv/bin/pip install -r requirements.txt)", e.name)
        return None
    modellen = inst.data_dir / "modellen"
    return Spraak(
        o.brain,
        o.logboek,
        AlsaMicrofoon(inst.mic_apparaat, inst.mic_kanalen, inst.mic_kanaal),
        WhisperHerkenner(inst.stt_model, modellen / "whisper"),
        PiperStem(inst.stem, modellen / "piper"),
        AlsaLuidspreker(inst.speaker_apparaat),
        bij_wijziging,
        piep=piep(),
    )
