"""Meet hoe snel en hoe duur Bongo is met verschillende modellen: `python -m assistent.meet`

Stelt dezelfde vragen aan elke combinatie van model en denkstand, elke vraag in een nieuw
gesprek en zoals bij spraak (korte antwoorden). Het gebeurt met de nep-agenda in een
tijdelijke map: je eigen agenda, geheugen en wachtrij blijven onaangeroerd. Het kost wel
echt geld: bij elkaar een paar dubbeltjes.

Kijk niet alleen naar de tijd, maar lees ook de antwoorden: sneller is alleen beter als
het antwoord nog klopt.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
from dataclasses import replace
from pathlib import Path

from .brain import BreinFout
from .config import laad_instellingen
from .opbouw import maak_onderdelen

VRAGEN = [
    "Wat heb ik vandaag?",
    "Heb ik morgen na de lunch nog iets?",
    "Zet volgende week dinsdag om drie uur de kapper erin.",
    "Hoeveel dagen is het nog tot kerst?",
]
COMBINATIES = [
    ("claude-opus-5-5", "adaptief"),
    ("claude-sonnet-5-5", "adaptief"),
    ("claude-sonnet-5-5", "tussen_tools"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m assistent.meet", description=__doc__.splitlines()[0])
    parser.add_argument("--alleen", metavar="MODEL", help="meet alleen dit model, bijvoorbeeld claude-sonnet-5-5")
    args = parser.parse_args(argv)

    inst = laad_instellingen()
    if not inst.anthropic_api_key:
        print("Zet eerst ANTHROPIC_API_KEY in .env.")
        return 1
    combinaties = [c for c in COMBINATIES if not args.alleen or c[0] == args.alleen]
    print(f"{len(VRAGEN)} vragen x {len(combinaties)} instellingen. Dat duurt een paar minuten.\n")

    uitslag = []
    for model, denken in combinaties:
        with tempfile.TemporaryDirectory() as map_:
            data = Path(map_)
            proef = replace(
                inst, model=model, denken=denken, calendar_backend="mock", data_dir=data,
                db_pad=data / "meet.sqlite3", geheugen_pad=data / "over_mij.md", log_dir=data / "logs",
            )
            o = maak_onderdelen(proef)
            print(f"== {model}, denken: {denken}")
            tijden, kosten = [], []
            for vraag in VRAGEN:
                o.brain.nieuw_gesprek("meting")
                try:
                    a = o.brain.vraag(vraag, bron="spraak")
                except BreinFout as e:
                    print(f"   {vraag}\n   FOUT: {e.technisch}\n")
                    continue
                tijden.append(a.ms / 1000)
                kosten.append(a.kosten_usd)
                tools = ", ".join(t["tool"] for t in a.tool_aanroepen) or "geen"
                print(f"   {vraag}  ({a.ms / 1000:.1f} s, $ {a.kosten_usd:.4f}, tools: {tools})\n   -> {a.tekst}\n")
            if tijden:
                uitslag.append((model, denken, statistics.median(tijden), max(tijden), statistics.mean(kosten)))

    print("Samenvatting (mediaan en langzaamste antwoordtijd, gemiddelde kosten per vraag):")
    for model, denken, mediaan, traagst, prijs in sorted(uitslag, key=lambda u: u[2]):
        print(f"   {model:18} {denken:13} {mediaan:5.1f} s  (traagst {traagst:4.1f} s)   $ {prijs:.4f}")
    print("\nKies je iets anders dan de standaard, zet dan in .env bijvoorbeeld:")
    print("   BONGO_MODEL=claude-sonnet-5-5\n   BONGO_DENKEN=tussen_tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
