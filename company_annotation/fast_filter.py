import sys
import asyncio
import json
import time
from playwright.async_api import async_playwright

SCENARIO_CONFIGS = {
    1: {
        "name": "校招 + 爬取一天内 + 网申一月前",
        "desc": "国内所有企业（排除境外企业）| 岗位类型:校招 | 岗位爬取:一天内 | 网申开始:一月前"
    },
    2: {
        "name": "校招 + 爬取一天内 + 关联公告未关联",
        "desc": "国内所有企业（排除境外企业）| 岗位类型:校招 | 岗位爬取:一天内 | 关联公告:未关联"
    },
    3: {
        "name": "校招 + 爬取一天内 + 届数未标注/26届/25届",
        "desc": "国内所有企业（排除境外企业）| 岗位类型:校招 | 岗位爬取:一天内 | 届数:未标注,26届,25届"
    },
    4: {
        "name": "校招 + 爬取前一日和当天 + 网申一月前",
        "desc": "国内所有企业（排除境外企业）| 岗位类型:校招 | 岗位爬取:前一日和当天 | 网申开始:一月前"
    },
    5: {
        "name": "校招 + 爬取前一日和当天 + 关联公告未关联",
        "desc": "国内所有企业（排除境外企业）| 岗位类型:校招 | 岗位爬取:前一日和当天 | 关联公告:未关联"
    },
    6: {
        "name": "校招 + 爬取前一日和当天 + 届数未标注/26届/25届",
        "desc": "国内所有企业（排除境外企业）| 岗位类型:校招 | 岗位爬取:前一日和当天 | 届数:未标注,26届,25届"
    }
}

def parse_company_record(item: dict) -> dict:
    """提取用户指定的 8 个核心字段"""
    name = item.get("name") or (item.get("keywords") and item.get("keywords")[0]) or ""
    
    # 公告信息（标题与网址）
    posting_url = item.get("posting_url") or ""
    job_postings = item.get("job_posting") or []
    post_title = ""
    latest_post_url = posting_url

    # 若已关联 posting_url，优先从候选池匹配其标题
    if posting_url and job_postings:
        matched = next((p for p in job_postings if p.get("url") == posting_url), None)
        if matched:
            post_title = matched.get("title") or ""

    # 若未找到标题或未关联，则取候选池按时间最新的公告
    if not post_title and job_postings:
        sorted_posts = sorted(job_postings, key=lambda x: x.get("pub_time") or "", reverse=True)
        newest = sorted_posts[0]
        post_title = newest.get("title") or ""
        if not latest_post_url:
            latest_post_url = newest.get("url") or ""

    # 开始时间
    publish_date = item.get("publish_date") or ""

    # 标注届数
    grade_list = item.get("grade") or []
    if isinstance(grade_list, list):
        grades_str = ", ".join(f"{g}届" if isinstance(g, int) and g > 0 else "未标注" if g == -1 else str(g) for g in grade_list)
    else:
        grades_str = str(grade_list)

    # 最近审计员与对应的审计时间
    operators = item.get("operator") or []
    latest_auditor = ""
    latest_audit_time = ""
    if operators:
        sorted_ops = sorted(operators, key=lambda x: x.get("timestamp") or "")
        latest_op = sorted_ops[-1]
        latest_auditor = latest_op.get("username") or ""
        latest_audit_time = latest_op.get("timestamp") or ""

    # 备注 note
    note = item.get("note") or ""

    return {
        "公司名称": name,
        "最新一条的公告标题": post_title,
        "公告网址": latest_post_url,
        "开始时间": publish_date,
        "标注的届数": grades_str,
        "最近审计员": latest_auditor,
        "审计时间": latest_audit_time,
        "备注": note
    }

