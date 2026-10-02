import asyncio
import re
import json
import math
from playwright.async_api import async_playwright

# 严格跳过的 7 家异常企业
EXCLUDE_COMPANIES = {
    "华勤橡胶工业集团有限公司",
    "北京航空航天大学",
    "北京中医药大学",
    "南京农业大学",
    "前锦网络信息技术（上海）有限公司长沙分公司",
    "江西省人力资源和社会保障厅",
    "湖南五新智能装备集团股份有限公司"
}

def is_target_company(note: str) -> bool:
    """判断是否为目标批次企业（备注包含'自动新增公告链接，须核查'）"""
    if not note:
        return False
    return "自动新增公告链接，须核查" in str(note)

def has_one_in_note(note: str) -> bool:
    """判断备注是否已经带有 1 或已处理标记"""
    if not note:
        return False
    n = str(note).strip()
    return "1" in n or n.endswith("1")

async def close_dialog_if_open(page):
    try:
        await page.evaluate("""() => {
            const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper'));
            for (const w of wrappers) {
                if (w.style.display !== 'none' && getComputedStyle(w).display !== 'none') {
                    const btn = w.querySelector('.el-dialog__headerbtn, button.el-button--default');
                    if (btn) btn.click();
                }
            }
            const form = document.querySelector('.el-form');
            if (form && form.__vue__ && form.__vue__.$parent) {
                form.__vue__.$parent.showLabelDialog = false;
            }
        }""")
        await page.wait_for_timeout(500)
    except Exception:
        pass

async def annotate_single_row(page, row_data: dict, row_locator) -> bool:
    company_name = row_data.get("name", "")
    current_note = (row_data.get("note") or "").strip()
    
    # 1. 安全检查 1：异常企业黑名单
    if company_name in EXCLUDE_COMPANIES:
        print(f"    🚫 [跳过异常] {company_name} (属于审计异常企业，保持未追加状态)", flush=True)
        return False

    # 2. 安全检查 2：是否为目标企业
    if not is_target_company(current_note):
        print(f"    ⏭ [跳过非目标] {company_name} (备注不是'自动新增公告链接，须核查': '{current_note}')", flush=True)
        return False

    # 3. 安全检查 3：备注是否已经带 1
    if has_one_in_note(current_note):
        print(f"    ⏩ [跳过已办] {company_name} (备注已包含1: '{current_note}')", flush=True)
        return False

    # 4. 定位行内的【标注】按钮并滚动到可视区域
    annotate_btn = row_locator.locator("button:has-text('标注')").first
    if await annotate_btn.count() == 0:
        print(f"    ❌ 未找到【标注】按钮: {company_name}", flush=True)
        return False

    try:
        await annotate_btn.scroll_into_view_if_needed()
        await annotate_btn.click()
        main_dialog = page.locator(".el-dialog__wrapper:not([style*='display: none']) .el-dialog:has(.el-dialog__title:has-text('标注信息'))").first
        await main_dialog.wait_for(state="visible", timeout=4000)
    except Exception as e:
        print(f"    ❌ 弹窗打开失败: {company_name} ({e})", flush=True)
        await close_dialog_if_open(page)
        return False

    # 5. 双重保险：检查弹窗中的当前备注
    remark_textarea = main_dialog.locator("textarea[placeholder='请输入备注信息']").first
    modal_note = (await remark_textarea.input_value()).strip()
    if has_one_in_note(modal_note):
        print(f"    ⏩ [弹窗内复核跳过] {company_name} (弹窗内备注已带1: '{modal_note}')", flush=True)
        cancel_btn = main_dialog.locator(".el-dialog__footer button:has-text('取 消'), button.el-dialog__headerbtn").first
        await cancel_btn.click()
        await page.wait_for_timeout(400)
        return False

    # 6. 选择网申开始时间快捷项【公告发布日期】
    try:
        start_time_input = main_dialog.locator("input[placeholder='请选择网申开始时间']").first
        await start_time_input.click()
        await page.wait_for_timeout(300)

        shortcut_btn = page.locator(".el-picker-panel:visible button.el-picker-panel__shortcut:has-text('公告发布日期')").first
        if await shortcut_btn.count() > 0:
            await shortcut_btn.click()
            await page.wait_for_timeout(300)
            new_date = await start_time_input.input_value()
        else:
            new_date = await start_time_input.input_value()
            print(f"    ℹ [提示] {company_name} 未出现快捷选项，维持当前值: {new_date}", flush=True)

        # 7. 备注追加 1
        new_note = f"{modal_note}1"
        await remark_textarea.fill(new_note)

        # 8. 点击【确 定】保存并监听响应
        confirm_btn = main_dialog.locator(".el-dialog__footer button.el-button--primary:has-text('确 定')").last
        
        async with page.expect_response(lambda r: "update_manual" in r.url and r.status == 200, timeout=10000) as resp_info:
            await confirm_btn.click()
        
        resp = await resp_info.value
        resp_json = await resp.json()
        if resp_json.get("code") == 0:
            print(f"    ✔ [成功] {company_name} -> 开始时间:{new_date} | 备注更新为:'{new_note}'", flush=True)
            # 等待弹窗关闭，若未关闭则调用兜底关闭
            try:
                await main_dialog.wait_for(state="hidden", timeout=1500)
            except Exception:
                await close_dialog_if_open(page)
            await page.wait_for_timeout(400)
            return True
        else:
            print(f"    ⚠ [失败] {company_name} -> 后端返回: {resp_json}", flush=True)
            await close_dialog_if_open(page)
            return False

    except Exception as e:
        print(f"    ❌ [异常] {company_name} -> {e}", flush=True)
        await close_dialog_if_open(page)
        return False
    finally:
        # 兜底确保无论任何情况遮罩弹窗都被清理，不影响后续行的点击
        try:
            is_dialog_vis = await page.evaluate("""() => {
                const w = document.querySelector('.el-dialog__wrapper:not([style*="display: none"])');
                return !!w && getComputedStyle(w).display !== 'none';
            }""")
            if is_dialog_vis:
                await close_dialog_if_open(page)
        except Exception:
            pass

