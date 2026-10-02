import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        pg = browser.contexts[0].pages[9]
        
        # 点击查询按钮
        btns = await pg.query_selector_all("button")
        for b in btns:
            if "查询" in (await b.inner_text()).strip():
                await b.click()
                break
        await asyncio.sleep(2)
        
        rows = await pg.query_selector_all("tbody tr")
        print(f"Page 9 rows count: {len(rows)}")
        for idx, r in enumerate(rows):
            tds = await r.query_selector_all("td")
            texts = [await td.inner_text() for td in tds]
            print(f"Row {idx+1}:", texts[:8])

asyncio.run(main())
