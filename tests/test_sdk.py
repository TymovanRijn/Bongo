"""Het brein met de échte Anthropic-bibliotheek; alleen het netwerk is nep.

De andere tests gebruiken NepClaude, die de bibliotheek overslaat. Deze tests laten de
bibliotheek het verzoek echt bouwen en het antwoord echt inlezen, met antwoorden en
foutmeldingen zoals de API ze geeft. Zo vallen fouten op in alles daartussen.
"""

import json
import logging

import anthropic
import httpx2
import pytest

from assistent.brain import BreinFout
from assistent.cli import Terminal
from assistent.opbouw import maak_onderdelen


def bericht(content, stop):
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 2500, "output_tokens": 120, "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 0},
    }


def api_fout(status, soort, melding):
    return httpx2.Response(status, json={"type": "error", "error": {"type": soort, "message": melding}, "request_id": "req_01"})


@pytest.fixture
def met_server(inst):
    """met_server(antwoorden) -> (onderdelen, verzoeken): een echte client tegen een nep-server."""

    def _maak(antwoorden):
        verzoeken = []

        def server(request):
            verzoeken.append({"koppen": dict(request.headers), "body": json.loads(request.content)})
            antwoord = antwoorden.pop(0)
            return antwoord if isinstance(antwoord, httpx2.Response) else httpx2.Response(200, json=antwoord)

        client = anthropic.Anthropic(
            api_key="sk-ant-nep", http_client=httpx2.Client(transport=httpx2.MockTransport(server)), max_retries=0
        )
        return maak_onderdelen(inst, client=client), verzoeken

    return _maak


def test_tool_ronde_door_de_echte_bibliotheek(met_server):
    o, verzoeken = met_server(
        [
            bericht(
                [
                    {"type": "thinking", "thinking": "", "signature": "sig-1"},
                    {"type": "tool_use", "id": "toolu_01", "name": "agenda_lezen", "input": {"van": "2030-03-04", "tot": "2030-03-04"}},
                ],
                "tool_use",
            ),
            bericht([{"type": "text", "text": "Je agenda is leeg.", "citations": None}], "end_turn"),
        ]
    )
    antwoord = o.brain.vraag("Wat heb ik op 4 maart 2030?")
    assert antwoord.tekst == "Je agenda is leeg."
    assert antwoord.kosten_usd > 0

    eerste, tweede = (v["body"] for v in verzoeken)
    assert verzoeken[0]["koppen"]["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert eerste["model"] == "claude-opus-5-5" and eerste["fallbacks"] == "default"
    assert [t["name"] for t in eerste["tools"]] == ["agenda_lezen", "afspraak_voorstellen", "onthouden_voorstellen", "vergeten_voorstellen"]
    # Het denkblok gaat ongewijzigd terug, en de tool_use krijgt zijn tool_result.
    assert tweede["messages"][1]["content"][0] == {"type": "thinking", "thinking": "", "signature": "sig-1"}
    assert tweede["messages"][2]["content"][0]["tool_use_id"] == "toolu_01"


@pytest.mark.parametrize(
    "antwoord, melding",
    [
        (
            api_fout(400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API."),
            "Er staat geen tegoed meer op je Anthropic-account",
        ),
        (api_fout(404, "not_found_error", "model: claude-opus-5-5"), "Ik kan het model claude-opus-5-5 niet vinden"),
        (api_fout(401, "authentication_error", "invalid x-api-key"), "Mijn API-sleutel wordt geweigerd"),
        (api_fout(400, "invalid_request_error", "tools.1: iets onverwachts"), "Er ging iets mis bij het nadenken"),
        (api_fout(529, "overloaded_error", "Overloaded"), "Claude heeft op dit moment een storing"),
    ],
)
def test_weigeringen_van_de_api(met_server, antwoord, melding):
    o, _ = met_server([antwoord])
    with pytest.raises(BreinFout) as fout:
        o.brain.vraag("Wat heb ik vandaag?")
    assert fout.value.melding.startswith(melding)
    # De technische oorzaak is wat de API zelf zei, zonder alles eromheen.
    assert fout.value.technisch == f"{antwoord.status_code} {antwoord.json()['error']['type']}: {antwoord.json()['error']['message']}"


def test_de_oorzaak_staat_in_de_terminal_en_in_het_logbestand(met_server, caplog):
    o, _ = met_server([api_fout(400, "invalid_request_error", "tools.1: iets onverwachts")])
    with caplog.at_level(logging.WARNING, logger="assistent.brain"):
        uit = Terminal(o).verwerk("Wat heb ik vandaag?")
    assert uit == "Bongo: Er ging iets mis bij het nadenken.\n   (technisch: 400 invalid_request_error: tools.1: iets onverwachts)"
    assert "tools.1: iets onverwachts" in caplog.text
