import threading
from datetime import datetime, timedelta

import pytest

from assistent.db import Database
from assistent.wachtrij import Wachtrij, WachtrijFout


@pytest.fixture
def uitgevoerd():
    return []


@pytest.fixture
def wachtrij(tmp_path, uitgevoerd):
    def opslaan(g):
        uitgevoerd.append(g)
        return f"gedaan: {g['x']}"

    def kapot(g):
        raise RuntimeError("agenda onbereikbaar")

    return Wachtrij(Database(tmp_path / "db.sqlite3"), {"test": opslaan, "kapot": kapot})


def test_voorstel_staat_open_tot_iemand_het_goedkeurt(wachtrij, uitgevoerd):
    v = wachtrij.voorstel("test", "Iets doen", {"x": 1}, bron="cli")
    assert v.status == "open"
    assert [o.id for o in wachtrij.open()] == [v.id]
    assert uitgevoerd == []  # nog niets gebeurd

    klaar = wachtrij.approve(v.id, via="test")
    assert klaar.status == "uitgevoerd"
    assert klaar.resultaat == "gedaan: 1"
    assert klaar.afgehandeld_via == "test"
    assert uitgevoerd == [{"x": 1}]
    assert wachtrij.open() == []


def test_goedkeuren_kan_maar_een_keer(wachtrij):
    v = wachtrij.voorstel("test", "Iets doen", {"x": 1})
    wachtrij.approve(v.id)
    with pytest.raises(WachtrijFout, match="niet meer open"):
        wachtrij.approve(v.id)
    with pytest.raises(WachtrijFout, match="niet meer open"):
        wachtrij.reject(v.id)


def test_twee_tikken_tegelijk_voeren_maar_een_keer_uit(wachtrij, uitgevoerd):
    v = wachtrij.voorstel("test", "Iets doen", {"x": 1})
    fouten = []

    def tik():
        try:
            wachtrij.approve(v.id)
        except WachtrijFout as e:
            fouten.append(e)

    draden = [threading.Thread(target=tik) for _ in range(8)]
    for d in draden:
        d.start()
    for d in draden:
        d.join()
    assert len(uitgevoerd) == 1
    assert len(fouten) == 7


def test_afwijzen_voert_niets_uit(wachtrij, uitgevoerd):
    v = wachtrij.voorstel("test", "Iets doen", {"x": 1})
    assert wachtrij.reject(v.id, via="web").status == "afgewezen"
    assert uitgevoerd == []
    assert [a.id for a in wachtrij.afgehandeld()] == [v.id]


def test_mislukte_uitvoering_wordt_bewaard(wachtrij):
    v = wachtrij.voorstel("kapot", "Gaat mis", {})
    klaar = wachtrij.approve(v.id)
    assert klaar.status == "mislukt"
    assert "agenda onbereikbaar" in klaar.resultaat


def test_onbekende_soort_wordt_geweigerd(wachtrij):
    with pytest.raises(WachtrijFout, match="onbekende soort"):
        wachtrij.voorstel("raket_lanceren", "Nee", {})


def test_onbekend_nummer(wachtrij):
    with pytest.raises(WachtrijFout, match="bestaat niet"):
        wachtrij.approve(999)


# ---- vervallen ----------------------------------------------------------------------------
def test_laat_vervallen(wachtrij, uitgevoerd):
    v = wachtrij.voorstel("test", "Iets doen", {"x": 1})
    klaar = wachtrij.laat_vervallen(v.id, "beurt mislukt")
    assert (klaar.status, klaar.resultaat, klaar.afgehandeld_via) == ("vervallen", "beurt mislukt", "systeem")
    with pytest.raises(WachtrijFout):
        wachtrij.approve(v.id)
    assert uitgevoerd == []


# ---- herstel na een stroomstoring ------------------------------------------------------
def _hang_op_bezig(wachtrij, voorstel_id, minuten_geleden=10):
    """Doe alsof de stroom uitviel terwijl dit voorstel werd uitgevoerd."""
    tijd = (datetime.now().astimezone() - timedelta(minutes=minuten_geleden)).isoformat(timespec="seconds")
    with wachtrij.db.verbinding() as con:
        con.execute("UPDATE voorstellen SET status = 'bezig', afgehandeld = ? WHERE id = ?", (tijd, voorstel_id))


@pytest.mark.parametrize("gedaan, status", [(True, "uitgevoerd"), (False, "open"), (None, "onbekend")])
def test_herstel_onderbroken(tmp_path, gedaan, status):
    wachtrij = Wachtrij(Database(tmp_path / "db.sqlite3"), {"test": lambda g: "ok"}, controles={"test": lambda g: gedaan})
    v = wachtrij.voorstel("test", "Iets doen", {})
    _hang_op_bezig(wachtrij, v.id)
    [hersteld] = wachtrij.herstel_onderbroken()
    assert hersteld.status == status
    if status == "open":
        assert wachtrij.approve(v.id).status == "uitgevoerd"  # Tymo kan weer kiezen


def test_herstel_zonder_controle_of_met_kapotte_controle(tmp_path):
    def kapot(g):
        raise RuntimeError("iCloud onbereikbaar")

    wachtrij = Wachtrij(Database(tmp_path / "db.sqlite3"), {"a": lambda g: "", "b": lambda g: ""}, controles={"b": kapot})
    for soort in ("a", "b"):
        _hang_op_bezig(wachtrij, wachtrij.voorstel(soort, soort, {}).id)
    assert [v.status for v in wachtrij.herstel_onderbroken()] == ["onbekend", "onbekend"]


def test_herstel_laat_een_net_begonnen_uitvoering_met_rust(tmp_path):
    """Misschien voert de CLI dit voorstel op dit moment netjes uit."""
    wachtrij = Wachtrij(Database(tmp_path / "db.sqlite3"), {"test": lambda g: ""}, controles={"test": lambda g: False})
    v = wachtrij.voorstel("test", "Iets doen", {})
    _hang_op_bezig(wachtrij, v.id, minuten_geleden=0)
    assert wachtrij.herstel_onderbroken() == []
    assert wachtrij.get(v.id).status == "bezig"
