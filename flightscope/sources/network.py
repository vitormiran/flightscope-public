"""Internet plane feed: adsb.lol-style 'v2' point queries, polled in a thread; the UI reads .latest under .lock.

Two free providers with the same aircraft format. adsb.lol caps each IP (500 requests a day, 60 a
minute), so a 429 parks that provider until its reset and the next one takes over.
Where to ask: .points() (set by the app) returns [(lat, lon, radius_nm), ...] - the map's view; a wide view
gives several points and each poll asks the next one, so the fleet fills in across the screen. Moving the map
somewhere new asks about the middle of it first, without waiting for the next poll."""
from __future__ import annotations
import json, math, threading, time, urllib.request, urllib.error

PROVIDERS = [  # name, url template, list key
    ("adsb.fi", "https://opendata.adsb.fi/api/v2/lat/{la:.4f}/lon/{lo:.4f}/dist/{r}", "aircraft"),
    ("adsb.lol", "{base}/v2/point/{la:.4f}/{lo:.4f}/{r}", "ac"),
]

class NetworkSource:
    name = "net"

    def __init__(self, cfg):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.latest: list[dict] = []
        self.stamp = 0.0            # time of last successful fetch
        self.latency = 0.0
        self.error: str | None = None
        self.total = 0
        self.fetches = 0
        self.fails = 0              # consecutive failed polls
        self.provider = None        # who answered last
        self.points = lambda: [(cfg.home_lat, cfg.home_lon, int(cfg.net_radius_nm))]
        self._parked: dict[str, float] = {}      # provider -> time it may be asked again
        self._turn = 0
        self._asked = None          # (lat, lon, r) of the last view's centre point
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, name="net-poll", daemon=True)

    def start(self): self._t.start()
    def stop(self): self._stop.set()

    @property
    def ok(self) -> bool:
        """Data is fresh enough to trust; a single failed poll doesn't flip this."""
        return time.time() - self.stamp < 75

    def _points(self):
        return self.points() or [(self.cfg.home_lat, self.cfg.home_lon, int(self.cfg.net_radius_nm))]

    def _moved(self, pts) -> bool:
        """The view's middle is now somewhere the last asks didn't cover well (half a radius away, or a new zoom)."""
        if self._asked is None: return True
        (la, lo, r), (la0, lo0, r0) = pts[0], self._asked
        dx = ((lo - lo0 + 540) % 360 - 180) * 60 * math.cos(math.radians(la)); dy = (la - la0) * 60
        return r != r0 or math.hypot(dx, dy) > r / 2

    def _next_point(self):
        pts = self._points()
        if self._moved(pts): self._turn = 0; self._asked = pts[0]
        else: self._turn = (self._turn + 1) % len(pts)
        la, lo, r = pts[self._turn % len(pts)]
        return la, (lo + 540) % 360 - 180, max(1, min(250, int(r)))

    def _park(self, name, e):
        h = e.headers
        try: wait = float(h.get("x-ratelimit-reset") or h.get("Retry-After") or 60)
        except ValueError: wait = 60.0
        wait = max(30.0, min(wait, 86400.0))
        self._parked[name] = time.time() + wait
        print(f"net: {name} rate-limited, resting {wait / 60:.0f} min", flush=True)

    def _run(self):
        while not self._stop.is_set():
            t0 = time.time(); la, lo, r = self._next_point(); asked = False
            for name, tpl, key in PROVIDERS:
                if self._parked.get(name, 0) > t0: continue
                asked = True
                url = tpl.format(base=self.cfg.adsb_base, la=la, lo=lo, r=r)
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": self.cfg.user_agent, "Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        d = json.load(resp)
                    rows = d.get(key) or []
                    with self.lock:
                        self.latest, self.total = rows, len(rows)
                        self.stamp, self.latency, self.error, self.fetches, self.fails = time.time(), time.time() - t0, None, self.fetches + 1, 0
                        self.provider = name
                    break
                except urllib.error.HTTPError as e:
                    if e.code == 429: self._park(name, e)
                    elif self.error != f"{name}: HTTP {e.code}": print(f"net: {name}: HTTP {e.code}", flush=True)
                    self.error = f"{name}: HTTP {e.code}"
                except Exception as e:
                    self.error = f"{name}: {type(e).__name__}"
            else:
                self.fails += 1
            if not asked: self.error = "all feeds resting"
            wait = self.cfg.net_poll_s if self.error is None else min(30, self.cfg.net_poll_s * 3)
            if not asked: wait = max(30.0, min(self._parked.values()) - time.time())
            until = t0 + max(0.2, wait)
            while not self._stop.wait(min(0.5, max(0.0, until - time.time()))) and time.time() < until:
                if asked and time.time() - t0 > 2.0 and self._moved(self._points()): break     # he scrolled somewhere new

    def snapshot(self) -> list[dict]:
        with self.lock:
            return list(self.latest)