async def apply_filter(page, scenario_id: int, fetch_all: bool = True):
    """
    一键应用指定的筛选条件（终极稳健方案）：
    1. 彻底深度清空所有干扰字段；
    2. DOM 点击展开类型面板，精准勾选除【境外企业】外的全部 17 项，UI 完美呈现 [央企 + 16]；
    3. 固定校招并根据场景设置专属字段；
    4. 触发搜索并确保列表刷新。
    """
    captured = {}
    done_event = asyncio.Event()

    def on_request(req):
        if "company/basic/all" in req.url and req.method == "POST":
            captured["payload"] = json.loads(req.post_data) if req.post_data else {}

    async def on_response(res):
        if "company/basic/all" in res.url and res.request.method == "POST":
            try:
                captured["res"] = await res.json()
            except Exception:
                pass
            done_event.set()

    page.on("request", on_request)
    page.on("response", on_response)

    start_time = time.time()

    # 1. 彻底清空所有历史条件
    await page.evaluate("""() => {
        const form = document.querySelector('.el-form');
        if (!form || !form.__vue__) return;
        const vm = form.__vue__.$parent;

        vm.resetFilterData();
        vm.posting_publish_date = null;
        vm.position_spider_date = null;
        vm.position_update_date = null;
        vm.grade = [];
        vm.positing_exist = null;
        vm.interval = null;
        vm.companyName = null;
        vm.creditCode = null;
    }""")
    await asyncio.sleep(0.3)

    # 2. 点击展开类型下拉，通过 DOM 勾选除境外企业外的 17 项
    cascader = page.locator(".el-form-item:has(.el-form-item__label:has-text('类型')) .el-cascader").first
    await cascader.click()
    await asyncio.sleep(0.4)

    dropdown = page.locator(".el-cascader__dropdown:not([style*='display: none'])")
    nodes = dropdown.locator(".el-cascader-node")
    count = await nodes.count()
    for i in range(count):
        node = nodes.nth(i)
        label = (await node.locator(".el-cascader-node__label").inner_text()).strip()
        cb = node.locator(".el-checkbox")
        is_checked = "is-checked" in (await cb.get_attribute("class") or "")
        if label == "境外企业":
            if is_checked:
                await cb.click()
        else:
            if not is_checked:
                await cb.click()

    # 按 Escape 收起类型下拉
    await page.keyboard.press("Escape")
    await asyncio.sleep(0.3)

    # 3. 设置业务专属筛选条件并触发搜索（使用 Vue 内置快捷逻辑与数据模型，免除弹窗冲突）
    await page.evaluate("""(sid) => {
        const form = document.querySelector('.el-form');
        const vm = form.__vue__.$parent;

        // 固定校招
        vm.cls = [0];

        // 爬取时间设置
        const isTwoDays = (sid === 4 || sid === 5 || sid === 6);
        if (isTwoDays) {
            const end = new Date();
            end.setHours(23, 59, 59, 999);
            const start = new Date();
            start.setDate(start.getDate() - 1);
            start.setHours(0, 0, 0, 0);
            vm.position_spider_date = [start, end];
        } else {
            const s1 = vm.spiderDatePickerOptions.shortcuts.find(s => s.text === '一天内');
            if (s1) s1.onClick({ $emit: (e, val) => { vm.position_spider_date = val; } });
        }

        // 专属情形字段配置
        if (sid === 1 || sid === 4) {
            // 网申开始时间：一月前
            const s2 = vm.publishDatePickerOptions.shortcuts.find(s => s.text === '一月前');
            if (s2) s2.onClick({ $emit: (e, val) => { vm.posting_publish_date = val; } });
        } else if (sid === 2 || sid === 5) {
            // 关联公告：未关联
            vm.positing_exist = false;
        } else if (sid === 3 || sid === 6) {
            // 网申届数：未标注(-1), 26届(26), 25届(25)
            vm.grade = [-1, 26, 25];
        }

        // 触发查询
        vm.searchClick();
    }""", scenario_id)

    # 等待接口响应
    try:
        await asyncio.wait_for(done_event.wait(), timeout=8.0)
    except asyncio.TimeoutError:
        pass

    duration = time.time() - start_time

    page.remove_listener("request", on_request)
    page.remove_listener("response", on_response)

    # 安全收起所有浮层，并滚回顶部
    await page.keyboard.press("Escape")
    await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.3)

    # 从 API 响应中提取纯正结构化数据
    api_json = captured.get("res", {})
    api_data = api_json.get("data", {}) if isinstance(api_json.get("data"), dict) else {}
    api_total = api_data.get("count", 0)
    api_results = api_data.get("results", [])

    # 提取渲染后的 DOM 数据行
    result_info = await page.evaluate("""() => {
        const form = document.querySelector('.el-form');
        const vm = form.__vue__.$parent;
        const rows = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map(tr => {
            const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            return {
                id: tds[0] || '',
                name: tds[1] || '',
                shortName: tds[2] || '',
                type: tds[3] || '',
                industry: tds[4] || '',
                websiteCount: tds[7] || ''
            };
        });
        return {
            total: vm.totalRecords,
            page: vm.currentPage,
            rows: rows.filter(r => r.name && r.name !== '暂无数据')
        };
    }""")

    # 3. 若启用全量获取 (fetch_all=True) 且总数 > 10，直接在页面上下文中利用原生鉴权并发拉取所有页
    all_raw_results = list(api_results)
    if fetch_all and api_total and api_total > len(api_results) and captured.get("payload"):
        exact_payload = captured["payload"]
        additional_results = await page.evaluate("""async ({ exactPayload, totalCount }) => {
            const form = document.querySelector('.el-form');
            const vm = form.__vue__.$parent;
            const token = vm.getHeaderToken ? vm.getHeaderToken() : null;

            const pageSize = 50;
            const totalPages = Math.ceil(totalCount / pageSize);

            // 从第 1 页到最后一页并发拉取完整集合
            const fetchTasks = [];
            for (let p = 1; p <= totalPages; p++) {
                fetchTasks.push((async (pageIdx) => {
                    const bodyObj = Object.assign({}, exactPayload, { page: pageIdx, page_size: pageSize });
                    const resp = await fetch('https://www.tatawangshen.com/api/recruit/company/basic/all', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': token || ''
                        },
                        body: JSON.stringify(bodyObj)
                    });
                    const j = await resp.json();
                    return (j.data && j.data.results) || [];
                })(p));
            }

            const pagesData = await Promise.all(fetchTasks);
            const merged = [];
            for (const pList of pagesData) {
                merged.push(...pList);
            }
            return merged;
        }""", {"exactPayload": exact_payload, "totalCount": api_total})

        # 按 _id 或 name 去重合并
        seen_ids = set()
        deduped = []
        for item in additional_results:
            iid = item.get("_id") or item.get("name")
            if iid not in seen_ids:
                seen_ids.add(iid)
                deduped.append(item)
        all_raw_results = deduped

    # 提纯出用户指定的 8 大核心业务字段 (全量)
    clean_records = [parse_company_record(item) for item in all_raw_results]

    return {
        "scenario_id": scenario_id,
        "config": SCENARIO_CONFIGS.get(scenario_id, {}),
        "duration": duration,
        "payload": captured.get("payload", {}),
        "api_response": api_json,
        "api_results": all_raw_results,
        "clean_records": clean_records,
        "total": api_total if api_total is not None else result_info.get("total", 0),
        "rows": result_info.get("rows", [])
    }

