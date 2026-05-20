# coding: utf-8
import os
import sys
from pathlib import Path

# change DEBUG to False if you want to compile the code to exe
DEBUG = "__compiled__" not in globals()

# 应用根目录：打包后为 exe 所在目录，开发时为项目根目录
if "__compiled__" in globals() or getattr(sys, 'frozen', False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).parent.parent

# 数据目录：统一存放到用户 AppData 下
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", APP_DIR)) / "AutoPublisher"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Playwright 浏览器路径：打包后 driver 会在自身目录下找 local-browsers，
# 必须显式指定到系统默认位置，确保 install 和 launch 使用同一路径
_local = os.environ.get("LOCALAPPDATA", "")
if _local:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH",
                          os.path.join(_local, "ms-playwright"))

YEAR = 2023
AUTHOR = "zhiyiYo"
VERSION = "v0.0.1"
APP_NAME = "AutoPublisher"
HELP_URL = "https://qfluentwidgets.com"
REPO_URL = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets"
FEEDBACK_URL = "https://github.com/zhiyiYo/PyQt-Fluent-Widgets/issues"
DOC_URL = "https://qfluentwidgets.com/"

CONFIG_FOLDER = DATA_DIR / "AppData"
CONFIG_FILE = CONFIG_FOLDER / "config.json"


async def launch_browser(playwright, *, headless=False):
    """启动 Chromium，未安装时给出简洁中文提示。"""
    try:
        return await playwright.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
    except Exception as e:
        msg = str(e)
        if "Executable doesn't exist" in msg or "playwright install" in msg:
            raise RuntimeError(
                "浏览器未安装，请在设置中点击「安装浏览器」") from None
        raise
