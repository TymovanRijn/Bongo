"""Tekst uitspreekbaar maken voordat hij naar de stem gaat (spraak/uitspraak.py)."""

import shutil
import subprocess

import pytest
from nep_claude import tekst
from test_spraak import SECONDE, NepHerkenner, NepLuidspreker, NepMicrofoon

from assistent.spraak.keten import Spraak
from assistent.spraak.uitspraak import spreekbaar, tijd


@pytest.mark.parametrize(
    "uur, minuut, gezegd",
    [
        (14, 0, "twee uur"), (0, 0, "twaalf uur"), (12, 0, "twaalf uur"),
        (14, 15, "kwart over twee"), (14, 30, "half drie"), (14, 45, "kwart voor drie"),
        (9, 5, "vijf over negen"), (10, 20, "tien voor half elf"), (10, 35, "vijf over half elf"),
        (10, 50, "tien voor elf"), (23, 45, "kwart voor twaalf"), (0, 30, "half een"), (11, 59, "een voor twaalf"),
    ],
)
def test_tijden_zoals_je_ze_zegt(uur, minuut, gezegd):
    assert tijd(uur, minuut) == gezegd


@pytest.mark.parametrize(
    "geschreven, gezegd",
    [
        ("Om 14:30 heb je de tandarts.", "Om half drie heb je de tandarts."),
        ("Van 10:00-10:30 ben je bezig.", "Van tien uur tot half elf ben je bezig."),
        ("Om 14.30 uur.", "Om half drie."),
        ("Om 23:45 uur.", "Om kwart voor twaalf."),
        ("Dat kost € 12,50.", "Dat kost 12 euro 50."),
        ("Dat kost €12,-.", "Dat kost 12 euro."),
        ("Nog 3,50 euro.", "Nog 3 euro 50."),
        ("Bijv. de kapper, ca. 20 min.", "bijvoorbeeld de kapper, ongeveer 20 minuten"),
        ("Dat is t/m vrijdag, o.a. bij Sanne.", "Dat is tot en met vrijdag, onder andere bij Sanne."),
        ("Op 7 okt. om 12:00.", "Op 7 oktober om twaalf uur."),
        ("Bel Jan.", "Bel Jan."),  # Jan is meestal een naam, geen januari
        ("Datum: 2026-10-14.", "Datum: 14 oktober 2026."),
        ("Hoi Tymo! 😊👍🏽", "Hoi Tymo!"),
        ("Je hebt **niets** gepland.", "Je hebt niets gepland."),
        ("- Lunch met Sanne & Piet", "Lunch met Sanne en Piet"),
        ("Zie [de site](https://x.nl) of https://y.nl", "Zie de site of een link"),
        ("Versie 1.5 is uit.", "Versie 1.5 is uit."),  # geen tijd
        ("Gewoon een zin.", "Gewoon een zin."),
    ],
)
def test_spreekbaar(geschreven, gezegd):
    assert spreekbaar(geschreven) == gezegd


def test_alleen_een_emoji_wordt_niets():
    assert spreekbaar("🎉") == ""


@pytest.mark.skipif(shutil.which("espeak-ng") is None, reason="espeak-ng is nodig")
def test_piper_zegt_geen_rare_dingen_meer():
    """espeak-ng bepaalt de uitspraak voor Piper. Vóór spreekbaar() las hij tekens letterlijk voor."""

    def klanken(t):
        return subprocess.run(["espeak-ng", "-v", "nl", "-q", "-x", t], capture_output=True, text=True).stdout

    zin = "Je hebt **niets** om 10:00-10:30, dat kost € 12,50 😊"
    raar = {"sterretje": "rEt;@", "nul": "8l", "euroteken": "t,e:k@n", "lachend gezicht": "l'Ax@nt"}
    voor, na = klanken(zin), klanken(spreekbaar(zin))
    for woord, klank in raar.items():
        assert klank in voor, f"zonder spreekbaar zegt hij '{woord}'"
        assert klank not in na, f"met spreekbaar zegt hij nog steeds '{woord}'"


# ---- in de spraakketen ------------------------------------------------------------------------
class OnthoudStem:
    def __init__(self):
        self.gekregen = []

    def zinnen(self, t):
        self.gekregen.append(t)
        yield t.encode(), 22050

    def warm_op(self):
        pass


def test_stem_krijgt_spreekbare_tekst_en_ondertitel_blijft_gewoon(maak):
    o, _ = maak([tekst("Om 14:30 heb je de **tandarts**. 😊")])
    stem = OnthoudStem()
    s = Spraak(o.brain, o.logboek, NepMicrofoon(SECONDE), NepHerkenner("Wat heb ik vandaag?"), stem, NepLuidspreker())
    s.tik()
    s.wacht(5)

    assert stem.gekregen == ["Om half drie heb je de tandarts."]  # de emoji was een eigen "zin": overgeslagen
    assert s.ondertitel == "Om 14:30 heb je de **tandarts**. 😊"  # op het scherm de gewone tekst
    [regel] = [g for g in o.logboek.recent() if g["soort"] == "uitgesproken"]
    assert regel["inhoud"] == "Om half drie heb je de tandarts."  # zo kun je nakijken wat er naar de stem ging
