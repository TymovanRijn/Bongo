"""De geluidstest, met nep-programma's in plaats van arecord en aplay (hier is geen ReSpeaker).

De nep-arecord doet alsof hij een ReSpeaker is: hij geeft een lijst met kaarten, zegt hoeveel
kanalen er zijn, en "neemt op" wat de test klaarzet. De geluidstest zelf is de echte.
"""

import json
import os
import sys

import numpy as np
import pytest

from assistent.spraak import geluidstest
from assistent.spraak.audio import RATE
from assistent.spraak.geluidstest import echo, lees_kaarten, stem_boven_stilte

ARECORD_L = """**** List of CAPTURE Hardware Devices ****
card 2: ArrayUAC10 [ReSpeaker 4 Mic Array (UAC1.0)], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
"""
APLAY_L = """**** List of PLAYBACK Hardware Devices ****
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
  Subdevices: 1/1
card 2: ArrayUAC10 [ReSpeaker 4 Mic Array (UAC1.0)], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
"""

NEP = r'''
import json, os, sys
import numpy as np
map_ = os.environ["NEP_MAP"]
instelling = json.load(open(os.path.join(map_, "instelling.json")))
args = sys.argv[1:]
naam = os.path.basename(sys.argv[0])
with open(os.path.join(map_, "log.txt"), "a") as f:
    f.write(naam + " " + " ".join(args) + "\n")
if "-l" in args:
    print(instelling[naam + "_l"])
    sys.exit(0)
if instelling.get("bezet"):
    sys.stderr.write("audio open error: Device or resource busy")
    sys.exit(1)
if naam == "aplay":
    data = sys.stdin.buffer.read()
    open(os.path.join(map_, "gespeeld"), "wb").write(data)
    sys.exit(0)
kanalen = int(args[args.index("-c") + 1])
if args[-1] == "/dev/null":  # proberen hoeveel kanalen er zijn
    if kanalen != instelling["kanalen"]:
        sys.stderr.write("arecord: set_params:1349: Channels count non available")
        sys.exit(1)
    sys.exit(0)
teller = os.path.join(map_, "opnames")
n = int(open(teller).read()) if os.path.exists(teller) else 0
open(teller, "w").write(str(n + 1))
seconden = int(args[args.index("-d") + 1])
rng = np.random.default_rng(n)
audio = rng.normal(0, 30, (seconden * 16000, kanalen))  # achtergrondgeluid
for stuk in instelling["opnames"][n]:  # [kanaal, van, tot, sterkte]
    k, van, tot, sterkte = stuk
    if k < kanalen:
        audio[int(van * 16000):int(tot * 16000), k] += rng.normal(0, sterkte, int(tot * 16000) - int(van * 16000))
sys.stdout.buffer.write(audio.clip(-32768, 32767).astype(np.int16).tobytes())
'''

STEM = [[k, 1.0, 3.0, 3000] for k in range(5)]  # je stem op kanaal 0 tot en met 4


def luidspreker(bongo_hoort):
    """De zin uit de speakers: hard op de losse microfoons en op kanaal 5, op kanaal 0 zoals opgegeven."""
    return [[k, 1.0, 3.0, 3000] for k in (1, 2, 3, 4, 5)] + [[0, 1.0, 3.0, bongo_hoort]]


@pytest.fixture
def nep(tmp_path, monkeypatch, inst):
    """nep(kanalen=6, opnames=[...], antwoorden=[...]) -> (code, uitvoer, map)"""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for naam in ("arecord", "aplay"):
        pad = bin_ / naam
        pad.write_text(f"#!{sys.executable}\n{NEP}")
        pad.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("NEP_MAP", str(tmp_path))
    # Een kort testgeluid van 2 seconden, zonder Piper (dat zou een stem willen downloaden).
    monkeypatch.setattr(geluidstest, "testgeluid", lambda inst_: (b"\x10\x00" * RATE * 2, RATE))

    def _draai(kanalen=6, opnames=(STEM, luidspreker(30)), antwoorden=("", "j"), arecord_l=ARECORD_L, bezet=False):
        instelling = {"kanalen": kanalen, "opnames": list(opnames), "arecord_l": arecord_l, "aplay_l": APLAY_L, "bezet": bezet}
        (tmp_path / "instelling.json").write_text(json.dumps(instelling))
        uitvoer, antwoord = [], iter(antwoorden)
        code = geluidstest.geluidstest(inst, schrijf=uitvoer.append, vraag=lambda tekst: (uitvoer.append(tekst), next(antwoord))[1])
        return code, "\n".join(uitvoer), tmp_path

    return _draai