async def run(scenario_id: int):
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        
        page = next((pg for pg in ctx.pages if "company-basic" in pg.url), None)
        if not page:
            page = ctx.pages[0]
            await page.goto("http://admin.jobleap.betaquantity.com/#/company-basic/index", wait_until="domcontentloaded")
            await asyncio.sleep(1.0)

        await page.bring_to_front()

        cfg = SCENARIO_CONFIGS.get(scenario_id, {})
        print(f"\n==================================================")
        print(f"  正在执行【情形 {scenario_id}】：{cfg.get('name')}")
        print(f"  规则细节：{cfg.get('desc')}")
        print(f"==================================================")

        res = await apply_filter(page, scenario_id)

        print(f"\n[OK] 筛选执行成功！(耗时: {res['duration']:.2f}s)")
        print(f"[OK] 命中公司总数: {res['total']} 条")
        
        pl = res.get("payload", {})
        print("\n--- 下发接口参数校验 ---")
        print(f"  * org_type 勾选数量: {len(pl.get('org_type', []))} 项 (排除境外企业)")
        print(f"  * 岗位类型 class: {pl.get('class')}")
        print(f"  * 爬取时间范围: {pl.get('position_spider_time_s', '未限制')} ~ {pl.get('position_spider_time_e', '未限制')}")
        if "publish_date_e" in pl:
            print(f"  * 网申开始时间截止: {pl.get('publish_date_e')}")
        else:
            print("  * 网申开始时间: 未限制 (干净)")
        if "positing_exist" in pl:
            print(f"  * 关联公告状态: {pl.get('positing_exist')}")
        if pl.get("grade"):
            print(f"  * 网申届数: {pl.get('grade')}")

        clean_records = res.get("clean_records", [])
        if clean_records:
            print(f"\n--- [核心 8 字段全量提纯预览] 前 5 条 (本次已全量获取共 {len(clean_records)} 条) ---")
            for idx, r in enumerate(clean_records[:5]):
                print(f"  [{idx+1}] 公司名称: {r['公司名称']}")
                print(f"      最新公告标题: {r['最新一条的公告标题'] or '（未关联）'}")
                print(f"      公告网址: {r['公告网址'] or '（无）'}")
                print(f"      开始时间: {r['开始时间'] or '（未设置）'} | 标注届数: {r['标注的届数'] or '（未设置）'}")
                print(f"      最近审计员: {r['最近审计员'] or '（无）'} | 审计时间: {r['审计时间'] or '（无）'}")
                print(f"      备注 (note): {r['备注'] or '（空）'}")

            # 自动落盘保存提纯版与原始全字段版 JSON 文件
            save_path_clean = f"D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_{scenario_id}.json"
            with open(save_path_clean, "w", encoding="utf-8") as f:
                json.dump(clean_records, f, ensure_ascii=False, indent=2)
            print(f"\n[OK] 已将提纯后的完整全量 JSON ({len(clean_records)}条) 保存至:\n     {save_path_clean}")

            raw_records = res.get("api_results", [])
            if raw_records:
                save_path_raw = f"D:/100_Work/101_Program/Proj/XHS/company_annotation/raw_scenario_{scenario_id}.json"
                with open(save_path_raw, "w", encoding="utf-8") as f:
                    json.dump(raw_records, f, ensure_ascii=False, indent=2)
                print(f"[OK] 已将原始全字段 JSON ({len(raw_records)}条，含候选推文与工商底座) 保存至:\n     {save_path_raw}")

        print(f"\n页面已停留在【情形 {scenario_id}】的筛选结果展示中。\n")
        return res

