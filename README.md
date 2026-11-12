# Flightscope

A handheld, battery-powered flight tracker for children. Tap a plane on the map to see a photo
of it, where it came from and where it's going; follow it, or catch it in a logbook. No ads, no
accounts. Runs on a Raspberry Pi 4 with a 4.3" touchscreen, a UPS HAT with two 21700
cells, a GPS, and (as a fallback when there's no Wi‑Fi) a FlightAware Pro Stick Plus ADS‑B
receiver. The whole thing lives in a 3D‑printed case.

## Hardware

| Part | Notes |
|---|---|
| Raspberry Pi 4B (2 GB) | |
| Waveshare 4.3" DSI capacitive touchscreen (800×480) | overlay `vc4-kms-dsi-waveshare-800x480` |
| Waveshare UPS HAT (D) + 2 × Molicel P42A 21700 | pogo‑pin power, INA219 fuel gauge on I2C 0x43 |
| Adafruit Ultimate GPS Breakout | on the Pi UART (`/dev/serial0`), backup power from the pack |
| FlightAware Pro Stick Plus + SMA bulkhead + antenna | readsb; only started when the internet feed is down |
| 12 mm latching switch, panel‑mount USB‑C, M3 inserts and screws (M2.5 for the Pi/HAT stack) | see `case/README.md` |

## Software (`flightscope/`)

Pure Python + pygame‑ce, rendering straight to the framebuffer (`/dev/fb0`) and reading touch
from evdev, so there's no desktop, no X, no compositor. Boots to the map in ~10 s.

- **Map** — offline vector map clipped from Natural Earth + OurAirports, continuous pinch zoom,
  planes coloured by altitude with drawn icons (helicopters too), dotted route lines to origin
  and destination, FOLLOW mode, star badges for logged planes, and small round badges for military
  (white star on olive) and "interesting" (yellow `!`) aircraft, taken from the feed's tar1090-db `dbFlags`.
- **Plane data** — adsb.lol v2 point query over Wi‑Fi (5 s polls, polite back‑off), routes from
  adsbdb and adsb.im, photos from Planespotters. The antenna (readsb) is a fallback only: it's
  stopped while the feed is healthy to save ~1 W, and started as soon as the feed goes quiet.
- **Offline** — an aircraft database (tar1090-db) and a route database (VRS standing data) are
  downloaded weekly while online, so planes heard on the antenna still get a registration, type and
  route with no internet. Setup > Status > "Antenna only" simulates being offline (the app stops
  using the internet; Wi-Fi and SSH stay up) for testing the antenna.
- **City pictures** — on the full-screen plane card the origin and destination names are underlined;
  tap one to see a picture of that city (Wikipedia's lead image, credited on screen). It is fetched
  over Wi‑Fi when you tap, shown from memory and never saved to disk. No picture, or no Wi‑Fi: just the name.
- **Logbook** — one entry per airframe, "seen again" after 2 h or a new flight, totals by
  airline and by type, two‑step delete.
- **Setup screen** — hold Home for 3 s: status, Wi‑Fi (scan/join with an on‑screen keyboard),
  settings with steppers (saved to `~/.config/flightscope/config.json`), battery detail, power.
- **Power** — backlight dims then powers the panel down through DRM (touch wakes it), battery %
  from an OCV curve with load correction, time‑to‑empty/full. GPS "You" marker; the feed follows
  the device when it has a fix.

Dev hooks on the device (`/tmp/flightscope.shot`, `.tap`, `.pinch`, `.sel`, `.admin`, `.key`)
let you drive and screenshot the UI over SSH.

## Getting it on a Pi

1. `provision/flash.sh` writes Raspberry Pi OS Lite (Trixie, arm64) and drops in the cloud‑init
   files (`user-data`, `network-config` — fill in your Wi‑Fi), the `config.txt` additions and
   a quiet‑boot `cmdline.txt`. First boot installs packages, readsb and the venv.
2. `tools/deploy.sh` rsyncs `flightscope/` to the Pi and (re)starts the systemd service.
3. Make it safe to switch off at any time (the panel switch cuts power instantly): shut the Pi down,
   put the card in a reader and run `sudo provision/make-readonly.sh /dev/sdX`. The system then runs
   read-only (overlayroot, writes go to RAM) and a small `fsdata` partition at `/data` keeps the logbook,
   settings, route/photo cache and saved Wi‑Fi. `tools/deploy.sh` writes through to the real rootfs
   when the overlay is on. To change the system itself, `sudo raspi-config nonint disable_overlayfs` and reboot.
4. Build the offline map for your area once:
   `python3 tools/build_map.py <lat> <lon> --radius-nm 220` → `flightscope/data/map.json`.
   It reads Natural Earth 10 m `land`, `lakes`, `urban_areas`, `coastline`, `rivers_europe`,
   `populated_places_simple` GeoJSON and OurAirports `airports.csv` / `runways.csv` from `data/`
   (not committed — download from naturalearthdata.com and ourairports.com).

Runtime config lives on the device; the only two things you must set are `owner` (the child's
name) and `photo_contact` (Planespotters requires a contact in the User‑Agent). Home is set
from the GPS on the setup screen.

## Case (`case/`)

Parametric CadQuery model (`flightscope_case.py`) with a pairwise interference check
(`check.py`), component stand‑ins and STL export (`exploded.py`), an interactive Three.js
assembly viewer (`viewer.html`, with wiring, screws and an explode slider) and a caliper
measurement sheet (`measure.html`) that feeds real dimensions back into the model.
Print settings, hardware list, screw table and assembly steps are in
`case/README.md`. Printed STLs are in `case/out/`.

Build it on any Linux box with [uv](https://docs.astral.sh/uv/) and ImageMagick:

```
uv venv case/.venv --python 3.12 && VIRTUAL_ENV=case/.venv uv pip install -r case/requirements.txt
case/build.sh            # STLs, clash check, fit-test prints, renders, viewer data (~4 min)
```

## Layout

```
flightscope/      the app (sources/, ui/, data/, fonts/)
provision/        cloud-init + config.txt + systemd unit + flash script
tools/            deploy.sh, build_map.py
case/             CadQuery case (build.sh), checks, viewer, measurement sheet, print presets, STLs
```

Fonts: Nunito (SIL OFL, `flightscope/fonts/OFL.txt`). Map data: Natural Earth and OurAirports (public domain).
Live data, fetched at runtime and not redistributed here: adsb.lol, adsbdb, adsb.im, Planespotters,
wiedehopf/tar1090-db, VRS standing data. Please be polite to these free services: the app polls
gently, backs off when told to, and needs `photo_contact` set before it asks Planespotters.

Code and case: MIT.
