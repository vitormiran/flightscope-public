"""Look-ups for when there's no internet: aircraft (hex -> registration, type, model) from wiedehopf's tar1090-db, and
routes (callsign -> airports) from the VRS standing data. Downloaded at most weekly while online and built into one
SQLite file by a niced subprocess (parsing ~1.2M CSV rows inside the app would stall the map), read by key."""
from __future__ import annotations
import csv, gzip, io, os, sqlite3, subprocess, sys, threading, time, urllib.request
from pathlib import Path
from . import offline

AIRCRAFT = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft.csv.gz"
ROUTES = "https://vrs-standing-data.adsb.lol/routes.csv.gz"       # static files, not the rate-limited API
AIRPORTS = "https://vrs-standing-data.adsb.lol/airports.csv.gz"
MAX_AGE_S = 7 * 86400
RETRY_S = 6 * 3600

class OfflineDB:
    def __init__(self, cfg):
        self.cfg = cfg
        self.path = Path(cfg.cache_dir) / "offline.db"
        self._con = None; self._mtime = 0.0; self._has_country = None
        self._lock = threading.Lock()
        self._planes: dict[str, tuple | None] = {}
        self._proc = None; self._tried = time.time() - RETRY_S + 120      # first try 2 min after boot, not during it

    def _db(self):
        try: m = self.path.stat().st_mtime
        except OSError: return None
        if m != self._mtime:                                                 # rebuilt: reopen
            if self._con: self._con.close()
            self._con = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True, check_same_thread=False)
            self._mtime = m; self._planes.clear()
            self._has_country = any(c[1] == "country" for c in self._con.execute("PRAGMA table_info(airports)"))      # built before flags: rebuild
        return self._con

    def plane(self, hex: str):
        """(reg, type, desc) or None."""
        if hex in self._planes: return self._planes[hex]
        with self._lock:
            db = self._db()
            try: r = db.execute("SELECT reg, type, desc FROM aircraft WHERE hex = ?", (hex.upper(),)).fetchone() if db else None
            except sqlite3.Error: r = None
        if len(self._planes) > 5000: self._planes.clear()
        self._planes[hex] = r
        return r

    def enrich(self, rows: list[dict]) -> list[dict]:
        """readsb only knows hex, callsign and position: fill in what the internet feed would have said."""
        out = []
        for r in rows:
            if not r.get("t") and (p := self.plane((r.get("hex") or "").lower())):
                r = dict(r, r=r.get("r") or p[0], t=p[1], desc=r.get("desc") or p[2])
            out.append(r)
        return out

    def route(self, cs: str, pos) -> dict | None:
        """Same shape as RouteCache's answers; for 'A-B-C' the leg the plane is on."""
        from .routes import _seg_off
        with self._lock:
            db = self._db()
            if not db: return None
            try:
                row = db.execute("SELECT aps FROM routes WHERE cs = ?", (cs,)).fetchone()
                if not row: return None
                aps = []
                for code in row[0].split("-"):
                    a = db.execute(f"SELECT icao, iata, name, city, lat, lon{', country' if self._has_country else ''} FROM airports WHERE icao = ?", (code,)).fetchone()
                    if a: aps.append(dict(zip(("icao", "iata", "name", "city", "lat", "lon", "country"), a)))
            except sqlite3.Error: return None
        if len(aps) < 2: return None
        legs = list(zip(aps, aps[1:]))
        o, d = min(legs, key=lambda l: _seg_off(pos, (l[0]["lat"], l[0]["lon"]), (l[1]["lat"], l[1]["lon"]))) if pos else legs[0]
        return {"origin": o, "dest": d, "airline": None, "src": "vrs"}

    def tick(self):
        """From the main loop: refresh when the file is a week old, only while online, one build at a time."""
        now = time.time()
        if self._proc is not None:
            if self._proc.poll() is None: return
            print(f"offline db: build {'done' if self._proc.returncode == 0 else f'failed ({self._proc.returncode})'}", flush=True)
            self._proc = None
        if now - self._tried < RETRY_S or offline.on: return
        with self._lock: self._db()
        try:
            if now - self.path.stat().st_mtime < MAX_AGE_S and self._has_country is not False: return
        except OSError: pass
        self._tried = now
        print("offline db: downloading aircraft and routes", flush=True)
        self._proc = subprocess.Popen(["nice", "-n", "19", sys.executable, "-m", "flightscope.offlinedb", str(self.path), self.cfg.user_agent],
                                      cwd=Path(__file__).resolve().parent.parent)

def _get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(r.read())), encoding="utf-8-sig", newline="")

def build(path: Path, ua: str):
    tmp = path.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript("""PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
        CREATE TABLE aircraft (hex TEXT PRIMARY KEY, reg TEXT, type TEXT, desc TEXT) WITHOUT ROWID;
        CREATE TABLE routes (cs TEXT PRIMARY KEY, aps TEXT) WITHOUT ROWID;
        CREATE TABLE airports (icao TEXT PRIMARY KEY, iata TEXT, name TEXT, city TEXT, lat REAL, lon REAL, country TEXT) WITHOUT ROWID;""")
    rows = csv.reader(_get(AIRCRAFT, ua), delimiter=";")
    con.executemany("INSERT OR IGNORE INTO aircraft VALUES (?, ?, ?, ?)",
                    ((r[0].upper(), r[1] or None, r[2] or None, r[4] or None) for r in rows if len(r) > 4 and (r[1] or r[2])))
    con.executemany("INSERT OR IGNORE INTO routes VALUES (?, ?)",
                    ((r["Callsign"], r["AirportCodes"]) for r in csv.DictReader(_get(ROUTES, ua)) if r.get("AirportCodes")))
    con.executemany("INSERT OR IGNORE INTO airports VALUES (?, ?, ?, ?, ?, ?, ?)",
                    ((r["ICAO"], r["IATA"] or "", r["Name"], r["Location"], float(r["Latitude"]), float(r["Longitude"]), r.get("CountryISO2") or "")
                     for r in csv.DictReader(_get(AIRPORTS, ua)) if r.get("ICAO") and r.get("Latitude")))
    n = [con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("aircraft", "routes", "airports")]
    con.commit(); con.close()
    if min(n) == 0: tmp.unlink(); raise SystemExit(f"offline db: empty table {n}")
    os.replace(tmp, path)
    print(f"offline db: {n[0]} aircraft, {n[1]} routes, {n[2]} airports", flush=True)

if __name__ == "__main__":
    build(Path(sys.argv[1]), sys.argv[2])
