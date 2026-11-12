"""Shared toy-UI pieces: rounded chunky buttons with press feedback, chips, tiles, icons."""
from __future__ import annotations
import math, time
import pygame
from . import theme as T
from .widgets import text

PAPER, INK, INK_SOFT = (252, 252, 250), (28, 38, 48), (98, 112, 126)
CHIP, OUTLINE, SHADOW = (232, 236, 240), (150, 162, 174), (170, 180, 190)
ORANGE, GREEN, BLUE, RED = (255, 149, 0), (52, 168, 83), (36, 120, 220), (226, 84, 70)

PLANE = [(0, -11), (2, -7), (2, -2), (11, 3), (11, 5), (2, 3), (2, 7), (5, 10), (5, 11), (0, 10),
         (-5, 11), (-5, 10), (-2, 7), (-2, 3), (-11, 5), (-11, 3), (-2, -2), (-2, -7)]
SKY_TOP, SKY_LOW = (122, 186, 238), (206, 232, 252)

_ART: dict = {}
def plane_art(w, h, caption="", heli=False, radius=10) -> pygame.Surface:
    """Stand-in for a missing photo: sky, two soft clouds and the map's own plane (or helicopter) flying up-right,
    with what it is along the bottom. Cached per size/caption."""
    key = (w, h, caption, heli, radius)
    if key in _ART: return _ART[key]
    art = pygame.Surface((w, h), pygame.SRCALPHA)
    for y in range(h):
        t = y / max(1, h - 1)
        art.fill(tuple(int(SKY_TOP[i] + (SKY_LOW[i] - SKY_TOP[i]) * t) for i in range(3)), (0, y, w, 1))
    for cx, cy, cw in ((0.22, 0.30, 0.34), (0.80, 0.62, 0.42)):                 # clouds: three overlapping puffs each
        cw = int(w * cw); x, y = int(w * cx), int(h * cy)
        for dx, dy, r in ((-0.30, 0.10, 0.22), (0.0, -0.05, 0.30), (0.32, 0.10, 0.20)):
            pygame.draw.circle(art, (255, 255, 255, 170), (x + int(dx * cw), y + int(dy * cw)), int(r * cw))
    sc = min(w, h) / 30.0; t = math.radians(45); ct, st = math.cos(t), math.sin(t)
    cx, cy = w * 0.5, h * (0.44 if caption else 0.5)
    R = lambda px, py, d=0: (cx + (px * ct - py * st) * sc + d, cy + (px * st + py * ct) * sc + d * 1.4)
    if heli:                                                       # cabin, tail boom, a soft rotor disc, two blades
        body = [(0, -7), (3.5, -4), (4, 1), (2.5, 4), (-2.5, 4), (-4, 1), (-3.5, -4)]; boom = [(-1.2, 3), (1.2, 3), (0.8, 11), (-0.8, 11)]
        for shape in (boom, body): pygame.draw.polygon(art, (90, 130, 170, 90), [R(*p, sc * 1.2) for p in shape])
        for shape in (boom, body):
            pts = [R(*p) for p in shape]; pygame.draw.polygon(art, PAPER, pts); pygame.draw.polygon(art, INK, pts, max(1, int(sc * 0.35)))
        pygame.draw.line(art, INK, R(-3, 10.5), R(3, 10.5), max(2, int(sc * 0.45)))                    # tail rotor
        disc = pygame.Surface((w, h), pygame.SRCALPHA); hub = R(0, -1)
        pygame.draw.circle(disc, (255, 255, 255, 80), hub, int(sc * 10)); pygame.draw.circle(disc, (255, 255, 255, 150), hub, int(sc * 10), max(1, int(sc * 0.3)))
        art.blit(disc, (0, 0))
        for a0 in (20, 110):
            a1 = math.radians(a0); dx, dy = 10 * math.cos(a1), 10 * math.sin(a1)
            pygame.draw.line(art, (60, 70, 82), R(-dx, -dy - 1), R(dx, dy - 1), max(2, int(sc * 0.55)))
        pygame.draw.circle(art, INK, hub, max(2, int(sc * 0.8)))
    else:
        pygame.draw.polygon(art, (90, 130, 170, 90), [R(*p, sc * 1.2) for p in PLANE])          # shadow on the sky
        pts = [R(*p) for p in PLANE]
        pygame.draw.polygon(art, PAPER, pts); pygame.draw.polygon(art, INK, pts, max(1, int(sc * 0.35)))
    if caption:
        f = T.font(max(12, int(h * 0.11)), weight="extrabold")
        img = f.render(caption, True, INK)
        if img.get_width() > w - 12: img = pygame.transform.smoothscale(img, (w - 12, int(img.get_height() * (w - 12) / img.get_width())))
        band = pygame.Rect(0, h - img.get_height() - 10, w, img.get_height() + 10)
        art.fill((255, 255, 255, 150), band); art.blit(img, img.get_rect(center=band.center))
    mask = pygame.Surface((w, h), pygame.SRCALPHA); pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    art.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MIN)
    _ART[key] = art
    return art

