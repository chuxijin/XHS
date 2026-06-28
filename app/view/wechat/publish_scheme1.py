# coding: utf-8
"""发布方案1 —— 基于草稿模板的公众号发布流程"""
import asyncio
import re
import time
from datetime import datetime

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from .wechat_service import (WECHAT_URL, ACCOUNTS_DIR,
                              get_today_templates_dir, load_templates,
                              save_history, launch_browser,
                              TEMPLATE_CATEGORIES)

# 条件等待的默认超时（毫秒）
_TIMEOUT = 15000
_DAILY_TEMPLATE_NAMES = {
    "校招": "校招日常模板2",
    "实习": "实习日常模板1",
    "社招": "社招日常模板1",
}


class _StopRequested(Exception):
    """用户请求终止"""


async def _retry(action, retries=2, delay=3, log=None):
    """对异步操作进行重试，_StopRequested 不重试直接抛出"""
    for attempt in range(retries + 1):
        try:
            return await action()
        except _StopRequested:
            raise
        except Exception as e:
            if attempt < retries:
                if log:
                    log(f"  操作失败，{delay}秒后重试 "
                        f"({attempt+1}/{retries}): {e}")
                await asyncio.sleep(delay)
            else:
                raise


async def _find_editor_page(context):
    for p in context.pages:
        has_editor = await p.evaluate("""() => {
            return !!document.querySelector('.ProseMirror') ||
                   !!document.querySelector('[contenteditable="true"]');
        }""")
        if has_editor:
            return p
    return None


async def _find_mini_program_text_input(editor_page, link: str, log,
                                         timeout: float = 15.0):
    """在"插入小程序"弹窗中查找"文字内容"输入框（解析后自动填入小程序名）。

    弹窗 .weui-desktop-dialog__wrp 在 DOM 中可能有多个隐藏副本，
    需用标题文本 + 可见性双重过滤锁定当前弹窗。
    弹窗内有 2 个 text input：链接（#小程序://...）+ 文字内容（如"塔塔网申"）。
    跳过链接框，第一个非空 textbox 就是文字内容。
    返回 (locator, value)。
    """
    # 用 :visible 伪类 + 标题文本"插入小程序"锁定可见弹窗
    dialog = editor_page.locator(
        '.weui-desktop-dialog__wrp:visible').filter(
        has_text="插入小程序").first
    try:
        await dialog.wait_for(state="visible", timeout=5000)
    except Exception:
        pass

    end_t = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end_t:
        try:
            all_boxes = dialog.get_by_role("textbox")
            cnt = await all_boxes.count()
        except Exception:
            cnt = 0
        for i in range(cnt):
            cand = all_boxes.nth(i)
            try:
                if not await cand.is_visible(timeout=200):
                    continue
                val = await cand.input_value(timeout=500)
            except Exception:
                continue
            if not val or not val.strip():
                continue
            # 跳过链接输入框：值匹配原链接、或形如 URL/小程序链接格式
            if (val == link
                or val.startswith(
                    ("http://", "https://", "//", "#小程序://"))):
                continue
            log(f"  小程序已解析: {val} (dialog textbox#{i})")
            return cand, val
        await asyncio.sleep(0.5)

    # 超时：打印所有 dialog 状态帮助排查
    try:
        debug = await editor_page.evaluate("""() => {
            const dialogs = Array.from(document.querySelectorAll(
                '.weui-desktop-dialog__wrp'));
            return dialogs.map((d, i) => {
                const inputs = Array.from(d.querySelectorAll(
                    'input[type="text"], textarea, input:not([type])'));
                return {
                    idx: i,
                    visible: d.offsetParent !== null,
                    headerText: (d.querySelector(
                        '.weui-desktop-dialog__title, h1, h2, h3')
                        ?.textContent || '').substring(0, 30),
                    inputs: inputs.map((el, j) => ({
                        idx: j,
                        ph: el.placeholder || '',
                        val: (el.value || '').substring(0, 60),
                        visible: el.offsetParent !== null,
                    }))
                };
            });
        }""")
        log(f"  [调试] 所有 dialog: {debug}")
    except Exception:
        pass
    raise Exception("未找到小程序文案输入框（解析超时或选择器失效）")


