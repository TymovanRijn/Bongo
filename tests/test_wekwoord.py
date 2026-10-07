"""Het wekwoord: de altijd-aan-microfoon, Spraak.wek() en de koppeling met openWakeWord.

Het echte openWakeWord-model zit niet in de tests (het moet gedownload worden). Een nep-detector
"hoort" het wekwoord in stukjes met een afgesproken waarde, en een nep-microfoon geeft het geluid
dat de test klaarzet. De logica eromheen is wel de echte.
"""

import queue
import shutil
import subprocess
import sys
import threading
import types
import wave

import numpy as np
import pytest
from nep_claude import tekst
from test_spraak import NepHerkenner, NepLuidspreker, NepStem, wacht_tot

from assistent.config import ROOT, laad_instellingen
from assistent.spraak.audio import RATE, VENSTER, Eindpunt, GeluidFout, Microfoon
from assistent.spraak.keten import NOG_LADEN, Spraak, maak_spraak
from assistent.spraak.wekwoord import AltijdAan, WekwoordDetector

STIL = np.zeros(VENSTER, dtype=np.float32)
WEK = np.full(VENSTER, 0.05, dtype=np.float32)  # "Hey Jarvis" (zacht: de nep-VAD vindt het geen vraag)
STEM = np.full(VENSTER, 0.5, dtype=np.float32)  # de vraag
KORT = dict(stilte_ms=320)  # na 10 stille stukjes is de zin klaar


class NepStroom(Microfoon):
    """De echte Microfoon (dus ook de echte neem_op), maar het geluid komt uit een wachtrij."""

    def __init__(self):
        super().__init__(detector=lambda: (lambda stukje: 1.0 if np.abs(stukje).max() > 0.1 else 0.0))
        self.geluid: queue.Queue = queue.Queue()
        self.geopend = 0

    def stroom(self):
        self.geopend += 1
        while True:
            stukje = self.geluid.get()
            if isinstance(stukje, Exception):
                raise stukje
            yield stukje

    def zeg(self, *stukjes):
        for s in stukjes:
            self.geluid.put(s)

    def sluit(self):
        self.geluid.put(GeluidFout("gesloten"))


class NepWekwoord:
    def __init__(self):
        self.gehoord = []  # alle stukjes die het wekwoordmodel te zien kreeg
        self.resets = 0

    def __call__(self, stukje):
        self.gehoord.append(stukje)
        return 1.0 if np.allclose(stukje, WEK) else 0.0

    def reset(self):
        self.resets += 1


def altijd_aan(bezig=False, detector=None, mag=None):
    """Een AltijdAan met nep-microfoon en nep-detector. `bezig`: Bongo doet al iets."""
    mic, wekwoord = NepStroom(), NepWekwoord()
    gewekt, fouten = threading.Event(), []

    def bij_wekwoord():
        gewekt.set()
        return not bezig

    a = AltijdAan(mic, detector or (lambda: wekwoord), bij_wekwoord=bij_wekwoord, bij_fout=fouten.append, mag_wekken=mag)
    a.OPNIEUW_NA = 0.05
    return a, mic, wekwoord, gewekt, fouten


# ---- de altijd-aan-microfoon ---------------------------------------------------------------
def test_wekwoord_en_meteen_doorpraten():
    a, mic, wekwoord, gewekt, _ = altijd_aan()
    a.start()
    # "Hey Jarvis, wat heb ik vandaag?" in één adem: de vraag begint voordat de opname begint.
    mic.zeg(*[STIL] * 5, WEK, *[STEM] * 10)
    assert gewekt.wait(5)
    mic.zeg(*[STIL] * 10)
    audio = a.neem_op(Eindpunt(**KORT))

    assert audio is not None
    assert np.sum(audio == 0.5) == 10 * VENSTER  # de hele vraag zit erin...
    assert not np.any(np.isclose(audio, 0.05))  # ...het wekwoord zelf niet
    mic.zeg(STIL, STIL)
    wacht_tot(lambda: len(wekwoord.gehoord) >= 8)  # na de opname luistert hij weer naar het wekwoord
    assert not any(np.allclose(x, STEM) for x in wekwoord.gehoord)  # maar de vraag kreeg hij niet te horen
    assert wekwoord.resets == 1
    assert mic.geopend == 1  # en dat allemaal met één keer de microfoon openen
    a.sluit()


