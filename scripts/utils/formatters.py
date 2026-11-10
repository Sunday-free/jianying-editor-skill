import difflib
import functools
import os
import re
import subprocess
from typing import Dict, List, Optional, Union

DRAFT_CONTENT_FILENAMES = ("draft_info.json", "draft_content.json")


def find_draft_content_path(draft_path: str) -> Optional[str]:
    """Return the current draft content JSON path, supporting v5.9+ and legacy drafts."""
    for filename in DRAFT_CONTENT_FILENAMES:
        content_path = os.path.join(draft_path, filename)
        if os.path.exists(content_path):
            return content_path
    return None


# ----------------- 路径自动探测 -----------------
def _is_confirmed_draft_root(path: str) -> bool:
    """剪映会在草稿根目录放 root_meta_info.json（或 .recycle_bin），据此确认。

    安装器顺手建的 `JianyingPro Drafts` 空目录不算 —— 否则会当成草稿根往里面写。
    """
    if not os.path.isdir(path):
        return False
    return (os.path.isfile(os.path.join(path, "root_meta_info.json"))
            or os.path.isdir(os.path.join(path, ".recycle_bin")))


def _has_draft_children(path: str) -> bool:
    """目录下是否真的有草稿子文件夹。

    ★ 重装 / 换安装盘后会出现「空壳根」：旧根里只剩 root_meta_info.json +
      .recycle_bin，而新草稿已经落到另一个盘（实测 C 盘 com.lveditor.draft 空、
      D 盘 JianyingPro Drafts 里有草稿）。生成草稿若写进空壳根，剪映列表里看不到。
    """
    try:
        for name in os.listdir(path):
            sub = os.path.join(path, name)
            if name.startswith(".") or not os.path.isdir(sub):
                continue
            for fn in ("draft_content.json", "draft_info.json", "draft_meta_info.json"):
                if os.path.isfile(os.path.join(sub, fn)):
                    return True
    except OSError:
        return False
    return False


def _jianying_registry_draft_path() -> Optional[str]:
    """草稿根**真源**：剪映「设置 → 草稿位置」记录在 HKCU 注册表里（Windows）。

    ★ 比枚举盘符/目录名可靠得多：用户把草稿目录改到任意位置都能直接拿到。
    """
    import sys as _sys

    if _sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Bytedance\JianyingPro\GlobalSettings\History",
        ) as key:
            for name in ("currentCustomDraftPath", "draftPath", "draft_path"):
                try:
                    value = winreg.QueryValueEx(key, name)[0]
                except OSError:
                    continue
                if isinstance(value, str) and value.strip():
                    path = os.path.normpath(value.strip())
                    if os.path.isdir(path):
                        return path
    except Exception:  # noqa: BLE001 —— 没装剪映 / 非 Windows 都走这里
        return None
    return None


