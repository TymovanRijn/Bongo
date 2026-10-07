"""De spraakketen: tik op het gezicht -> luisteren -> verstaan -> nadenken -> praten.

Alles gebeurt op de Pi zelf, behalve het nadenken (Claude). Er gaat dus nooit geluid naar
internet, alleen de tekst die Whisper ervan maakte. Zonder wekwoord staat de microfoon alleen
aan tussen een tik op het scherm en het einde van je zin. Met wekwoord (WEKWOORD in .env) staat
hij altijd aan, maar blijft het geluid op de Pi tot je het wekwoord zegt (zie wekwoord.py).

Elke stap wordt gemeten (tabel `metingen`, zie Meer > Snelheid in de webapp), zodat je ziet
waar de tijd heen gaat. De belangrijkste: `tot_geluid`, van het einde van je zin tot het
eerste geluid van Bongo. Dat is hoe lang het voor jou voelt.

Bongo begint te praten zodra Claude zijn eerste zin af heeft, niet pas als het hele
antwoord klaar is (zie `_antwoord_hardop`).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Callable, Iterable, Iterator, Protocol

from ..brain import BreinFout
from .uitspraak import spreekbaar
from .zinnen import Zinnensplitser

log = logging.getLogger(__name__)

NIET_VERSTAAN = "Sorry, dat verstond ik niet."
NOG_LADEN = "Ik ben mijn oren en stem nog aan het klaarmaken. Probeer het zo nog eens."


class Microfoon(Protocol):
    def start(self) -> None: ...
    def neem_op(self): ...
    def stop(self) -> None: ...
    def sluit(self) -> None: ...


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
            if self.toestand == "rust":
                self._begin_te_luisteren()
            elif self.toestand == "luisteren":
                self.microfoon.stop()
            elif self.toestand == "praten":
                self.luidspreker.stop()
            return self.toestand

    def wek(self) -> bool:
        """Het wekwoord is gehoord: hij gaat luisteren, net als na een tik.

        Maar alleen als hij niets doet. Een tik tijdens het praten betekent "stil maar", het
        wekwoord niet: anders kan hij zichzelf stilmaken. Geeft True als hij is gaan luisteren.
        """
        with self._slot:
            if self.toestand != "rust":
                return False
            return self._begin_te_luisteren()

    def mag_wekken(self) -> bool:
        """Mag het wekwoord nu meeluisteren? Niet terwijl hij zelf bezig is (zie wekwoord.py)."""
        return self.toestand == "rust"

    def zeg(self, tekst: str) -> bool:
        """Iets uitspreken zonder dat erom gevraagd is (het ochtendoverzicht). Alleen als hij niets doet."""
        with self._slot:
            if self.toestand != "rust":
                return False
            self._start(lambda: self._praat(tekst), "praten")
            return True

    def start(self) -> None:
        """De kern start: modellen laden en, met wekwoord, de microfoon openzetten."""
        self.warm_op()
        self.microfoon.start()

    def sluit(self) -> None:
        """De kern stopt: de microfoon echt uit."""
        self.microfoon.sluit()

    def meld(self, tekst: str) -> None:
        """Laat zien dat er iets mis is (het gezicht kijkt verward, de tekst staat eronder)."""
        self.melding = tekst
        self.bij_wijziging()

    def warm_op(self) -> None:
        """Laad de modellen op de achtergrond. De eerste keer worden ze gedownload: dat kan minuten duren."""

        def laden():
            begin = time.monotonic()
            try:
                self.herkenner.warm_op()
                self.stem.warm_op()
                self.klaar = True
                if self.melding == NOG_LADEN:
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
    def _begin_te_luisteren(self) -> bool:
        if self._laden:
            # Anders hangt hij minutenlang op "denken" terwijl Whisper nog downloadt.
            self.melding = NOG_LADEN
            self.bij_wijziging()
            return False
        self._start(self._beurt, "luisteren")
        return True

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

        self._antwoord_hardop(tekst, einde_zin)

    def _antwoord_hardop(self, vraag: str, einde_zin: float) -> None:
        """Laat Claude antwoorden en spreek elke zin uit zodra hij af is.

        Claude schrijft in een eigen draad, de luidspreker praat in deze draad, en een
        wachtrij met zinnen zit ertussen. Zo klinkt de eerste zin al terwijl Claude de rest
        nog schrijft. (Zegt Claude eerst "even kijken" en zoekt hij dan in de agenda, dan
        hoor je dat ook meteen.)
        """
        zinnen: queue.Queue[str | None] = queue.Queue()
        splitser = Zinnensplitser()
        eerste = threading.Event()
        begin = time.monotonic()

        def bij_tekst(stukje: str, einde_bericht: bool) -> None:
            for zin in splitser.klaar() if einde_bericht else splitser.voeg_toe(stukje):
                if not eerste.is_set():
                    eerste.set()
                    self._meet("eerste_zin_bedacht", _ms(begin))
                zinnen.put(zin)

        def denk() -> None:
            try:
                antwoord = self.brain.vraag(vraag, bron="spraak", bij_tekst=bij_tekst)
                if not eerste.is_set():
                    zinnen.put(antwoord.tekst)  # er kwam geen tekst binnen (bijvoorbeeld een leeg antwoord)
            except BreinFout as e:
                zinnen.put(e.melding)
            except Exception:
                log.exception("nadenken mislukt")
                zinnen.put("Er ging iets mis bij het nadenken.")
            finally:
                self._meet("nadenken", _ms(begin))
                zinnen.put(None)  # klaar

        threading.Thread(target=denk, name="spraak-denken", daemon=True).start()
        self._spreek(iter(zinnen.get, None), einde_zin)

    def _praat(self, tekst: str, einde_zin: float | None = None) -> None:
        """Spreek een tekst uit die al helemaal klaar is."""
        self._spreek(iter([tekst]), einde_zin)

    def _spreek(self, zinnen: Iterator[str], einde_zin: float | None = None) -> None:
        """Spreek de zinnen uit zodra ze er zijn. De ondertitel op het scherm groeit mee.

        De ondertitel is de tekst zoals Claude hem schreef; naar de stem gaat hij uitspreekbaar
        gemaakt ("14:30" wordt "half drie"). Wat er precies naar de stem ging, staat in het
        logboek (soort "uitgesproken"), met | tussen de zinnen.
        """
        gezegd: list[str] = []
        uitgesproken: list[str] = []
        eerste_geluid: list[float] = []

        def geluid() -> Iterator[tuple[bytes, int]]:
            for zin in zinnen:
                gezegd.append(zin)
                self._zet("praten", " ".join(gezegd))
                uit = spreekbaar(zin)
                if not uit:
                    continue  # er stond alleen een emoji of opmaak
                uitgesproken.append(uit)
                log.info("naar de stem: %s", uit)
                stem_begin = time.monotonic()
                for stuk in self.stem.zinnen(uit):
                    if not eerste_geluid:
                        eerste_geluid.append(time.monotonic())
                        self._meet("stem", _ms(stem_begin))
                        if einde_zin is not None:
                            self._meet("tot_geluid", _ms(einde_zin))
                    yield stuk

        try:
            afgemaakt = self.luidspreker.speel(geluid())
        finally:
            if uitgesproken:
                try:
                    self.logboek.schrijf("uitgesproken", " | ".join(uitgesproken))
                except Exception:
                    log.exception("logboek schrijven mislukt")
        if eerste_geluid:
            self._meet("praten", _ms(eerste_geluid[0]), {"afgemaakt": afgemaakt, "tekens": len(" ".join(gezegd))})


def maak_spraak(o, bij_wijziging: Callable[[], None] | None = None) -> Spraak | None:
    """De echte spraakketen, of None als spraak uit staat of de pakketten ontbreken."""
    inst = o.inst
    if not inst.spraak:
        return None
    try:
        from .audio import Luidspreker as AlsaLuidspreker
        from .audio import Microfoon as AlsaMicrofoon
        from .audio import piep
        from .stem import maak_stem
        from .verstaan import WhisperHerkenner
    except ImportError as e:
        log.warning("spraak staat uit: het pakket '%s' ontbreekt (.venv/bin/pip install -r requirements.txt)", e.name)
        return None
    modellen = inst.data_dir / "modellen"
    log.info(
        "spraak: microfoon %s (kanaal %d van %d), luidspreker %s, stem %s%s",
        inst.mic_apparaat, inst.mic_kanaal, inst.mic_kanalen, inst.speaker_apparaat,
        f"Azure {inst.azure_stem} (reserve: Piper)" if inst.azure_speech_key else f"Piper {inst.stem}",
        "" if "ArrayUAC10" in inst.mic_apparaat else " (niet de ReSpeaker? test het met: python -m assistent.kern geluid)",
    )
    microfoon = AlsaMicrofoon(inst.mic_apparaat, inst.mic_kanalen, inst.mic_kanaal)
    if inst.wekwoord:
        from .wekwoord import AltijdAan, WekwoordDetector

        microfoon = AltijdAan(microfoon, lambda: WekwoordDetector(inst.wekwoord), inst.wekwoord_drempel)
    spraak = Spraak(
        o.brain,
        o.logboek,
        microfoon,
        WhisperHerkenner(inst.stt_model, modellen / "whisper"),
        maak_stem(inst),
        AlsaLuidspreker(inst.speaker_apparaat),
        bij_wijziging,
        piep=piep(),
    )
    if inst.wekwoord:
        microfoon.bij_wekwoord = spraak.wek
        microfoon.bij_fout = spraak.meld
        microfoon.mag_wekken = spraak.mag_wekken
    return spraak
