"""Agenda: een nep-agenda om mee te testen en iCloud via CalDAV, met dezelfde interface.

Daarnaast abonnementen (zoals een lesrooster): agenda's die je via een link volgt. Die zitten niet
in iCloud's CalDAV, dus die leest Bongo rechtstreeks via hun link (MetAbonnementen).
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)


class AgendaFout(Exception):
    pass


@dataclass
class Afspraak:
    titel: str
    start: datetime
    eind: datetime
    hele_dag: bool = False
    locatie: str | None = None
    notitie: str | None = None
    agenda: str | None = None
    uid: str | None = None

    def als_dict(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["eind"] = self.eind.isoformat()
        return d


class AgendaBackend(Protocol):
    naam: str
    standaard: str | None  # waar een afspraak heen gaat als niet gezegd is in welke agenda

    def afspraken(self, van: datetime, tot: datetime) -> list[Afspraak]: ...

    def agendas(self) -> list[str]:
        """De agenda's waarin Bongo afspraken mag zetten."""
        ...

    def voeg_toe(
        self,
        titel: str,
        start: datetime,
        eind: datetime,
        locatie: str | None = None,
        notitie: str | None = None,
        hele_dag: bool = False,
        uid: str | None = None,
        agenda: str | None = None,
    ) -> str: ...


def _overlapt(a: Afspraak, van: datetime, tot: datetime) -> bool:
    return a.start < tot and a.eind > van