def get_default_drafts_root() -> str:
    """自动探测剪映草稿目录 (Windows / macOS 跨平台)

    ★ 2026-11：安装位置与草稿位置都不再只有系统盘默认那一处。剪映允许把草稿
      目录改到别的盘（实测重装到 D 盘后出现
      `D:\\AppStoreSoftstore\\Install\\JianyingPro Drafts`）。
      顺序：注册表真源 → 「真的有草稿」的候选 → 「剪映认过的」候选 → 存在的候选。
      先挑真源/有草稿的，避免选中空壳根导致生成的草稿在剪映列表里看不到。
    """
    import sys as _sys

    if _sys.platform == "win32":
        reg_root = _jianying_registry_draft_path()
        if reg_root:
            return reg_root

    candidates = []

    if _sys.platform == "darwin":
        # ---- macOS ----
        home = os.path.expanduser("~")
        candidates.extend(
            [
                os.path.join(home, "Movies", "JianyingPro Drafts"),
                os.path.join(
                    home, "Movies", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"
                ),
                os.path.join(
                    home,
                    "Library",
                    "Containers",
                    "com.lemon.lvpro",
                    "Data",
                    "Library",
                    "Application Support",
                    "JianyingPro",
                    "User Data",
                    "Projects",
                    "com.lveditor.draft",
                ),
                os.path.join(
                    home,
                    "Library",
                    "Application Support",
                    "JianyingPro",
                    "User Data",
                    "Projects",
                    "com.lveditor.draft",
                ),
            ]
        )
        fallback = os.path.join(home, "Movies", "JianyingPro Drafts")
    else:
        # ---- Windows ----
        local_app_data = os.environ.get("LOCALAPPDATA")
        user_profile = os.environ.get("USERPROFILE")

        if local_app_data:
            candidates.extend(
                [
                    os.path.join(
                        local_app_data, "JianyingPro", "User Data", "Projects", "com.lveditor.draft"
                    ),
                    os.path.join(
                        local_app_data, "CapCut", "User Data", "Projects", "com.lveditor.draft"
                    ),
                ]
            )

        if user_profile:
            candidates.append(
                os.path.join(
                    user_profile,
                    "AppData",
                    "Local",
                    "JianyingPro",
                    "User Data",
                    "Projects",
                    "com.lveditor.draft",
                )
            )

        # 草稿目录被用户/安装器挪到其它盘（含商店类安装器落盘的 JianyingPro Drafts）
        for _letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            _drive = f"{_letter}:\\"
            if not os.path.exists(_drive):
                continue
            candidates.append(os.path.join(_drive, "JianyingPro Drafts"))
            candidates.append(
                os.path.join(_drive, "AppStoreSoftstore", "Install", "JianyingPro Drafts")
            )

        # ★ 不要写死 C:\Users\Administrator —— 客户机的用户名不是这个。
        fallback = os.path.join(
            local_app_data or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
            "JianyingPro",
            "User Data",
            "Projects",
            "com.lveditor.draft",
        )

    # ① 真的有草稿的根最优先（换盘 / 重装后旧根会剩空壳，写进去剪映看不到）
    for path in candidates:
        if _has_draft_children(path):
            return path
    # ② 其次才是「剪映认过的根」（刚装好、还没建草稿时走这条）
    for path in candidates:
        if _is_confirmed_draft_root(path):
            return path
    for path in candidates:
        if os.path.exists(path):
            return path
    return candidates[0] if candidates else fallback


def get_default_cache_root() -> str:
    """自动探测剪映特效缓存目录 (Windows / macOS 跨平台)。

    ★ 不能只从草稿根反推：用户可以把**草稿**目录改到别的盘（如 D 盘
      `JianyingPro Drafts`），而**缓存**仍留在 `<用户>\\AppData\\Local\\JianyingPro\\User Data\\Cache`，
      反推会得到一个不存在的 `D:\\...\\JianyingPro Drafts\\Cache`。
      所以先直接找 User Data\\Cache，找不到才退回「与草稿根同父级的 User Data」推导。
    """
    import sys as _sys

    if _sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            direct = os.path.join(local, "JianyingPro", "User Data", "Cache")
            if os.path.isdir(direct):
                return direct

    root = get_default_drafts_root()
    if "User Data" in root:
        base = root.rsplit("User Data", 1)[0] + "User Data"
        return os.path.join(base, "Cache")
    return os.path.join(root, "Cache")


def get_all_drafts(root_path: str = None) -> List[Dict]:
    """获取所有草稿并按修改时间排序"""
    root = root_path or get_default_drafts_root()
    drafts = []
    if not os.path.exists(root):
        return []

    for item in os.listdir(root):
        path = os.path.join(root, item)
        if os.path.isdir(path):
            if find_draft_content_path(path) or os.path.exists(
                os.path.join(path, "draft_meta_info.json")
            ):
                drafts.append({"name": item, "mtime": os.path.getmtime(path), "path": path})
    return sorted(drafts, key=lambda x: x["mtime"], reverse=True)


try:
    from pyJianYingDraft import tim
except ImportError:

    def tim(v):
        if isinstance(v, (int, float)):
            return int(v * 1000000)
        return 0


