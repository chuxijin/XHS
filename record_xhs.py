# coding: utf-8
"""打开小红书创作者中心，启动 Playwright Inspector 录制操作"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

XHS_URL = "https://creator.xiaohongshu.com/"
# 如果有已登录的 session，改成对应路径；没有就设为 None
SESSION_PATH = None

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        if SESSION_PATH and Path(SESSION_PATH).exists():
            context = await browser.new_context(
                no_viewport=True,
                storage_state=SESSION_PATH,
            )
        else:
            context = await browser.new_context(no_viewport=True)

        page = await context.new_page()
        await page.goto(XHS_URL)

        # 打开 Inspector，点击 Record 按钮开始录制
        await page.pause()

        # 录制完成后保存 session
        await context.storage_state(path="xhs_session.json")
        await browser.close()

asyncio.run(main())
