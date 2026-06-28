# coding: utf-8
"""发布方案2 —— 周日汇总（校招 + 实习 + 社招）"""
import asyncio
import time
from datetime import datetime

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from .publish_scheme1 import (
    _StopRequested, _retry, _find_editor_page, _save_draft, _TIMEOUT,
    _find_and_click_template, _find_mini_program_text_input,
)
from .wechat_service import (
    WECHAT_URL, ACCOUNTS_DIR,
    load_date_range_templates, compute_month_and_week,
    save_history, launch_browser, TEMPLATE_CATEGORIES,
)


# ---- 辅助函数 ----

_SUMMARY_TEMPLATE_PREFIXES = {
    "校招": "周日总结校招模板",
    "实习": "周日总结实习模板",
    "社招": "周日总结社招模板",
}


async def _navigate_to_first_editor_scheme2(page, template_prefix: str, log):
    """新建图文 → 切换草稿 → 查找周日汇总模板 → 确定 → 等待编辑器。"""
    log("点击新建图文...")
    async with page.expect_popup() as popup_info:
        await page.locator(".new-creation__menu > div:nth-child(3)").click()
    editor_page = await popup_info.value

    log("等待编辑页加载...")
    await editor_page.wait_for_load_state("domcontentloaded")
    await asyncio.sleep(1)

    log("切换到「草稿」标签...")
    await editor_page.get_by_text("草稿", exact=True).click()
    await asyncio.sleep(1)

    log(f"查找「{template_prefix}」...")
    await _find_and_click_template(editor_page, template_prefix, log)
    await asyncio.sleep(1)

    log("点击确定...")
    await editor_page.get_by_role("button", name="确定").click()
    await asyncio.sleep(1)

    log("等待页面网络请求完成...")
    try:
        await editor_page.wait_for_load_state("networkidle", timeout=_TIMEOUT)
    except Exception:
        pass
    await asyncio.sleep(1)

    log("等待编辑器就绪...")
    # 新版页面有 2 个 .ProseMirror（标题 + 正文），只等正文
    await editor_page.locator(
        ".ProseMirror:not([data-placeholder])").wait_for(
        state="visible", timeout=_TIMEOUT)
    await asyncio.sleep(1)

    log("等待模板内容加载...")
    await editor_page.wait_for_function(
        "() => (document.querySelector("
        "'.ProseMirror:not([data-placeholder])')?.textContent "
        "|| '').includes('{{')",
        timeout=_TIMEOUT)

    return editor_page


async def _create_new_article_scheme2(editor_page, template_prefix: str, log):
    """在已有编辑页中新建第 2 篇文章，选择周日汇总模板。"""
    log("点击「新建内容」...")
    await editor_page.get_by_text("新建内容", exact=True).click()
    await asyncio.sleep(1)

    log("等待「选择已有内容」...")
    link = editor_page.get_by_role("link", name="选择已有内容")
    await link.wait_for(state="visible", timeout=_TIMEOUT)
    await link.click()
    await asyncio.sleep(1)

    log("切换到「草稿」标签...")
    draft_tab = editor_page.get_by_text("草稿", exact=True)
    await draft_tab.wait_for(state="visible", timeout=_TIMEOUT)
    await draft_tab.click()
    await asyncio.sleep(1)

    log(f"查找「{template_prefix}」...")
    await _find_and_click_template(editor_page, template_prefix, log)
    await asyncio.sleep(1)

    log("点击确定...")
    await editor_page.get_by_role("button", name="确定").click()
    await asyncio.sleep(1)

    log("等待编辑器加载...")
    try:
        await editor_page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    await asyncio.sleep(1)

    log("等待模板内容加载...")
    try:
        await editor_page.wait_for_function(
            "() => (document.querySelector("
            "'.ProseMirror:not([data-placeholder])')?.textContent "
            "|| '').includes('{{')",
            timeout=_TIMEOUT)
    except Exception:
        pass


