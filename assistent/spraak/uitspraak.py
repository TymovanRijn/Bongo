"""Tekst uitspreekbaar maken, vlak voordat hij naar de stem gaat.

Een stem leest letterlijk voor wat er staat. Piper maakte van "**niets**" "sterretje sterretje niets
sterretje sterretje", van een emoji "lachend gezicht met lachende ogen" en van "10:00-10:30" "tien nul
nul tien dertig". Claude krijgt de opdracht om te schrijven zoals je praat, maar dat lukt niet altijd;
dit is het vangnet. De ondertitel op het scherm houdt de gewone tekst.
"""

from __future__ import annotations

import re

GETALLEN = ["nul", "een", "twee", "drie", "vier", "vijf", "zes", "zeven", "acht", "negen", "tien", "elf",
            "twaalf", "dertien", "veertien"]
MAANDEN = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september",
           "oktober", "november", "december"]

AFKORTINGEN = [
    (r"bijv\.|bv\.", "bijvoorbeeld"),
    (r"ca\.", "ongeveer"),
    (r"o\.a\.", "onder andere"),
    (r"d\.w\.z\.", "dat wil zeggen"),
    (r"i\.p\.v\.", "in plaats van"),
    (r"m\.b\.t\.", "met betrekking tot"),
    (r"o\.b\.v\.", "op basis van"),
    (r"z\.s\.m\.", "zo snel mogelijk"),
    (r"t/m|t\.e\.m\.", "tot en met"),
    (r"a\.s\.", "aanstaande"),
    (r"incl\.", "inclusief"),
    (r"excl\.", "exclusief"),
    (r"evt\.", "eventueel"),
    (r"nr\.", "nummer"),
    (r"etc\.|enz\.", "enzovoort"),
    # Geen "jan.": dat is vaker de naam Jan dan januari.
    (r"feb\.", "februari"), (r"mrt\.", "maart"), (r"apr\.", "april"),
    (r"jun\.", "juni"), (r"jul\.", "juli"), (r"aug\.", "augustus"), (r"sept?\.", "september"),
    (r"okt\.", "oktober"), (r"nov\.", "november"), (r"dec\.", "december"),
]
_AFKORTING = [(re.compile(rf"(?<![\w.]){patroon}(?!\w)", re.I), voluit) for patroon, voluit in AFKORTINGEN]

_TIJD = r"([01]?\d|2[0-3]):([0-5]\d)"
_TIJDVAK = re.compile(rf"\b{_TIJD}\s*[-–—]\s*{_TIJD}(\s*uur)?\b")
_TIJDSTIP = re.compile(
    r"\b(?P<u>[01]?\d|2[0-3]):(?P<m>[0-5]\d)(\s*uur)?\b"  # 14:30, 14:30 uur
    r"|\b(?P<u2>[01]?\d|2[0-3])\.(?P<m2>[0-5]\d)\s*uur\b"  # 14.30 uur
)
_DATUM = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_EURO = re.compile(r"€\s?(\d+)(?:[,.](\d{2}|-))?|(\d+),(\d{2})\s?euro\b")
_MINUTEN = re.compile(r"(\d)\s?min\.?(?!\w)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_URL = re.compile(r"https?://\S+")
_OPMAAK = re.compile(r"\*\*|__|(?<!\w)[*_](?=\w)|(?<=\w)[*_](?!\w)|`|^#+\s*|^\s*[-•]\s+|^\s*>\s*", re.M)
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF"  # emoji
    "\u2600-\u27BF\u2B00-\u2BFF"  # zonnetjes, vinkjes, sterren
    "\uFE0F\u200D\u20E3\U000E0000-\U000E007F]"  # onzichtbare emoji-lijm
)
_PIJL = re.compile(r"[→←⇒➔]")


def _uur(uur: int) -> str:
    return GETALLEN[(uur % 12) or 12]  # 14 uur is "twee", 0 uur is "twaalf"


def tijd(uur: int, minuut: int) -> str:
    """Zoals je het zegt: 14:30 is "half drie", 10:20 is "tien voor half elf"."""
    nu, straks = _uur(uur), _uur(uur + 1)
    if minuut == 0:
        return f"{nu} uur"
    if minuut == 15:
        return f"kwart over {nu}"
    if minuut == 30:
        return f"half {straks}"
    if minuut == 45:
        return f"kwart voor {straks}"
    if minuut < 15:
        return f"{GETALLEN[minuut]} over {nu}"
    if minuut < 30:
        return f"{GETALLEN[30 - minuut]} voor half {straks}"
    if minuut < 45:
        return f"{GETALLEN[minuut - 30]} over half {straks}"
    return f"{GETALLEN[60 - minuut]} voor {straks}"


def spreekbaar(tekst: str) -> str:
    t = _LINK_MD.sub(r"\1", tekst)
    t = _URL.sub("een link", t)
    t = _OPMAAK.sub("", t)
    t = _EMOJI.sub("", t)
    t = _PIJL.sub(",", t)
    t = _TIJDVAK.sub(lambda m: f"{tijd(int(m[1]), int(m[2]))} tot {tijd(int(m[3]), int(m[4]))}", t)
    t = _TIJDSTIP.sub(lambda m: tijd(int(m["u"] or m["u2"]), int(m["m"] or m["m2"])), t)
    t = _DATUM.sub(lambda m: f"{int(m[3])} {MAANDEN[int(m[2]) - 1]} {m[1]}" if 1 <= int(m[2]) <= 12 else m[0], t)
    t = _EURO.sub(_euro, t)
    t = _MINUTEN.sub(r"\1 minuten", t)
    for patroon, voluit in _AFKORTING:
        t = patroon.sub(voluit, t)
    t = t.replace("&", " en ")
    return re.sub(r"\s+", " ", t).strip()


def _euro(m: re.Match) -> str:
    euro, cent = (m[1], m[2]) if m[1] else (m[3], m[4])
    return f"{euro} euro" + (f" {int(cent)}" if cent and cent not in ("-", "00") else "")
