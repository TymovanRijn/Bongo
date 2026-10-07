import threading
import time

import pytest

from assistent.geheugen import SECTIE, Geheugen


@pytest.fixture
def geheugen(tmp_path):
    return Geheugen(tmp_path / "over_mij.md")


def test_nieuw_bestand_krijgt_de_standaardtekst(geheugen):
    assert SECTIE in geheugen.lees()


def test_voeg_toe_zet_het_feit_in_de_juiste_sectie(geheugen):
    geheugen.schrijf(geheugen.lees() + "\n## Later toegevoegd door Tymo\n\n- iets anders\n")
    regel = geheugen.voeg_toe("Werkt op   dinsdag thuis.")
    assert regel.startswith("- Werkt op dinsdag thuis. (")
    tekst = geheugen.lees()
    # Onder de sectie van de assistent, niet onder de kop die erna komt.
    assert tekst.index(SECTIE) < tekst.index(regel) < tekst.index("## Later toegevoegd door Tymo")


def test_zoek_regel_negeert_streepje_datum_en_hoofdletters(geheugen):
    regel = geheugen.voeg_toe("Houdt van koffie")
    assert geheugen.zoek_regel("houdt van koffie.") == regel
    assert geheugen.zoek_regel("houdt van thee") is None
    assert geheugen.zoek_regel("ko") is None  # te kort om veilig te zoeken


def test_verwijder_en_vorige_versie(geheugen):
    geheugen.voeg_toe("Houdt van koffie")
    voor = geheugen.lees()
    geheugen.verwijder("Houdt van koffie")
    assert "koffie" not in geheugen.lees()
    vorige = geheugen.pad.with_suffix(".md.vorige").read_text(encoding="utf-8")
    assert vorige == voor
    with pytest.raises(ValueError):
        geheugen.verwijder("Houdt van koffie")


def test_versie_verandert_als_het_bestand_verandert(geheugen):
    oud = geheugen.versie()
    time.sleep(0.01)
    geheugen.voeg_toe("Nieuw feit")
    assert geheugen.versie() != oud


def test_gelijktijdig_onthouden_verliest_niets(geheugen, monkeypatch):
    """Twee goedkeuringen tegelijk (scherm en webapp) mogen elkaars feit niet overschrijven."""
    echte_lees = Geheugen.lees

    def trage_lees(self):
        tekst = echte_lees(self)
        time.sleep(0.005)  # maakt het moment tussen lezen en schrijven groter
        return tekst

    monkeypatch.setattr(Geheugen, "lees", trage_lees)
    draden = [threading.Thread(target=geheugen.voeg_toe, args=(f"Feit nummer {i}",)) for i in range(10)]
    for d in draden:
        d.start()
    for d in draden:
        d.join()
    tekst = geheugen.lees()
    assert [i for i in range(10) if f"Feit nummer {i} " not in tekst] == []
