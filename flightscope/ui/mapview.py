"""The main screen: a map with planes on it. Drag to move, pinch or +/- to zoom,
tap a plane to see where it came from and where it's going, FOLLOW to ride along."""
from __future__ import annotations
import json, math, threading, time
from pathlib import Path
import pygame
from . import theme as T
from .widgets import text, fit_text, vscale
from ..geo import nm_xy
from .. import names
from ..touch import PINCH
from ..world import World, lod_for
from .kid import plane_art, Pill, Round, chip, chip_pair, draw_icon, draw_badge, pulse, route_line, ORANGE, GREEN, BLUE, RED, CHIP, OUTLINE

MAP_PATH = Path(__file__).resolve().parent.parent / "data" / "map.json"
W, H = 800, 480
ZOOM_MIN, ZOOM_MAX, ZOOM_START, ZOOM_STEP = 5.0, 6000.0, 36.0, 1.6    # NM across the screen (6000: half the world)
LAYER_W, LAYER_H = 2400, 1440
CARD_H = 160
HIT = 48

SEA, LAND, URBAN, RIVER, COAST = (176, 212, 236), (238, 241, 228), (230, 232, 220), (146, 190, 224), (110, 150, 180)
INK, INK_SOFT, PAPER = (28, 38, 48), (98, 112, 126), (252, 252, 250)
RUNWAY, AIRPORT, TOWN = (90, 96, 104), (70, 80, 92), (98, 112, 126)
HOME, ROUTE = (36, 120, 220), (150, 80, 0)
BORDER, COUNTRY = (196, 170, 200), (150, 120, 160)

PLANE = [(0, -11), (2, -7), (2, -2), (11, 3), (11, 5), (2, 3), (2, 7), (5, 10), (5, 11), (0, 10),
         (-5, 11), (-5, 10), (-2, 7), (-2, 3), (-11, 5), (-11, 3), (-2, -2), (-2, -7)]

_LABELS: dict[tuple, pygame.Surface] = {}
def label_surf(txt, size, color, bold=True, halo=PAPER) -> pygame.Surface:
    """Text with a halo, rendered once and cached."""
    key = (txt, size, color, bold, halo)
    if key not in _LABELS:
        f = T.font(size, bold)
        base = f.render(txt, True, halo); w, h = base.get_size()
        s = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            s.blit(base, (2 + dx, 2 + dy))
        s.blit(f.render(txt, True, color), (2, 2))
        _LABELS[key] = s
    return _LABELS[key]

def place(s, img, placed, cands) -> bool:
    """Blit img at the first candidate (anchor, pos) that doesn't collide with placed rects."""
    for anchor, pos in cands:
        r = img.get_rect(**{anchor: pos})
        if not any(r.colliderect(p) for p in placed):
            placed.append(r); s.blit(img, r); return True
    return False

def halo_text(s, txt, size, color, pos, anchor="topleft", bold=True, halo=PAPER):
    img = label_surf(txt, size, color, bold, halo)
    r = img.get_rect(**{anchor: pos}); s.blit(img, r); return r