def test_alles_goed_met_6_kanalen(nep):
    code, uit, map_ = nep()
    assert code == 0
    assert "<- de ReSpeaker" in uit and "6 kanalen" in uit
    assert "Je stem komt goed binnen" in uit
    assert "Bongo hoort zichzelf vrijwel niet" in uit
    assert "MIC_APPARAAT=plughw:CARD=ArrayUAC10,DEV=0        (nu: default)" in uit
    assert "MIC_KANALEN=6" in uit and "SPEAKER_APPARAAT=plughw:CARD=ArrayUAC10,DEV=0" in uit
    assert (map_ / "gespeeld").stat().st_size == RATE * 4  # het testgeluid ging naar de speakers
    log = (map_ / "log.txt").read_text()
    assert "arecord -q -D hw:CARD=ArrayUAC10,DEV=0" in log  # kanalen proberen zonder plug
    assert "aplay -q -D plughw:CARD=ArrayUAC10,DEV=0" in log


def test_bongo_hoort_zichzelf(nep):
    _, uit, _ = nep(opnames=(STEM, luidspreker(3000)))
    assert "Bongo hoort zichzelf duidelijk" in uit


def test_speakers_niet_gehoord(nep):
    code, uit, _ = nep(antwoorden=("", "n"))
    assert code == 0
    assert "alsamixer -c ArrayUAC10" in uit and "SPEAKER_APPARAAT" not in uit.split("5.")[-1]


def test_firmware_met_1_kanaal(nep):
    code, uit, _ = nep(kanalen=1)
    assert code == 0 and "1 kanaal." in uit
    assert "MIC_KANALEN" not in uit.split("5.")[-1]  # 1 is de standaard: dat hoeft niet te veranderen
    assert "Op het kanaal dat Bongo gebruikt" in uit


def test_zachte_microfoon(nep):
    _, uit, _ = nep(opnames=([[k, 1.0, 3.0, 150] for k in range(5)], luidspreker(30)))
    assert "zacht" in uit or "bijna niet" in uit


def test_geen_respeaker(nep):
    code, uit, _ = nep(arecord_l="**** List of CAPTURE Hardware Devices ****\n")
    assert code == 1 and "lsusb | grep 2886" in uit


def test_kern_staat_nog_aan(nep):
    code, uit, _ = nep(bezet=True)
    assert code == 1 and "bezet" in uit and "systemctl --user stop bongo-kern" in uit


def test_kern_geluid_commando(inst, monkeypatch):
    from assistent import kern

    gestart = []
    monkeypatch.setattr(kern, "laad_instellingen", lambda: inst)
    monkeypatch.setattr(geluidstest, "geluidstest", lambda i: gestart.append(i) or 0)
    assert kern.main(["geluid"]) == 0 and gestart == [inst]


# ---- het meten zelf --------------------------------------------------------------------------
def test_kaarten_lezen():
    [hdmi, respeaker] = lees_kaarten(APLAY_L)
    assert not hdmi.is_respeaker and respeaker.is_respeaker
    assert respeaker.alsa == "plughw:CARD=ArrayUAC10,DEV=0" and respeaker.hw == "hw:CARD=ArrayUAC10,DEV=0"


def test_stem_en_echo_meten():
    rng = np.random.default_rng(0)
    opname = rng.normal(0, 30, (4 * RATE, 2))
    opname[RATE : 3 * RATE, 1] += rng.normal(0, 3000, 2 * RATE)  # 100 keer harder: 40 dB
    stil, hard = stem_boven_stilte(opname.astype(np.int16))
    assert stil < 3 and 35 < hard < 45
    _, door = echo(opname.astype(np.int16), vanaf=1.0, duur=2.0)
    assert 35 < door < 45
