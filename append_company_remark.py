import sys
import json
import time
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(encoding='utf-8')

def close_all_dialogs(page):
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
        page.wait_for_timeout(400)
    except Exception:
        pass

def reset_search_filters(page):
    """清除页面可能存在的筛选条件，确保全局搜索"""
    try:
        # 清除下拉框和日期范围等筛选器的选中项
        clear_btns = page.locator(".el-form .el-icon-circle-close").all()
        for btn in clear_btns:
            try:
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(100)
            except Exception:
                pass
    except Exception:
        pass

def append_remark_to_company(page, company_name: str, append_text: str):
    print(f"\n==========================================")
    print(f"开始处理: {company_name}")
    print(f"追加备注: {append_text}")
    print(f"==========================================")

    close_all_dialogs(page)
    reset_search_filters(page)

    # 1. 搜索目标公司
    name_input = page.locator(".el-form-item:has(.el-form-item__label:has-text('名称')) input").first
    name_input.fill("")
    name_input.fill(company_name)
    
    search_btn = page.locator("button.el-button--primary:has-text('搜索')").first
    try:
        with page.expect_response(lambda r: ("company/basic/all" in r.url or "recruit/company" in r.url or "company" in r.url) and r.status == 200, timeout=10000):
            search_btn.click()
    except Exception:
        search_btn.click()
    page.wait_for_timeout(800)

    rows = page.locator(".el-table__body-wrapper tbody tr")
    if rows.count() == 0 or "暂无数据" in rows.first.inner_text():
        # 如果当前有未重置的特殊过滤，刷新页面兜底重置
        print("直接搜索无结果，正在重载页面重置全部筛选条件后重试...")
        page.reload()
        page.wait_for_timeout(1500)
        name_input = page.locator(".el-form-item:has(.el-form-item__label:has-text('名称')) input").first
        name_input.fill("")
        name_input.fill(company_name)
        search_btn = page.locator("button.el-button--primary:has-text('搜索')").first
        try:
            with page.expect_response(lambda r: ("company/basic/all" in r.url or "recruit/company" in r.url or "company" in r.url) and r.status == 200, timeout=10000):
                search_btn.click()
        except Exception:
            search_btn.click()
        page.wait_for_timeout(800)
        rows = page.locator(".el-table__body-wrapper tbody tr")

    # 严格匹配目标公司
    target_row = None
    for i in range(rows.count()):
        r = rows.nth(i)
        if company_name in r.inner_text():
            target_row = r
            break
            
    if not target_row:
        raise Exception(f"未在列表中定位到公司: {company_name}")

    actual_name = target_row.locator("td").nth(1).inner_text().strip()
    short_name = target_row.locator("td").nth(2).inner_text().strip()
    print(f"匹配到公司: {actual_name} (简称: {short_name})")

    # 2. 点击标注打开弹窗
    target_row.locator("button:has-text('标注')").click()
    page.wait_for_timeout(800)

    main_dialog = page.locator(".el-dialog__wrapper:visible .el-dialog:has(.el-dialog__title:has-text('标注信息'))")
    main_dialog.wait_for(state="visible", timeout=6000)

    # 3. 获取并更新备注
    remark_textarea = main_dialog.locator("textarea[placeholder='请输入备注信息']")
    current_remark = remark_textarea.input_value().strip()
    print(f"当前备注: '{current_remark}'")

    if append_text in current_remark:
        print(f"⚠️ 备注中已包含 '{append_text}'，无需重复追加。")
    else:
        new_remark = f"{current_remark} {append_text}".strip() if current_remark else append_text
        remark_textarea.fill(new_remark)
        print(f"更新为新备注: '{new_remark}'")

    # 4. 点击确定保存
    confirm_btn = main_dialog.locator(".el-dialog__footer button.el-button--primary:has-text('确 定')").last
    with page.expect_response(lambda r: "update_manual" in r.url and r.status == 200, timeout=10000):
        confirm_btn.click()

    page.wait_for_timeout(800)
    print(f"✅ 公司【{actual_name}】备注追加并保存成功！\n")
    return actual_name

if __name__ == "__main__":
    tasks = [
        {"company": "汇丰控股有限公司", "append": "10.2最新岗位为社招"},
        {"company": "太原科技大学", "append": "10.2最新岗位为社招"}
    ]

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "company-basic" in pg.url:
                    page = pg
                    break
            if page:
                break
                
        if not page:
            raise Exception("未找到 company-basic 页面")

        for t in tasks:
            try:
                append_remark_to_company(page, t["company"], t["append"])
            except Exception as e:
                print(f"❌ 失败: {t['company']} - {e}")
                close_all_dialogs(page)
