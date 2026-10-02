import sys
import time
import json
import argparse
from playwright.sync_api import sync_playwright

CDP_URL = "http://127.0.0.1:9222"

from rpa_engine import (
    INDUSTRY_MAP, ORG_TYPE_MAP, map_guopin_type, map_guopin_industry,
    get_pages, jump_to_page, wait_modal_gone, close_visible_dialogs,
    do_ensure_company, fetch_guopin_meta, do_inspect
)

def resolve_industry(cname, meta_ind):
    if meta_ind and meta_ind != "综合":
        return meta_ind
    if any(k in cname for k in ["新材料", "化工", "能源", "材料", "石油", "石化", "涂料"]):
        return "材料/能源/化工"
    if any(k in cname for k in ["半导体", "芯片", "集成电路", "电子科技", "微电子"]):
        return "硬件/半导体/芯片"
    if any(k in cname for k in ["银行", "保险", "证券", "保理", "资管", "基金", "投资", "金融"]):
        return "金融业"
    if any(k in cname for k in ["设备", "机械", "智能装备", "仪器", "制造", "重工", "模具", "精密"]):
        return "机械/制造业"
    if any(k in cname for k in ["环保", "水务", "固废"]):
        return "环保"
    if any(k in cname for k in ["消防", "总队", "支队", "局", "委员会", "机关"]):
        return "政府机关"
    if any(k in cname for k in ["软件", "网络", "信息技术", "互联", "智能科技"]):
        return "IT/互联网/游戏"
    if any(k in cname for k in ["生物", "医药", "制药", "医疗", "基因"]):
        return "生物/医疗/制药"
    if any(k in cname for k in ["汽车", "零部件", "车业", "智驾"]):
        return "汽车/智能驾驶"
    if any(k in cname for k in ["物流", "供应链", "货运", "仓储"]):
        return "物流/供应链/交通运输"
    return meta_ind or "综合"


def process_one_page(page_site, page_basic, ctx, target_page):
    print(f"\n========================================================")
    print(f"🚀 开始高效闭环第 {target_page} 页国聘任务...")
    print(f"========================================================")

    # 1. 切到目标页
    jump_to_page(page_site, target_page)

    # 2. 扫描本页待办的国聘任务
    rows = page_site.evaluate("""() => {
        const t = document.querySelector('.el-table');
        if (!t || !t.__vue__ || !t.__vue__.data) return [];
        return t.__vue__.data.map((r, i) => ({
            idx: i + 1,
            name: r.name || '',
            task: r.task_name || '',
            cid: r.page_list_url || r.website || '',
            org_type: r.org_type || [],
            industry: r.industry || []
        }));
    }""")

    pending = [r for r in rows if r["task"] == "guopin_v3_spider_task" and not (r["org_type"] and r["industry"])]
    print(f"📋 第 {target_page} 页检视到 {len(pending)} 个待补充国聘任务")
    if not pending:
        print(f"✅ 第 {target_page} 页无待办国聘任务，直接闭环！")
        return True

    # 阶段 1: 网站列表逐行触发系统建档 + 同步抓取原生企业属性
    meta_cache = {}
    page_site.bring_to_front()
    close_visible_dialogs(page_site)

    for idx, it in enumerate(pending, 1):
        name = it["name"]
        cid = it["cid"]
        print(f"\n⚡ [{idx}/{len(pending)}] 处理国聘任务: 【{name}】 (ID: {cid})")

        # 1. 抓取原生属性 (使用已固化的 fetch_guopin_meta)
        gp_url = f"https://www.iguopin.com/company?id={cid}" if not cid.startswith("http") else cid
        meta = fetch_guopin_meta(ctx, gp_url)
        if meta:
            meta_cache[name] = meta

        # 2. 网站列表点【配置】->【确定】触发系统建档
        row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
            has=page_site.locator(f"td:has-text('{cid}')")
        ).first
        if not row.is_visible():
            row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
                has=page_site.locator(f"td:has-text('{name}')")
            ).first

        if row.is_visible():
            wait_modal_gone(page_site)
            cfg_btn = row.locator("button:has-text('配置')").first
            cfg_btn.click(force=True)

            diag = None
            for _ in range(3):
                try:
                    page_site.wait_for_selector(".el-dialog:visible", timeout=2000)
                    diag = page_site.locator(".el-dialog:visible").last
                    if diag.is_visible():
                        break
                except Exception:
                    cfg_btn.click(force=True)
                    page_site.wait_for_timeout(500)

            if diag and diag.is_visible():
                confirm_btn = diag.locator("button:has-text('确 定'), button:has-text('确定')").last
                confirm_btn.click(force=True)
                page_site.wait_for_timeout(800)
                try:
                    msg_box = page_site.locator(".el-message-box:visible").first
                    if msg_box.count() > 0 and msg_box.is_visible():
                        ok_btn = msg_box.locator(".el-message-box__btns button:has-text('确定')").first
                        if ok_btn.count() > 0:
                            ok_btn.click()
                        close_visible_dialogs(page_site)
                except Exception:
                    pass
                wait_modal_gone(page_site)
                page_site.wait_for_timeout(200)
                print(f"  ✅ 平台自动建档与关联已触发完成")

    # 阶段 2: 公司库批量差量补齐
    print(f"\n🏢 [公司库维护] 依次进行差量补齐 (共 {len(pending)} 家)...")
    for it in pending:
        cname = it["name"]
        meta = meta_cache.get(cname, {})
        # 推导规范简称
        short = cname
        for sfx in ["股份有限公司", "有限责任公司", "有限公司", "集团", "（东莞）", "(东莞)", "东莞分行"]:
            short = short.replace(sfx, "")
        short = short.strip()

        ctype = meta.get("type") or "民企"
        raw_ind = meta.get("industry") or ""
        ind = resolve_industry(cname, raw_ind)
        try:
            do_ensure_company(page_basic, cname, short, ctype, ind, location="")
        except Exception as e:
            print(f"  ❌ 公司库维护异常: {cname} ({e})")

    # 阶段 3: 刷新网站列表检验闭环
    print(f"\n🔄 刷新网站列表检验闭环效果...")
    page_site.bring_to_front()
    page_site.reload()
    page_site.wait_for_load_state("networkidle")
    page_site.wait_for_timeout(1000)

    # 重新检验当前页
    do_inspect(page_site, target_page)
    return True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--page", type=int, default=None, help="目标单页")
    parser.add_argument("--start-page", type=int, default=1, help="起始页")
    parser.add_argument("--end-page", type=int, default=1, help="结束页")
    args = parser.parse_args()

    start_p = args.page if args.page else args.start_page
    end_p = args.page if args.page else args.end_page

    with sync_playwright() as p:
        b = p.chromium.connect_over_cdp(CDP_URL)
        ctx = b.contexts[0]
        page_site, page_basic = get_pages(ctx)

        for p_num in range(start_p, end_p + 1):
            process_one_page(page_site, page_basic, ctx, p_num)
            time.sleep(1)

if __name__ == "__main__":
    main()
