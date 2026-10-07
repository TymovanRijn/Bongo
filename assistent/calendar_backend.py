"""Agenda: een nep-agenda om mee te testen en iCloud via CalDAV, met dezelfde interface."""

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

    def afspraken(self, van: datetime, tot: datetime) -> list[Afspraak]: ...

    def voeg_toe(
        self,
        titel: str,
        start: datetime,
        eind: datetime,
        locatie: str | None = None,
        notitie: str | None = None,
        hele_dag: bool = False,
    ) -> str: ...


def _overlapt(a: Afspraak, van: datetime, tot: datetime) -> bool:
    return a.start < tot and a.eind > van


# ---------------------------------------------------------------------------------------
# Nep-agenda: een JSON-bestand in data/, zodat kern en CLI dezelfde afspraken zien.
# ---------------------------------------------------------------------------------------
class MockAgenda:
    naam = "mock"

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
            Afspraak("Lunch met Sanne", op(0, 12, 30), op(0, 13, 30), locatie="Café de Zaak", uid="mock-2"),
            Afspraak("Tandarts", op(1, 10), op(1, 10, 30), locatie="Tandartspraktijk Centrum", uid="mock-3"),
            Afspraak("Sporten", op(1, 18), op(1, 19), uid="mock-4"),
            Afspraak("Verjaardag oma", op(3, 0), op(4, 0), hele_dag=True, uid="mock-5"),
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

    def voeg_toe(self, titel, start, eind, locatie=None, notitie=None, hele_dag=False) -> str:
        uid = f"mock-{uuid.uuid4().hex[:8]}"
        with self._slot:
            alles = self._laad()
            alles.append(Afspraak(titel, start, eind, hele_dag, locatie, notitie, "Mock", uid))
            self._bewaar(alles)
        return uid


# ---------------------------------------------------------------------------------------
# iCloud via CalDAV. Inloggen met Apple ID + app-specifiek wachtwoord (account.apple.com).
# ---------------------------------------------------------------------------------------
class ICloudAgenda:
    naam = "icloud"
    URL = "https://caldav.icloud.com"
    CACHE_SECONDEN = 60

    def __init__(self, gebruiker: str, wachtwoord: str, schrijf_agenda: str, lees_agendas: tuple[str, ...], tz: ZoneInfo):
        if not gebruiker or not wachtwoord:
            raise AgendaFout("ICLOUD_USERNAME en ICLOUD_APP_PASSWORD moeten in .env staan")
        self.gebruiker = gebruiker
        self.wachtwoord = wachtwoord
        self.schrijf_agenda = schrijf_agenda
        self.lees_agendas = lees_agendas
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
                self._agendas = [(c, c.get_display_name() or "") for c in client.principal().calendars()]
            except Exception as e:
                raise AgendaFout(f"Kan niet inloggen bij iCloud: {e}") from e
        return self._agendas

    def agenda_namen(self) -> list[str]:
        with self._slot:
            return [naam for _, naam in self._alle_agendas()]

    def _te_lezen(self):
        agendas = self._alle_agendas()
        if not self.lees_agendas:
            return agendas
        gekozen = [(c, naam) for c, naam in agendas if naam in self.lees_agendas]
        return gekozen or agendas

    def _naar_lokaal(self, waarde) -> tuple[datetime, bool]:
        if isinstance(waarde, datetime):
            if waarde.tzinfo is None:
                return waarde.replace(tzinfo=self.tz), False
            return waarde.astimezone(self.tz), False
        if isinstance(waarde, date):
            return datetime(waarde.year, waarde.month, waarde.day, tzinfo=self.tz), True
        raise AgendaFout(f"onbekend tijdformaat: {waarde!r}")

    def _lees_event(self, event, agenda_naam: str) -> Afspraak | None:
        comp = event.icalendar_component
        if comp is None or "DTSTART" not in comp:
            return None
        start, hele_dag = self._naar_lokaal(comp["DTSTART"].dt)
        if "DTEND" in comp:
            eind, _ = self._naar_lokaal(comp["DTEND"].dt)
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
                    afspraak = self._lees_event(ev, naam)
                    if afspraak and _overlapt(afspraak, van, tot):
                        uit.append(afspraak)
            uit.sort(key=lambda a: a.start)
            self._cache[sleutel] = (time.monotonic(), uit)
            return list(uit)

    def voeg_toe(self, titel, start, eind, locatie=None, notitie=None, hele_dag=False) -> str:
        from icalendar import Calendar, Event

        with self._slot:
            agendas = self._alle_agendas()
            doel = [c for c, naam in agendas if naam == self.schrijf_agenda]
            if not doel:
                namen = ", ".join(naam or "?" for _, naam in agendas)
                raise AgendaFout(f"Agenda '{self.schrijf_agenda}' niet gevonden. Beschikbaar: {namen}")

            uid = f"{uuid.uuid4()}@bongo"
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


def maak_agenda(instellingen) -> AgendaBackend:
    tz = ZoneInfo(instellingen.tijdzone)
    if instellingen.calendar_backend == "icloud":
        return ICloudAgenda(
            instellingen.icloud_gebruiker,
            instellingen.icloud_wachtwoord,
            instellingen.icloud_agenda,
            instellingen.icloud_lees_agendas,
            tz,
        )
    if instellingen.calendar_backend != "mock":
        raise AgendaFout(f"onbekende CALENDAR_BACKEND: {instellingen.calendar_backend}")
    return MockAgenda(instellingen.data_dir / "mock_agenda.json", tz)
