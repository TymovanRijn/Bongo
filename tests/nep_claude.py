"""Een nep-Claude voor de tests, plus hulpjes om antwoorden klaar te zetten.

`NepClaude` doet alsof hij de Anthropic-API is. Zo kosten de tests geen geld en werken
ze zonder internet. Hij geeft de antwoorden die de test vooraf klaarzet, en hij
controleert een paar regels van de echte API. Breekt het brein zo'n regel, dan krijgt
het (net als in het echt) een BadRequestError. Gecontroleerd wordt:

- elke tool_use krijgt in het volgende bericht een tool_result;
- wie tool_use of tool_result meestuurt, moet ook de tools meesturen;
- een systeembericht midden in het gesprek volgt op een bericht van de gebruiker;
- een denkblok is gebonden aan het gesprek waarin het ontstond: systeemprompt, tools
  en alle berichten ervoor moeten hetzelfde zijn als toen ("preserved thinking").
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import anthropic
import httpx2

TZ = ZoneInfo("Europe/Amsterdam")
GEBRUIK = SimpleNamespace(input_tokens=1000, output_tokens=50, cache_creation_input_tokens=0, cache_read_input_tokens=0)


# ---- antwoorden die een test klaarzet -------------------------------------------------
def tekst(t: str, stop: str = "end_turn") -> SimpleNamespace:
    """Een gewoon antwoord: een (leeg) denkblok en daarna tekst."""
    return SimpleNamespace(
        content=[{"type": "thinking", "thinking": "", "signature": None}, {"type": "text", "text": t}],
        stop_reason=stop,
        usage=GEBRUIK,
        model="claude-opus-5-5",
    )


def tool(naam: str, invoer: dict, tool_id: str = "toolu_1") -> SimpleNamespace:
    """Claude wil een tool gebruiken."""
    return SimpleNamespace(
        content=[
            {"type": "thinking", "thinking": "", "signature": None},
            {"type": "tool_use", "id": tool_id, "name": naam, "input": invoer},
        ],
        stop_reason="tool_use",
        usage=GEBRUIK,
        model="claude-opus-5-5",
    )


def weigering() -> SimpleNamespace:
    return SimpleNamespace(content=[], stop_reason="refusal", usage=GEBRUIK, model="claude-opus-5-5")


_VERZOEK = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def api_fout(melding: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(melding, response=httpx2.Response(400, request=_VERZOEK), body=None)


def geen_verbinding() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_VERZOEK)


# ---- de nep-API -------------------------------------------------------------------------
def _schoon(x):
    """cache_control mag verschuiven zonder dat de inhoud 'verandert'."""
    if isinstance(x, dict):
        return {k: _schoon(v) for k, v in x.items() if k != "cache_control"}
    if isinstance(x, list):
        return [_schoon(v) for v in x]
    return x


def _zonder_denken(berichten: list[dict]) -> list[dict]:
    uit = []
    for b in berichten:
        if isinstance(b.get("content"), list):
            b = {**b, "content": [x for x in b["content"] if x.get("type") not in ("thinking", "redacted_thinking")]}
        uit.append(b)
    return uit


def vingerafdruk(system, tools, berichten) -> str:
    """Wat een denkblok 'onthoudt' van het gesprek waarin het ontstond: systeemprompt, tools
    en alle eerdere berichten. (Eerdere denkblokken tellen niet mee, net als bij de echte API.)"""
    inhoud = json.dumps(_schoon([system, tools, _zonder_denken(berichten)]), sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(inhoud.encode()).hexdigest()[:16]


class NepClaude:
    def __init__(self, antwoorden=()):
        self.antwoorden = list(antwoorden)
        self.verzoeken: list[dict] = []
        self.gestreamd: list[bool] = []  # per verzoek: met streaming of niet
        self.pauze_na_zin = 0.0  # zo lang "schrijft" hij na elke zin (om streaming te testen)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create, stream=self._stream))

    def zet_klaar(self, *antwoorden) -> None:
        self.antwoorden.extend(antwoorden)

    def _create(self, **kwargs):
        self.gestreamd.append(False)
        return self._antwoord(kwargs)

    def _stream(self, **kwargs):
        self.gestreamd.append(True)
        return _NepStroom(self._antwoord(kwargs), self.pauze_na_zin)

    def _antwoord(self, kwargs):
        verzoek = copy.deepcopy(kwargs)
        self.verzoeken.append(verzoek)
        self._controleer(verzoek)
        if not self.antwoorden:
            raise AssertionError("NepClaude kreeg een verzoek, maar de test had geen antwoord klaargezet")
        antwoord = self.antwoorden.pop(0)
        if isinstance(antwoord, Exception):
            raise antwoord
        antwoord = copy.deepcopy(antwoord)
        handtekening = vingerafdruk(verzoek.get("system"), verzoek.get("tools"), verzoek["messages"])
        for blok in antwoord.content:
            if blok.get("type") == "thinking" and blok.get("signature") is None:
                blok["signature"] = handtekening
        return antwoord

    def _controleer(self, v: dict) -> None:
        berichten = v["messages"]
        if not berichten or berichten[0]["role"] != "user":
            raise api_fout("messages: first message must use the 'user' role")
        blokken = [b for m in berichten if isinstance(m["content"], list) for b in m["content"]]
        if not v.get("tools") and any(b.get("type") in ("tool_use", "tool_result") for b in blokken):
            raise api_fout("Requests which include `tool_use` or `tool_result` blocks must define tools.")
        for i, m in enumerate(berichten):
            if m["role"] == "system":
                if berichten[i - 1]["role"] != "user" or (i + 1 < len(berichten) and berichten[i + 1]["role"] != "assistant"):
                    raise api_fout(f"messages.{i}: a system message must follow a user message")
            if m["role"] != "assistant" or not isinstance(m["content"], list):
                continue
            ids = {b["id"] for b in m["content"] if b.get("type") == "tool_use"}
            volgende = berichten[i + 1]["content"] if i + 1 < len(berichten) else []
            beantwoord = {b.get("tool_use_id") for b in volgende if isinstance(volgende, list)}
            if not ids <= beantwoord:
                raise api_fout(f"messages.{i}: `tool_use` ids were found without `tool_result` blocks immediately after")
            for j, b in enumerate(m["content"]):
                if b.get("type") == "thinking" and b.get("signature") != vingerafdruk(v.get("system"), v.get("tools"), berichten[:i]):
                    raise api_fout(
                        f"messages.{i}.content.{j}: Invalid `signature` in `thinking` block. "
                        "The block is bound to a different conversation."
                    )


class _NepStroom:
    """Zoals client.beta.messages.stream(): de tekst komt woord voor woord binnen."""

    def __init__(self, antwoord, pauze_na_zin=0.0):
        self.antwoord = antwoord
        self.pauze_na_zin = pauze_na_zin

    def __enter__(self):
        return self

    def __exit__(self, *fout):
        return False

    @property
    def text_stream(self):
        for blok in self.antwoord.content:
            if blok.get("type") == "text":
                for woord in re.findall(r"\S+\s*", blok["text"]):
                    yield woord
                    if woord.rstrip().endswith((".", "!", "?")):
                        time.sleep(self.pauze_na_zin)

    def get_final_message(self):
        return self.antwoord


# ---- een klok die de test zelf kan verzetten -------------------------------------------
class Klok:
    def __init__(self, tijd: datetime):
        self.tijd = tijd

    def __call__(self) -> datetime:
        return self.tijd

    def verzet(self, **hoeveel) -> None:
        self.tijd += timedelta(**hoeveel)
