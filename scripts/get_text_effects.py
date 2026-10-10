#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""花字效果（花字 / Flower Text）列表查询与标识符解析。

数据源：config/huazi.json —— 剪映花字面板抓取结果，结构为：
    [{"id": "<effect_id>", "title": "<中文名>", "is_vip": true|false}, ...]

对外 API（进程导入时一次性载入内存，之后按 effect_id / 中文名 O(1) 查找）：
    get_text_effects(mode=0)         -> [{"id", "title", "is_vip"}, ...]
    resolve_text_effect(identifier)  -> {"resource_id", "effect_id"} | None
        identifier 可以是 effect_id（数字串）或花字名称。

命令行：
    python scripts/get_text_effects.py                    # 列出全部花字
    python scripts/get_text_effects.py --mode 2           # 只看免费花字
    python scripts/get_text_effects.py --resolve 复古红蓝  # 名称 → effect_id
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

# 允许 `python scripts/get_text_effects.py` 直接运行（把 scripts/ 放进 sys.path 才能 import utils）
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from utils.errors import InfraError, UserInputError
from utils.logging_utils import setup_logger

logger = setup_logger("get_text_effects")

# 默认取 skill 根目录下的 config/huazi.json，可用 JY_HUAZI_CONFIG 指到别处
HUAZI_CONFIG_PATH = os.getenv("JY_HUAZI_CONFIG", "").strip() or os.path.join(
    os.path.dirname(_SCRIPTS_DIR), "config", "huazi.json"
)

# 进程启动时加载花字数据到内存
_HUAZI_DATA: List[Dict[str, Any]] = []
_HUAZI_MAP_BY_NAME: Dict[str, Dict[str, Any]] = {}
_HUAZI_MAP_BY_ID: Dict[str, Dict[str, Any]] = {}


def _normalize_item(item: Any) -> Optional[Dict[str, Any]]:
    """把 config 里的一条记录统一成 {"id", "title", "is_vip"}；无有效字段则丢弃。"""
    if not isinstance(item, dict):
        return None
    resource_id = str(item.get("id", "") or "").strip()
    title = str(item.get("title", "") or "").strip()
    if not resource_id and not title:
        return None
    return {"id": resource_id, "title": title, "is_vip": bool(item.get("is_vip", False))}


def _reset_data() -> None:
    global _HUAZI_DATA, _HUAZI_MAP_BY_NAME, _HUAZI_MAP_BY_ID
    _HUAZI_DATA = []
    _HUAZI_MAP_BY_NAME = {}
    _HUAZI_MAP_BY_ID = {}


