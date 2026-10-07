import json
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

TZ = ZoneInfo("Europe/Amsterdam")


@pytest.fixture
def o(maak):
    onderdelen, _ = maak()
    return onderdelen


def test_agenda_lezen_geeft_afspraken_als_json(o):
    o.agenda.voeg_toe("Kapper", _t("2030-03-04T10:00"), _t("2030-03-04T10:30"), locatie="Dorpsstraat 1")
    res = o.tools.voer_uit("agenda_lezen", {"van": "2030-03-04", "tot": "2030-03-04"})
    assert not res.is_fout
    assert json.loads(res.inhoud) == {
        "afspraken": [
            {"wanneer": "maandag 4 maart 2030, 10:00-10:30", "titel": "Kapper", "locatie": "Dorpsstraat 1", "agenda": "Privé"}
        ],
        "agendas": ["Privé", "Werk", "School"],  # zodat Claude weet waarin hij kan voorstellen
        "standaard_agenda": "Privé",
    }


def test_agenda_lezen_zonder_afspraken(o):
    res = o.tools.voer_uit("agenda_lezen", {"van": "2030-03-05", "tot": "2030-03-06"})
    uit = json.loads(res.inhoud)
    assert uit["afspraken"] == [] and uit["uitleg"].startswith("Geen afspraken") and uit["agendas"]


@pytest.mark.parametrize(
    "invoer, fout",
    [
        ({"van": "morgen", "tot": "2030-03-05"}, "JJJJ-MM-DD"),
        ({"van": "2030-03-05", "tot": "2030-03-04"}, "voor 'van'"),
        ({"van": "2030-01-01", "tot": "2030-06-01"}, "twee maanden"),
    ],
)
def test_agenda_lezen_foute_invoer_gaat_terug_naar_claude(o, invoer, fout):
    res = o.tools.voer_uit("agenda_lezen", invoer)
    assert res.is_fout and fout in res.inhoud


def test_afspraak_voorstellen_zet_niets_in_de_agenda(o):
    res = o.tools.voer_uit("afspraak_voorstellen", _afspraak(), bron="cli")
    assert not res.is_fout
    assert "NOG NIET" in res.inhoud
    [voorstel] = o.wachtrij.open()
    assert res.voorstel_ids == [voorstel.id]
    assert voorstel.samenvatting == "Afspraak: Tandarts, maandag 4 maart 2030, 10:00-10:30, Centrum (agenda Privé)"
    assert voorstel.gegevens["start"] == "2030-03-04T10:00:00+01:00"
    assert o.agenda.afspraken(_t("2030-03-04T00:00"), _t("2030-03-05T00:00")) == []


def test_afspraak_in_de_agenda_die_erbij_past(o):
    [vid] = o.tools.voer_uit("afspraak_voorstellen", _afspraak(titel="Tentamen", agenda="school")).voorstel_ids
    v = o.wachtrij.get(vid)
    assert v.gegevens["agenda"] == "School" and v.samenvatting.endswith("(agenda School)")  # hoofdletters maken niet uit
    o.wachtrij.approve(vid)
    [a] = o.agenda.afspraken(_t("2030-03-04T00:00"), _t("2030-03-05T00:00"))
    assert a.titel == "Tentamen" and a.agenda == "School"


def test_afspraak_in_een_agenda_die_niet_bestaat(o):
    res = o.tools.voer_uit("afspraak_voorstellen", _afspraak(agenda="Rooster Iris"))
    assert res.is_fout and "Rooster Iris" in res.inhoud and "Privé, Werk, School" in res.inhoud
    assert o.wachtrij.open() == []  # meteen gezegd, niet pas als Tymo op "ja" drukt


def test_hele_dag_eindigt_aan_het_eind_van_de_laatste_dag(o):
    res = o.tools.voer_uit("afspraak_voorstellen", _afspraak(start="2030-03-04", eind="2030-03-05", hele_dag=True))
    [voorstel] = o.wachtrij.open()
    assert voorstel.gegevens["start"] == "2030-03-04T00:00:00+01:00"
    assert voorstel.gegevens["eind"] == "2030-03-06T00:00:00+01:00"
    assert "tot en met dinsdag 5 maart 2030, hele dag" in res.inhoud


