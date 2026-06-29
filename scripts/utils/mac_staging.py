"""
Mac 剪映沙箱适配：将素材自动硬链接（或拷贝）到草稿目录的 assets/ 下。

背景：
  Mac 版剪映 (com.lemon.lvpro) 是沙箱应用，只能读取 ~/Movies/ 子树下的文件，
  即使给 Python/Terminal 授予"完全磁盘访问权限"也无效。软链接（symlink）不会被
  沙箱跟随，因此必须使用硬链接（同一 inode，是真正的文件入口）。

策略：
  1. 优先使用硬链接（不占额外空间）
  2. 跨卷时自动降级为 copy
  3. 目标路径：<draft_dir>/assets/<类型>/<原文件名>
     类型按文件扩展名分类：videos / images / audios
  4. 如果源文件已在 ~/Movies/ 下，直接返回原路径（零开销）
"""

import os
import shutil
import time


# 文件类型到子目录的映射
_EXT_TO_TYPE_DIR = {
    # 视频
    ".mp4": "assets/videos",
    ".mov": "assets/videos",
    ".avi": "assets/videos",
    ".mkv": "assets/videos",
    ".webm": "assets/videos",
    ".flv": "assets/videos",
    ".m4v": "assets/videos",
    ".ts": "assets/videos",
    # 图片
    ".jpg": "assets/images",
    ".jpeg": "assets/images",
    ".png": "assets/images",
    ".gif": "assets/images",
    ".webp": "assets/images",
    ".bmp": "assets/images",
    ".tiff": "assets/images",
    ".tif": "assets/images",
    # 音频
    ".wav": "assets/audios",
    ".mp3": "assets/audios",
    ".aac": "assets/audios",
    ".m4a": "assets/audios",
    ".flac": "assets/audios",
    ".ogg": "assets/audios",
    ".wma": "assets/audios",
    ".aiff": "assets/audios",
}


def _get_media_type_dir(media_path: str) -> str:
    """根据文件扩展名返回分类子目录路径"""
    ext = os.path.splitext(media_path)[1].lower()
    return _EXT_TO_TYPE_DIR.get(ext, "assets/others")


def _build_staging_path(media_path: str, draft_dir: str) -> str:
    """
    为素材文件构建分类 staging 目标路径。

    路径结构：<draft_dir>/assets/<videos|images|audios>/<原文件名>
    """
    basename = os.path.basename(media_path)
    type_dir = _get_media_type_dir(media_path)
    target_dir = os.path.join(draft_dir, type_dir)
    os.makedirs(target_dir, exist_ok=True)
    target = os.path.join(target_dir, basename)

    if os.path.exists(target):
        # 已存在的文件指向同一 inode，直接复用
        try:
            if os.path.samefile(media_path, target):
                return target
        except OSError:
            pass
        # 否则是旧残留，删除后重建
        os.remove(target)
        name, ext = os.path.splitext(basename)
        target = os.path.join(target_dir, f"{name}_{int(time.time() * 1000000)}{ext}")

    return target


def stage_for_mac(media_path: str, draft_dir: str) -> str:
    """
    将素材硬链接（或拷贝）到草稿目录的 assets/ 子目录下。

    优先使用硬链接，失败时降级为文件拷贝。如果源路径本身就在
    ~/Movies/ 下则直接返回。

    注意：不能使用软链接（symlink），剪映沙箱不会跟随软链接。
    """
    media_path = os.path.abspath(media_path)

    # 已在沙箱可见区内，无需处理
    movies_root = os.path.expanduser("~/Movies/")
    if media_path.startswith(movies_root):
        return media_path

    target = _build_staging_path(media_path, draft_dir)

    # 目标已存在且是最新的（源文件时间未变）
    if os.path.exists(target):
        src_mtime = os.path.getmtime(media_path)
        dst_mtime = os.path.getmtime(target)
        if src_mtime <= dst_mtime:
            return target
        # 源文件更新了，删除旧的重新 staging
        os.remove(target)

    # 1) 尝试硬链接
    try:
        os.link(media_path, target)
        print(f"  [Mac Staging] 硬链接: {os.path.basename(media_path)} → {target}")
        return target
    except OSError as e:
        print(f"  [Mac Staging] 硬链接失败 ({e})，降级为拷贝...")

    # 2) 降级为拷贝
    try:
        shutil.copy2(media_path, target)
        print(f"  [Mac Staging] 文件拷贝: {os.path.basename(media_path)} → {target}")
        return target
    except OSError as e:
        print(f"  [Mac Staging] 拷贝也失败了 ({e})，回退到原始路径（可能导致剪映素材丢失）")
        return media_path


def cleanup_staging_for_draft(draft_dir: str) -> None:
    """
    清理指定草稿的 assets staging 子目录。

    在草稿不再需要时调用，移除 assets/ 下的硬链接。
    """
    assets_dir = os.path.join(draft_dir, "assets")
    if os.path.exists(assets_dir):
        shutil.rmtree(assets_dir, ignore_errors=True)
        print(f"  [Mac Staging] 已清理 assets 目录: {assets_dir}")