def _naar_lokaal(waarde, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Een tijd uit een agenda als datetime in onze tijdzone, plus: is het een hele dag?"""
    if isinstance(waarde, datetime):
        if waarde.tzinfo is None:
            return waarde.replace(tzinfo=tz), False
        return waarde.astimezone(tz), False
    if isinstance(waarde, date):
        return datetime(waarde.year, waarde.month, waarde.day, tzinfo=tz), True
    raise AgendaFout(f"onbekend tijdformaat: {waarde!r}")


def _afspraak_uit(comp, agenda_naam: str, tz: ZoneInfo) -> Afspraak | None:
    """Een VEVENT uit een iCalendar-bestand als Afspraak."""
    if comp is None or "DTSTART" not in comp:
        return None
    start, hele_dag = _naar_lokaal(comp["DTSTART"].dt, tz)
    if "DTEND" in comp:
        eind, _ = _naar_lokaal(comp["DTEND"].dt, tz)
    elif "DURATION" in comp:
        eind = start + comp["DURATION"].dt
    else:
        eind = start + (timedelta(days=1) if hele_dag else timedelta(hours=1))
    return Afspraak(
        titel=str(comp.get("SUMMARY", "(geen titel)")),
        start=start,
        eind=eind,
        hele_dag=hele_dag,
        locatie=str(comp["LOCATION"]) if comp.get("LOCATION") else None,
        notitie=str(comp["DESCRIPTION"])[:500] if comp.get("DESCRIPTION") else None,
        agenda=agenda_naam,
        uid=str(comp.get("UID", "")) or None,
    )


def kies_agenda(agenda: str | None, standaard: str | None, beschikbaar: list[str]) -> str:
    """In welke agenda een nieuwe afspraak komt. Hoofdletters maken niet uit ("werk" is "Werk")."""
    gevraagd = agenda or standaard
    if not gevraagd:
        raise AgendaFout(f"Zeg in welke agenda de afspraak moet. Er zijn: {', '.join(beschikbaar)}")
    for naam in beschikbaar:
        if naam.casefold() == gevraagd.strip().casefold():
            return naam
    raise AgendaFout(f"Agenda '{gevraagd}' bestaat niet of is alleen te lezen. Er zijn: {', '.join(beschikbaar)}")


# ---------------------------------------------------------------------------------------
# Nep-agenda: een JSON-bestand in data/, zodat kern en CLI dezelfde afspraken zien.
# ---------------------------------------------------------------------------------------
class MockAgenda:
    naam = "mock"
    AGENDAS = ("Privé", "Werk", "School")
    standaard = "Privé"

    def __init__(self, pad: Path, tz: ZoneInfo):
        self.pad = Path(pad)
        self.tz = tz
        self._slot = threading.Lock()
        if not self.pad.exists():
            self._bewaar(self._voorbeelden())

    def _voorbeelden(self) -> list[Afspraak]:
        vandaag = datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0)

        def op(dag: int, uur: int, minuut: int = 0) -> datetime:
            return vandaag + timedelta(days=dag, hours=uur, minutes=minuut)

        return [
            Afspraak("Stand-up met het team", op(0, 9, 30), op(0, 9, 45), agenda="Werk", uid="mock-1"),
            Afspraak("Lunch met Sanne", op(0, 12, 30), op(0, 13, 30), locatie="Café de Zaak", agenda="Privé", uid="mock-2"),
            Afspraak("Tandarts", op(1, 10), op(1, 10, 30), locatie="Tandartspraktijk Centrum", agenda="Privé", uid="mock-3"),
            Afspraak("Sporten", op(1, 18), op(1, 19), agenda="Privé", uid="mock-4"),
            Afspraak("Verjaardag oma", op(3, 0), op(4, 0), hele_dag=True, agenda="Privé", uid="mock-5"),
        ]

    def _laad(self) -> list[Afspraak]:
        ruw = json.loads(self.pad.read_text(encoding="utf-8"))
        uit = []
        for d in ruw:
            d["start"] = datetime.fromisoformat(d["start"])
            d["eind"] = datetime.fromisoformat(d["eind"])
            uit.append(Afspraak(**d))
        return uit

    def _bewaar(self, afspraken: list[Afspraak]) -> None:
        self.pad.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.pad.with_suffix(".tmp")
        tmp.write_text(json.dumps([a.als_dict() for a in afspraken], ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.pad)

    def afspraken(self, van: datetime, tot: datetime) -> list[Afspraak]:
        with self._slot:
            alles = self._laad()
        return sorted((a for a in alles if _overlapt(a, van, tot)), key=lambda a: a.start)

    def agendas(self) -> list[str]:
        return list(self.AGENDAS)

    def voeg_toe(self, titel, start, eind, locatie=None, notitie=None, hele_dag=False, uid=None, agenda=None) -> str:
        agenda = kies_agenda(agenda, self.standaard, self.agendas())
        uid = uid or f"mock-{uuid.uuid4().hex[:8]}"
        with self._slot:
            alles = self._laad()
            alles.append(Afspraak(titel, start, eind, hele_dag, locatie, notitie, agenda, uid))
            self._bewaar(alles)
        return uid


# ---------------------------------------------------------------------------------------
# iCloud via CalDAV. Inloggen met Apple ID + app-specifiek wachtwoord (account.apple.com).
# ---------------------------------------------------------------------------------------
class ICloudAgenda:
    naam = "icloud"
    URL = "https://caldav.icloud.com"
    CACHE_SECONDEN = 60

    def __init__(
        self,
        gebruiker: str,
        wachtwoord: str,
        standaard: str,
        lees_agendas: tuple[str, ...],
        tz: ZoneInfo,
        niet_lezen: tuple[str, ...] = (),
    ):
        if not gebruiker or not wachtwoord:
            raise AgendaFout("ICLOUD_USERNAME en ICLOUD_APP_PASSWORD moeten in .env staan")
        self.gebruiker = gebruiker
        self.wachtwoord = wachtwoord
        self.standaard = standaard or None
        self.lees_agendas = lees_agendas
        self.niet_lezen = {n.casefold() for n in niet_lezen}
        self.tz = tz
        self._agendas = None
        self._slot = threading.Lock()
        self._cache: dict[tuple, tuple[float, list[Afspraak]]] = {}

    def _alle_agendas(self):
        if self._agendas is None:
            import caldav

            client = caldav.DAVClient(url=self.URL, username=self.gebruiker, password=self.wachtwoord, timeout=20)
            try:
                # Namen meteen ophalen: elke get_display_name() is een netwerkverzoek.
                agendas = [(c, c.get_display_name() or "") for c in client.principal().calendars()]
            except Exception as e:
                raise AgendaFout(f"Kan niet inloggen bij iCloud: {e}") from e
            # Alleen agenda's met afspraken: een lijst met herinneringen is ook een "calendar".
            self._agendas = [(c, naam) for c, naam in agendas if self._heeft_afspraken(c)]
        return self._agendas

    @staticmethod
    def _heeft_afspraken(agenda) -> bool:
        try:
            return "VEVENT" in agenda.get_supported_components()
        except Exception:
            return True  # niet te zeggen: dan maar wel

    def agendas(self) -> list[str]:
        """Bongo schrijft alleen in agenda's die hij ook leest (zo kan hij na een stroomstoring
        nakijken of een afspraak er al in staat)."""
        with self._slot:
            return [naam for _, naam in self._te_lezen()]

    def _te_lezen(self):
        agendas = [(c, naam) for c, naam in self._alle_agendas() if naam.casefold() not in self.niet_lezen]
        if not self.lees_agendas:
            return agendas
        gekozen = [(c, naam) for c, naam in agendas if naam in self.lees_agendas]
        return gekozen or agendas

    def afspraken(self, van: datetime, tot: datetime) -> list[Afspraak]:
        sleutel = (van.isoformat(), tot.isoformat())
        with self._slot:
            gecached = self._cache.get(sleutel)
            if gecached and time.monotonic() - gecached[0] < self.CACHE_SECONDEN:
                return list(gecached[1])
            uit: list[Afspraak] = []
            for agenda, naam in self._te_lezen():
                try:
                    events = agenda.search(start=van, end=tot, event=True, expand=True)
                except Exception as e:
                    raise AgendaFout(f"Kan agenda '{naam}' niet lezen: {e}") from e
                for ev in events:
                    afspraak = _afspraak_uit(ev.icalendar_component, naam, self.tz)
                    if afspraak and _overlapt(afspraak, van, tot):
                        uit.append(afspraak)
            uit.sort(key=lambda a: a.start)
            self._cache[sleutel] = (time.monotonic(), uit)
            return list(uit)

    def voeg_toe(self, titel, start, eind, locatie=None, notitie=None, hele_dag=False, uid=None, agenda=None) -> str:
        from icalendar import Calendar, Event

        with self._slot:
            te_lezen = self._te_lezen()
            gekozen = kies_agenda(agenda, self.standaard, [naam for _, naam in te_lezen])
            doel = [c for c, naam in te_lezen if naam == gekozen]

            uid = uid or f"{uuid.uuid4()}@bongo"
            ev = Event()
            ev.add("uid", uid)
            ev.add("dtstamp", datetime.now(timezone.utc))
            ev.add("summary", titel)
            if hele_dag:
                ev.add("dtstart", start.date())
                ev.add("dtend", eind.date() if eind.date() > start.date() else start.date() + timedelta(days=1))
            else:
                # UTC wordt door elke CalDAV-server begrepen; de iPhone toont het in lokale tijd.
                ev.add("dtstart", start.astimezone(timezone.utc))
                ev.add("dtend", eind.astimezone(timezone.utc))
            if locatie:
                ev.add("location", locatie)
            if notitie:
                ev.add("description", notitie)
            cal = Calendar()
            cal.add("prodid", "-//Bongo huisassistent//NL")
            cal.add("version", "2.0")
            cal.add_component(ev)
            try:
                doel[0].save_event(ical=cal.to_ical().decode("utf-8"))
            except Exception as e:
                raise AgendaFout(f"Kan afspraak niet opslaan in iCloud: {e}") from e
            self._cache.clear()
            return uid


# ---------------------------------------------------------------------------------------
# Abonnementen: agenda's die je via een link volgt (in Agenda op de Mac het zendmast-icoontje),
# zoals een lesrooster. Alleen lezen.
# ---------------------------------------------------------------------------------------
def _haal_op(url: str) -> bytes:
    import urllib.request

    verzoek = urllib.request.Request(url, headers={"User-Agent": "Bongo-huisassistent"})
    with urllib.request.urlopen(verzoek, timeout=20) as antwoord:
        return antwoord.read(20_000_000)  # hooguit 20 MB


class Abonnement:
    CACHE_SECONDEN = 15 * 60  # een rooster verandert niet elke minuut

    def __init__(self, naam: str, url: str, tz: ZoneInfo, haal_op=_haal_op):
        self.naam = naam
        # webcal:// is gewoon https:// met een ander naampje (zodat je Agenda-app hem opent).
        self.url = "https://" + url.removeprefix("webcal://") if url.startswith("webcal://") else url
        self.tz = tz
        self._haal_op = haal_op
        self._slot = threading.Lock()
        self._kalender = None
        self._gehaald = float("-inf")

    def _kalender_nu(self):
        from icalendar import Calendar

        with self._slot:
            if time.monotonic() - self._gehaald > self.CACHE_SECONDEN:
                try:
                    self._kalender = Calendar.from_ical(self._haal_op(self.url))
                    self._gehaald = time.monotonic()
                except Exception as e:
                    if self._kalender is None:
                        raise AgendaFout(f"Kan het abonnement '{self.naam}' niet ophalen: {e}") from e
                    log.warning("abonnement '%s' ophalen mislukt, ik gebruik de vorige versie: %s", self.naam, e)
                    self._gehaald = time.monotonic() - self.CACHE_SECONDEN + 60  # over een minuut opnieuw
            return self._kalender

    def afspraken(self, van: datetime, tot: datetime) -> list[Afspraak]:
        import recurring_ical_events

        kalender = self._kalender_nu()
        # Herhalende afspraken ("elke maandag college") worden hier losse afspraken.
        uit = []
        for comp in recurring_ical_events.of(kalender).between(van, tot):
            afspraak = _afspraak_uit(comp, self.naam, self.tz)
            if afspraak and _overlapt(afspraak, van, tot):
                uit.append(afspraak)
        return uit


class MetAbonnementen:
    """Een agenda plus abonnementen. Lezen gaat uit allebei, schrijven alleen in de agenda."""

    def __init__(self, agenda: AgendaBackend, abonnementen: list[Abonnement]):
        self.agenda = agenda
        self.abonnementen = abonnementen
        self.naam = agenda.naam

    @property
    def standaard(self) -> str | None:
        return self.agenda.standaard

    def afspraken(self, van: datetime, tot: datetime) -> list[Afspraak]:
        alles = list(self.agenda.afspraken(van, tot))
        for abonnement in self.abonnementen:
            alles.extend(abonnement.afspraken(van, tot))
        return sorted(alles, key=lambda a: a.start)

    def agendas(self) -> list[str]:
        return self.agenda.agendas()

    def voeg_toe(self, *args, **kwargs) -> str:
        return self.agenda.voeg_toe(*args, **kwargs)


def agenda_overzicht(agenda: AgendaBackend, nu: datetime) -> list[str]:
    """Voor `python -m assistent.kern agendas`: welke agenda's Bongo ziet, en wat hij ermee mag."""
    basis = agenda.agenda if isinstance(agenda, MetAbonnementen) else agenda
    schrijven = basis.agendas()
    with getattr(basis, "_slot", threading.Lock()):
        alle = [naam for _, naam in basis._alle_agendas()] if isinstance(basis, ICloudAgenda) else schrijven
    regels = []
    for naam in alle:
        if naam not in schrijven:
            regels.append(f"  {naam:24} niet gelezen (uitgesloten in .env)")
        else:
            regels.append(f"  {naam:24} lezen en schrijven" + (" (de standaard)" if naam == basis.standaard else ""))
    for abonnement in getattr(agenda, "abonnementen", []):
        try:
            aantal = len(abonnement.afspraken(nu, nu + timedelta(days=7)))
            hoeveel = "1 afspraak" if aantal == 1 else f"{aantal} afspraken"
            regels.append(f"  {abonnement.naam:24} alleen lezen (abonnement), {hoeveel} in de komende 7 dagen")
        except AgendaFout as e:
            regels.append(f"  {abonnement.naam:24} WERKT NIET: {e}")
    if not basis.standaard:
        regels.append("Er is geen standaardagenda (ICLOUD_CALENDAR_NAME): Bongo moet dan altijd zelf kiezen.")
    elif basis.standaard not in schrijven:
        regels.append(f"Let op: de standaardagenda '{basis.standaard}' bestaat niet (ICLOUD_CALENDAR_NAME).")
    return regels


def maak_agenda(instellingen) -> AgendaBackend:
    tz = ZoneInfo(instellingen.tijdzone)
    abonnementen = [Abonnement(naam, url, tz) for naam, url in instellingen.abonnementen]
    if instellingen.calendar_backend == "icloud":
        agenda = ICloudAgenda(
            instellingen.icloud_gebruiker,
            instellingen.icloud_wachtwoord,
            instellingen.icloud_agenda,
            instellingen.icloud_lees_agendas,
            tz,
            # Staat een abonnement toch in iCloud, dan niet twee keer lezen.
            niet_lezen=instellingen.icloud_niet_lezen + tuple(a.naam for a in abonnementen),
        )
    elif instellingen.calendar_backend == "mock":
        agenda = MockAgenda(instellingen.data_dir / "mock_agenda.json", tz)
    else:
        raise AgendaFout(f"onbekende CALENDAR_BACKEND: {instellingen.calendar_backend}")
    return MetAbonnementen(agenda, abonnementen) if abonnementen else agenda
