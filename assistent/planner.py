"""De klok van de kern: wat op een vast moment moet gebeuren.

- Het ochtendoverzicht (beslispunt 5): één keer per dag, vanaf OCHTEND_TIJD.
- Het logboek opruimen: één keer per nacht.
- 's Nachts het scherm uit, als NACHT_SCHERM_UIT aan staat.

`tik(nu)` doet wat er op dat moment te doen is. De thread roept hem elke twintig seconden
aan; de tests roepen hem aan met een tijd die ze zelf kiezen.
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from datetime import date, datetime, time, timedelta
from typing import Callable
from zoneinfo import ZoneInfo

from .db import nu_iso
from .opbouw import Onderdelen
from .overzicht import maak_ochtendoverzicht

log = logging.getLogger(__name__)


def klokje(tekst: str) -> time:
    uur, _, minuut = tekst.strip().partition(":")
    return time(int(uur), int(minuut or 0))


def is_nacht(nu: datetime, van: str, tot: str) -> bool:
    begin, eind = klokje(van), klokje(tot)
    t = nu.time()
    if begin <= eind:
        return begin <= t < eind
    return t >= begin or t < eind  # over middernacht heen, zoals 23:00 tot 07:00


def zet_scherm(aan: bool) -> None:
    """Scherm aan of uit via X11 (DPMS). Nog niet getest op dit scherm, zie docs/hardware.md."""
    scherm = os.environ.get("DISPLAY", ":0")
    subprocess.run(["xset", "-display", scherm, "dpms", "force", "on" if aan else "off"], check=True, timeout=5, capture_output=True)


class Planner:
    INTERVAL_SECONDEN = 20
    OCHTEND_VENSTER = timedelta(hours=4)  # start de Pi om drie uur 's middags, dan geen ochtendoverzicht meer
    OPNIEUW_NA = timedelta(minutes=10)  # na een fout niet elke twintig seconden opnieuw proberen
    LOGBOEK_DAGEN = 180

    def __init__(
        self,
        o: Onderdelen,
        bij_wijziging: Callable[[], None] | None = None,
        scherm: Callable[[bool], None] = zet_scherm,
        spraak=None,
    ):
        self.o = o
        self.inst = o.inst
        self.tz = ZoneInfo(o.inst.tijdzone)
        self.bij_wijziging = bij_wijziging or (lambda: None)
        self.scherm = scherm
        self.spraak = spraak
        self._mislukt_om: datetime | None = None
        self._opgeruimd_op: date | None = None
        self._was_nacht: bool | None = None
        self._stop = threading.Event()
        self._draad: threading.Thread | None = None

    # ---- ochtendoverzicht --------------------------------------------------------------
    def ochtendoverzicht(self, datum: date) -> dict | None:
        with self.o.db.verbinding() as con:
            rij = con.execute("SELECT * FROM ochtendoverzicht WHERE datum = ?", (datum.isoformat(),)).fetchone()
        return dict(rij) if rij else None

    def maak_ochtendoverzicht(self, datum: date) -> dict:
        tekst, _ = maak_ochtendoverzicht(self.o.brain, self.o.agenda, self.tz, self.inst.gebruiker_naam, vanaf=datum)
        with self.o.db.verbinding() as con:
            con.execute(
                "INSERT OR REPLACE INTO ochtendoverzicht (datum, tekst, gemaakt) VALUES (?, ?, ?)",
                (datum.isoformat(), tekst, nu_iso()),
            )
        self.o.logboek.schrijf("ochtend", tekst, bron="ochtend")
        self.bij_wijziging()
        return self.ochtendoverzicht(datum)

    # ---- de klok -----------------------------------------------------------------------
    def tik(self, nu: datetime) -> None:
        for taak in (self._ochtend, self._opruimen, self._nacht):
            try:
                taak(nu)
            except Exception:
                log.exception("planner: %s mislukt", taak.__name__)

    def _ochtend(self, nu: datetime) -> None:
        begin = datetime.combine(nu.date(), klokje(self.inst.ochtend_tijd), self.tz)
        if not begin <= nu < begin + self.OCHTEND_VENSTER:
            return
        if self.ochtendoverzicht(nu.date()) is not None:
            return
        if self._mislukt_om and nu - self._mislukt_om < self.OPNIEUW_NA:
            return
        try:
            overzicht = self.maak_ochtendoverzicht(nu.date())
        except Exception:
            self._mislukt_om = nu
            raise
        self._mislukt_om = None
        if self.inst.ochtend_uitspreken:
            if self.spraak is None:
                log.info("OCHTEND_UITSPREKEN staat aan, maar de spraak niet")
            elif not self.spraak.zeg(overzicht["tekst"]):
                log.info("ochtendoverzicht niet uitgesproken: Bongo was al bezig")

    def _opruimen(self, nu: datetime) -> None:
        if nu.hour >= 3 and self._opgeruimd_op != nu.date():
            weg = self.o.logboek.opruimen(self.LOGBOEK_DAGEN)
            self._opgeruimd_op = nu.date()
            if weg:
                log.info("logboek opgeruimd: %d oude regels weg", weg)

    def _nacht(self, nu: datetime) -> None:
        nacht = is_nacht(nu, self.inst.nacht_van, self.inst.nacht_tot)
        if nacht == self._was_nacht:
            return
        if self._was_nacht is not None:  # niet bij het opstarten, alleen bij een overgang
            self.bij_wijziging()  # het scherm past zich meteen aan
            if self.inst.nacht_scherm_uit:
                self.scherm(not nacht)
        self._was_nacht = nacht

    # ---- de thread ---------------------------------------------------------------------
    def start(self) -> None:
        if self._draad is None:
            self._stop.clear()
            self._draad = threading.Thread(target=self._loop, name="planner", daemon=True)
            self._draad.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.tik(datetime.now(self.tz))
            self._stop.wait(self.INTERVAL_SECONDEN)

    def stop(self) -> None:
        self._stop.set()
        if self._draad is not None:
            self._draad.join(timeout=5)
            self._draad = None
