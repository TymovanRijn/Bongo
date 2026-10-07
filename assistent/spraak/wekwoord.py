"""Het wekwoord: Bongo luistert de hele tijd of iemand hem roept (openWakeWord, op de Pi zelf).

Met een wekwoord staat de microfoon altijd aan. Het geluid blijft op de Pi: openWakeWord
kijkt steeds naar de laatste anderhalve seconde en vergeet de rest meteen. Pas na het
wekwoord neemt Bongo je vraag op, en ook dan gaat er alleen tekst naar internet. Toch staat
het wekwoord standaard uit: een microfoon die altijd luistert, zet je zelf aan (WEKWOORD in .env).

Terwijl Bongo luistert, nadenkt of praat, krijgt openWakeWord niets te horen: anders kan hij
zichzelf wakker maken. Daarna begint het met een schone lei (zie _lees).
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Callable

import numpy as np

from .audio import RATE, VENSTER, Eindpunt, GeluidFout, Microfoon

log = logging.getLogger(__name__)


class WekwoordDetector:
    """openWakeWord: per stukje geluid de kans (0 tot 1) dat het wekwoord net gezegd is.

    `model` is de naam van een kant-en-klaar wekwoord (hey_jarvis, alexa, hey_mycroft,
    hey_rhasspy) of het pad naar een eigen model (.onnx), bijvoorbeeld een getraind "Hé Bongo".
    """

    def __init__(self, model: str):
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        if model.endswith(".onnx") and not Path(model).exists():
            raise FileNotFoundError(f"het model {model} bestaat niet")
        # Downloadt de hulpmodellen (geluid -> kenmerken) en, bij een kant-en-klaar wekwoord, dat
        # wekwoord zelf. Wat er al is, slaat hij over.
        download_models([Path(model).stem])
        # onnx in plaats van tflite: tflite-runtime is gemaakt voor numpy 1, en wij hebben numpy 2.
        self._model = Model(wakeword_models=[model], inference_framework="onnx")

    def __call__(self, stukje: np.ndarray) -> float:
        # openWakeWord wil 16-bit getallen. Hij rekent per 80 ms; bij een kleiner stukje geeft
        # hij de vorige uitkomst nog eens.
        scores = self._model.predict((stukje * 32767).astype(np.int16))
        return float(max(scores.values(), default=0.0))

    def reset(self) -> None:
        """Vergeet het geluid van daarnet (na het wekwoord, zodat het niet nog eens afgaat)."""
        self._model.reset()


class AltijdAan:
    """Een microfoon die altijd open staat, voor het wekwoord.

    Voor Spraak is dit gewoon een microfoon (neem_op, stop). Maar een microfoon kun je niet
    twee keer tegelijk openen, dus de opname van je vraag leest uit dezelfde stroom als het
    wekwoord. Daardoor gaat ook niet verloren wat je direct na het wekwoord zegt ("Hey Jarvis,
    wat heb ik vandaag?" in één adem): dat bewaart hij tot de opname begint.
    """

    OPNIEUW_NA = 10.0  # seconden: werkt de microfoon niet, dan zo lang wachten en het opnieuw proberen
    MAX_NA_WEKWOORD = 3 * RATE // VENSTER  # hooguit zoveel stukjes (3 s) bewaren tot de opname begint

    def __init__(
        self,
        microfoon: Microfoon,
        detector: Callable[[], Callable[[np.ndarray], float]],
        drempel: float = 0.5,
        bij_wekwoord: Callable[[], bool] | None = None,
        bij_fout: Callable[[str], None] | None = None,
        mag_wekken: Callable[[], bool] | None = None,
    ):
        self.microfoon = microfoon
        self._maak_detector = detector  # pas in de eigen draad: de eerste keer downloadt hij
        self.drempel = drempel
        self.bij_wekwoord = bij_wekwoord or (lambda: False)  # True: Bongo gaat luisteren
        self.bij_fout = bij_fout or (lambda tekst: None)
        self.mag_wekken = mag_wekken or (lambda: True)  # False zolang Bongo zelf bezig is
        self.fout = ""  # wat er nu mis is (leeg: niets)
        self._slot = threading.Lock()
        self._opname: queue.Queue | None = None  # loopt er een opname, dan gaat het geluid hierheen
        self._na_wekwoord: list[np.ndarray] | None = None  # geluid tussen wekwoord en opname
        self._stroom_open = threading.Lock()  # bezet zolang de stroom loopt (zie neem_op)
        self._stop = threading.Event()
        self._draad: threading.Thread | None = None

    # ---- aan en uit -----------------------------------------------------------------------
    def start(self) -> None:
        if self._draad is None:
            self._draad = threading.Thread(target=self._luister, name="wekwoord", daemon=True)
            self._draad.start()

    def sluit(self) -> None:
        self._stop.set()
        self.microfoon.sluit()
        if self._draad is not None:
            self._draad.join(timeout=3)

    def _luister(self) -> None:
        try:
            detector = self._maak_detector()
        except Exception as e:
            log.exception("wekwoord laden mislukt")
            self._meld(f"Het wekwoord werkt niet: {e}")
            return  # tikken op het gezicht werkt nog wel
        log.info("wekwoord staat aan")
        while not self._stop.is_set():
            try:
                with self._stroom_open:
                    self._lees(detector)
            except GeluidFout as e:
                if self._stop.is_set():
                    return  # de kern stopt: dan stopt de microfoon natuurlijk
                self._meld(f"De microfoon werkt niet: {e}")
            self._stop.wait(self.OPNIEUW_NA)

    def _lees(self, detector) -> None:
        doof = False  # kreeg openWakeWord net een tijdje niets te horen?
        try:
            for stukje in self.microfoon.stroom():
                if self.fout:
                    log.info("de microfoon werkt weer")
                    self.fout = ""
                if self._stop.is_set():
                    return
                if self._geef_door(stukje):
                    continue
                if not self.mag_wekken():
                    doof = True  # Bongo is bezig: zijn eigen stem hoeft openWakeWord niet te horen
                    continue
                if doof:
                    detector.reset()  # schone lei: niet verder rekenen met geluid van vóór zijn beurt
                    doof = False
                if detector(stukje) < self.drempel:
                    continue
                log.info("wekwoord gehoord")
                detector.reset()
                with self._slot:
                    self._na_wekwoord = []  # al bewaren, voor het geval de opname meteen begint
                if not self.bij_wekwoord():
                    with self._slot:
                        self._na_wekwoord = None  # Bongo was bezig: niets te bewaren
        finally:
            with self._slot:
                if self._opname is not None:
                    self._opname.put(None)  # de stroom is op: een lopende opname stopt ook

    def _geef_door(self, stukje: np.ndarray) -> bool:
        """Hoort dit stukje bij een opname (of bij de tijd tussen wekwoord en opname)?"""
        with self._slot:
            if self._opname is not None:
                self._opname.put(stukje)
                return True
            if self._na_wekwoord is not None:
                self._na_wekwoord.append(stukje)
                if len(self._na_wekwoord) > self.MAX_NA_WEKWOORD:
                    self._na_wekwoord = None  # er kwam geen opname: weggooien
                return True
            return False

    def _meld(self, tekst: str) -> None:
        if tekst != self.fout:  # dezelfde fout niet elke tien seconden opnieuw
            log.warning("%s", tekst)
            self.fout = tekst
            self.bij_fout(tekst)

    # ---- als microfoon voor Spraak ----------------------------------------------------------
    def neem_op(self, eindpunt: Eindpunt | None = None) -> np.ndarray | None:
        if self._stroom_open.acquire(blocking=False):
            # De stroom loopt niet: het wekwoord laadt nog, werkt niet, of de microfoon hapert.
            # Dan gewoon de microfoon openen, zoals zonder wekwoord.
            try:
                return self.microfoon.neem_op(eindpunt)
            finally:
                self._stroom_open.release()
        opname: queue.Queue = queue.Queue()
        with self._slot:
            for stukje in self._na_wekwoord or []:
                opname.put(stukje)
            self._na_wekwoord = None
            self._opname = opname
        try:
            return self.microfoon.neem_op(eindpunt, stroom=_tot_none(opname))
        finally:
            with self._slot:
                self._opname = None

    def stop(self) -> None:
        self.microfoon.stop()


def _tot_none(wachtrij: queue.Queue):
    """De stukjes uit de wachtrij, tot er None komt. (Niet iter(wachtrij.get, None): dat vergelijkt
    elk stukje met == None, en bij een numpy-array geeft dat geen ja of nee maar een hele array.)"""
    while (stukje := wachtrij.get()) is not None:
        yield stukje
