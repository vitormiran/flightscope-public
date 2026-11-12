"""Event loop, screen stack, data plumbing."""
from __future__ import annotations
import os, subprocess, sys, time
from pathlib import Path
import pygame
from . import config as C, safefile
from .model import Fleet
from .sources.network import NetworkSource
from .sources.readsb import ReadsbSource
from .sources.gps import GpsSource
from .photos import PhotoCache
from .cities import CityImages
from . import display as D
from .touch import Touch
from .routes import RouteCache
from . import offline
from .offlinedb import OfflineDB
from .logbook import Logbook
from .power import Backlight, DongleSleeper, Battery
from .ui.splash import SplashScreen
from .ui.charging import ChargingScreen
from .ui.mapview import MapScreen
from .ui.card import CardScreen

class App:
    def __init__(self, cfg: C.Config):
        self.cfg = cfg
        self.restore_clock()                # before anything talks HTTPS
        D.select_driver(cfg)          # must precede pygame.init(): SDL picks its video driver then
        pygame.init()
        self.display = D.make(cfg)
        self.screen = self.display.surface
        self.touch = Touch() if isinstance(self.display, D.FbDisplay) else None
        self.clock = pygame.time.Clock()
        self.fleet = Fleet(cfg.home_lat, cfg.home_lon)
        self.net = NetworkSource(cfg); self.net.start()
        self.local = ReadsbSource(cfg)
        self.gps = GpsSource(cfg)
        self.photos = PhotoCache(cfg)
        self.cities = CityImages(cfg)
        self.offdb = OfflineDB(cfg)
        self.routes = RouteCache(cfg); self.routes.db = self.offdb
        self.logbook = Logbook(cfg)
        self.backlight = Backlight(cfg) if not cfg.windowed else None
        self.sleeper = DongleSleeper(self) if self.local.present or not cfg.windowed else None
        self.battery = Battery(cfg)
        self._swallow = False
        self.map = MapScreen(self)
        self.net.points = self.map.feed_points               # the feed looks wherever the map is looking
        self.stack = [SplashScreen(self)]
        self.save_boot_frame()
        self._net_stamp = 0.0; self._shot_check = 0.0; self._clock_saved = 0.0
        self.last_input = time.time()
        self.running = True

    CLOCK_FILE = Path("/data/cache/clock")

    def restore_clock(self):
        """The root is read-only, so every boot starts at the same old time until NTP answers (~30 s): HTTPS then
        fails ('certificate not yet valid') and catches get the wrong date. Start from the last time we saved instead."""
        try: t = float(self.CLOCK_FILE.read_text())
        except (OSError, ValueError): return
        ahead = t - time.time()
        if ahead > 60 and not os.path.exists("/run/systemd/timesync/synchronized"):
            r = subprocess.run(["sudo", "-n", "date", "-u", "-s", f"@{int(t)}"], capture_output=True, text=True)
            print(f"clock: wound forward {ahead / 86400:.1f} days from the saved time ({'ok' if r.returncode == 0 else r.stderr.strip()[:60]})", flush=True)

    def _save_clock(self):
        now = time.time()
        if now - self._clock_saved < 300 or not self.CLOCK_FILE.parent.is_dir(): return
        self._clock_saved = now
        try: safefile.write_text(self.CLOCK_FILE, f"{int(now)}\n")
        except OSError as e: print(f"clock: {e}", flush=True)

    BOOT_FRAME = Path("/data/cache/bootsplash.fb")       # shown by flightscope-bootsplash.service early in boot

    def save_boot_frame(self):
        """The splash's first frame in the framebuffer's format, rewritten only when it changes (title, panel)."""
        if not isinstance(self.display, D.FbDisplay) or not self.BOOT_FRAME.parent.is_dir(): return
        try:
            surf = pygame.Surface((self.display.w, self.display.h)); self.stack[0].draw(surf, up=0.0)
            raw = self.display.raw(surf)
            if not self.BOOT_FRAME.exists() or self.BOOT_FRAME.read_bytes() != raw:
                tmp = self.BOOT_FRAME.with_suffix(".tmp"); tmp.write_bytes(raw)
                safefile.copy_file(tmp, self.BOOT_FRAME); tmp.unlink()
                print(f"boot frame saved -> {self.BOOT_FRAME}", flush=True)
        except Exception as e: print(f"boot frame: {e}", flush=True)

    CHARGE_SCREEN_AFTER_S = 60.0

    def _charging_check(self):
        """Plugged in and left alone for a minute: the charging screen (not over Setup, where a grown-up is busy)."""
        top = self.stack[-1]
        if isinstance(top, (ChargingScreen, SplashScreen)) or type(top).__name__ == "AdminScreen": return
        if self.battery.charging and time.time() - self.last_input > self.CHARGE_SCREEN_AFTER_S:
            self.push(ChargingScreen(self)); print("charging screen", flush=True)

    # screen stack
    def push(self, scr): self.stack.append(scr)
    def pop(self):
        if len(self.stack) > 1: self.stack.pop()
    def replace(self, scr): self.stack[-1] = scr
    def make_main(self): return self.map
    def make_card(self, hex): return CardScreen(self, hex)
    def make_logbook(self):
        from .ui.logbook import LogbookScreen
        return LogbookScreen(self)
    def make_admin(self):
        from .ui.admin import AdminScreen
        return AdminScreen(self)

    def _ingest(self):
        if self.net.stamp != self._net_stamp:
            self.fleet.update(self.net.snapshot(), "net"); self._net_stamp = self.net.stamp
        if not self.net.ok and self.local.present:      # the antenna is a fallback, never a second source
            rows = self.local.snapshot()
            if rows: self.fleet.update(self.offdb.enrich(rows), "local")

    def antenna_only(self, on: bool):
        """Test the antenna: the app acts as if the internet has gone (see offline.py) and drops the feed's planes now
        rather than when they go stale, so the map shows only what readsb hears."""
        offline.on = on
        if on:
            with self.net.lock: self.net.latest, self.net.stamp = [], 0.0
            for h in [h for h, a in self.fleet.by_hex.items() if "local" not in a.sources]: del self.fleet.by_hex[h]
        else:
            self.routes._failed.clear(); self.photos._failed.clear()     # lookups refused during the test: ask again now
        print(f"feed: {'antenna only (simulated offline)' if on else 'back on the feed'}", flush=True)

    @property
    def mode(self) -> str:
        """'wifi' = internet feed is fresh (happy path); 'antenna' = only our own receiver is alive;
        'none' = neither. The antenna is always merged in when it hears something."""
        if self.net.ok: return "wifi"
        if self.local.present and self.local.ok: return "antenna"
        return "none"

    def _screenshot_check(self):
        now = time.time()
        if now - self._shot_check < 1.0: return
        self._shot_check = now
        trig = Path(self.cfg.screenshot_trigger)
        if trig.exists():
            out = trig.with_suffix(".png")
            pygame.image.save(self.screen, str(out)); trig.unlink()
            print(f"screenshot -> {out} ({type(self.stack[-1]).__name__}, depth {len(self.stack)})", flush=True)
        tap = trig.with_suffix(".tap")            # dev aid: echo "x y" > /tmp/flightscope.tap simulates a touch
        if tap.exists():
            try:
                x, y = map(int, tap.read_text().split()[:2])
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=(x, y), button=1))
                pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=(x, y), button=1))
            except ValueError: pass
            tap.unlink()
        pin = trig.with_suffix(".pinch")          # dev aid: echo "scale x y" > /tmp/flightscope.pinch
        if pin.exists():
            from .touch import PINCH
            try:
                sc, x, y = pin.read_text().split()[:3]; sc, x, y = float(sc), int(x), int(y)
                for ph, k in (("start", 1.0), ("move", sc), ("end", 1.0)):
                    pygame.event.post(pygame.event.Event(PINCH, phase=ph, scale=k, center=(x, y)))
            except ValueError: pass
            pin.unlink()
        adm = trig.with_suffix(".admin")          # dev aid: echo "" > /tmp/flightscope.admin opens the setup screen (or "1" = Wi-Fi tab, etc.)
        if adm.exists():
            from .ui.admin import AdminScreen
            scr = AdminScreen(self)
            try: scr.tab = int(adm.read_text().strip() or 0)
            except ValueError: pass
            self.push(scr); adm.unlink()
        key = trig.with_suffix(".key")            # dev aid: echo "text" > /tmp/flightscope.key types into an open keyboard
        if key.exists():
            txt = key.read_text().rstrip("\n"); key.unlink()
            for ch in txt: pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=ord(ch) if len(ch) == 1 and ord(ch) < 256 else 0, unicode=ch, mod=0))
        sel = trig.with_suffix(".sel")            # dev aid: touch /tmp/flightscope.sel selects the plane nearest the centre with a known route
        if sel.exists() and hasattr(self.stack[-1], "selected"):
            import math
            scr = self.stack[-1]; best, bd = None, 9e9
            want = sel.read_text().strip().lower()
            if want in self.fleet.by_hex: best, bd = want, 0
            for a in self.fleet.positioned():
                x, y = scr.to_px(*a.est_pos(time.time()))
                if not (0 <= x <= 800 and 0 <= y <= 360): continue
                rt = self.routes.get(a.flight, (a.lat, a.lon))
                d = math.hypot(x - 400, y - 200) + (0 if rt and rt.dest else 5000) + (2000 if a.on_ground else 0)
                if d < bd: best, bd = a.hex, d
            if best: scr.selected = best
            sel.unlink()

    IDLE_AFTER_S, IDLE_FPS = 30.0, 10      # nobody touching: planes still glide, at half the frames (and CPU)

    def _fps(self):
        top = self.stack[-1]
        busy = time.time() - self.last_input < self.IDLE_AFTER_S or getattr(top, "_anim", None) or getattr(top, "_party", None)
        return self.cfg.fps if busy else min(self.cfg.fps, self.IDLE_FPS)

    def run(self):
        while self.running:
            dt = self.clock.tick(self._fps()) / 1000.0
            for e in pygame.event.get():
                if e.type == pygame.QUIT: self.running = False
                elif e.type == pygame.KEYDOWN and e.key == pygame.K_q: self.running = False
                else:
                    if e.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEMOTION, pygame.MOUSEBUTTONUP) or e.type == pygame.USEREVENT + 1:
                        self.last_input = time.time()
                        if self.backlight and e.type == pygame.MOUSEBUTTONDOWN and self.backlight.touched():
                            self._swallow = True                       # this tap only woke the screen
                        elif self.backlight: self.backlight.last_touch = time.time()
                        if self._swallow:
                            if e.type == pygame.MOUSEBUTTONUP: self._swallow = False
                            continue
                    self.stack[-1].handle(e)
            if self.backlight:
                self._charging_check()
                top = self.stack[-1]
                self.backlight.allow_off = bool(self.touch and self.touch.ok) and not (isinstance(top, ChargingScreen) and top.keep_lit)
                self.backlight.tick()
            if self.sleeper and int(time.time()) % 2 == 0: self.sleeper.tick()
            self._ingest()
            self.stack[-1].update(dt)
            self.stack[-1].draw(self.screen)
            self.display.flip()
            self._screenshot_check()
            self._save_clock()
            if int(time.time()) % 10 == 0: self.offdb.tick()
        self.net.stop(); self.gps.stop(); self.display.close(); pygame.quit()

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="flightscope")
    ap.add_argument("--windowed", action="store_true", help="run in a window (desktop dev)")
    ap.add_argument("--home", help="lat,lon override")
    ap.add_argument("--range", type=int)
    ap.add_argument("--write-config", action="store_true", help="write an example config and exit")
    a = ap.parse_args(argv)
    if a.write_config: C.save_example(); print(C.CONFIG_PATH); return
    cfg = C.load()
    if a.windowed: cfg.windowed = True
    if a.home: cfg.home_lat, cfg.home_lon = map(float, a.home.split(","))
    if a.range: cfg.range_nm = a.range
    App(cfg).run()
