# coding: utf-8
import asyncio
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from ...common.setting import launch_browser

WECHAT_URL = "https://mp.weixin.qq.com/"


class WechatLoginThread(QThread):
    """在子线程中运行 Playwright 完成微信公众号登录"""

    loginSuccess = Signal(str)   # 账号名
    loginFailed = Signal(str)    # 错误信息

    def __init__(self, account_name: str, accounts_dir: Path, parent=None):
        super().__init__(parent)
        self.account_name = account_name
        self.account_dir = accounts_dir / account_name
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
        # 创建账号目录
        self.account_dir.mkdir(parents=True, exist_ok=True)
        (self.account_dir / "templates").mkdir(exist_ok=True)

        async with async_playwright() as p:
            browser = await launch_browser(p)
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()

            try:
                await page.goto(WECHAT_URL)
            except Exception:
                pass

            # 轮询等待登录成功（URL 跳转到后台首页）
            max_wait = 180  # 最长等待 3 分钟
            elapsed = 0
            interval = 1

            while elapsed < max_wait:
                try:
                    url = page.url
                    if "cgi-bin/home" in url or "cgi-bin/frame" in url:
                        break
                except Exception:
                    pass
                await asyncio.sleep(interval)
                elapsed += interval
            else:
                # 超时
                await browser.close()
                self.loginFailed.emit("登录超时，请重试")
                return

            # 登录成功，保存 session
            await context.storage_state(path=str(self.session_path))
            await browser.close()
            self.loginSuccess.emit(self.account_name)
