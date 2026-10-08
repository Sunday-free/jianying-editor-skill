#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剪映「智能划重点」接口客户端（audio_subtitle/highlight）。

参考 universal_tts.py 的伪造调用方式：
  - 读取本地剪映配置（device_id / iid，可选）
  - 用最小可用请求头直连剪映 PC 网关，无需登录态
  - 输入字幕文本列表 → 返回每句关键词及起止字符下标

抓包得到的接口（剪映 PC 端）：
    POST https://lv-pc-api-sinfonlinea.ulikecam.com/lv/v1/audio_subtitle/highlight
    入参:  {draft_id, language, scene, subtitle_list[]}
    返回:  {ret, errmsg, log_id, Data: {keyword[][], task_id}}

鉴权要点（重放实验结论）：
    - x-ss-stub = MD5(body)          —— 可自行计算
    - sign / sign-ver / cookie / tdid —— 均非必需，可省略
    - user-agent 必须为剪映客户端 UA（Cronet/TTNet…）；
      脚本类 UA（python-requests / urllib 默认）会被拒，返回 ret=1014 system busy
    - draft_id 可任意填写，不参与鉴权
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

try:
    from utils.config import CONFIG
except Exception:  # 允许作为独立脚本直接运行
    class _FallbackConfig:
        tts_insecure_ssl = True

    CONFIG = _FallbackConfig()


HIGHLIGHT_URL = (
    "https://lv-pc-api-sinfonlinea.ulikecam.com/lv/v1/audio_subtitle/highlight"
)

APP_ID = "3704"

# 剪映 PC 客户端 UA —— 接口会校验 UA，务必保留客户端特征
DEFAULT_USER_AGENT = (
    "Cronet/TTNetVersion:906739f5 2024-12-18 QuicVersion:55af8b7a 2024-11-18"
)

# 网关公共头（无 cookie/sign 时用于放行）
_BASE_HEADERS = {
    "appid": APP_ID,
    "appvr": "10.4.0",
    "pf": "3",
    "lan": "zh-hans",
    "loc": "cn",
    "ch": "App Store",
    "app-sdk-version": "48.0.0",
    "x-ss-dp": APP_ID,
}


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Keyword:
    keyword: str
    start_index: int
    end_index: int


@dataclass
class HighlightResult:
    ok: bool
    ret: str = ""
    errmsg: str = ""
    log_id: str = ""
    task_id: str = ""
    keywords: List[List[Keyword]] = field(default_factory=list)  # 与入参一一对应
    raw: Dict = field(default_factory=dict)

    def plain(self) -> List[List[str]]:
        """只要关键词文本，二维数组与入参句子一一对应。"""
        return [[k.keyword for k in group] for group in self.keywords]


