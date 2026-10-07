import shutil
import subprocess
import sys
import threading
import wave

import numpy as np
import pytest
from nep_claude import geen_verbinding, tekst

from assistent.spraak.audio import RATE, VENSTER, Eindpunt, GeluidFout, Luidspreker, Microfoon, piep
from assistent.spraak.keten import NIET_VERSTAAN, NOG_LADEN, Spraak


# ---- nep-onderdelen --------------------------------------------------------------------
class NepMicrofoon:
    def __init__(self, *opnames, wacht_op_stop=False):
        self.opnames = list(opnames)
        self.gestopt = threading.Event()
        self.wacht_op_stop = wacht_op_stop

    def neem_op(self):
        if self.wacht_op_stop:
            assert self.gestopt.wait(5), "niemand tikte"
        opname = self.opnames.pop(0)
        if isinstance(opname, Exception):
            raise opname
        return opname

    def stop(self):
        self.gestopt.set()


class NepHerkenner:
    def __init__(self, *teksten, laden=None):
        self.teksten = list(teksten)
        self.geladen = False
        self.laden = laden  # een Event: pas klaar met laden als dat gezet wordt

    def herken(self, audio):
        return self.teksten.pop(0)

    def warm_op(self):
        if self.laden is not None:
            assert self.laden.wait(5)
        self.geladen = True


class NepStem:
    def zinnen(self, tekst_):
        for zin in tekst_.split(". "):
            yield zin.encode(), 22050

    def warm_op(self):
        pass


class NepLuidspreker:
    def __init__(self, blijft_praten=False):
        self.gespeeld = []
        self.gestopt = threading.Event()
        self.blijft_praten = blijft_praten  # praat door tot iemand stop() zegt (het piepje niet)

    def speel(self, stukken):
        geluid = b" ".join(g for g, _ in stukken).decode(errors="replace")
        self.gespeeld.append(geluid)
        if self.blijft_praten and geluid != "piep":
            return not self.gestopt.wait(5)
        return True

    def stop(self):
        self.gestopt.set()


SECONDE = np.zeros(RATE, dtype=np.float32)


def wacht_tot(voorwaarde, seconden=5):
    for _ in range(int(seconden * 50)):
        if voorwaarde():
            return
        threading.Event().wait(0.02)
    raise AssertionError("het gebeurde niet")


@pytest.fixture
def spraak(maak):
    """spraak(antwoorden_van_claude, microfoon=..., herkenner=..., luidspreker=...) -> (spraak, o, nep, toestanden)"""

    def _maak(antwoorden=(), microfoon=None, herkenner=None, luidspreker=None):
        o, nep = maak(antwoorden)
        toestanden = []
        s = Spraak(
            o.brain, o.logboek, microfoon or NepMicrofoon(SECONDE), herkenner or NepHerkenner("Wat heb ik vandaag?"),
            NepStem(), luidspreker or NepLuidspreker(), bij_wijziging=lambda: toestanden.append(s.toestand),
            piep=(b"piep", RATE),
        )
        return s, o, nep, toestanden

    return _maak


# ---- de keten ---------------------------------------------------------------------------
def test_een_hele_beurt(spraak):
    s, o, nep, toestanden = spraak([tekst("Je hebt vandaag niets. Lekker rustig.")])
    assert s.tik() == "luisteren"
    s.wacht(5)

    assert s.luidspreker.gespeeld == ["piep", "Je hebt vandaag niets Lekker rustig."]
    assert toestanden[0] == "luisteren" and toestanden[-1] == "rust"
    assert [t for i, t in enumerate(toestanden) if i == 0 or t != toestanden[i - 1]] == ["luisteren", "denken", "praten", "rust"]
    assert s.ondertitel == "Je hebt vandaag niets. Lekker rustig."
    assert "via spraak, antwoord extra kort" in nep.verzoeken[0]["messages"][0]["content"][-1]["text"]
    stappen = {m["stap"] for m in o.logboek.metingen_samenvatting()}
    assert stappen == {"opnemen", "verstaan", "nadenken", "eerste_zin_gemaakt", "tot_geluid", "praten"}


def test_niets_gezegd(spraak):
    s, _, nep, _ = spraak(microfoon=NepMicrofoon(None))
    s.tik()
    s.wacht(5)
    assert nep.verzoeken == [] and s.luidspreker.gespeeld == ["piep"] and s.toestand == "rust"


