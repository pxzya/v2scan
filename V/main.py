"""
main.py
Entry point for V2Scan.

Window chrome notes:
Dragging and resizing this frameless window are done entirely through
pywebview's own documented, stable API (window.x/y/width/height,
window.move(), window.resize()), driven by JS mouse-tracking in
gui/app.js. easy_drag is never used -- combining frameless=True with
easy_drag=True is a known pywebview bug on the Windows WinForms backend
(easy_drag continuously recalculates window bounds on every mouse-move,
which collides with Windows' own accessibility layer doing the same on a
frameless window, causing a RecursionError). vibrancy is never set on
Windows either (it's macOS-only) -- the frosted-glass look is plain CSS
backdrop-filter blur in gui/style.css.

Maximize uses pywebview's native window.maximize() to enter (respects the
taskbar correctly), but restore does NOT use the paired window.restore() --
api.py captures the exact pre-maximize rect itself and restores it with
explicit resize()+move() calls instead, which is what actually fixes
"maximize again doesn't return to the original size".
"""
from __future__ import annotations

import os
import sys

import webview

from api import Api


def resource_path(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


def main():
    api = Api()

    window = webview.create_window(
        title="V2Scan",
        url=resource_path("gui/index.html"),
        js_api=api,
        width=1180,
        height=760,
        min_size=(860, 560),
        frameless=True,
        easy_drag=False,
        vibrancy=False,
        background_color="#1c1c1e",
        resizable=True,
    )
    api.set_window(window)

    webview.start(debug=False)


if __name__ == "__main__":
    main()