# --------------------------------------------------------------------------- #
# 请求构造
# --------------------------------------------------------------------------- #
def _build_body(
    subtitle_list: Sequence[str],
    draft_id: str,
    language: str,
    scene: str,
) -> bytes:
    payload = {
        # 未显式指定时生成一个正常的 uuid4（大写，与剪映自身风格一致）
        "draft_id": draft_id or str(uuid.uuid4()).upper(),
        "language": language,
        "scene": scene,
        "subtitle_list": list(subtitle_list),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _build_headers(
    body: bytes,
    *,
    user_agent: Optional[str],
    device_id: str,
    extra_headers: Optional[Dict[str, str]],
) -> Dict[str, str]:
    headers = dict(_BASE_HEADERS)
    headers["content-type"] = "application/json"
    headers["user-agent"] = user_agent or DEFAULT_USER_AGENT
    headers["accept-encoding"] = "gzip, deflate"
    headers["x-ss-stub"] = hashlib.md5(body).hexdigest()  # 签名 = body 的 MD5
    if device_id:
        headers["tdid"] = device_id
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _ssl_context() -> ssl.SSLContext:
    if getattr(CONFIG, "tts_insecure_ssl", False):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


def _decode(raw: bytes, content_encoding: Optional[str]) -> str:
    if content_encoding and "gzip" in content_encoding.lower():
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def _post(url: str, headers: Dict[str, str], body: bytes, timeout: float) -> str:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    ctx = _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return _decode(resp.read(), resp.headers.get("content-encoding"))
    except urllib.error.HTTPError as e:
        return _decode(e.read(), e.headers.get("content-encoding"))


def _parse(text: str) -> HighlightResult:
    try:
        data = json.loads(text)
    except Exception:
        return HighlightResult(ok=False, errmsg=text[:200], raw={})

    d = data.get("Data") or {}
    groups: List[List[Keyword]] = []
    for group in d.get("keyword", []) or []:
        groups.append(
            [
                Keyword(
                    keyword=item.get("keyword", ""),
                    start_index=int(item.get("start_index", 0)),
                    end_index=int(item.get("end_index", 0)),
                )
                for item in group
            ]
        )

    ret = str(data.get("ret", ""))
    return HighlightResult(
        ok=(ret == "0"),
        ret=ret,
        errmsg=data.get("errmsg", ""),
        log_id=data.get("log_id", ""),
        task_id=d.get("task_id", ""),
        keywords=groups,
        raw=data,
    )


# --------------------------------------------------------------------------- #
# 公开 API
# --------------------------------------------------------------------------- #
def highlight(
    subtitle_list: Sequence[str],
    *,
    draft_id: str = "",
    language: str = "zh",
    scene: str = "common",
    user_agent: Optional[str] = DEFAULT_USER_AGENT,
    device_id: str = "",
    timeout: float = 30.0,
    extra_headers: Optional[Dict[str, str]] = None,
) -> HighlightResult:
    """对字幕列表做智能划重点。

    :param subtitle_list: 字幕分句文本，按顺序传入
    :param draft_id: 草稿 ID，可任意（不参与鉴权）；缺省自动生成 uuid4
    :param user_agent: 客户端 UA，默认剪映 Cronet UA
    :param device_id: 可选，写进 tdid 头
    :return: HighlightResult
    """
    body = _build_body(subtitle_list, draft_id, language, scene)
    headers = _build_headers(
        body, user_agent=user_agent, device_id=device_id, extra_headers=extra_headers
    )
    text = _post(HIGHLIGHT_URL, headers, body, timeout)
    return _parse(text)


async def highlight_async(
    subtitle_list: Sequence[str],
    **kwargs,
) -> HighlightResult:
    """highlight 的异步封装，便于嵌入 async 流水线（如 TTS pipeline）。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: highlight(subtitle_list, **kwargs))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _main() -> int:
    parser = argparse.ArgumentParser(description="剪映智能划重点接口调用")
    parser.add_argument(
        "texts",
        nargs="*",
        help="字幕文本（多句用空格分隔）；留空则使用内置示例",
    )
    parser.add_argument("--draft-id", default="", help="草稿 ID（缺省自动生成 uuid4）")
    parser.add_argument("--language", default="zh", help="语言，默认 zh")
    parser.add_argument("--scene", default="common", help="场景，默认 common")
    parser.add_argument("--ua", default=DEFAULT_USER_AGENT, help="User-Agent")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    texts = args.texts or [
        "今天A股放量大涨",
        "沪指重新站上三千四百点",
        "北向资金净买入五十亿",
        "你觉得明天会怎么走",
    ]

    result = highlight(
        texts,
        draft_id=args.draft_id,
        language=args.language,
        scene=args.scene,
        user_agent=args.ua,
    )

    if args.json:
        print(json.dumps(result.raw, ensure_ascii=False, indent=2))
        return 0 if result.ok else 1

    if not result.ok:
        print(f"[!] 失败 ret={result.ret} errmsg={result.errmsg}", file=sys.stderr)
        return 1

    print(f"[+] ret={result.ret} task_id={result.task_id}")
    for i, (sentence, group) in enumerate(zip(texts, result.keywords)):
        kws = [k.keyword for k in group]
        print(f"  [{i:>3}] {sentence}  ->  {kws}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
