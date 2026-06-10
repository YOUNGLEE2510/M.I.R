"""
utils.py – Shared utility functions
"""
import re
from pathlib import Path

# ── European / German → Anglo-American note mapping ───────────────────────────
# Order matters: longer tokens must come first so "Cis" beats "C", "As" beats "A"
_EU_TO_ANGLO: list[tuple[str, str]] = [
    # Sharps (German "is" suffix)
    ("Cis", "C#"), ("Dis", "D#"), ("Eis", "E#"), ("Fis", "F#"),
    ("Gis", "G#"), ("Ais", "A#"), ("His", "B#"),
    # Flats (German "s"/"es" suffix);  "Es"=Eb, "As"=Ab, "B"=Bb (classic German)
    ("Des", "Db"), ("Es",  "Eb"), ("Ges", "Gb"), ("As",  "Ab"), ("Hes", "Bb"),
    # "B" alone = Bb in German/European notation (H = B-natural)
    ("H",   "B"),  ("B",   "Bb"),
]

# Regex: European token  e.g. Cis4 | As3 | H5 | Ges2
_EU_PAT = re.compile(
    r"(?:^|[_\- ])([A-H](?:is|es|s)?)(\d)(?=$|[_\- .])",
    re.IGNORECASE,
)

# Regex: Anglo token  e.g. C#4 | Ab3 | F5
_ANGLO_PAT = re.compile(
    r"(?:^|[_\- ])([A-G][#b]?)(\d)(?=$|[_\- .])",
    re.IGNORECASE,
)


def _eu_to_anglo(token: str) -> str:
    """Convert European note letter (without octave) to Anglo equivalent."""
    upper = token.upper()  # normalise casing
    # Capitalise only first letter so "CIS" → "Cis" for dict lookup
    cap = upper[0] + upper[1:].lower()
    for eu, anglo in _EU_TO_ANGLO:
        if cap == eu:
            return anglo
    # Already Anglo (A-G, no suffix)
    return upper


def parse_note_from_filename(filename: str) -> str:
    """Extract musical note from filename.

    Supports:
    - Anglo-American notation  : C4, A#3, Bb5, F#2
    - European/German notation : Cis4, As3, Es4, Gis5, H3, B4 (=Bb4)

    Returns a canonical Anglo note string like "C#4" or "unknown".
    """
    stem = Path(filename).stem

    # 1. Try European first (longer tokens, higher priority)
    m = _EU_PAT.search(stem)
    if m:
        note_letter = _eu_to_anglo(m.group(1))
        octave = m.group(2)
        tok = note_letter + octave
        # Fix double-flat edge-case that slipped through (BBb → Bb)
        return tok.replace("BBb", "Bb").replace("BB", "Bb")

    # 2. Fallback: Anglo notation
    m = _ANGLO_PAT.search(stem)
    if not m:
        return "unknown"
    tok = m.group(1).upper() + m.group(2)
    return tok.replace("BB", "Bb")