async def run_batch_process(start_page: int = 2, end_page: int = 6):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        context = browser.contexts[0]
        
        page = None
        for pg in context.pages:
            if "company-basic" in pg.url:
                page = pg
                break
        
        if not page:
            print("❌ 未找到 company-basic 页面！", flush=True)
            return

        print("=" * 60, flush=True)
        print("🚀 开始执行：公告开始时间同步 + 备注追加1（严格防重与风控版）", flush=True)
        print(f"   处理页码范围: 第 {start_page} 页 ~ 第 {end_page} 页 (每页 50 条)", flush=True)
        print(f"   风控规则: ① 备注已包含 '1' 自动跳过; ② 7 家严重异常企业坚决跳过; ③ 非目标备注跳过", flush=True)
        print("=" * 60, flush=True)

        # 1. 先清空搜索输入框，恢复完整表格视图
        print("\n🔄 检查并重置搜索筛选条件...", flush=True)
        labels = await page.locator(".el-form-item__label").all()
        for l in labels:
            t = await l.inner_text()
            if "名称" in t:
                inp = l.locator("xpath=..//input").first
                cur_val = await inp.input_value()
                if cur_val:
                    await inp.fill("")
                    search_btn = page.locator("button.el-button--primary:has-text('搜索')").first
                    async with page.expect_response(lambda r: "company/basic/all" in r.url and r.status == 200, timeout=10000):
                        await search_btn.click()
                    await page.wait_for_timeout(1000)
                    print("✔ 已清空搜索框并刷新表格", flush=True)
                break

        # 2. 确保每页条数设为 50 条
        cur_page_size = await page.evaluate("() => document.querySelector('.el-table').__vue__.$parent.pageSize")
        if cur_page_size != 50:
            print("⚙ 调整每页展示数量为 50 条...", flush=True)
            async with page.expect_response(lambda r: "company/basic/all" in r.url and r.status == 200, timeout=10000):
                await page.evaluate("() => document.querySelector('.el-table').__vue__.$parent.pageSizeChange(50)")
            await page.wait_for_timeout(1000)

        stats = {
            "success": 0,
            "skipped_has_one": 0,
            "skipped_abnormal": 0,
            "skipped_non_target": 0,
            "failed": 0
        }

        # 3. 逐页循环处理
        for p_no in range(start_page, end_page + 1):
            print(f"\n==================== 正在处理第 {p_no} / {end_page} 页 ====================", flush=True)
            
            # 翻页
            cur_p = await page.evaluate("() => document.querySelector('.el-table').__vue__.$parent.currentPage")
            if cur_p != p_no:
                print(f"📄 翻页至第 {p_no} 页...", flush=True)
                async with page.expect_response(lambda r: "company/basic/all" in r.url and r.status == 200, timeout=10000):
                    await page.evaluate(f"() => document.querySelector('.el-table').__vue__.$parent.pageChange({p_no})")
                await page.wait_for_timeout(1000)

            # 获取当前页的表格数据列表
            table_data = await page.evaluate("() => document.querySelector('.el-table').__vue__.$parent.tableData")
            print(f"✔ 第 {p_no} 页加载成功，共 {len(table_data)} 条记录", flush=True)

            # 遍历当前页记录
            for idx, item in enumerate(table_data):
                cname = item.get("name", "")
                note = (item.get("note") or "").strip()

                # 快速前置过滤
                if cname in EXCLUDE_COMPANIES:
                    print(f"  [{idx+1}/50] 🚫 [跳过异常] {cname}", flush=True)
                    stats["skipped_abnormal"] += 1
                    continue

                if not is_target_company(note):
                    print(f"  [{idx+1}/50] ⏭ [跳过非目标] {cname} (备注: '{note}')", flush=True)
                    stats["skipped_non_target"] += 1
                    continue

                if has_one_in_note(note):
                    # 已带 1 跳过
                    print(f"  [{idx+1}/50] ⏩ [跳过已办] {cname} (当前备注已含1: '{note}')", flush=True)
                    stats["skipped_has_one"] += 1
                    continue

                # 需要处理的目标企业
                print(f"  [{idx+1}/50] 👉 [执行更新] {cname} (原备注: '{note}')", flush=True)
                
                # 在 DOM 中精准定位对应行
                row_loc = page.locator(".el-table__body-wrapper tbody tr").nth(idx)
                row_text = await row_loc.inner_text()
                if cname not in row_text:
                    all_rows = page.locator(".el-table__body-wrapper tbody tr")
                    count = await all_rows.count()
                    for r_i in range(count):
                        t = await all_rows.nth(r_i).inner_text()
                        if cname in t:
                            row_loc = all_rows.nth(r_i)
                            break

                ok = await annotate_single_row(page, item, row_loc)
                if ok:
                    stats["success"] += 1
                else:
                    stats["failed"] += 1

                # 适当间隔防止请求过密
                await page.wait_for_timeout(350)

        print("\n" + "=" * 60, flush=True)
        print("🎉 批量处理流程全部完成！统计结果如下：", flush=True)
        print(f"   ✔ 成功更新数量: {stats['success']} 家", flush=True)
        print(f"   ⏩ 跳过已处理数量 (备注已含1): {stats['skipped_has_one']} 家", flush=True)
        print(f"   🚫 跳过异常企业数量 (风控黑名单): {stats['skipped_abnormal']} 家", flush=True)
        print(f"   ⏭ 跳过非目标企业数量: {stats['skipped_non_target']} 家", flush=True)
        print(f"   ❌ 处理失败/异常数量: {stats['failed']} 家", flush=True)
        print("=" * 60, flush=True)

if __name__ == "__main__":
    asyncio.run(run_batch_process(2, 6))
