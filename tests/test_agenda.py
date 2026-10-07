"""De agenda's: welke Bongo leest, waarin hij schrijft, en abonnementen (zoals een lesrooster)."""

from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace

import pytest
from icalendar import Calendar
from nep_claude import TZ

from assistent.calendar_backend import (
    Abonnement,
    AgendaFout,
    ICloudAgenda,
    MetAbonnementen,
    MockAgenda,
    agenda_overzicht,
    maak_agenda,
)
from assistent.config import laad_instellingen

ROOSTER = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Hogeschool//Rooster//NL
BEGIN:VEVENT
UID:college-1@hogeschool
DTSTART;TZID=Europe/Amsterdam:20301007T090000
DTEND;TZID=Europe/Amsterdam:20301007T110000
RRULE:FREQ=WEEKLY;COUNT=10
SUMMARY:Programmeren 2
LOCATION:Lokaal 3.14
END:VEVENT
BEGIN:VEVENT
UID:tentamen@hogeschool
DTSTART;VALUE=DATE:20301018
DTEND;VALUE=DATE:20301019
SUMMARY:Tentamenweek
END:VEVENT
END:VCALENDAR
"""


def _t(tekst):
    return datetime.fromisoformat(tekst).replace(tzinfo=TZ)


class NepOphalen:
    def __init__(self, *antwoorden):
        self.antwoorden = list(antwoorden)
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        antwoord = self.antwoorden.pop(0) if len(self.antwoorden) > 1 else self.antwoorden[0]
        if isinstance(antwoord, Exception):
            raise antwoord
        return antwoord


# ---- abonnementen ------------------------------------------------------------------------
def test_abonnement_met_een_wekelijks_college():
    ophalen = NepOphalen(ROOSTER)
    rooster = Abonnement("Hogeschool", "webcal://rooster.example.nl/ics/geheim", TZ, haal_op=ophalen)
    afspraken = rooster.afspraken(_t("2030-10-14T00:00"), _t("2030-10-21T00:00"))

    assert ophalen.urls == ["https://rooster.example.nl/ics/geheim"]  # webcal:// is gewoon https://
    assert [(a.titel, a.start, a.hele_dag) for a in afspraken] == [
        ("Programmeren 2", _t("2030-10-14T09:00"), False),  # de tweede week van de herhaling
        ("Tentamenweek", _t("2030-10-18T00:00"), True),
    ]
    assert afspraken[0].agenda == "Hogeschool" and afspraken[0].locatie == "Lokaal 3.14"


def test_abonnement_wordt_niet_elke_keer_opgehaald():
    ophalen = NepOphalen(ROOSTER, OSError("geen internet"))
    rooster = Abonnement("Hogeschool", "https://rooster.example.nl/ics", TZ, haal_op=ophalen)
    rooster.afspraken(_t("2030-10-07T00:00"), _t("2030-10-08T00:00"))
    rooster.afspraken(_t("2030-10-07T00:00"), _t("2030-10-08T00:00"))
    assert len(ophalen.urls) == 1

    rooster._gehaald -= Abonnement.CACHE_SECONDEN + 1  # een kwartier later, en het internet is weg
    assert rooster.afspraken(_t("2030-10-07T00:00"), _t("2030-10-08T00:00"))  # dan de vorige versie
    assert len(ophalen.urls) == 2


def test_abonnement_dat_nooit_lukte():
    rooster = Abonnement("Hogeschool", "https://rooster.example.nl/ics", TZ, haal_op=NepOphalen(OSError("404")))
    with pytest.raises(AgendaFout, match="Hogeschool"):
        rooster.afspraken(_t("2030-10-07T00:00"), _t("2030-10-08T00:00"))


def test_agenda_met_abonnementen(tmp_path):
    rooster = Abonnement("Hogeschool", "https://x", TZ, haal_op=NepOphalen(ROOSTER))
    agenda = MetAbonnementen(MockAgenda(tmp_path / "agenda.json", TZ), [rooster])
    agenda.voeg_toe("Sporten", _t("2030-10-07T08:00"), _t("2030-10-07T08:45"), agenda="Privé")

    dag = agenda.afspraken(_t("2030-10-07T00:00"), _t("2030-10-08T00:00"))
    assert [(a.titel, a.agenda) for a in dag] == [("Sporten", "Privé"), ("Programmeren 2", "Hogeschool")]
    assert "Hogeschool" not in agenda.agendas()  # een abonnement is alleen te lezen
    with pytest.raises(AgendaFout, match="alleen te lezen"):
        agenda.voeg_toe("Extra les", _t("2030-10-08T09:00"), _t("2030-10-08T10:00"), agenda="Hogeschool")


# ---- iCloud: welke agenda's (met nep-agenda's, zonder internet) ----------------------------
class NepICloudAgenda:
    def __init__(self, *afspraken):
        self.afspraken = list(afspraken)
        self.opgeslagen = []

    def search(self, start, end, event, expand):
        return [SimpleNamespace(icalendar_component=c) for c in self.afspraken]

    def save_event(self, ical):
        self.opgeslagen.append(Calendar.from_ical(ical))


def _event(titel, start, eind):
    cal = Calendar.from_ical(
        f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:{titel}\nDTSTART:{start}\nDTEND:{eind}\nSUMMARY:{titel}\nEND:VEVENT\nEND:VCALENDAR\n"
    )
    return cal.walk("VEVENT")[0]


@pytest.fixture
def icloud():
    werk = NepICloudAgenda(_event("Overleg", "20301007T080000Z", "20301007T090000Z"))
    iris = NepICloudAgenda(_event("Dienst Iris", "20301007T060000Z", "20301007T140000Z"))
    sport = NepICloudAgenda()
    agenda = ICloudAgenda("tymo@example.nl", "app-wachtwoord", "", (), TZ, niet_lezen=("rooster iris",))
    agenda._agendas = [(werk, "Werk"), (iris, "Rooster Iris"), (sport, "Sport")]
    return agenda, werk, sport


def test_icloud_leest_niet_wat_uitgesloten_is(icloud):
    agenda, _, _ = icloud
    assert [a.titel for a in agenda.afspraken(_t("2030-10-07T00:00"), _t("2030-10-08T00:00"))] == ["Overleg"]
    assert agenda.agendas() == ["Werk", "Sport"]


def test_icloud_schrijft_in_de_gekozen_agenda(icloud):
    agenda, werk, sport = icloud
    agenda.voeg_toe("Training", _t("2030-10-08T19:00"), _t("2030-10-08T20:30"), agenda="sport")
    assert len(sport.opgeslagen) == 1 and werk.opgeslagen == []
    [ev] = sport.opgeslagen[0].walk("VEVENT")
    assert str(ev["SUMMARY"]) == "Training"

    with pytest.raises(AgendaFout, match="Zeg in welke agenda"):  # geen standaard ingesteld, en niets gekozen
        agenda.voeg_toe("Iets", _t("2030-10-08T19:00"), _t("2030-10-08T20:00"))
    with pytest.raises(AgendaFout, match="Werk, Sport"):  # in een uitgesloten agenda schrijft hij ook niet
        agenda.voeg_toe("Iets", _t("2030-10-08T19:00"), _t("2030-10-08T20:00"), agenda="Rooster Iris")


def test_lijstjes_met_herinneringen_tellen_niet_mee():
    assert ICloudAgenda._heeft_afspraken(SimpleNamespace(get_supported_components=lambda: ["VEVENT", "VTODO"]))
    assert not ICloudAgenda._heeft_afspraken(SimpleNamespace(get_supported_components=lambda: ["VTODO"]))

    def kapot():
        raise OSError("server zegt niets")

    assert ICloudAgenda._heeft_afspraken(SimpleNamespace(get_supported_components=kapot))


# ---- instellingen ----------------------------------------------------------------------------
def test_instellingen_voor_de_agenda(monkeypatch):
    monkeypatch.setenv("ICLOUD_NIET_LEZEN", "Rooster Iris, Verjaardagen")
    monkeypatch.setenv(
        "AGENDA_ABONNEMENTEN", "Hogeschool=webcal://rooster.example.nl/ics?id=12&sleutel=ab=c, Voetbal=https://club.example/ics"
    )
    inst = laad_instellingen()
    assert inst.icloud_niet_lezen == ("Rooster Iris", "Verjaardagen")
    assert inst.abonnementen == (
        ("Hogeschool", "webcal://rooster.example.nl/ics?id=12&sleutel=ab=c"),  # een = in de link mag
        ("Voetbal", "https://club.example/ics"),
    )
    monkeypatch.setenv("AGENDA_ABONNEMENTEN", "alleen-een-naam")
    with pytest.raises(ValueError, match="naam=link"):
        laad_instellingen()


def test_maak_agenda_met_abonnement(inst):
    agenda = maak_agenda(
        replace(inst, calendar_backend="icloud", icloud_gebruiker="t", icloud_wachtwoord="w",
                icloud_niet_lezen=("Rooster Iris",), abonnementen=(("Hogeschool", "https://x"),))
    )
    assert isinstance(agenda, MetAbonnementen)
    # Staat het abonnement toch ook in iCloud, dan leest hij het niet twee keer.
    assert agenda.agenda.niet_lezen == {"rooster iris", "hogeschool"}
    assert isinstance(maak_agenda(inst), MockAgenda)  # zonder abonnementen: gewoon de agenda


# ---- python -m assistent.kern agendas ----------------------------------------------------------
def test_overzicht_van_de_agendas(icloud):
    agenda, _, _ = icloud
    agenda.standaard = "Werk"
    kapot = Abonnement("Voetbal", "https://x", TZ, haal_op=NepOphalen(OSError("404")))
    rooster = Abonnement("Hogeschool", "https://x", TZ, haal_op=NepOphalen(ROOSTER))
    regels = agenda_overzicht(MetAbonnementen(agenda, [rooster, kapot]), _t("2030-10-07T08:00"))
    assert [r.split()[0] for r in regels] == ["Werk", "Rooster", "Sport", "Hogeschool", "Voetbal"]
    assert "de standaard" in regels[0] and "niet gelezen" in regels[1] and "lezen en schrijven" in regels[2]
    assert "1 afspraak in" in regels[3]  # het college van 7 oktober; dat van 14 oktober valt er net buiten
    assert "WERKT NIET" in regels[4] and "404" in regels[4]


def test_overzicht_zonder_standaard(icloud):
    agenda, _, _ = icloud
    assert agenda_overzicht(agenda, _t("2030-10-07T08:00"))[-1].startswith("Er is geen standaardagenda")
    agenda.standaard = "Bongo"
    assert "bestaat niet" in agenda_overzicht(agenda, _t("2030-10-07T08:00"))[-1]


def test_kern_agendas_commando(inst, monkeypatch, capsys):
    from assistent import kern

    monkeypatch.setattr(kern, "laad_instellingen", lambda: inst)
    assert kern.main(["agendas"]) == 0
    uit = capsys.readouterr().out
    assert "Agenda: mock" in uit and "Privé" in uit and "(de standaard)" in uit
