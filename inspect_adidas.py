import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = None
        for pg in browser.contexts[0].pages:
            if "company-basic/index" in pg.url:
                page = pg
                break

        kw_input = await page.query_selector("input[placeholder='输入关键词搜索']")
        # 双击全选再退格或 fill
        await kw_input.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await kw_input.type("阿迪达斯")
        
        # 点击查询
        btns = await page.query_selector_all("button")
        for b in btns:
            if "查询" in (await b.inner_text()).strip():
                await b.click()
                break
        await asyncio.sleep(2)
        
        rows = await page.query_selector_all("tbody tr")
        print(f"阿迪达斯 搜出记录数: {len(rows)}")
        for idx, r in enumerate(rows):
            tds = await r.query_selector_all("td")
            texts = [await td.inner_text() for td in tds]
            print(f"Row {idx+1}: 名称={texts[1]}, 简称={texts[2]}, 类型={texts[3]}, 关联网站数={texts[7]}")

asyncio.run(main())
