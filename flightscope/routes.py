"""Where a flight came from and where it's going: adsbdb callsign lookup, then adsb.im's routeset (the
tar1090 route database, which knows many callsigns adsbdb doesn't), cached on disk per callsign, fetched by
a worker thread so the UI never waits. 'No route' answers are retried after a few days, failed lookups after a few
minutes. The plane on screen (urgent) jumps the queue."""
from __future__ import annotations
import collections, json, threading, time, urllib.error, urllib.request
from pathlib import Path
from . import offline

API = "https://api.adsbdb.com/v0/callsign/{cs}"
ROUTESET = "https://adsb.im/api/0/routeset"      # api.adsb.lol/api/0/routeset answers 201 with an empty body
RETRY_NONE_S = 3 * 86400
RETRY_FAIL_S = 600            # offline, timeout, bad clock: leave that callsign alone for a while

def _seg_off(p, a, b):
    """Rough distance (deg) from p to the segment a-b, flat - only used to pick the leg of a multi-stop route."""
    (y, x), (y0, x0), (y1, x1) = p, a, b
    dx, dy = x1 - x0, y1 - y0; L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / L))
    return ((x - x0 - t * dx) ** 2 + (y - y0 - t * dy) ** 2) ** 0.5

class Route:
    __slots__ = ("origin", "dest", "airline")
    def __init__(self, origin, dest, airline):
        self.origin, self.dest, self.airline = origin, dest, airline   # each: dict(iata, icao, city, name, lat, lon) or None

def _ap(d):
    if not d: return None
    return {"iata": d.get("iata_code") or "", "icao": d.get("icao_code") or "", "city": d.get("municipality") or "",
            "name": d.get("name") or "", "lat": d.get("latitude"), "lon": d.get("longitude"), "country": d.get("country_iso_name") or ""}

class RouteCache:
    def __init__(self, cfg):
        self.cfg = cfg
        self.dir = Path(cfg.cache_dir) / "routes"; self.dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, Route | None] = {}
        self._pending: set[str] = set()
        self._absent: set[str] = set()          # no file on disk (so get() needn't stat it every frame)
        self._failed: dict[str, float] = {}
        self._q: collections.deque = collections.deque()
        self._lock = threading.Condition()
        self.db = None                          # OfflineDB: routes when the lookups can't be reached
        threading.Thread(target=self._worker, name="routes", daemon=True).start()

    def get(self, callsign: str, pos=None, urgent=False) -> Route | None:
        """Cached route or None. pos (lat, lon) of the plane lets a lookup pick the right leg of a multi-stop route;
        without it this only reads the cache. urgent: the plane he's looking at - ask before the rest."""
        cs = (callsign or "").strip().upper()
        if not cs or len(cs) < 4 or not cs[:3].isalpha(): return None
        if cs in self._mem: return self._mem[cs]
        if cs not in self._absent and cs not in self._pending:
            p = self.dir / f"{cs}.json"
            if not p.exists(): self._absent.add(cs)
            else:
                try:
                    d = json.load(open(p))
                    r = Route(d.get("origin"), d.get("dest"), d.get("airline")) if d.get("origin") else None
                    stale = r is None and time.time() - float(d.get("at") or p.stat().st_mtime) > RETRY_NONE_S
                    if not stale:
                        self._mem[cs] = r
                        if r and pos is not None and self._lacks_country(d) and time.time() - self._failed.get(cs, 0) >= RETRY_FAIL_S:
                            self._enqueue(cs, pos, urgent)             # cached before flags existed: show it now, fetch the country behind it
                        return r
                    if pos is None: return None
                except ValueError: pass                      # stale 'no route' or a torn file: ask again
        if pos is None or time.time() - self._failed.get(cs, 0) < RETRY_FAIL_S: return None
        self._enqueue(cs, pos, urgent)
        return None

    @staticmethod
    def _lacks_country(d) -> bool:
        return any(isinstance(ap, dict) and "country" not in ap for ap in (d.get("origin"), d.get("dest")))

    def _enqueue(self, cs, pos, urgent):
        with self._lock:
            if cs not in self._pending:
                self._pending.add(cs)
                (self._q.appendleft if urgent else self._q.append)((cs, pos)); self._lock.notify()
            elif urgent and self._q and self._q[0][0] != cs:
                item = next((x for x in self._q if x[0] == cs), None)
                if item: self._q.remove(item); self._q.appendleft(item)

    def _fetch(self, url, body=None):
        h = {"User-Agent": self.cfg.user_agent, "Accept": "application/json"}
        if body is not None: h["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=h)
        with offline.urlopen(req, timeout=10) as r:
            raw = r.read()
        return json.loads(raw) if raw.strip() else None

    def _adsbdb(self, cs):
        try: d = self._fetch(API.format(cs=cs))
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            raise
        fr = (d.get("response") or {}).get("flightroute") if d and isinstance(d.get("response"), dict) else None
        if not fr: return None
        return {"origin": _ap(fr.get("origin")), "dest": _ap(fr.get("destination")), "airline": (fr.get("airline") or {}).get("name"), "src": "adsbdb"}

    def _routeset(self, cs, pos):
        d = self._fetch(ROUTESET, {"planes": [{"callsign": cs, "lat": pos[0], "lng": pos[1]}]})
        hit = next((x for x in (d or []) if (x.get("callsign") or "").upper() == cs), None)
        aps = [a for a in (hit or {}).get("_airports") or [] if a.get("lat") is not None]
        if len(aps) < 2: return None
        legs = list(zip(aps, aps[1:]))                  # 'A-B-C' is two legs: take the one the plane is on
        o, dst = min(legs, key=lambda l: _seg_off(pos, (l[0]["lat"], l[0]["lon"]), (l[1]["lat"], l[1]["lon"])))
        ap = lambda a: {"iata": a.get("iata") or "", "icao": a.get("icao") or "", "city": a.get("location") or "",
                        "name": a.get("name") or "", "lat": a.get("lat"), "lon": a.get("lon"), "country": a.get("countryiso2") or ""}
        return {"origin": ap(o), "dest": ap(dst), "airline": None, "src": "adsb.im"}

    def _worker(self):
        while True:
            with self._lock:
                while not self._q: self._lock.wait()
                cs, pos = self._q.popleft()
            try:
                out = self._adsbdb(cs) or self._routeset(cs, pos) or (self.db and self.db.route(cs, pos)) or {"origin": None, "dest": None, "airline": None}
                out["at"] = int(time.time())
                for k in ("origin", "dest"):
                    if isinstance(out.get(k), dict): out[k].setdefault("country", "")      # always present once asked, so a cached route isn't asked about again
                json.dump(out, open(self.dir / f"{cs}.json", "w"))
                self._failed.pop(cs, None); self._mem.pop(cs, None)
            except Exception as e:
                off = self.db.route(cs, pos) if self.db else None
                if off: self._mem[cs] = Route(off["origin"], off["dest"], None)     # not saved: the internet's answer wins once it's back
                else:
                    self._mem.pop(cs, None); self._failed[cs] = time.time()
                    if not offline.on: print(f"routes: {cs}: {type(e).__name__}: {e} (again in {RETRY_FAIL_S // 60} min)", flush=True)
            finally:
                self._absent.discard(cs)
                with self._lock: self._pending.discard(cs)
            time.sleep(0.7)
