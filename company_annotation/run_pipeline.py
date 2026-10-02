"""
全自动批处理与数据提纯流水线 (Pipeline)：
贯穿 6 大业务情形：
1. 自动切换情形筛选条件；
2. 自动就地识别并执行【公众号推文 + 27届 + 非今日审计】企业的标注并保存确认；
3. 重新拉取最新数据，天然剔除已完成的企业；
4. 输出最终提纯的 8 字段待办清单至 clean_scenario_1.json ~ clean_scenario_6.json。
"""
import sys
import os
import asyncio
import json
import math
import time
from datetime import datetime
from playwright.async_api import async_playwright

from fast_filter import apply_filter, parse_company_record, SCENARIO_CONFIGS
from auto_annotator import is_target_company, annotate_and_confirm

OUTPUT_DIR = r"D:\100_Work\101_Program\Proj\XHS\company_annotation"

async def auto_annotate_current_scenario(page, page_size: int = 50) -> dict:
    """
    在当前已筛选的情形下，执行全量翻页标注并保存
    """
    # 1. 确保每页条数设为 page_size (50)
    current_size = await page.evaluate("() => document.querySelector('.el-form').__vue__.$parent.pageSize")
    if current_size != page_size:
        async with page.expect_response(lambda res: "company/basic/all" in res.url and res.request.method == "POST"):
            await page.evaluate(f"() => document.querySelector('.el-form').__vue__.$parent.pageSizeChange({page_size})")
        await asyncio.sleep(0.8)

    # 2. 读取总数并计算总页数
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

    processed = 0
    success = 0

    for p_idx in range(1, total_pages + 1):
        cur_p = await page.evaluate("() => document.querySelector('.el-form').__vue__.$parent.currentPage")
        if cur_p != p_idx:
            async with page.expect_response(lambda res: "company/basic/all" in res.url and res.request.method == "POST"):
                await page.evaluate(f"() => document.querySelector('.el-form').__vue__.$parent.pageChange({p_idx})")
            await asyncio.sleep(0.8)

        # 读取当前页数据
        table_data = await page.evaluate("""() => {
            const table = document.querySelector('.el-table');
            if (!table || !table.__vue__) return [];
            return table.__vue__.data || [];
        }""")

        targets = [item for item in table_data if is_target_company(item)]
        if not targets:
            continue

        print(f"    [第 {p_idx}/{total_pages} 页] 命中目标 {len(targets)} 家，开始自动确认...", flush=True)
        for idx, t in enumerate(targets, 1):
            name = t.get("name")
            print(f"      [{idx}/{len(targets)}]", end="", flush=True)
            ok = await annotate_and_confirm(page, name)
            processed += 1
            if ok:
                success += 1
            await asyncio.sleep(0.4)

    return {"processed": processed, "success": success}

async def fetch_remaining_clean_records(page, scenario_id: int) -> list:
    """
    拉取当前情形的全部数据，并剔除掉所有已满足 (公众号 + 27届 + 今日已审计) 的企业，
    只保留真正需要后续处理或人工关注的纯净待办清单。
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 利用 apply_filter 的底层并发拉取逻辑获取全量
    res = await apply_filter(page, scenario_id, fetch_all=True)
    all_raw = res["api_results"]

    todo_records = []
    for item in all_raw:
        posting_url = item.get("posting_url") or ""
        grades = item.get("grade") or []
        has_27 = (27 in grades) if isinstance(grades, list) else ("27" in str(grades))

        # 检查是否今日已审计
        operators = item.get("operator") or []
        audited_today = False
        if operators:
            sorted_ops = sorted(operators, key=lambda x: x.get("timestamp") or "")
            latest_time = sorted_ops[-1].get("timestamp") or ""
            audited_today = latest_time.startswith(today_str)

        # 剔除条件：如果是标准微信推文 + 27届 + 今日已完成审计，则属于已处理完毕，不纳入待办
        if "mp.weixin.qq.com" in posting_url and has_27 and audited_today:
            continue

        todo_records.append(parse_company_record(item))

    return todo_records

async def run_pipeline():
    start_total_time = time.time()
    summary_report = []

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

        print("=" * 65, flush=True)
        print("🚀 启动【1-6 情形全自动化标注确认与待办数据提纯流水线】", flush=True)
        print("=" * 65, flush=True)

        for sid in range(1, 7):
            cfg = SCENARIO_CONFIGS.get(sid, {})
            s_name = cfg.get("name", f"情形 {sid}")
            print(f"\n▶ 正在处理【情形 {sid}】：{s_name}", flush=True)

            # 步骤 1：应用该情形筛选
            print("  [1/3] 应用筛选条件...", flush=True)
            await apply_filter(page, sid, fetch_all=False)
            await asyncio.sleep(0.5)

            # 步骤 2：就地执行自动标注与保存（公众号 + 27届 + 非今日审计）
            print("  [2/3] 扫描并自动处理符合条件的目标企业...", flush=True)
            auto_res = await auto_annotate_current_scenario(page, page_size=50)
            print(f"  ✔ 自动确认完毕：处理 {auto_res['processed']} 家，成功保存 {auto_res['success']} 家", flush=True)

            # 步骤 3：拉取剔除后的纯净待办数据并保存 JSON
            print("  [3/3] 拉取提纯数据并导出待办 JSON...", flush=True)
            clean_todos = await fetch_remaining_clean_records(page, sid)
            json_path = os.path.join(OUTPUT_DIR, f"clean_scenario_{sid}.json")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(clean_todos, f, ensure_ascii=False, indent=2)

            print(f"  ✔ 待办 JSON 已导出：{json_path} (剩余待办企业: {len(clean_todos)} 家)", flush=True)

            summary_report.append({
                "sid": sid,
                "name": s_name,
                "auto_done": auto_res["success"],
                "todo_count": len(clean_todos),
                "json_file": f"clean_scenario_{sid}.json"
            })

    total_duration = time.time() - start_total_time
    print("\n" + "=" * 65, flush=True)
    print(f"🎉 1-6 全情形流水线执行完毕！总耗时: {total_duration:.1f} 秒", flush=True)
    print("=" * 65, flush=True)
    print(f"{'情形':<8}{'名称':<32}{'自动标注入库':<12}{'剩余待办':<10}{'输出文件'}")
    print("-" * 65)
    for rep in summary_report:
        print(f"情形 {rep['sid']:<4}{rep['name']:<30}{rep['auto_done']:<14}{rep['todo_count']:<10}{rep['json_file']}")
    print("=" * 65, flush=True)

if __name__ == "__main__":
    asyncio.run(run_pipeline())
