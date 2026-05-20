# coding: utf-8
"""小红书发布方案1 —— 视频笔记自动发布"""
import asyncio
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from .xhs_service import (XHS_URL, ACCOUNTS_DIR,
                           save_history, compose_title)
from ...common.setting import launch_browser


class _StopRequested(Exception):
    """用户请求终止"""


class XhsPublishThread(QThread):
    """方案1：视频笔记自动发布（单条）"""

    logMessage = Signal(str)
    publishWaiting = Signal()
    publishSuccess = Signal()
    publishFailed = Signal(str)
    publishStopped = Signal()

    def __init__(self, account_name: str, video_path: str,
                 template_name: str, template_data: dict,
                 publish_config: dict, parent=None,
                 *, headless=False):
        super().__init__(parent)
        self.account_name = account_name
        self.video_path = video_path
        self.template_name = template_name
        self.template_data = template_data
        self.publish_config = publish_config
        self.account_dir = ACCOUNTS_DIR / account_name
        self.session_path = self.account_dir / "session.json"
        self._headless = headless
        self._stop_requested = False
        self._pause_requested = False

    def request_stop(self):
        self._stop_requested = True
        self._pause_requested = False

    def request_pause(self):
        self._pause_requested = True

    def request_resume(self):
        self._pause_requested = False

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logMessage.emit(f"[{ts}] {msg}")

    async def _check_state(self):
        """每个步骤之间调用，处理暂停和终止"""
        if self._stop_requested:
            raise _StopRequested()
        while self._pause_requested:
            if self._stop_requested:
                raise _StopRequested()
            await asyncio.sleep(0.3)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._publish())
        except Exception as e:
            if not self._stop_requested:
                self.publishFailed.emit(str(e))
        finally:
            loop.close()
    async def _publish(self):
        config = self.publish_config

        if not Path(self.video_path).exists():
            self.publishFailed.emit(f"视频文件不存在: {self.video_path}")
            return
        if not self.session_path.exists():
            self.publishFailed.emit("未找到登录会话，请先登录账号")
            return

        self._log(f"模板: {self.template_name}")

        async with async_playwright() as p:
            browser = await launch_browser(p, headless=self._headless)
            context = await browser.new_context(
                no_viewport=True,
                storage_state=str(self.session_path),
            )
            page = await context.new_page()
            try:
                await page.goto(XHS_URL)
            except Exception:
                pass

            self._log("浏览器已打开，正在确认登录...")

            max_wait = 30
            elapsed = 0
            while elapsed < max_wait:
                if self._stop_requested:
                    self._log("用户已停止")
                    await browser.close()
                    self.publishStopped.emit()
                    return
                if "/creator" in page.url and "login" not in page.url:
                    break
                await asyncio.sleep(1)
                elapsed += 1
            else:
                await browser.close()
                self.publishFailed.emit("会话已过期，请重新登录")
                return

            self._log("已登录创作者中心")

            try:
                await self._publish_one_note(page, config)
                self._log("所有步骤已完成，请确认页面无误后点击「结束流程」")
                save_history(self.account_dir, self.template_name,
                             self.template_data, "success")
                self.publishWaiting.emit()
            except _StopRequested:
                self._log("用户已终止，正在关闭浏览器...")
                await context.storage_state(path=str(self.session_path))
                await browser.close()
                self.publishStopped.emit()
                return
            except Exception as e:
                self._log(f"发布失败: {e}")
                save_history(self.account_dir, self.template_name,
                             self.template_data, "failed", str(e))
                self.publishWaiting.emit()

            if self._headless:
                self._log("隐藏模式，5秒后自动关闭浏览器")
                await asyncio.sleep(5)
                await context.storage_state(path=str(self.session_path))
                await browser.close()
                self.publishSuccess.emit()
                return

            # 保持浏览器打开，等待用户手动结束
            while not self._stop_requested:
                await asyncio.sleep(0.5)

            self._log("用户已结束流程，正在关闭浏览器...")
            await context.storage_state(path=str(self.session_path))
            await browser.close()
            self.publishStopped.emit()

    async def _publish_one_note(self, page, config: dict):
        """发布单条视频笔记"""
        await page.goto("https://creator.xiaohongshu.com/publish/publish")
        await page.wait_for_timeout(3000)
        await self._check_state()

        # 上传视频
        self._log("上传视频...")
        file_input = page.locator('input[type="file"]')
        await file_input.set_input_files(self.video_path)
        await self._wait_for_upload(page)
        await self._check_state()

        # 填写标题
        title = compose_title(self.template_data)
        self._log(f"填写标题: {title}")
        title_box = page.get_by_role("textbox", name="填写标题会有更多赞哦")
        await title_box.fill(title)
        await page.wait_for_timeout(500)
        await self._check_state()

        # 添加话题
        topics = config.get("topics", [])
        if topics:
            body_box = page.get_by_role("textbox").nth(1)
            self._log(f"添加话题: {', '.join(topics)}")
            for i, topic in enumerate(topics):
                await self._check_state()
                if i > 0:
                    await body_box.type(" ")
                    await page.wait_for_timeout(200)
                await body_box.type(f"#{topic}")
                await page.wait_for_timeout(2000)
                try:
                    container = page.locator("#creator-editor-topic-container")
                    await container.wait_for(state="visible", timeout=5000)
                    item = container.get_by_text(f"#{topic}", exact=True)
                    if await item.is_visible(timeout=3000):
                        await item.click()
                        self._log(f"已添加话题: {topic}")
                        await page.wait_for_timeout(1000)
                    else:
                        self._log(f"未找到话题建议: {topic}")
                except Exception:
                    self._log(f"话题添加失败: {topic}")

        await self._check_state()

        # 选择合集
        collection_name = config.get("collection", "")
        if collection_name:
            self._log(f"选择合集: {collection_name}")
            await self._select_collection(page, collection_name)

        await self._check_state()

        # 选择群聊
        group_chat_name = config.get("group_chat", "")
        if group_chat_name:
            self._log(f"选择群聊: {group_chat_name}")
            await self._select_group_chat(page, group_chat_name)

        await self._check_state()

        # 发布

        await self._check_state()

        # 点击发布
        self._log("点击发布...")
        publish_btn = page.get_by_role("button", name="发布")
        await publish_btn.click()
        await page.wait_for_timeout(3000)

    async def _wait_for_upload(self, page, timeout=120):
        """等待视频上传完成"""
        self._log("等待上传完成...")
        elapsed = 0
        while elapsed < timeout:
            if self._stop_requested:
                raise _StopRequested()
            try:
                progress = page.locator(".upload-progress, .progress-bar")
                if await progress.count() > 0:
                    text = await progress.first.text_content()
                    if text and ("100" in text or "完成" in text):
                        break
                else:
                    title_box = page.get_by_role(
                        "textbox", name="填写标题会有更多赞哦")
                    if await title_box.is_visible(timeout=1000):
                        break
            except Exception:
                pass
            await asyncio.sleep(2)
            elapsed += 2
        await page.wait_for_timeout(2000)

    async def _select_collection(self, page, collection_name: str):
        """选择合集（模糊匹配：包含关键字的第一个）"""
        try:
            trigger = page.locator("text=添加到合集").first
            if await trigger.is_visible(timeout=5000):
                await trigger.click()
                await page.wait_for_timeout(2000)
                item = page.locator(
                    f"//*[contains(text(), '{collection_name}')]").first
                if await item.is_visible(timeout=5000):
                    self._log(f"匹配到合集: {await item.text_content()}")
                    await item.click()
                    await page.wait_for_timeout(1000)
                else:
                    self._log(f"未找到包含「{collection_name}」的合集")
        except Exception as e:
            self._log(f"合集选择失败: {e}")

    async def _select_group_chat(self, page, group_name: str):
        """选择群聊（模糊匹配：包含关键字的第一个）"""
        try:
            trigger = page.locator("text=群聊").first
            if await trigger.is_visible(timeout=5000):
                await trigger.click()
                await page.wait_for_timeout(2000)
                item = page.locator(
                    f"//*[contains(text(), '{group_name}')]").first
                if await item.is_visible(timeout=5000):
                    self._log(f"匹配到群聊: {await item.text_content()}")
                    await item.click()
                    await page.wait_for_timeout(1000)
                else:
                    self._log(f"未找到包含「{group_name}」的群聊")
        except Exception as e:
            self._log(f"群聊选择失败: {e}")
