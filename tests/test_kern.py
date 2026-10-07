import threading
import time
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from nep_claude import geen_verbinding, tekst, tool

from assistent.kern import maak_app
from assistent.toegang import COOKIE

BASIS = "http://192.168.1.53:8765"
AFSPRAAK = {
    "titel": "Tandarts",
    "start": "2030-03-04T10:00",
    "eind": "2030-03-04T10:30",
    "hele_dag": False,
    "locatie": None,
    "notitie": None,
}


@pytest.fixture
def web(maak):
    """web(antwoorden, ip=..., **instellingen) -> (testclient, onderdelen, nep_claude)"""

    def _web(antwoorden=(), ip="127.0.0.1", **anders):
        o, nep = maak(antwoorden, **anders)
        return TestClient(maak_app(o, start_planner=False), base_url=BASIS, client=(ip, 50000)), o, nep

    return _web


def ander_apparaat(c, ip):
    return TestClient(c.app, base_url=BASIS, client=(ip, 50001))


# ---- laag 1: netwerk -------------------------------------------------------------------
def test_het_scherm_van_de_pi_mag_zonder_aanmelden(web):
    c, _, _ = web(pin="4821")
    assert c.get("/api/toestand").json()["apparaat"] == "scherm"
    assert "<title>Bongo</title>" in c.get("/").text
    assert c.get("/kiosk").status_code == 200


@pytest.mark.parametrize(
    "ip, tailscale, status",
    [
        ("8.8.8.8", False, 403),  # internet
        ("100.101.102.103", False, 403),  # Tailscale, staat standaard uit
        ("100.101.102.103", True, 401),  # Tailscale aan: wel bereikbaar, maar aanmelden
        ("192.168.1.20", False, 401),  # thuisnetwerk: aanmelden
    ],
)
def test_netwerken(web, ip, tailscale, status):
    c, _, _ = web(ip=ip, tailscale_toegestaan=tailscale, pin="4821")
    assert c.get("/api/toestand").status_code == status


def test_extra_netwerk(web):
    c, _, _ = web(ip="203.0.113.7", extra_netwerken=("203.0.113.0/24",), toegang="open")
    assert c.get("/api/toestand").status_code == 200


# ---- laag 2: herkomst ------------------------------------------------------------------
def test_een_andere_website_mag_niets_veranderen(web):
    c, o, _ = web()
    v = o.wachtrij.voorstel("onthouden", "Onthouden: Houdt van thee", {"feit": "Houdt van thee"})
    r = c.post(f"/api/voorstellen/{v.id}/ja", headers={"Origin": "http://kwaadaardig.example"})
    assert r.status_code == 403
    assert o.wachtrij.get(v.id).status == "open"
    assert c.post(f"/api/voorstellen/{v.id}/ja", headers={"Origin": BASIS}).status_code == 200


def test_dns_rebinding(web):
    c, _, _ = web()
    assert c.get("/api/toestand", headers={"Host": "kwaadaardig.example"}).status_code == 400
    for host in ("raspberrypi.local:8765", "localhost:8765", "[::1]:8765", "pi.tail1234.ts.net"):
        assert c.get("/api/toestand", headers={"Host": host}).status_code == 200, host


def test_beveiligingskoppen(web):
    c, _, _ = web()
    r = c.get("/")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert c.get("/api/toestand").headers["Cache-Control"] == "no-store"