def shadow_rect(s, r, radius, dy=4):
    pygame.draw.rect(s, SHADOW, r.move(0, dy), border_radius=radius)

class Pill:
    """A big rounded button. Draws pressed state while a finger is on it."""
    def __init__(self, rect, label, fill=PAPER, color=INK, size=18, icon=None):
        self.rect = pygame.Rect(rect); self.label = label; self.fill = fill; self.color = color; self.size = size
        self.icon = icon; self.pressed = False
    def hit(self, p): return self.rect.inflate(10, 10).collidepoint(p)
    def draw(self, s, fill=None, color=None, label=None):
        r = self.rect.move(0, 3) if self.pressed else self.rect
        radius = r.h // 2
        if not self.pressed: shadow_rect(s, r, radius)
        pygame.draw.rect(s, fill or self.fill, r, border_radius=radius)
        pygame.draw.rect(s, OUTLINE if (fill or self.fill) == PAPER else (fill or self.fill), r, 3, border_radius=radius)
        lab = label or self.label; col = color or self.color
        if self.icon:
            f = T.font(self.size, weight="extrabold"); tw = f.size(lab)[0]
            ix = r.centerx - (tw + 26) // 2 + 8
            draw_icon(s, self.icon, (ix, r.centery), ORANGE if self.icon == "star" else col)
            s.blit(f.render(lab, True, col), (ix + 18, r.centery - f.get_height() // 2))
        else:
            text(s, lab, self.size, col, r.center, "center", weight="extrabold")

class Round:
    def __init__(self, cx, cy, r, label, size=34, icon=None):
        self.cx, self.cy, self.r, self.label, self.size, self.icon = cx, cy, r, label, size, icon; self.pressed = False
        self.dim = False; self.color = INK          # dim: greyed out, nothing to do yet
    def hit(self, p): return math.hypot(p[0] - self.cx, p[1] - self.cy) <= self.r + 10
    def draw(self, s):
        cy = self.cy + 3 if self.pressed else self.cy
        if not self.pressed: pygame.draw.circle(s, SHADOW, (self.cx, self.cy + 4), self.r)
        pygame.draw.circle(s, (215, 232, 246) if self.pressed else (236, 238, 240) if self.dim else PAPER, (self.cx, cy), self.r)
        pygame.draw.circle(s, (196, 202, 208) if self.dim else OUTLINE, (self.cx, cy), self.r, 3)
        if self.icon: draw_icon(s, self.icon, (self.cx, cy), (178, 186, 194) if self.dim else self.color)
        else: text(s, self.label, self.size, INK, (self.cx, cy - 2), "center", weight="black")

def chip(s, pos, label, icon=None, size=17) -> pygame.Rect:
    """Rounded fact chip: [icon] label. Returns its rect so chips can be laid out in a row."""
    f = T.font(size, weight="bold"); w, h = f.size(label)
    pad = 12; iw = 22 if icon else 0
    r = pygame.Rect(pos[0], pos[1], w + pad * 2 + iw, h + 12)
    pygame.draw.rect(s, CHIP, r, border_radius=r.h // 2)
    if icon: draw_icon(s, icon, (r.x + pad + 8, r.centery))
    s.blit(f.render(label, True, INK), (r.x + pad + iw, r.y + 6))
    return r

def chip_pair(s, pos, left, right, icon=None, size=16, max_w=None) -> pygame.Rect:
    """One rounded chip holding two facts with a divider: [icon] left | right."""
    f = T.font(size, weight="bold")
    parts = [t for t in (left, right) if t]
    if not parts: return pygame.Rect(pos, (0, 0))
    pad, iw, div = 12, 22 if icon else 0, 22
    if max_w:
        while len(parts) == 2 and sum(f.size(t)[0] for t in parts) + pad * 2 + iw + div > max_w and size > 12:
            size -= 1; f = T.font(size, weight="bold")
    w = sum(f.size(t)[0] for t in parts) + pad * 2 + iw + (div if len(parts) == 2 else 0)
    r = pygame.Rect(pos[0], pos[1], w, f.get_height() + 10)
    pygame.draw.rect(s, CHIP, r, border_radius=r.h // 2)
    x = r.x + pad
    if icon: draw_icon(s, icon, (x + 8, r.centery)); x += iw
    s.blit(f.render(parts[0], True, INK), (x, r.y + 5)); x += f.size(parts[0])[0]
    if len(parts) == 2:
        pygame.draw.line(s, OUTLINE, (x + div // 2, r.y + 8), (x + div // 2, r.bottom - 8), 2); x += div
        s.blit(f.render(parts[1], True, INK), (x, r.y + 5))
    return r

def tile(s, rect, big, caption, color=INK, icon=None):
    r = pygame.Rect(rect)
    pygame.draw.rect(s, CHIP, r, border_radius=16)
    f = T.font(28, weight="extrabold"); tw = f.size(big)[0]; iw = 24 if icon else 0
    x = r.centerx - (tw + iw) // 2
    s.blit(f.render(big, True, color), (x, r.y + 16))
    if icon: draw_icon(s, icon, (x + tw + 14, r.y + 16 + f.get_height() // 2), color)
    text(s, caption, 14, INK_SOFT, (r.centerx, r.bottom - 14), "midbottom", weight="bold")

def draw_icon(s, kind, c, col=INK_SOFT):
    x, y = c
    if kind == "up":     pygame.draw.polygon(s, GREEN, [(x, y - 7), (x + 7, y + 5), (x - 7, y + 5)])
    elif kind == "down": pygame.draw.polygon(s, ORANGE, [(x, y + 7), (x + 7, y - 5), (x - 7, y - 5)])
    elif kind == "level": pygame.draw.rect(s, col, (x - 7, y - 2, 14, 4), border_radius=2)
    elif kind == "speed":
        for i, w in enumerate((12, 8, 5)): pygame.draw.rect(s, col, (x - 7, y - 5 + i * 5, w, 3), border_radius=1)
    elif kind == "clock":
        pygame.draw.circle(s, col, (x, y), 8, 2); pygame.draw.line(s, col, (x, y), (x, y - 5), 2); pygame.draw.line(s, col, (x, y), (x + 4, y), 2)
    elif kind == "house":
        pygame.draw.polygon(s, PAPER, [(x, y - 13), (x + 13, y - 1), (x - 13, y - 1)])
        pygame.draw.rect(s, PAPER, (x - 10, y - 2, 20, 12))
        pygame.draw.polygon(s, BLUE, [(x, y - 10), (x + 10, y - 1), (x - 10, y - 1)])
        pygame.draw.rect(s, BLUE, (x - 7, y - 1, 14, 9))
        pygame.draw.rect(s, PAPER, (x - 2, y + 2, 4, 6))
    elif kind == "plus":
        pygame.draw.rect(s, col, (x - 12, y - 3, 24, 6), border_radius=3); pygame.draw.rect(s, col, (x - 3, y - 12, 6, 24), border_radius=3)
    elif kind == "minus":
        pygame.draw.rect(s, col, (x - 12, y - 3, 24, 6), border_radius=3)
    elif kind == "close":
        pygame.draw.line(s, col, (x - 7, y - 7), (x + 7, y + 7), 4); pygame.draw.line(s, col, (x - 7, y + 7), (x + 7, y - 7), 4)
    elif kind == "back":
        pygame.draw.polygon(s, col, [(x - 8, y), (x + 5, y - 9), (x + 5, y + 9)])
    elif kind == "home":
        pygame.draw.polygon(s, col, [(x, y - 13), (x + 14, y), (x - 14, y)])
        pygame.draw.rect(s, col, (x - 10, y - 1, 20, 12)); pygame.draw.rect(s, PAPER, (x - 3, y + 3, 6, 8))
    elif kind == "locate":                                      # 'where am I': ring, dot, four ticks
        pygame.draw.circle(s, col, (x, y), 9, 3); pygame.draw.circle(s, col, (x, y), 4)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            pygame.draw.line(s, col, (x + dx * 9, y + dy * 9), (x + dx * 15, y + dy * 15), 3)
    elif kind == "tick":
        pygame.draw.lines(s, col, False, [(x - 9, y), (x - 3, y + 6), (x + 9, y - 7)], 4)
    elif kind == "star":
        pts = []
        for i in range(10):
            rr = 11 if i % 2 == 0 else 5; a = math.radians(-90 + i * 36)
            pts.append((x + rr * math.cos(a), y + rr * math.sin(a)))
        pygame.draw.polygon(s, col, pts); pygame.draw.polygon(s, PAPER, pts, 2)
    elif kind == "wifi":
        for rr in (4, 8, 12):
            pygame.draw.arc(s, col, pygame.Rect(x - rr, y - rr + 4, 2 * rr, 2 * rr), math.radians(45), math.radians(135), 2)
        pygame.draw.circle(s, col, (x, y + 5), 2)
    elif kind == "antenna":
        pygame.draw.line(s, col, (x, y - 9), (x, y + 8), 2)
        pygame.draw.line(s, col, (x - 6, y + 8), (x + 6, y + 8), 2)
        for rr in (5, 9):
            pygame.draw.arc(s, col, pygame.Rect(x - rr, y - 9 - rr, 2 * rr, 2 * rr), math.radians(200), math.radians(340), 2)
    elif kind == "eye":
        pygame.draw.ellipse(s, col, (x - 10, y - 6, 20, 12), 2); pygame.draw.circle(s, col, (x, y), 3)

MILITARY_OLIVE, INTEREST_YELLOW = (75, 90, 40), (255, 204, 0)

def draw_badge(s, kind, c, r):
    """Small round map badge of radius r centred on c: 'military' = white star on an olive disc,
    'interesting' = dark exclamation mark on a yellow disc."""
    x, y = c
    pygame.draw.circle(s, MILITARY_OLIVE if kind == "military" else INTEREST_YELLOW, (x, y), r)
    if kind == "military":
        pts = [(x + (r * (0.78 if i % 2 == 0 else 0.32)) * math.cos(math.radians(-90 + i * 36)),
                y + (r * (0.78 if i % 2 == 0 else 0.32)) * math.sin(math.radians(-90 + i * 36))) for i in range(10)]
        pygame.draw.polygon(s, PAPER, pts)
    else:
        w = max(2, round(r * 0.34))
        pygame.draw.rect(s, INK, (x - w // 2, y - round(r * 0.62), w, round(r * 0.72)))
        pygame.draw.circle(s, INK, (x, y + round(r * 0.5)), max(1, round(r * 0.2)))
    pygame.draw.circle(s, INK, (x, y), r, 1)

def pulse(period=1.2, lo=0.0, hi=1.0):
    return lo + (hi - lo) * (0.5 + 0.5 * math.sin(time.time() * 2 * math.pi / period))

def route_line(s, o, d, size, color, pos, max_w):
    """'Origin  ->  Dest' with a drawn arrow, fitted to max_w. Returns the rect used."""
    f = T.font(size, weight="extrabold"); arrow_w = int(size * 1.6)
    while size > 13 and f.size(o)[0] + f.size(d)[0] + arrow_w + 20 > max_w:      # shrink first, cut last
        size -= 1; f = T.font(size, weight="extrabold"); arrow_w = int(size * 1.6)
    def fit(t, w):
        while t and f.size(t)[0] > w: t = t[:-1]
        return t if f.size(t)[0] <= w else t + "…"
    budget = max_w - arrow_w - 16
    ow, dw = f.size(o)[0], f.size(d)[0]
    if ow + dw > budget:
        if ow > budget // 2 and dw > budget // 2: o, d = fit(o, budget // 2 - 6) + "…", fit(d, budget // 2 - 6) + "…"
        elif ow > dw: o = fit(o, budget - dw - 6) + "…"
        else: d = fit(d, budget - ow - 6) + "…"
    x, y = pos; h = f.get_height()
    s.blit(f.render(o, True, color), (x, y)); x += f.size(o)[0] + 10
    cy = y + h // 2 + 1; ax = x + arrow_w - 4
    pygame.draw.line(s, color, (x, cy), (ax, cy), max(3, size // 7))
    pygame.draw.polygon(s, color, [(ax + 2, cy), (ax - size // 3, cy - size // 3), (ax - size // 3, cy + size // 3)])
    x += arrow_w + 10
    s.blit(f.render(d, True, color), (x, y))
    return pygame.Rect(pos[0], y, x + f.size(d)[0] - pos[0], h)


def journey_line(s, o, d, frac, size, color, pos, max_w):
    """'Origin  ●━━━━✈┄┄┄○  Dest': how far along the trip the plane is. Falls back to route_line when tight."""
    f = T.font(size, weight="extrabold"); ow, dw = f.size(o)[0], f.size(d)[0]
    bar = max_w - ow - dw - 36
    if bar < 150: return route_line(s, o, d, size, color, pos, max_w)
    bar = min(bar, 420)
    x, y = pos; h = f.get_height(); cy = y + h // 2 + 1
    s.blit(f.render(o, True, color), (x, y)); x0 = x + ow + 18; x1 = x0 + bar
    px = x0 + (x1 - x0) * max(0.0, min(1.0, frac))
    for xx in range(int(px) + 10, int(x1) - 6, 11): pygame.draw.circle(s, (210, 190, 170), (xx, cy), 2)       # still to go
    pygame.draw.line(s, color, (x0, cy), (px, cy), 5)                                                       # done
    pygame.draw.circle(s, color, (x0, cy), 7)
    pygame.draw.circle(s, PAPER, (x1, cy), 7); pygame.draw.circle(s, color, (x1, cy), 7, 3)
    sc = size / 14.0; t = math.radians(90); ct, st = math.cos(t), math.sin(t)
    poly = [(px + (a * ct - b * st) * sc, cy + (a * st + b * ct) * sc) for a, b in PLANE]
    pygame.draw.polygon(s, PAPER, poly); pygame.draw.polygon(s, color, poly, 2)
    s.blit(f.render(d, True, color), (x1 + 18, y))
    return pygame.Rect(pos[0], y, x1 + 18 + dw - pos[0], h)