async def _do_sequential_replace(editor_page, month: int, week: int,
                                 entries: list, template_prefix: str,
                                 log) -> dict:
    """对编辑器中重复出现的占位符进行顺序替换。

    entries: [(date, data_dict), ...]  按日期、编号排序的扁平列表
    """
    results = {}

    # ---- 调试 ----
    try:
        debug_info = await editor_page.evaluate("""() => {
            const root = document.querySelector(
                '.ProseMirror:not([data-placeholder])');
            const titleDiv = document.querySelector(
                '.ProseMirror[data-placeholder="请在这里输入标题"]');
            const titleInput = document.querySelector(
                'input[placeholder="请在这里输入标题"]');
            const title = titleDiv || titleInput;
            let titleText = '(未找到标题框)';
            if (title) {
                titleText = title.tagName === 'INPUT'
                    ? title.value : title.textContent;
            }
            return {
                title: titleText,
                bodyLen: root ? root.innerHTML.length : 0,
                bodyPreview: root
                    ? root.textContent.substring(0, 200)
                    : '(未找到编辑器)',
            };
        }""")
        log(f"  [调试] 标题: {debug_info.get('title', '?')}")
        log(f"  [调试] 正文长度: {debug_info.get('bodyLen', 0)}, "
            f"预览: {debug_info.get('bodyPreview', '?')[:100]}...")
    except Exception as e:
        log(f"  [调试] 读取内容失败: {e}")

    # ---- 1. 替换标题 ----
    try:
        log("替换标题...")
        # 新版页面：标题是 ProseMirror contenteditable div
        title_box = editor_page.locator(
            '.ProseMirror[data-placeholder="请在这里输入标题"]')
        title_is_editable_div = await title_box.count() > 0
        if not title_is_editable_div:
            # 兜底：旧版 input
            title_box = editor_page.get_by_role(
                "textbox", name="请在这里输入标题")
        if await title_box.count() > 0:
            if title_is_editable_div:
                title_text = (await title_box.text_content()) or ""
            else:
                title_text = await title_box.input_value()
            # 去掉模板名前缀
            title_text = title_text.replace(template_prefix, "").strip()
            title_text = title_text.replace("{{月数}}", str(month))
            title_text = title_text.replace("{{周数}}", str(week))
            if title_is_editable_div:
                # ProseMirror 需要真实键盘事件才能更新内部状态
                await title_box.click()
                await editor_page.keyboard.press("Control+A")
                await editor_page.keyboard.press("Delete")
                await editor_page.keyboard.type(title_text)
            else:
                await title_box.fill(title_text)
            log(f"  标题: {title_text[:80]}")
            results["标题"] = 1
    except Exception as e:
        log(f"  标题替换异常: {e}")
        results["标题"] = 0

    # ---- 2. 全局替换正文中的 {{月数}} 和 {{周数}} ----
    log("替换正文中的月数/周数...")
    global_result = await editor_page.evaluate("""(args) => {
        const root = document.querySelector(
            '.ProseMirror:not([data-placeholder])');
        if (!root) return {month: 0, week: 0};
        let html = root.innerHTML;

        function buildRegex(placeholder, global) {
            const pat = placeholder.split('').map(c =>
                c.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')
            ).join('(?:<[^>]*>)*');
            return new RegExp(pat, global ? 'g' : '');
        }

        const mCount = (html.match(buildRegex('{{月数}}', true)) || []).length;
        const wCount = (html.match(buildRegex('{{周数}}', true)) || []).length;
        html = html.replace(buildRegex('{{月数}}', true), String(args.month));
        html = html.replace(buildRegex('{{周数}}', true), String(args.week));
        root.innerHTML = html;
        return {month: mCount, week: wCount};
    }""", {"month": month, "week": week})
    log(f"  月数替换 {global_result.get('month', 0)} 处, "
        f"周数替换 {global_result.get('week', 0)} 处")
    await asyncio.sleep(1)

    # ---- 3. 顺序替换 {{日数}} ----
    seen_dates = []
    day_numbers = []
    for d, _ in entries:
        if d not in seen_dates:
            seen_dates.append(d)
            day_numbers.append(d.day)

    log(f"替换日数 ({len(day_numbers)} 天: {day_numbers})...")
    day_result = await editor_page.evaluate("""(dayNumbers) => {
        const root = document.querySelector(
            '.ProseMirror:not([data-placeholder])');
        if (!root) return 0;
        let html = root.innerHTML;
        function buildRegex(placeholder) {
            return new RegExp(
                placeholder.split('').map(c =>
                    c.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')
                ).join('(?:<[^>]*>)*')
            );
        }
        let count = 0;
        for (const dayNum of dayNumbers) {
            const regex = buildRegex('{{日数}}');
            if (regex.test(html)) {
                html = html.replace(regex, String(dayNum));
                count++;
            }
        }
        root.innerHTML = html;
        return count;
    }""", day_numbers)
    log(f"  日数替换 {day_result} 处")
    results["{{日数}}"] = day_result
    await asyncio.sleep(1)

    # ---- 4. 顺序替换条目占位符 ----
    PER_ENTRY_FIELDS = ["{{公司简称}}", "{{岗位名称}}", "{{工作地点}}"]

    field_values = {f: [] for f in PER_ENTRY_FIELDS}
    for _, data in entries:
        for f in PER_ENTRY_FIELDS:
            field_values[f].append(data.get(f, "") or " ")

    log(f"替换正文占位符 ({len(entries)} 条记录)...")
    body_result = await editor_page.evaluate("""(fieldValues) => {
        const root = document.querySelector(
            '.ProseMirror:not([data-placeholder])');
        if (!root) return {};
        let html = root.innerHTML;
        const replaced = {};

        function buildRegex(placeholder) {
            return new RegExp(
                placeholder.split('').map(c =>
                    c.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')
                ).join('(?:<[^>]*>)*')
            );
        }
        function escapeHtml(text) {
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function toEditorHtml(text) {
            const normalized = escapeHtml(text)
                .replace(/\\\\n/g, '\\n')
                .split(/\\r\\n|\\r|\\n/g);
            return normalized.join('</span></p><p><span leaf="">');
        }

        for (const [ph, values] of Object.entries(fieldValues)) {
            let count = 0;
            for (const val of values) {
                const regex = buildRegex(ph);
                if (regex.test(html)) {
                    html = html.replace(regex, toEditorHtml(val));
                    count++;
                }
            }
            replaced[ph] = count;
        }

        root.innerHTML = html;
        return replaced;
    }""", field_values)
    total = sum(body_result.values())
    log(f"  正文替换 {total} 处: {body_result}")
    results.update(body_result)
    await asyncio.sleep(1)

    # ---- 5. 逐个插入小程序卡片 ----
    mini_links = [(data.get("{{小程序链接}}", "")) for _, data in entries]
    mini_links = [l for l in mini_links if l]

    if mini_links:
        log(f"插入 {len(mini_links)} 个小程序卡片...")
        card_ok = 0
        for i, link in enumerate(mini_links):
            try:
                log(f"  卡片 {i+1}/{len(mini_links)}...")
                target = editor_page.get_by_text("{{小程序链接}}").first
                await target.click(click_count=3)
                await editor_page.keyboard.press("Backspace")

                log(f"    点击小程序按钮...")
                weapp_btn = editor_page.locator(
                    "#js_editor_insertweapp").get_by_text("小程序")
                await weapp_btn.wait_for(state="visible", timeout=5000)
                await weapp_btn.click()

                log(f"    填入链接...")
                link_input = editor_page.get_by_role(
                    "textbox",
                    name="微信打开小程序，右上角复制链接后粘贴到此处")
                await link_input.wait_for(state="visible", timeout=5000)
                await link_input.fill(link)

                log(f"    等待解析...")
                text_input, auto_val = await _find_mini_program_text_input(
                    editor_page, link, log)

                log(f"    设置文案...")
                await text_input.click(click_count=3)
                await editor_page.keyboard.type("投递链接")
                await asyncio.sleep(0.5)

                log(f"    点击确定...")
                confirm_btn = editor_page.get_by_role(
                    "button", name="确定").last
                await confirm_btn.click()
                card_ok += 1
                await asyncio.sleep(1)
            except Exception as e:
                log(f"    卡片 {i+1} 失败: {e}")

        results["{{小程序链接}}"] = card_ok
        log(f"  小程序卡片: {card_ok}/{len(mini_links)} 成功")
    else:
        log("  无小程序链接，跳过卡片插入")

    return results


