#!/usr/bin/env python3
"""
mitmproxy addon — 只抓 tts_optimize speaker，不存其他垃圾数据。
"""
import json
import os
from datetime import datetime
from mitmproxy import http

LOG_DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(LOG_DIR, "sami_captured_speakers.log")


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Extractor:
    def response(self, flow: http.HTTPFlow):
        host = flow.request.pretty_host or ""
        if "slardar-bd.feishu.cn" not in host and "zijieapi.com" not in host:
            return
        try:
            text = flow.response.get_text()
        except Exception:
            return
        if not text or "tts_optimize" not in text:
            return

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return

        batches = data.get("data", [data] if isinstance(data, dict) else [])
        if not isinstance(batches, list):
            return

        for batch in batches:
            if not isinstance(batch, dict):
                continue
            for evt in batch.get("events", []):
                if evt.get("event") != "tts_optimize":
                    continue
                params_str = evt.get("params", "{}")
                try:
                    params = json.loads(params_str)
                except json.JSONDecodeError:
                    continue
                speaker = params.get("speaker", "")
                res_id = params.get("res_id", "")
                status = params.get("status", "")
                if speaker:
                    log(f"★★★ SPEAKER: {speaker}  |  res_id: {res_id}  |  status: {status}")


addons = [Extractor()]