async def _find_and_click_template(editor_page, template_name: str, log):
    """在草稿列表中轮询查找标题以 template_name 开头的项并点击。
    兼容列表尚未加载完成、标签页切换延迟等情况。"""
    items = editor_page.locator(".weui-desktop-mass-media")
    timeout_s = _TIMEOUT / 1000
    end_time = asyncio.get_event_loop().time() + timeout_s

    # 轮询：列表可能还在加载或刷新，反复检查直到找到目标
    while asyncio.get_event_loop().time() < end_time:
        try:
            await items.first.wait_for(state="visible", timeout=3000)
        except Exception:
            await asyncio.sleep(0.5)
            continue
        count = await items.count()
        for j in range(count):
            title = (await items.nth(j).text_content()).strip()
            if title.startswith(template_name):
                log(f"  找到: {title[:60]}")
                await items.nth(j).click()
                await asyncio.sleep(1)  # 等待选中状态生效
                return
        await asyncio.sleep(0.5)

    # 兜底：通过搜索框过滤后再找
    log(f"  列表中未找到「{template_name}」，尝试搜索过滤...")
    search_box = editor_page.get_by_role("textbox", name="输入标题搜索")
    if await search_box.count() > 0:
        await search_box.click()
        await search_box.fill(template_name)
        await editor_page.keyboard.press("Enter")
        await asyncio.sleep(2)

        try:
            await items.first.wait_for(state="visible", timeout=_TIMEOUT)
        except Exception:
            pass
        count = await items.count()
        for j in range(count):
            title = (await items.nth(j).text_content()).strip()
            if title.startswith(template_name):
                log(f"  搜索后找到: {title[:60]}")
                await items.nth(j).click()
                await asyncio.sleep(1)
                return

    raise Exception(f"草稿列表中未找到「{template_name}」")


async def _navigate_to_first_editor(page, template_name: str, log):
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

    log(f"查找「{template_name}」...")
    await _find_and_click_template(editor_page, template_name, log)
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


async def _create_new_article(editor_page, template_name: str, log):
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

    log(f"查找「{template_name}」...")
    await _find_and_click_template(editor_page, template_name, log)
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


