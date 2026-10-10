#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""剪映「贴纸」接口客户端（艺术家素材域 /artist/v1/…）。

参考 subtitle_highlight.py 的伪造调用方式：
  - 纯标准库，无第三方依赖
  - 用最小可用请求头直连剪映素材网关，无需登录态
  - 关键词 → 贴纸列表；可导出成 config/sticker.json 兼容结构

抓包得到的接口（剪映专业版 Mac v10.4.0）：
    POST https://lv-api-sinfonlinea.ulikecam.com/artist/v1/effect/search
    POST https://lv-api-sinfonlinea.ulikecam.com/artist/v1/effect/get_search_words
    POST https://lv-api-sinfonlinea.ulikecam.com/artist/v1/effect/get_suggest_words
    POST https://lv-api-sinfonlinea.ulikecam.com/artist/v1/panel/get_panel_info
    POST https://lv-api-sinfonlinea.ulikecam.com/artist/v1/effect/get_resources_by_category_id

    ⚠️ panel/get_panel_info 有必填字段 `panel` + `panel_source`（值 "default" / "heycan"），
       缺任一即 ret=1000 invalid parameter。这两个值是从 get_resources_by_category_id
       的抓包原文里学到的 —— 该接口的空 query 版本能通，但 panel 接口认这两个字段。

鉴权要点（重放 + 最小化实验结论，详见 docs/sticker-api.md）：
    - content-type: application/json  —— 唯一必需项，缺失返回 ret=2008
    - user-agent / x-ss-stub / cookie / tdid / 全部 URL query —— 均可省略
    - 该域比「智能划重点」的 lv-pc-api-sinfonlinea 更宽松，无需伪装 UA
    - 返回的 cover_url / item_urls / download_info 为带签名 CDN 地址，有时效，需即时下载

注意：本域是 `lv-api-sinfonlinea.ulikecam.com`，
      与「智能划重点」的 `lv-pc-api-sinfonlinea.ulikecam.com` **不是同一个域**。
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

try:
    from utils.config import CONFIG
except Exception:  # 允许作为独立脚本直接运行
    class _FallbackConfig:
        tts_insecure_ssl = True

    CONFIG = _FallbackConfig()


# --------------------------------------------------------------------------- #
# 常量
# --------------------------------------------------------------------------- #
STICKER_HOST = "https://lv-api-sinfonlinea.ulikecam.com"

EFFECT_SEARCH_URL = f"{STICKER_HOST}/artist/v1/effect/search"
SEARCH_WORDS_URL = f"{STICKER_HOST}/artist/v1/effect/get_search_words"
SUGGEST_WORDS_URL = f"{STICKER_HOST}/artist/v1/effect/get_suggest_words"
PANEL_INFO_URL = f"{STICKER_HOST}/artist/v1/panel/get_panel_info"
RESOURCES_BY_CATEGORY_URL = (
    f"{STICKER_HOST}/artist/v1/effect/get_resources_by_category_id"
)

APP_ID = 3704
EFFECT_TYPE_STICKER = 2  # 2 = 贴纸（同一套接口换 effect_type 可服务其它特效）

# 素材面板的两个必填标识（来自 get_resources_by_category_id 抓包原文）
# 缺失会导致 get_panel_info 返回 ret=1000 invalid parameter
DEFAULT_PANEL = "default"
DEFAULT_PANEL_SOURCE = "heycan"

# 抓包原样保留的环境 query（实测服务端不校验，可用 --no-query 一键去掉）
DEFAULT_QUERY_PARAMS = urllib.parse.urlencode(
    {
        "channel": "App Store",
        "version_name": "10.4.0",
        "opengl_version": "3.0",
        "aid": "3704",
        "effect_sdk_version": "21.1.0",
        "version_code": "10.4.0",
        "device_platform": "mac",
        "device_info": json.dumps(
            {
                "cpu": "Apple M2 Pro",
                "gpu": "Apple M2 Pro",
                "nv_driver_branch_version": "",
                "os_version": "14.8.9",
                "pc_gl_driver_version": "",
                "pc_gl_vendor": "Apple",
                "pc_gl_version": "3.0",
                "version_code": "656384",
            },
            separators=(",", ":"),
        ),
        "region": "CN",
        "subdivision_id": "",
        "device_id": "2285265576813817",
        "gpu": "Apple M2 Pro",
        "version_code_num": "656384",
        "biz_id": "2",
        "language": "zh-Hans",
        "cpu": "Apple M2 Pro",
        "device_type": "arm64",
    }
)

