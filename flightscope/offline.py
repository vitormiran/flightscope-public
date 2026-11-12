"""Setup > Status 'Antenna only': pretend the internet has gone. Every fetch goes through urlopen here, so the app
behaves as it would with no Wi-Fi (planes from the antenna, no new photos or routes) while the Pi itself stays
online and reachable. Never saved - a restart is back on the feed."""
import urllib.error, urllib.request

on = False

def urlopen(req, timeout):
    if on: raise urllib.error.URLError("offline (antenna test)")
    return urllib.request.urlopen(req, timeout=timeout)
