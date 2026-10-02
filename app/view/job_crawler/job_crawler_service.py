# coding: utf-8
"""招聘采集业务服务层 —— 公众号文章轻量采集与台账管理"""
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import requests
from PySide6.QtCore import QThread, Signal

from ...common.setting import DATA_DIR

CRAWLER_DATA_DIR = DATA_DIR / "job_crawler"
CRAWLER_DATA_DIR.mkdir(parents=True, exist_ok=True)
LEDGER_FILE = CRAWLER_DATA_DIR / "accounts_ledger.json"
WECHAT_ACCOUNTS_DIR = DATA_DIR / "accounts" / "wechat"


def load_ledger() -> dict:
    """加载已记录的公众号台账（包含 fakeid、最后抓取时间等）"""
    if not LEDGER_FILE.exists():
        return {}
    try:
        with open(LEDGER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_ledger(data: dict):
    """保存台账信息"""
    try:
        with open(LEDGER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存台账失败: {e}")


def load_credentials_file() -> Tuple[Optional[str], Optional[str]]:
    """从 job_crawler 专用 credentials.json 加载"""
    cred_file = CRAWLER_DATA_DIR / "credentials.json"
    if not cred_file.exists():
        return None, None
    try:
        with open(cred_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("cookie"), data.get("token")
    except Exception:
        return None, None


def save_credentials_file(cookie: str, token: str):
    """保存凭据到 job_crawler 专用 credentials.json"""
    cred_file = CRAWLER_DATA_DIR / "credentials.json"
    data = {
        "cookie": cookie,
        "token": token,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    try:
        with open(cred_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"保存 credentials.json 失败: {e}")


class CrawlerLoginThread(QThread):
    """
    专门针对微信公众号采集的扫码登录线程（完全采用 wechat-article-claw 项目核心逻辑）
    自动启动 Chromium 浏览器，等待用户扫码，成功跳转后直接从 URL 中解析 token 并获取 context.cookies()
    """
    login_success_signal = Signal(str, str)  # cookie, token
    login_failed_signal = Signal(str)
    log_signal = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        from playwright.sync_api import sync_playwright
        self.log_signal.emit("🚀 正在启动 Chromium 浏览器...")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=["--start-maximized"]
                )
                context = browser.new_context(
                    no_viewport=True,
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
                )
                page = context.new_page()

                self.log_signal.emit("🌐 正在导航至微信公众平台 (mp.weixin.qq.com)...")
                page.goto("https://mp.weixin.qq.com/", wait_until="domcontentloaded")

                self.log_signal.emit("⏳ 等待手机微信扫码并确认登录（超时时间 2 分钟）...")

                # 采用原项目核心判断：等待页面跳转到带 token= 的后台首页
                try:
                    page.wait_for_function(
                        "() => window.location.href.includes('token=')",
                        timeout=120000
                    )
                    self.log_signal.emit("✅ 扫码成功，页面已跳转！")
                except Exception as e:
                    browser.close()
                    self.login_failed_signal.emit("登录超时或未完成确认，请重新点击扫码登录")
                    return

                # 从跳转后的 URL 中提取 token
                current_url = page.url
                token = ""
                if "token=" in current_url:
                    token = current_url.split("token=")[1].split("&")[0]
                else:
                    browser.close()
                    self.login_failed_signal.emit("未能在跳转后的网址中找到 token，请重试")
                    return

                # 提取完整 Cookies
                cookies = context.cookies()
                cookie_parts = [f"{c['name']}={c['value']}" for c in cookies]
                cookie_str = "; ".join(cookie_parts)

                browser.close()

                # 保存到本地专有凭据文件
                save_credentials_file(cookie_str, token)
                self.log_signal.emit(f"🎉 成功提取凭据！Token: {token}")
                self.login_success_signal.emit(cookie_str, token)

        except Exception as e:
            self.login_failed_signal.emit(f"启动或登录异常: {e}")


class WeChatCrawlerClient:
    """微信公众平台文章抓取客户端"""

    def __init__(self, cookie: str, token: str):
        self.cookie = cookie
        self.token = token
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Cookie": self.cookie,
            "Referer": f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit_v2&action=edit&isNew=1&type=77&token={token}&lang=zh_CN"
        }

    def verify_login(self) -> bool:
        """测试凭据是否有效"""
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz",
            "begin": 0,
            "count": 1,
            "query": "微信",
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1
        }
        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=10)
            data = r.json()
            ret = data.get("base_resp", {}).get("ret", -1)
            return ret == 0
        except Exception:
            return False

    def search_biz(self, query: str) -> Optional[dict]:
        """按名称搜索公众号并返回首个匹配项信息"""
        url = "https://mp.weixin.qq.com/cgi-bin/searchbiz"
        params = {
            "action": "search_biz",
            "begin": 0,
            "count": 5,
            "query": query.strip(),
            "token": self.token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1
        }
        try:
            r = requests.get(url, headers=self.headers, params=params, timeout=10)
            data = r.json()
            if data.get("base_resp", {}).get("ret") != 0:
                return None
            items = data.get("list", [])
            if not items:
                return None
            # 优先精准匹配名字，否则返回第一个
            for it in items:
                if it.get("nickname") == query.strip():
                    return it
            return items[0]
        except Exception as e:
            print(f"搜索公众号异常: {e}")
            return None

    def fetch_articles(self, fakeid: str, since_timestamp: int = 0, max_count: int = 20) -> List[dict]:
        """
        获取指定 fakeid 公众号的文章列表
        返回: [{"title": ..., "link": ..., "create_time": ..., "time_str": ...}]
        """
        url = "https://mp.weixin.qq.com/cgi-bin/appmsg"
        begin = 0
        articles = []
        page_size = 5

        while len(articles) < max_count:
            params = {
                "action": "list_ex",
                "begin": begin,
                "count": page_size,
                "fakeid": fakeid,
                "type": 9,
                "token": self.token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1
            }
            try:
                r = requests.get(url, headers=self.headers, params=params, timeout=10)
                data = r.json()
                base_resp = data.get("base_resp", {})
                ret = base_resp.get("ret", 0)
                err_msg = base_resp.get("err_msg", "")

                if ret != 0:
                    error_desc = f"接口返回错误 (ret={ret}, err_msg='{err_msg}')"
                    if ret == 200013 or "freq control" in err_msg:
                        error_desc = "触发微信公众平台接口频率限制（freq control / 200013），当前账号已被微信风控限制调用，建议稍后再试或换号"
                    elif ret == 200003:
                        error_desc = "登录凭证已失效（token/cookie过期），请重新扫码登录"
                    return articles, error_desc

                app_msg_list = data.get("app_msg_list", [])
                if not app_msg_list:
                    break

                stop_crawl = False
                for item in app_msg_list:
                    pub_time = item.get("update_time", 0)
                    if pub_time < since_timestamp:
                        stop_crawl = True
                        break

                    dt_str = datetime.fromtimestamp(pub_time).strftime("%Y-%m-%d %H:%M")
                    articles.append({
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "create_time": pub_time,
                        "time_str": dt_str
                    })
                    if len(articles) >= max_count:
                        stop_crawl = True
                        break

                if stop_crawl or len(app_msg_list) < page_size:
                    break

                begin += page_size
                time.sleep(2)  # 防频控延迟
            except Exception as e:
                return articles, f"网络请求异常: {e}"

        return articles, None


