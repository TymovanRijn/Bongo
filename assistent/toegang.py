"""Wie mag bij de webapp? (beslispunt 2)

Wie de webapp kan bereiken, kan Tymo's agenda lezen, voorstellen goedkeuren (en dus in
zijn agenda schrijven), zijn geheugen aanpassen en Claude laten werken op zijn kosten.
Daarom drie lagen, van buiten naar binnen:

1. Netwerk: alleen de Pi zelf, het thuisnetwerk en (alleen als dat aan staat) Tailscale.
2. Herkomst: de Host moet Bongo zelf zijn en een verzoek dat iets verandert, moet van
   Bongo's eigen pagina komen (Origin). Dat houdt kwaadaardige websites buiten, ook als
   Tymo ze bezoekt op een apparaat dat wél bij Bongo mag (CSRF en DNS-rebinding).
3. Apparaat: met WEB_TOEGANG=pin of link meldt een apparaat zich één keer aan en krijgt
   het een cookie. In de database staat alleen een hash van die cookie: wie de database
   kan lezen, kan zich daarmee nog niet aanmelden.

De Pi zelf (het touchscreen) hoeft zich niet aan te melden.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import secrets
import socket
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Callable

from .config import Instellingen
from .db import Database, nu_iso

log = logging.getLogger(__name__)

COOKIE = "bongo_apparaat"
COOKIE_DAGEN = 400  # langer bewaren browsers een cookie niet

_LOKAAL = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128")]
_THUIS = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fe80::/10", "fc00::/7")]
_TAILSCALE = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "fd7a:115c:a1e0::/48")]

SCHEMA = """
CREATE TABLE IF NOT EXISTS koppelcodes (
    code_hash  TEXT PRIMARY KEY,
    naam       TEXT NOT NULL,
    aangemaakt TEXT NOT NULL,
    geldig_tot TEXT NOT NULL,
    gebruikt   TEXT
);
"""


class TeVeelPogingen(Exception):
    def __init__(self, wacht_seconden: int):
        super().__init__(f"Te veel foute pogingen. Probeer het over {max(1, wacht_seconden // 60)} minuten opnieuw.")
        self.wacht_seconden = wacht_seconden


def _hash(geheim: str) -> str:
    return hashlib.sha256(geheim.encode()).hexdigest()


def _ip(tekst: str):
    try:
        ip = ipaddress.ip_address(tekst)
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip


def host_ok(host_kop: str) -> bool:
    """Is dit een naam waaronder Bongo bereikt wordt? Tegen DNS-rebinding: een aanvaller
    laat zijn eigen domeinnaam naar het adres van de Pi wijzen, maar die naam zou hier staan."""
    host = host_kop.strip().lower()
    if host.startswith("["):  # IPv6: [::1]:8765
        host = host[1 : host.find("]")]
    else:
        host = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    if not host:
        return False
    if _ip(host) is not None or host == "localhost":
        return True
    return host == socket.gethostname().lower() or host.endswith((".local", ".ts.net"))


def herkomst_ok(origin: str | None, host_kop: str) -> bool:
    """Komt een verzoek dat iets verandert van Bongo's eigen pagina? Browsers sturen bij
    zo'n verzoek altijd een Origin mee; programma's als curl niet (die zijn geen gevaar)."""
    if origin is None:
        return True
    return origin.split("://", 1)[-1].lower() == host_kop.lower()


class Poortwachter:
    MAX_POGINGEN = 5
    VENSTER_SECONDEN = 15 * 60
    KOPPELCODE_GELDIG = timedelta(hours=24)

    def __init__(self, inst: Instellingen, db: Database, klok: Callable[[], float] = time.monotonic):
        if inst.toegang not in ("open", "pin", "link"):
            raise ValueError(f"WEB_TOEGANG moet open, pin of link zijn, niet '{inst.toegang}'")
        self.modus = inst.toegang
        self.pin = inst.pin
        self.netwerken = list(_THUIS)
        if inst.tailscale_toegestaan:
            self.netwerken += _TAILSCALE
        self.netwerken += [ipaddress.ip_network(n, strict=False) for n in inst.extra_netwerken]
        self.db = db
        self.klok = klok
        self._fouten: deque[float] = deque()
        self._slot = threading.Lock()
        with db.verbinding() as con:
            con.executescript(SCHEMA)

    # ---- laag 1: netwerk ---------------------------------------------------------------
    @staticmethod
    def is_lokaal(adres: str) -> bool:
        ip = _ip(adres)
        return ip is not None and any(ip in n for n in _LOKAAL)

    def netwerk_ok(self, adres: str) -> bool:
        ip = _ip(adres)
        if ip is None:
            return False
        return any(ip in n for n in _LOKAAL) or any(ip.version == n.version and ip in n for n in self.netwerken)

    # ---- laag 3: apparaten -------------------------------------------------------------
    def apparaat(self, token: str | None) -> str | None:
        """De naam van het apparaat bij deze cookie, of None."""
        if not token:
            return None
        with self.db.verbinding() as con:
            rij = con.execute("SELECT naam, laatst_gezien FROM apparaten WHERE token_hash = ?", (_hash(token),)).fetchone()
            if rij is None:
                return None
            nu = nu_iso()
            if (rij["laatst_gezien"] or "")[:13] != nu[:13]:  # hooguit één keer per uur schrijven
                con.execute("UPDATE apparaten SET laatst_gezien = ? WHERE token_hash = ?", (nu, _hash(token)))
        return rij["naam"]

    def nieuw_apparaat(self, naam: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.db.verbinding() as con:
            con.execute(
                "INSERT INTO apparaten (token_hash, naam, aangemaakt, laatst_gezien) VALUES (?, ?, ?, ?)",
                (_hash(token), _naam(naam), nu_iso(), nu_iso()),
            )
        log.info("nieuw apparaat aangemeld: %s", naam)
        return token

    def apparaten(self) -> list[dict]:
        with self.db.verbinding() as con:
            rijen = con.execute("SELECT * FROM apparaten ORDER BY aangemaakt").fetchall()
        # De eerste tekens van de hash zijn genoeg om een apparaat aan te wijzen.
        return [{"id": r["token_hash"][:12], "naam": r["naam"], "aangemaakt": r["aangemaakt"], "laatst_gezien": r["laatst_gezien"]} for r in rijen]

    def ontkoppel(self, apparaat_id: str = "", token: str | None = None) -> bool:
        with self.db.verbinding() as con:
            if token:
                weg = con.execute("DELETE FROM apparaten WHERE token_hash = ?", (_hash(token),)).rowcount
            elif len(apparaat_id) >= 8:
                weg = con.execute("DELETE FROM apparaten WHERE token_hash LIKE ?", (apparaat_id.lower() + "%",)).rowcount
            else:
                weg = 0
        return weg > 0

    # ---- aanmelden met een koppellink (WEB_TOEGANG=link, of een extra apparaat) ---------
    def maak_koppelcode(self, naam: str) -> tuple[str, datetime]:
        code = secrets.token_urlsafe(24)
        tot = datetime.now().astimezone() + self.KOPPELCODE_GELDIG
        with self.db.verbinding() as con:
            con.execute(
                "INSERT INTO koppelcodes (code_hash, naam, aangemaakt, geldig_tot) VALUES (?, ?, ?, ?)",
                (_hash(code), _naam(naam), nu_iso(), tot.isoformat(timespec="seconds")),
            )
        return code, tot

    def gebruik_koppelcode(self, code: str) -> str | None:
        """Wissel een koppelcode (één keer bruikbaar, 24 uur geldig) in voor een apparaatcookie."""
        with self.db.verbinding() as con:
            rij = con.execute("SELECT * FROM koppelcodes WHERE code_hash = ?", (_hash(code),)).fetchone()
            if rij is None or rij["gebruikt"] or datetime.fromisoformat(rij["geldig_tot"]) < datetime.now().astimezone():
                return None
            # De WHERE maakt het inwisselen ondeelbaar: twee keer tegelijk klikken geeft één apparaat.
            if not con.execute(
                "UPDATE koppelcodes SET gebruikt = ? WHERE code_hash = ? AND gebruikt IS NULL", (nu_iso(), _hash(code))
            ).rowcount:
                return None
        return self.nieuw_apparaat(rij["naam"])

    # ---- aanmelden met de pincode (WEB_TOEGANG=pin) -------------------------------------
    @property
    def pin_ingesteld(self) -> bool:
        return len(self.pin) >= 4

    def probeer_pin(self, pin: str) -> bool:
        """Hooguit vijf foute pogingen per kwartier, voor alle apparaten samen.

        Een pincode van vier cijfers heeft 10.000 mogelijkheden. Zonder grens probeert een
        script ze in een paar minuten allemaal. Met deze grens duurt dat gemiddeld maanden.
        """
        with self._slot:
            nu = self.klok()
            while self._fouten and nu - self._fouten[0] > self.VENSTER_SECONDEN:
                self._fouten.popleft()
            if len(self._fouten) >= self.MAX_POGINGEN:
                raise TeVeelPogingen(int(self.VENSTER_SECONDEN - (nu - self._fouten[0])))
            # compare_digest kost altijd even lang, dus de tijd verraadt niet hoeveel cijfers goed waren.
            goed = self.pin_ingesteld and hmac.compare_digest(pin.strip().encode(), self.pin.encode())
            if not goed:
                self._fouten.append(nu)
                log.warning("foute pincode (%d in dit kwartier)", len(self._fouten))
            return goed


def _naam(naam: str) -> str:
    return " ".join(naam.split())[:60] or "apparaat"
