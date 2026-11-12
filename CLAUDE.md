# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Flightscope: a handheld Raspberry Pi 4 flight tracker for children (pygame-ce map, live ADS-B data, logbook), plus the parametric 3D-printed case (`case/`) and the provisioning/deploy scripts for the device (`provision/`, `tools/`). There is no test suite and no linter configured.

## Commands

Run the app on a desktop (window instead of framebuffer, mouse instead of touch):

```
python3 -m venv .venv && source .venv/bin/activate
pip install pygame-ce numpy pyserial smbus2     # numpy is imported by world.py but missing from requirements.txt; evdev is Linux-only, skip it off-device
python -m flightscope --windowed [--home LAT,LON] [--range NM]
python -m flightscope --write-config            # writes a full example config and exits
```

- Press `q` in the window to quit.
- Config is JSON at `~/.config/flightscope/config.json` (override path with `FLIGHTSCOPE_CONFIG`). There is no `.env`. `Config` in `flightscope/config.py` holds the defaults, and only keys matching a `Config` field are applied. `photo_contact` is empty by default, which disables Planespotters photo lookups.
- Device deploy: `tools/deploy.sh [pi@flightscope.local]` rsyncs `flightscope/` and restarts the systemd unit. It also handles the read-only overlay rootfs.
- Rebuild the offline map: `python3 tools/build_map.py <lat> <lon> --radius-nm 220` writes `flightscope/data/map.json`. Raw Natural Earth and OurAirports inputs go in `data/`, which is gitignored. `tools/build_world.py` builds `data/world.npz` and `world_labels.json`.
- Case: `case/build.sh` (needs `case/.venv` with cadquery 2.8.0 via uv, plus ImageMagick `convert`; about 4 min). It aborts if `check.py` reports clashes. `--holes` adds a hole report.

## Architecture

`flightscope/app.py` `App` owns everything and runs the main loop. Each frame: pump events to the top screen of a **screen stack** (`push`/`pop`/`replace`; screens in `ui/` implement `handle`, `update(dt)`, `draw`), ingest data, tick power, update, draw, flip.

Data flow:
- **Sources** (`sources/`): `NetworkSource` polls adsb.fi then adsb.lol in a thread (a 429 parks that provider). `ReadsbSource` reads the local `/run/readsb/aircraft.json`. `GpsSource` reads gpsd and serial. The antenna is a **fallback only**: `App._ingest` reads it only when the network feed isn't fresh, and `power.DongleSleeper` stops readsb while the feed is healthy.
- `model.Fleet` merges rows into aircraft keyed by hex. `App.mode` is `wifi`, `antenna` or `none`.
- **Enrichment**: `RouteCache` (adsbdb, then adsb.im routeset, then `OfflineDB`) and `PhotoCache` (Planespotters) fetch in worker threads and cache on disk under `cfg.cache_dir`. `get()` is called every frame and returns None until data arrives. Route airports carry an ISO `country` code (adsbdb, adsb.im, VRS data); `ui/flags.py` draws the matching PNG from `flightscope/data/flags/` beside the city name in `kid.route_line`/`journey_line`, and routes cached before this existed refetch once to pick the code up. `CityImages` (`cities.py`) fetches a city's Wikipedia lead image when the user taps a place name on the card; it is held in memory only (never written to disk), and a page is accepted only if it sits within 40 NM of the airport. `OfflineDB` builds a SQLite file weekly in a niced subprocess (`python -m flightscope.offlinedb`) for use with no internet.
- All HTTP goes through `offline.urlopen`, except the offlinedb download, which uses `urllib.request.urlopen` directly. This is how the "Antenna only" setup toggle simulates being offline.
- `world.World` loads `data/world.npz` (quantised polygons) in a background thread and draws with numpy. `ui/mapview.py` is the largest file, with the map, zoom and follow logic.

Device-specific constraints that shape the code:
- The panel switch cuts power instantly and the rootfs is read-only (overlayroot). All persistent writes must go through `safefile` (temp file, fsync, rename, fsync dir). Persistent state lives under `/data` (logbook, config, cache). `App.restore_clock` and `_save_clock` exist because there is no RTC.
- Display: `display.py` selects `FbDisplay` (writes `/dev/fb0` with `pwrite`, with `SDL_VIDEODRIVER=dummy`) or a normal window. Touch comes from evdev in `touch.py` (`FbDisplay` mode only).
- Privileged operations use `sudo -n` subprocess calls (`nmcli`, `systemctl`, `date -s`, sysfs writes in `power.py` and `touch.py`). They fail harmlessly off-device. On a dev Mac with passwordless sudo, the `date -s` calls in `app.py` and `sources/gps.py` could actually change the clock.
- Dev hooks in `App._screenshot_check` (polled once per second): touching or writing `/tmp/flightscope.{shot,tap,pinch,sel,admin,key}` takes a screenshot or injects input, which lets you drive the UI headlessly, including over SSH.

## Provisioning and case

- `provision/` holds cloud-init (`user-data`, `network-config`), the `config.txt` additions, systemd units, `flash.sh` (writes an SD card; check the device path) and `make-readonly.sh`. `user-data` ships a placeholder SSH key that must be replaced, and grants `pi` `NOPASSWD:ALL`.
- `case/flightscope_case.py` is the CadQuery model. All dimensions are constants at the top, and some are marked `MEASURE` as estimates. `check.py`, `exploded.py`, `fit_test.py` and `views.py` import it. `viewer_layout.js` and `viewer_parts.js` are generated by `views.py`, so don't hand-edit them. See `case/README.md` for the assembly and print details.
