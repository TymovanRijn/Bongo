"""De stem: Azure (met een nep-Azure, zonder internet), Piper als reserve, en de luidspreker."""

import sys
from dataclasses import replace

import httpx2
import pytest

from assistent.config import laad_instellingen
from assistent.spraak.audio import Luidspreker
from assistent.spraak.stem import AzureStem, MetReserve, PiperStem, StemFout, maak_stem


def nep_azure(status=200, geluid=b"\x01\x02\x03\x04\x05\x06", fout=None):
    """Een nep-Azure. Het geluid komt in rare stukjes binnen (3 bytes, 1, 2), zoals over internet kan."""
    verzoeken = []

    def antwoord(verzoek):
        verzoeken.append(verzoek)
        if fout:
            raise fout
        return httpx2.Response(status, content=iter([geluid[:3], geluid[3:4], geluid[4:]]))

    return AzureStem("geheime-sleutel", "westeurope", transport=httpx2.MockTransport(antwoord)), verzoeken


# ---- Azure -----------------------------------------------------------------------------------
def test_azure_spreekt_een_zin_uit():
    azure, verzoeken = nep_azure()
    stukken = list(azure.zinnen("Tom & Jerry <3"))

    assert b"".join(g for g, _ in stukken) == b"\x01\x02\x03\x04\x05\x06"
    assert all(len(g) % 2 == 0 for g, _ in stukken)  # nooit een halve sample naar de luidspreker
    assert {rate for _, rate in stukken} == {24_000}
    [v] = verzoeken
    assert str(v.url) == "https://westeurope.tts.speech.microsoft.com/cognitiveservices/v1"
    assert v.headers["Ocp-Apim-Subscription-Key"] == "geheime-sleutel"
    assert v.headers["X-Microsoft-OutputFormat"] == "raw-24khz-16bit-mono-pcm"
    assert v.headers["Content-Type"] == "application/ssml+xml"
    ssml = v.content.decode()
    assert "<voice name='nl-NL-FennaNeural'>" in ssml and "xml:lang='nl-NL'" in ssml
    assert "Tom &amp; Jerry &lt;3" in ssml  # anders is het geen geldige SSML meer


@pytest.mark.parametrize(
    "status, verwacht", [(401, "AZURE_SPEECH_KEY"), (400, "AZURE_STEM"), (429, "tegoed"), (500, "fout 500")]
)
def test_azure_fouten_in_gewone_taal(status, verwacht):
    azure, _ = nep_azure(status=status)
    with pytest.raises(StemFout, match=verwacht):
        list(azure.zinnen("Hoi"))


def test_azure_zonder_internet():
    azure, _ = nep_azure(fout=httpx2.ConnectError("geen verbinding"))
    with pytest.raises(StemFout, match="niet bereikbaar"):
        list(azure.zinnen("Hoi"))


# ---- Piper als reserve ---------------------------------------------------------------------------
class NepStem:
    def __init__(self, naam, kapot=False, kapot_na=None):
        self.naam, self.kapot, self.kapot_na = naam, kapot, kapot_na
        self.gevraagd = 0
        self.opgewarmd = False

    def warm_op(self):
        self.opgewarmd = True
        if self.kapot:
            raise StemFout("sleutel klopt niet")

    def zinnen(self, tekst):
        self.gevraagd += 1
        if self.kapot:
            raise StemFout("sleutel klopt niet")
        yield f"{self.naam}:{tekst}".encode(), 24_000
        if self.kapot_na:
            raise StemFout("verbinding weg")


def test_reserve_als_azure_niet_werkt():
    azure, piper = NepStem("azure", kapot=True), NepStem("piper")
    stem = MetReserve(azure, piper)
    stem.warm_op()  # gooit geen fout: Bongo praat dan gewoon met Piper
    assert piper.opgewarmd and "sleutel" in stem.fout

    assert [g for g, _ in stem.zinnen("Hoi")] == [b"piper:Hoi"]
    assert azure.gevraagd == 0  # een minuut lang niet opnieuw proberen: dat kost bij elke zin een time-out

    azure.kapot = False
    stem._fout_sinds -= MetReserve.WACHT_NA_FOUT
    assert [g for g, _ in stem.zinnen("Hoi")] == [b"azure:Hoi"]  # daarna komt Azure vanzelf terug
    assert stem.fout == ""


def test_azure_valt_halverwege_een_zin_weg():
    stem = MetReserve(NepStem("azure", kapot_na=True), NepStem("piper"))
    # Niet de hele zin nog eens met een andere stem: dan hoor je het begin twee keer.
    assert [g for g, _ in stem.zinnen("Hoi")] == [b"azure:Hoi"]
    assert [g for g, _ in stem.zinnen("Doei")] == [b"piper:Doei"]


def test_maak_stem(inst):
    assert isinstance(maak_stem(inst), PiperStem)
    stem = maak_stem(replace(inst, azure_speech_key="sleutel", azure_speech_regio="northeurope", azure_stem="nl-NL-MaartenNeural"))
    assert isinstance(stem, MetReserve) and isinstance(stem.reserve, PiperStem)
    assert stem.hoofd.url.startswith("https://northeurope.") and stem.hoofd.stem == "nl-NL-MaartenNeural"


def test_azure_instellingen(monkeypatch):
    monkeypatch.setenv("AZURE_SPEECH_KEY", "abc")
    monkeypatch.setenv("AZURE_SPEECH_REGIO", "West Europe")  # zoals de Azure-website het schrijft
    monkeypatch.delenv("AZURE_STEM", raising=False)
    inst = laad_instellingen()
    assert inst.azure_speech_key == "abc" and inst.azure_speech_regio == "westeurope"
    assert inst.azure_stem == "nl-NL-FennaNeural"


# ---- de luidspreker: wisselen van stem midden in een antwoord ---------------------------------
def test_luidspreker_begint_opnieuw_bij_een_andere_snelheid(tmp_path):
    uit = tmp_path / "gespeeld.txt"
    schrijf = lambda rate: [  # noqa: E731
        sys.executable, "-c",
        f"import sys; open({str(uit)!r}, 'a').write('{rate}:' + sys.stdin.buffer.read().decode() + '\\n')",
    ]
    assert Luidspreker(commando=schrijf).speel([(b"aa", 24_000), (b"bb", 24_000), (b"cc", 22_050)])
    # Azure op 24000, en daarna Piper op 22050: niet Piper op de snelheid van Azure (dan klinkt het raar).
    assert uit.read_text().splitlines() == ["24000:aabb", "22050:cc"]
