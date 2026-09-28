"""
api.py
The object exposed to the webview's JS side as `window.pywebview.api`.
This is a config *tester*: it scrapes/fetches, parses, and TCP-ping-tests
VLESS/VMess/Trojan/Shadowsocks/SOCKS5 configs and Telegram proxy links --
nothing here connects to anything as a VPN or touches system network
settings. Scanning runs on a background thread so the UI never blocks.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from typing import Optional

import webview  # provided by pywebview

import geo
from channels_store import ChannelStore
from proxy_links import parse_proxy_link
from scraper import scrape_channel, ChannelNotFound, ScraperNetworkError
from subscriptions import fetch_subscription, SubscriptionError
from tester import test_configs, TestResult

APP_TITLE = "V2Scan"


def _app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class Api:
    def __init__(self):
        self._window: Optional[webview.Window] = None
        self._stop_flag = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None

        base_dir = _app_base_dir()
        data_dir = os.path.join(base_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        self._channels = ChannelStore(os.path.join(data_dir, "channels.json"))

        self._is_maximized = False
        self._pre_maximize_rect: Optional[tuple] = None

        self._last_alive_items: list[dict] = []

    def set_window(self, window: webview.Window):
        self._window = window

    # ------------------------------------------------------------------
    # window chrome (drag/resize/maximize via pywebview's documented
    # window.x/y/width/height + move()/resize() API)
    # ------------------------------------------------------------------

    def get_window_geometry(self) -> dict:
        if not self._window:
            return {"x": 0, "y": 0, "width": 0, "height": 0}
        return {
            "x": self._window.x, "y": self._window.y,
            "width": self._window.width, "height": self._window.height,
        }

    def move_window(self, x: float, y: float):
        if self._window:
            self._window.move(int(x), int(y))

    def resize_and_move_window(self, x: float, y: float, width: float, height: float):
        if not self._window:
            return
        width = max(int(width), 360)
        height = max(int(height), 240)
        self._window.resize(width, height)
        self._window.move(int(x), int(y))

    def minimize(self):
        if self._window:
            self._window.minimize()

    def toggle_maximize(self):
        if not self._window:
            return
        if self._is_maximized:
            if self._pre_maximize_rect:
                x, y, w, h = self._pre_maximize_rect
                self._window.resize(w, h)
                self._window.move(x, y)
            self._is_maximized = False
        else:
            self._pre_maximize_rect = (
                self._window.x, self._window.y, self._window.width, self._window.height,
            )
            self._window.maximize()
            self._is_maximized = True

    def close(self):
        if self._window:
            self._window.destroy()

    # ------------------------------------------------------------------
    # channel list management
    # ------------------------------------------------------------------

    def list_channels(self) -> dict:
        return {"ok": True, "channels": self._channels.list()}

    def add_channel(self, username: str, label: str = "") -> dict:
        try:
            ch = self._channels.add(username, label)
            return {"ok": True, "channel": ch}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def edit_channel(self, username: str, new_label: Optional[str] = None, new_username: Optional[str] = None) -> dict:
        try:
            ch = self._channels.edit(username, new_label, new_username)
            return {"ok": True, "channel": ch}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def remove_channel(self, username: str) -> dict:
        try:
            self._channels.remove(username)
            return {"ok": True}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------
    # scan control
    # ------------------------------------------------------------------

    def start_scan(self, options: dict) -> dict:
        if self._scan_thread and self._scan_thread.is_alive():
            return {"ok": False, "error": "A scan is already running."}

        self._stop_flag.clear()
        self._scan_thread = threading.Thread(target=self._run_scan, args=(options,), daemon=True)
        self._scan_thread.start()
        return {"ok": True}

    def stop_scan(self) -> dict:
        self._stop_flag.set()
        return {"ok": True}

    def export_valid(self) -> dict:
        if not self._last_alive_items:
            return {"ok": False, "error": "No reachable configs from the last scan to export."}
        try:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename="v2scan_valid_configs.txt",
                file_types=("Text files (*.txt)",),
            )
        except Exception as e:
            return {"ok": False, "error": f"Couldn't open the save dialog: {e}"}
        if not result:
            return {"ok": False, "error": "cancelled"}
        path = result if isinstance(result, str) else result[0]
        try:
            with open(path, "w", encoding="utf-8") as f:
                for item in self._last_alive_items:
                    f.write(item["raw"] + "\n")
        except OSError as e:
            return {"ok": False, "error": f"Couldn't write file: {e}"}
        return {"ok": True, "path": path, "count": len(self._last_alive_items)}

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _emit(self, event: str, payload: dict):
        if not self._window:
            return
        safe_payload = json.dumps(payload)
        try:
            self._window.evaluate_js(f"window.__onNative && window.__onNative('{event}', {safe_payload})")
        except Exception:
            pass

    def _resolve_discovery_proxy_url(self, options: dict) -> Optional[str]:
        mode = options.get("discovery_mode", "direct")
        if mode == "direct":
            return None
        if mode != "proxy":
            raise ValueError(f"Unknown discovery mode: {mode!r}")

        proxy_url = (options.get("discovery_proxy_url") or "").strip()
        if not proxy_url:
            raise ValueError("No proxy given for proxy-based discovery.")

        parsed_tg = parse_proxy_link(proxy_url)
        if parsed_tg:
            requests_url = parsed_tg.as_requests_proxy_url()
            if requests_url:
                return requests_url
            raise ValueError(
                "That's an MTProto proxy link. MTProto only carries Telegram's own app "
                "protocol -- it can't be used to fetch the plain t.me web pages this app "
                "scrapes. Use a SOCKS Telegram proxy link or a plain socks5://host:port instead."
            )
        return proxy_url

    def _run_scan(self, options: dict):
        source = options.get("source", "channel")
        proxies_only = bool(options.get("proxies_only"))
        limit = int(options.get("limit") or 100)
        min_ping_enabled = bool(options.get("min_ping_enabled"))
        min_ping_ms = int(options.get("min_ping_ms") or 500)
        test_ip = (options.get("test_ip") or "").strip() or None
        timeout_s = float(options.get("timeout_s") or 3.0)

        try:
            requests_proxy_url = self._resolve_discovery_proxy_url(options)
        except ValueError as e:
            self._emit("scan_error", {"message": str(e)})
            return

        if source == "subscription":
            url = (options.get("subscription_url") or "").strip()
            if not url:
                self._emit("scan_error", {"message": "Enter a subscription URL first."})
                return
            self._emit("scan_started", {"channel": url, "limit": limit})
            try:
                configs, proxies = fetch_subscription(url)
            except SubscriptionError as e:
                self._emit("scan_error", {"message": str(e)})
                return
            items = proxies if proxies_only else configs
            items = items[:limit]
        else:
            channel = (options.get("channel") or "").strip()
            if not channel:
                self._emit("scan_error", {"message": "Enter a channel username first."})
                return
            self._emit("scan_started", {"channel": channel, "limit": limit})

            def on_scrape_progress(found: int, pages: int):
                self._emit("scrape_progress", {"found": found, "pages": pages})

            try:
                items = scrape_channel(
                    channel,
                    limit,
                    mode=("proxies" if proxies_only else "configs"),
                    requests_proxy_url=requests_proxy_url,
                    progress_cb=on_scrape_progress,
                    should_stop=self._stop_flag.is_set,
                )
            except ChannelNotFound:
                self._emit("scan_error", {"message": f"Channel '@{channel}' wasn't found or isn't public."})
                return
            except ScraperNetworkError as e:
                self._emit("scan_error", {"message": str(e)})
                return
            except Exception as e:
                self._emit("scan_error", {"message": f"Scraping failed: {e}"})
                return

        if self._stop_flag.is_set():
            self._emit("scan_stopped", {})
            return

        if not items:
            self._emit("scan_finished", {"tested": 0, "alive": 0})
            return

        self._emit("scrape_done", {"count": len(items)})

        hosts = [it.host for it in items]
        try:
            flags = geo.lookup_countries(hosts)
        except Exception:
            flags = {}

        self._last_alive_items = []

        def on_result(r: TestResult):
            item_dict = {
                "protocol": r.config.protocol,
                "host": r.config.host,
                "port": r.config.port,
                "remark": getattr(r.config, "remark", ""),
                "raw": r.config.raw,
                "flag": flags.get(r.config.host, "🌐"),
                "alive": r.alive,
                "ping_ms": r.ping_ms,
                "error": r.error,
            }
            if r.alive:
                self._last_alive_items.append(item_dict)
            self._emit("config_result", item_dict)

        try:
            results = asyncio.run(test_configs(
                items,
                override_ip=test_ip,
                timeout=timeout_s,
                min_ping_ms=(min_ping_ms if min_ping_enabled else None),
                on_result=on_result,
                should_stop=self._stop_flag.is_set,
            ))
        except Exception as e:
            self._emit("scan_error", {"message": f"Testing failed: {e}"})
            return

        alive_count = sum(1 for r in results if r.alive)
        if self._stop_flag.is_set():
            self._emit("scan_stopped", {"tested": len(results), "alive": alive_count})
        else:
            self._emit("scan_finished", {"tested": len(results), "alive": alive_count})
