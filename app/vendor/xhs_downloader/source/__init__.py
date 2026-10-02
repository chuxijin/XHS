"""Vendored XHS-Downloader core.

当前项目只需要小红书解析/下载核心能力，不需要原项目的 CLI、TUI、API
入口。这里保持一个轻量导出，避免导入 textual/click 等界面模块。
"""

from .application import XHS

__all__ = [
    "XHS",
]
