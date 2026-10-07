from datetime import datetime

import pytest
from nep_claude import TZ, geen_verbinding, tekst, tool

from assistent import cli
from assistent.cli import Terminal

AFSPRAAK = {
    "titel": "Tandarts",
    "start": "2030-03-04T10:00",
    "eind": "2030-03-04T10:30",
    "hele_dag": False,
    "locatie": None,
    "notitie": None,
}


@pytest.fixture
def maak_terminal(maak):
    def _maak(antwoorden=()):
        o, nep = maak(antwoorden)
        return Terminal(o), o

    return _maak


def test_vraag_voorstel_en_ja(maak_terminal):
    t, o = maak_terminal([tool("afspraak_voorstellen", AFSPRAAK), tekst("Ik heb het klaargezet.")])
    uit = t.verwerk("zet de tandarts op 4 maart 2030 om tien uur")
    assert uit.startswith("Bongo: Ik heb het klaargezet.")
    assert "[#1] Afspraak: Tandarts" in uit and "/ja 1" in uit

    assert "Welk voorstel?" in t.verwerk("/ja")  # zonder nummer gebeurt er niets
    assert o.wachtrij.get(1).status == "open"

    assert t.verwerk("/ja 1").startswith("Gedaan.")
    [afspraak] = o.agenda.afspraken(datetime(2030, 3, 4, tzinfo=TZ), datetime(2030, 3, 5, tzinfo=TZ))
    assert afspraak.titel == "Tandarts"
    assert "niet meer open" in t.verwerk("/ja 1")


def test_nee(maak_terminal):
    t, o = maak_terminal()
    v = o.wachtrij.voorstel("onthouden", "Onthouden: Houdt van thee", {"feit": "Houdt van thee"})
    assert t.verwerk(f"/nee #{v.id}") == "Afgewezen: Onthouden: Houdt van thee"
    assert "thee" not in o.geheugen.lees()
    assert t.verwerk("/wachtrij") == "Er staan geen voorstellen open."


def test_geen_nummer(maak_terminal):
    t, _ = maak_terminal()
    assert t.verwerk("/ja twee") == "Dat lukt niet: 'twee' is geen nummer"
    assert t.verwerk("/ja") == "Er staan geen voorstellen open."


def test_fout_van_het_brein_wordt_netjes_gemeld(maak_terminal):
    t, _ = maak_terminal([geen_verbinding()])
    assert t.verwerk("hallo") == "Bongo: Ik kan het internet niet bereiken, dus ik kan nu even niet nadenken."


def test_agenda(maak_terminal):
    t, _ = maak_terminal()
    uit = t.verwerk("/agenda")
    assert uit.startswith("Vandaag (") and "Morgen (" in uit


def test_kosten(maak_terminal):
    t, _ = maak_terminal([tekst("Hoi")])
    assert "nog niets gekost" in t.verwerk("/kosten")
    t.verwerk("hallo")
    assert "totaal" in t.verwerk("/kosten")


def test_overige_opdrachten(maak_terminal):
    t, o = maak_terminal()
    assert "/ja <nummer>" in t.verwerk("/hulp")
    assert "# Over Tymo" in t.verwerk("/geheugen")
    oud = o.brain.gesprek_id
    t.verwerk("/nieuw")
    assert o.brain.gesprek_id != oud
    assert t.verwerk("/vlieg").startswith("Onbekende opdracht")
    assert t.verwerk("   ") == ""
    assert t.verwerk("/stop") is None


def test_main_met_een_opdracht(inst, monkeypatch, capsys):
    monkeypatch.setattr(cli, "laad_instellingen", lambda: inst)
    monkeypatch.setattr(cli, "stel_logging_in", lambda *a, **k: None)
    assert cli.main(["/wachtrij"]) == 0
    assert capsys.readouterr().out == "Er staan geen voorstellen open.\n"
