import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        for pg in browser.contexts[0].pages:
            if "company/index" in pg.url:
                btns = await pg.query_selector_all("button")
                print("Buttons in company/index:")
                for b in btns:
                    txt = (await b.inner_text()).strip()
                    if txt:
                        print(f"  btn: '{txt}'")
                break

asyncio.run(main())
