"""
平台检测工具，用于识别当前运行环境是否为 Mac。
Mac 版剪映有 App Sandbox 限制，只能读取 ~/Movies/ 目录下的文件，
因此需要额外的 staging 和协议适配逻辑。
"""

import sys


def is_mac() -> bool:
    """判断当前平台是否为 macOS"""
    return sys.platform == "darwin"