# ---- 主线程 ----

class Scheme2Thread(QThread):
    """方案2：周日汇总 —— 跨日期范围的校招/实习汇总发布"""

    logMessage = Signal(str)
    publishWaiting = Signal()
    publishSuccess = Signal()
    publishFailed = Signal(str)
    publishStopped = Signal()

    def __init__(self, account_name: str, start_date, end_date,
                 parent=None, *, headless=False):
        super().__init__(parent)
        self.account_name = account_name
        self.account_dir = ACCOUNTS_DIR / account_name
        self.session_path = self.account_dir / "session.json"
        self._start_date = start_date
        self._end_date = end_date
        self._headless = headless
        self._stop_requested = False
        self._pause_requested = False

    def request_stop(self):
        self._stop_requested = True
        self._pause_requested = False

    def request_pause(self):
        self._pause_requested = True

    def request_resume(self):
        self._pause_requested = False

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.logMessage.emit(f"[{ts}] {msg}")

    async def _check_state(self):
        if self._stop_requested:
            raise _StopRequested()
        while self._pause_requested:
            if self._stop_requested:
                raise _StopRequested()
            await asyncio.sleep(0.3)

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._publish())
        except Exception as e:
            if not self._stop_requested:
                self.publishFailed.emit(str(e))
        finally:
            loop.close()

    async def _publish(self):
        _start_time = time.monotonic()

        month, week = compute_month_and_week(self._end_date)
        self._log(f"周日汇总: {self._start_date} ~ {self._end_date}, "
                  f"{month}月第{week}周")

        # 加载并展平为 (date, data_dict) 列表
        category_entries = []
        for category in TEMPLATE_CATEGORIES:
            raw_templates = load_date_range_templates(
                self.account_name, self._start_date, self._end_date,
                category)
            flat_entries = [(d, data)
                            for d, day_temps in raw_templates
                            for _, data in day_temps]
            category_entries.append((category, flat_entries))

        summary = ", ".join(
            f"{category}: {len(entries)} 条"
            for category, entries in category_entries
        )
        self._log(summary)

        if not any(entries for _, entries in category_entries):
            self.publishFailed.emit("日期范围内未找到任何模板数据")
            return

        if not self.session_path.exists():
            self.publishFailed.emit("未找到登录会话，请先登录账号")
            return

        async with async_playwright() as p:
            browser = await launch_browser(p, headless=self._headless)
            context = await browser.new_context(
                no_viewport=True,
                storage_state=str(self.session_path),
            )
            page = await context.new_page()
            try:
                await page.goto(WECHAT_URL)
            except Exception:
                pass

            self._log("浏览器已打开，等待页面加载...")

            max_wait = 30
            elapsed = 0
            while elapsed < max_wait:
                if self._stop_requested:
                    self._log("用户已停止")
                    await browser.close()
                    self.publishStopped.emit()
                    return
                if ("cgi-bin/home" in page.url
                        or "cgi-bin/frame" in page.url):
                    self._log("公众号后台加载完成")
                    break
                await asyncio.sleep(1)
                elapsed += 1
            else:
                await browser.close()
                self.publishFailed.emit("会话已过期，请重新登录")
                return

            try:
                article_idx = 0
                for category, entries in category_entries:
                    if not entries:
                        self._log(f"{category}无数据，跳过")
                        continue

                    await self._check_state()
                    template_prefix = _SUMMARY_TEMPLATE_PREFIXES[category]
                    self._log(f"===== 第{article_idx + 1}篇: {category} "
                              f"({len(entries)}条) =====")

                    if article_idx == 0:
                        editor_page = await _retry(
                            lambda tp=template_prefix:
                                _navigate_to_first_editor_scheme2(
                                    page, tp, self._log),
                            retries=1, delay=3, log=self._log)
                    else:
                        editor_page = await _find_editor_page(context)
                        if not editor_page:
                            raise Exception("未找到编辑器页面")
                        await _retry(
                            lambda ep=editor_page, tp=template_prefix:
                                _create_new_article_scheme2(
                                    ep, tp, self._log),
                            retries=1, delay=3, log=self._log)

                    await self._check_state()
                    editor_page = await _find_editor_page(context)
                    if not editor_page:
                        raise Exception("未找到编辑器页面")

                    result = await _do_sequential_replace(
                        editor_page, month, week,
                        entries, template_prefix, self._log)
                    self._log(f"{category}替换完成: {result}")
                    save_history(self.account_dir, f"{category}汇总",
                                {"entries": len(entries)}, "success")
                    article_idx += 1

                # 保存草稿
                self._log("正在保存草稿...")
                editor_page = await _find_editor_page(context)
                if editor_page:
                    await _save_draft(editor_page, self._log)

                elapsed_s = time.monotonic() - _start_time
                m, s = divmod(int(elapsed_s), 60)
                self._log(f"全部完成，总耗时 {m}分{s}秒")
                if not self._headless:
                    self._log("请在浏览器中检查内容后点击「结束流程」")
                self.publishWaiting.emit()

            except _StopRequested:
                self._log("用户已终止，正在关闭浏览器...")
                await context.storage_state(path=str(self.session_path))
                await browser.close()
                self.publishStopped.emit()
                return
            except Exception as e:
                self._log(f"发布失败: {e}")
                self.publishWaiting.emit()

            if self._headless:
                self._log("隐藏模式，5秒后自动关闭浏览器")
                await asyncio.sleep(5)
                await context.storage_state(path=str(self.session_path))
                await browser.close()
                self.publishSuccess.emit()
                return

            # 保持浏览器打开，等待用户手动结束
            while not self._stop_requested:
                await asyncio.sleep(0.5)

            self._log("用户已结束流程，正在关闭浏览器...")
            await context.storage_state(path=str(self.session_path))
            await browser.close()
            self.publishStopped.emit()
