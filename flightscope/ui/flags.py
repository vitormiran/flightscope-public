"""Country flags for the route line: flightscope/data/flags/<cc>.png (see tools/fetch_flags.py), scaled to a height
and cached. No code, or no flag for it: None, and the name is drawn without one."""
from __future__ import annotations
from pathlib import Path
import pygame

DIR = Path(__file__).resolve().parent.parent / "data" / "flags"
EDGE = (150, 158, 166)
_RAW: dict[str, pygame.Surface | None] = {}
_SCALED: dict[tuple, pygame.Surface] = {}

def flag(code, h: int) -> pygame.Surface | None:
    code = (code or "").strip().lower()
    if len(code) != 2 or not code.isalpha(): return None
    key = (code, h)
    if key in _SCALED: return _SCALED[key]
    if code not in _RAW:
        try: _RAW[code] = pygame.image.load(str(DIR / f"{code}.png")).convert_alpha()
        except (pygame.error, FileNotFoundError): _RAW[code] = None
    raw = _RAW[code]
    if raw is None: return None
    w = max(1, round(raw.get_width() * h / raw.get_height()))
    out = pygame.transform.smoothscale(raw, (w, h))
    pygame.draw.rect(out, EDGE, out.get_rect(), 1)                 # a hairline, so a white flag doesn't vanish into the card
    _SCALED[key] = out
    return out
