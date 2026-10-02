import asyncio
import json
from playwright.async_api import async_playwright

COMPANIES = [
    "昂跑", "珀莱雅", "亿滋", "阿迪达斯", "达能",
    "百盛", "赫力昂", "阶跃星辰", "保乐力加", "英富曼",
    "优尼博览", "K2 Asia", "Attila", "不凡帝范梅勒", "费列罗",
    "康泰纳仕", "芬美意", "奇华顿", "IFF", "Wiley", "施普林格"
]

async def click_search(page):
    btns = await page.query_selector_all("button")
    for b in btns:
        if (await b.inner_text()).strip() == "搜索":
            await b.click()
            return True
    return False

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        
        basic_page = None
        site_page = None
        for pg in context.pages:
            if "company-basic/index" in pg.url and not basic_page:
                basic_page = pg
            elif "company/index" in pg.url and not site_page:
                site_page = pg

        if not basic_page or not site_page:
            print("Required pages not found")
            return

        all_company_records = {}

        # 1. 在公司列表批量查
        basic_kw = await basic_page.query_selector("input[placeholder='输入关键词搜索']")

        for kw in COMPANIES:
            await basic_kw.click()
            await basic_page.keyboard.press("Control+A")
            await basic_page.keyboard.press("Backspace")
            await basic_kw.type(kw)
            await click_search(basic_page)
            await asyncio.sleep(1.0)

            rows = await basic_page.query_selector_all("tbody tr")
            records = []
            for r in rows:
                tds = await r.query_selector_all("td")
                if len(tds) >= 8:
                    texts = [await td.inner_text() for td in tds]
                    records.append({
                        "id": texts[0],
                        "full_name": texts[1],
                        "short_name": texts[2],
                        "type": texts[3],
                        "site_count": texts[7]
                    })
            all_company_records[kw] = records
            print(f"[公司列表] {kw} -> 搜出 {len(records)} 条记录", flush=True)
            for r in records:
                print(f"    - 全称: {r['full_name']} | 简称: {r['short_name']} | 关联网站数: {r['site_count']}", flush=True)

        # 2. 在网站列表批量查
        site_kw = await site_page.query_selector("input[placeholder='输入网站名称搜索']")
        site_task = await site_page.query_selector("input[placeholder='输入任务名称搜索']")
        if site_task:
            await site_task.fill("")

        final_result = {}
        for kw, records in all_company_records.items():
            final_result[kw] = {"companies": records, "sites": []}
            if not records:
                continue

            search_names = set([kw])
            for r in records:
                if r["full_name"]:
                    search_names.add(r["full_name"])
                if r["short_name"]:
                    for sn in r["short_name"].split("/"):
                        if sn.strip():
                            search_names.add(sn.strip())

            seen_sites = set()
            sites = []
            for name in search_names:
                q = name.strip()[:15]
                await site_kw.click()
                await site_page.keyboard.press("Control+A")
                await site_page.keyboard.press("Backspace")
                await site_kw.type(q)
                await click_search(site_page)
                await asyncio.sleep(0.8)

                s_rows = await site_page.query_selector_all("tbody tr")
                for sr in s_rows:
                    stds = await sr.query_selector_all("td")
                    if len(stds) >= 7:
                        s_name = (await stds[1].inner_text()).strip()
                        s_task = (await stds[4].inner_text()).strip()
                        s_url = (await stds[6].inner_text()).strip()
                        key = (s_name, s_url)
                        if key not in seen_sites and s_name:
                            seen_sites.add(key)
                            sites.append({"name": s_name, "task": s_task, "url": s_url})

            final_result[kw]["sites"] = sites
            print(f"[网站列表] {kw} -> 查到 {len(sites)} 个网站", flush=True)
            for s in sites:
                print(f"    * {s['name']} | 任务: {s['task']} | {s['url']}", flush=True)

        with open("batch_query_result.json", "w", encoding="utf-8") as f:
            json.dump(final_result, f, ensure_ascii=False, indent=2)
        print("ALL_DONE_SUCCESSFULLY", flush=True)

asyncio.run(main())
