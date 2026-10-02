"""
业务操作自动化模块（全量版）：
目标：全量自动识别符合条件的企业（公众号网址 + 包含27届 + 审计时间非今日），
      自动遍历所有分页，逐一点击行内【标注】按钮，并在弹出的【标注信息】弹窗中直接点击【确 定】保存。
"""
import asyncio
import json
import math
from datetime import datetime
from playwright.async_api import async_playwright

def is_target_company(item: dict) -> bool:
    """
    判定单家企业是否同时满足 3 大业务条件：
    1. 公告网址包含 'mp.weixin.qq.com'
    2. 标注届数包含 '27'（27届）
    3. 审计时间不是今日（以当前系统日期判断）
    """
    # 1. 检查公告网址
    posting_url = item.get("posting_url") or ""
    if not posting_url and item.get("job_posting"):
        sorted_posts = sorted(item["job_posting"], key=lambda x: x.get("pub_time") or "", reverse=True)
        posting_url = sorted_posts[0].get("url") or ""
    
    if "mp.weixin.qq.com" not in posting_url:
        return False

    # 2. 检查届数是否包含 27
    grades = item.get("grade") or []
    has_27 = False
    if isinstance(grades, list):
        has_27 = (27 in grades) or any("27" in str(g) for g in grades)
    elif isinstance(grades, str):
        has_27 = "27" in grades
    if not has_27:
        return False

    # 3. 检查审计时间是否不是今日
    today_str = datetime.now().strftime("%Y-%m-%d")
    operators = item.get("operator") or []
    if operators:
        sorted_ops = sorted(operators, key=lambda x: x.get("timestamp") or "")
        latest_time = sorted_ops[-1].get("timestamp") or ""
        if latest_time.startswith(today_str):
            return False  # 今日已审计过，排除

    return True


async def annotate_and_confirm(page, company_name: str) -> bool:
    """
    核心原子操作：
    1. 在当前页表格中精确定位公司所在行
    2. 点击行内【标注】按钮
    3. 等待【标注信息】弹窗显现
    4. 点击弹窗底部【确 定】按钮（直接子代选择器避开嵌套弹窗冲突）
    5. 监听后端 update_manual 接口返回 code: 0，等待弹窗彻底消失
    """
    print(f"\n  [执行] 目标企业: {company_name}", flush=True)

    # 1. 查找目标企业所在的行
    row = page.locator(".el-table__body-wrapper tbody tr").filter(
        has=page.locator(f"td:has-text('{company_name}')")
    ).first

    if await row.count() == 0:
        print(f"    ❌ 当前页面未找到包含 [{company_name}] 的表格行！", flush=True)
        return False

    annotate_btn = row.locator("button:has-text('标注')").first
    if await annotate_btn.count() == 0:
        print(f"    ❌ 该行未找到【标注】按钮！", flush=True)
        return False

    # 2. 点击【标注】并等待主弹窗显现
    await annotate_btn.click()
    dialog_wrapper = page.locator(".el-dialog__wrapper:not([style*='display: none'])").filter(
        has=page.locator(".el-dialog__title:text-is('标注信息')")
    ).first

    try:
        await dialog_wrapper.wait_for(state="visible", timeout=5000)
    except Exception:
        print("    ❌ 标注弹窗未能在 5 秒内弹出！", flush=True)
        return False

    # 3. 定位主弹窗底部的【确 定】按钮
    confirm_btn = page.locator(
        ".el-dialog:has(.el-dialog__title:text-is('标注信息')) > .el-dialog__footer button.el-button--primary:has-text('确 定')"
    ).first

    if await confirm_btn.count() == 0:
        print("    ❌ 未定位到【确 定】按钮！", flush=True)
        return False

    # 4. 点击【确 定】并监听保存接口 update_manual 响应
    save_success = False
    try:
        async with page.expect_response(
            lambda res: "company/basic/update_manual" in res.url and res.request.method == "POST",
            timeout=8000
        ) as response_info:
            await confirm_btn.click()
        
        resp = await response_info.value
        res_json = await resp.json()
        if res_json.get("code") == 0:
            save_success = True
            print(f"    ✔ 保存成功 (update_manual -> code: 0)", flush=True)
        else:
            print(f"    ⚠ 后端返回异常: {res_json}", flush=True)
    except Exception as e:
        print(f"    ❌ 等待保存接口超时或出错: {e}", flush=True)
        return False

    # 5. 等待弹窗完全关闭
    try:
        await dialog_wrapper.wait_for(state="hidden", timeout=5000)
    except Exception:
        # 如遇未正常隐藏，调用组件变量直接强制重置
        await page.evaluate("""() => {
            const form = document.querySelector('.el-form');
            if (form && form.__vue__) form.__vue__.$parent.showLabelDialog = false;
        }""")

    await asyncio.sleep(0.4)
    print(f"    ✔ [{company_name}] 标注保存完成！", flush=True)
    return save_success


