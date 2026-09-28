"""
proxy_links.py
Parses Telegram proxy share links: MTProto (tg://proxy, t.me/proxy) and
SOCKS5 (tg://socks, t.me/socks). MTProto proxies only speak Telegram's own
protocol and can't be used as a generic HTTP/SOCKS proxy for scraping.
SOCKS5 proxies can, and are turned into a requests-compatible proxy URL.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qs

PROXY_LINK_RE = re.compile(
    r"(?:https?://t\.me/(?:proxy|socks)\?[^\s<>\"'`]+|tg://(?:proxy|socks)\?[^\s<>\"'`]+)",
    re.IGNORECASE,
)


@dataclass
class TelegramProxy:
    kind: str          # "mtproto" or "socks5"
    raw: str
    host: str
    port: int
    secret: str = ""
    user: str = ""
    password: str = ""
    remark: str = ""

    @property
    def protocol(self) -> str:
        return self.kind

    @property
    def fingerprint(self) -> str:
        return f"{self.kind}|{self.host}|{self.port}"

    def as_requests_proxy_url(self) -> Optional[str]:
        if self.kind != "socks5":
            return None
        auth = f"{self.user}:{self.password}@" if self.user or self.password else ""
        return f"socks5h://{auth}{self.host}:{self.port}"


def parse_proxy_link(link: str) -> Optional[TelegramProxy]:
    link = link.strip()
    try:
        parsed = urlparse(link)
    except ValueError:
        return None

    is_proxy = "/proxy" in parsed.path or parsed.path == "proxy" or (parsed.netloc == "proxy")
    is_socks = "/socks" in parsed.path or parsed.path == "socks" or (parsed.netloc == "socks")
    if not is_proxy and not is_socks:
        return None

    q = parse_qs(parsed.query)
    server = q.get("server", [None])[0]
    port = q.get("port", [None])[0]
    if not server or not port:
        return None
    try:
        port = int(port)
    except ValueError:
        return None

    if is_proxy:
        secret = q.get("secret", [""])[0]
        return TelegramProxy(kind="mtproto", raw=link, host=server, port=port, secret=secret)
    else:
        user = q.get("user", [""])[0]
        password = q.get("pass", [""])[0]
        return TelegramProxy(kind="socks5", raw=link, host=server, port=port, user=user, password=password)


def extract_proxy_links(text: str) -> list[TelegramProxy]:
    found = []
    for match in PROXY_LINK_RE.finditer(text):
        p = parse_proxy_link(match.group(0))
        if p:
            found.append(p)
    return found
