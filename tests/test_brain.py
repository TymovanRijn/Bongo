import time
from datetime import datetime

import pytest
from nep_claude import TZ, api_fout, geen_verbinding, tekst, tool, weigering

from assistent.brain import BreinFout
from assistent.opbouw import maak_onderdelen

AGENDA_VRAAG = {"van": "2030-03-04", "tot": "2030-03-04"}
AFSPRAAK = {
    "titel": "Tandarts",
    "start": "2030-03-04T10:00",
    "eind": "2030-03-04T10:30",
    "hele_dag": False,
    "locatie": None,
    "notitie": None,
}


def _blokken(verzoek):
    return [b for m in verzoek["messages"] if isinstance(m["content"], list) for b in m["content"]]


# ---- het gewone pad ---------------------------------------------------------------------
def test_gewone_vraag(maak):
    o, nep = maak([tekst("Hoi Tymo!")])
    antwoord = o.brain.vraag("hallo", bron="cli")

    assert antwoord.tekst == "Hoi Tymo!"
    assert antwoord.kosten_usd > 0
    [v] = nep.verzoeken
    assert v["model"] == "claude-opus-5-5"
    assert v["output_config"] == {"effort": "low"}
    assert v["fallbacks"] == "default"
    assert v["cache_control"] == {"type": "ephemeral"}
    assert "<geheugen>" in v["system"][1]["text"]
    # Datum, tijd en bron staan in het bericht, niet in de systeemprompt (goed voor de cache).
    assert v["messages"][0]["content"][-1]["text"] == "[woensdag 7 oktober 2026, 14:00, via de terminal]\nhallo"
    assert "2026" not in v["system"][0]["text"] and "14:00" not in v["system"][0]["text"]


def test_tool_ronde(maak):
    o, nep = maak([tool("agenda_lezen", AGENDA_VRAAG), tekst("Om tien uur naar de kapper.")])
    o.agenda.voeg_toe("Kapper", datetime(2030, 3, 4, 10, tzinfo=TZ), datetime(2030, 3, 4, 11, tzinfo=TZ))
    antwoord = o.brain.vraag("wat heb ik op 4 maart 2030?")

    assert antwoord.tekst == "Om tien uur naar de kapper."
    assert [a["tool"] for a in antwoord.tool_aanroepen] == ["agenda_lezen"]
    resultaat = nep.verzoeken[1]["messages"][-1]["content"][0]
    assert resultaat["type"] == "tool_result" and "Kapper" in resultaat["content"]


def test_voorstel_en_later_de_status(maak):
    o, nep = maak([tool("afspraak_voorstellen", AFSPRAAK), tekst("Klaargezet!"), tekst("Fijn.")])
    antwoord = o.brain.vraag("zet de tandarts erin")
    [vid] = antwoord.voorstel_ids
    assert o.wachtrij.get(vid).status == "open"  # Claude kan het niet zelf uitvoeren

    o.wachtrij.approve(vid, via="test")
    o.brain.vraag("staat hij erin?")
    kop = nep.verzoeken[-1]["messages"][-1]["content"][-1]["text"]
    assert f"voorstel #{vid} is goedgekeurd en uitgevoerd" in kop


# ---- als er iets misgaat ----------------------------------------------------------------
def test_api_fout_laat_de_geschiedenis_heel(maak):
    o, nep = maak([tekst("een"), geen_verbinding(), tekst("drie")])
    o.brain.vraag("een")
    with pytest.raises(BreinFout, match="internet"):
        o.brain.vraag("twee")
    assert len(o.brain.history) == 2
    assert o.brain.vraag("drie").tekst == "drie"


def test_onverwachte_fout_midden_in_een_tool_ronde(maak, monkeypatch):
    """Na een bug in een tool mag Bongo niet blijven hangen.

    Gaat het mis tussen tool_use en tool_result, dan blijft er een tool_use zonder
    antwoord in de geschiedenis staan. De API weigert dan elk volgend verzoek.
    """
    o, nep = maak([tool("agenda_lezen", AGENDA_VRAAG), tekst("Gelukt")])

    def kapot(*a, **k):
        raise RuntimeError("bug in een tool")

    monkeypatch.setattr(o.brain.tools, "voer_uit", kapot)
    with pytest.raises(BreinFout):
        o.brain.vraag("wat heb ik vandaag?")
    assert o.brain.history == []

    monkeypatch.undo()
    assert o.brain.vraag("en nu?").tekst == "Gelukt"


def test_weigering(maak):
    o, _ = maak([weigering()])
    with pytest.raises(BreinFout, match="niet mee helpen"):
        o.brain.vraag("iets wat niet mag")
    assert o.brain.history == []


def test_te_veel_rondes(maak):
    o, _ = maak([tool("agenda_lezen", AGENDA_VRAAG, tool_id=f"toolu_{i}") for i in range(8)])
    with pytest.raises(BreinFout, match="kwam er niet uit"):
        o.brain.vraag("blijf maar zoeken")
    assert o.brain.history == []