def test_hoort_zichzelf_niet():
    bongo_praat = threading.Event()
    a, mic, wekwoord, gewekt, _ = altijd_aan(mag=lambda: not bongo_praat.is_set())
    a.start()
    mic.zeg(STIL)
    wacht_tot(lambda: len(wekwoord.gehoord) == 1)
    bongo_praat.set()
    mic.zeg(*[STEM] * 5, WEK, *[STEM] * 5)  # "... dat heb ik voor je gedaan, Jarvis-achtig ..."
    wacht_tot(mic.geluid.empty)
    bongo_praat.clear()
    mic.zeg(STIL)
    wacht_tot(lambda: len(wekwoord.gehoord) == 2)
    assert not gewekt.is_set() and wekwoord.resets == 1  # niets gehoord, en daarna een schone lei
    mic.zeg(WEK)
    assert gewekt.wait(5)  # daarna luistert hij weer
    a.sluit()


def test_tik_met_wekwoord_aan():
    a, mic, wekwoord, gewekt, _ = altijd_aan()
    a.start()
    mic.zeg(STIL)
    wacht_tot(lambda: len(wekwoord.gehoord) == 1)
    opname = []
    tik = threading.Thread(target=lambda: opname.append(a.neem_op(Eindpunt(**KORT))))
    tik.start()
    wacht_tot(lambda: a._opname is not None)
    mic.zeg(*[STEM] * 5, *[STIL] * 10)
    tik.join(5)
    assert np.sum(opname[0] == 0.5) == 5 * VENSTER and mic.geopend == 1 and not gewekt.is_set()
    a.sluit()


def test_wekwoord_terwijl_bongo_bezig_is():
    a, mic, wekwoord, gewekt, _ = altijd_aan(bezig=True)
    a.start()
    mic.zeg(WEK, *[STEM] * 3)
    wacht_tot(lambda: len(wekwoord.gehoord) == 4)
    assert gewekt.is_set() and a._na_wekwoord is None  # niets bewaard: er komt geen opname

    # Tikt iemand daarna, dan zit dat oude geluid niet in de opname.
    tik = []
    threading.Thread(target=lambda: tik.append(a.neem_op(Eindpunt(max_wachten_ms=320)))).start()
    wacht_tot(lambda: a._opname is not None)
    mic.zeg(*[STIL] * 12)
    wacht_tot(lambda: tik)
    assert tik == [None]
    a.sluit()


def test_tik_terwijl_het_wekwoord_nog_laadt():
    laden = threading.Event()
    wekwoord = NepWekwoord()

    def traag():
        assert laden.wait(5)  # de eerste keer wordt het model gedownload
        return wekwoord

    a, mic, _, _, _ = altijd_aan(detector=traag)
    a.start()
    mic.zeg(*[STEM] * 3, *[STIL] * 10)
    opname = []  # in een eigen draad: gaat het mis, dan faalt de test in plaats van te blijven hangen
    tik = threading.Thread(target=lambda: opname.append(a.neem_op(Eindpunt(**KORT))), daemon=True)
    tik.start()
    tik.join(5)
    assert opname, "de opname bleef hangen"  # gewoon de microfoon openen, zoals zonder wekwoord
    assert np.sum(opname[0] == 0.5) == 3 * VENSTER and mic.geopend == 1
    laden.set()
    wacht_tot(lambda: mic.geopend == 2)  # daarna gaat hij luisteren naar het wekwoord
    a.sluit()


def test_wekwoord_laden_mislukt():
    def kapot():
        raise RuntimeError("geen internet")

    a, mic, _, _, fouten = altijd_aan(detector=kapot)
    a.start()
    wacht_tot(lambda: fouten)
    assert fouten == ["Het wekwoord werkt niet: geen internet"]
    mic.zeg(*[STEM] * 3, *[STIL] * 10)
    assert a.neem_op(Eindpunt(**KORT)) is not None  # tikken werkt nog wel
    a.sluit()


