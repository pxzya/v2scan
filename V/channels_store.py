"""
channels_store.py
Persists the user's saved list of Telegram channels to a small JSON file
next to the executable (portable -- no registry, no AppData).
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class SavedChannel:
    username: str
    label: str = ""


class ChannelStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._channels: list[SavedChannel] = []
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            self._channels = []
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self._channels = [SavedChannel(**item) for item in raw]
        except (json.JSONDecodeError, TypeError, OSError):
            self._channels = []

    def _save(self):
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump([asdict(c) for c in self._channels], f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self.path)

    def list(self) -> list[dict]:
        with self._lock:
            return [asdict(c) for c in self._channels]

    def add(self, username: str, label: str = "") -> dict:
        username = username.strip().lstrip("@")
        with self._lock:
            for c in self._channels:
                if c.username.lower() == username.lower():
                    raise ValueError(f"'{username}' is already saved.")
            ch = SavedChannel(username=username, label=label.strip())
            self._channels.append(ch)
            self._save()
            return asdict(ch)

    def edit(self, username: str, new_label: Optional[str] = None, new_username: Optional[str] = None) -> dict:
        username = username.strip().lstrip("@")
        with self._lock:
            for c in self._channels:
                if c.username.lower() == username.lower():
                    if new_label is not None:
                        c.label = new_label.strip()
                    if new_username is not None:
                        c.username = new_username.strip().lstrip("@")
                    self._save()
                    return asdict(c)
            raise ValueError(f"'{username}' isn't in the saved list.")

    def remove(self, username: str):
        username = username.strip().lstrip("@")
        with self._lock:
            before = len(self._channels)
            self._channels = [c for c in self._channels if c.username.lower() != username.lower()]
            if len(self._channels) == before:
                raise ValueError(f"'{username}' isn't in the saved list.")
            self._save()