@pytest.mark.parametrize(
    "anders, fout",
    [
        ({"eind": "2030-03-04T09:00"}, "na het begin"),
        ({"start": "2020-03-04T10:00", "eind": "2020-03-04T11:00"}, "verleden"),
        ({"titel": "   "}, "leeg"),
        ({"eind": "2030-04-04T10:00"}, "twee weken"),
    ],
)
def test_afspraak_voorstellen_weigert_onzin(o, anders, fout):
    res = o.tools.voer_uit("afspraak_voorstellen", _afspraak(**anders))
    assert res.is_fout and fout in res.inhoud
    assert o.wachtrij.open() == []


def test_onthouden_voorstellen_en_dubbel(o):
    res = o.tools.voer_uit("onthouden_voorstellen", {"feit": "Houdt van koffie."})
    assert res.voorstel_ids
    o.wachtrij.approve(res.voorstel_ids[0])
    assert "Houdt van koffie." in o.geheugen.lees()

    dubbel = o.tools.voer_uit("onthouden_voorstellen", {"feit": "houdt van koffie"})
    assert dubbel.voorstel_ids == [] and "staat al" in dubbel.inhoud


def test_vergeten_voorstellen(o):
    assert o.tools.voer_uit("vergeten_voorstellen", {"feit": "Bestaat niet"}).is_fout
    o.geheugen.voeg_toe("Houdt van koffie")
    res = o.tools.voer_uit("vergeten_voorstellen", {"feit": "houdt van koffie"})
    o.wachtrij.approve(res.voorstel_ids[0])
    assert "koffie" not in o.geheugen.lees()


def test_onbekende_tool(o):
    assert o.tools.voer_uit("raket_lanceren", {}).is_fout


def test_onverwachte_fout_gaat_als_fout_terug_naar_claude(o, monkeypatch):
    """Een kapotte database mag de agent-lus niet breken: Claude hoort dat het misging."""

    def kapot(*a, **k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(o.wachtrij, "voorstel", kapot)
    res = o.tools.voer_uit("afspraak_voorstellen", _afspraak())
    assert res.is_fout
    assert "database is locked" not in res.inhoud  # geen technische details naar het model
    assert res.voorstel_ids == []


# ---- hulpjes ----------------------------------------------------------------------------
def _t(tekst):
    return datetime.fromisoformat(tekst).replace(tzinfo=TZ)


def _afspraak(**anders):
    invoer = {
        "titel": "Tandarts",
        "start": "2030-03-04T10:00",
        "eind": "2030-03-04T10:30",
        "hele_dag": False,
        "locatie": "Centrum",
        "notitie": None,
    }
    invoer.update(anders)
    return invoer


# ---- herstel met de echte controles ------------------------------------------------------
def _stroomstoring(o, voorstel_id):
    with o.db.verbinding() as con:
        con.execute("UPDATE voorstellen SET status = 'bezig', afgehandeld = '2026-01-01T00:00:00+01:00' WHERE id = ?", (voorstel_id,))


def test_herstel_afspraak_die_al_in_de_agenda_stond(o):
    [vid] = o.tools.voer_uit("afspraak_voorstellen", _afspraak()).voorstel_ids
    v = o.wachtrij.get(vid)
    o.agenda.voeg_toe("Tandarts", _t("2030-03-04T10:00"), _t("2030-03-04T10:30"), uid=v.gegevens["uid"])
    _stroomstoring(o, vid)
    assert [h.status for h in o.wachtrij.herstel_onderbroken()] == ["uitgevoerd"]


def test_herstel_afspraak_die_er_nog_niet_in_stond(o):
    [vid] = o.tools.voer_uit("afspraak_voorstellen", _afspraak()).voorstel_ids
    _stroomstoring(o, vid)
    assert [h.status for h in o.wachtrij.herstel_onderbroken()] == ["open"]
    o.wachtrij.approve(vid)
    afspraken = o.agenda.afspraken(_t("2030-03-04T00:00"), _t("2030-03-05T00:00"))
    assert [a.uid for a in afspraken] == [o.wachtrij.get(vid).gegevens["uid"]]  # precies één keer


def test_herstel_onthouden(o):
    [vid] = o.tools.voer_uit("onthouden_voorstellen", {"feit": "Houdt van thee"}).voorstel_ids
    o.geheugen.voeg_toe("Houdt van thee")  # het lukte nog net voor de stroom uitviel
    _stroomstoring(o, vid)
    assert [h.status for h in o.wachtrij.herstel_onderbroken()] == ["uitgevoerd"]