DEFAULT_USER_AGENT = (
    "Cronet/TTNetVersion:906739f5 2024-12-18 QuicVersion:55af8b7a 2024-11-18"
)

# 该域实际只需要 content-type；其余仅在显式传入时才附带
_BASE_HEADERS = {"content-type": "application/json", "charset": "utf-8"}


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Sticker:
    """单条贴纸（对应接口 effect_item_list[i]）。"""

    id: str = ""
    title: str = ""
    cover_url: str = ""
    item_url: str = ""          # 原始资源地址（item_urls[0]）
    download_url: str = ""      # download_info.url（hd 1920）
    download_format: str = ""
    md5: str = ""
    aspect_ratio: float = 1.0
    sticker_type: int = 0
    track_thumbnail: str = ""   # 列表缩略图（jianying config 用这个）
    large_image_url: str = ""
    author_name: str = ""
    author_uid: str = ""
    category_ids: List[Any] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "Sticker":
        attr = item.get("common_attr") or {}
        sticker = item.get("sticker") or {}
        author = item.get("author") or {}
        cover = attr.get("cover_url") or {}
        item_urls = attr.get("item_urls") or []
        dl = attr.get("download_info") or {}
        large = sticker.get("large_image") or {}

        return cls(
            id=str(attr.get("id") or attr.get("effect_id") or ""),
            title=attr.get("title", "") or attr.get("description", ""),
            cover_url=cover.get("static_img") or cover.get("small") or "",
            item_url=item_urls[0] if item_urls else "",
            download_url=dl.get("url", ""),
            download_format=dl.get("format", ""),
            md5=attr.get("md5", ""),
            aspect_ratio=float(attr.get("aspect_ratio") or 1.0),
            sticker_type=int(sticker.get("sticker_type") or 0),
            track_thumbnail=sticker.get("track_thumbnail", ""),
            large_image_url=large.get("image_url", ""),
            author_name=author.get("name", ""),
            author_uid=str(author.get("uid", "")),
            category_ids=list(attr.get("category_ids") or []),
            raw=item,
        )

    def best_url(self) -> str:
        """优先取高清（1920），退化到原始资源地址。"""
        return self.download_url or self.item_url or self.large_image_url

    def as_config_entry(self) -> Dict[str, Any]:
        """转成 config/sticker.json 的条目结构（sticker_id / title / sticker）。"""
        return {
            "sticker": self.raw.get("sticker") or {
                "large_image": {"image_url": self.large_image_url},
                "preview_cover": "",
                "sticker_type": self.sticker_type,
                "track_thumbnail": self.track_thumbnail,
            },
            "sticker_id": self.id,
            "title": self.title,
        }


@dataclass
class SearchResult:
    ok: bool
    ret: str = ""
    errmsg: str = ""
    logid: str = ""
    items: List[Sticker] = field(default_factory=list)
    next_offset: int = 0
    has_more: bool = False
    search_id: str = ""
    related_words: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    def titles(self) -> List[str]:
        return [s.title for s in self.items]

    def ids(self) -> List[str]:
        return [s.id for s in self.items]

    def config_entries(self) -> List[Dict[str, Any]]:
        return [s.as_config_entry() for s in self.items]


