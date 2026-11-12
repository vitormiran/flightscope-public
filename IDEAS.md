# Flightscope ideas and follow-ups

Effort guide: **S** under a day, **M** a few days, **L** a week or more. Tick the ones to build.

## Done
- [x] Military badge (white star on olive disc) and "interesting" badge (exclamation mark on yellow disc), top right of the plane icon on the map. Uses `dbFlags` bit 0 and bit 1 (`model.py`, `ui/kid.py` `draw_badge`, `ui/mapview.py`).

## Follow-ups on the badges
- [ ] Show the badges on the plane card and in the logbook (S)
- [ ] Check that "interesting" (value 2) really shows up in live adsb.fi and adsb.lol data. The one sample I pulled only had 1 and 8.

## Spotting more, using data the app already receives
- [ ] Emergency alert for `emergency` / squawk 7700 / 7500, worded gently, e.g. "A plane needs to land quickly" (S)
- [ ] Plane-overhead alert: glow and chime when a plane is within about 2 NM (S)
- [ ] Arrival countdown: "lands in about 25 min, 190 miles to go", from route destination plus ground speed (S)
- [ ] Fun comparisons: "3x faster than a race car", "as high as 30 Eiffel Towers" (S)
- [ ] Plane facts by type: a hand-written table keyed on the `t` field (seats, wingspan, engines) for the top ~30 types (M)
- [ ] Look-up sky view: circular chart with direction and elevation from altitude and distance. There is no compass, so it is relative to north (M)

## Collecting and playing
- [ ] Badges and achievements: "10 airlines", "first A380", "a helicopter", "planes from 5 countries" (M). The logbook already tracks airline and type totals.
- [ ] Rarity score and a "rare catch!" celebration, from logbook history or a curated list (M)
- [ ] Daily or weekly challenge, e.g. "spot a plane going to Spain" (M)
- [ ] Mini-games: guess the destination, match the silhouette, "which is higher" (M-L)
- [ ] Silhouette illustration by plane type when there is no Planespotters photo or `photo_contact` is unset (M)

## Sound and feel
- [ ] Sounds: catch jingle, new-plane chime, overhead alert (S-M). Provisioning enables an I2S amp (`hifiberry-dac`), but I did not check whether the app plays any sound today.
- [ ] Read-aloud of plane name and route with `espeak` (M)
- [ ] Haptic or LED cue (M-L, needs new hardware, probably skip)

## Parent controls
- [ ] PIN on the setup screen (S-M). Setup opens by holding Home for 3 seconds, which a child could find.
- [ ] Quiet hours and daily screen-time limit (M), building on the existing backlight code
- [ ] Gentler polling when idle or overnight (S)
- [ ] Weekly summary for parents, e.g. "Sam spotted 14 planes, 6 airlines", shown as a QR code (M). A local web page on the Pi would need more security care.

## Extra data sources
Each adds an outside service, so it adds privacy and rate-limit costs.
- [ ] Weather at your location or the destination, e.g. Open-Meteo, no key (M)
- [ ] Country flags and facts from adsbdb (M, needs flag images)
- [ ] Airport detail pages: tap an airport label (L)

## Polish and accessibility
- [ ] Night mode or red-light mode (S)
- [ ] Larger-text or dyslexia-friendly font option (S-M)
- [ ] Longer flight trail and replay. The trail keeps only 90 s today (M)

## Housekeeping
- [ ] Fix the stale README line and `config.py` comment: the app asks adsb.fi first and adsb.lol second, not adsb.lol only (S)
- [ ] Add `numpy` to `requirements.txt` (`world.py` imports it) (S)
- [ ] Add `.venv/` to `.gitignore` (S)
- [ ] Guard the `sudo -n date -s` calls in `app.py` and `sources/gps.py` so they only run on Linux, to protect a dev Mac with passwordless sudo (S)

## Security hardening (from the review)
- [ ] Replace `sudo: ALL=(ALL) NOPASSWD:ALL` in `provision/user-data` with a sudoers file limited to the exact commands the app uses (`nmcli`, `systemctl reboot/poweroff/restart`, `date -s`, the I2C bind and the backlight write) (S-M)
- [ ] Replace the two `sudo sh -c` calls in `touch.py` and `power.py` with direct file writes plus narrow sudoers rules (S-M)
- [ ] Pass the Wi-Fi password to `nmcli` without exposing it in the process list (S)
- [ ] Remove `FLIGHTSCOPE_DEBUG=1` from `provision/flightscope.service` for production (S)
- [ ] Replace the placeholder SSH key in `provision/user-data` with your own before flashing (S)

## Suggested starting set
Emergency alert, overhead alert, arrival countdown, fun comparisons and sounds are quick wins. A setup PIN is the best parent-side win. Achievements and daily challenges give the most replay value for a child.