class MapScreen:
    def __init__(self, app):
        self.app = app; self.cfg = app.cfg
        self.center = [self.cfg.home_lat, self.cfg.home_lon]
        self.zoom = float(self.cfg.start_zoom_nm or ZOOM_START)
        self.selected: str | None = None
        self.follow = False
        self.map = self._load_map(); self.world = World()
        self._labels = ([], [], [])             # (airports, places, countries) worth labelling in the current layer
        self._layer = None; self._layer_center = None; self._layer_zoom = None; self._layer_world = False
        self._building = False; self._built = None      # a new layer drawn in the background, waiting to be swapped in
        self._down = None; self._dragging = False; self._last = None
        self._pinch = None                  # (zoom at start, last centre)
        self.b_plus = Round(W - 46, 64, 32, "", icon="plus")          # rail ends above the card (top at H - CARD_H)
        self.b_minus = Round(W - 46, 136, 32, "", icon="minus")
        self.b_home = Round(W - 46, 208, 32, "", icon="home")
        self.b_gps = Round(W - 46, 280, 32, "", icon="locate"); self.b_gps.color = BLUE
        self.b_book = Round(46, 46, 32, "", icon="star")
        self.card_rect = pygame.Rect(0, H - CARD_H, W, CARD_H)
        self.b_follow = Pill((W - 178, H - CARD_H + 22, 164, 54), "FOLLOW", ORANGE, (255, 255, 255), 19)
        self.b_log = Pill((W - 178, H - CARD_H + 88, 164, 54), "LOG", size=18, icon="plus")
        self.b_close = Round(W - 30, H - CARD_H + 2, 22, "", icon="close")
        self._pressed = None; self._hold = None      # time the home button went down (hold 3 s -> setup)
        self._ripple = None                 # (x, y, t) for tap feedback
        self._trail = pygame.Surface((W, H), pygame.SRCALPHA)
        self._empty_since = time.time() - 10; self._found = None
        self._anim = None                       # (t0, centre0, zoom0, centre1, zoom1) while gliding
        self._party = None                      # (t0, x, y, particles) after a catch    # 'Looking for planes' banner: shown from the start

    # ---------- geometry ----------
    @property
    def k(self): return W / self.zoom

    def to_px(self, lat, lon, center=None, origin=(W / 2, H / 2), k=None):
        c = center or self.center; k = k or self.k
        x, y = nm_xy(lat, lon, c[0], c[1])
        return origin[0] + x * k, origin[1] - y * k

    def to_geo(self, x, y):
        dx_nm, dy_nm = (x - W / 2) / self.k, (H / 2 - y) / self.k
        return (self.center[0] + dy_nm / 60.0, self.center[1] + dx_nm / 60.0 / max(0.2, math.cos(math.radians(self.center[0]))))

    def pan_px(self, dx, dy):
        self.center[1] -= dx / self.k / 60.0 / max(0.2, math.cos(math.radians(self.center[0])))
        self.center[1] = (self.center[1] + 540.0) % 360.0 - 180.0          # round the world and back
        self.center[0] = max(-72.0, min(72.0, self.center[0] + dy / self.k / 60.0))

    def set_zoom_about(self, new_zoom, px):
        """Change zoom keeping the geographic point under px fixed on screen."""
        new_zoom = max(ZOOM_MIN, min(ZOOM_MAX, new_zoom))
        g = self.to_geo(*px)
        self.zoom = new_zoom
        x2, y2 = self.to_px(*g)
        self.pan_px(px[0] - x2, px[1] - y2)

    def zoom_by(self, f, px=(W / 2, H / 2)):
        if px == (W / 2, H / 2) and self._pinch is None:                # the +/- buttons: glide
            base = self._anim[4] if self._anim else self.zoom
            return self.glide_to(self._anim[3] if self._anim else self.center, base * f)
        self.set_zoom_about(self.zoom * f, px)

    # ---------- map layer ----------
    def _load_map(self):
        try: m = json.load(open(MAP_PATH))
        except Exception: m = {}
        for key in ("land", "lakes", "urban", "coast", "rivers"):
            m.setdefault(key, [])
            m[key] = [(p, (min(q[0] for q in p), max(q[0] for q in p), min(q[1] for q in p), max(q[1] for q in p))) for p in m[key]]
        for key in ("airports", "runways", "places"): m.setdefault(key, [])
        if "home" in m:                                   # the detailed map's own box (build_map.py's clip)
            hl, hlo = m["home"]; r = m.get("radius_nm", 220)
            dlat = r / 60.0; dlon = r / 60.0 / max(0.2, math.cos(math.radians(hl)))
            m["box"] = (hl - dlat, hl + dlat, hlo - dlon, hlo + dlon)
        return m

    def feed_points(self):
        """Where the internet feed should look: the view. Wide views get a grid of 250 NM circles, centre first."""
        c = self.center; hw, hh = self.zoom / 2, self.zoom * H / W / 2; need = math.hypot(hw, hh)
        if need <= 150: return [(c[0], c[1], max(150, int(self.cfg.net_radius_nm)))]
        if need <= 250: return [(c[0], c[1], 250)]
        step = 350.0
        while math.ceil(2 * hw / step) * math.ceil(2 * hh / step) > 9: step *= 1.25
        nx, ny = math.ceil(2 * hw / step), math.ceil(2 * hh / step)
        cos = max(0.2, math.cos(math.radians(c[0]))); pts = []
        for i in range(nx):
            for j in range(ny):
                ex, ny_ = (i - (nx - 1) / 2) * step, (j - (ny - 1) / 2) * step
                pts.append((math.hypot(ex, ny_), max(-80, min(80, c[0] + ny_ / 60)), c[1] + ex / 60 / cos))
        pts.sort()
        return [(la, lo, 250) for _, la, lo in pts]

    def _layer_needed(self):
        if self._layer is None or self._layer_zoom != self.zoom or self._layer_world != self.world.ready: return True
        lx, ly = self.to_px(self.center[0], self.center[1], self._layer_center, (LAYER_W / 2, LAYER_H / 2))
        return abs(lx - LAYER_W / 2) > (LAYER_W - W) / 2 - 40 or abs(ly - LAYER_H / 2) > (LAYER_H - H) / 2 - 40

    def _refresh_layer(self):
        """The first layer is drawn there and then; after that a thread draws the next one while the old one is
        shown (shifted or stretched), so crossing a layer edge or finishing a pinch never freezes the screen."""
        if self._built: self._layer, self._layer_center, self._layer_zoom, self._layer_world, self._labels = self._built; self._built = None
        if self._pinch is not None or (self._anim is not None and self._layer is not None) or not self._layer_needed(): return
        job = (list(self.center), self.zoom, self.world.ready)
        if self._layer is None:
            self._layer, self._layer_center, self._layer_zoom, self._layer_world, self._labels = self._build_layer(*job); return
        if self._building: return
        self._building = True
        def run():
            try: self._built = self._build_layer(*job)
            except Exception as e: print(f"map layer: {type(e).__name__}: {e}", flush=True)
            finally: self._building = False
        threading.Thread(target=run, name="map-layer", daemon=True).start()

    def _build_layer(self, c, z, ready):
        t0 = time.time(); k = W / z; org = (LAYER_W / 2, LAYER_H / 2)
        s = pygame.Surface((LAYER_W, LAYER_H)); s.fill(SEA)
        half_lat = LAYER_H / 2 / k / 60 + 0.05
        half_lon = LAYER_W / 2 / k / 60 / max(0.2, math.cos(math.radians(c[0]))) + 0.05
        dl = lambda lo: (lo - c[1] + 540) % 360 - 180
        vis = lambda bb: not (bb[1] < c[0] - half_lat or bb[0] > c[0] + half_lat or dl(bb[3]) < -half_lon or dl(bb[2]) > half_lon)
        to_px = lambda la, lo: self.to_px(la, lo, c, org, k)
        P = lambda pts: [to_px(la, lo) for la, lo in pts]
        wd, lod = self.world, lod_for(z)
        if ready:                                                   # the whole world, simplified for this zoom
            wd.draw(s, "land", lod, c, org, k, LAND)
            if lod == "f" and z <= 110: wd.draw(s, "urban", lod, c, org, k, URBAN)
            wd.draw(s, "lakes", lod, c, org, k, SEA)
            wd.draw(s, "coast", lod, c, org, k, COAST, lines=True, width=2 if z <= 1200 else 1)
        box = self.map.get("box")
        if z <= 250 and box and vis((box[0], box[1], box[2], box[3])):   # home: the detailed map over the top
            (bx0, by0), (bx1, by1) = to_px(box[1], box[2]), to_px(box[0], box[3])
            if ready: s.fill(SEA, pygame.Rect(int(bx0), int(by0), int(bx1 - bx0) + 1, int(by1 - by0) + 1))
            for pts, bb in self.map["land"]:
                if vis(bb) and len(pts) > 2: pygame.draw.polygon(s, LAND, P(pts))
            if z <= 110:
                for pts, bb in self.map["urban"]:
                    if vis(bb) and len(pts) > 2: pygame.draw.polygon(s, URBAN, P(pts))
            for pts, bb in self.map["lakes"]:
                if vis(bb) and len(pts) > 2: pygame.draw.polygon(s, SEA, P(pts))
            if z <= 60:
                for pts, bb in self.map["rivers"]:
                    if vis(bb): pygame.draw.lines(s, RIVER, False, P(pts), 2)
            for pts, bb in self.map["coast"]:
                if vis(bb): pygame.draw.lines(s, COAST, False, P(pts), 2)
            if z <= 60:
                for la0, lo0, la1, lo1 in self.map["runways"]:
                    a, b = to_px(la0, lo0), to_px(la1, lo1)
                    if 0 <= a[0] <= LAYER_W and 0 <= a[1] <= LAYER_H: pygame.draw.line(s, RUNWAY, a, b, max(3, int(k * 0.06)))
        if ready: wd.draw(s, "border", lod, c, org, k, BORDER, lines=True, width=2 if z <= 1200 else 1)
        inl = lambda la, lo: abs(la - c[0]) <= half_lat and abs(dl(lo)) <= half_lon
        thresh = self._town_threshold(z)
        places = [p for p in self.map["places"] + wd.labels["places"] if p["pop"] >= thresh and inl(p["lat"], p["lon"])]
        airports = sorted((a for a in self.map["airports"] + wd.labels["airports"] if self._airport_shown(a, z) and inl(a["lat"], a["lon"])), key=lambda a: -a["rank"])
        for p in places:
            x, y = to_px(p["lat"], p["lon"]); pygame.draw.circle(s, TOWN, (x, y), 3)
        for a in airports:
            x, y = to_px(a["lat"], a["lon"])
            r = 7 if a["rank"] == 3 else 5
            pygame.draw.circle(s, PAPER, (x, y), r + 2); pygame.draw.circle(s, AIRPORT, (x, y), r)
            pygame.draw.circle(s, PAPER, (x, y), r - 3)
        countries = [n for n in wd.labels["countries"] if z >= 500 and n["min"] <= self._country_level(z) and inl(n["lat"], n["lon"])]
        print(f"map layer {z:.0f} NM ({lod}) in {time.time() - t0:.2f}s", flush=True)
        return s, c, z, ready, (airports, places, countries)

    @staticmethod
    def _country_level(z):
        return 5.0 if z <= 900 else 4.0 if z <= 1800 else 3.0 if z <= 3500 else 2.0

    @staticmethod
    def _town_threshold(z):
        return (0 if z <= 14 else 15000 if z <= 30 else 40000 if z <= 60 else 120000 if z <= 110 else 300000 if z <= 250
                else 1500000 if z <= 700 else 4000000 if z <= 1800 else 10000000)

    @staticmethod
    def _airport_shown(a, z):
        return (a["rank"] == 3 and z <= 700) or (a["rank"] == 2 and z <= 110) or (a["rank"] == 1 and z <= 30)

    # ---------- input ----------
    def handle(self, e):
        if e.type == PINCH:
            if e.phase == "start":
                self._down = None; self._dragging = False; self.follow = False; self._anim = None; self._hold = None
                if self._pressed: self._pressed.pressed = False; self._pressed = None       # a finger that began on a button
                self._pinch = (self.zoom, e.center)
            elif e.phase == "move" and self._pinch:
                z0, last = self._pinch
                self.pan_px(e.center[0] - last[0], e.center[1] - last[1])
                self.set_zoom_about(z0 / max(0.2, e.scale), e.center)
                self._pinch = (z0, e.center)
            elif e.phase == "end":
                self._pinch = None
            return
        if e.type == pygame.KEYDOWN:
            if e.key in (pygame.K_MINUS, pygame.K_LEFTBRACKET): self.zoom_by(ZOOM_STEP)
            if e.key in (pygame.K_EQUALS, pygame.K_RIGHTBRACKET): self.zoom_by(1 / ZOOM_STEP)
            if e.key == pygame.K_h: self.go_home()
            return
        if e.type == pygame.MOUSEBUTTONDOWN:
            if self._anim: self._glide(); self._anim = None                 # a finger stops a glide where it is
            self._down = e.pos; self._last = e.pos; self._dragging = False
            self._pressed = next((b for b in self._buttons() if b.hit(e.pos)), None)
            if self._pressed: self._pressed.pressed = True
            self._hold = time.time() if self._pressed is self.b_home else None
        elif e.type == pygame.MOUSEMOTION and self._down is not None:
            if not self._dragging and math.hypot(e.pos[0] - self._down[0], e.pos[1] - self._down[1]) > 14:
                self._dragging = True; self.follow = False
            if self._dragging: self.pan_px(e.pos[0] - self._last[0], e.pos[1] - self._last[1])
            self._last = e.pos
        elif e.type == pygame.MOUSEBUTTONUP and self._down is not None:
            self._hold = None
            if self._pressed: self._pressed.pressed = False; self._pressed = None
            if not self._dragging: self.tap(self._down)
            self._down = None; self._dragging = False

    def _buttons(self):
        bs = [self.b_plus, self.b_minus, self.b_home, self.b_gps, self.b_book]
        if self.selected: bs += [self.b_follow, self.b_log, self.b_close]
        return bs

    def log_selected(self):
        a = self.app.fleet.by_hex.get(self.selected)
        if a is None: return
        from pathlib import Path
        src = Path(self.app.photos.dir) / f"{a.hex}.jpg"
        if self.app.logbook.press(a, self.route_for(a), src if src.exists() else None, self.app.photos.credit(a.hex)) in ("new", "again"):
            self._ripple = (self.b_log.rect.centerx, self.b_log.rect.centery, time.time())
            import random
            cols = (ORANGE, GREEN, BLUE, RED, (255, 214, 64))
            parts = [(random.uniform(0, 2 * math.pi), random.uniform(160, 420), random.choice(cols), random.random() < 0.4, random.uniform(-6, 6))
                     for _ in range(36)]
            self._party = (time.time(), self.b_log.rect.centerx, self.b_log.rect.centery, parts)

    def go_home(self):
        self.follow = False                                  # back to the starting view, not just the place
        self.glide_to([self.cfg.home_lat, self.cfg.home_lon], float(self.cfg.start_zoom_nm or ZOOM_START))

    def go_here(self):
        here = self.app.gps.here()                          # greyed out (does nothing) until the GPS has a fix
        if here: self.follow = False; self.glide_to(list(here), self.zoom)

    GLIDE_S = 0.45

    def glide_to(self, center, zoom):
        """Ease to a new view instead of jumping. The current layer is stretched meanwhile (as in a pinch); a
        target the layer doesn't reach just jumps, rather than sliding over blank sea."""
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if self._layer is not None:
            lx, ly = self.to_px(center[0], center[1], self._layer_center, (LAYER_W / 2, LAYER_H / 2), k=W / self._layer_zoom)
            if 0 <= lx <= LAYER_W and 0 <= ly <= LAYER_H:
                self._anim = (time.time(), list(self.center), self.zoom, list(center), zoom); return
        self._anim = None; self.center = list(center); self.zoom = zoom

    def _glide(self):
        t0, c0, z0, c1, z1 = self._anim
        t = min(1.0, (time.time() - t0) / self.GLIDE_S); e = 1 - (1 - t) ** 3                # ease-out
        dlon = (c1[1] - c0[1] + 540) % 360 - 180
        self.center = [c0[0] + (c1[0] - c0[0]) * e, c0[1] + dlon * e]
        self.zoom = z0 * (z1 / z0) ** e
        if t >= 1.0: self.center, self.zoom, self._anim = list(c1), z1, None

    def tap(self, p):
        if self.b_plus.hit(p): return self.zoom_by(1 / ZOOM_STEP)
        if self.b_minus.hit(p): return self.zoom_by(ZOOM_STEP)
        if self.b_home.hit(p): return self.go_home()
        if self.b_gps.hit(p): return self.go_here()
        if self.b_book.hit(p): return self.app.push(self.app.make_logbook())
        if self.selected and self.b_close.hit(p): self.selected = None; self.follow = False; return
        if self.selected and self.card_rect.collidepoint(p):
            if self.b_follow.hit(p): self.follow = not self.follow; return
            if self.b_log.hit(p): return self.log_selected()
            return self.app.push(self.app.make_card(self.selected))
        self._ripple = (p[0], p[1], time.time())
        now = time.time(); best, bd = None, HIT
        for a in self.app.fleet.positioned():
            x, y = self.to_px(*a.est_pos(now))
            d = math.hypot(x - p[0], y - p[1])
            if d < bd: best, bd = a.hex, d
        if best is None: self.selected = None; self.follow = False
        elif best == self.selected: self.app.push(self.app.make_card(best))
        else: self.selected = best; self.follow = False

    HOLD_S = 3.0

    def update(self, dt):
        if self._anim: self._glide()
        if self._hold and not self._dragging and time.time() - self._hold >= self.HOLD_S:     # grown-ups' door
            self._hold = None; self._down = None; self.b_home.pressed = False; self._pressed = None
            self.app.push(self.app.make_admin()); return
        if self._hold and self._dragging: self._hold = None
        if self.selected and self.selected not in self.app.fleet.by_hex:
            self.selected = None; self.follow = False
        if self.follow and self.selected:
            la, lo = self.app.fleet.by_hex[self.selected].est_pos(time.time())
            if la is not None:
                self.center = [la, lo]
                self.pan_px(0, -(H / 2 - (H - CARD_H) / 2))       # centre in the map you can see, not under the card

    # ---------- draw ----------
    def draw(self, s):
        self._refresh_layer()
        self._blit_layer(s)
        placed: list[pygame.Rect] = [pygame.Rect(W - 90, 24, 90, 296), pygame.Rect(0, 0, 100, 100), pygame.Rect(92, 20, 260, 52)]   # buttons, mode chip
        if self.selected: placed.append(pygame.Rect(0, H - CARD_H, W, CARD_H))
        banner = self._banner_state()
        if banner: placed.append(pygame.Rect(W / 2 - 200, H - 100, 400, 100))
        self._draw_home(s, placed)
        sel = self.app.fleet.by_hex.get(self.selected) if self.selected else None
        if sel: self._draw_route(s, sel, placed)
        self._draw_planes(s, sel, placed)
        self._draw_you(s, placed)
        self._draw_map_labels(s, placed)
        if self._ripple:
            x, y, t0 = self._ripple; age = time.time() - t0
            if age < 0.35:
                rr = pygame.Surface((120, 120), pygame.SRCALPHA)
                pygame.draw.circle(rr, (*ORANGE, int(160 * (1 - age / 0.35))), (60, 60), int(12 + 44 * age / 0.35), 4)
                s.blit(rr, (x - 60, y - 60))
            else: self._ripple = None
        self.b_gps.dim = self.app.gps.here() is None
        for b in (self.b_plus, self.b_minus, self.b_home, self.b_gps, self.b_book): b.draw(s)
        if self._hold and not self._dragging:                                                 # progress ring while holding Home
            held = time.time() - self._hold
            if held > 0.5:
                b = self.b_home; frac = min(1.0, (held - 0.5) / (self.HOLD_S - 0.5))
                pygame.draw.arc(s, ORANGE, pygame.Rect(b.cx - b.r - 6, b.cy - b.r - 6 + 3, 2 * b.r + 12, 2 * b.r + 12), math.pi / 2 - 2 * math.pi * frac, math.pi / 2, 5)
        n = len(self.app.logbook.by_hex)
        if n:
            br = pygame.Rect(0, 0, 30, 24); br.center = (self.b_book.cx + 24, self.b_book.cy - 22)
            pygame.draw.rect(s, ORANGE, br, border_radius=12); pygame.draw.rect(s, PAPER, br, 2, border_radius=12)
            text(s, str(n), 14, PAPER, br.center, "center", weight="black")
        self._draw_mode(s)
        if banner: self._draw_banner(s, *banner)
        if sel: self._draw_card(s, sel)
        if self._party: self._draw_party(s)

    PARTY_S = 1.4

    def _draw_party(self, s):
        """A catch! Confetti bursts from the LOG button and a star flies up to the logbook, which pops."""
        t0, x0, y0, parts = self._party; t = time.time() - t0
        if t > self.PARTY_S: self._party = None; return
        for ang, v, col, star, spin in parts:                                     # confetti with a bit of gravity
            if t > 1.0: break
            x = x0 + math.cos(ang) * v * t; y = y0 + math.sin(ang) * v * t + 520 * t * t
            if star: draw_icon(s, "star", (x, y), col)
            else:
                a = spin * t; dx, dy = 6 * math.cos(a), 6 * math.sin(a)
                pygame.draw.line(s, col, (x - dx, y - dy), (x + dx, y + dy), 5)
        bx, by = self.b_book.cx, self.b_book.cy                                    # the star's flight to the logbook
        f = min(1.0, t / 0.9); e = f * f * (3 - 2 * f)
        if f < 1.0:
            x = x0 + (bx - x0) * e; y = y0 + (by - y0) * e - math.sin(math.pi * e) * 120
            big = pygame.Surface((60, 60), pygame.SRCALPHA); draw_icon(big, "star", (30, 30), ORANGE)
            big = pygame.transform.rotozoom(big, -360 * e, 2.4 - 1.2 * e); s.blit(big, big.get_rect(center=(x, y)))
        else:
            g = (t - 0.9) / (self.PARTY_S - 0.9)                                    # the logbook button pops
            pygame.draw.circle(s, ORANGE, (bx, by), int(self.b_book.r + 6 + 26 * g), max(1, int(6 * (1 - g))))

    BANNER_FOUND_S = 3.0

    def _banner_state(self):
        """('look', seconds empty) while the map has no planes; ('found', n, age) for a few seconds when they arrive."""
        now = time.time(); n = len(self.app.fleet.positioned())
        if n == 0:
            if self._empty_since is None: self._empty_since = now; self._found = None
            return ("look", now - self._empty_since) if now - self._empty_since > 1.5 else None   # ignore a blip
        if self._empty_since is not None:
            if now - self._empty_since > 1.5: self._found = (n, now)
            self._empty_since = None
        if self._found and now - self._found[1] < self.BANNER_FOUND_S:
            return ("found", len(self.app.fleet.positioned()), now - self._found[1])
        return None

    def _draw_banner(self, s, kind, *a):
        """Bottom-centre pill. Looking: a radar sweep + hopping dots (no reading needed). Found: green, tick, count."""
        if kind == "look":
            age = a[0]; label = "Looking for planes" if age < 60 else "Still looking for planes"
            fill, col, extra = PAPER, BLUE, 52; slide = max(0.0, 1 - (age - 1.5) / 0.3)
        else:
            n, age = a; label = "Found a plane!" if n == 1 else f"Found {n} planes!"
            fill, col, extra = GREEN, PAPER, 0; slide = max(0.0, (age - (self.BANNER_FOUND_S - 0.4)) / 0.4)
        f = T.font(22, weight="black"); tw = f.size(label)[0]
        r = pygame.Rect(0, 0, 66 + tw + extra + 26, 60); r.midbottom = (W // 2, H - 22 + int(100 * slide ** 2))
        pygame.draw.rect(s, (170, 180, 190), r.move(0, 4), border_radius=30)
        pygame.draw.rect(s, fill, r, border_radius=30)
        pygame.draw.rect(s, OUTLINE if fill == PAPER else fill, r, 3, border_radius=30)
        cx, cy = r.x + 38, r.centery
        if kind == "look":                                                        # radar: ring, sweeping arm, blip
            pygame.draw.circle(s, (215, 230, 246), (cx, cy), 18); pygame.draw.circle(s, BLUE, (cx, cy), 18, 2)
            ang = time.time() * 3.0
            pygame.draw.line(s, BLUE, (cx, cy), (cx + 17 * math.cos(ang), cy + 17 * math.sin(ang)), 3)
            pygame.draw.circle(s, ORANGE, (cx + 8, cy - 7), int(2 + 3 * pulse(1.0)))
        else: draw_icon(s, "tick", (cx, cy), PAPER)
        s.blit(f.render(label, True, col), (r.x + 66, cy - f.get_height() // 2))
        if kind == "look":
            dx = r.x + 66 + tw + 14
            for i in range(3):
                on = int(time.time() * 3) % 4 > i
                pygame.draw.circle(s, BLUE if on else (205, 214, 224), (dx + i * 16, cy + 6), 5)

    def _blit_layer(self, s):
        lz = self._layer_zoom; lk = W / lz
        lx, ly = self.to_px(self.center[0], self.center[1], self._layer_center, (LAYER_W / 2, LAYER_H / 2), k=lk)
        if abs(lz - self.zoom) < 1e-9:
            ox, oy = W / 2 - lx, H / 2 - ly
            if ox > 0 or oy > 0 or ox + LAYER_W < W or oy + LAYER_H < H: s.fill(SEA)      # dragged past it before the next one is ready
            s.blit(self._layer, (ox, oy)); return
        f = lz / self.zoom                                   # screen px per layer px
        src = pygame.Rect(0, 0, int(W / f), int(H / f)); src.center = (int(lx), int(ly))
        clip = src.clip(self._layer.get_rect())
        s.fill(SEA)
        if clip.w > 1 and clip.h > 1:
            part = pygame.transform.scale(self._layer.subsurface(clip), (max(1, int(clip.w * f)), max(1, int(clip.h * f))))
            s.blit(part, ((clip.x - src.x) * f, (clip.y - src.y) * f))

    def _draw_home(self, s, placed):
        x, y = self.to_px(self.cfg.home_lat, self.cfg.home_lon)
        if -20 < x < W + 20 and -20 < y < H + 20:
            draw_icon(s, "house", (x, y))
            placed.append(pygame.Rect(x - 14, y - 14, 28, 28))
            placed.append(halo_text(s, "Home", 13, HOME, (x + 17, y), "midleft"))

    def _draw_you(self, s, placed):
        """Where we are, as in any maps app: blue dot with a white rim, a soft accuracy halo, a pulse, and a
        heading cone when moving. Grey once the fix is more than a minute old. On top of everything on the map."""
        g = self.app.gps
        if g.lat is None: return
        live = g.here() is not None
        x, y = self.to_px(g.lat, g.lon)
        if not (-40 < x < W + 40 and -40 < y < H + 40): return
        col = HOME if live else (150, 158, 166)
        acc_m = max(5.0, (g.hdop or 1.5) * 5.0)                             # rough: ~5 m per unit of HDOP
        acc = int(acc_m / 1852.0 * self.k)
        over = pygame.Surface((240, 240), pygame.SRCALPHA); c = (120, 120)
        if 14 < acc < 118: pygame.draw.circle(over, (*col, 40), c, acc); pygame.draw.circle(over, (*col, 90), c, acc, 1)
        if live and g.speed_kt > 2 and g.course is not None:                 # which way we're going
            t = math.radians(g.course - 90); spread = math.radians(30)
            for r, a in ((50, 35), (38, 45), (26, 60)):                      # a fan that fades with distance
                arc = [(c[0] + r * math.cos(t + spread * (i / 4 - 1)), c[1] + r * math.sin(t + spread * (i / 4 - 1))) for i in range(9)]
                pygame.draw.polygon(over, (*col, a), [c] + arc)
        if live:
            ph = (time.time() % 2.0) / 2.0                                    # a ring that swells and fades
            pygame.draw.circle(over, (*col, int(110 * (1 - ph))), c, int(10 + 22 * ph), 3)
        pygame.draw.circle(over, (0, 0, 0, 45), (c[0], c[1] + 2), 11)       # little shadow
        s.blit(over, (x - 120, y - 120))
        pygame.draw.circle(s, PAPER, (x, y), 10); pygame.draw.circle(s, col, (x, y), 7)
        placed.append(pygame.Rect(x - 12, y - 12, 24, 24))

    def _dotted(self, s, a, b, color, step=11, r=2):
        dx, dy = b[0] - a[0], b[1] - a[1]; L = math.hypot(dx, dy)
        if L < 1: return
        ux, uy = dx / L, dy / L
        for i in range(1, int(min(L, 4000) // step) + 1):
            x, y = a[0] + ux * step * i, a[1] + uy * step * i
            if -10 <= x <= W + 10 and -10 <= y <= H + 10: pygame.draw.circle(s, color, (x, y), r)
            elif i > 3 and (x < -10 and ux < 0 or x > W + 10 and ux > 0 or y < -10 and uy < 0 or y > H + 10 and uy > 0): break

    def _edge_point(self, p):
        """Where the line from the map centre to p meets the usable edge (clear of card and buttons)."""
        cx, cy = W / 2, (H - CARD_H) / 2
        dx, dy = p[0] - cx, p[1] - cy
        if abs(dx) < 1 and abs(dy) < 1: return p
        tx = ((W - 110 - cx) if dx > 0 else (cx - 60)) / abs(dx) if dx else 9e9
        ty = ((H - CARD_H - 26 - cy) if dy > 0 else (cy - 26)) / abs(dy) if dy else 9e9
        t = min(tx, ty)
        return cx + dx * t, cy + dy * t

    def route_for(self, a):
        return names.plausible_route(a, self.app.routes.get(a.flight, (a.lat, a.lon), urgent=True))

    def _draw_route(self, s, a, placed):
        rt = self.route_for(a)
        px = self.to_px(*a.est_pos(time.time()))
        for ap, past in ((rt.origin if rt else None, True), (rt.dest if rt else None, False)):
            if not ap or ap.get("lat") is None: continue
            q = self.to_px(ap["lat"], ap["lon"])
            col = INK_SOFT if past else T.SIGNAL
            self._dotted(s, px, q, col, r=2 if past else 3)
            lab = names.place(ap)
            if 0 <= q[0] <= W and 0 <= q[1] <= H - CARD_H:
                pygame.draw.circle(s, PAPER, q, 10); pygame.draw.circle(s, col, q, 7)
                placed.append(halo_text(s, lab, 15, col if past else ROUTE, (q[0], q[1] + 12), "midtop"))
            # off-screen airports: the dotted line running off the edge is enough - the card names them

    def _draw_planes(self, s, sel, placed):
        now = time.time()
        trail = self._trail; trail.fill((0, 0, 0, 0))
        fb = T.font(14, True)
        items = []
        for a in self.app.fleet.positioned():
            x, y = self.to_px(*a.est_pos(now))
            if -30 <= x <= W + 30 and -30 <= y <= H + 30:
                items.append((math.hypot(x - W / 2, y - H / 2), a, x, y))
        items.sort(key=lambda t: t[0])
        if self.zoom > 400: return self._draw_planes_wide(s, sel, placed, items)
        for _, a, x, y in items[:40]: self.app.routes.get(a.flight, (a.lat, a.lon))      # warm the route cache, nearest first (labels only read it)
        scale = 1.15 if self.zoom <= 30 else 1.0 if self.zoom <= 110 else 0.8
        drawn = []
        for _, a, x, y in items:                                   # pass 1: trails and icons
            col = T.alt_color(a.alt, a.on_ground) if not a.on_ground else (150, 155, 160)
            is_sel = sel is not None and a.hex == sel.hex
            pts = [self.to_px(la, lo) for la, lo, _ in a.trail]
            if len(pts) > 1:
                for i in range(len(pts) - 1):
                    pygame.draw.line(trail, (*col, int(40 + 120 * i / len(pts))), pts[i], pts[i + 1], 2)
            sc = scale * (0.7 if a.on_ground else 1.0) * (1.25 if is_sel else 1.0)
            if is_sel: pygame.draw.circle(s, ORANGE, (x, y), int((20 + 5 * pulse()) * sc), 4)
            hdg = a.heading()
            if hdg is None:                                   # no idea which way: an honest dot
                pygame.draw.circle(s, col, (x, y), int(7 * sc)); pygame.draw.circle(s, INK, (x, y), int(7 * sc), 1)
            elif names.kind(a) == "Helicopter":
                self._draw_heli(s, x, y, hdg, sc, col)
            else:
                t = math.radians(hdg); ct, st = math.cos(t), math.sin(t)
                poly = [(x + (px * ct - py * st) * sc, y + (px * st + py * ct) * sc) for px, py in PLANE]
                pygame.draw.polygon(s, col, poly); pygame.draw.polygon(s, INK, poly, 1)
            r = int(12 * sc); placed.append(pygame.Rect(x - r, y - r, 2 * r, 2 * r))
            badge = "military" if a.military else "interesting" if a.interesting else None
            if self.app.logbook.has(a.hex):                          # top right is the special badge's corner, so the logged star steps aside
                draw_icon(s, "star", (x + (-11 if badge else 11) * sc, y - 11 * sc), ORANGE)
            if badge: draw_badge(s, badge, (round(x + 11 * sc), round(y - 11 * sc)), max(4, round(5.5 * sc)))   # half the plane icon's size
            drawn.append((a, x, y, sc, is_sel))
        s.blit(trail, (0, 0))
        for a, x, y, sc, is_sel in drawn:                          # pass 2: names, avoiding everything so far
            img = label_surf(names.label_for(a, self.app.routes.get(a.flight)), 14, INK if not is_sel else ROUTE)
            off = int(16 * sc)
            place(s, img, placed, [("midleft", (x + off, y)), ("midright", (x - off, y)), ("midtop", (x, y + off)), ("midbottom", (x, y - off))])

    _SPRITES: dict = {}

    def _sprite(self, hdg, alt, ground):
        """Small plane icon for wide views, pre-drawn per 15 deg of heading and 4000 ft band (blits, not polygons)."""
        tiny = self.zoom > 1500                                       # whole countries on screen: specks, not a carpet
        key = (int(hdg // 15) % 24 if hdg is not None else -1, -1 if ground else (alt or 0) // 4000, tiny)
        img = self._SPRITES.get(key)
        if img is None:
            col = (150, 155, 160) if ground else T.alt_color(key[1] * 4000 + 2000)
            img = pygame.Surface((18, 18), pygame.SRCALPHA)
            if key[0] < 0: pygame.draw.circle(img, col, (9, 9), 4); pygame.draw.circle(img, INK, (9, 9), 4, 1)
            else:
                t = math.radians(key[0] * 15 + 7.5); ct, st = math.cos(t), math.sin(t); sc = 0.38 if tiny else 0.62
                poly = [(9 + (px * ct - py * st) * sc, 9 + (px * st + py * ct) * sc) for px, py in PLANE]
                pygame.draw.polygon(img, col, poly)
                if not tiny: pygame.draw.polygon(img, INK, poly, 1)
            self._SPRITES[key] = img
        return img

    def _draw_planes_wide(self, s, sel, placed, items):
        """Zoomed right out there can be thousands: sprites only, no trails, names for the few nearest the middle."""
        for _, a, x, y in items:
            s.blit(self._sprite(a.heading(), a.alt, a.on_ground), (x - 9, y - 9))
            if self.zoom <= 1500 and (a.military or a.interesting):          # not on the specks of the whole-country views
                draw_badge(s, "military" if a.military else "interesting", (round(x + 7), round(y - 7)), 4)
        for _, a, x, y in items[:12]:
            r = pygame.Rect(x - 7, y - 7, 14, 14)
            if sel is not None and a.hex == sel.hex: pygame.draw.circle(s, ORANGE, (x, y), int(14 + 4 * pulse()), 3)
            img = label_surf(names.label_for(a, self.app.routes.get(a.flight)), 13, INK)
            placed.append(r); place(s, img, placed, [("midleft", (x + 11, y)), ("midright", (x - 11, y))])
        if sel is not None and not any(a.hex == sel.hex for _, a, _, _ in items[:12]):
            x, y = self.to_px(*sel.est_pos(time.time())); pygame.draw.circle(s, ORANGE, (x, y), int(14 + 4 * pulse()), 3)

    def _draw_heli(self, s, x, y, hdg, sc, col):
        """Top-down helicopter at the same footprint as a plane: cabin, short boom, rotor disc with blades."""
        t = math.radians(hdg); ct, st = math.cos(t), math.sin(t)
        R = lambda px, py: (x + (px * ct - py * st) * sc, y + (px * st + py * ct) * sc)
        boom = [(-1.2, 3), (1.2, 3), (0.8, 10), (-0.8, 10)]
        pygame.draw.polygon(s, col, [R(*p) for p in boom]); pygame.draw.polygon(s, INK, [R(*p) for p in boom], 1)
        pygame.draw.line(s, INK, R(-3, 9.5), R(3, 9.5), max(1, int(1.5 * sc)))                # tail rotor
        cabin = [(0, -7), (3.5, -4), (4, 1), (2.5, 4), (-2.5, 4), (-4, 1), (-3.5, -4)]
        pygame.draw.polygon(s, col, [R(*p) for p in cabin]); pygame.draw.polygon(s, INK, [R(*p) for p in cabin], 1)
        disc = pygame.Surface((int(20 * sc) + 2, int(20 * sc) + 2), pygame.SRCALPHA)            # rotor disc, faint
        pygame.draw.circle(disc, (*INK, 70), (disc.get_width() // 2, disc.get_height() // 2), int(8 * sc), 1)
        s.blit(disc, (x - disc.get_width() // 2, y - 1 - disc.get_height() // 2))
        for a0 in (30, 150):                                                                  # two short blades
            a1 = math.radians(a0); dx, dy = 7.5 * math.cos(a1), 7.5 * math.sin(a1)
            pygame.draw.line(s, INK, R(-dx, -dy - 1), R(dx, dy - 1), max(1, int(1.5 * sc)))
        pygame.draw.circle(s, INK, R(0, -1), max(1, int(1.8 * sc)))

    def _draw_map_labels(self, s, placed):
        """Airport and town names, placed after the planes so nothing important is covered."""
        airports, places, countries = self._labels
        for k in countries:                                                          # big and soft, under everything else
            x, y = self.to_px(k["lat"], k["lon"])
            if not (-100 <= x <= W + 100 and -20 <= y <= H + 20): continue
            img = label_surf(k["name"].upper(), 15, COUNTRY, True)
            lr = img.get_rect(center=(x, y))
            if not any(lr.colliderect(p) for p in placed): placed.append(lr); s.blit(img, lr)
        for a in airports:
            x, y = self.to_px(a["lat"], a["lon"])
            if not (-100 <= x <= W + 20 and -20 <= y <= H + 20): continue
            r = 7 if a["rank"] == 3 else 5
            label = (a["city"] or a["name"]) + (" Airport" if a["rank"] == 3 else "")
            img = label_surf(label, 14 if a["rank"] == 3 else 12, AIRPORT, a["rank"] == 3)
            lr = img.get_rect(midleft=(x + r + 5, y))
            if lr.right < 0 or lr.top > H - (CARD_H if self.selected else 0): continue
            if not any(lr.colliderect(p) for p in placed):
                placed.append(lr); s.blit(img, lr)
        for p in places:
            x, y = self.to_px(p["lat"], p["lon"])
            if not (-100 <= x <= W + 20 and -20 <= y <= H + 20): continue
            big = p["pop"] > 200000
            img = label_surf(p["name"], 13 if big else 12, TOWN, big)
            lr = img.get_rect(midleft=(x + 6, y))
            if lr.right < 0 or lr.top > H - (CARD_H if self.selected else 0): continue
            if not any(lr.colliderect(q) for q in placed):
                placed.append(lr); s.blit(img, lr)

    def _draw_mode(self, s):
        """Where the planes are coming from. Quiet when all is well, loud when it isn't."""
        mode = self.app.mode
        if mode == "wifi": label, icon, fill, col = "Wi-Fi", "wifi", PAPER, GREEN
        else: label, icon, fill, col = "No signal", "wifi", RED, PAPER        # the banner does the friendly bit
        f = T.font(15, weight="extrabold"); w = f.size(label)[0] + 52
        r = pygame.Rect(92, 26, w, 40)
        pygame.draw.rect(s, fill, r, border_radius=20); pygame.draw.rect(s, OUTLINE if fill == PAPER else fill, r, 2, border_radius=20)
        draw_icon(s, icon, (r.x + 22, r.centery), col if fill == PAPER else PAPER)
        s.blit(f.render(label, True, col if fill == PAPER else PAPER), (r.x + 40, r.centery - f.get_height() // 2))
        b = self.app.battery
        if b.present and b.percent is not None:
            pw = T.font(14, weight="extrabold").size(f"{b.percent}%")[0]
            br = pygame.Rect(r.right + 10, 26, 50 + pw + (16 if b.charging else 0) + 14, 40)     # icon + text + bolt, never clipped
            pygame.draw.rect(s, PAPER, br, border_radius=20); pygame.draw.rect(s, OUTLINE, br, 2, border_radius=20)
            bx, by = br.x + 14, br.centery
            pygame.draw.rect(s, INK, (bx, by - 7, 24, 14), 2, border_radius=3); pygame.draw.rect(s, INK, (bx + 25, by - 3, 3, 6))
            fillc = GREEN if b.percent > 30 else ORANGE if b.percent > 12 else RED
            pygame.draw.rect(s, fillc, (bx + 3, by - 4, int(18 * b.percent / 100), 8), border_radius=1)
            tr = text(s, f"{b.percent}%", 14, INK, (bx + 36, by), "midleft", weight="extrabold")
            if b.charging:                                                                    # a little bolt
                x0 = tr.right + 5
                pygame.draw.polygon(s, ORANGE, [(x0 + 4, by - 8), (x0, by + 1), (x0 + 4, by + 1), (x0 + 2, by + 8), (x0 + 8, by - 2), (x0 + 4, by - 2)])

    def _draw_card(self, s, a):
        r = self.card_rect
        pygame.draw.rect(s, PAPER, r)
        pygame.draw.rect(s, OUTLINE, (0, r.y, W, 3))
        ph = self.app.photos.get(a.hex)
        pr = pygame.Rect(14, r.y + 16, 200, 128)
        pygame.draw.rect(s, CHIP, pr.inflate(8, 8), border_radius=14)
        if ph: s.blit(vscale(ph, pr.w, pr.h), pr)
        else:
            s.blit(plane_art(pr.w, pr.h, names.kind(a), names.kind(a) == "Helicopter"), pr)
        rt = self.route_for(a)
        x0, maxw = pr.right + 22, W - pr.right - 22 - 194
        ident = a.reg or a.hex.upper()
        text(s, fit_text(names.label_for(a, rt), 28, maxw, weight="extrabold"), 28, INK, (x0, r.y + 8), "topleft", weight="extrabold")
        kind = names.plane_type(a.type, a.desc) if a.type else names.kind(a)
        text(s, fit_text(f"{kind} ({ident})", 16, maxw, weight="bold"), 16, INK_SOFT, (x0, r.y + 44), "topleft", weight="bold")
        has_route = bool(rt and (rt.origin or rt.dest))
        if has_route: route_line(s, names.place(rt.origin), names.place(rt.dest), 21, ROUTE, (x0, r.y + 66), maxw)
        chips = []
        if a.on_ground: chips.append(("on the ground", "level"))
        else:
            if a.alt is not None:
                chips.append((f"{a.alt:,} ft", "up" if (a.vr or 0) > 300 else "down" if (a.vr or 0) < -300 else "level"))
            if a.gs: chips.append((f"{a.gs * 1.151:.0f} mph", "speed"))
        def row_w(sz, cs):
            f = T.font(sz, weight="bold")
            return sum(f.size(t)[0] + 24 + (22 if ic else 0) for t, ic in cs) + 10 * (len(cs) - 1)
        if not a.on_ground:
            _, eta = names.flight_times_short(a, rt)          # "lands in 25 min" / "landing now!"
            if eta:
                short = eta.replace("lands in ", "").replace("landing now!", "landing!")
                chips.append((eta if row_w(17, chips + [(eta, "clock")]) <= maxw else short, "clock"))
        size = 17
        while size > 13 and row_w(size, chips) > maxw: size -= 1
        x, y = x0, r.y + 104 + (17 - size) // 2
        for t, ic in chips: x = chip(s, (x, y), t, ic, size).right + 10
        self.b_follow.draw(s, fill=GREEN if self.follow else ORANGE, label="FOLLOWING" if self.follow else "FOLLOW")
        st = self.app.logbook.state(a)
        if st == "new":    self.b_log.icon = "plus"; self.b_log.draw(s, fill=PAPER, color=INK, label="LOG")
        elif st == "again": self.b_log.icon = "star"; self.b_log.draw(s, fill=PAPER, color=INK, label="SEEN AGAIN")
        elif st == "full":  self.b_log.icon = None; self.b_log.draw(s, fill=(236, 238, 240), color=(160, 168, 176), label="BOOK FULL")
        else:               self.b_log.icon = "tick"; self.b_log.draw(s, fill=GREEN, color=PAPER, label="LOGGED")
        self.b_close.draw(s)