@dataclass
class HotWordsResult:
    ok: bool
    ret: str = ""
    errmsg: str = ""
    default_word: str = ""
    recommend_words: List[str] = field(default_factory=list)
    hot_words: List[str] = field(default_factory=list)
    grey_words: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SuggestResult:
    ok: bool
    ret: str = ""
    errmsg: str = ""
    sug_words: List[str] = field(default_factory=list)
    highlights: Dict[str, List[Dict[str, int]]] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PanelCategory:
    """面板分类导航的一项。"""

    category_id: int = 0
    category_key: str = ""
    category_name: str = ""
    is_top: bool = False
    is_vip: bool = False
    category_source: int = 0
    icon: str = ""
    selected_icon: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_item(cls, item: Dict[str, Any]) -> "PanelCategory":
        return cls(
            category_id=int(item.get("category_id") or 0),
            category_key=str(item.get("category_key") or ""),
            category_name=item.get("category_name", ""),
            is_top=bool(item.get("category_is_top")),
            is_vip=bool(item.get("category_is_vip")),
            category_source=int(item.get("category_source") or 0),
            icon=item.get("category_icon", ""),
            selected_icon=item.get("category_selected_icon", ""),
            raw=item,
        )


@dataclass
class PanelResult:
    ok: bool
    ret: str = ""
    errmsg: str = ""
    categories: List[PanelCategory] = field(default_factory=list)
    version_code: str = ""
    panel_source: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    def names(self) -> List[str]:
        return [c.category_name for c in self.categories]

    def find(self, name_or_key: str) -> Optional["PanelCategory"]:
        """按名称（可模糊，如「中秋」）或 category_key 找分类。"""
        for c in self.categories:
            if c.category_key == name_or_key or c.category_name == name_or_key:
                return c
        for c in self.categories:
            if name_or_key and name_or_key in c.category_name:
                return c
        return None


# --------------------------------------------------------------------------- #
# 传输层
# --------------------------------------------------------------------------- #
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


