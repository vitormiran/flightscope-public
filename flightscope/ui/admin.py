"""Setup: the grown-ups' screen, reached by holding Home for three seconds.
Status · Wi-Fi · Settings · Power. Plain rows, big targets, nothing destructive without a second tap."""
from __future__ import annotations
import time, pygame
from . import theme as T
from .widgets import text, fit_text
from .kid import Pill, draw_icon, PAPER, INK, INK_SOFT, CHIP, OUTLINE, ORANGE, GREEN, RED, SHADOW
from .keyboard import KeyboardScreen
from .. import config as C
from .. import system as S

W, H = 800, 480
TOP, ROW = 76, 56
TABS = ["Status", "Wi-Fi", "Settings", "Power"]

def hms(sec: float) -> str:
    sec = int(sec); d, r = divmod(sec, 86400); h, r = divmod(r, 3600); m = r // 60
    return (f"{d}d {h}h" if d else f"{h}h {m:02d}m" if h else f"{m} min")

def bars(s, pos, signal, col=INK):
    x, y = pos
    for i in range(4):
        on = signal >= (i + 1) * 22
        pygame.draw.rect(s, col if on else OUTLINE, (x + i * 7, y + 12 - 4 * i, 5, 4 + 4 * i), border_radius=1)

class AdminScreen:
    def __init__(self, app):
        self.app = app; self.cfg = app.cfg; self.tab = 0
        self.back = Pill((14, 14, 130, 50), "Map", size=19, icon="back")
        self.tabs = [Pill((166 + i * 154, 14, 146, 50), t, size=17) for i, t in enumerate(TABS)]
        self.scroll = 0.0; self._down = None; self._moved = 0; self._last = 0; self.content_h = 0
        self.hits: list[tuple[pygame.Rect, object]] = []
        self.status = {}; self._status_job = None; self._status_at = 0.0
        self.networks: list[dict] = []; self.saved: dict[str, str] = {}; self.scan_job = None; self.net_job = None; self.net_label = ""
        self.msg = ("", 0.0)
        self.confirm = None                                             # (label, fn, expiry)
        self.toast("", 0)

    # ---------- plumbing ----------
    def toast(self, m, ttl=6.0): self.msg = (m, time.time() + ttl)

    def handle(self, e):
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE): return self.app.pop()
        if e.type == pygame.MOUSEBUTTONDOWN:
            self._down = e.pos; self._last = e.pos[1]; self._moved = 0
            self.back.pressed = self.back.hit(e.pos)
            for b in self.tabs: b.pressed = b.hit(e.pos)
        elif e.type == pygame.MOUSEMOTION and self._down is not None:
            dy = e.pos[1] - self._last; self._last = e.pos[1]; self._moved += abs(dy)
            if e.pos[1] > TOP: self.scroll = max(0, min(max(0, self.content_h - (H - TOP)), self.scroll - dy))
        elif e.type == pygame.MOUSEBUTTONUP and self._down is not None:
            self.back.pressed = False
            for b in self.tabs: b.pressed = False
            p = e.pos; self._down = None
            if self._moved >= 12: return
            if self.back.hit(p): return self.app.pop()
            for i, b in enumerate(self.tabs):
                if b.hit(p): self.tab = i; self.scroll = 0; self.confirm = None; return
            for r, fn in self.hits:
                if r.collidepoint(p): fn(); return

    def update(self, dt):
        now = time.time()
        if self._status_job and self._status_job.done:
            self.status = self._status_job.result or self.status; self._status_job = None
        if self._status_job is None and now - self._status_at > (4 if self.tab == 0 else 20):
            self._status_at = now; self._status_job = S.Job(S.status_snapshot)
        if self.scan_job and self.scan_job.done:
            self.networks = self.scan_job.result or []; self.saved = S.saved_wifi() if self.scan_job.result is not None else self.saved
            if self.scan_job.error: self.toast("Scan failed: " + self.scan_job.error)
            self.scan_job = None
        if self.net_job and self.net_job.done:
            ok, m = self.net_job.result or (False, self.net_job.error or "?")
            self.toast(m, 8); self.net_job = None; self._status_at = 0; self.scan_job = S.Job(S.wifi_scan, False)
        if self.confirm and now > self.confirm[2]: self.confirm = None
        if self.tab == 1 and not self.networks and self.scan_job is None and not getattr(self, "_scanned", False):
            self._scanned = True; self.scan_job = S.Job(S.wifi_scan, True)

    # ---------- shared drawing ----------
    def _button(self, s, rect, label, fn, fill=PAPER, color=INK, size=16, icon=None):
        r = pygame.Rect(rect)
        pygame.draw.rect(s, SHADOW, r.move(0, 3), border_radius=r.h // 2)
        pygame.draw.rect(s, fill, r, border_radius=r.h // 2); pygame.draw.rect(s, OUTLINE if fill == PAPER else fill, r, 2, border_radius=r.h // 2)
        if icon: draw_icon(s, icon, r.center, color)
        else: text(s, label, size, color, r.center, "center", weight="extrabold")
        self.hits.append((r.inflate(6, 6), fn))
        return r

    def _row(self, s, y, label, value, actions=(), value_col=INK, sub=None):
        """One settings row: label, value, and up to two round-ish buttons on the right."""
        r = pygame.Rect(0, y, W, ROW)
        pygame.draw.line(s, CHIP, (24, r.bottom - 1), (W - 24, r.bottom - 1), 2)
        text(s, label, 16, INK_SOFT, (30, r.centery - (8 if sub else 0)), "midleft", weight="bold")
        if sub: text(s, sub, 13, INK_SOFT, (30, r.centery + 12), "midleft", weight="bold")
        x = W - 30
        for lab, fn, fill, col, w in reversed(actions):
            self._button(s, (x - w, r.y + 8, w, ROW - 16), lab, fn, fill, col, 18 if len(lab) == 1 else 15)
            x -= w + 10
        vw = x - 16 - 250
        text(s, fit_text(str(value), 18, vw, weight="extrabold"), 18, value_col, (250, r.centery), "midleft", weight="extrabold")
        return r.bottom

    def _stepper(self, attr, lo, hi, step, after=None, fmt=None):
        def make(d):
            def fn():
                v = getattr(self.cfg, attr); v = type(v)(max(lo, min(hi, v + d)))
                setattr(self.cfg, attr, v); C.save(self.cfg)
                if after: after()
            return fn
        return [("–", make(-step), PAPER, INK, 56), ("+", make(step), PAPER, INK, 56)]

    def _edit(self, attr, title, secret=False, hint=""):
        def fn():
            def done(v):
                setattr(self.cfg, attr, v.strip()); C.save(self.cfg); self.toast("Saved")
            self.app.push(KeyboardScreen(self.app, title, getattr(self.cfg, attr) or "", done, secret, hint))
        return fn

    def _confirm_btn(self, s, rect, label, fn, fill):
        """Two-step: first tap arms for 4 s, second tap does it."""
        armed = self.confirm and self.confirm[0] == label
        def tap():
            if self.confirm and self.confirm[0] == label: self.confirm = None; fn()
            else: self.confirm = (label, fn, time.time() + 4)
        self._button(s, rect, "Tap again to confirm" if armed else label, tap, RED if armed else fill, PAPER, 16)

    # ---------- tabs ----------
    def _draw_status(self, s, y):
        st = self.status; app = self.app; b = app.battery; net = app.net
        feed = "OK" if net.ok else (net.error or "no data yet")
        age = f"{time.time() - net.stamp:.0f} s ago" if net.stamp else ""
        rows = [("Name", st.get("host", "…"), None),
                ("Wi-Fi", (st.get("ssid") or "not connected") + (f"  ·  {st.get('signal', 0)}%" if st.get("ssid") else ""), None),
                ("IP address", st.get("ip") or "—", None),
                ("Plane feed", f"{feed}" + (f"  ·  {age}" if net.ok else ""), GREEN if net.ok else RED),
                ("Planes on map", str(len(app.fleet.positioned())), None),
                ("GPS", app.gps.status(), GREEN if app.gps.fix else None),
                ("GPS signal", app.gps.signal_text(), None),
                ("Battery", (f"{b.percent}%  ·  {b.volts:.2f} V  ·  {b.state}" + (f"  ·  {b.eta_text()}" if b.eta_text() else "")) if b.cells else ("HAT found, no cells" if b.present else "no UPS HAT"), None),
                ("CPU", f"{st['temp']:.0f} °C" if st.get("temp") else "—", None),
                ("Up for", hms(st.get("uptime", 0)), None),
                ("Logbook", f"{len(app.logbook.by_hex)} planes", None),
                ("Software", f"{self.cfg.app_name} {self.cfg.app_version}", None)]
        for label, value, col, *acts in rows: y = self._row(s, y, label, value, acts[0] if acts else (), value_col=col or INK)
        return y

    def _draw_wifi(self, s, y):
        cur = next((n for n in self.networks if n["active"]), None)
        ssid = self.status.get("ssid"); ip = self.status.get("ip")
        acts = [("Forget", lambda: self._forget(ssid), PAPER, INK_SOFT, 100)] if ssid and ssid in self.saved else []
        y = self._row(s, y, "Connected to", (ssid or "nothing") + (f"  ·  {ip}" if ip else ""), acts, GREEN if ssid else RED)
        scanning = self.scan_job is not None
        label = "Scanning…" if scanning else "Scan again"
        r = pygame.Rect(30, y + 8, W - 60, ROW - 16)
        self._button(s, r, label, (lambda: None) if scanning else self._rescan, CHIP if scanning else PAPER, INK_SOFT if scanning else INK, 16)
        y += ROW
        if self.net_job: text(s, self.net_label, 16, ORANGE, (W / 2, y + 26), "center", weight="extrabold"); y += ROW
        for n in self.networks:
            rr = pygame.Rect(0, y, W, ROW)
            pygame.draw.line(s, CHIP, (24, rr.bottom - 1), (W - 24, rr.bottom - 1), 2)
            bars(s, (30, rr.centery - 8), n["signal"], GREEN if n["active"] else INK)
            text(s, fit_text(n["ssid"], 18, 420, weight="extrabold"), 18, INK, (72, rr.centery), "midleft", weight="extrabold")
            x = 72 + T.font(18, weight="extrabold").size(fit_text(n["ssid"], 18, 420, weight="extrabold"))[0] + 12
            if n["active"]: x = text(s, "connected", 13, GREEN, (x, rr.centery), "midleft", weight="bold").right + 10
            elif n["ssid"] in self.saved: x = text(s, "saved", 13, INK_SOFT, (x, rr.centery), "midleft", weight="bold").right + 10
            if n["secure"]:                                                               # padlock
                pygame.draw.rect(s, INK_SOFT, (x + 2, rr.centery - 1, 12, 9), border_radius=2)
                pygame.draw.arc(s, INK_SOFT, pygame.Rect(x + 3, rr.centery - 9, 10, 12), 0, 3.15, 2)
            if not n["active"]:
                self._button(s, (W - 150, rr.y + 8, 120, ROW - 16), "Join", lambda n=n: self._join(n), ORANGE, PAPER, 16)
            y = rr.bottom
        if not self.networks and not scanning:
            text(s, "No networks found", 18, INK_SOFT, (W / 2, y + 30), "center", weight="bold"); y += ROW
        return y

    def _rescan(self):
        if self.scan_job is None: self.scan_job = S.Job(S.wifi_scan, True)

    def _join(self, n):
        ssid = n["ssid"]
        if ssid in self.saved or not n["secure"]:
            self._connect(ssid, None); return
        def done(pw):
            if pw: self._connect(ssid, pw)
        self.app.push(KeyboardScreen(self.app, f"Password for {ssid}", "", done, secret=True, hint="Wi-Fi password"))

    def _connect(self, ssid, pw):
        if self.net_job: return
        self.net_label = f"Joining {ssid}…"; self.net_job = S.Job(S.wifi_connect, ssid, pw)

    def _forget(self, ssid):
        if self.net_job or not ssid: return
        self.net_label = f"Forgetting {ssid}…"; self.net_job = S.Job(S.wifi_forget, ssid)

    def _draw_settings(self, s, y):
        cfg = self.cfg; app = self.app
        def set_home():
            c = app.map.center; cfg.home_lat, cfg.home_lon = round(c[0], 4), round(c[1], 4); C.save(cfg)
            app.fleet.set_home(cfg.home_lat, cfg.home_lon); self.toast("Home moved to the middle of the map")
        y = self._row(s, y, "Name", cfg.owner or "(none)", [("Edit", self._edit("owner", "Whose planes?", hint="Name"), PAPER, INK, 90)])
        def set_home_gps():
            h = app.gps.here()
            if not h: return self.toast("No GPS fix yet")
            cfg.home_lat, cfg.home_lon = round(h[0], 4), round(h[1], 4); C.save(cfg); app.fleet.set_home(cfg.home_lat, cfg.home_lon); self.toast("Home set from GPS")
        home_acts = [("Use map centre", set_home, PAPER, INK, 170)]
        if app.gps.fix: home_acts.insert(0, ("Use GPS", set_home_gps, GREEN, PAPER, 110))
        y = self._row(s, y, "Home", f"{cfg.home_lat:.4f}, {cfg.home_lon:.4f}", home_acts, sub="pan the map first, then tap")
        y = self._row(s, y, "Map at start", f"{cfg.start_zoom_nm:.0f} miles across", self._stepper("start_zoom_nm", 8.0, 200.0, 4.0))
        y = self._row(s, y, "Brightness", f"{int(cfg.brightness / 255 * 100)}%", self._stepper("brightness", 30, 255, 25, after=lambda: app.backlight and app.backlight.apply()))
        y = self._row(s, y, "Dim after", f"{cfg.dim_after_s:.0f} s" if cfg.dim_after_s > 0 else "never", self._stepper("dim_after_s", 0.0, 600.0, 10.0))
        y = self._row(s, y, "Screen off after", f"{cfg.off_after_s:.0f} s" if cfg.off_after_s > 0 else "never", self._stepper("off_after_s", 0.0, 1800.0, 30.0))
        y = self._row(s, y, "Dimmed level", f"{int(cfg.dim_level / 255 * 100)}%", self._stepper("dim_level", 10, 200, 10))
        y = self._row(s, y, "Plane feed radius", f"{cfg.net_radius_nm} miles", self._stepper("net_radius_nm", 50, 250, 25))
        y = self._row(s, y, "Photo contact", cfg.photo_contact or "(off)", [("Edit", self._edit("photo_contact", "Contact for plane photos", hint="mailto:you@example.com"), PAPER, INK, 90)])
        y = self._row(s, y, "Battery size", f"{cfg.battery_mah} mAh", self._stepper("battery_mah", 2000, 20000, 500))
        return y

    def _draw_power(self, s, y):
        b = self.app.battery
        box = pygame.Rect(30, y + 10, W - 60, 150)
        pygame.draw.rect(s, CHIP, box, border_radius=18)
        if b.cells and b.percent is not None:
            pct = b.percent; col = GREEN if pct > 30 else ORANGE if pct > 12 else RED
            text(s, f"{pct}%", 64, col, (box.x + 30, box.centery), "midleft", weight="black")
            bx = box.x + 200; by = box.y + 22
            pygame.draw.rect(s, INK, (bx, by, 120, 40), 3, border_radius=8); pygame.draw.rect(s, INK, (bx + 121, by + 12, 8, 16), border_radius=2)
            pygame.draw.rect(s, col, (bx + 6, by + 6, int(108 * pct / 100), 28), border_radius=4)
            state = {"charging": "Charging", "full": "Full, on the charger", "discharging": "On battery"}.get(b.state, b.state)
            text(s, state, 22, INK, (bx + 145, by + 20), "midleft", weight="extrabold")
            line2 = f"{b.volts:.2f} V   ·   {abs(b.amps) * 1000:.0f} mA {'in' if b.amps > 0 else 'out'}   ·   {b.watts:.1f} W"
            text(s, line2, 17, INK_SOFT, (bx, by + 66), "topleft", weight="bold")
            eta = b.eta_text()
            if eta: text(s, eta.capitalize(), 20, INK, (bx, by + 94), "topleft", weight="extrabold")
        elif b.present:
            text(s, "UPS HAT found, but no battery on it", 22, INK, box.center, "center", weight="extrabold")
        else:
            text(s, "No UPS HAT — running from the mains", 22, INK, box.center, "center", weight="extrabold")
        y = box.bottom + 24
        self._button(s, (30, y, 230, 54), "Restart app", S.restart_app, PAPER, INK, 17)
        self._confirm_btn(s, (285, y, 230, 54), "Reboot", S.reboot, ORANGE)
        self._confirm_btn(s, (540, y, 230, 54), "Shut down", S.poweroff, RED)
        y += 74
        text(s, "Shut down before charging overnight, or it'll happily run all night.", 14, INK_SOFT, (W / 2, y + 10), "center", weight="bold")
        return y + 30

    # ---------- draw ----------
    def draw(self, s):
        s.fill(PAPER); self.hits = []
        s.set_clip(pygame.Rect(0, TOP, W, H - TOP))
        y0 = TOP - int(self.scroll)
        y = [self._draw_status, self._draw_wifi, self._draw_settings, self._draw_power][self.tab](s, y0)
        self.content_h = y - y0 + 12
        for i, (r, fn) in enumerate(self.hits):                     # hits below the header don't count when scrolled under it
            if r.bottom < TOP: self.hits[i] = (pygame.Rect(0, 0, 0, 0), fn)
        s.set_clip(None)
        pygame.draw.rect(s, PAPER, (0, 0, W, TOP)); pygame.draw.line(s, OUTLINE, (0, TOP - 2), (W, TOP - 2), 2)
        self.back.draw(s)
        for i, b in enumerate(self.tabs):
            b.draw(s, fill=ORANGE if i == self.tab else PAPER, color=PAPER if i == self.tab else INK)
        m, until = self.msg
        if m and time.time() < until:
            f = T.font(16, weight="extrabold"); w = f.size(m)[0] + 40
            r = pygame.Rect(0, 0, w, 44); r.midbottom = (W / 2, H - 12)
            pygame.draw.rect(s, INK, r, border_radius=22); s.blit(f.render(m, True, PAPER), f.render(m, True, PAPER).get_rect(center=r.center))