def test_zonder_sleutel(inst):
    o = maak_onderdelen(inst, client=None)
    with pytest.raises(BreinFout, match="API-sleutel"):
        o.brain.vraag("hallo")


def test_lege_vraag(maak):
    o, nep = maak()
    with pytest.raises(BreinFout):
        o.brain.vraag("   ")
    assert nep.verzoeken == []


def test_weigering_van_denkblokken_herstelt_een_keer(maak):
    o, nep = maak([tekst("een"), api_fout("messages.1.content.0: Invalid `signature` in `thinking` block."), tekst("twee")])
    o.brain.vraag("een")
    assert o.brain.vraag("twee").tekst == "twee"
    assert all(b["type"] != "thinking" for b in _blokken(nep.verzoeken[2])[:-1])


# ---- beslispunt 1: hoe lang onthoudt hij een gesprek? -----------------------------------
def test_na_stilte_een_nieuw_gesprek(maak, klok):
    o, nep = maak([tekst("a"), tekst("b"), tekst("c")])
    o.brain.vraag("een")
    klok.verzet(minutes=5)
    o.brain.vraag("twee")
    assert len(nep.verzoeken[1]["messages"]) == 3  # zelfde gesprek
    oud = o.brain.gesprek_id

    klok.verzet(minutes=11)
    o.brain.vraag("drie")
    assert len(nep.verzoeken[2]["messages"]) == 1
    assert o.brain.gesprek_id != oud


def test_laatste_n_knipt_zonder_de_api_boos_te_maken(maak):
    o, nep = maak([tekst(f"antwoord {i}") for i in range(5)], gespreksgeheugen="laatste_n", max_beurten=3)
    for i in range(5):
        o.brain.vraag(f"vraag {i}")  # NepClaude geeft een fout als een denkblok niet meer klopt
    # Precies één verzoek per vraag: geen enkel verzoek werd geweigerd en opnieuw geprobeerd.
    assert len(nep.verzoeken) == 5

    vragen = [b["text"].split("\n")[-1] for b in _blokken(nep.verzoeken[-1]) if b.get("type") == "text" and b["text"].startswith("[")]
    assert vragen == ["vraag 2", "vraag 3", "vraag 4"]


def test_samenvatten(maak):
    o, nep = maak(
        [
            tool("agenda_lezen", AGENDA_VRAAG),
            tekst("Je agenda is leeg."),
            tekst("Graag gedaan."),
            tekst("Tymo vroeg naar zijn agenda op 4 maart 2030; die was leeg."),
            tekst("Niets bijzonders."),
        ],
        gespreksgeheugen="samenvatten",
        max_beurten=2,
    )
    o.brain.vraag("wat heb ik op 4 maart 2030?")
    o.brain.vraag("dank je")
    oud = o.brain.gesprek_id
    o.brain.vraag("nog iets?")

    assert len(nep.verzoeken) == 5  # niets geweigerd
    samenvatten = nep.verzoeken[3]
    assert "Vat ons gesprek" in samenvatten["messages"][-1]["content"]
    # Zelfde tools als de rest van het gesprek, maar Claude mag ze nu niet gebruiken.
    assert samenvatten["tools"] == nep.verzoeken[0]["tools"]
    assert samenvatten["tool_choice"] == {"type": "none"}

    nieuw = nep.verzoeken[4]["messages"]
    assert len(nieuw) == 1
    assert "Samenvatting van ons eerdere gesprek: Tymo vroeg naar zijn agenda" in nieuw[0]["content"][0]["text"]
    assert o.brain.gesprek_id != oud


# ---- het geheugen verandert ---------------------------------------------------------------
def test_geheugen_verandert_midden_in_een_gesprek(maak):
    o, nep = maak([tekst("a"), tekst("b")])
    o.brain.vraag("een")
    time.sleep(0.02)
    o.geheugen.voeg_toe("Houdt van thee")
    o.brain.vraag("twee")

    tweede = nep.verzoeken[1]
    assert tweede["system"] == nep.verzoeken[0]["system"]  # systeemprompt ligt vast
    assert tweede["messages"][-1]["role"] == "system"
    assert "Houdt van thee" in tweede["messages"][-1]["content"]


def test_geheugen_na_een_mislukte_eerste_vraag(maak):
    o, nep = maak([geen_verbinding(), tekst("ok")])
    with pytest.raises(BreinFout):
        o.brain.vraag("een")
    time.sleep(0.02)
    o.geheugen.voeg_toe("Houdt van thee")
    o.brain.vraag("twee")
    assert "Houdt van thee" in nep.verzoeken[1]["system"][1]["text"]


# ---- losse opdrachten ---------------------------------------------------------------------
def test_eenmalig_raakt_het_gesprek_niet(maak):
    o, nep = maak([tekst("a"), tekst("Goedemorgen!")])
    o.brain.vraag("een")
    voor = list(o.brain.history)
    tekst_, kosten = o.brain.eenmalig("Maak het ochtendoverzicht.", doel="ochtendoverzicht")
    assert tekst_ == "Goedemorgen!" and kosten > 0
    assert o.brain.history == voor
    assert "tools" not in nep.verzoeken[1]
