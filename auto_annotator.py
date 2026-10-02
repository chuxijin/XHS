import sys
import json
import time
import re
import urllib.request
from datetime import datetime
from playwright.sync_api import sync_playwright

def get_wx_publish_date(notice_url: str, job_item=None) -> str:
    # 1. 优先从页面的 job-item 中提取 .job-time
    if job_item:
        try:
            time_el = job_item.locator(".job-time")
            if time_el.count() > 0:
                raw_time = time_el.inner_text().strip()
                m = re.search(r'\d{4}-\d{2}-\d{2}', raw_time)
                if m:
                    date_val = m.group(0)
                    print(f"从公告列表提取到发布时间: {date_val}")
                    return date_val
        except Exception as e:
            print(f"从DOM提取时间异常: {e}")

    # 2. 从微信文章网页抓取 var ct
    try:
        req = urllib.request.Request(notice_url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            m = re.search(r'var\s+ct\s*=\s*["\']?(\d{10})["\']?', html)
            if m:
                ts = int(m.group(1))
                dt = datetime.fromtimestamp(ts)
                date_val = dt.strftime("%Y-%m-%d")
                print(f"从微信文章源码解析到发布时间: {date_val}")
                return date_val
    except Exception as e:
        print(f"抓取微信发布时间异常: {e}")

    fallback = datetime.now().strftime("%Y-%m-%d")
    print(f"无法获取发布时间，兜底使用当天: {fallback}")
    return fallback

def filter_empty_notice_row(page, rows, match_name=None):
    headers = [th.inner_text().strip() for th in page.locator(".el-table__header th").all()]
    notice_idx = headers.index("公告") if "公告" in headers else 10

    candidate_rows = []
    for i in range(rows.count()):
        r = rows.nth(i)
        if match_name and match_name not in r.inner_text():
            continue
        candidate_rows.append(r)

    if not candidate_rows:
        candidate_rows = [rows.nth(i) for i in range(rows.count())]

    # 优先筛选公司全称完全精确匹配的行
    if match_name:
        exact_match_rows = []
        for r in candidate_rows:
            tds = r.locator("td")
            if tds.count() > 1 and tds.nth(1).inner_text().strip() == match_name:
                exact_match_rows.append(r)
        if exact_match_rows:
            print(f"在搜索结果中精准匹配到全称一致记录（共 {len(exact_match_rows)} 条）")
            candidate_rows = exact_match_rows

    empty_notice_rows = []
    for r in candidate_rows:
        tds = r.locator("td")
        if tds.count() > notice_idx:
            val = tds.nth(notice_idx).inner_text().strip()
            if not val:
                empty_notice_rows.append(r)

    if empty_notice_rows:
        print(f"搜出多个目标，已锁定【公告】列为空的记录（共 {len(empty_notice_rows)} 条未标注记录）")
        return empty_notice_rows[0]
    else:
        print("提示：搜出多个目标但各行公告列均非空，选取候选匹配第一条记录")
        return candidate_rows[0]

def search_and_locate_row(page, company_name: str):
    name_input = page.locator(".el-form-item:has(.el-form-item__label:has-text('名称')) input").first
    name_input.fill(company_name)
    search_btn = page.locator("button.el-button--primary:has-text('搜索')").first
    try:
        with page.expect_response(lambda r: "company" in r.url and r.status == 200, timeout=10000):
            search_btn.click()
    except Exception:
        search_btn.click()
    page.wait_for_timeout(600)

    rows = page.locator(".el-table__body-wrapper tbody tr")
    if rows.count() == 1 and "暂无数据" not in rows.first.inner_text():
        return rows.first
    elif rows.count() > 1:
        return filter_empty_notice_row(page, rows, company_name)

    clean_name = company_name
    for suffix in ["分公司", "支公司", "集团有限公司", "有限责任公司", "股份有限公司", "有限公司", "集团", "公司"]:
        if clean_name.endswith(suffix) and len(clean_name) - len(suffix) >= 3:
            clean_name = clean_name[:-len(suffix)]
            break

    if clean_name != company_name:
        print(f"原名称未直接定位，尝试用核心关键词搜索: '{clean_name}'...")
        name_input.fill(clean_name)
        try:
            with page.expect_response(lambda r: "company" in r.url and r.status == 200, timeout=10000):
                search_btn.click()
        except Exception:
            search_btn.click()
        page.wait_for_timeout(600)

        rows = page.locator(".el-table__body-wrapper tbody tr")
        row_count = rows.count()
        if row_count == 1 and "暂无数据" in rows.first.inner_text():
            row_count = 0
        print(f"关键词搜索返回 {row_count} 条记录")

        if row_count == 1:
            return rows.first
        elif row_count > 1:
            return filter_empty_notice_row(page, rows, clean_name)

    return None

def close_all_open_dialogs(page):
    try:
        page.evaluate('''() => {
            const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper'));
            for (let i = wrappers.length - 1; i >= 0; i--) {
                const w = wrappers[i];
                if (window.getComputedStyle(w).display !== 'none') {
                    const btn = w.querySelector('.el-dialog__headerbtn, button.el-button--default');
                    if (btn) btn.click();
                }
            }
        }''')
        page.wait_for_timeout(500)
    except Exception:
        pass

def urls_match(u1: str, u2: str) -> bool:
    if not u1 or not u2:
        return False
    u1_clean = u1.strip().rstrip("/").lower()
    u2_clean = u2.strip().rstrip("/").lower()
    if u1_clean == u2_clean:
        return True
    # 忽略协议头差异
    for proto in ["http://", "https://"]:
        if u1_clean.startswith(proto):
            u1_clean = u1_clean[len(proto):]
        if u2_clean.startswith(proto):
            u2_clean = u2_clean[len(proto):]
    if u1_clean == u2_clean:
        return True
    # 微信文章比对：匹配 /s/xxxx 核心路径
    if "mp.weixin.qq.com/s/" in u1 and "mp.weixin.qq.com/s/" in u2:
        key1 = u1.split("/s/")[-1].split("?")[0].split("#")[0].strip("/")
        key2 = u2.split("/s/")[-1].split("?")[0].split("#")[0].strip("/")
        if key1 and key1 == key2:
            return True
    return False

def execute_annotation_on_page(page, company_name: str, notice_url: str, custom_grad_year=None, end_date=None):
    today_str = datetime.now().strftime("%Y-%m-%d")

    if isinstance(custom_grad_year, list):
        target_grad_years = custom_grad_year
    elif isinstance(custom_grad_year, str):
        target_grad_years = [y.strip() for y in custom_grad_year.replace(',', ' ').split() if y.strip()]
    else:
        target_grad_years = ["27届"]

    print(f"\n==========================================")
    print(f"开始处理: {company_name}")
    print(f"公告链接: {notice_url}")
    print(f"==========================================")

    # 1. 预先清理可能未关闭的残留弹窗并搜索目标公司
    close_all_open_dialogs(page)
    target_row = search_and_locate_row(page, company_name)
    if not target_row or target_row.count() == 0:
        raise Exception(f"未在列表中找到公司: {company_name}")

    actual_name = target_row.locator("td").nth(1).inner_text().strip()
    short_name = target_row.locator("td").nth(2).inner_text().strip()
    if not short_name:
        short_name = actual_name
    notice_title = f"{short_name}公告详情"
    print(f"匹配到公司: {actual_name} | 简称: {short_name} | 公告标题: {notice_title}")

    # 2. 点击标注按钮
    target_row.locator("button:has-text('标注')").click()
    page.wait_for_timeout(800)

    main_dialog = page.locator(".el-dialog__wrapper:visible .el-dialog:has(.el-dialog__title:has-text('标注信息'))")
    main_dialog.wait_for(state="visible", timeout=5000)

    is_wx_url = "mp.weixin.qq.com" in notice_url

    # 3. 检查弹窗中已存在的最近公告信息，进行比对去重
    existing_items = page.evaluate('''() => {
        const dialog = document.querySelector(".el-dialog__wrapper:not([style*='display: none']) .el-dialog");
        if (!dialog) return [];
        const items = Array.from(dialog.querySelectorAll(".job-item"));
        return items.map((item, idx) => {
            const a = item.querySelector("a");
            const mouseBtn = item.querySelector("button i.el-icon-mouse")?.closest("button");
            return {
                index: idx,
                href: a ? a.href : "",
                text: a ? a.innerText.trim() : "",
                isActive: mouseBtn ? mouseBtn.classList.contains("el-button--success") : false
            };
        });
    }''')

    matched_item = None
    for item in existing_items:
        if urls_match(item["href"], notice_url) or urls_match(item["text"], notice_url):
            matched_item = item
            break

    action_type = "created"

    if matched_item:
        print(f"🔍 检查到该公告链接在历史公告中已存在 (索引 #{matched_item['index']})，当前激活状态: {matched_item['isActive']}")
        job_items = main_dialog.locator(".job-item")
        target_job_item = job_items.nth(matched_item["index"])

        # 检查届数是否已满足要求
        grad_item = main_dialog.locator(".el-form-item:has-text('网申届数')")
        existing_tags = [t.strip() for t in grad_item.locator(".el-tag").all_inner_texts()]

        if matched_item["isActive"] and set(existing_tags) == set(target_grad_years):
            print(f"⚡ 该公告链接已存在且当前已是主公告，届数 {existing_tags} 与目标一致，无需重复标注！直接跳过。")
            close_btn = main_dialog.locator(".el-dialog__footer button:has-text('取 消'), button.el-dialog__headerbtn").first
            close_btn.click()
            page.wait_for_timeout(600)
            print(f"✅ 公司【{actual_name}】已跳过（已完全标注）！\n")
            return actual_name, "skipped"

        if not matched_item["isActive"]:
            print("🔄 该公告链接已存在但未激活，直接点击激活为主公告（跳过重复添加）...")
            target_job_item.locator("button:has(i.el-icon-mouse)").click()
            page.wait_for_timeout(800)
            print("公告激活成功！")
            action_type = "reactivated"
        else:
            print(f"🔄 该公告链接已为主公告，但届数不匹配（当前: {existing_tags}, 目标: {target_grad_years}），将更新届数并保存...")
            action_type = "updated_years"
    else:
        # 不存在，执行正常的新增公告流程
        print("未在已有公告中找到该链接，执行新增公告流程...")
        main_dialog.locator("button:has-text('添加公告')").click()
        page.wait_for_timeout(500)

        notice_dialog = page.locator(".el-dialog__wrapper:visible .el-dialog:has(.el-dialog__title:has-text('添加公告'))")
        notice_dialog.wait_for(state="visible", timeout=3000)

        url_input = notice_dialog.locator("input[placeholder='请输入公告URL']")
        url_input.fill(notice_url)

        if not is_wx_url:
            url_input.press("Tab")
            title_input = notice_dialog.locator("input[placeholder='请输入公告标题']")
            title_input.wait_for(state="visible", timeout=3000)
            title_input.fill(notice_title)

            pub_time_input = notice_dialog.locator("input[placeholder='选择发布时间']")
            pub_time_input.fill(today_str)
            pub_time_input.press("Enter")

            # 关键保障：强制向底层 Vue Form Model 注入 url, title, pub_time 并派发事件
            page.evaluate('''({url, title, pub_time}) => {
                const dialog = Array.from(document.querySelectorAll('.el-dialog')).find(d => {
                    const t = d.querySelector('.el-dialog__title');
                    return t && t.innerText.trim() === '添加公告';
                });
                if (!dialog) return;
                const formEl = dialog.querySelector('.el-form');
                if (formEl && formEl.__vue__ && formEl.__vue__.model) {
                    formEl.__vue__.model.url = url;
                    formEl.__vue__.model.title = title;
                    formEl.__vue__.model.pub_time = pub_time;
                }
                const urlInp = dialog.querySelector("input[placeholder='请输入公告URL']");
                if (urlInp) {
                    urlInp.value = url;
                    urlInp.dispatchEvent(new Event('input', { bubbles: true }));
                    urlInp.dispatchEvent(new Event('change', { bubbles: true }));
                }
            }''', {"url": notice_url, "title": notice_title, "pub_time": today_str})

            notice_dialog.locator("button.el-button--primary:has-text('确 定')").click()
            notice_dialog.wait_for(state="hidden", timeout=5000)
            page.wait_for_timeout(800)
        else:
            print("识别为微信公众号链接，跳过标题和发布时间填写，点击确定并等待爬取解析完成...")
            try:
                with page.expect_response(lambda r: "spider_job_posting" in r.url and r.status == 200, timeout=15000) as resp_info:
                    notice_dialog.locator("button.el-button--primary:has-text('确 定')").click()
                print("收到微信公告爬取接口 spider_job_posting 200 响应！")
            except Exception as e:
                print(f"等待 spider_job_posting 响应提示: {e}")
                if notice_dialog.is_visible():
                    notice_dialog.locator("button.el-button--primary:has-text('确 定')").click()
            
            notice_dialog.wait_for(state="hidden", timeout=5000)
            page.wait_for_timeout(1500) # 关键：让 Vue 彻底更新主弹窗

        print("公告添加完成，准备激活公告...")

        # 激活该新增公告
        if is_wx_url:
            target_job_item = main_dialog.locator(".job-item:has(a[href*='mp.weixin.qq.com'])").first
            if target_job_item.count() == 0:
                target_job_item = main_dialog.locator(".job-item").first
        else:
            target_job_item = main_dialog.locator(f".job-item:has-text('{notice_title}')").first
            if target_job_item.count() == 0:
                target_job_item = main_dialog.locator(".job-item").first

        mouse_btn = target_job_item.locator("button:has(i.el-icon-mouse)")
        mouse_btn.click()
        page.wait_for_timeout(800)
        print("公告激活成功！")

    # 4. 设置网申届数（没有特别情况，严格只保留 target_grad_years，默认仅 27届）
    grad_item = main_dialog.locator(".el-form-item:has-text('网申届数')")
    existing_tags = [t.strip() for t in grad_item.locator(".el-tag").all_inner_texts()]
    if set(existing_tags) != set(target_grad_years):
        print(f"当前已有届数 {existing_tags} 与目标 {target_grad_years} 不一致，执行精准设置...")
        # 点击展开下拉框
        grad_item.locator(".el-select").click()
        page.wait_for_timeout(400)

        dropdown = page.locator(".el-select-dropdown:visible")
        dropdown.wait_for(state="visible", timeout=3000)
        options = dropdown.locator(".el-select-dropdown__item").all()
        for opt in options:
            opt_text = opt.inner_text().strip()
            opt_class = opt.get_attribute("class") or ""
            is_selected = "selected" in opt_class

            if opt_text in target_grad_years and not is_selected:
                print(f"  [+] 勾选目标届数: {opt_text}")
                opt.click()
                page.wait_for_timeout(200)
            elif opt_text not in target_grad_years and is_selected:
                print(f"  [-] 取消非目标届数: {opt_text}")
                opt.click()
                page.wait_for_timeout(200)

        # 收起下拉框
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)

        current_tags = [t.strip() for t in grad_item.locator(".el-tag").all_inner_texts()]
        print(f"当前已选届数标签: {current_tags}")

    # 5. 设置网申开始时间：优先使用平台原生快捷选项【公告发布日期】
    start_time_input = main_dialog.locator("input[placeholder='请选择网申开始时间']")
    start_time_input.click()
    page.wait_for_timeout(300)

    shortcut_btn = page.locator(".el-picker-panel:visible button.el-picker-panel__shortcut:has-text('公告发布日期')")
    if shortcut_btn.count() > 0:
        shortcut_btn.click()
        page.wait_for_timeout(300)
        print(f"点击【公告发布日期】快捷选项，开始时间已自动同步为: {start_time_input.input_value()}")
    else:
        # 兜底手动填入
        start_date_str = get_wx_publish_date(notice_url, target_job_item) if is_wx_url else today_str
        start_time_input.fill(start_date_str)
        start_time_input.press("Enter")
        print(f"手动填入开始时间: {start_date_str}")

    # 5.1 设置截止时间（若有指定）
    if end_date:
        print(f"设置网申截止时间为: {end_date}")
        end_time_input = main_dialog.locator("input[placeholder='请选择网申截止时间']")
        end_time_input.fill(end_date)
        end_time_input.press("Enter")
    else:
        print("未指定固定截止时间（招满即止），截止时间保持留空")

    # 6. 设置备注：非微信链接才追加 ' 当前非官微'
    if not is_wx_url:
        remark_textarea = main_dialog.locator("textarea[placeholder='请输入备注信息']")
        current_remark = remark_textarea.input_value().strip()
        append_text = "当前非官微"
        if append_text not in current_remark:
            new_remark = f"{current_remark} {append_text}".strip()
            remark_textarea.fill(new_remark)
            print(f"更新备注为: '{new_remark}'")
    else:
        print("微信公众号链接，无需追加备注")

    # 7. 点击主弹窗确定按钮完成保存
    confirm_btn = main_dialog.locator(".el-dialog__footer button.el-button--primary:has-text('确 定')").last
    
    with page.expect_response(lambda r: "update_manual" in r.url and r.status == 200, timeout=10000) as response_info:
        confirm_btn.click()

    print("收到后端保存响应 200！")
    page.wait_for_timeout(800)
    print(f"✅ 公司【{actual_name}】全部流程标注成功！\n")
    return actual_name, action_type
