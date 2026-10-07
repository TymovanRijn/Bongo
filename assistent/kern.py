"""De kern: de server die altijd draait. Start met `python -m assistent.kern`.

Hij levert:
- de webapp voor de telefoon (/), het touchscreen (/kiosk) en de aanmeldpagina (/inloggen);
- de API die die pagina's gebruiken (/api/...);
- de planner: ochtendoverzicht, logboek opruimen, scherm 's nachts uit;
- de spraak: een tik op het gezicht op het scherm start een gesprek (spraak/).

Wie erbij mag, regelt de poortwachter (toegang.py, beslispunt 2).

Open pagina's horen het via "long polling" als er iets verandert: ze vragen /api/wacht
met de versie die ze kennen, en krijgen pas antwoord als er een nieuwe versie is (of na
25 seconden). Dan halen ze /api/toestand opnieuw op.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .brain import BreinFout
from .calendar_backend import AgendaFout
from .config import Instellingen, laad_instellingen
from .db import Database
from .opbouw import Onderdelen, maak_onderdelen, stel_logging_in
from .overzicht import agenda_per_dag
from .planner import Planner, is_nacht
from .spraak import Spraak, maak_spraak
from .toegang import COOKIE, COOKIE_DAGEN, Poortwachter, TeVeelPogingen, herkomst_ok, host_ok
from .wachtrij import Voorstel, WachtrijFout

log = logging.getLogger("assistent.kern")  # niet __name__: dat is "__main__" bij python -m

WEB = Path(__file__).resolve().parent / "web"
# Zonder aanmelden bereikbaar (wel alleen vanaf een toegestaan netwerk).
PUBLIEK = ("/inloggen", "/api/aanmelden", "/api/inloggen", "/koppel/", "/static/", "/favicon.ico")


class Melder:
    """Houdt een versienummer bij dat omhoog gaat bij elke wijziging (wachtrij, geheugen,
    ochtendoverzicht, dag/nacht). `meld()` mag vanuit elke thread; `wacht()` draait in de
    event loop van de server."""

    def __init__(self) -> None:
        self.versie = 0
        self._lus: asyncio.AbstractEventLoop | None = None
        self._gebeurd: asyncio.Event | None = None

    def koppel(self, lus: asyncio.AbstractEventLoop) -> None:
        self._lus = lus
        self._gebeurd = asyncio.Event()

    def meld(self) -> None:
        if self._lus is None:
            self.versie += 1
        else:
            self._lus.call_soon_threadsafe(self._in_de_lus)

    def _in_de_lus(self) -> None:
        self.versie += 1
        self._gebeurd.set()
        self._gebeurd = asyncio.Event()

    async def wacht(self, versie: int, timeout: float) -> int:
        if versie == self.versie and self._gebeurd is not None:
            try:
                await asyncio.wait_for(self._gebeurd.wait(), timeout)
            except asyncio.TimeoutError:
                pass
        return self.versie


# ---- wat de pagina's opsturen ----------------------------------------------------------
class Vraag(BaseModel):
    tekst: str = Field(min_length=1, max_length=2000)
    bron: Literal["web", "kiosk"] = "web"


class Aanmelding(BaseModel):
    pin: str = Field(max_length=64)
    naam: str = Field(default="", max_length=60)


class GeheugenTekst(BaseModel):
    tekst: str = Field(max_length=20_000)


class NieuwApparaat(BaseModel):
    naam: str = Field(min_length=1, max_length=60)


def _voorstel(v: Voorstel) -> dict:
    d = v.als_dict()
    d.pop("gegevens")
    return d


def _fout(status: int, melding: str) -> JSONResponse:
    return JSONResponse({"fout": melding}, status_code=status)


def maak_app(o: Onderdelen, start_planner: bool = True, spraak: Spraak | None = None) -> FastAPI:
    inst = o.inst
    tz = ZoneInfo(inst.tijdzone)
    melder = Melder()
    o.wachtrij.bij_wijziging = melder.meld
    if spraak is not None:
        spraak.bij_wijziging = melder.meld  # het gezicht verandert mee: luisteren, denken, praten
    poort = Poortwachter(inst, o.db)
    planner = Planner(o, bij_wijziging=melder.meld, spraak=spraak)

    @asynccontextmanager
    async def levensloop(app: FastAPI):
        melder.koppel(asyncio.get_running_loop())
        for v in await run_in_threadpool(o.wachtrij.herstel_onderbroken):
            log.warning("voorstel #%s was onderbroken en staat nu op %s", v.id, v.status)
        if start_planner:
            planner.start()
        if spraak is not None:
            spraak.warm_op()  # modellen laden (de eerste keer downloaden) op de achtergrond
        yield
        planner.stop()

    app = FastAPI(title="Bongo", lifespan=levensloop, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.onderdelen, app.state.poort, app.state.planner, app.state.melder = o, poort, planner, melder

    # ---- de poortwachter -----------------------------------------------------------------
    @app.middleware("http")
    async def poortwachter(request: Request, call_next):
        pad = request.url.path
        host = request.headers.get("host", "")
        adres = request.client.host if request.client else ""
        if not host_ok(host):
            return PlainTextResponse("Onbekende host.", status_code=400)
        if not poort.netwerk_ok(adres):
            log.warning("verzoek van %s geweigerd (netwerk)", adres)
            return PlainTextResponse("Bongo is niet bereikbaar vanaf dit netwerk.", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not herkomst_ok(request.headers.get("origin"), host):
            log.warning("verzoek van een andere website geweigerd: %s", request.headers.get("origin"))
            return PlainTextResponse("Verzoek van een andere website geweigerd.", status_code=403)

        request.state.lokaal = poort.is_lokaal(adres)
        if request.state.lokaal:
            apparaat = "scherm"
        elif poort.modus == "open":
            apparaat = "webapp"
        else:
            apparaat = await run_in_threadpool(poort.apparaat, request.cookies.get(COOKIE))
        request.state.apparaat = apparaat
        if apparaat is None and not pad.startswith(PUBLIEK):
            if pad.startswith("/api/"):
                return _fout(401, "Meld je eerst aan.")
            return RedirectResponse("/inloggen", status_code=303)

        antwoord = await call_next(request)
        antwoord.headers["X-Frame-Options"] = "DENY"  # niemand kan Bongo onzichtbaar in zijn site laden
        antwoord.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; base-uri 'none'"
        antwoord.headers["Referrer-Policy"] = "no-referrer"
        antwoord.headers["X-Content-Type-Options"] = "nosniff"
        if pad.startswith("/api/"):
            antwoord.headers["Cache-Control"] = "no-store"
        return antwoord

    def via(request: Request) -> str:
        return "scherm" if request.state.lokaal else f"web: {request.state.apparaat}"

    # ---- pagina's ------------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def webapp():
        return FileResponse(WEB / "index.html")

    @app.get("/kiosk", include_in_schema=False)
    def kiosk():
        return FileResponse(WEB / "kiosk.html")

    @app.get("/inloggen", include_in_schema=False)
    def inloggen_pagina():
        return FileResponse(WEB / "inloggen.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(WEB / "aap.svg", media_type="image/svg+xml")

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    # ---- aanmelden -----------------------------------------------------------------------
    def _met_cookie(antwoord: Response, token: str) -> Response:
        antwoord.set_cookie(COOKIE, token, max_age=COOKIE_DAGEN * 86400, httponly=True, samesite="lax")
        return antwoord

    @app.get("/api/aanmelden")
    def aanmelden_info(request: Request):
        return {
            "naam": inst.assistent_naam,
            "modus": poort.modus,
            "pin_ingesteld": poort.pin_ingesteld,
            "aangemeld": request.state.apparaat is not None,
        }

    @app.post("/api/inloggen")
    def inloggen(a: Aanmelding):
        if poort.modus != "pin":
            return _fout(400, "Aanmelden met een pincode staat uit. Vraag een koppellink.")
        if not poort.pin_ingesteld:
            return _fout(503, "Er is nog geen pincode ingesteld. Zet WEB_PIN in .env op de Pi.")
        try:
            goed = poort.probeer_pin(a.pin)
        except TeVeelPogingen as e:
            return _fout(429, str(e))
        if not goed:
            return _fout(401, "Die pincode klopt niet.")
        return _met_cookie(JSONResponse({"ok": True}), poort.nieuw_apparaat(a.naam or "apparaat"))

    @app.post("/api/uitloggen")
    def uitloggen(request: Request):
        token = request.cookies.get(COOKIE)
        if token:
            poort.ontkoppel(token=token)
        antwoord = JSONResponse({"ok": True})
        antwoord.delete_cookie(COOKIE)
        return antwoord

    @app.get("/koppel/{code}", include_in_schema=False)
    def koppel(code: str):
        token = poort.gebruik_koppelcode(code)
        if token is None:
            return HTMLResponse(
                "<!doctype html><meta charset=utf-8><title>Bongo</title>"
                "<p>Deze koppellink is verlopen of al gebruikt. Maak een nieuwe.</p>",
                status_code=403,
            )
        return _met_cookie(RedirectResponse("/", status_code=303), token)

    # ---- toestand ------------------------------------------------------------------------
    @app.get("/api/toestand")
    def toestand(request: Request):
        versie = melder.versie  # eerst: verandert er hierna iets, dan haalt de pagina het opnieuw op
        nu = datetime.now(tz)
        try:
            agenda, agenda_fout = agenda_per_dag(o.agenda, tz, dagen=2), None
        except AgendaFout as e:
            agenda, agenda_fout = [], str(e)
        return {
            "versie": versie,
            "naam": inst.assistent_naam,
            "gebruiker": inst.gebruiker_naam,
            "nu": nu.isoformat(timespec="seconds"),
            "nacht": is_nacht(nu, inst.nacht_van, inst.nacht_tot),
            "open": [_voorstel(v) for v in o.wachtrij.open()],
            "recent": [_voorstel(v) for v in o.wachtrij.afgehandeld(8)],
            "agenda": agenda,
            "agenda_fout": agenda_fout,
            "ochtend": planner.ochtendoverzicht(nu.date()),
            "apparaat": request.state.apparaat,
            "toegang": poort.modus,
            "kan_nadenken": o.brain.client is not None,
            "spraak": spraak.status() if spraak else {"toestand": "uit", "ondertitel": "", "melding": "", "klaar": False},
        }

    @app.get("/api/wacht")
    async def wacht(versie: int = 0, timeout: float = 25):
        return {"versie": await melder.wacht(versie, min(max(timeout, 0.0), 30.0))}

    # ---- praten --------------------------------------------------------------------------
    @app.post("/api/vraag")
    def vraag(v: Vraag):
        try:
            a = o.brain.vraag(v.tekst, bron=v.bron)
        except BreinFout as e:
            return _fout(503, e.melding)
        return {
            "tekst": a.tekst,
            "voorstellen": [_voorstel(o.wachtrij.get(vid)) for vid in a.voorstel_ids],
            "ms": a.ms,
            "kosten_usd": a.kosten_usd,
        }

    @app.post("/api/luister")
    def luister(request: Request):
        # Alleen het scherm van de Pi zelf: anders kan iemand met de webapp op afstand meeluisteren.
        if not request.state.lokaal:
            return _fout(403, "Alleen het scherm van de Pi zelf kan de microfoon aanzetten.")
        if spraak is None:
            return _fout(503, "Spraak staat uit (SPRAAK in .env), of de pakketten ervoor ontbreken.")
        spraak.tik()
        return spraak.status()

    @app.post("/api/gesprek/nieuw")
    def nieuw_gesprek(request: Request):
        return {"gesprek": o.brain.nieuw_gesprek(f"handmatig, {via(request)}")}

    # ---- de wachtrij ---------------------------------------------------------------------
    @app.post("/api/voorstellen/{voorstel_id}/ja")
    def ja(voorstel_id: int, request: Request):
        try:
            return _voorstel(o.wachtrij.approve(voorstel_id, via=via(request)))
        except WachtrijFout as e:
            raise HTTPException(409, str(e)) from e

    @app.post("/api/voorstellen/{voorstel_id}/nee")
    def nee(voorstel_id: int, request: Request):
        try:
            return _voorstel(o.wachtrij.reject(voorstel_id, via=via(request)))
        except WachtrijFout as e:
            raise HTTPException(409, str(e)) from e

    # ---- agenda, geheugen, ochtendoverzicht ----------------------------------------------
    @app.get("/api/agenda")
    def agenda(dagen: int = 7):
        try:
            return {"dagen": agenda_per_dag(o.agenda, tz, dagen=min(max(dagen, 1), 14))}
        except AgendaFout as e:
            return _fout(503, str(e))

    @app.get("/api/geheugen")
    def geheugen():
        return {"tekst": o.geheugen.lees()}

    @app.put("/api/geheugen")
    def geheugen_opslaan(g: GeheugenTekst, request: Request):
        # Tymo past zijn eigen geheugen aan: dat is geen voorstel van Claude, dus mag direct.
        o.geheugen.schrijf(g.tekst)
        o.logboek.schrijf("geheugen", f"met de hand aangepast ({via(request)})", bron="web")
        melder.meld()
        return {"ok": True}

    @app.post("/api/ochtendoverzicht")
    def ochtendoverzicht_nu():
        try:
            return planner.maak_ochtendoverzicht(datetime.now(tz).date())
        except AgendaFout as e:
            return _fout(503, str(e))

    # ---- kosten en logboek ---------------------------------------------------------------
    @app.get("/api/kosten")
    def kosten():
        return {"dagen": o.logboek.kosten_per_dag(30), "metingen": o.logboek.metingen_samenvatting(7)}

    @app.get("/api/logboek")
    def logboek(limiet: int = 50):
        return {"gebeurtenissen": o.logboek.recent(min(max(limiet, 1), 200))}

    # ---- apparaten -----------------------------------------------------------------------
    @app.get("/api/apparaten")
    def apparaten():
        return {"apparaten": poort.apparaten(), "toegang": poort.modus}

    @app.post("/api/apparaten")
    def apparaat_koppelen(a: NieuwApparaat, request: Request):
        code, tot = poort.maak_koppelcode(a.naam)
        o.logboek.schrijf("apparaat", f"koppellink gemaakt voor '{a.naam}' ({via(request)})", bron="web")
        return {"link": f"{request.base_url}koppel/{code}", "geldig_tot": tot.isoformat(timespec="minutes")}

    @app.delete("/api/apparaten/{apparaat_id}")
    def apparaat_ontkoppelen(apparaat_id: str):
        if not poort.ontkoppel(apparaat_id):
            raise HTTPException(404, "Dat apparaat bestaat niet.")
        return {"ok": True}

    return app


# ---- starten vanaf de commandoregel ------------------------------------------------------
def eigen_adressen(inst: Instellingen) -> list[str]:
    adressen = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # verstuurt niets; zo hoor je welk adres naar buiten gaat
            adressen.append(s.getsockname()[0])
    except OSError:
        pass
    adressen.append(f"{socket.gethostname()}.local")
    return [f"http://{a}:{inst.kern_poort}" for a in adressen]


def waarschuwingen(inst: Instellingen) -> list[str]:
    uit = []
    if inst.toegang == "pin" and len(inst.pin) < 4:
        uit.append("WEB_TOEGANG=pin, maar WEB_PIN is leeg of korter dan 4 tekens: alleen het scherm van de Pi kan nu bij Bongo.")
    if inst.toegang == "open" and inst.tailscale_toegestaan:
        uit.append("WEB_TOEGANG=open met Tailscale aan: iedereen in je tailnet kan zonder pincode bij Bongo.")
    if not inst.anthropic_api_key:
        uit.append("Geen ANTHROPIC_API_KEY: Bongo kan niet nadenken. Agenda en wachtrij werken wel.")
    return uit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assistent.kern", description="De kern van Bongo.")
    sub = parser.add_subparsers(dest="opdracht")
    sub.add_parser("start", help="start de kern (dat gebeurt ook zonder opdracht)")
    k = sub.add_parser("koppel", help="maak een koppellink voor een nieuw apparaat")
    k.add_argument("naam", help='bijvoorbeeld "Telefoon van Tymo"')
    sub.add_parser("apparaten", help="laat de gekoppelde apparaten zien")
    w = sub.add_parser("ontkoppel", help="ontkoppel een apparaat")
    w.add_argument("id", help="de id uit 'apparaten'")
    args = parser.parse_args(argv)
    inst = laad_instellingen()

    if args.opdracht in ("koppel", "apparaten", "ontkoppel"):
        poort = Poortwachter(inst, Database(inst.db_pad))
        if args.opdracht == "koppel":
            code, tot = poort.maak_koppelcode(args.naam)
            print(f"Open één van deze links op '{args.naam}' (één keer bruikbaar, geldig tot {tot:%d-%m %H:%M}):")
            for adres in eigen_adressen(inst):
                print(f"  {adres}/koppel/{code}")
        elif args.opdracht == "apparaten":
            apparaten = poort.apparaten()
            if not apparaten:
                print("Nog geen apparaten gekoppeld.")
            for a in apparaten:
                print(f"  {a['id']:12}  {a['naam']:30}  laatst gezien {a['laatst_gezien'] or '-'}")
        else:
            print("Ontkoppeld." if poort.ontkoppel(args.id) else "Geen apparaat met die id.")
        return 0

    import uvicorn

    stel_logging_in(inst, "kern")
    for melding in waarschuwingen(inst):
        log.warning(melding)
    o = maak_onderdelen(inst)
    app = maak_app(o, spraak=maak_spraak(o))
    log.info("Bongo luistert op %s", ", ".join(eigen_adressen(inst)))
    uvicorn.run(
        app,
        host=inst.kern_host,
        port=inst.kern_poort,
        proxy_headers=False,  # er zit geen proxy voor: vertrouw geen X-Forwarded-For
        log_level="warning",
        timeout_graceful_shutdown=5,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
