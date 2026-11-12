"""Battery life: sleep the SDR while the internet feed is healthy, dim/blank the backlight when
nobody is touching, and read the UPS HAT's fuel gauge when there is one."""
from __future__ import annotations
import glob, subprocess, threading, time

class Backlight:
    def __init__(self, cfg):
        paths = glob.glob("/sys/class/backlight/*/brightness")
        self.path = paths[0] if paths else None
        self.cfg = cfg; self.level = None; self.state = "on"; self.last_touch = time.time(); self.allow_off = True
        self.set(cfg.brightness)

    def _write(self, path, v):
        try:
            with open(path, "w") as f: f.write(str(int(v)))
        except OSError as e:
            print(f"power: {path} not writable ({e.strerror}); using sudo", flush=True)
            try: subprocess.Popen(["sudo", "-n", "sh", "-c", f"echo {int(v)} > {path}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError: pass

    FB_BLANK = "/sys/class/graphics/fb0/blank"      # 4 = power the panel down through DRM; 0 = wake

    def apply(self):
        """Config changed (setup screen): re-apply the awake level now."""
        if self.state == "on": self.level = None; self.set(self.cfg.brightness)

    def set(self, v: int):
        """0 = properly off. This panel's brightness 0 (and bl_power) still glow; powering the display
        down through the framebuffer's DPMS blank goes fully dark. The app keeps drawing meanwhile."""
        if self.path is None or v == self.level: return
        if v <= 0:
            self._write(self.FB_BLANK, 4)
        else:
            if self.level is not None and self.level <= 0: self._write(self.FB_BLANK, 0)
            self._write(self.path, v)
        self.level = int(v)

    def touched(self) -> bool:
        """Call on any touch. Returns True if this touch only woke the screen (and should be swallowed)."""
        self.last_touch = time.time()
        woke = self.state == "off"
        if self.state != "on": print(f"power: backlight on (touch{', woke' if woke else ''})", flush=True)
        self.state = "on"; self.set(self.cfg.brightness)
        return woke

    def tick(self):
        idle = time.time() - self.last_touch                  # a timer of 0 means never
        off_after = self.cfg.off_after_s if self.cfg.off_after_s > 0 else float("inf")
        if idle > off_after and self.state != "off" and self.allow_off:      # never go dark if nothing could wake us
            self.state = "off"; self.set(0); print(f"power: backlight off after {idle:.0f}s idle", flush=True)
        elif self.cfg.dim_after_s > 0 and self.cfg.dim_after_s < idle <= off_after and self.state == "on":
            self.state = "dim"; self.set(self.cfg.dim_level); print(f"power: backlight dim after {idle:.0f}s idle", flush=True)

class DongleSleeper:
    """readsb keeps the SDR sampling flat out (~1.1 W). Stop it while Wi-Fi carries the map; start it
    the moment the feed goes stale. Hysteresis so a single bad poll doesn't bounce the service."""
    def __init__(self, app):
        self.app = app; self.want_running = True; self.since = time.time(); self._last_cmd = 0.0; self.running = None
        self._check()

    def _check(self):
        try: self.running = subprocess.run(["systemctl", "is-active", "readsb"], capture_output=True, text=True, timeout=3).stdout.strip() not in ("inactive", "failed")
        except Exception: self.running = None

    def _cmd(self, verb):
        try: subprocess.Popen(["sudo", "-n", "systemctl", verb, "readsb"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError: pass
        self._last_cmd = time.time(); print(f"power: readsb {verb} ({'wifi ok' if verb == 'stop' else 'feed down'})", flush=True)

    def tick(self):
        now = time.time(); net = self.app.net
        want = (not net.ok) or net.fails >= 2            # start the antenna early: two failed polls in a row, don't wait for staleness
        if want != self.want_running: self.want_running, self.since = want, now
        held = now - self.since
        if now - self._last_cmd < 10: return
        if self.want_running and held > 5 and not self.running: self._cmd("start"); self.running = True
        elif not self.want_running and held > 60 and self.running is not False: self._cmd("stop"); self.running = False

class Battery:
    """The UPS HAT (D)'s INA219 sits on the battery rail. Current comes straight from the shunt voltage and the
    real shunt value, so it doesn't depend on the calibration register. present = the chip answers;
    cells = there is actually a battery on the rail."""
    ADDR = 0x43
    # open-circuit voltage -> charge, for a 21700 NMC cell at light load
    OCV = [(3.00, 0), (3.30, 3), (3.40, 6), (3.50, 12), (3.60, 25), (3.70, 42), (3.80, 57), (3.90, 70), (4.00, 82), (4.10, 92), (4.20, 100)]
    R_INT = 0.03                                                        # two P42As in parallel, roughly

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.present = False; self.cells = False; self.percent = None; self.volts = None; self.amps = 0.0; self.watts = 0.0
        self.state = "none"                                             # none | charging | full | discharging
        self.eta_s = None                                               # to empty (discharging) or to full (charging)
        self._pct_f = None; self._amps_f = None; self.updated = 0.0
        try:
            import smbus2
            self.bus = smbus2.SMBus(1)
            self.bus.write_i2c_block_data(self.ADDR, 0x00, [0x39, 0x9F])      # 32 V bus, ±320 mV shunt, 12-bit, continuous
            self.present = True
        except Exception:
            self.bus = None
        if self.present: threading.Thread(target=self._loop, name="battery", daemon=True).start()

    def _read(self, reg):
        d = self.bus.read_i2c_block_data(self.ADDR, reg, 2); v = (d[0] << 8) | d[1]
        return v - 65536 if v > 32767 else v

    @classmethod
    def _pct(cls, v):
        if v <= cls.OCV[0][0]: return 0.0
        for (v0, p0), (v1, p1) in zip(cls.OCV, cls.OCV[1:]):
            if v <= v1: return p0 + (p1 - p0) * (v - v0) / (v1 - v0)
        return 100.0

    def _loop(self):
        shunt = (self.cfg.battery_shunt_ohm if self.cfg else 0.01) or 0.01
        sign = (self.cfg.battery_sign if self.cfg else -1) or -1
        mah = (self.cfg.battery_mah if self.cfg else 8400) or 8400
        fails = 0
        while True:
            try:
                bus_v = (self._read(0x02) >> 3) * 0.004
                amps = sign * self._read(0x01) * 0.00001 / shunt        # shunt register LSB = 10 µV; + = into the battery
                fails = 0
            except Exception:
                fails += 1
                if fails > 5: self.present = False; return
                time.sleep(2); continue
            self.volts, self.updated = bus_v, time.time()
            self.cells = bus_v > 2.5
            if not self.cells:
                self.state, self.percent, self.eta_s, self.amps = "none", None, None, 0.0
                time.sleep(5); continue
            self._amps_f = amps if self._amps_f is None else self._amps_f * 0.7 + amps * 0.3
            self.amps = self._amps_f; self.watts = bus_v * abs(self.amps)
            ocv = bus_v - self.amps * self.R_INT                            # undo the sag under load / rise under charge
            pct = self._pct(ocv)
            self._pct_f = pct if self._pct_f is None else self._pct_f * 0.8 + pct * 0.2
            self.percent = int(round(self._pct_f))
            if self.amps > 0.05: self.state = "charging"
            elif ocv >= 4.13 and abs(self.amps) <= 0.05: self.state = "full"
            else: self.state = "discharging"
            remaining = mah * self._pct_f / 100.0
            if self.state == "charging": self.eta_s = (mah - remaining) / (self.amps * 1000) * 3600 if self.amps > 0.1 else None
            elif self.state == "discharging" and self.amps < -0.05: self.eta_s = remaining / (-self.amps * 1000) * 3600
            else: self.eta_s = None
            time.sleep(3)

    @property
    def charging(self) -> bool: return self.state in ("charging", "full")

    def eta_text(self) -> str:
        if self.eta_s is None: return ""
        h, m = divmod(int(self.eta_s // 60), 60)
        t = f"{h} h {m:02d} min" if h else f"{m} min"
        return ("full in " if self.state == "charging" else "") + t + ("" if self.state == "charging" else " left")