async def run_all():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = next((pg for pg in ctx.pages if "company-basic" in pg.url), None)
        if not page:
            page = ctx.pages[0]
            await page.goto("http://admin.jobleap.betaquantity.com/#/company-basic/index", wait_until="domcontentloaded")
            await asyncio.sleep(1.0)
        await page.bring_to_front()

        print("\n========================================================")
        print("          开始批量极速全量获取 6 大情形数据...")
        print("========================================================")
        total_all = 0
        for sid in range(1, 7):
            cfg = SCENARIO_CONFIGS[sid]
            print(f"\n>>> 正在全量处理【情形 {sid}】：{cfg['name']}...")
            res = await apply_filter(page, sid, fetch_all=True)
            clean = res.get("clean_records", [])
            save_path = f"D:/100_Work/101_Program/Proj/XHS/company_annotation/clean_scenario_{sid}.json"
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(clean, f, ensure_ascii=False, indent=2)
            print(f"    [OK] 命中总数: {res.get('total')} 条 | 实际全量保存: {len(clean)} 条 -> {save_path}")
            total_all += len(clean)
            await asyncio.sleep(0.5)

        print("\n========================================================")
        print(f"      [全部完成] 6 大情形全部全量抓取完毕，累计保存 {total_all} 条数据！")
        print("========================================================\n")

def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip().lower()
        if arg in ["all", "-a", "--all"]:
            asyncio.run(run_all())
            return
        try:
            sid = int(arg)
            if sid not in SCENARIO_CONFIGS:
                print(f"无效的情形编号: {sid}，请输入 1 ~ 6 或 'all'。")
                sys.exit(1)
            asyncio.run(run(sid))
        except ValueError:
            print("参数错误，请输入数字 1 ~ 6 或 'all'。")
            sys.exit(1)
    else:
        print("\n===== JobLeap 公司列表 6 大筛选情形 =====")
        for k, v in SCENARIO_CONFIGS.items():
            print(f"  [{k}] {v['name']} ({v['desc']})")
        print("  [a] 一键全量获取全部 6 个情形数据 (保存 6 个完整 JSON)")
        choice = input("\n请选择要执行的情形编号 (1-6 或 a) [默认 1]: ").strip().lower()
        if choice in ["a", "all"]:
            asyncio.run(run_all())
        else:
            sid = int(choice) if choice in ["1", "2", "3", "4", "5", "6"] else 1
            asyncio.run(run(sid))

if __name__ == "__main__":
    main()
