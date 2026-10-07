"""Tekst naar spraak: met Azure (natuurlijk, via internet) of met Piper (op de Pi zelf).

Piper downloadt de eerste keer de stem (ongeveer 60 MB) naar data/modellen/piper. Andere
Nederlandse stemmen zien: `.venv/bin/python -m piper.download_voices | grep nl_` en dan in .env
bijvoorbeeld STEM=nl_NL-pim-medium.

Met AZURE_SPEECH_KEY in .env praat Bongo met een stem van Microsoft Azure: veel natuurlijker.
Alleen de tekst van zijn antwoord gaat naar Azure (die tekst kwam al van Claude). Werkt Azure niet
(geen internet, verkeerde sleutel, tegoed op), dan praat hij met Piper verder (MetReserve).
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Iterator
from xml.sax.saxutils import escape

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


class StemFout(Exception):
    pass


class AzureStem:
    RATE = 24_000
    FORMAAT = "raw-24khz-16bit-mono-pcm"  # kaal geluid, 16 bit: precies wat de luidspreker wil

    def __init__(self, sleutel: str, regio: str, stem: str = "nl-NL-FennaNeural", transport=None):
        import httpx2

        self.url = f"https://{regio}.tts.speech.microsoft.com/cognitiveservices/v1"
        self.stem = stem
        self._sleutel = sleutel
        # Eén client die blijft bestaan: dan hoeft niet elke zin opnieuw een verbinding op te zetten.
        self._client = httpx2.Client(transport=transport, timeout=httpx2.Timeout(10.0, connect=3.0))
        self._fout = httpx2.HTTPError

    def warm_op(self) -> None:
        """Probeer het één keer: zo zie je bij het starten al of de sleutel klopt."""
        for _ in self.zinnen("Hoi."):
            pass
        log.info("Azure-stem %s werkt", self.stem)

    def _ssml(self, tekst: str) -> str:
        taal = self.stem[:5]  # nl-NL
        return f"<speak version='1.0' xml:lang='{taal}'><voice name='{self.stem}'>{escape(tekst)}</voice></speak>"

    def zinnen(self, tekst: str) -> Iterator[tuple[bytes, int]]:
        """Het geluid komt in stukjes binnen terwijl Azure het nog maakt; elk stukje gaat meteen door."""
        kop = {
            "Ocp-Apim-Subscription-Key": self._sleutel,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": self.FORMAAT,
            "User-Agent": "Bongo-huisassistent",
        }
        try:
            with self._client.stream("POST", self.url, headers=kop, content=self._ssml(tekst).encode()) as antwoord:
                if antwoord.status_code != 200:
                    antwoord.read()
                    raise StemFout(_azure_fout(antwoord.status_code, self.stem))
                rest = b""
                for stuk in antwoord.iter_bytes():
                    stuk = rest + stuk
                    heel = len(stuk) - len(stuk) % 2  # een sample is 2 bytes: nooit een halve doorgeven
                    rest = stuk[heel:]
                    if heel:
                        yield stuk[:heel], self.RATE
        except self._fout as e:
            raise StemFout(f"Azure is niet bereikbaar: {e}") from e


def _azure_fout(status: int, stem: str) -> str:
    if status in (401, 403):
        return "Azure weigert de sleutel. Kloppen AZURE_SPEECH_KEY en AZURE_SPEECH_REGIO in .env?"
    if status == 400:
        return f"Azure snapt het verzoek niet. Bestaat de stem '{stem}' (AZURE_STEM)?"
    if status == 429:
        return "Te veel verzoeken bij Azure, of het gratis tegoed van deze maand is op."
    return f"Azure gaf fout {status}"


class MetReserve:
    """Eerst de hoofdstem (Azure); lukt dat niet, dan de reserve (Piper).

    Na een fout probeert hij het een minuut lang niet opnieuw: anders wacht elke zin eerst op een
    time-out. Daarna wel, zodat Azure vanzelf terugkomt als het internet het weer doet.
    """

    WACHT_NA_FOUT = 60.0  # seconden

    def __init__(self, hoofd, reserve):
        self.hoofd, self.reserve = hoofd, reserve
        self.fout = ""  # waarom de hoofdstem het nu niet doet
        self._fout_sinds = float("-inf")

    def warm_op(self) -> None:
        self.reserve.warm_op()  # Piper alvast laden, voor als het internet wegvalt
        try:
            self.hoofd.warm_op()
        except Exception as e:
            self._mislukt(e)

    def zinnen(self, tekst: str) -> Iterator[tuple[bytes, int]]:
        if time.monotonic() - self._fout_sinds >= self.WACHT_NA_FOUT:
            begonnen = False
            try:
                for stuk in self.hoofd.zinnen(tekst):
                    begonnen = True
                    yield stuk
                self.fout = ""
                return
            except Exception as e:
                self._mislukt(e)
                if begonnen:
                    return  # de zin was al half uitgesproken: niet opnieuw beginnen met een andere stem
        yield from self.reserve.zinnen(tekst)

    def _mislukt(self, e: Exception) -> None:
        if str(e) != self.fout:
            log.warning("de stem van Azure werkt niet, ik praat met Piper: %s", e)
        self.fout = str(e)
        self._fout_sinds = time.monotonic()


def maak_stem(inst):
    """Azure met Piper als reserve, of alleen Piper (zonder AZURE_SPEECH_KEY)."""
    piper = PiperStem(inst.stem, inst.data_dir / "modellen" / "piper")
    if not inst.azure_speech_key:
        return piper
    return MetReserve(AzureStem(inst.azure_speech_key, inst.azure_speech_regio, inst.azure_stem), piper)
