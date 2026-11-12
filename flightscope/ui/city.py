"""A city's picture, full screen, opened by tapping its name on the plane card. The picture is only held in memory
(see cities.py); with no picture, or no Wi-Fi, the name stands alone on the sky."""
from __future__ import annotations
import time
import pygame
from . import theme as T
from .widgets import text, fit_text, vscale
from .kid import plane_art, Pill, PAPER, INK, INK_SOFT, OUTLINE
from ..cities import CREDIT

W, H = 800, 480

class CityScreen:
    def __init__(self, app, name: str, lat=None, lon=None):
        self.app = app; self.name = name; self.lat = lat; self.lon = lon
        self.back = Pill((14, 14, 130, 50), "Back", size=19, icon="back")
        self._down = None; self._t0 = time.time()
        self.app.cities.get(name, lat, lon)                 # start fetching straight away

    def handle(self, e):
        if e.type == pygame.KEYDOWN and e.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE): return self.app.pop()
        if e.type == pygame.MOUSEBUTTONDOWN:
            self._down = e.pos; self.back.pressed = self.back.hit(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP:
            self.back.pressed = False
            if self._down: self.app.pop()                   # anywhere: back to the plane
            self._down = None

    def update(self, dt): pass

    def draw(self, s):
        state, img = self.app.cities.get(self.name, self.lat, self.lon)
        if img is not None:
            s.blit(vscale(img, W, H), (0, 0))
            band = pygame.Surface((W, 120), pygame.SRCALPHA)
            for y in range(120): pygame.draw.line(band, (0, 0, 0, int(170 * y / 119)), (0, y), (W, y))
            s.blit(band, (0, H - 120))
            text(s, fit_text(self.name, 52, W - 60, weight="black"), 52, (255, 255, 255), (30, H - 28), "bottomleft", weight="black")
            text(s, CREDIT, 11, (225, 225, 225), (W - 10, H - 8), "bottomright", bold=False)
        else:
            s.fill(PAPER); s.blit(plane_art(W, H, "", False, radius=0), (0, 0))
            name = fit_text(self.name, 64, W - 120, weight="black")
            pw = max(T.font(64, weight="black").size(name)[0] + 70, 420)
            panel = pygame.Rect(0, 0, pw, 170); panel.center = (W // 2, H // 2 + 10)
            pygame.draw.rect(s, PAPER, panel, border_radius=36); pygame.draw.rect(s, OUTLINE, panel, 3, border_radius=36)
            text(s, name, 64, INK, (W // 2, panel.y + 66), "center", weight="black")
            if state == "loading": msg = "Finding a picture" + "." * (1 + int((time.time() - self._t0) * 2) % 3)
            elif state == "failed": msg = "Couldn't get a picture - is the Wi-Fi on?"
            else: msg = "No picture for this place yet"
            text(s, msg, 18, INK_SOFT, (W // 2, panel.y + 126), "center", weight="bold")
        self.back.draw(s)
