"""
utils.py – Shared utility functions
"""
import re
from pathlib import Path


def parse_note_from_filename(filename: str) -> str:
    """Extract musical note (e.g. C4, A#3) from filename."""
    stem = Path(filename).stem
    m = re.search(r"(^|[_\- ])([A-G](?:#|b)?\d)($|[_\- ])", stem, flags=re.IGNORECASE)
    if not m:
        return "unknown"
    tok = m.group(2).upper()
    return tok.replace("BB", "Bb")
