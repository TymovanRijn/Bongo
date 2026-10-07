"""Geluid erin en eruit: de microfoon, de luidspreker, en wanneer iemand klaar is met praten.

Opnemen en afspelen gaat met `arecord` en `aplay` (alsa-utils, staat op Raspberry Pi OS).
Zo werkt het met elke microfoon en luidspreker die Linux kent, zonder extra drivers.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections import deque
from typing import Callable, Iterable, Iterator

import numpy as np

log = logging.getLogger(__name__)

RATE = 16_000  # Whisper en het VAD-model verwachten 16 kHz
VENSTER = 512  # samples per stukje: 32 ms, de maat van het VAD-model
STUKJE_MS = VENSTER * 1000 // RATE


class GeluidFout(Exception):
    pass


class Spraakdetector:
    """Hoe groot is de kans dat er in dit stukje van 32 ms gesproken wordt?

    Silero VAD, een klein neuraal netwerk dat met faster-whisper meekomt. Het onderscheidt
    een stem van een dichte deur of een wasmachine; alleen naar luidheid kijken kan dat niet.
    Het model houdt een geheugen bij tussen stukjes (h en c), dus: één detector per opname.
    """

    CONTEXT = 64  # samples van het vorige stukje die het model ook wil zien

    def __init__(self):
        import os

        import onnxruntime
        from faster_whisper.utils import get_assets_path

        opties = onnxruntime.SessionOptions()
        opties.inter_op_num_threads = opties.intra_op_num_threads = 1
        opties.log_severity_level = 4
        self._sessie = onnxruntime.InferenceSession(
            os.path.join(get_assets_path(), "silero_vad_v6.onnx"), providers=["CPUExecutionProvider"], sess_options=opties
        )
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._vorige = np.zeros(self.CONTEXT, dtype=np.float32)

    def __call__(self, stukje: np.ndarray) -> float:
        invoer = np.concatenate([self._vorige, stukje]).astype(np.float32)[None, :]
        kans, self._h, self._c = self._sessie.run(None, {"input": invoer, "h": self._h, "c": self._c})
        self._vorige = stukje[-self.CONTEXT :]
        return float(np.ravel(kans)[0])


class Eindpunt:
    """Wanneer begint iemand te praten, en wanneer is hij klaar?

    Krijgt per stukje van 32 ms het geluid en de kans op spraak, en zegt dan:
    "wacht" (nog niemand), "spreekt", "klaar" (genoeg stilte na het praten) of
    "niets" (te lang gewacht zonder dat iemand iets zei).
    """

    def __init__(
        self,
        start_kans: float = 0.5,
        stop_kans: float = 0.35,  # lager dan start_kans, zodat hij niet heen en weer springt
        start_ms: int = 96,  # zo lang boven start_kans = iemand praat echt
        stilte_ms: int = 800,  # zo lang stil na het praten = klaar
        max_wachten_ms: int = 6_000,
        max_spraak_ms: int = 15_000,
        voorloop_ms: int = 320,  # geluid van vlak voor het begin bewaren, anders mis je de eerste klank
    ):
        self.start_kans, self.stop_kans = start_kans, stop_kans
        self._start = max(1, start_ms // STUKJE_MS)
        self._stilte = max(1, stilte_ms // STUKJE_MS)
        self._max_wachten = max_wachten_ms // STUKJE_MS
        self._max_spraak = max_spraak_ms // STUKJE_MS
        self._voorloop: deque[np.ndarray] = deque(maxlen=max(1, voorloop_ms // STUKJE_MS))
        self._spraak: list[np.ndarray] = []
        self._boven = self._stil = self._gewacht = 0
        self.gestart = False

    def voeg_toe(self, stukje: np.ndarray, kans: float) -> str:
        if not self.gestart:
            self._gewacht += 1
            self._voorloop.append(stukje)
            self._boven = self._boven + 1 if kans >= self.start_kans else 0
            if self._boven >= self._start:
                self.gestart = True
                self._spraak = list(self._voorloop)
                return "spreekt"
            return "niets" if self._gewacht >= self._max_wachten else "wacht"
        self._spraak.append(stukje)
        self._stil = self._stil + 1 if kans < self.stop_kans else 0
        if self._stil >= self._stilte or len(self._spraak) >= self._max_spraak:
            return "klaar"
        return "spreekt"

    def audio(self) -> np.ndarray:
        return np.concatenate(self._spraak) if self._spraak else np.zeros(0, dtype=np.float32)


class Microfoon:
    def __init__(
        self,
        apparaat: str = "default",
        kanalen: int = 1,
        kanaal: int = 0,
        detector: Callable[[], Callable[[np.ndarray], float]] = Spraakdetector,
        commando: list[str] | None = None,
    ):
        if not 0 <= kanaal < kanalen:
            raise ValueError(f"MIC_KANAAL={kanaal} bestaat niet bij MIC_KANALEN={kanalen}")
        self.kanalen, self.kanaal = kanalen, kanaal
        self.commando = commando or [
            "arecord", "-q", "-D", apparaat, "-f", "S16_LE", "-r", str(RATE), "-c", str(kanalen), "-t", "raw",
        ]
        self._maak_detector = detector
        self._stop = threading.Event()
        self._proces: subprocess.Popen | None = None

    def start(self) -> None:
        """Niets te doen: deze microfoon gaat pas aan bij een opname (met wekwoord: zie wekwoord.py)."""

    def stop(self) -> None:
        """Tik tijdens het luisteren: wat er tot nu toe gezegd is, is de vraag."""
        self._stop.set()

    def sluit(self) -> None:
        """Zet de microfoon echt uit (de kern stopt)."""
        proces = self._proces
        if proces is not None and proces.poll() is None:
            proces.kill()

    def stroom(self) -> Iterator[np.ndarray]:
        """De microfoon als doorlopende stroom stukjes van 32 ms: float32, 16 kHz, alleen het gekozen kanaal.
        De microfoon gaat uit zodra je stopt met lezen."""
        grootte = VENSTER * 2 * self.kanalen  # 16 bit = 2 bytes per sample per kanaal
        try:
            proces = subprocess.Popen(self.commando, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            raise GeluidFout(f"{self.commando[0]} is niet geïnstalleerd") from e
        self._proces = proces
        try:
            while True:
                ruw = proces.stdout.read(grootte)
                if len(ruw) < grootte:
                    proces.wait(timeout=2)
                    fout = proces.stderr.read().decode(errors="replace").strip()
                    raise GeluidFout(f"de microfoon stopte: {fout or 'geen geluid meer'}")
                stukje = np.frombuffer(ruw, dtype=np.int16).reshape(-1, self.kanalen)[:, self.kanaal]
                yield stukje.astype(np.float32) / 32768.0
        finally:
            if proces.poll() is None:
                proces.kill()
            proces.wait()
            self._proces = None

    def neem_op(self, eindpunt: Eindpunt | None = None, stroom: Iterator[np.ndarray] | None = None) -> np.ndarray | None:
        """Neem op tot iemand klaar is met praten. Geeft 16 kHz mono (float32), of None als er niets gezegd werd.

        Zonder `stroom` gaat de microfoon alleen voor deze opname aan. Met het wekwoord staat
        hij al open, en komt het geluid uit die stroom (zie wekwoord.py).
        """
        self._stop.clear()
        eindpunt = eindpunt or Eindpunt()
        detector = self._maak_detector()
        bron = stroom if stroom is not None else self.stroom()
        try:
            for stukje in bron:
                status = eindpunt.voeg_toe(stukje, detector(stukje))
                if status == "niets":
                    return None
                if status == "klaar" or (self._stop.is_set() and eindpunt.gestart):
                    return eindpunt.audio()
                if self._stop.is_set():
                    return None  # getikt voordat er iets gezegd werd: toch maar niet
            raise GeluidFout("de microfoon stopte")
        finally:
            if stroom is None:
                bron.close()  # de microfoon weer uit


def piep(hoogte: float = 880.0, ms: int = 120) -> tuple[bytes, int]:
    """Een kort, zacht belletje: nu mag je praten."""
    t = np.arange(int(RATE * ms / 1000)) / RATE
    golf = np.sin(2 * np.pi * hoogte * t) * np.minimum(1, np.minimum(t, t[::-1]) * 60)  # zacht in en uit
    return (golf * 0.25 * 32767).astype(np.int16).tobytes(), RATE


class Luidspreker:
    def __init__(self, apparaat: str = "default", commando: Callable[[int], list[str]] | None = None):
        self._commando = commando or (
            lambda rate: ["aplay", "-q", "-D", apparaat, "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", "1"]
        )
        self._proces: subprocess.Popen | None = None
        self._slot = threading.Lock()
        self._gestopt = False

    def speel(self, stukken: Iterable[tuple[bytes, int]]) -> bool:
        """Speel 16-bit mono geluid af, stuk voor stuk (bijvoorbeeld zin voor zin, terwijl de
        volgende zin nog gemaakt wordt). Geeft False als het werd onderbroken."""
        self._gestopt = False
        proces = None
        huidige_rate = None
        try:
            for geluid, rate in stukken:
                if self._gestopt:
                    return False
                if proces is not None and rate != huidige_rate:
                    # Ander geluid (bijvoorbeeld Piper na Azure): eerst dit afmaken, dan opnieuw
                    # beginnen met de nieuwe snelheid. Anders klinkt het te snel of te langzaam.
                    proces.stdin.close()
                    proces.wait()
                    proces = None
                if proces is None:
                    try:
                        proces = subprocess.Popen(self._commando(rate), stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    except FileNotFoundError as e:
                        raise GeluidFout("aplay is niet geïnstalleerd") from e
                    huidige_rate = rate
                    with self._slot:
                        self._proces = proces
                proces.stdin.write(geluid)
                proces.stdin.flush()
            if proces is not None:
                proces.stdin.close()
                proces.wait()
            return not self._gestopt
        except (BrokenPipeError, ValueError):
            return False  # afgebroken met stop()
        finally:
            with self._slot:
                self._proces = None
            if proces is not None and proces.poll() is None:
                proces.kill()
                proces.wait()

    def stop(self) -> None:
        """Tik tijdens het praten: meteen stil."""
        self._gestopt = True
        with self._slot:
            if self._proces is not None:
                self._proces.kill()