async def _do_replace(editor_page, replacements: dict, log) -> dict:
    results = {}

    # 调试：输出当前编辑器内容概要
    try:
        debug_info = await editor_page.evaluate("""() => {
            const root = document.querySelector(
                '.ProseMirror:not([data-placeholder])');
            // 新版：ProseMirror contenteditable div；旧版：input
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

    # 1. 替换标题
    title_fields = {k: v if v else " " for k, v in replacements.items()
                    if k != "{{小程序链接}}"}
    if title_fields:
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
                title_text = re.sub(
                    r'^(校招|实习)日常模板\d+\s*', '', title_text)
                replaced = 0
                for ph, val in title_fields.items():
                    if ph in title_text:
                        title_text = title_text.replace(ph, val)
                        replaced += 1
                if replaced > 0:
                    if title_is_editable_div:
                        # ProseMirror 需要真实键盘事件才能更新内部状态
                        await title_box.click()
                        await editor_page.keyboard.press("Control+A")
                        await editor_page.keyboard.press("Delete")
                        await editor_page.keyboard.type(title_text)
                    else:
                        await title_box.fill(title_text)
                log(f"  标题替换 {replaced} 处")
                results["标题"] = replaced
        except Exception as e:
            log(f"  标题替换异常: {e}")
            results["标题"] = 0

    # 2. 替换正文 (ProseMirror innerHTML)
    body_fields = {k: v if v else " " for k, v in replacements.items()
                   if k != "{{小程序链接}}"}
    if body_fields:
        log("替换正文...")
        body_result = await editor_page.evaluate("""(replacements) => {
            const root = document.querySelector(
                '.ProseMirror:not([data-placeholder])');
            if (!root) return {};
            let html = root.innerHTML;
            const replaced = {};
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
            for (const [ph, newText] of Object.entries(replacements)) {
                const escaped = ph.split('').map(c =>
                    c.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')
                ).join('(?:<[^>]*>)*');
                const regex = new RegExp(escaped, 'g');
                const matches = html.match(regex);
                const count = matches ? matches.length : 0;
                if (count > 0) {
                    const htmlText = toEditorHtml(newText);
                    html = html.replace(regex, htmlText);
                }
                replaced[ph] = count;
            }
            if (Object.values(replaced).some(c => c > 0)) {
                root.innerHTML = html;
            }
            return replaced;
        }""", body_fields)
        total = sum(body_result.values())
        log(f"  正文替换 {total} 处")
        results.update(body_result)

    # 3. 插入小程序卡片
    link = replacements.get("{{小程序链接}}", "")
    if link:
        try:
            log("插入小程序卡片...")
            target = editor_page.get_by_text("{{小程序链接}}")
            await target.click(click_count=3)
            await editor_page.keyboard.press("Backspace")

            log("  点击小程序按钮...")
            weapp_btn = editor_page.locator(
                "#js_editor_insertweapp").get_by_text("小程序")
            await weapp_btn.wait_for(state="visible", timeout=5000)
            await weapp_btn.click()

            log("  填入小程序链接...")
            link_input = editor_page.get_by_role(
                "textbox",
                name="微信打开小程序，右上角复制链接后粘贴到此处")
            await link_input.wait_for(state="visible", timeout=5000)
            await link_input.fill(link)

            log("  等待小程序解析...")
            text_input, auto_val = await _find_mini_program_text_input(
                editor_page, link, log)

            log("  设置卡片文案...")
            # 用键盘输入代替 fill()，触发完整的 DOM 事件链
            await text_input.click(click_count=3)  # 全选已有文字
            await editor_page.keyboard.type("点击复制官方链接")
            await asyncio.sleep(0.5)

            log("  点击确定...")
            confirm_btn = editor_page.get_by_role("button", name="确定").last
            await confirm_btn.click()
            results["{{小程序链接}}"] = 1
            log("  小程序卡片插入成功")
        except Exception as e:
            log(f"  小程序插入异常: {e}")
            results["{{小程序链接}}"] = 0

    return results


async def _save_draft(editor_page, log):
    """点击保存为草稿按钮"""
    try:
        save_btn = editor_page.get_by_role("button", name="保存为草稿")
        if await save_btn.count() > 0 and await save_btn.first.is_visible():
            await save_btn.first.click()
            log("  草稿已保存")
            # 等待保存完成（页面会出现短暂的"已保存"提示）
            await editor_page.wait_for_timeout(1000)
        else:
            log("  未找到「保存为草稿」按钮，请手动保存")
    except Exception as e:
        log(f"  保存草稿异常: {e}")


class WechatPublishThread(QThread):
    """方案1：基于草稿模板的公众号发布"""

    logMessage = Signal(str)
    publishWaiting = Signal()
    publishSuccess = Signal()
    publishFailed = Signal(str)
    publishStopped = Signal()

    def __init__(self, account_name: str, templates_dir=None, parent=None,
                 *, headless=False):
        super().__init__(parent)
        self.account_name = account_name
        self.account_dir = ACCOUNTS_DIR / account_name
        self.session_path = self.account_dir / "session.json"
        self._templates_dir = templates_dir
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
        """每个步骤之间调用，处理暂停和终止"""
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

        if self._templates_dir:
            templates_dir = self._templates_dir
        else:
            templates_dir = get_today_templates_dir(self.account_name)
        category_templates = [
            (category, load_templates(templates_dir, category))
            for category in TEMPLATE_CATEGORIES
        ]
        recruit_temps = dict(category_templates).get("校招", [])
        intern_temps = dict(category_templates).get("实习", [])
        if not recruit_temps and not intern_temps:
            self.publishFailed.emit(
                f"未找到模板，请在 {templates_dir} 下的 校招/ 和 实习/ "
                f"文件夹中放入模板")
            return

        loaded_summary = ", ".join(
            f"{category} {len(temps)} 个"
            for category, temps in category_templates
        )
        self._log(f"已加载 {loaded_summary}")

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
                if "cgi-bin/home" in page.url or "cgi-bin/frame" in page.url:
                    self._log("公众号后台加载完成")
                    break
                await asyncio.sleep(1)
                elapsed += 1
            else:
                await browser.close()
                self.publishFailed.emit("会话已过期，请重新登录")
                return

            try:
                editor_page = await _navigate_to_first_editor(
                    page, "校招日常模板1", self._log)
                self._log("已进入编辑页")
            except _StopRequested:
                self._log("用户已终止，正在关闭浏览器...")
                await context.storage_state(path=str(self.session_path))
                await browser.close()
                self.publishStopped.emit()
                return
            except Exception as e:
                await context.storage_state(path=str(self.session_path))
                await browser.close()
                self.publishFailed.emit(f"导航失败: {e}")
                return

            success_count = 0
            fail_count = 0
            total_count = sum(len(temps) for _, temps in category_templates)

            try:
                article_idx = 0
                for category, temps in category_templates:
                    for i, (name, data) in enumerate(temps):
                        await self._check_state()

                        active = {k: v for k, v in data.items() if v}
                        if not active:
                            self._log(f"[{category}/{name}] 模板为空，跳过")
                            article_idx += 1
                            continue

                        try:
                            if article_idx > 0:
                                tpl_name = _DAILY_TEMPLATE_NAMES[category]

                                self._log(
                                    f"新建第 {article_idx + 1} 篇"
                                    f"（{category}）...")
                                editor_page = await _find_editor_page(
                                    context)
                                if not editor_page:
                                    self._log("未找到编辑器页面，中断")
                                    break
                                await _retry(
                                    lambda tn=tpl_name:
                                        _create_new_article(
                                            editor_page, tn, self._log),
                                    retries=2, delay=3, log=self._log)

                            await self._check_state()

                            label = f"{category}/{name}"
                            self._log(
                                f"[{label}] 替换中 "
                                f"({article_idx+1}/{total_count})...")

                            editor_page = await _find_editor_page(context)
                            if not editor_page:
                                self._log("未找到编辑器页面，中断")
                                break

                            result = await _retry(
                                lambda ep=editor_page, a=active:
                                    _do_replace(ep, a, self._log),
                                retries=1, delay=2, log=self._log)
                            self._log(f"[{label}] 替换完成: {result}")
                            save_history(
                                self.account_dir, label, active, "success")
                            success_count += 1

                        except _StopRequested:
                            raise
                        except Exception as e:
                            label = f"{category}/{name}"
                            self._log(f"[{label}] 处理失败，跳过: {e}")
                            save_history(
                                self.account_dir, label, active, "fail",
                                error=str(e))
                            fail_count += 1

                        article_idx += 1
                        await asyncio.sleep(1)

                # 保存草稿
                self._log("正在保存草稿...")
                editor_page = await _find_editor_page(context)
                if editor_page:
                    await _save_draft(editor_page, self._log)

                elapsed_s = time.monotonic() - _start_time
                m, s = divmod(int(elapsed_s), 60)
                summary = f"成功 {success_count} 个"
                if fail_count:
                    summary += f"，失败 {fail_count} 个"
                self._log(f"全部完成，{summary}，总耗时 {m}分{s}秒")
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
