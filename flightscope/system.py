"""What the setup screen needs from the OS: Wi-Fi through NetworkManager, addresses, temperatures, power actions.
Anything slow runs in a Job so the UI never stalls."""
from __future__ import annotations
import subprocess, threading, time

def _run(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except Exception as e:
        return 1, "", str(e)

def _fields(line: str) -> list[str]:
    """Split one line of `nmcli -t` output; nmcli escapes ':' inside values as '\\:'."""
    return [f.replace("\x00", ":") for f in line.replace("\\:", "\x00").split(":")]

class Job:
    """Run fn in a thread; poll .done / .result from the UI."""
    def __init__(self, fn, *args):
        self.done = False; self.result = None; self.error = None; self.started = time.time()
        threading.Thread(target=self._go, args=(fn, args), daemon=True).start()
    def _go(self, fn, args):
        try: self.result = fn(*args)
        except Exception as e: self.error = str(e)
        self.done = True

# ---------- facts ----------
def hostname() -> str: return _run(["hostname"])[1] or "?"

def ip_addr(dev="wlan0") -> str | None:
    for line in _run(["nmcli", "-t", "-f", "IP4.ADDRESS", "dev", "show", dev])[1].splitlines():
        if ":" in line: return line.split(":", 1)[1].split("/")[0]
    return None

def wifi_status() -> tuple[str | None, int]:
    """(ssid, signal %) of the network we're on, or (None, 0)."""
    for line in _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"])[1].splitlines():
        f = _fields(line)
        if f and f[0] == "yes" and len(f) >= 3: return f[1], int(f[2] or 0)
    return None, 0

def cpu_temp() -> float | None:
    try: return int(open("/sys/class/thermal/thermal_zone0/temp").read()) / 1000.0
    except Exception: return None

def uptime_s() -> float:
    try: return float(open("/proc/uptime").read().split()[0])
    except Exception: return 0.0

def service_state(name: str) -> str:
    return _run(["systemctl", "is-active", name], timeout=5)[1] or "?"

def status_snapshot() -> dict:
    ssid, sig = wifi_status()
    return {"host": hostname(), "ip": ip_addr(), "ssid": ssid, "signal": sig, "temp": cpu_temp(), "uptime": uptime_s(),
            "readsb": service_state("readsb"), "gpsd": service_state("gpsd")}

# ---------- wi-fi ----------
def wifi_scan(rescan=True) -> list[dict]:
    """Networks in range, strongest first, one row per SSID."""
    out = _run(["sudo", "-n", "nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,ACTIVE", "dev", "wifi", "list", "--rescan", "yes" if rescan else "no"], timeout=40)[1]
    seen: dict[str, dict] = {}
    for line in out.splitlines():
        f = _fields(line) + ["", "", "", ""]
        ssid, sig, sec, act = f[0], int(f[1] or 0), f[2], f[3] == "yes"
        if not ssid: continue
        if ssid not in seen or sig > seen[ssid]["signal"] or act:
            seen[ssid] = {"ssid": ssid, "signal": sig, "secure": bool(sec and sec != "--"), "active": act or seen.get(ssid, {}).get("active", False)}
    return sorted(seen.values(), key=lambda n: (not n["active"], -n["signal"]))

def saved_wifi() -> dict[str, str]:
    """{ssid: profile name} for every saved Wi-Fi profile."""
    out = {}
    for line in _run(["nmcli", "-t", "-f", "NAME,TYPE", "con", "show"])[1].splitlines():
        f = _fields(line)
        if len(f) >= 2 and f[1] == "802-11-wireless":
            ssid = _run(["nmcli", "-g", "802-11-wireless.ssid", "con", "show", f[0]])[1]
            if ssid: out[ssid] = f[0]
    return out

def wifi_connect(ssid: str, password: str | None) -> tuple[bool, str]:
    saved = saved_wifi()
    if ssid in saved and not password:
        rc, out, err = _run(["sudo", "-n", "nmcli", "con", "up", "id", saved[ssid]], timeout=45)
    else:
        if ssid in saved: _run(["sudo", "-n", "nmcli", "con", "delete", "id", saved[ssid]])      # new password: start clean
        args = ["sudo", "-n", "nmcli", "dev", "wifi", "connect", ssid]
        if password: args += ["password", password]
        rc, out, err = _run(args, timeout=60)
    if rc == 0: return True, f"Connected to {ssid}"
    msg = (err or out).replace("Error: ", "").strip()
    if "Secrets were required" in msg or "802-11-wireless-security" in msg: msg = "Wrong password"
    return False, msg[:90] or "Could not connect"

def wifi_forget(ssid: str) -> tuple[bool, str]:
    saved = saved_wifi()
    if ssid not in saved: return False, "Not saved"
    rc, out, err = _run(["sudo", "-n", "nmcli", "con", "delete", "id", saved[ssid]])
    return rc == 0, ("Forgot " + ssid) if rc == 0 else (err or out)[:90]

# ---------- power ----------
def _fire(args):
    try: subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e: print(f"system: {args[-1]} failed: {e}", flush=True)

def reboot(): _fire(["sudo", "-n", "systemctl", "reboot"])
def poweroff(): _fire(["sudo", "-n", "systemctl", "poweroff"])
def restart_app(): _fire(["sudo", "-n", "systemctl", "restart", "flightscope"])
