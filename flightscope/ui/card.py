"""Full-screen plane card: big photo, big words, fact tiles."""
from __future__ import annotations
import pygame
from . import theme as T
from .widgets import text, fit_text, vscale
from .. import names
from .kid import plane_art, journey_line, Pill, tile, route_line, PAPER, INK, INK_SOFT, CHIP, ORANGE, GREEN
from .city import CityScreen
from .mapview import halo_text, ROUTE

W, H = 800, 480

class CardScreen:
    def __init__(self, app, hex: str):
        self.app = app; self.hex = hex
        self.back = Pill((14, 14, 130, 50), "Map", size=19, icon="back")
        self._down = None; self._hits = {}; self._places = {}

    def handle(self, e):
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE): return self.app.pop()
        if e.type == pygame.MOUSEBUTTONDOWN:
            self._down = e.pos; self.back.pressed = self.back.hit(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP:
            self.back.pressed = False
            if self._down:
                for k, r in self._hits.items():     # a city name: its picture
                    if r.inflate(24, 20).collidepoint(self._down) and r.inflate(24, 20).collidepoint(e.pos) and k in self._places:
                        name, lat, lon = self._places[k]; self._down = None
                        return self.app.push(CityScreen(self.app, name, lat, lon))
                self.app.pop()                      # anywhere else: back to the map
            self._down = None

    def update(self, dt):
        if self.hex not in self.app.fleet.by_hex: self.app.pop()

    @staticmethod
    def _progress(a, rt):
        """0 at the origin, 1 at the destination, by distance flown vs distance to go; None if we can't tell."""
        o, d = rt.origin, rt.dest
        if not (o and d and o.get("lat") is not None and d.get("lat") is not None and a.lat is not None): return None
        from ..geo import gc_nm
        done, togo = gc_nm(o["lat"], o["lon"], a.lat, a.lon), gc_nm(a.lat, a.lon, d["lat"], d["lon"])
        return done / (done + togo) if done + togo > 1 else None

    def draw(self, s):
        s.fill(PAPER)
        a = self.app.fleet.by_hex.get(self.hex)
        if a is None: return
        pr = pygame.Rect(0, 0, W, 230)
        ph = self.app.photos.get(a.hex)
        if ph: s.blit(vscale(ph, pr.w, pr.h), pr)
        else:
            s.blit(plane_art(pr.w, pr.h, "", names.kind(a) == "Helicopter", radius=0), pr)
        c = self.app.photos.credit(a.hex)
        if ph and c: halo_text(s, f"photo: {c}", 11, INK_SOFT, (W - 10, pr.bottom - 8), "bottomright", bold=False)
        self.back.draw(s)
        rt = names.plausible_route(a, self.app.routes.get(a.flight, (a.lat, a.lon), urgent=True))
        y = pr.bottom + 8
        text(s, fit_text(names.label_for(a, rt), 32, 640, weight="black"), 32, INK, (20, y), "topleft", weight="black")
        text(s, a.flight or "", 15, INK_SOFT, (W - 20, y + 12), "topright", weight="bold")
        y += 40
        kind = names.plane_type(a.type, a.desc) if a.type else names.kind(a)
        text(s, fit_text(f"{kind} ({a.reg or a.hex.upper()})", 17, 640, weight="bold"), 17, INK_SOFT, (20, y), "topleft", weight="bold")
        y += 24
        self._hits = {}; self._places = {}
        if rt and (rt.origin or rt.dest):
            frac = self._progress(a, rt)
            fl = ((rt.origin or {}).get("country"), (rt.dest or {}).get("country"))
            if frac is None: route_line(s, names.place(rt.origin), names.place(rt.dest), 24, ROUTE, (20, y), 760, self._hits, fl)
            else: journey_line(s, names.place(rt.origin), names.place(rt.dest), frac, 24, ROUTE, (20, y), 760, self._hits, fl)
            for k, ap in (("o", rt.origin), ("d", rt.dest)):
                if ap and k in self._hits and names.place(ap) != "?":          # tappable: underlined, and only for a real place name
                    self._places[k] = (names.place(ap), ap.get("lat"), ap.get("lon"))
                    r = self._hits[k + "_t"]; pygame.draw.line(s, ROUTE, (r.x, r.bottom - 2), (r.right, r.bottom - 2), 2)
        # fact tiles
        tiles = []
        if a.on_ground: tiles.append(("on the ground", "RIGHT NOW", INK, None))
        else:
            if a.alt is not None:
                icon = "up" if (a.vr or 0) > 300 else "down" if (a.vr or 0) < -300 else None
                tiles.append((f"{a.alt:,} ft", "HOW HIGH", GREEN if icon == "up" else ORANGE if icon == "down" else INK, icon))
            if a.gs: tiles.append((f"{a.gs * 1.151:.0f} mph", "HOW FAST", INK, None))
        ago, eta = names.flight_times(a, rt)
        if ago: tiles.append((ago.replace("took off about ", "").replace(" ago", ""), "TOOK OFF", INK, None) if ago.startswith("took") else ("just now", "TOOK OFF", INK, None))
        if eta: tiles.append((eta.replace("lands in about ", ""), "LANDS IN", ROUTE, None) if eta.startswith("lands") else ("now!", "LANDING", ROUTE, None))
        if a.dst is not None and len(tiles) < 4: tiles.append((f"{a.dst:.0f} miles", "FROM HOME", INK, None))
        n = len(tiles)
        if n:
            gap, tw = 14, min(190, (W - 40 - 14 * (n - 1)) // n)
            x = (W - (tw * n + gap * (n - 1))) // 2
            for big, cap, col, icon in tiles:
                tile(s, (x, 350, tw, 104), big, cap, col, icon); x += tw + gap
