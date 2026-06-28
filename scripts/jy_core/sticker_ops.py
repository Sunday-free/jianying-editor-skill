"""
JyProject 贴纸操作 Mixin
封装 pyJianYingDraft.StickerSegment 的创建、定位、关键帧动画
"""

import os
import json
from typing import Union, Optional, List, Tuple
import pyJianYingDraft as draft
from utils.formatters import safe_tim


class StickerOpsMixin:
    """
    贴纸相关操作：
    - add_sticker(): 通过 resource_id 添加贴纸到轨道
    - add_sticker_from_template(): 从模板草稿提取贴纸 resource_id 并添加
    - inspect_template_stickers(): 列出模板中所有贴纸元数据
    """

    def add_sticker(
        self,
        resource_id: str,
        start_time: Union[str, int] = None,
        duration: Union[str, int] = "3s",
        track_name: str = "StickerTrack",
        *,
        transform_x: float = 0.0,
        transform_y: float = 0.0,
        scale: float = 1.0,
        rotation: float = 0.0,
        opacity: float = 1.0,
    ) -> Optional[draft.StickerSegment]:
        """
        向指定轨道添加贴纸片段。

        Args:
            resource_id: 贴纸资源 ID，可通过 inspect_template_stickers() 获取
            start_time: 起始时间，默认追加到轨道末尾
            duration: 持续时长
            track_name: 目标轨道名称
            transform_x: X 轴偏移 (-1.0 ~ 1.0，0 为居中)
            transform_y: Y 轴偏移 (-1.0 ~ 1.0，0 为居中)
            scale: 缩放比例 (1.0 = 原始大小)
            rotation: 旋转角度（度）
            opacity: 不透明度 (0.0 ~ 1.0)

        Returns:
            StickerSegment 对象，失败返回 None
        """
        if start_time is None:
            start_time = self.get_track_duration(track_name)

        # 贴纸轨道必须位于最顶层（高于字幕 text=15000），手动指定 absolute_index
        self._ensure_track(draft.TrackType.sticker, track_name, absolute_index=20000)

        clip_settings = draft.ClipSettings(
            transform_x=transform_x,
            transform_y=transform_y,
            scale_x=scale,
            scale_y=scale,
            rotation=rotation,
            alpha=opacity,
        )

        seg = draft.StickerSegment(
            resource_id=str(resource_id),
            target_timerange=draft.Timerange(safe_tim(start_time), safe_tim(duration)),
            clip_settings=clip_settings,
        )

        self.script.add_segment(seg, track_name)
        return seg

    def add_sticker_with_keyframes(
        self,
        resource_id: str,
        start_time: Union[str, int] = None,
        duration: Union[str, int] = "3s",
        track_name: str = "StickerTrack",
        *,
        keyframes: Optional[List[Tuple[str, float, float]]] = None,
    ) -> Optional[draft.StickerSegment]:
        """
        添加带关键帧动画的贴纸。

        Args:
            resource_id: 贴纸资源 ID
            start_time: 起始时间
            duration: 持续时长
            track_name: 轨道名称
            keyframes: 关键帧列表，每项为 (property_type, time_offset_seconds, value)
                      例如 [("position_x", 0.0, -0.5), ("position_x", 2.0, 0.5)]
                      表示贴纸从左边移动到右边

        Returns:
            StickerSegment 对象
        """
        seg = self.add_sticker(resource_id, start_time, duration, track_name)
        if seg is None or keyframes is None:
            return seg

        # 关键帧通过 common_keyframes 添加到 segment 上
        if keyframes:
            if not hasattr(seg, "common_keyframes") or seg.common_keyframes is None:
                seg.common_keyframes = []

            PROP_MAP = {
                "position_x": "KFTypePositionX",
                "position_y": "KFTypePositionY",
                "scale": "KFTypeScale",
                "rotation": "KFTypeRotation",
                "alpha": "KFTypeAlpha",
            }

            for prop, offset_sec, value in keyframes:
                prop_type = PROP_MAP.get(prop, prop)
                kf = draft.KeyframeProperty(
                    property_type=prop_type,
                    time_offset=int(offset_sec * 1_000_000),  # 微秒
                    value=value,
                )
                seg.common_keyframes.append(kf)

        return seg

    def inspect_template_stickers(self, template_name: str) -> List[dict]:
        """
        从模板草稿中提取所有贴纸素材的元数据。

        Args:
            template_name: 模板草稿名称

        Returns:
            贴纸元数据列表，每项含 resource_id 和 name
        """
        draft_path = os.path.join(self.root, template_name)
        content_path = os.path.join(draft_path, "draft_content.json")
        if not os.path.exists(content_path):
            print(f"⚠️ Template draft not found: {template_name}")
            return []

        with open(content_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        stickers = []
        materials = data.get("materials", {})
        sticker_mats = materials.get("stickers", [])

        for mat in sticker_mats:
            stickers.append({
                "resource_id": mat.get("resource_id", mat.get("sticker_id", "")),
                "name": mat.get("name", ""),
                "type": mat.get("type", "sticker"),
            })

        # 也检查视频素材中的贴纸类型
        for mat in materials.get("videos", []):
            if mat.get("type") == "sticker":
                stickers.append({
                    "resource_id": mat.get("resource_id", mat.get("sticker_id", "")),
                    "name": mat.get("name", ""),
                    "type": "sticker",
                })

        return stickers

    def add_sticker_from_template(
        self,
        template_name: str,
        start_time: Union[str, int] = None,
        track_name: str = "StickerTrack",
    ) -> Optional[draft.StickerSegment]:
        """
        从模板草稿提取第一个贴纸并添加到当前工程。

        这是一个便捷方法，适合只有一个贴纸的模板。

        Args:
            template_name: 模板草稿名称
            start_time: 起始时间
            track_name: 目标轨道名称

        Returns:
            StickerSegment 对象
        """
        stickers = self.inspect_template_stickers(template_name)
        if not stickers:
            print(f"⚠️ No stickers found in template: {template_name}")
            return None

        first = stickers[0]
        print(f"🎯 Adding sticker: {first['name']} (resource_id: {first['resource_id']})")
        return self.add_sticker(first["resource_id"], start_time, track_name=track_name)
