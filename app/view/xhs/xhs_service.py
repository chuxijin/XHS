# coding: utf-8
"""小红书业务层 —— 账号管理、模板、配置、历史、登录"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from ...common.setting import DATA_DIR, launch_browser

XHS_URL = "https://creator.xiaohongshu.com/"
ACCOUNTS_DIR = DATA_DIR / "accounts" / "xhs"


# ---- 账号管理 ----

def get_accounts() -> list[str]:
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        d.name for d in ACCOUNTS_DIR.iterdir()
        if d.is_dir() and (d / "session.json").exists()
    )


def account_exists(name: str) -> bool:
    return (ACCOUNTS_DIR / name / "session.json").exists()


def get_account_dir(name: str) -> Path:
    return ACCOUNTS_DIR / name


# ---- 发布配置（多配置管理）----

CONFIGS_DIR = DATA_DIR / "configs" / "xhs"

DEFAULT_CONFIG = {
    "topics": [],
    "collection": "",
    "group_chat": "",
}


def get_config_names() -> list[str]:
    """返回所有已保存的配置名称"""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(
        f.stem for f in CONFIGS_DIR.glob("*.json")
    )


def load_publish_config(name: str) -> dict:
    """读取指定名称的配置"""
    config_path = CONFIGS_DIR / f"{name}.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return {**DEFAULT_CONFIG, **data}
        except (json.JSONDecodeError, ValueError):
            pass
    return dict(DEFAULT_CONFIG)


def save_publish_config(name: str, config: dict):
    """保存配置"""
    CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
    config_path = CONFIGS_DIR / f"{name}.json"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def delete_publish_config(name: str):
    """删除配置"""
    config_path = CONFIGS_DIR / f"{name}.json"
    if config_path.exists():
        config_path.unlink()


# ---- 标题 / 正文生成 ----

def compose_title(template_data: dict) -> str:
    today = datetime.now().strftime("%#m.%d") if sys.platform == "win32" \
        else datetime.now().strftime("%-m.%d")
    company = template_data.get("{{公司简称}}", "")
    job = template_data.get("{{岗位名称}}", "")
    return f"{today} 【{company}】新开【{job}】岗位"


def compose_body(template_data: dict) -> str:
    duties = template_data.get("{{岗位职责内容}}", "")
    requirements = template_data.get("{{岗位需求内容}}", "")
    parts = []
    if duties:
        parts.append(f"岗位职责：\n{duties}")
    if requirements:
        parts.append(f"\n岗位需求：\n{requirements}")
    return "\n".join(parts)


# ---- 历史记录 ----

def save_history(account_dir: Path, template_name: str,
                 replacements: dict, status: str, error: str = "",
                 max_records: int = 200):
    history_path = account_dir / "history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            history = []
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "template": template_name,
        "replacements": replacements,
        "status": status,
        "error": error,
    })
    history = history[-max_records:]
    history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def load_history(account_dir: Path) -> list[dict]:
    history_path = account_dir / "history.json"
    if not history_path.exists():
        return []
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


# ---- Playwright: 登录线程 ----

class XhsLoginThread(QThread):
    loginSuccess = Signal(str)
    loginFailed = Signal(str)

    def __init__(self, account_name: str, parent=None):
        super().__init__(parent)
        self.account_name = account_name
        self.account_dir = ACCOUNTS_DIR / account_name
        self.session_path = self.account_dir / "session.json"

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._login())
        except Exception as e:
            self.loginFailed.emit(str(e))
        finally:
            loop.close()

    async def _login(self):
        self.account_dir.mkdir(parents=True, exist_ok=True)

        async with async_playwright() as p:
            browser = await launch_browser(p)
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()
            try:
                await page.goto(XHS_URL)
            except Exception:
                pass

            max_wait = 180
            elapsed = 0
            while elapsed < max_wait:
                try:
                    url = page.url
                    if "/creator" in url and "login" not in url:
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
                elapsed += 1
            else:
                await browser.close()
                self.loginFailed.emit("登录超时，请重试")
                return

            await context.storage_state(path=str(self.session_path))
            await browser.close()
            self.loginSuccess.emit(self.account_name)
