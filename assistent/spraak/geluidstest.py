"""Geluidstest: zoekt de ReSpeaker, meet de microfoon en de luidspreker, en zegt wat er in .env moet.

    .venv/bin/python -m assistent.kern geluid

Zet de kern eerst uit: een microfoon kan maar door één programma tegelijk gebruikt worden.

Wat hij doet:
1. Kijkt welke geluidskaarten er zijn (arecord -l, aplay -l) en of de ReSpeaker erbij zit.
2. Probeert hoeveel kanalen de ReSpeaker geeft. Dat hangt af van zijn firmware: 6 (kanaal 0 is je
   stem, schoongemaakt; 1 tot en met 4 de losse microfoons; 5 wat hij zelf afspeelt) of 1.
3. Neemt je stem op en meet per kanaal hoe hard die binnenkomt.
4. Speelt een zin af via de ReSpeaker en luistert tegelijk mee. Zo zie je of de luidspreker werkt,
   en hoeveel van Bongo's eigen stem er na de echo-onderdrukking nog in de microfoon zit.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .audio import RATE, GeluidFout

PRATEN_SECONDEN = 4
GELUID_VANAF = 1.0  # zoveel seconden na het begin van de opname begint het testgeluid
TEST_ZIN = "Hallo, ik ben Bongo. Dit is een test van de luidspreker. Hoor je mij goed?"
VENSTER = RATE // 10  # niveaus per 100 ms


class Bezet(GeluidFout):
    pass


@dataclass
class Kaart:
    id: str  # bijvoorbeeld ArrayUAC10
    naam: str  # bijvoorbeeld ReSpeaker 4 Mic Array (UAC1.0)
    apparaat: int

    @property
    def is_respeaker(self) -> bool:
        return self.id.lower().startswith("arrayuac") or "respeaker" in self.naam.lower()

    @property
    def alsa(self) -> str:
        """Met plug: ALSA rekent het aantal kanalen en de samplerate om als dat nodig is."""
        return f"plughw:CARD={self.id},DEV={self.apparaat}"

    @property
    def hw(self) -> str:
        """Zonder omrekenen: alleen wat de kaart zelf kan."""
        return f"hw:CARD={self.id},DEV={self.apparaat}"


_KAART = re.compile(r"^card \d+: (\S+) \[(.*?)\], device (\d+):", re.M)


def lees_kaarten(uitvoer: str) -> list[Kaart]:
    """De kaarten uit `arecord -l` of `aplay -l`."""
    return [Kaart(id_, naam, int(apparaat)) for id_, naam, apparaat in _KAART.findall(uitvoer)]


# ---- meten ---------------------------------------------------------------------------------
def niveaus(kanaal: np.ndarray) -> np.ndarray:
    """Hoe hard elk stukje van 100 ms is, in dB onder het maximum (0 is keihard, -90 is stil)."""
    n = len(kanaal) // VENSTER
    if n == 0:
        return np.array([-120.0])
    stukken = kanaal[: n * VENSTER].astype(np.float64).reshape(n, VENSTER) / 32768
    rms = np.sqrt(np.mean(stukken**2, axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-6))


def stilte_en_piek(kanaal: np.ndarray) -> tuple[float, float]:
    """Het achtergrondgeluid (het stilste tiende deel) en het hardste moment."""
    n = niveaus(kanaal)
    return float(np.percentile(n, 10)), float(n.max())


def stem_boven_stilte(opname: np.ndarray) -> list[float]:
    """Per kanaal: hoeveel dB je stem boven het achtergrondgeluid uitkwam."""
    uit = []
    for k in range(opname.shape[1]):
        stilte, piek = stilte_en_piek(opname[:, k])
        uit.append(piek - stilte)
    return uit


def echo(opname: np.ndarray, vanaf: float, duur: float) -> list[float]:
    """Per kanaal: hoeveel dB het testgeluid boven de stilte ervoor uitkwam."""
    stil = opname[int(0.1 * RATE) : int((vanaf - 0.2) * RATE)]
    # Pas na een halve seconde meten: de echo-onderdrukking moet zich eerst instellen.
    tijdens = opname[int((vanaf + 0.5) * RATE) : int((vanaf + duur - 0.1) * RATE)]
    uit = []
    for k in range(opname.shape[1]):
        achtergrond = float(np.median(niveaus(stil[:, k])))
        uit.append(float(niveaus(tijdens[:, k]).max()) - achtergrond)
    return uit


# ---- de programma's (arecord en aplay) --------------------------------------------------------
def _draai(commando: list[str], **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(commando, capture_output=True, timeout=30, **kwargs)
    except FileNotFoundError as e:
        raise GeluidFout(f"{commando[0]} is niet geïnstalleerd (sudo apt install alsa-utils)") from e


def _fout(stderr: bytes) -> GeluidFout:
    tekst = stderr.decode(errors="replace").strip()
    if "busy" in tekst.lower():
        return Bezet(
            "De ReSpeaker is bezet. Staat de kern nog aan? Zet hem eerst uit "
            "(Ctrl+C, of: systemctl --user stop bongo-kern)."
        )
    return GeluidFout(tekst or "onbekende fout")


def kaarten(programma: str) -> list[Kaart]:
    return lees_kaarten(_draai([programma, "-l"]).stdout.decode(errors="replace"))


def proef_kanalen(kaart: Kaart) -> int:
    """Hoeveel kanalen geeft de ReSpeaker? Zonder plug, want plug doet alsof alles kan."""
    laatste = b""
    for kanalen in (6, 1):
        r = _draai(["arecord", "-q", "-D", kaart.hw, "-f", "S16_LE", "-r", str(RATE),
                    "-c", str(kanalen), "-d", "1", "-t", "raw", "/dev/null"])
        if r.returncode == 0:
            return kanalen
        laatste = r.stderr
        if b"busy" in laatste.lower():
            break
    raise _fout(laatste)


def neem_op(apparaat: str, kanalen: int, seconden: int, ondertussen: Callable[[], None] | None = None) -> np.ndarray:
    """Neem `seconden` op, alle kanalen. `ondertussen` draait tijdens de opname (om iets af te spelen)."""
    try:
        proces = subprocess.Popen(
            ["arecord", "-q", "-D", apparaat, "-f", "S16_LE", "-r", str(RATE), "-c", str(kanalen),
             "-t", "raw", "-d", str(seconden)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except FileNotFoundError as e:
        raise GeluidFout("arecord is niet geïnstalleerd (sudo apt install alsa-utils)") from e
    gelezen: list[bytes] = []
    lezer = threading.Thread(target=lambda: gelezen.append(proces.stdout.read()), daemon=True)
    lezer.start()
    try:
        if ondertussen is not None:
            ondertussen()
    finally:
        lezer.join(seconden + 10)
        stderr = proces.stderr.read()
        proces.wait(timeout=5)
    if proces.returncode != 0:
        raise _fout(stderr)
    ruw = gelezen[0] if gelezen else b""
    n = len(ruw) // (2 * kanalen)
    return np.frombuffer(ruw[: n * 2 * kanalen], dtype=np.int16).reshape(n, kanalen)


def speel(apparaat: str, geluid: bytes, rate: int) -> None:
    r = _draai(["aplay", "-q", "-D", apparaat, "-t", "raw", "-f", "S16_LE", "-r", str(rate), "-c", "1"], input=geluid)
    if r.returncode != 0:
        raise _fout(r.stderr)


def testgeluid(inst) -> tuple[bytes, int, str]:
    """De testzin met de stem uit .env (Azure of Piper), of anders een melodietje. Plus waar het vandaan komt."""
    waarom = ""
    if inst.azure_speech_key:
        try:
            from .stem import AzureStem

            azure = AzureStem(inst.azure_speech_key, inst.azure_speech_regio, inst.azure_stem)
            return b"".join(g for g, _ in azure.zinnen(TEST_ZIN)), AzureStem.RATE, f"Azure ({inst.azure_stem})"
        except Exception as e:
            waarom = f"Azure werkt niet: {e}. "
    try:
        from .stem import PiperStem

        stukken = list(PiperStem(inst.stem, inst.data_dir / "modellen" / "piper").zinnen(TEST_ZIN))
        return b"".join(g for g, _ in stukken), stukken[0][1], waarom + f"Piper ({inst.stem})"
    except Exception as e:
        waarom += f"Piper werkt niet: {e}. "
    # Met pauzes ertussen: een doorlopende toon haalt de ruisonderdrukking van de ReSpeaker weg,
    # en dan lijkt de echo-onderdrukking beter dan hij is.
    tonen = []
    for hoogte in (523, 659, 784, 659, 587, 698, 880, 698, 523, 659, 784, 523):
        t = np.arange(int(RATE * 0.22)) / RATE
        tonen += [np.sin(2 * np.pi * hoogte * t) * 0.3, np.zeros(int(RATE * 0.06))]
    return (np.concatenate(tonen) * 32767).astype(np.int16).tobytes(), RATE, waarom + "een melodietje"


# ---- de test zelf ---------------------------------------------------------------------------
def _balk(db: float) -> str:
    vol = int(max(0, min(20, db / 2)))
    return "█" * vol + "░" * (20 - vol)


KANAAL_UITLEG = {
    6: ["je stem, schoongemaakt (dit gebruikt Bongo)", "microfoon 1", "microfoon 2", "microfoon 3", "microfoon 4",
        "wat de ReSpeaker zelf afspeelt"],
    1: ["je stem, schoongemaakt (dit gebruikt Bongo)"],
}


def geluidstest(inst, schrijf: Callable[[str], None] = print, vraag: Callable[[str], str] = input) -> int:
    schrijf("Geluidstest voor Bongo. Zet de kern eerst uit, anders is de microfoon bezet.\n")
    try:
        return _geluidstest(inst, schrijf, vraag)
    except GeluidFout as e:
        schrijf(f"\nDat lukt niet: {e}")
        return 1


def _geluidstest(inst, schrijf, vraag) -> int:
    # 1. Wat is er aangesloten?
    opnemen, afspelen = kaarten("arecord"), kaarten("aplay")
    schrijf("1. Wat er is aangesloten")
    for soort, lijst in (("opnemen", opnemen), ("afspelen", afspelen)):
        for k in lijst:
            schrijf(f"   {soort:9} {k.id:14} {k.naam}" + ("   <- de ReSpeaker" if k.is_respeaker else ""))
    mic = next((k for k in opnemen if k.is_respeaker), None)
    if mic is None:
        schrijf(
            "\nIk zie geen ReSpeaker. Kijk of hij er is met: lsusb | grep 2886\n"
            "Staat hij daar niet, probeer dan een andere USB-poort of een andere kabel "
            "(sommige kabels kunnen alleen opladen)."
        )
        return 1
    speaker = next((k for k in afspelen if k.is_respeaker), None)

    # 2. Hoeveel kanalen?
    kanalen = proef_kanalen(mic)
    schrijf(f"\n2. De ReSpeaker geeft {kanalen} {'kanalen' if kanalen > 1 else 'kanaal'}.")
    uitleg = KANAAL_UITLEG.get(kanalen, [f"kanaal {k}" for k in range(kanalen)])

    # 3. Je stem
    vraag(f"\n3. Druk op Enter en zeg dan {PRATEN_SECONDEN} seconden lang iets, bijvoorbeeld: 'Hey Jarvis, wat heb ik morgen?' ")
    schrijf("   Praat maar...")
    opname = neem_op(mic.alsa, kanalen, PRATEN_SECONDEN)
    stem = stem_boven_stilte(opname)
    for k, db in enumerate(stem):
        schrijf(f"   kanaal {k}  {_balk(db)}  {db:4.0f} dB  {uitleg[k]}")
    if stem[0] >= 20:
        schrijf("   Je stem komt goed binnen.")
    elif stem[0] >= 10:
        schrijf("   Je stem komt binnen, maar zacht. Praat dichterbij, of zet hem harder: alsamixer -c " + mic.id)
    else:
        schrijf("   Ik hoor je bijna niet. Zet de microfoon harder (alsamixer -c " + mic.id + ") of praat dichterbij.")

    # 4. De luidspreker
    gehoord = None
    if speaker is None:
        schrijf("\n4. De ReSpeaker heeft geen uitgang voor een luidspreker. De speakers zitten dus ergens anders.")
    else:
        schrijf("\n4. Nu spreek ik een zin uit via de ReSpeaker en luister ik tegelijk mee.")
        schrijf("   Bongo's stem laden (Piper wordt de eerste keer gedownload)...")
        geluid, rate, bron = testgeluid(inst)
        schrijf(f"   Stem: {bron}. Even stil zijn...")
        duur = len(geluid) / 2 / rate

        def afspelen_():
            time.sleep(GELUID_VANAF)
            speel(speaker.alsa, geluid, rate)

        opname = neem_op(mic.alsa, kanalen, int(np.ceil(GELUID_VANAF + duur + 1)), ondertussen=afspelen_)
        gehoord = vraag("   Hoorde je de zin uit de speakers? (j/n) ").strip().lower().startswith("j")
        schrijf("   " + _over_de_echo(echo(opname, GELUID_VANAF, duur), kanalen, gehoord, mic.id))

    # 5. Wat er in .env moet
    advies = {"MIC_APPARAAT": mic.alsa, "MIC_KANALEN": str(kanalen), "MIC_KANAAL": "0"}
    if speaker is not None and gehoord:
        advies["SPEAKER_APPARAAT"] = speaker.alsa
    nu = {"MIC_APPARAAT": inst.mic_apparaat, "MIC_KANALEN": str(inst.mic_kanalen),
          "MIC_KANAAL": str(inst.mic_kanaal), "SPEAKER_APPARAAT": inst.speaker_apparaat}
    anders = {naam: waarde for naam, waarde in advies.items() if nu[naam] != waarde}
    if anders:
        schrijf("\n5. Zet dit in .env (nano .env) en start de kern opnieuw:")
        for naam, waarde in anders.items():
            schrijf(f"   {naam}={waarde}        (nu: {nu[naam]})")
    else:
        schrijf("\n5. In .env staat alles al goed.")
    return 0


def _over_de_echo(boven_stilte: list[float], kanalen: int, gehoord: bool, kaart_id: str) -> str:
    bongo = boven_stilte[0]
    if not gehoord:
        return (
            "Zit de stekker van de speakers in de ReSpeaker, staan ze aan, en staat het volume open? "
            f"Volume: alsamixer -c {kaart_id} (met M zet je iets aan of uit)."
        )
    if kanalen == 6:
        microfoons = float(np.mean(boven_stilte[1:5]))
        if microfoons < 10:
            return "De microfoons hoorden de speakers nauwelijks. Staan ze erg zacht?"
        oordeel = (
            "Bongo hoort zichzelf vrijwel niet: de echo-onderdrukking werkt." if bongo < 6
            else "Bongo hoort zichzelf nog zachtjes." if bongo < 15
            else "Bongo hoort zichzelf duidelijk. Zit de luidspreker echt in de ReSpeaker? Anders kan die hem niet wegpoetsen."
        )
        return (
            f"De losse microfoons hoorden de zin {microfoons:.0f} dB boven de stilte. Op kanaal 0, wat Bongo "
            f"gebruikt, was dat nog {bongo:.0f} dB. {oordeel}"
        )
    oordeel = "Hij hoort zichzelf vrijwel niet." if bongo < 6 else "Hij hoort zichzelf nog: het kan wat zachter."
    return f"Op het kanaal dat Bongo gebruikt, kwam de zin {bongo:.0f} dB boven de stilte uit. {oordeel}"
