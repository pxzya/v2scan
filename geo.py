"""
geo.py
Turns a 2-letter country code into its flag emoji, and looks up country
codes for a batch of hosts/IPs via the free ip-api.com batch endpoint.
"""
from __future__ import annotations

import requests

BATCH_URL = "http://ip-api.com/batch?fields=query,countryCode,status"
BATCH_SIZE = 100
REQUEST_TIMEOUT = 8

_FALLBACK_FLAG = "🌐"


def country_code_to_flag(cc: str) -> str:
    if not cc or len(cc) != 2 or not cc.isalpha():
        return _FALLBACK_FLAG
    cc = cc.upper()
    try:
        return "".join(chr(0x1F1E6 + (ord(ch) - ord("A"))) for ch in cc)
    except ValueError:
        return _FALLBACK_FLAG


def lookup_countries(hosts: list[str]) -> dict[str, str]:
    unique_hosts = list(dict.fromkeys(h for h in hosts if h))
    result: dict[str, str] = {h: _FALLBACK_FLAG for h in unique_hosts}
    if not unique_hosts:
        return result

    session = requests.Session()
    for i in range(0, len(unique_hosts), BATCH_SIZE):
        chunk = unique_hosts[i:i + BATCH_SIZE]
        try:
            resp = session.post(BATCH_URL, json=[{"query": h} for h in chunk], timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue
        for host, entry in zip(chunk, data):
            if isinstance(entry, dict) and entry.get("status") == "success":
                result[host] = country_code_to_flag(entry.get("countryCode", ""))
    return result
