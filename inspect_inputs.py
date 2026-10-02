import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        # 找激活的那个 company-basic/index
        for idx, pg in enumerate(browser.contexts[0].pages):
            if "company-basic/index" in pg.url:
                title = await pg.title()
                inputs = await pg.query_selector_all("input")
                print(f"Page {idx} ({pg.url}):")
                for i, inp in enumerate(inputs):
                    ph = await inp.get_attribute("placeholder")
                    val = await inp.input_value()
                    vis = await inp.is_visible()
                    if vis and ph:
                        print(f"  Input {i}: placeholder='{ph}', value='{val}'")

asyncio.run(main())
