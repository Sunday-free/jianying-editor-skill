"""
Mac 剪映草稿协议适配器：修复 draft_info.json 中缺失的 Mac 必要字段。

背景：
  Mac 版剪映 (5.9+) 使用 draft_info.json 格式，对素材字段有更严格要求：
  - local_material_id：必须为 32 位大写十六进制（uuid4 hex）
  - check_flag：视频 63487 / 音频 1
  - video_algorithm / matting：缺少这两个字段会导致剪映直接闪退（segfault）
  
  pyJianYingDraft 生成的草稿默认使用通用格式，在 Windows 上正常，
  但在 Mac 上会因缺少上述字段而出现"媒体丢失"或闪退。
"""

import json
import os
import uuid
from typing import Any, Dict, List, Optional


def _generate_local_material_id() -> str:
    """生成 32 位大写十六进制 local_material_id"""
    return uuid.uuid4().hex.upper()


def _patch_video_material(mat: Dict[str, Any]) -> None:
    """修复视频素材的 Mac 必需字段"""
    # 1) local_material_id：必须是非空的 32 位大写十六进制
    if not mat.get("local_material_id"):
        mat["local_material_id"] = _generate_local_material_id()

    # 2) check_flag：视频必须为 63487
    if mat.get("check_flag") != 63487:
        mat["check_flag"] = 63487

    # 3) video_algorithm：缺失会导致 segfault
    if "video_algorithm" not in mat:
        mat["video_algorithm"] = {
            "algorithms": [],
            "complement_frame_config": None,
            "deflicker": None,
            "gameplay_configs": [],
            "motion_blur_config": None,
            "noise_reduction": None,
            "path": "",
            "quality_enhance": None,
            "time_range": None,
        }

    # 4) matting：缺失也可能导致闪退
    if "matting" not in mat:
        mat["matting"] = {
            "flag": 0,
            "has_adjustment": False,
            "matting_type": 0,
        }

    # 5) media_path（部分版本需要）
    if "media_path" not in mat:
        mat["media_path"] = ""


def _patch_audio_material(mat: Dict[str, Any]) -> None:
    """修复音频素材的 Mac 必需字段"""
    # check_flag：Mac 音频通常为 1（Windows 上可能是 3，都可以）
    # 这里只修补缺失的情况
    if "check_flag" not in mat:
        mat["check_flag"] = 1

    # local_material_id
    if not mat.get("local_material_id"):
        mat["local_material_id"] = _generate_local_material_id()


def patch_draft_for_mac(draft_path: str) -> bool:
    """
    修复指定草稿目录的 draft_info.json，补充 Mac 必需字段。

    支持 draft_info.json 和 draft_content.json 两种文件名。

    Args:
        draft_path: 草稿目录的绝对路径

    Returns:
        True 表示已修补，False 表示未能找到草稿文件
    """
    # 查找草稿内容文件
    content_file: Optional[str] = None
    for filename in ("draft_info.json", "draft_content.json"):
        candidate = os.path.join(draft_path, filename)
        if os.path.exists(candidate):
            content_file = candidate
            break

    if not content_file:
        print(f"  [Mac Patcher] 草稿文件不存在于 {draft_path}")
        return False

    try:
        with open(content_file, "r", encoding="utf-8") as f:
            content = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [Mac Patcher] 读取草稿失败: {e}")
        return False

    materials: Dict[str, List[Dict[str, Any]]] = content.get("materials", {})
    patched_count = 0

    # 修复视频素材
    for video in materials.get("videos", []):
        _patch_video_material(video)
        patched_count += 1

    # 修复音频素材
    for audio in materials.get("audios", []):
        _patch_audio_material(audio)
        patched_count += 1

    # 写回
    try:
        with open(content_file, "w", encoding="utf-8") as f:
            json.dump(content, f, ensure_ascii=False, indent=4)
    except OSError as e:
        print(f"  [Mac Patcher] 写回草稿失败: {e}")
        return False

    print(f"  [Mac Patcher] 已修复 {patched_count} 个素材 ({os.path.basename(content_file)})")
    return True
