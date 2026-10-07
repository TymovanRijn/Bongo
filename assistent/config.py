"""Instellingen, gelezen uit .env in de projectmap (en de omgeving).

Alles wat Tymo wil kunnen veranderen staat hier, met een veilige standaardwaarde.
De beslispunten uit het bouwplan staan in docs/beslispunten.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# override=True: wat in .env staat, gaat voor. Anders wint een variabele die toevallig al in de
# omgeving staat; Claude Code zet bijvoorbeeld zelf CLAUDE_EFFORT. Daarom heten Bongo's eigen
# instellingen ook BONGO_..., zodat ze nooit per ongeluk van een ander programma komen.
load_dotenv(ROOT / ".env", override=True)


def _tekst(naam: str, standaard: str = "") -> str:
    return os.environ.get(naam, standaard).strip()


def _getal(naam: str, standaard: int) -> int:
    waarde = _tekst(naam)
    return int(waarde) if waarde else standaard


def _ja(naam: str, standaard: bool) -> bool:
    waarde = _tekst(naam).lower()
    if not waarde:
        return standaard
    return waarde in ("1", "ja", "true", "aan", "yes", "on")


def _pad(naam: str, standaard: Path) -> Path:
    waarde = _tekst(naam)
    if not waarde:
        return standaard
    pad = Path(waarde).expanduser()
    return pad if pad.is_absolute() else ROOT / pad


@dataclass(frozen=True)
class Instellingen:
    # Claude
    anthropic_api_key: str = ""
    # Alleen nodig als de sleutel niet bij één workspace hoort (dan weigert de API anders elk verzoek).
    anthropic_workspace_id: str = ""
    model: str = "claude-opus-5-5"
    effort: str = "low"
    # adaptief: het model bepaalt zelf of en hoeveel het nadenkt (op effort low meestal kort).
    # tussen_tools: geen extra nadenken, alleen korte notities tussen tool-aanroepen. Alleen voor
    # claude-sonnet-5-5; Opus 5.5 kan niet zonder nadenken.
    denken: str = "adaptief"
    max_tokens: int = 16000
    assistent_naam: str = "Bongo"
    gebruiker_naam: str = "Tymo"
    tijdzone: str = "Europe/Amsterdam"

    # Opslag
    data_dir: Path = ROOT / "data"
    db_pad: Path = ROOT / "data" / "assistent.sqlite3"
    geheugen_pad: Path = ROOT / "data" / "over_mij.md"
    log_dir: Path = ROOT / "data" / "logs"

    # Agenda
    calendar_backend: str = "mock"  # mock | icloud
    icloud_gebruiker: str = ""
    icloud_wachtwoord: str = ""
    icloud_agenda: str = ""  # naar welke agenda geschreven wordt
    icloud_lees_agendas: tuple[str, ...] = ()  # leeg = alle agenda's lezen

    # Beslispunt 1: gespreksgeheugen
    gespreksgeheugen: str = "stilte"  # stilte | laatste_n | samenvatten
    stilte_minuten: int = 10
    max_beurten: int = 20

    # Kern / webapp
    kern_host: str = "0.0.0.0"
    kern_poort: int = 8765
    # Beslispunt 2: toegang tot de webapp
    toegang: str = "pin"  # open | pin | link
    pin: str = ""
    tailscale_toegestaan: bool = False
    extra_netwerken: tuple[str, ...] = ()

    # Beslispunt 4: mag een hardop "ja" een voorstel goedkeuren?
    stem_bevestigen: bool = False

    # Beslispunt 5: ochtendoverzicht
    ochtend_tijd: str = "07:30"
    ochtend_uitspreken: bool = False

    # Spraak (fase 3, zie docs/spraak.md)
    spraak: bool = True
    mic_apparaat: str = "default"  # ALSA-naam, bijvoorbeeld plughw:CARD=ArrayUAC10,DEV=0
    mic_kanalen: int = 1  # 6 bij de ReSpeaker met 6-kanaalsfirmware
    mic_kanaal: int = 0  # welk kanaal is de stem (bij de ReSpeaker: 0, met echo-onderdrukking)
    speaker_apparaat: str = "default"
    stt_model: str = "small"  # Whisper: tiny, base, small, medium (groter = beter en trager)
    stem: str = "nl_NL-mls-medium"  # Piper-stem

    # Scherm
    nacht_van: str = "23:00"
    nacht_tot: str = "07:00"
    nacht_scherm_uit: bool = False



def laad_instellingen() -> Instellingen:
    data_dir = _pad("DATA_DIR", ROOT / "data")
    lees = tuple(a.strip() for a in _tekst("ICLOUD_READ_CALENDARS").split(",") if a.strip())
    extra_net = tuple(n.strip() for n in _tekst("EXTRA_NETWERKEN").split(",") if n.strip())
    return Instellingen(
        anthropic_api_key=_tekst("ANTHROPIC_API_KEY"),
        anthropic_workspace_id=_tekst("ANTHROPIC_WORKSPACE_ID"),
        model=_tekst("BONGO_MODEL", "claude-opus-5-5"),
        effort=_tekst("BONGO_EFFORT", "low"),
        denken=_tekst("BONGO_DENKEN", "adaptief").lower(),
        max_tokens=_getal("BONGO_MAX_TOKENS", 16000),
        assistent_naam=_tekst("ASSISTENT_NAAM", "Bongo"),
        gebruiker_naam=_tekst("GEBRUIKER_NAAM", "Tymo"),
        tijdzone=_tekst("TIJDZONE", "Europe/Amsterdam"),
        data_dir=data_dir,
        db_pad=data_dir / "assistent.sqlite3",
        geheugen_pad=data_dir / "over_mij.md",
        log_dir=data_dir / "logs",
        calendar_backend=_tekst("CALENDAR_BACKEND", "mock").lower(),
        icloud_gebruiker=_tekst("ICLOUD_USERNAME"),
        icloud_wachtwoord=_tekst("ICLOUD_APP_PASSWORD"),
        icloud_agenda=_tekst("ICLOUD_CALENDAR_NAME"),
        icloud_lees_agendas=lees,
        gespreksgeheugen=_tekst("GESPREKSGEHEUGEN", "stilte").lower(),
        stilte_minuten=_getal("GESPREK_STILTE_MINUTEN", 10),
        max_beurten=_getal("GESPREK_MAX_BEURTEN", 20),
        kern_host=_tekst("KERN_HOST", "0.0.0.0"),
        kern_poort=_getal("KERN_POORT", 8765),
        toegang=_tekst("WEB_TOEGANG", "pin").lower(),
        pin=_tekst("WEB_PIN"),
        tailscale_toegestaan=_ja("TAILSCALE_TOEGESTAAN", False),
        extra_netwerken=extra_net,
        stem_bevestigen=_ja("STEM_BEVESTIGEN", False),
        ochtend_tijd=_tekst("OCHTEND_TIJD", "07:30"),
        ochtend_uitspreken=_ja("OCHTEND_UITSPREKEN", False),
        spraak=_ja("SPRAAK", True),
        mic_apparaat=_tekst("MIC_APPARAAT", "default"),
        mic_kanalen=_getal("MIC_KANALEN", 1),
        mic_kanaal=_getal("MIC_KANAAL", 0),
        speaker_apparaat=_tekst("SPEAKER_APPARAAT", "default"),
        stt_model=_tekst("STT_MODEL", "small"),
        stem=_tekst("STEM", "nl_NL-mls-medium"),
        nacht_van=_tekst("NACHT_VAN", "23:00"),
        nacht_tot=_tekst("NACHT_TOT", "07:00"),
        nacht_scherm_uit=_ja("NACHT_SCHERM_UIT", False),
    )
