"""Planespotters photo lookup + on-disk cache. Fetches in a worker thread;
the UI asks get() every frame and receives a Surface once one exists. A failed fetch waits a few minutes;
only the last few photos stay decoded in memory."""
from __future__ import annotations
import io, json, queue, threading, time, urllib.request
from pathlib import Path
from . import offline
import pygame

API = "https://api.planespotters.net/pub/photos/hex/{hex}"
RETRY_FAIL_S = 600
KEEP = 40                      # decoded photos held in memory (~400 KB each)

class PhotoCache:
    def __init__(self, cfg):
        self.cfg = cfg
        self.enabled = bool(cfg.photo_contact)
        self.dir = Path(cfg.cache_dir) / "photos"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._surf: dict[str, pygame.Surface | None] = {}
        self._pending: set[str] = set()
        self._failed: dict[str, float] = {}
        self._credit: dict[str, str] = {}
        self._q: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        if self.enabled:
            threading.Thread(target=self._worker, name="photos", daemon=True).start()

    def credit(self, hex: str) -> str:
        if hex in self._credit: return self._credit[hex]
        p = self.dir / f"{hex}.json"; c = ""
        if p.exists():
            try: c = json.load(open(p)).get("photographer", "")
            except ValueError: pass
        if hex in self._surf: self._credit[hex] = c         # settled (photo or none): safe to remember
        return c

    def get(self, hex: str) -> pygame.Surface | None:
        """Surface if cached, None otherwise (and kick off a fetch)."""
        if hex in self._surf: return self._surf[hex]
        jpg, none = self.dir / f"{hex}.jpg", self.dir / f"{hex}.none"
        if jpg.exists():
            try:
                s = pygame.image.load(str(jpg)).convert()
            except pygame.error:
                s = None
            self._keep(hex, s)
            return s
        if none.exists() or not self.enabled:
            self._keep(hex, None)
            return None
        if time.time() - self._failed.get(hex, 0) < RETRY_FAIL_S: return None
        with self._lock:
            if hex not in self._pending:
                self._pending.add(hex); self._q.put(hex)
        return None

    def _keep(self, hex, s):
        self._surf[hex] = s
        if s is not None and sum(v is not None for v in self._surf.values()) > KEEP:
            old = next(k for k, v in self._surf.items() if v is not None)
            del self._surf[old]; self._credit.pop(old, None)

    def _fetch(self, url: str, accept: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": self.cfg.user_agent, "Accept": accept})
        with offline.urlopen(req, timeout=10) as r:
            return r.read()

    def _worker(self):
        while True:
            hex = self._q.get()
            try:
                d = json.loads(self._fetch(API.format(hex=hex.upper()), "application/json"))
                photos = d.get("photos") or []
                if not photos:
                    (self.dir / f"{hex}.none").touch()
                else:
                    p = photos[0]
                    src = (p.get("thumbnail_large") or p.get("thumbnail") or {}).get("src")
                    img = self._fetch(src, "image/*")
                    (self.dir / f"{hex}.jpg").write_bytes(img)
                    json.dump({"photographer": p.get("photographer", ""), "link": p.get("link", "")},
                              open(self.dir / f"{hex}.json", "w"))
                self._failed.pop(hex, None)
            except Exception as e:
                self._failed[hex] = time.time()
                print(f"photos: {hex}: {type(e).__name__}: {e} (again in {RETRY_FAIL_S // 60} min)", flush=True)
            finally:
                with self._lock: self._pending.discard(hex)
                self._surf.pop(hex, None); self._credit.pop(hex, None)
            time.sleep(1.0)   # planespotters asks for a gentle rate