def test_niet_verstaan(spraak):
    s, _, nep, _ = spraak(herkenner=NepHerkenner(""))
    s.tik()
    s.wacht(5)
    assert nep.verzoeken == []
    assert s.luidspreker.gespeeld[-1] == NIET_VERSTAAN.replace(". ", " ")


def test_een_fout_van_claude_wordt_uitgesproken(spraak):
    s, _, _, _ = spraak([geen_verbinding()])
    s.tik()
    s.wacht(5)
    assert "internet" in s.luidspreker.gespeeld[-1]


def test_tik_tijdens_luisteren_maakt_de_zin_af(spraak):
    s, _, _, _ = spraak([tekst("Hoi")], microfoon=NepMicrofoon(SECONDE, wacht_op_stop=True))
    s.tik()
    assert s.tik() == "luisteren"  # tweede tik: geen tweede beurt, maar "klaar met praten"
    s.wacht(5)
    assert s.luidspreker.gespeeld[-1] == "Hoi"


def test_tik_tijdens_praten_maakt_hem_stil(spraak):
    s, _, _, _ = spraak([tekst("Een heel lang verhaal")], luidspreker=NepLuidspreker(blijft_praten=True))
    s.tik()
    wacht_tot(lambda: s.toestand == "praten")
    assert s.tik() == "praten"
    s.wacht(5)
    assert s.luidspreker.gestopt.is_set() and s.toestand == "rust"


def test_kapotte_microfoon(spraak):
    s, _, nep, _ = spraak(microfoon=NepMicrofoon(GeluidFout("de microfoon stopte: audio open error")))
    s.tik()
    s.wacht(5)
    assert "audio open error" in s.melding and s.toestand == "rust" and nep.verzoeken == []


def test_zeg_alleen_als_hij_niets_doet(spraak):
    s, _, _, _ = spraak(microfoon=NepMicrofoon(None, wacht_op_stop=True))
    assert s.zeg("Goedemorgen!")
    s.wacht(5)
    assert s.luidspreker.gespeeld == ["Goedemorgen!"]
    s.tik()  # nu luistert hij
    assert not s.zeg("Nog iets")
    s.microfoon.stop()
    s.wacht(5)


def test_modellen_laden(spraak):
    s, _, _, toestanden = spraak()
    s.warm_op()
    wacht_tot(lambda: s.klaar)
    assert s.herkenner.geladen


# ---- wanneer is iemand klaar met praten? ---------------------------------------------
def _stukje():
    return np.zeros(VENSTER, dtype=np.float32)


def test_eindpunt_spraak_en_dan_stilte():
    e = Eindpunt(start_ms=96, stilte_ms=320, voorloop_ms=160)
    statussen = [e.voeg_toe(_stukje(), k) for k in [0.0] * 10 + [0.9] * 20 + [0.1] * 10]
    assert statussen[:10] == ["wacht"] * 10
    assert statussen[12] == "spreekt"  # na drie stukjes spraak
    assert "klaar" in statussen
    # Voorloop (5 stukjes van voor het begin) + spraak + de stilte tot "klaar".
    assert len(e.audio()) == VENSTER * (5 + 17 + 10)


def test_eindpunt_te_lang_niets():
    e = Eindpunt(max_wachten_ms=320)
    assert [e.voeg_toe(_stukje(), 0.0) for _ in range(10)][-1] == "niets"


def test_eindpunt_te_lang_praten():
    e = Eindpunt(max_spraak_ms=640)
    assert "klaar" in [e.voeg_toe(_stukje(), 0.9) for _ in range(30)]


def test_eindpunt_korte_klap_is_geen_spraak():
    e = Eindpunt(start_ms=96)
    assert [e.voeg_toe(_stukje(), k) for k in [0.9, 0.9, 0.1, 0.9, 0.1]] == ["wacht"] * 5


