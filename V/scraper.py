"""
scraper.py
Pulls messages from a *public* Telegram channel via the read-only web preview
at https://t.me/s/<channel>. No bot token, API ID, or login required.
Paginates backwards in time until enough items are collected or a safety
cap on pages is hit.

Supports two extraction modes:
  - "configs" (default): vless/vmess/trojan/ss/socks5 VPN share links
  - "proxies": Telegram MTProto/SOCKS proxy share links
and can optionally route the scraping HTTP requests themselves through a
SOCKS/HTTP proxy (requests_proxy_url), for when t.me is directly censored.
"""
from __future__ import annotations

import html
import re
import time
from typing import Callable, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from parser import VpnConfig, extract_configs
from proxy_links import TelegramProxy, extract_proxy_links

ScrapedItem = Union[VpnConfig, TelegramProxy]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

MESSAGE_BLOCK_RE = re.compile(
    r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL,
)
DATA_POST_RE = re.compile(r'data-post="[^/]+/(\d+)"')
TAG_RE = re.compile(r"<[^>]+>")

MAX_PAGES_SAFETY = 60
REQUEST_TIMEOUT = 10
PAGE_DELAY_SECONDS = 0.4

RETRY_TOTAL = 4
RETRY_BACKOFF = 0.6


class ChannelNotFound(Exception):
    pass


class ScraperNetworkError(Exception):
    """Raised with a specific, actionable message the caller can show
    directly to the user rather than a raw traceback."""
    pass


def _clean_username(raw: str) -> str:
    raw = raw.strip()
    raw = raw.removeprefix("https://t.me/").removeprefix("http://t.me/")
    raw = raw.removeprefix("@")
    return raw.strip("/")


def _strip_tags(block: str) -> str:
    block = block.replace("<br>", "\n").replace("<br/>", "\n")
    block = TAG_RE.sub(" ", block)
    return html.unescape(block)


def _build_session(requests_proxy_url: Optional[str]) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    retry = Retry(
        total=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    if requests_proxy_url:
        session.proxies.update({"http": requests_proxy_url, "https": requests_proxy_url})
    return session


def _get_with_clear_errors(session: requests.Session, url: str, using_proxy: bool):
    try:
        return session.get(url, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.InvalidSchema as e:
        if "SOCKS" in str(e):
            raise ScraperNetworkError(
                "That SOCKS proxy needs the PySocks package, which isn't installed. "
                "Run 'pip install -r requirements.txt' (or rebuild the .exe after that) and try again."
            ) from e
        raise ScraperNetworkError(str(e)) from e
    except requests.exceptions.SSLError as e:
        hint = (
            " This can happen under network-level interference with t.me itself -- "
            "try Discovery: Proxy with a working SOCKS proxy instead of Direct."
            if not using_proxy else ""
        )
        raise ScraperNetworkError(f"TLS connection to t.me failed.{hint} ({e})") from e
    except requests.exceptions.ProxyError as e:
        raise ScraperNetworkError(f"The proxy refused the connection or isn't reachable: {e}") from e
    except requests.exceptions.ConnectionError as e:
        hint = (
            " This can happen under network-level interference -- try Discovery: Proxy instead of Direct."
            if not using_proxy else " Double-check the proxy address/port."
        )
        raise ScraperNetworkError(f"Couldn't connect to t.me.{hint} ({e})") from e
    except requests.exceptions.Timeout as e:
        raise ScraperNetworkError(f"Request to t.me timed out: {e}") from e


def scrape_channel(
    username: str,
    limit: int,
    mode: str = "configs",
    requests_proxy_url: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> list[ScrapedItem]:
    if mode not in ("configs", "proxies"):
        raise ValueError(f"Unknown mode: {mode!r}")

    username = _clean_username(username)
    if not username:
        raise ValueError("Empty channel username.")

    session = _build_session(requests_proxy_url)
    extract = extract_configs if mode == "configs" else extract_proxy_links

    seen_fingerprints: set[str] = set()
    results: list[ScrapedItem] = []

    before_id: Optional[str] = None
    pages = 0
    saw_any_page = False

    while len(results) < limit and pages < MAX_PAGES_SAFETY:
        if should_stop and should_stop():
            break

        url = f"https://t.me/s/{username}"
        if before_id:
            url += f"?before={before_id}"

        resp = _get_with_clear_errors(session, url, using_proxy=bool(requests_proxy_url))
        if resp.status_code == 404:
            raise ChannelNotFound(username)
        resp.raise_for_status()
        page_html = resp.text
        saw_any_page = True
        pages += 1

        post_ids = DATA_POST_RE.findall(page_html)
        if not post_ids:
            break

        for block in MESSAGE_BLOCK_RE.findall(page_html):
            text = _strip_tags(block)
            for item in extract(text):
                if item.fingerprint not in seen_fingerprints:
                    seen_fingerprints.add(item.fingerprint)
                    results.append(item)
                    if len(results) >= limit:
                        break
            if len(results) >= limit:
                break

        if progress_cb:
            progress_cb(len(results), pages)

        oldest_id = min(int(i) for i in post_ids)
        if before_id is not None and str(oldest_id) == before_id:
            break
        before_id = str(oldest_id)

        time.sleep(PAGE_DELAY_SECONDS)

    if not saw_any_page:
        raise ChannelNotFound(username)

    return results[:limit]
