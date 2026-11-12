"""Local receiver: readsb's aircraft.json. Zero-cost when readsb isn't running."""
from __future__ import annotations
import json, os, time

class ReadsbSource:
    name = "local"

    def __init__(self, cfg):
        self.path = cfg.readsb_json
        self.stamp = 0.0
        self._mtime = 0.0
        self._rows: list[dict] = []

    @property
    def present(self) -> bool:
        return os.path.exists(self.path)

    @property
    def ok(self) -> bool:
        return time.time() - self.stamp < 10

    def snapshot(self) -> list[dict]:
        try:
            m = os.stat(self.path).st_mtime
            if m != self._mtime:
                with open(self.path) as fh:
                    d = json.load(fh)
                self._rows, self._mtime, self.stamp = d.get("aircraft") or [], m, time.time()
        except (OSError, ValueError):
            self._rows = []
        return list(self._rows)