# ---- de echte microfoon- en luidsprekercode, met een nep-programma --------------------
def _opname(tmp_path, kanalen, stem_op):
    """Een rauwe opname: 0,5 s stil, 1 s 'stem' op kanaal `stem_op`, 1 s stil."""
    stukken = [np.zeros((RATE // 2, kanalen)), np.zeros((RATE, kanalen)), np.zeros((RATE, kanalen))]
    stukken[1][:, stem_op] = 8000
    pad = tmp_path / "opname.raw"
    pad.write_bytes(np.concatenate(stukken).astype(np.int16).tobytes())
    return [sys.executable, "-c", f"import sys; sys.stdout.buffer.write(open({str(pad)!r}, 'rb').read())"]


def _luid():
    return lambda stukje: 1.0 if np.abs(stukje).max() > 0.1 else 0.0  # nep-detector: hard = spraak


def test_microfoon_neemt_het_goede_kanaal(tmp_path):
    mic = Microfoon(kanalen=6, kanaal=0, detector=_luid, commando=_opname(tmp_path, 6, stem_op=0))
    audio = mic.neem_op(Eindpunt(stilte_ms=320))
    assert audio is not None and np.abs(audio).max() > 0.2

    mic = Microfoon(kanalen=6, kanaal=0, detector=_luid, commando=_opname(tmp_path, 6, stem_op=5))
    assert mic.neem_op(Eindpunt(max_wachten_ms=1000)) is None  # kanaal 5 is het afspeelsignaal, niet de stem


def test_microfoon_die_niet_werkt():
    fout = [sys.executable, "-c", "import sys; sys.stderr.write('audio open error: No such device'); sys.exit(1)"]
    with pytest.raises(GeluidFout, match="No such device"):
        Microfoon(detector=_luid, commando=fout).neem_op()
    with pytest.raises(GeluidFout, match="niet geïnstalleerd"):
        Microfoon(detector=_luid, commando=["bestaat-niet-xyz"]).neem_op()
    with pytest.raises(ValueError):
        Microfoon(kanalen=1, kanaal=3)


def test_luidspreker_speelt_alles_af(tmp_path):
    uit = tmp_path / "gespeeld.raw"
    schrijf = [sys.executable, "-c", f"import sys; open({str(uit)!r}, 'wb').write(sys.stdin.buffer.read())"]
    assert Luidspreker(commando=lambda rate: schrijf).speel([(b"zin een ", 22050), (b"zin twee", 22050)])
    assert uit.read_bytes() == b"zin een zin twee"


def test_luidspreker_stoppen(tmp_path):
    traag = [sys.executable, "-c", "import time; time.sleep(10)"]
    luidspreker = Luidspreker(commando=lambda rate: traag)
    threading.Timer(0.3, luidspreker.stop).start()
    assert luidspreker.speel([(b"x" * 100, 22050)]) is False


def test_piep():
    geluid, rate = piep()
    assert rate == RATE and len(geluid) == 2 * RATE * 120 // 1000


# ---- het echte VAD-model --------------------------------------------------------------------
def test_vad_hoort_geen_spraak_in_stilte():
    pytest.importorskip("faster_whisper")
    from assistent.spraak.audio import Spraakdetector

    detector = Spraakdetector()
    kansen = [detector(np.zeros(VENSTER, dtype=np.float32)) for _ in range(20)]
    assert max(kansen) < 0.2


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng is nodig om een zin te maken")
def test_vad_vindt_een_gesproken_zin(tmp_path):
    pytest.importorskip("faster_whisper")
    wav = tmp_path / "zin.wav"
    subprocess.run(["espeak-ng", "-v", "nl", "-w", str(wav), "Hoi Bongo, wat heb ik morgen?"], check=True)
    with wave.open(str(wav)) as w:
        bron, sr = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32), w.getframerate()
    zin = np.interp(np.arange(0, len(bron) * RATE / sr) * sr / RATE, np.arange(len(bron)), bron)
    ruis = np.random.default_rng(1).normal(0, 150, RATE)
    opname = tmp_path / "opname.raw"
    opname.write_bytes(np.concatenate([ruis, zin, ruis, ruis]).clip(-32768, 32767).astype(np.int16).tobytes())

    audio = Microfoon(commando=[sys.executable, "-c", f"import sys; sys.stdout.buffer.write(open({str(opname)!r}, 'rb').read())"]).neem_op()
    assert audio is not None
    assert len(zin) / RATE - 1 < len(audio) / RATE < len(zin) / RATE + 1.5  # de zin, plus een beetje stilte


def test_tik_tijdens_het_laden(spraak):
    laden = threading.Event()
    s, _, nep, _ = spraak([tekst("Hoi")], herkenner=NepHerkenner("hallo", laden=laden))
    s.warm_op()
    assert s.tik() == "rust" and s.melding == NOG_LADEN  # niet minutenlang op "denken"
    laden.set()
    wacht_tot(lambda: s.klaar)
    assert s.melding == ""
    s.tik()
    s.wacht(5)
    assert s.luidspreker.gespeeld[-1] == "Hoi"
