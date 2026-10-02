import asyncio
import json
import re
import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

class LocationExtractor:
    def __init__(self, cdp_url="http://localhost:9222"):
        self.cdp_url = cdp_url
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }

    async def fetch_workday_cxs_api(self, client, url):
        m = re.search(r'https://([^.]+)\.(wd\d+\.myworkdayjobs\.com)/([^/]+)/job/(.+)', url)
        if not m:
            return None
        
        tenant, domain, site_path, job_path = m.group(1), m.group(2), m.group(3), m.group(4)
        api_url = f"https://{tenant}.{domain}/wday/cxs/{tenant}/{site_path}/job/{job_path}"

        try:
            resp = await client.get(api_url, headers=self.headers, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                job_info = data.get('jobPostingInfo', {})
                primary_loc = job_info.get('location')
                add_locs = job_info.get('additionalLocations', [])

                loc_list = []
                if primary_loc:
                    loc_list.append(primary_loc.strip())
                if add_locs and isinstance(add_locs, list):
                    for al in add_locs:
                        if al and al.strip() not in loc_list:
                            loc_list.append(al.strip())

                if loc_list:
                    return ", ".join(loc_list)
        except Exception:
            pass
        return None

    async def fetch_smartrecruiters_api(self, client, url):
        m = re.search(r'smartrecruiters\.com/([^/]+)/(\d+)', url)
        if not m:
            return None
        company, posting_id = m.group(1), m.group(2)
        api_url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"

        try:
            resp = await client.get(api_url, headers=self.headers, timeout=6.0)
            if resp.status_code == 200:
                data = resp.json()
                loc = data.get('location', {})
                full_loc = loc.get('fullLocation') or loc.get('city') or loc.get('region')
                return full_loc
        except Exception:
            pass
        return None

    def render_via_cdp_chrome(self, url, wait_seconds=3.0):
        try:
            with sync_playwright() as p:
                browser = p.chromium.connect_over_cdp(self.cdp_url)
                context = browser.contexts[0]
                page = context.new_page()
                page.goto(url, wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(int(wait_seconds * 1000))

                body_text = page.inner_text('body')
                page.close()
                return body_text
        except Exception as e:
            return f"Error: {e}"
