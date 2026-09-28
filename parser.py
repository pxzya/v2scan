"""
parser.py
Extracts and decodes v2ray-family share links (vless, vmess, trojan, ss, socks)
from raw Telegram message text/HTML and pulls out (host, port) so they can be
latency-tested.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote

LINK_RE = re.compile(
    r"(vless|vmess|trojan|ss|socks5|socks)://[^\s<>\"'`]+",
    re.IGNORECASE,
)


@dataclass
class VpnConfig:
    protocol: str
    raw: str
    host: str
    port: int
    remark: str = ""
    fingerprint: str = field(default="", repr=False)

    def __post_init__(self):
        self.fingerprint = f"{self.protocol}|{self.host}|{self.port}"


def _b64_pad(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def _safe_b64decode(s: str) -> Optional[bytes]:
    s = s.strip()
    for variant in (s, s.replace("-", "+").replace("_", "/")):
        try:
            return base64.b64decode(_b64_pad(variant))
        except (binascii.Error, ValueError):
            continue
    return None


def _parse_vmess(link: str) -> Optional[VpnConfig]:
    payload = link[len("vmess://"):]
    decoded = _safe_b64decode(payload)
    if decoded is None:
        return None
    try:
        data = json.loads(decoded.decode("utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return None
    host = data.get("add")
    port = data.get("port")
    if not host or not port:
        return None
    try:
        port = int(port)
    except (TypeError, ValueError):
        return None
    return VpnConfig(
        protocol="vmess",
        raw=link,
        host=str(host),
        port=port,
        remark=str(data.get("ps", "")),
    )


def _parse_generic_uri(protocol: str, link: str) -> Optional[VpnConfig]:
    try:
        parsed = urlparse(link)
    except ValueError:
        return None
    host = parsed.hostname
    port = parsed.port
    if not host or not port:
        return None
    remark = unquote(parsed.fragment or "")
    return VpnConfig(protocol=protocol, raw=link, host=host, port=port, remark=remark)


def _parse_ss(link: str) -> Optional[VpnConfig]:
    body = link[len("ss://"):]
    frag = ""
    if "#" in body:
        body, frag = body.split("#", 1)
    remark = unquote(frag)

    if "@" in body:
        cred_part, hostport = body.rsplit("@", 1)
        decoded = _safe_b64decode(cred_part)
        if decoded is not None:
            hostport = hostport.split("/")[0]
            if ":" in hostport:
                host, port_s = hostport.rsplit(":", 1)
                try:
                    return VpnConfig("ss", link, host, int(port_s), remark)
                except ValueError:
                    return None
        else:
            return _parse_generic_uri("ss", link)

    decoded = _safe_b64decode(body)
    if decoded is None:
        return None
    text = decoded.decode("utf-8", errors="ignore")
    m = re.search(r"@([^/:@]+):(\d+)", text)
    if not m:
        return None
    return VpnConfig("ss", link, m.group(1), int(m.group(2)), remark)


def parse_link(link: str) -> Optional[VpnConfig]:
    link = link.strip()
    proto = link.split("://", 1)[0].lower()
    try:
        if proto == "vmess":
            return _parse_vmess(link)
        if proto == "ss":
            return _parse_ss(link)
        if proto in ("vless", "trojan", "socks5", "socks"):
            return _parse_generic_uri(proto, link)
    except Exception:
        return None
    return None


def extract_configs(text: str) -> list[VpnConfig]:
    found = []
    for match in LINK_RE.finditer(text):
        cfg = parse_link(match.group(0))
        if cfg:
            found.append(cfg)
    return found
