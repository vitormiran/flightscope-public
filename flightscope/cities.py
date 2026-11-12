"""A picture of a city, for when a child taps its name on the plane card.

Source: Wikipedia's page summary (its lead image, from Wikimedia Commons). Nothing is saved: the picture is fetched
by a worker thread when asked for, decoded straight from memory and kept for a handful of cities only. Only the city's
name is sent. A page is used only if it is a real article (not a disambiguation page) whose coordinates are near the
airport, so 'Paisley' never turns into a different Paisley. No picture, or no Wi-Fi: the screen shows the name alone."""
from __future__ import annotations
import io, json, queue, re, threading, time, urllib.error, urllib.parse, urllib.request
import pygame
from .geo import gc_nm
from . import offline

API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}?redirect=true"
GEO = "https://en.wikipedia.org/w/api.php?action=query&list=geosearch&gscoord={lat}%7C{lon}&gsradius=10000&gslimit=200&format=json"
MAX_NM = 40.0                # how far the article may be from the airport and still count as the same city
MAX_BYTES = 4_000_000
KEEP = 6                     # decoded pictures held in memory
RETRY_FAIL_S = 60
CREDIT = "Picture: Wikipedia / Wikimedia Commons"

class CityImages:
    def __init__(self, cfg):
        self.cfg = cfg
        self._res: dict[str, tuple[str, pygame.Surface | None]] = {}     # key -> ("ready", surface) | ("none", None)
        self._failed: dict[str, float] = {}
        self._pending: set[str] = set()
        self._q: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        threading.Thread(target=self._worker, name="cities", daemon=True).start()

    @staticmethod
    def key(name: str, lat, lon) -> str:
        return f"{name.strip().lower()}|{round(lat, 1) if lat is not None else ''}|{round(lon, 1) if lon is not None else ''}"

    def get(self, name: str, lat=None, lon=None) -> tuple[str, pygame.Surface | None]:
        """('ready', surface) | ('none', None) once settled, ('loading', None) while a fetch is under way,
        ('failed', None) if the last try could not reach the internet (asks again after a minute)."""
        k = self.key(name, lat, lon)
        if k in self._res: return self._res[k]
        if time.time() - self._failed.get(k, 0) < RETRY_FAIL_S: return ("failed", None)
        with self._lock:
            if k not in self._pending:
                self._pending.add(k); self._q.put((k, name, lat, lon))
        return ("loading", None)

    def _get(self, url: str, accept: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": self.cfg.user_agent, "Accept": accept})
        with offline.urlopen(req, timeout=10) as r:
            data = r.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES: raise ValueError("picture too large")
        return data

    def _summary(self, title: str) -> dict | None:
        try: return json.loads(self._get(API.format(title=urllib.parse.quote(title.strip().replace(" ", "_"), safe="")), "application/json"))
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            raise

    def _nearby(self, name: str, lat, lon) -> list[str]:
        """Articles within 10 km of the airport named like the city: 'Faro, Portugal', 'Cork (city)'. Not 'Faro Airport'."""
        if lat is None or lon is None: return []
        d = json.loads(self._get(GEO.format(lat=lat, lon=lon), "application/json"))
        n = name.strip().lower()
        out = []
        for g in (d.get("query") or {}).get("geosearch") or []:
            t = g.get("title") or ""; rest = t[len(n):] if t.lower().startswith(n) else None
            if rest is not None and (rest.startswith(",") or rest.startswith(" (")) and "(disambiguation)" not in t: out.append(t)
        return out[:3]

    def _lookup(self, name: str, lat, lon) -> pygame.Surface | None:
        tried = [name]
        d = self._summary(name)
        titles = iter(())
        while True:
            if d and d.get("type") == "standard":
                c = d.get("coordinates") or {}
                near = lat is None or lon is None or (c.get("lat") is not None and gc_nm(lat, lon, c["lat"], c["lon"]) <= MAX_NM)
                thumb = (d.get("thumbnail") or {}).get("source")
                if near and thumb:
                    big = re.sub(r"/(\d+)px-", "/960px-", thumb, count=1)         # one of Wikimedia's standard sizes
                    try: raw = self._get(big, "image/*")
                    except urllib.error.HTTPError: raw = self._get(thumb, "image/*")
                    try: return pygame.image.load(io.BytesIO(raw)).convert()
                    except pygame.error: return None
            if len(tried) == 1:                                                   # the bare name was a disambiguation page or the wrong place
                titles = iter(self._nearby(name, lat, lon))
            t = next(titles, None)
            if t is None: return None
            tried.append(t); d = self._summary(t)

    def _worker(self):
        while True:
            k, name, lat, lon = self._q.get()
            try:
                s = self._lookup(name, lat, lon)
                self._res[k] = ("ready", s) if s is not None else ("none", None)
                self._failed.pop(k, None)
                while sum(v[1] is not None for v in self._res.values()) > KEEP:
                    del self._res[next(x for x, v in self._res.items() if v[1] is not None)]
            except Exception as e:
                self._failed[k] = time.time()
                print(f"cities: {name}: {type(e).__name__}: {e}", flush=True)
            finally:
                with self._lock: self._pending.discard(k)
            time.sleep(0.5)
