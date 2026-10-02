import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        # 找 company/index 页面，搜索 adidas 或 阿迪达斯
        site_page = None
        for pg in browser.contexts[0].pages:
            if "company/index" in pg.url:
                site_page = pg
                break
        
        if not site_page:
            print("Site page not found")
            return

        kw_inp = await site_page.query_selector("input[placeholder='输入网站名称搜索']")
        task_inp = await site_page.query_selector("input[placeholder='输入任务名称搜索']")
        if task_inp:
            await task_inp.fill("")
        
        for search_term in ["阿迪达斯", "adidas"]:
            print(f"=== 搜索网站名称: {search_term} ===")
            await kw_inp.fill(search_term)
            btns = await site_page.query_selector_all("button")
            for b in btns:
                if "查询" in (await b.inner_text()).strip():
                    await b.click()
                    break
            await asyncio.sleep(2)
            
            rows = await site_page.query_selector_all("tbody tr")
            print(f"找到行数: {len(rows)}")
            for idx, r in enumerate(rows):
                tds = await r.query_selector_all("td")
                texts = [await td.inner_text() for td in tds]
                if len(texts) >= 7:
                    print(f"  [{idx+1}] 名称: {texts[1]} | 任务: {texts[4]} | 链接: {texts[6]}")

asyncio.run(main())