async def run_full_batch(page, page_size: int = 50):
    """
    全量自动化执行调度：
    1. 自动切换每页显示数量（默认 50 条，极速收敛页数）
    2. 计算总页数，逐页遍历
    3. 每页自动扫描命中目标，顺序执行标注并确认
    4. 自动翻页直到最后一页全部处理完毕
    """
    print("=" * 60, flush=True)
    print(f"🚀 开始启动【全量企业自动化标注与确定】流程...", flush=True)
    print("=" * 60, flush=True)

    # 1. 确保每页条数设为 page_size (如 50)
    current_size = await page.evaluate("() => document.querySelector('.el-form').__vue__.$parent.pageSize")
    if current_size != page_size:
        print(f"⚙ 切换每页展示数量为 {page_size} 条...", flush=True)
        async with page.expect_response(lambda res: "company/basic/all" in res.url and res.request.method == "POST"):
            await page.evaluate(f"() => document.querySelector('.el-form').__vue__.$parent.pageSizeChange({page_size})")
        await asyncio.sleep(1)

    # 2. 获取总记录数与总页数
    page_info = await page.evaluate("""() => {
        const vm = document.querySelector('.el-form').__vue__.$parent;
        return {
            currentPage: vm.currentPage,
            pageSize: vm.pageSize,
            totalRecords: vm.totalRecords
        };
    }""")

    total_records = page_info["totalRecords"]
    page_size = page_info["pageSize"]
    total_pages = math.ceil(total_records / page_size) if total_records > 0 else 1

    print(f"📊 当前筛选总记录数: {total_records} 条，共 {total_pages} 页（每页 {page_size} 条）\n", flush=True)

    total_processed = 0
    total_success = 0

    # 3. 逐页循环处理
    for p_idx in range(1, total_pages + 1):
        # 若不在当前循环页，则执行翻页
        cur_p = await page.evaluate("() => document.querySelector('.el-form').__vue__.$parent.currentPage")
        if cur_p != p_idx:
            print(f"\n📄 正在翻至第 {p_idx} / {total_pages} 页...", flush=True)
            async with page.expect_response(lambda res: "company/basic/all" in res.url and res.request.method == "POST"):
                await page.evaluate(f"() => document.querySelector('.el-form').__vue__.$parent.pageChange({p_idx})")
            await asyncio.sleep(1)

        # 读取当前页 Vue 表格数据
        table_data = await page.evaluate("""() => {
            const table = document.querySelector('.el-table');
            if (!table || !table.__vue__) return [];
            return table.__vue__.data || [];
        }""")

        targets = [item for item in table_data if is_target_company(item)]
        print(f"--- [第 {p_idx} 页] 共 {len(table_data)} 家企业，命中目标企业 {len(targets)} 家 ---", flush=True)

        if not targets:
            print("  （本页无符合条件的企业，自动跳过）", flush=True)
            continue

        # 逐个处理当前页目标
        for idx, t in enumerate(targets, 1):
            name = t.get("name")
            print(f"[{idx}/{len(targets)}]", end="", flush=True)
            ok = await annotate_and_confirm(page, name)
            total_processed += 1
            if ok:
                total_success += 1
            await asyncio.sleep(0.5)

    print("\n" + "=" * 60, flush=True)
    print(f"🎉 全量处理大功告成！", flush=True)
    print(f"   总计命中处理: {total_processed} 家", flush=True)
    print(f"   成功确认保存: {total_success} 家", flush=True)
    print("=" * 60, flush=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://127.0.0.1:9222")
        page = None
        for ctx in browser.contexts:
            for pg in ctx.pages:
                if "company-basic" in pg.url:
                    page = pg
                    break
        if not page:
            print("❌ 未找到已打开的 JobLeap 公司列表页面！", flush=True)
            return

        print(f"✔ 成功连接至浏览器，当前页面: {page.url}", flush=True)
        
        # 启动全量自动化处理（自动设为每页50条，自动跨页循环）
        await run_full_batch(page, page_size=50)

if __name__ == "__main__":
    asyncio.run(main())
