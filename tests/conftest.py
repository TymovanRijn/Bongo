"""Fixtures voor alle tests. De nep-Claude zelf staat in nep_claude.py."""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assistent.config import Instellingen  # noqa: E402
from assistent.opbouw import maak_onderdelen  # noqa: E402
from nep_claude import TZ, Klok, NepClaude  # noqa: E402


# ---- fixtures ---------------------------------------------------------------------------
@pytest.fixture
def inst(tmp_path) -> Instellingen:
    data = tmp_path / "data"
    return Instellingen(
        anthropic_api_key="nep-sleutel",
        data_dir=data,
        db_pad=data / "assistent.sqlite3",
        geheugen_pad=data / "over_mij.md",
        log_dir=data / "logs",
        calendar_backend="mock",
    )


@pytest.fixture
def klok() -> Klok:
    return Klok(datetime(2026, 10, 7, 14, 0, tzinfo=TZ))


@pytest.fixture
def maak(inst, klok):
    """maak(antwoorden, **instellingen) -> (onderdelen, nep_claude)"""

    def _maak(antwoorden=(), **anders):
        nep = NepClaude(antwoorden)
        o = maak_onderdelen(replace(inst, **anders), client=nep)
        o.brain.klok = klok
        return o, nep

    return _maak
