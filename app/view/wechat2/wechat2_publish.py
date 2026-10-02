# coding: utf-8
"""公众号2：仅根据 JSON 模板批量创建公众号草稿。"""
import asyncio
import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from ..wechat.publish_scheme1 import (
    _create_new_article,
    _do_replace,
    _find_editor_page,
    _navigate_to_first_editor,
    _save_draft,
)
from ..wechat.wechat_service import ACCOUNTS_DIR, WECHAT_URL, launch_browser


DRAFT_TEMPLATE_NAME = "{{日常模板1}}"


class _StopRequested(Exception):
    """用户请求终止"""


async def _set_article_title(editor_page, title: str, log):
    title_box = editor_page.locator(
        '.ProseMirror[data-placeholder="请在这里输入标题"]'
    )
    if await title_box.count() == 0:
        title_box = editor_page.get_by_role("textbox", name="请在这里输入标题")
    if await title_box.count() == 0:
        raise RuntimeError("未找到公众号标题输入框")
    await title_box.first.click()
    await editor_page.keyboard.press("Control+A")
    await editor_page.keyboard.press("Delete")
    await editor_page.keyboard.type(title)
    log(f"标题已设置：{title}")


class Wechat2JsonPublishThread(QThread):
    logMessage = Signal(str)
    publishSuccess = Signal(int, int)
    publishFailed = Signal(str)
    publishStopped = Signal()
    publishWaiting = Signal()

    def __init__(self, account_names: list[str], template_paths: list[Path], headless: bool = True, parent=None):
        super().__init__(parent)
        self.account_names = account_names
        self.template_paths = template_paths
        self.headless = headless
        self._paused = False
        self._stop_requested = False

    def _log(self, message: str):
        self.logMessage.emit(message)

    def pause(self):
        self._paused = True
        self._log("收到暂停指令，当前步骤完成后将暂停...")

    def resume(self):
        self._paused = False
        self._log("恢复执行...")

    def stop(self):
        self._stop_requested = True
        self._log("收到终止指令...")

    async def _check_state(self):
        if self._stop_requested:
            raise _StopRequested()
        while self._paused:
            if self._stop_requested:
                raise _StopRequested()
            await asyncio.sleep(0.5)

    def run(self):
        try:
            success, failed = asyncio.run(self._publish())
            if self._stop_requested:
                self.publishStopped.emit()
            else:
                self.publishSuccess.emit(success, failed)
        except _StopRequested:
            self._log("流程已被用户终止")
            self.publishStopped.emit()
        except Exception as error:
            self.publishFailed.emit(str(error))

    async def _publish(self) -> tuple[int, int]:
        success = 0
        failed = 0
        for account_name in self.account_names:
            await self._check_state()
            account_success, account_failed = await self._publish_account(account_name)
            success += account_success
            failed += account_failed
        return success, failed

    async def _publish_account(self, account_name: str) -> tuple[int, int]:
        session_path = ACCOUNTS_DIR / account_name / "session.json"
        if not session_path.exists():
            raise RuntimeError(f"账号「{account_name}」没有登录会话")

        self._log(f"[{account_name}] 准备发布 {len(self.template_paths)} 篇草稿")
        success = 0
        failed = 0
        async with async_playwright() as playwright:
            browser = await launch_browser(playwright, headless=self.headless)
            context = await browser.new_context(
                no_viewport=True,
                storage_state=str(session_path),
            )
            page = await context.new_page()
            try:
                await self._check_state()
                await page.goto(WECHAT_URL)
                await page.wait_for_timeout(1500)

                elapsed = 0
                while elapsed < 15:
                    await self._check_state()
                    if "cgi-bin/home" in page.url or "cgi-bin/frame" in page.url:
                        break
                    await asyncio.sleep(1)
                    elapsed += 1

                editor_page = await _navigate_to_first_editor(
                    page, DRAFT_TEMPLATE_NAME, self._log
                )

                for index, template_path in enumerate(self.template_paths):
                    await self._check_state()
                    try:
                        data = json.loads(template_path.read_text(encoding="utf-8"))
                        if not isinstance(data, dict):
                            raise ValueError("模板必须是 JSON 对象")
                        title = str(data.get("{{标题}}") or "").strip()
                        if not title:
                            raise ValueError("{{标题}} 不能为空")
                        if index:
                            await _create_new_article(
                                editor_page, DRAFT_TEMPLATE_NAME, self._log
                            )
                            editor_page = await _find_editor_page(context)
                            if not editor_page:
                                raise RuntimeError("未找到公众号编辑器页面")

                        await self._check_state()
                        ALIAS_MAP = {
                            "{{简介}}": ["{{简介}}", "{{基本介绍}}"],
                            "{{基本介绍}}": ["{{基本介绍}}", "{{简介}}"],
                            "{{夸克连接}}": ["{{夸克连接}}", "{{夸克链接}}"],
                            "{{夸克链接}}": ["{{夸克链接}}", "{{夸克连接}}"],
                            "{{话题}}": ["{{话题}}", "{{话题标签}}"],
                            "{{话题标签}}": ["{{话题标签}}", "{{话题}}"],
                        }
                        replacements = {}
                        for key, value in data.items():
                            replacements[key] = value
                            if key in ALIAS_MAP:
                                for alias in ALIAS_MAP[key]:
                                    replacements[alias] = value

                        result = await _do_replace(
                            editor_page, replacements, self._log
                        )
                        await self._check_state()
                        await _set_article_title(editor_page, title, self._log)
                        await self._check_state()
                        await _save_draft(editor_page, self._log)
                        self._log(
                            f"[{account_name}] {template_path.name} 替换完成：{result}"
                        )
                        success += 1
                    except _StopRequested:
                        raise
                    except Exception as error:
                        failed += 1
                        self._log(
                            f"[{account_name}] {template_path.name} 发布失败：{error}"
                        )

                if not self.headless:
                    self._log("显示模式：模板保存完成，您可在浏览器中检查，检查完后请点击「终止」关闭浏览器")
                    self.publishWaiting.emit()
                    while not self._stop_requested:
                        await asyncio.sleep(0.5)
            finally:
                await context.storage_state(path=str(session_path))
                await browser.close()
        return success, failed