def _post_json(
    url: str,
    payload: Dict[str, Any],
    *,
    query_params: Optional[str] = DEFAULT_QUERY_PARAMS,
    timeout: float = 30.0,
    device_id: str = "",
    user_agent: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> str:
    """POST 一个 JSON body，返回响应文本（自动 gunzip）。"""
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    full_url = f"{url}?{query_params}" if query_params else url

    headers = dict(_BASE_HEADERS)
    if user_agent:
        headers["user-agent"] = user_agent
    headers["accept-encoding"] = "gzip, deflate"
    if device_id:
        headers["tdid"] = device_id
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(full_url, data=body, headers=headers, method="POST")
    ctx = _ssl_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return _decode(resp.read(), resp.headers.get("content-encoding"))
    except urllib.error.HTTPError as e:
        return _decode(e.read(), e.headers.get("content-encoding"))


def _loads(text: str) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------- #
# 1. 搜索主接口
# --------------------------------------------------------------------------- #
def _build_search_body(
    query: str,
    *,
    count: int,
    offset: int,
    search_id: str,
    sticker_type: int,
) -> Dict[str, Any]:
    """与抓包原文保持一致（字段顺序/默认值都对齐剪映 10.4.0）。"""
    return {
        "app_id": APP_ID,
        "count": count,
        "effect_type": EFFECT_TYPE_STICKER,
        "filter_optional": {
            "filter_paid_type": [],
            "filter_uncommercial": False,
            "no_copyrighted": False,
            "no_tuchong_order": False,
            "only_enterprise_commercial": False,
        },
        "need_recommend": False,
        "offset": offset,
        "pack_optional": {
            "fav_scene": None,
            "image_pack_param": None,
            "large_image_formats": [],
            "need_collection_id": False,
            "need_contract": True,
            "need_favorite_info": False,
            "need_operation_tag": False,
            "need_parent_tag": False,
            "need_tag": False,
            "need_thumb": False,
            "only_commercial": False,
            "tag_one_level": None,
        },
        "query": query,
        "replicate_sdk_version": "",
        "search_id": search_id,
        "search_option": {
            "aspect_ratio": "",
            "category_list": [],
            "effect_segment_type": None,
            "filter_uncommercial": False,
            "scene": "",
            "sticker_type": sticker_type,
        },
        "statistics_optional": {
            "need_add_count": False,
            "need_favorite_count": False,
            "need_usage_count": False,
        },
    }


def search_stickers(
    query: str,
    *,
    count: int = 50,
    offset: int = 0,
    search_id: str = "",
    sticker_type: int = 0,
    timeout: float = 30.0,
    query_params: Optional[str] = DEFAULT_QUERY_PARAMS,
    device_id: str = "",
    user_agent: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> SearchResult:
    """按关键词搜索贴纸（effect/search）。

    :param query: 关键词，如「中秋」
    :param count: 每页数量
    :param offset: 翻页偏移（0 → 50 → 100…）；翻页时把上次的 search_id 回填
    :param sticker_type: 贴纸类型筛选，0 = 不限
    """
    payload = _build_search_body(
        query, count=count, offset=offset, search_id=search_id, sticker_type=sticker_type
    )
    text = _post_json(
        EFFECT_SEARCH_URL,
        payload,
        query_params=query_params,
        timeout=timeout,
        device_id=device_id,
        user_agent=user_agent,
        extra_headers=extra_headers,
    )
    data = _loads(text)
    if data is None:
        return SearchResult(ok=False, errmsg=text[:200])

    d = data.get("data") or {}
    ret = str(data.get("ret", ""))
    return SearchResult(
        ok=(ret == "0"),
        ret=ret,
        errmsg=data.get("errmsg", ""),
        logid=data.get("logid", ""),
        items=[Sticker.from_item(i) for i in (d.get("effect_item_list") or [])],
        next_offset=int(d.get("next_offset") or 0),
        has_more=bool(d.get("has_more")),
        search_id=d.get("search_id", ""),
        related_words=[w if isinstance(w, str) else w.get("word", "")
                       for w in (d.get("related_words") or [])],
        raw=data,
    )


async def search_stickers_async(query: str, **kwargs) -> SearchResult:
    """search_stickers 的异步封装，便于嵌入 async 流水线。"""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: search_stickers(query, **kwargs))


def search_all(
    query: str,
    *,
    limit: int = 100,
    page_size: int = 50,
    max_pages: int = 10,
    **kwargs,
) -> SearchResult:
    """自动翻页，累计到 limit 条或没有更多为止（合并为单个 SearchResult）。"""
    merged = SearchResult(ok=False, raw={})
    offset, search_id = 0, ""
    for _ in range(max_pages):
        page = search_stickers(
            query, count=page_size, offset=offset, search_id=search_id, **kwargs
        )
        if not page.ok:
            if not merged.items:
                return page
            break
        if not merged.items:  # 首页的元信息作为整体元信息
            merged.ok, merged.ret, merged.errmsg = page.ok, page.ret, page.errmsg
            merged.logid, merged.search_id = page.logid, page.search_id
            merged.related_words = page.related_words
        merged.items.extend(page.items)
        merged.has_more = page.has_more
        merged.next_offset = page.next_offset
        offset, search_id = page.next_offset, page.search_id
        if not page.has_more or len(merged.items) >= limit or not page.items:
            break
    merged.items = merged.items[:limit]
    return merged


# --------------------------------------------------------------------------- #
# 2. 热词 / 联想词 / 分类
# --------------------------------------------------------------------------- #
def hot_words(
    *,
    timeout: float = 30.0,
    query_params: Optional[str] = DEFAULT_QUERY_PARAMS,
    **kwargs,
) -> HotWordsResult:
    """搜索框为空时的「大家都在搜」+ 热词。"""
    payload = {"app_id": APP_ID, "effect_type": EFFECT_TYPE_STICKER}
    text = _post_json(
        SEARCH_WORDS_URL, payload, query_params=query_params, timeout=timeout, **kwargs
    )
    data = _loads(text)
    if data is None:
        return HotWordsResult(ok=False, errmsg=text[:200])

    d = data.get("data") or {}
    ret = str(data.get("ret", ""))

    def _words(key: str) -> List[str]:
        out = []
        for w in d.get(key) or []:
            out.append(w if isinstance(w, str) else w.get("word", ""))
        return out

    return HotWordsResult(
        ok=(ret == "0"),
        ret=ret,
        errmsg=data.get("errmsg", ""),
        default_word=d.get("default_word", ""),
        recommend_words=list(d.get("recommend_words") or []),
        hot_words=_words("hot_words"),
        grey_words=_words("grey_words"),
        raw=data,
    )


def suggest_words(
    query: str,
    *,
    count: int = 5,
    sticker_type: int = 0,
    timeout: float = 30.0,
    query_params: Optional[str] = DEFAULT_QUERY_PARAMS,
    **kwargs,
) -> SuggestResult:
    """输入过程中的联想词。"""
    payload = {
        "app_id": APP_ID,
        "count": count,
        "effect_type": EFFECT_TYPE_STICKER,
        "query": query,
        "search_option": {"sticker_type": sticker_type},
    }
    text = _post_json(
        SUGGEST_WORDS_URL, payload, query_params=query_params, timeout=timeout, **kwargs
    )
    data = _loads(text)
    if data is None:
        return SuggestResult(ok=False, errmsg=text[:200])

    d = data.get("data") or {}
    ret = str(data.get("ret", ""))
    words, highlights = [], {}
    for w in d.get("sug_words") or []:
        word = w.get("words", "")
        words.append(word)
        highlights[word] = list(w.get("highlight") or [])
    return SuggestResult(
        ok=(ret == "0"),
        ret=ret,
        errmsg=data.get("errmsg", ""),
        sug_words=words,
        highlights=highlights,
        raw=data,
    )


def panel_categories(
    *,
    panel: str = DEFAULT_PANEL,
    panel_source: str = DEFAULT_PANEL_SOURCE,
    effect_type: int = EFFECT_TYPE_STICKER,
    timeout: float = 30.0,
    query_params: Optional[str] = DEFAULT_QUERY_PARAMS,
    extra_body: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> PanelResult:
    """贴纸面板分类导航（热门/中秋/国庆/hajimi…，实测 43 个分类）。

    ⚠️ 必填字段是 `panel` + `panel_source`，缺任一即 `ret=1000 invalid parameter`。
       这两个值来自 `get_resources_by_category_id` 的抓包原文，
       最小可用 body 只需 `{"app_id":3704,"panel":"default","panel_source":"heycan"}`。
    """
    body: Dict[str, Any] = {
        "app_id": APP_ID,
        "effect_type": effect_type,
        "panel": panel,
        "panel_source": panel_source,
    }
    if extra_body:
        body.update(extra_body)

    text = _post_json(
        PANEL_INFO_URL, body, query_params=query_params, timeout=timeout, **kwargs
    )
    data = _loads(text)
    if data is None:
        return PanelResult(ok=False, errmsg=text[:200])

    d = data.get("data") or {}
    ret = str(data.get("ret", ""))
    return PanelResult(
        ok=(ret == "0"),
        ret=ret,
        errmsg=data.get("errmsg", ""),
        categories=[PanelCategory.from_item(c) for c in (d.get("categories") or [])],
        version_code=str(d.get("version_code") or ""),
        panel_source=d.get("panel_source", ""),
        raw=data,
    )


def browse_category(
    *,
    category_id: int,
    category_key: str = "",
    count: int = 50,
    offset: int = 0,
    full_count: bool = False,
    timeout: float = 30.0,
    query_params: Optional[str] = DEFAULT_QUERY_PARAMS,
    extra_body: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> SearchResult:
    """按分类浏览（get_resources_by_category_id），返回结构与搜索一致。

    body 字段与抓包原文对齐（含 `panel` / `panel_source` / `full_count` / `request_id`）。
    """
    payload: Dict[str, Any] = {
        "app_id": APP_ID,
        "category_id": category_id,
        "category_key": category_key,
        "count": count,
        "filter_optional": {
            "filter_paid_type": [],
            "filter_uncommercial": False,
            "no_copyrighted": False,
            "no_tuchong_order": False,
            "only_enterprise_commercial": False,
        },
        "full_count": full_count,
        "offset": offset,
        "pack_optional": {
            "fav_scene": None,
            "image_pack_param": None,
            "large_image_formats": [],
            "need_collection_id": False,
            "need_contract": False,
            "need_favorite_info": True,
            "need_operation_tag": False,
            "need_parent_tag": False,
            "need_tag": False,
            "need_thumb": False,
            "only_commercial": False,
            "tag_one_level": None,
        },
        "panel": DEFAULT_PANEL,
        "panel_source": DEFAULT_PANEL_SOURCE,
        "replicate_sdk_version": "",
        "request_id": "",
        "statistics_optional": {
            "need_add_count": False,
            "need_favorite_count": False,
            "need_usage_count": False,
        },
    }
    if extra_body:
        payload.update(extra_body)

    text = _post_json(
        RESOURCES_BY_CATEGORY_URL,
        payload,
        query_params=query_params,
        timeout=timeout,
        **kwargs,
    )
    data = _loads(text)
    if data is None:
        return SearchResult(ok=False, errmsg=text[:200])

    d = data.get("data") or {}
    ret = str(data.get("ret", ""))
    return SearchResult(
        ok=(ret == "0"),
        ret=ret,
        errmsg=data.get("errmsg", ""),
        logid=data.get("logid", ""),
        items=[Sticker.from_item(i) for i in (d.get("effect_item_list") or [])],
        next_offset=int(d.get("next_offset") or 0),
        has_more=bool(d.get("has_more")),
        search_id=d.get("search_id", ""),
        raw=data,
    )


def browse_by_name(
    name_or_key: str,
    *,
    count: int = 50,
    offset: int = 0,
    **kwargs,
) -> SearchResult:
    """按分类中文名（如「中秋」）或 key 直接浏览：先查面板分类表，再拉资源。"""
    panel = panel_categories(timeout=kwargs.get("timeout", 30.0))
    if not panel.ok:
        return SearchResult(ok=False, ret=panel.ret, errmsg=f"panel error: {panel.errmsg}")
    cat = panel.find(name_or_key)
    if cat is None:
        return SearchResult(ok=False, errmsg=f"未找到分类 {name_or_key!r}")
    return browse_category(
        category_id=cat.category_id,
        category_key=cat.category_key,
        count=count,
        offset=offset,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# 落地：写入 config/sticker.json
# --------------------------------------------------------------------------- #
def dump_config(
    items: Iterable[Sticker],
    path: str,
    *,
    merge: bool = True,
) -> int:
    """把贴纸写成 config/sticker.json 兼容结构；merge=True 时按 sticker_id 去重合并。

    :return: 写回后文件内的总条数
    """
    new_entries = [s.as_config_entry() for s in items]
    existing: List[Dict[str, Any]] = []
    if merge and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f) or []
        except Exception:
            existing = []

    seen = {str(e.get("sticker_id")) for e in existing}
    for e in new_entries:
        if str(e.get("sticker_id")) not in seen:
            seen.add(str(e.get("sticker_id")))
            existing.append(e)

    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)
    return len(existing)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _print_search(result: SearchResult, limit: int) -> None:
    for i, s in enumerate(result.items[:limit]):
        print(f"  [{i:>3}] {s.id:<22} {s.title}")
        print(f"        cover : {s.cover_url[:96]}")
        print(f"        url   : {s.best_url()[:96]}")


def _main() -> int:
    parser = argparse.ArgumentParser(description="剪映贴纸接口调用（伪造客户端）")
    parser.add_argument("query", nargs="?", default="中秋", help="搜索关键词")
    parser.add_argument("--count", type=int, default=50, help="每页数量，默认 50")
    parser.add_argument("--offset", type=int, default=0, help="翻页偏移，默认 0")
    parser.add_argument("--pages", type=int, default=1, help="自动翻页页数，默认 1")
    parser.add_argument("--limit", type=int, default=20, help="打印条数上限，默认 20")
    parser.add_argument("--sticker-type", type=int, default=0, help="贴纸类型筛选，0=不限")
    parser.add_argument("--hot-words", action="store_true", help="改调热词接口")
    parser.add_argument("--suggest", metavar="KW", help="改调联想词接口")
    parser.add_argument("--categories", action="store_true", help="改调面板分类接口")
    parser.add_argument(
        "--browse",
        metavar="ID_OR_NAME",
        help="按分类浏览：可传 category_id（如 10515）或分类名（如 中秋）",
    )
    parser.add_argument("--save-config", metavar="PATH", help="结果写入 config JSON（去重合并）")
    parser.add_argument("--no-query", action="store_true", help="不带任何 URL query 参数")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON")
    args = parser.parse_args()

    qp = None if args.no_query else DEFAULT_QUERY_PARAMS

    # ---- 热词 ----
    if args.hot_words:
        r = hot_words(query_params=qp)
        if args.json:
            print(json.dumps(r.raw, ensure_ascii=False, indent=2))
            return 0 if r.ok else 1
        if not r.ok:
            print(f"[!] 失败 ret={r.ret} errmsg={r.errmsg}", file=sys.stderr)
            return 1
        print(f"[+] {r.default_word}")
        print(f"    recommend: {r.recommend_words}")
        print(f"    hot      : {r.hot_words}")
        return 0

    # ---- 联想词 ----
    if args.suggest is not None:
        r = suggest_words(args.suggest, query_params=qp)
        if args.json:
            print(json.dumps(r.raw, ensure_ascii=False, indent=2))
            return 0 if r.ok else 1
        if not r.ok:
            print(f"[!] 失败 ret={r.ret} errmsg={r.errmsg}", file=sys.stderr)
            return 1
        print(f"[+] 联想词（{args.suggest}）: {r.sug_words}")
        return 0

    # ---- 面板分类 ----
    if args.categories:
        r = panel_categories(query_params=qp)
        if args.json:
            print(json.dumps(r.raw, ensure_ascii=False, indent=2))
            return 0 if r.ok else 1
        if not r.ok:
            print(f"[!] 失败 ret={r.ret} errmsg={r.errmsg}", file=sys.stderr)
            return 1
        print(f"[+] 分类数: {len(r.categories)}  version_code={r.version_code}")
        for c in r.categories[: args.limit]:
            print(
                f"  {c.category_id:>10}  {c.category_key:<18} {c.category_name}"
                + ("  [VIP]" if c.is_vip else "")
            )
        return 0

    # ---- 分类浏览 ----
    if args.browse is not None:
        # 支持直接传分类名（如「中秋」）或 category_id
        if str(args.browse).isdigit():
            r = browse_category(
                category_id=int(args.browse),
                count=args.count,
                offset=args.offset,
                query_params=qp,
            )
        else:
            r = browse_by_name(str(args.browse), count=args.count, offset=args.offset)
        if args.json:
            print(json.dumps(r.raw, ensure_ascii=False, indent=2))
            return 0 if r.ok else 1
        if not r.ok:
            print(f"[!] 失败 ret={r.ret} errmsg={r.errmsg}", file=sys.stderr)
            return 1
        print(f"[+] 分类 {args.browse} 返回 {len(r.items)} 条（has_more={r.has_more}）")
        _print_search(r, args.limit)
        return 0

    # ---- 搜索（默认） ----
    if args.pages > 1:
        r = search_all(
            args.query,
            limit=args.count * args.pages,
            page_size=args.count,
            max_pages=args.pages,
            query_params=qp,
        )
    else:
        r = search_stickers(
            args.query,
            count=args.count,
            offset=args.offset,
            sticker_type=args.sticker_type,
            query_params=qp,
        )

    if args.json:
        print(json.dumps(r.raw, ensure_ascii=False, indent=2))
        return 0 if r.ok else 1

    if not r.ok:
        print(f"[!] 失败 ret={r.ret} errmsg={r.errmsg}", file=sys.stderr)
        return 1

    print(
        f"[+] query={args.query!r} 命中 {len(r.items)} 条  "
        f"next_offset={r.next_offset}  has_more={r.has_more}"
    )
    _print_search(r, args.limit)

    if args.save_config:
        total = dump_config(r.items, args.save_config)
        print(f"[+] 已写入 {args.save_config}（去重合并后共 {total} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
