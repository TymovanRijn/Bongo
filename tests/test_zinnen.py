import re

import pytest

from assistent.spraak.zinnen import Zinnensplitser


def knip(tekst):
    """Zoals Claude het stuurt: een paar woorden tegelijk."""
    splitser, zinnen = Zinnensplitser(), []
    for stukje in re.findall(r"\S+\s*", tekst):
        zinnen += splitser.voeg_toe(stukje)
    return zinnen + splitser.klaar()


@pytest.mark.parametrize(
    "tekst, zinnen",
    [
        ("Om tien uur de tandarts. Daarna sporten!", ["Om tien uur de tandarts.", "Daarna sporten!"]),
        ("Even kijken in je agenda", ["Even kijken in je agenda"]),
        ("Je hebt o.a. de tandarts en bijv. sporten. Klopt dat?", ["Je hebt o.a. de tandarts en bijv. sporten.", "Klopt dat?"]),
        ("Om 14.30 uur de kapper. Zal ik hem verzetten?", ["Om 14.30 uur de kapper.", "Zal ik hem verzetten?"]),
        ('Hij zei: "Kom maar." Toen ging hij.', ['Hij zei: "Kom maar."', "Toen ging hij."]),
        ("Wacht even... Ik kijk het na.", ["Wacht even...", "Ik kijk het na."]),
        ("Dat is J. de Vries. Hij komt morgen.", ["Dat is J. de Vries.", "Hij komt morgen."]),
        ("Eerste regel\nTweede regel", ["Eerste regel", "Tweede regel"]),
    ],
)
def test_knippen(tekst, zinnen):
    assert knip(tekst) == zinnen


def test_een_zin_komt_vrij_zodra_hij_af_is():
    splitser = Zinnensplitser()
    assert splitser.voeg_toe("Om tien uur") == []
    assert splitser.voeg_toe(" de tandarts.") == []  # nog niet: misschien komt er "..." of een afkorting
    assert splitser.voeg_toe(" Daarna") == ["Om tien uur de tandarts."]
    assert splitser.klaar() == ["Daarna"]
    assert splitser.klaar() == []
