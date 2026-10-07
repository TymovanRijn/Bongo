from datetime import date, datetime

import pytest
from nep_claude import TZ, tekst

from assistent.calendar_backend import AgendaFout
from assistent.planner import Planner, is_nacht


def om(dag: int, uur: int, minuut: int = 0) -> datetime:
    return datetime(2026, 10, dag, uur, minuut, tzinfo=TZ)


@pytest.mark.parametrize(
    "tijd, nacht",
    [(om(8, 22, 59), False), (om(8, 23, 0), True), (om(9, 3, 0), True), (om(9, 6, 59), True), (om(9, 7, 0), False)],
)
def test_is_nacht_over_middernacht(tijd, nacht):
    assert is_nacht(tijd, "23:00", "07:00") is nacht


def test_is_nacht_zonder_middernacht():
    assert is_nacht(om(8, 14, 0), "13:00", "15:00")
    assert not is_nacht(om(8, 16, 0), "13:00", "15:00")


def test_ochtendoverzicht_een_keer_per_dag(maak):
    o, nep = maak([tekst("Goedemorgen Tymo!")])
    meldingen = []
    planner = Planner(o, bij_wijziging=lambda: meldingen.append(1), scherm=lambda aan: None)

    planner.tik(om(8, 7, 0))  # te vroeg
    assert nep.verzoeken == []
    planner.tik(om(8, 7, 31))
    planner.tik(om(8, 7, 45))  # al gedaan
    assert len(nep.verzoeken) == 1
    assert planner.ochtendoverzicht(date(2026, 10, 8))["tekst"] == "Goedemorgen Tymo!"
    assert meldingen  # het scherm hoort het meteen


def test_geen_ochtendoverzicht_meer_s_middags(maak):
    o, nep = maak()
    Planner(o, scherm=lambda aan: None).tik(om(8, 15, 0))
    assert nep.verzoeken == []


def test_na_een_fout_niet_elke_twintig_seconden_opnieuw(maak, monkeypatch):
    o, _ = maak()
    pogingen = []

    def kapot(*a, **k):
        pogingen.append(1)
        raise AgendaFout("iCloud onbereikbaar")

    monkeypatch.setattr(o.agenda, "afspraken", kapot)
    planner = Planner(o, scherm=lambda aan: None)
    planner.tik(om(8, 7, 31))
    planner.tik(om(8, 7, 32))
    assert len(pogingen) == 1
    planner.tik(om(8, 7, 42))
    assert len(pogingen) == 2


def test_scherm_uit_en_aan(maak):
    o, _ = maak(nacht_scherm_uit=True)
    scherm = []
    planner = Planner(o, scherm=scherm.append)
    planner.tik(om(8, 22, 59))  # opstarten: niets forceren
    planner.tik(om(8, 23, 0))
    planner.tik(om(8, 23, 30))
    planner.tik(om(9, 7, 0))
    assert scherm == [False, True]


def test_scherm_blijft_met_rust_als_het_uit_staat(maak):
    o, _ = maak(nacht_scherm_uit=False)
    scherm = []
    planner = Planner(o, scherm=scherm.append)
    planner.tik(om(8, 22, 59))
    planner.tik(om(8, 23, 0))
    assert scherm == []


def test_logboek_opruimen(maak):
    o, _ = maak()
    with o.db.verbinding() as con:
        con.execute("INSERT INTO gebeurtenissen (tijd, soort, inhoud) VALUES ('2020-01-01T10:00:00+01:00', 'vraag', 'oud')")
    Planner(o, scherm=lambda aan: None).tik(om(8, 3, 5))
    assert [g["inhoud"] for g in o.logboek.recent() if g["inhoud"] == "oud"] == []


def test_ochtendoverzicht_uitspreken(maak):
    o, _ = maak([tekst("Goedemorgen Tymo!")], ochtend_uitspreken=True)
    gezegd = []
    spraak = type("NepSpraak", (), {"zeg": lambda self, t: gezegd.append(t) or True})()
    Planner(o, scherm=lambda aan: None, spraak=spraak).tik(om(8, 7, 31))
    assert gezegd == ["Goedemorgen Tymo!"]