def get_jobleap_page(browser):
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "company-basic" in pg.url:
                return pg
    for ctx in browser.contexts:
        for pg in ctx.pages:
            if "admin.jobleap" in pg.url:
                try:
                    menu_btn = pg.locator(".el-menu-item:has-text('公司列表')").first
                    if menu_btn.is_visible():
                        menu_btn.click()
                        pg.wait_for_timeout(1500)
                        return pg
                except Exception:
                    pass
                return pg
    return None

def auto_annotate_company(company_name: str, notice_url: str, custom_grad_year=None, end_date=None):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page = get_jobleap_page(browser)
        if not page:
            raise Exception("未找到 JobLeap 后台页面")
        execute_annotation_on_page(page, company_name, notice_url, custom_grad_year, end_date)

def batch_annotate_companies(items):
    success_list = []
    fail_list = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page = get_jobleap_page(browser)
        if not page:
            raise Exception("未找到 JobLeap 后台页面")
        for item in items:
            comp = item["company"]
            url = item["url"]
            grad = item.get("grad_year")
            end_date = item.get("end_date")
            try:
                actual_name, action_type = execute_annotation_on_page(page, comp, url, grad, end_date)
                success_list.append({"input": comp, "actual": actual_name, "action": action_type, "url": url})
            except Exception as e:
                print(f"❌ 公司【{comp}】处理异常: {e}")
                fail_list.append({"input": comp, "url": url, "error": str(e)})
                close_all_open_dialogs(page)
                try:
                    name_input = page.locator(".el-form-item:has(.el-form-item__label:has-text('名称')) input").first
                    name_input.fill("")
                    page.locator("button.el-button--primary:has-text('搜索')").first.click()
                    page.wait_for_timeout(800)
                except Exception:
                    pass

    print("\n================== 批量执行统计 ==================")
    created_count = sum(1 for s in success_list if s.get("action") == "created")
    skipped_count = sum(1 for s in success_list if s.get("action") == "skipped")
    reactivated_count = sum(1 for s in success_list if s.get("action") in ["reactivated", "updated_years"])
    print(f"成功: {len(success_list)} 家 (新增: {created_count}, 跳过已标注: {skipped_count}, 重新激活/补选: {reactivated_count}), 失败: {len(fail_list)} 家")
    if fail_list:
        print("失败明细:", json.dumps(fail_list, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--stdin":
        data = json.loads(sys.stdin.read())
        if isinstance(data, list):
            batch_annotate_companies(data)
        else:
            auto_annotate_company(data["company"], data["url"], data.get("grad_year"))
    elif len(sys.argv) >= 3:
        comp = sys.argv[1]
        url = sys.argv[2]
        grad = sys.argv[3] if len(sys.argv) > 3 else None
        auto_annotate_company(comp, url, grad)
    else:
        print("Usage: python auto_annotator.py <company_name> <notice_url> [grad_year] OR python auto_annotator.py --stdin")