def test_microfoon_valt_weg_en_komt_terug():
    a, mic, wekwoord, _, fouten = altijd_aan()
    a.start()
    mic.zeg(STIL)
    wacht_tot(lambda: len(wekwoord.gehoord) == 1)
    opname = []
    tik = threading.Thread(target=lambda: opname.append(pytest.raises(GeluidFout, a.neem_op)))
    tik.start()
    wacht_tot(lambda: a._opname is not None)
    mic.zeg(GeluidFout("de microfoon stopte: kabel eruit"))
    tik.join(5)
    assert opname and "stopte" in str(opname[0].value)  # een lopende opname hangt niet
    for _ in range(3):  # elke paar seconden opnieuw proberen, maar niet elke keer melden
        mic.zeg(GeluidFout("de microfoon stopte: kabel eruit"))
    wacht_tot(lambda: mic.geopend >= 4)
    assert fouten == ["De microfoon werkt niet: de microfoon stopte: kabel eruit"]

    mic.zeg(STIL)  # weer ingeplugd
    wacht_tot(lambda: len(wekwoord.gehoord) == 2)
    assert a.fout == ""
    a.sluit()


def test_sluiten_meldt_geen_fout():
    a, mic, wekwoord, _, fouten = altijd_aan()
    a.start()
    mic.zeg(STIL)
    wacht_tot(lambda: len(wekwoord.gehoord) == 1)
    a.sluit()
    assert not a._draad.is_alive() and fouten == []


# ---- Spraak.wek() ---------------------------------------------------------------------------
class TelMicrofoon:
    """Neemt meteen 'niets' op; telt hoe vaak."""

    def __init__(self):
        self.opnames = 0
        self.aan = None

    def neem_op(self):
        self.opnames += 1
        return None

    def stop(self): ...

    def start(self):
        self.aan = True

    def sluit(self):
        self.aan = False


@pytest.fixture
def spraak(maak):
    o, _ = maak([tekst("Hoi")])
    s = Spraak(o.brain, o.logboek, TelMicrofoon(), NepHerkenner("hallo"), NepStem(), NepLuidspreker())
    return s


def test_start_en_sluit(spraak):
    spraak.start()  # modellen laden en (met wekwoord) de microfoon open
    assert spraak.microfoon.aan
    wacht_tot(lambda: spraak.klaar)
    spraak.sluit()
    assert spraak.microfoon.aan is False


def test_wek_start_een_beurt(spraak):
    assert spraak.wek()
    spraak.wacht(5)
    assert spraak.microfoon.opnames == 1 and spraak.luidspreker.gespeeld == []


def test_wek_niet_terwijl_hij_bezig_is(spraak):
    assert spraak.mag_wekken()
    spraak.luidspreker.blijft_praten = True
    spraak.zeg("Een heel lang verhaal")
    wacht_tot(lambda: spraak.toestand == "praten")
    assert not spraak.wek() and not spraak.mag_wekken()
    spraak.tik()  # stil maar
    spraak.wacht(5)
    assert spraak.microfoon.opnames == 0


def test_wek_tijdens_het_laden(spraak):
    laden = threading.Event()
    spraak.herkenner = NepHerkenner("hallo", laden=laden)
    spraak.warm_op()
    assert not spraak.wek() and spraak.melding == NOG_LADEN
    laden.set()
    wacht_tot(lambda: spraak.klaar)
    assert spraak.melding == ""


def test_een_wekwoordfout_blijft_staan_na_het_laden(spraak):
    spraak.meld("Het wekwoord werkt niet: geen internet")
    spraak.warm_op()
    wacht_tot(lambda: spraak.klaar)
    assert spraak.melding == "Het wekwoord werkt niet: geen internet"


# ---- openWakeWord zelf (nagebootst) -------------------------------------------------------------
@pytest.fixture
def nep_openwakeword(monkeypatch):
    """Doet alsof openwakeword geïnstalleerd is, en onthoudt wat Bongo ermee doet."""
    gedaan = {"download": [], "model": None, "voorspeld": []}

    class Model:
        def __init__(self, wakeword_models, inference_framework):
            gedaan["model"] = (wakeword_models, inference_framework)

        def predict(self, x):
            gedaan["voorspeld"].append(x)
            return {"hey_jarvis": 0.25, "nog_een": 0.75}

        def reset(self):
            gedaan["reset"] = True

    pakket = types.ModuleType("openwakeword")
    monkeypatch.setitem(sys.modules, "openwakeword", pakket)
    monkeypatch.setitem(sys.modules, "openwakeword.model", types.SimpleNamespace(Model=Model))
    monkeypatch.setitem(sys.modules, "openwakeword.utils", types.SimpleNamespace(download_models=gedaan["download"].append))
    return gedaan


