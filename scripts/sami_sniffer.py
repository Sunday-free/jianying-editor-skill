#!/usr/bin/env python3
"""
mitmproxy addon — intercept JianyingPro SAMI TTS WebSocket traffic.

Start:  mitmdump -s sami_sniffer.py --set flow_detail=4
Then:   configure macOS system proxy to 127.0.0.1:8080 (HTTP + HTTPS)
        select a voice in JianyingPro and generate TTS
        speaker values will be printed and saved.

If the app does NOT respect system proxy, you must use
SOCKS/tun-based tools (like Surge, Clash, or mitmproxy in transparent mode).
"""

import json
import os
import re
import sys
import time
from datetime import datetime

from mitmproxy import ctx, http, websocket

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
CAPTURE_LOG = os.path.join(LOG_DIR, "sami_captured_speakers.log")


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _log(msg: str):
    ts = _now()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(CAPTURE_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _is_sami(flow) -> bool:
    """Check if the connection is the SAMI TTS endpoint."""
    if not flow or not flow.request:
        return False
    host = flow.request.pretty_host or ""
    path = flow.request.path or ""
    return "sami.bytedance.com" in host and "/internal/api/v2/ws" in path


def _extract_speaker(payload: str) -> str | None:
    """Try to pull 'speaker' from a JSON payload."""
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    # Direct field
    s = data.get("speaker")
    if isinstance(s, str) and s:
        return s

    # Nested in payload.*.speaker
    inner = data.get("payload")
    if isinstance(inner, str):
        try:
            inner = json.loads(inner)
        except json.JSONDecodeError:
            return None
    if isinstance(inner, dict):
        s = inner.get("speaker")
        if isinstance(s, str) and s:
            return s

    return None


class SamiSniffer:
    def request(self, flow: http.HTTPFlow) -> None:
        if _is_sami(flow):
            _log(f"[*] SAMI connection upgrade → {flow.request.pretty_url}")
            _log(f"    Headers: {dict(flow.request.headers)}")

    def websocket_start(self, flow: http.HTTPFlow) -> None:
        if _is_sami(flow):
            _log("[*] WebSocket handshake completed — listening...")

    def websocket_message(self, flow: http.HTTPFlow) -> None:
        """Capture every WS message — texts are JSON commands,
        binary blobs are audio data."""
        if not _is_sami(flow):
            return

        msg = flow.websocket.messages[-1]
        if msg is None:
            return

        direction = "→ SAMI" if msg.from_client else "← SAMI"
        is_text = not msg.is_text  # is_text means binary in mitmproxy model...

        content = msg.content
        if isinstance(content, bytes):
            try:
                content = content.decode("utf-8", errors="replace")
            except Exception:
                size = len(msg.content) if msg.content else 0
                _log(f"[audio] {direction} {size} bytes")
                return

        _log(f"[text] {direction}  {content[:600]}")

        speaker = _extract_speaker(content)
        if speaker:
            _log(f"")
            _log(f"  ★★★ SPEAKER: {speaker} ★★★")
            _log(f"")


addons = [SamiSniffer()]