class JobCrawlerThread(QThread):
    """后台采集线程"""
    log_signal = Signal(str)
    article_found_signal = Signal(dict)
    batch_finished_signal = Signal(bool, str)

    def __init__(self, targets: List[str], cookie: str, token: str, time_range_days: int = 30, use_last_time: bool = True):
        super().__init__()
        self.targets = targets
        self.cookie = cookie
        self.token = token
        self.time_range_days = time_range_days
        self.use_last_time = use_last_time
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        client = WeChatCrawlerClient(self.cookie, self.token)
        ledger = load_ledger()
        self.log_signal.emit(f"🚀 开始采集，目标列表共 {len(self.targets)} 个...")

        total_articles = 0
        now_ts = int(time.time())

        for idx, target in enumerate(self.targets):
            if not self.is_running:
                self.log_signal.emit("⏹ 用户已主动停止采集。")
                break

            target = target.strip()
            if not target:
                continue

            self.log_signal.emit(f"\n[{idx+1}/{len(self.targets)}] 正在处理：{target}")

            # 检查台账中是否存在 fakeid
            account_info = ledger.get(target, {})
            fakeid = account_info.get("fakeid")
            official_name = account_info.get("official_name", target)

            if not fakeid:
                self.log_signal.emit(f"  正在搜索公众号「{target}」获取识别码...")
                biz = client.search_biz(target)
                if not biz:
                    self.log_signal.emit(f"  ❌ 未找到公众号「{target}」，请检查名称是否准确。")
                    time.sleep(1.5)
                    continue
                fakeid = biz.get("fakeid")
                official_name = biz.get("nickname", target)
                account_info["fakeid"] = fakeid
                account_info["official_name"] = official_name
                self.log_signal.emit(f"  ✓ 匹配到「{official_name}」 (FakeID: {fakeid[:10]}...)")
                time.sleep(2)

            # 计算起始时间戳
            if self.use_last_time and account_info.get("last_crawl_timestamp"):
                since_ts = account_info["last_crawl_timestamp"]
                since_str = datetime.fromtimestamp(since_ts).strftime("%Y-%m-%d %H:%M")
                self.log_signal.emit(f"  按增量更新模式：拉取 {since_str} 以后的新文章")
            else:
                since_ts = int((datetime.now() - timedelta(days=self.time_range_days)).timestamp())
                self.log_signal.emit(f"  按时间范围模式：拉取近 {self.time_range_days} 天内的文章")

            # 开始拉取文章
            articles, err_desc = client.fetch_articles(fakeid, since_timestamp=since_ts)
            if err_desc:
                self.log_signal.emit(f"  ❌ 抓取失败: {err_desc}")
            else:
                self.log_signal.emit(f"  ✓ 成功获取到 {len(articles)} 篇符合条件的文章")

            for art in articles:
                item_data = {
                    "company": target,
                    "account": official_name,
                    "title": art["title"],
                    "link": art["link"],
                    "time_str": art["time_str"]
                }
                self.article_found_signal.emit(item_data)
                total_articles += 1

            # 仅在无严重接口错误时更新台账时间
            if not err_desc:
                account_info["last_crawl_timestamp"] = now_ts
                account_info["last_crawl_time"] = datetime.fromtimestamp(now_ts).strftime("%Y-%m-%d %H:%M:%S")
                ledger[target] = account_info
                save_ledger(ledger)

            # 礼貌间隔
            if idx < len(self.targets) - 1:
                time.sleep(3)

        self.batch_finished_signal.emit(True, f"采集完成！共处理 {len(self.targets)} 个目标，发现 {total_articles} 篇新文章。")
