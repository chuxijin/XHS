import asyncio
import json
from playwright.async_api import async_playwright

COMPANIES = [
    ("昂跑", "昂跑"),
    ("珀莱雅", "珀莱雅"),
    ("亿滋中国", "亿滋"),
    ("阿迪达斯", "阿迪达斯"),
    ("达能中国", "达能"),
    ("赫力昂", "赫力昂"),
    ("stepfun阶越星辰", "阶跃星辰"),
    ("保乐力加", "保乐力加"),
    ("不凡帝范梅勒", "不凡帝范梅勒"),
    ("费列罗", "费列罗"),
    ("康泰纳仕", "康泰纳仕"),
    ("奇华顿", "奇华顿"),
    ("IFF", "IFF"),
    ("施普林格.自然", "Springer"),
]

async def click_query_btn(page):
    btns = await page.query_selector_all("button")
    for b in btns:
        txt = (await b.inner_text()).strip()
        if "查询" in txt:
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

        results = []

        for user_label, kw in COMPANIES:
            # 1. 在公司列表搜全名
            kw_input = await basic_page.query_selector("input[placeholder='输入关键词搜索']")
            await kw_input.fill(kw)
            await click_query_btn(basic_page)
            await asyncio.sleep(1.5)
            
            rows = await basic_page.query_selector_all("tbody tr")
            if not rows:
                results.append({"label": user_label, "status": "未找到"})
                continue
                
            tds = await rows[0].query_selector_all("td")
            full_name = (await tds[1].inner_text()).strip()
            short_name = (await tds[2].inner_text()).strip()
            comp_type = (await tds[3].inner_text()).strip()
            site_count = (await tds[7].inner_text()).strip()
            
            # 点击第7列的关联网站数字（在 site_page 中查看，或者在 basic_page 点开它）
            site_td = tds[7]
            num_span = await site_td.query_selector("span")
            sites_found = []
            
            # 2. 直接在 site_page 搜
            site_kw_input = await site_page.query_selector("input[placeholder='输入网站名称搜索']")
            task_kw_input = await site_page.query_selector("input[placeholder='输入任务名称搜索']")
            if task_kw_input:
                await task_kw_input.fill("")
            
            # 优先用 kw 搜网站列表
            if site_kw_input:
                await site_kw_input.fill(kw)
                await click_query_btn(site_page)
                await asyncio.sleep(1.5)
                
                site_rows = await site_page.query_selector_all("tbody tr")
                for sr in site_rows[:3]:
                    stds = await sr.query_selector_all("td")
                    if len(stds) >= 7:
                        s_name = (await stds[1].inner_text()).strip()
                        s_task = (await stds[4].inner_text()).strip()
                        s_url = (await stds[6].inner_text()).strip()
                        sites_found.append({"name": s_name, "task": s_task, "url": s_url})

            results.append({
                "label": user_label,
                "full_name": full_name,
                "short_name": short_name,
                "type": comp_type,
                "site_count": site_count,
                "sites": sites_found
            })
            print(f"[{user_label}] 全称: {full_name} | 关联网站数: {site_count} | 查到网站: {[s['task'] for s in sites_found]}")

        print("=== FINAL RESULTS ===")
        print(json.dumps(results, ensure_ascii=False, indent=2))

asyncio.run(main())