def test_detector_met_een_kant_en_klaar_wekwoord(nep_openwakeword):
    d = WekwoordDetector("hey_jarvis")
    assert nep_openwakeword["download"] == [["hey_jarvis"]]
    assert nep_openwakeword["model"] == (["hey_jarvis"], "onnx")
    assert d(np.full(VENSTER, 0.5, dtype=np.float32)) == 0.75  # de hoogste score
    x = nep_openwakeword["voorspeld"][0]
    assert x.dtype == np.int16 and x[0] == 16383  # openWakeWord wil 16-bit getallen
    d.reset()
    assert nep_openwakeword["reset"]


def test_detector_met_een_eigen_model(nep_openwakeword, tmp_path):
    with pytest.raises(FileNotFoundError, match="bestaat niet"):
        WekwoordDetector(str(tmp_path / "he_bongo.onnx"))
    (tmp_path / "he_bongo.onnx").write_bytes(b"model")
    WekwoordDetector(str(tmp_path / "he_bongo.onnx"))
    assert nep_openwakeword["model"] == ([str(tmp_path / "he_bongo.onnx")], "onnx")


# ---- instellingen en opbouw ------------------------------------------------------------------
def test_wekwoord_staat_standaard_uit(monkeypatch):
    monkeypatch.delenv("WEKWOORD", raising=False)
    monkeypatch.delenv("WEKWOORD_DREMPEL", raising=False)
    inst = laad_instellingen()
    assert inst.wekwoord == "" and inst.wekwoord_drempel == 0.5
    monkeypatch.setenv("WEKWOORD", "hey_jarvis")
    monkeypatch.setenv("WEKWOORD_DREMPEL", "0,6")  # met een komma, zoals je het in Nederland schrijft
    inst = laad_instellingen()
    assert inst.wekwoord == "hey_jarvis" and inst.wekwoord_drempel == 0.6
    monkeypatch.setenv("WEKWOORD", "data/modellen/hey_bongo.onnx")  # een eigen model, vanaf de projectmap
    assert laad_instellingen().wekwoord == str(ROOT / "data" / "modellen" / "hey_bongo.onnx")


def test_maak_spraak_met_en_zonder_wekwoord(maak):
    pytest.importorskip("faster_whisper")
    pytest.importorskip("piper")
    o, _ = maak()
    assert isinstance(maak_spraak(o).microfoon, Microfoon)

    o, _ = maak(wekwoord="hey_jarvis", wekwoord_drempel=0.7)
    s = maak_spraak(o)
    assert isinstance(s.microfoon, AltijdAan) and s.microfoon.drempel == 0.7
    assert s.microfoon.bij_wekwoord == s.wek and s.microfoon.bij_fout == s.meld
    assert s.microfoon.mag_wekken == s.mag_wekken


# ---- het echte openWakeWord-model ------------------------------------------------------------
@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng is nodig om een zin te maken")
def test_het_echte_wekwoord(tmp_path):
    pytest.importorskip("openwakeword")
    try:
        detector = WekwoordDetector("hey_jarvis")  # de eerste keer: downloaden van GitHub
    except Exception as e:
        pytest.skip(f"het model kon niet geladen worden: {e}")

    def hoogste_kans(tekst_, stem):
        wav = tmp_path / "zin.wav"
        subprocess.run(["espeak-ng", "-v", stem, "-w", str(wav), tekst_], check=True)
        with wave.open(str(wav)) as w:
            bron, sr = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()
        zin = np.interp(np.arange(0, len(bron) * RATE / sr) * sr / RATE, np.arange(len(bron)), bron) / 32768
        geluid = np.concatenate([np.zeros(RATE), zin, np.zeros(RATE)]).astype(np.float32)
        detector.reset()
        return max(detector(geluid[i : i + VENSTER]) for i in range(0, len(geluid) - VENSTER, VENSTER))

    assert hoogste_kans("Hey Jarvis", "en-us") > 0.5
    assert hoogste_kans("Wat heb ik morgen op de agenda?", "nl") < 0.1
