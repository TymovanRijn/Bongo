"""Spraak naar tekst met Whisper (faster-whisper), op de Pi zelf: er gaat geen geluid naar internet.

De eerste keer downloadt hij het model (small: ongeveer 480 MB) naar data/modellen/whisper.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

# Woorden die Whisper alvast moet kennen. Zonder dit maakt hij van "Bongo" vaak "Bonjour" of "Bingo".
HINT = "Bongo, wat staat er in mijn agenda? Zet een afspraak bij de tandarts."

# Bij stilte of geruis verzint Whisper soms zinnen uit de ondertitels waarmee hij getraind is.
VERZONNEN = ("ondertiteld door", "ondertiteling", "amara.org", "bedankt voor het kijken", "tv gelderland")


class WhisperHerkenner:
    def __init__(self, model: str = "small", map_: Path | None = None, threads: int = 4):
        self.model_naam = model
        self.map = map_
        self.threads = threads
        self._model = None
        self._slot = threading.Lock()

    def warm_op(self) -> None:
        """Laad (en download zo nodig) het model alvast, zodat de eerste vraag niet extra lang duurt."""
        self._laad()

    def _laad(self):
        with self._slot:
            if self._model is None:
                from faster_whisper import WhisperModel

                log.info("Whisper-model '%s' laden (de eerste keer wordt het gedownload)", self.model_naam)
                self._model = WhisperModel(
                    self.model_naam,
                    device="cpu",
                    compute_type="int8",  # 4x kleiner en sneller dan float32, bijna even goed
                    cpu_threads=self.threads,
                    download_root=str(self.map) if self.map else None,
                )
            return self._model

    def herken(self, audio: np.ndarray) -> str:
        segmenten, _ = self._laad().transcribe(
            audio,
            language="nl",
            beam_size=1,  # snel; bij korte zinnen nauwelijks slechter dan 5
            vad_filter=True,  # stiltes eruit, minder kans op verzonnen tekst
            initial_prompt=HINT,
            condition_on_previous_text=False,
        )
        tekst = " ".join(s.text.strip() for s in segmenten).strip()
        if any(v in tekst.lower() for v in VERZONNEN):
            log.info("Whisper verzon iets, ik negeer het: %s", tekst)
            return ""
        return tekst
