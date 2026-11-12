"""Runtime configuration. Defaults here, overridden by ~/.config/flightscope/config.json."""
from __future__ import annotations
import json, os
from dataclasses import dataclass, field, asdict
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("FLIGHTSCOPE_CONFIG", Path.home() / ".config/flightscope/config.json"))

@dataclass
class Config:
    home_lat: float = 52.2380   # the bundled map's centre (north-west England); set yours from the GPS or with tools/build_map.py
    home_lon: float = -7.0953
    range_nm: int = 40                  # starting scope range
    ranges: tuple = (10, 20, 40, 80, 150)
    fps: int = 20
    # network source (adsb.lol v2, no key needed)
    adsb_base: str = "https://api.adsb.lol"
    net_poll_s: float = 5.0
    net_radius_nm: int = 150            # fetch this wide so range changes don't refetch
    # photos (planespotters requires a contact in the User-Agent; leave blank to disable)
    photo_contact: str = ""             # e.g. "mailto:you@example.com" or "https://your.site/contact"
    # misc
    cache_dir: str = str(Path.home() / ".cache/flightscope")
    screenshot_trigger: str = "/tmp/flightscope.shot"   # touch this file -> app saves /tmp/flightscope.png
    windowed: bool = False
    dim_after_s: float = 30.0          # backlight to dim_level after this much no-touch (0 = never)
    off_after_s: float = 120.0         # backlight off after this; any touch wakes it (0 = never)
    dim_level: int = 80                # 0-255
    brightness: int = 255              # backlight when awake, 0-255
    start_zoom_nm: float = 36.0        # how much map the screen shows at start, NM across
    battery_mah: int = 8400            # 2 x Molicel P42A in parallel
    battery_shunt_ohm: float = 0.01    # UPS HAT (D), measured: a Pi 4 + display draws ~1.1 A from 3.5 V cells
    battery_sign: int = -1             # INA219 shunt reads positive when the cells are being drained
    app_name: str = "Flightscope"
    owner: str = ""                   # the child's name: "Sam" -> "Sam's Planes", "Sam's Logbook"
    title: str = ""                   # override the splash title; blank = derived from owner
    app_version: str = "0.1"

    @property
    def possessive(self) -> str:
        return (self.owner + ("'" if self.owner.endswith("s") else "'s")) if self.owner else ""

    @property
    def splash_title(self) -> str:
        return self.title or (f"{self.possessive} Planes" if self.owner else self.app_name)

    @property
    def user_agent(self) -> str:
        c = f" (+{self.photo_contact})" if self.photo_contact else ""
        return f"{self.app_name}/{self.app_version}{c}"

def load() -> Config:
    cfg = Config()
    if CONFIG_PATH.exists():
        try:
            for k, v in json.load(open(CONFIG_PATH)).items():
                if hasattr(cfg, k):
                    setattr(cfg, k, tuple(v) if k == "ranges" else v)
        except Exception as e:  # a bad config file must never stop the device booting
            print(f"config: ignoring {CONFIG_PATH}: {e}")
    return cfg

def save(cfg: Config):
    """Write only what differs from the defaults, so future defaults still apply."""
    base = Config(); d = {k: v for k, v in asdict(cfg).items() if v != getattr(base, k) and k != "windowed"}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    from . import safefile
    safefile.write_text(CONFIG_PATH, json.dumps(d, indent=2))

def save_example():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(Config()), indent=2))