def _load_huazi_data() -> None:
    """在进程启动时加载花字数据到内存（失败只清空缓存并记日志，不阻断导入）。"""
    global _HUAZI_DATA, _HUAZI_MAP_BY_NAME, _HUAZI_MAP_BY_ID

    try:
        with open(HUAZI_CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception as e:
        logger.error(f"加载花字数据失败: {e}（{HUAZI_CONFIG_PATH}）")
        _reset_data()
        return

    if not isinstance(raw, list):
        logger.error(f"花字数据格式错误，应为数组: {HUAZI_CONFIG_PATH}")
        _reset_data()
        return

    data: List[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in raw:
        effect = _normalize_item(item)
        if effect is None:
            continue
        data.append(effect)
        # 同名花字（配置里有 233 条重名）只保留首条，保证按名称查找结果稳定
        if effect["title"]:
            by_name.setdefault(effect["title"], effect)
        if effect["id"]:
            by_id[effect["id"]] = effect

    _HUAZI_DATA, _HUAZI_MAP_BY_NAME, _HUAZI_MAP_BY_ID = data, by_name, by_id
    logger.info(f"成功加载 {len(data)} 个花字效果到内存: {HUAZI_CONFIG_PATH}")


# 模块导入时自动加载数据
_load_huazi_data()


def resolve_text_effect(effect_identifier: str) -> Optional[Dict[str, Any]]:
    """
    解析花字效果标识符，返回对应的效果信息

    Args:
        effect_identifier: 可以是 effect_id（数字字符串）或效果名称（中文名称）

    Returns:
        花字效果信息字典，包含 effect_id 和 resource_id，如果未找到则返回 None
    """
    key = str(effect_identifier or "").strip()
    if not key:
        return None

    logger.debug(f"Resolving text effect: {key}")

    # 1. 先按 effect_id 查，再按中文名称查
    effect_data = _HUAZI_MAP_BY_ID.get(key) or _HUAZI_MAP_BY_NAME.get(key)
    if effect_data is not None:
        return {
            "resource_id": effect_data["id"],
            "effect_id": effect_data["id"],
        }

    # 2. 不在配置里但形如 effect_id 的纯数字串：信任透传（支持未登记花字）
    if key.isdigit():
        return {
            "resource_id": key,
            "effect_id": key,
        }

    # 3. 未找到
    logger.warning(f"Text effect not found: {key}")
    return None


def get_text_effects(mode: int = 0) -> List[Dict[str, Any]]:
    """
    获取花字效果列表

    Args:
        mode: 花字效果模式，0=所有，1=VIP，2=免费，默认值为 0

    Returns:
        text_effects: 花字效果对象数组

    Raises:
        UserInputError: mode 不在 0/1/2 之内
        InfraError: 获取花字效果列表失败
    """
    logger.info(f"get_text_effects called with mode: {mode}")

    try:
        # 1. 参数验证
        if mode not in (0, 1, 2):
            logger.error(f"Invalid mode: {mode}")
            raise UserInputError(f"mode 只支持 0(所有)/1(VIP)/2(免费)，收到: {mode!r}")

        # 2. 根据模式获取花字效果数据
        text_effects = _get_text_effects_by_mode(mode=mode)
        logger.info(f"Found {len(text_effects)} text effects for mode: {mode}")
        return text_effects

    except UserInputError:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in get_text_effects: {e}")
        raise InfraError(f"获取花字效果列表失败: {e}") from e


def _get_text_effects_by_mode(mode: int) -> List[Dict[str, Any]]:
    """
    根据模式获取对应的花字效果数据

    Args:
        mode: 花字效果模式（0=所有，1=VIP，2=免费）

    Returns:
        包含花字效果信息的列表
    """
    # 从内存中直接获取所有花字效果（按配置条目取，避免按名称去重漏条）
    all_text_effects = _HUAZI_DATA

    logger.info(f"Total text effects loaded from memory: {len(all_text_effects)}")

    if mode == 0:  # 所有
        result = all_text_effects
    elif mode == 1:  # VIP
        result = [f for f in all_text_effects if f["is_vip"]]
    elif mode == 2:  # 免费
        result = [f for f in all_text_effects if not f["is_vip"]]
    else:
        result = []

    logger.info(f"Final filtered result: {len(result)} text effects")
    # 返回副本，避免调用方改动污染进程内缓存
    return [dict(f) for f in result]


def _main() -> int:
    parser = argparse.ArgumentParser(description="花字效果列表查询 / 标识符解析")
    parser.add_argument("--mode", type=int, default=0, choices=[0, 1, 2],
                        help="0=所有，1=VIP，2=免费（默认 0）")
    parser.add_argument("--resolve", metavar="NAME_OR_ID",
                        help="解析花字名称或 effect_id，打印对应 effect_id")
    parser.add_argument("--limit", type=int, default=0, help="打印条数上限，0=全部")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if args.resolve:
        hit = resolve_text_effect(args.resolve)
        if hit is None:
            if args.json:
                print(json.dumps(None))
            else:
                print(f"[!] 未找到花字: {args.resolve}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(hit, ensure_ascii=False, indent=2))
        else:
            print(f"[+] {args.resolve} -> {hit['effect_id']}")
        return 0

    effects = get_text_effects(args.mode)
    if args.json:
        print(json.dumps(effects, ensure_ascii=False, indent=2))
        return 0

    print(f"[+] 花字 {len(effects)} 个（mode={args.mode}）")
    for effect in effects if args.limit <= 0 else effects[: args.limit]:
        tag = "[VIP] " if effect["is_vip"] else ""
        print(f"  {effect['id']:<22} {tag}{effect['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