# ----------------- 时间与格式转换 -----------------
def safe_tim(inp: Union[str, int, float]) -> int:
    """
    增强版时间解析器，支持:
    1. 1h2m3s (底层库自带)
    2. 00:00:10 (冒号分隔格式)
    3. 10 (纯数字秒)
    """
    # 约定：
    # - int 统一视为“微秒”，避免 200000us 被误判为 200000s
    # - float 视为“秒”
    if isinstance(inp, int):
        return int(inp)
    if isinstance(inp, float):
        return int(inp * 1000000)

    if isinstance(inp, str) and ":" in inp:
        try:
            parts = inp.split(":")
            if len(parts) == 3:  # HH:MM:SS
                h, m, s = map(float, parts)
                return int((h * 3600 + m * 60 + s) * 1000000)
            elif len(parts) == 2:  # MM:SS
                m, s = map(float, parts)
                return int((m * 60 + s) * 1000000)
        except Exception:
            pass
    if isinstance(inp, str):
        s = inp.strip()
        # 支持显式单位组合: 1h2m3s500ms / 500ms / 200000us / 1m2.5s
        unit_pattern = re.compile(r"\s*(\d+(?:\.\d+)?)(ms|us|h|m|s)\s*", re.IGNORECASE)
        pos = 0
        total_us = 0.0
        unit_scale = {
            "h": 3600 * 1000000,
            "m": 60 * 1000000,
            "s": 1000000,
            "ms": 1000,
            "us": 1,
        }
        matches = list(unit_pattern.finditer(s))
        if matches:
            for match in matches:
                if match.start() != pos:
                    break
                value = float(match.group(1))
                unit = match.group(2).lower()
                total_us += value * unit_scale[unit]
                pos = match.end()
            if pos == len(s):
                return int(total_us)
        # 纯数字字符串按秒处理
        if s.replace(".", "", 1).isdigit():
            return int(float(s) * 1000000)
    return tim(inp)


def format_srt_time(us: int) -> str:
    """将微秒转换为 SRT 时间戳格式 (HH:MM:SS,mmm)"""
    ms = (us // 1000) % 1000
    s = (us // 1000000) % 60
    m = (us // 60000000) % 60
    h = us // 3600000000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ----------------- FFprobe 工具 -----------------


@functools.lru_cache(maxsize=128)
def get_duration_ffprobe_cached(file_path: str) -> float:
    """
    带缓存的 ffprobe 时长检测，防止重复开销。
    """
    file_path = os.path.abspath(file_path)
    if not os.path.exists(file_path):
        return 0.0
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            # ★ errors='replace'：中文 Windows 下 ffprobe 的输出可能是 UTF-8，
            #   按 GBK 解码会在线程里抛 UnicodeDecodeError（表现为时长静默变 0）。
            text=True,
            errors="replace",
            timeout=5,
        )
        return float(result.stdout.strip())
    except Exception as e:
        print(f"⚠️ ffprobe failed for {os.path.basename(file_path)}: {e}")
        return 0.0


# ----------------- Enum 模糊匹配 -----------------
def resolve_enum_with_synonyms(enum_cls, name: str, synonyms_dict: dict):
    """
    尝试从 Enum 类中找到匹配的属性。
    """
    if not name:
        return None

    if hasattr(enum_cls, name):
        return getattr(enum_cls, name)

    name_lower = name.lower()
    mapping = {k.lower(): k for k in enum_cls.__members__.keys()}

    if name_lower in mapping:
        real_key = mapping[name_lower]
        return getattr(enum_cls, real_key)

    for key, synonyms in synonyms_dict.items():
        if name_lower == key.lower():
            for candidate in synonyms:
                if candidate in mapping:
                    real_key = mapping[candidate]
                    print(f"ℹ️ Map EN->CN: '{name}' -> '{real_key}'")
                    return getattr(enum_cls, real_key)

        if key.lower() in mapping:
            for syn in synonyms:
                if syn in name_lower or name_lower in syn:
                    real_key = mapping[key.lower()]
                    print(f"ℹ️ Synonym Match: '{name}' -> '{real_key}'")
                    return getattr(enum_cls, real_key)

    matches = difflib.get_close_matches(name, enum_cls.__members__.keys(), n=1, cutoff=0.6)
    if matches:
        print(f"ℹ️ Fuzzy Match: '{name}' -> '{matches[0]}'")
        return getattr(enum_cls, matches[0])
    return None
