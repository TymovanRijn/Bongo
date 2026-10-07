"""Tekst naar spraak met Piper, op de Pi zelf.

De eerste keer downloadt hij de stem (ongeveer 60 MB) naar data/modellen/piper.
Andere Nederlandse stemmen zien: `.venv/bin/python -m piper.download_voices | grep nl_`
en dan in .env bijvoorbeeld STEM=nl_BE-nathalie-medium.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


class PiperStem:
    def __init__(self, stem: str = "nl_NL-mls-medium", map_: Path | None = None, snelheid: float = 1.0):
        self.stem = stem
        self.map = Path(map_ or ".")
        self.snelheid = snelheid
        self._stem = None
        self._slot = threading.Lock()

    def warm_op(self) -> None:
        self._laad()

    def _laad(self):
        with self._slot:
            if self._stem is None:
                from piper import PiperVoice
                from piper.download_voices import download_voice

                model = self.map / f"{self.stem}.onnx"
                if not model.exists():
                    log.info("Piper-stem '%s' downloaden naar %s", self.stem, self.map)
                    self.map.mkdir(parents=True, exist_ok=True)
                    download_voice(self.stem, self.map)
                self._stem = PiperVoice.load(model)
            return self._stem

    def zinnen(self, tekst: str) -> Iterator[tuple[bytes, int]]:
        """Het geluid per zin (16-bit mono), zodat de eerste zin al klinkt terwijl de rest nog gemaakt wordt."""
        from piper import SynthesisConfig

        instelling = SynthesisConfig(length_scale=1 / self.snelheid)
        for stuk in self._laad().synthesize(tekst, syn_config=instelling):
            yield stuk.audio_int16_bytes, stuk.sample_rate