# ---- laag 3: apparaten ------------------------------------------------------------------
def test_aanmelden_met_pincode(web):
    c, o, _ = web(ip="192.168.1.20", pin="4821")
    r = c.get("/", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/inloggen")
    assert c.get("/inloggen").status_code == 200
    assert c.get("/api/aanmelden").json() == {"naam": "Bongo", "modus": "pin", "pin_ingesteld": True, "aangemeld": False}

    assert c.post("/api/inloggen", json={"pin": "1234"}).status_code == 401
    r = c.post("/api/inloggen", json={"pin": "4821", "naam": "Telefoon"})
    assert r.status_code == 200
    token = r.cookies[COOKIE]
    assert "httponly" in r.headers["set-cookie"].lower() and "samesite=lax" in r.headers["set-cookie"].lower()
    assert c.get("/api/toestand").json()["apparaat"] == "Telefoon"

    # In de database staat alleen een hash van de cookie.
    with o.db.verbinding() as con:
        [rij] = con.execute("SELECT token_hash FROM apparaten").fetchall()
    assert token not in rij["token_hash"]

    c.post("/api/uitloggen")
    assert c.get("/api/toestand").status_code == 401


def test_te_veel_foute_pincodes(web):
    c, _, _ = web(ip="192.168.1.20", pin="4821")
    for _ in range(5):
        assert c.post("/api/inloggen", json={"pin": "0000"}).status_code == 401
    r = c.post("/api/inloggen", json={"pin": "4821"})  # zelfs de goede niet meer
    assert r.status_code == 429 and "minuten" in r.json()["fout"]


def test_pogingen_tellen_na_een_kwartier_niet_meer(inst):
    from assistent.db import Database
    from assistent.toegang import Poortwachter, TeVeelPogingen

    nu = [1000.0]
    poort = Poortwachter(inst, Database(inst.db_pad), klok=lambda: nu[0])
    poort.pin = "4821"
    for _ in range(5):
        assert not poort.probeer_pin("0000")
    with pytest.raises(TeVeelPogingen):
        poort.probeer_pin("4821")
    nu[0] += 15 * 60 + 1
    assert poort.probeer_pin("4821")


def test_zonder_pincode_kan_niemand_zich_aanmelden(web):
    c, _, _ = web(ip="192.168.1.20", pin="")
    assert c.post("/api/inloggen", json={"pin": ""}).status_code == 503
    assert c.get("/api/aanmelden").json()["pin_ingesteld"] is False


def test_koppellink(web):
    c, o, _ = web(ip="192.168.1.20", toegang="link")
    assert c.post("/api/inloggen", json={"pin": "1234"}).status_code == 400  # pincode staat uit
    code, _ = c.app.state.poort.maak_koppelcode("iPad")
    r = c.get(f"/koppel/{code}", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (303, "/")
    assert c.get("/api/toestand").json()["apparaat"] == "iPad"
    # Eén keer bruikbaar.
    assert ander_apparaat(c, "192.168.1.21").get(f"/koppel/{code}").status_code == 403


def test_verlopen_koppellink(web):
    c, o, _ = web(ip="192.168.1.20", toegang="link")
    code, _ = c.app.state.poort.maak_koppelcode("iPad")
    gisteren = (datetime.now().astimezone() - timedelta(days=1)).isoformat()
    with o.db.verbinding() as con:
        con.execute("UPDATE koppelcodes SET geldig_tot = ?", (gisteren,))
    assert c.get(f"/koppel/{code}").status_code == 403


def test_apparaat_koppelen_en_ontkoppelen(web):
    telefoon, _, _ = web(ip="192.168.1.20", pin="4821")
    telefoon.post("/api/inloggen", json={"pin": "4821", "naam": "Telefoon"})
    link = telefoon.post("/api/apparaten", json={"naam": "iPad"}).json()["link"]
    assert link.startswith(f"{BASIS}/koppel/")

    ipad = ander_apparaat(telefoon, "192.168.1.21")
    ipad.get(link.removeprefix(BASIS))
    assert ipad.get("/api/toestand").json()["apparaat"] == "iPad"

    namen = {a["naam"]: a["id"] for a in telefoon.get("/api/apparaten").json()["apparaten"]}
    assert set(namen) == {"Telefoon", "iPad"}
    assert telefoon.delete(f"/api/apparaten/{namen['iPad']}").status_code == 200
    assert ipad.get("/api/toestand").status_code == 401


def test_open_modus(web):
    c, _, _ = web(ip="192.168.1.20", toegang="open")
    assert c.get("/api/toestand").json()["apparaat"] == "webapp"


# ---- de API ------------------------------------------------------------------------------
def test_vraag_en_goedkeuren(web):
    c, o, _ = web([tool("afspraak_voorstellen", AFSPRAAK), tekst("Klaargezet.")])
    a = c.post("/api/vraag", json={"tekst": "zet de tandarts erin", "bron": "web"}).json()
    assert a["tekst"] == "Klaargezet."
    [v] = a["voorstellen"]
    assert v["status"] == "open" and "gegevens" not in v
    assert c.get("/api/toestand").json()["open"][0]["id"] == v["id"]

    assert c.post(f"/api/voorstellen/{v['id']}/ja").json()["status"] == "uitgevoerd"
    assert o.wachtrij.get(v["id"]).afgehandeld_via == "scherm"
    assert c.post(f"/api/voorstellen/{v['id']}/ja").status_code == 409


def test_vraag_die_mislukt(web):
    c, _, _ = web([geen_verbinding()])
    r = c.post("/api/vraag", json={"tekst": "hallo"})
    assert r.status_code == 503 and "internet" in r.json()["fout"]


def test_vraag_moet_redelijk_zijn(web):
    c, _, _ = web()
    assert c.post("/api/vraag", json={"tekst": ""}).status_code == 422
    assert c.post("/api/vraag", json={"tekst": "x" * 2001}).status_code == 422
    assert c.post("/api/vraag", json={"tekst": "hoi", "bron": "spraak"}).status_code == 422


def test_toestand(web):
    c, _, _ = web()
    t = c.get("/api/toestand").json()
    assert [d["label"] for d in t["agenda"]] == ["Vandaag", "Morgen"]
    assert t["ochtend"] is None and isinstance(t["nacht"], bool) and t["kan_nadenken"] is True


def test_geheugen_met_de_hand_aanpassen(web):
    c, o, _ = web()
    tekst_ = c.get("/api/geheugen").json()["tekst"] + "- Houdt van thee\n"
    assert c.put("/api/geheugen", json={"tekst": tekst_}).status_code == 200
    assert "Houdt van thee" in o.geheugen.lees()


def test_ochtendoverzicht_op_verzoek(web):
    c, _, _ = web([tekst("Goedemorgen!")])
    assert c.post("/api/ochtendoverzicht").json()["tekst"] == "Goedemorgen!"
    assert c.get("/api/toestand").json()["ochtend"]["tekst"] == "Goedemorgen!"


def test_kosten_logboek_agenda(web):
    c, _, _ = web([tekst("Hoi")])
    c.post("/api/vraag", json={"tekst": "hallo"})
    assert c.get("/api/kosten").json()["dagen"][0]["aanroepen"] == 1
    soorten = [g["soort"] for g in c.get("/api/logboek").json()["gebeurtenissen"]]
    assert "vraag" in soorten and "antwoord" in soorten
    assert len(c.get("/api/agenda?dagen=3").json()["dagen"]) == 3


def test_nieuw_gesprek(web):
    c, o, _ = web()
    oud = o.brain.gesprek_id
    c.post("/api/gesprek/nieuw")
    assert o.brain.gesprek_id != oud


# ---- wijzigingen doorgeven en opstarten --------------------------------------------------
def test_wacht_hoort_een_wijziging(web):
    c, o, _ = web()
    with c:  # start de server echt (lifespan), zodat de melder aan de event loop hangt
        versie = c.get("/api/toestand").json()["versie"]
        assert c.get(f"/api/wacht?versie={versie}&timeout=0.05").json()["versie"] == versie

        uitkomst = {}

        def wacht():
            begin = time.monotonic()
            uitkomst["versie"] = c.get(f"/api/wacht?versie={versie}&timeout=10").json()["versie"]
            uitkomst["seconden"] = time.monotonic() - begin

        draad = threading.Thread(target=wacht)
        draad.start()
        time.sleep(0.2)
        o.wachtrij.voorstel("onthouden", "Onthouden: Houdt van thee", {"feit": "Houdt van thee"})
        draad.join(5)
        assert uitkomst["versie"] == versie + 1
        assert uitkomst["seconden"] < 3  # meteen, niet pas na tien seconden


def test_herstel_bij_het_opstarten(web):
    c, o, _ = web()
    v = o.wachtrij.voorstel("onthouden", "Onthouden: Houdt van thee", {"feit": "Houdt van thee"})
    with o.db.verbinding() as con:
        con.execute("UPDATE voorstellen SET status = 'bezig', afgehandeld = '2026-01-01T00:00:00+01:00'")
    with c:
        pass
    assert o.wachtrij.get(v.id).status == "open"


# ---- spraak -------------------------------------------------------------------------------
class NepSpraak:
    def __init__(self):
        self.tikken = 0
        self.bij_wijziging = None
        self.opgewarmd = False

    def tik(self):
        self.tikken += 1
        return "luisteren"

    def status(self):
        return {"toestand": "luisteren" if self.tikken else "rust", "ondertitel": "", "melding": "", "klaar": True}

    def warm_op(self):
        self.opgewarmd = True


def test_alleen_het_scherm_zet_de_microfoon_aan(maak):
    o, _ = maak(pin="4821")
    spraak = NepSpraak()
    app = maak_app(o, start_planner=False, spraak=spraak)
    scherm = TestClient(app, base_url=BASIS, client=("127.0.0.1", 1))
    assert scherm.post("/api/luister").json()["toestand"] == "luisteren"
    assert scherm.get("/api/toestand").json()["spraak"]["toestand"] == "luisteren"

    telefoon = TestClient(app, base_url=BASIS, client=("192.168.1.20", 1))
    telefoon.post("/api/inloggen", json={"pin": "4821"})
    r = telefoon.post("/api/luister")
    assert r.status_code == 403 and "scherm van de Pi" in r.json()["fout"]
    assert spraak.tikken == 1


def test_spraak_uit(web):
    c, _, _ = web()
    assert c.post("/api/luister").status_code == 503
    assert c.get("/api/toestand").json()["spraak"]["toestand"] == "uit"


def test_spraak_warmt_op_bij_het_starten(maak):
    o, _ = maak()
    spraak = NepSpraak()
    with TestClient(maak_app(o, start_planner=False, spraak=spraak), base_url=BASIS, client=("127.0.0.1", 1)):
        pass
    assert spraak.opgewarmd and spraak.bij_wijziging is not None
