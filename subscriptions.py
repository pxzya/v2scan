"""
subscriptions.py
A "subscription" link is a URL that returns either a base64 blob decoding
to newline-separated share links, or plain-text share links directly. Both
are handled automatically. Clash/sing-box YAML subscriptions are not
supported -- only the raw share-link style.
"""
from __future__ import annotations

import base64
import binascii

import requests

from parser import extract_configs, VpnConfig
from proxy_links import extract_proxy_links, TelegramProxy

REQUEST_TIMEOUT = 12
USER_AGENT = "v2rayN/6.23"


class SubscriptionError(Exception):
    pass


def _try_b64_decode(body: str) -> str:
    stripped = body.strip()
    padded = stripped + "=" * (-len(stripped) % 4)
    try:
        decoded = base64.b64decode(padded, validate=False)
        text = decoded.decode("utf-8", errors="ignore")
        if any(scheme in text for scheme in ("vless://", "vmess://", "trojan://", "ss://", "socks")):
            return text
    except (binascii.Error, ValueError):
        pass
    return body


def fetch_subscription(url: str, timeout: float = REQUEST_TIMEOUT) -> tuple[list[VpnConfig], list[TelegramProxy]]:
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
    except requests.RequestException as e:
        raise SubscriptionError(f"Couldn't fetch subscription: {e}") from e

    body = _try_b64_decode(resp.text)
    configs = extract_configs(body)
    proxies = extract_proxy_links(body)

    seen = set()
    unique_configs = []
    for c in configs:
        if c.fingerprint not in seen:
            seen.add(c.fingerprint)
            unique_configs.append(c)

    return unique_configs, proxies
