# -*- coding: utf-8 -*-
"""
Foreign ATS Multi-Page Runner (Pages 1 - 4)
严格遵循 RPA_Guide.md 规范与第一套境外企业标准。
"""

import os
import json
import time
import argparse
from playwright.sync_api import sync_playwright

INDUSTRY_MAP = {
    "IT/互联网/游戏": ["0"],
    "金融业": ["1"],
    "专业服务": ["2"],
    "广告传媒/文化体育": ["3"],
    "快消": ["4"],
    "生物/医疗/制药": ["5"],
    "硬件/半导体/芯片": ["6"],
    "汽车/智能驾驶": ["7"],
    "物流/供应链/交通运输": ["8"],
    "建筑/房地产": ["9"],
    "机械/制造业": ["10"],
    "材料/能源/化工": ["11"],
    "政府机关": ["12"],
    "综合": ["13"],
    "环保": ["15"],
    "军工/航天/航空": ["16"],
    "通信": ["17"],
    "农林牧渔": ["18"],
    "教育": ["19"],
    "餐饮住宿": ["20"],
    "批发零售": ["21"],
    "科研技术": ["22"],
    "新闻出版": ["23"],
    "烟草": ["24"],
    "电子商务": ["25"],
    "船舶": ["26"],
    "机器人": ["27"],
    "人工智能": ["28"],
    "云计算": ["29"],
    "生活服务": ["30"],
    "新能源": ["31"],
    "大数据": ["32"],
    "消费电子": ["33"],
    "智能家居": ["35"],
    "商业服务": ["36"],
    "低空经济": ["37"],
    "区块链": ["38"],
    "奢侈品": ["39"],
    "其它": ["41"],
    "社会组织": ["42"],
}

ORG_TYPE_MAP = {
    "央企": ["0"],
    "国企": ["1"],
    "外商独资": ["2"],
    "民企": ["3"],
    "上市": ["4"],
    "律所": ["5"],
    "医院": ["6"],
    "学校": ["7"],
    "银行": ["8"],
    "国家机关": ["9"],
    "事业单位": ["10"],
    "中外合资": ["13"],
    "境外企业": ["18"],
    "招聘会来源": ["19"],
}


def wait_modal_gone(page, timeout=4000):
    try:
        page.wait_for_function("() => !document.querySelector('.v-modal')", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(300)


def close_visible_dialogs(page):
    try:
        page.evaluate("""() => {
            document.querySelectorAll('.el-dialog__wrapper').forEach(d => {
                if (window.getComputedStyle(d).display !== 'none') {
                    const btn = d.querySelector('.el-dialog__headerbtn');
                    if (btn) btn.click();
                }
            });
        }""")
        page.wait_for_timeout(300)
        wait_modal_gone(page)
    except Exception:
        pass


def jump_to_page(page_site, target_page):
    page_site.bring_to_front()
    page_site.wait_for_selector(".el-pager", timeout=8000)
    current_page = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText || '?'")
    if current_page == str(target_page):
        return True

    res = page_site.evaluate("""(target) => {
        const lis = Array.from(document.querySelectorAll('.el-pager li'));
        const targetLi = lis.find(li => li.innerText.trim() === String(target));
        if (targetLi) {
            targetLi.click();
            return 'clicked_li';
        }
        const pag = document.querySelector('.el-pagination');
        if (pag && pag.__vue__) {
            pag.__vue__.$emit('current-change', Number(target));
            return 'vue_emit';
        }
        const inp = document.querySelector('.el-pagination__jump input');
        if (inp) {
            inp.value = target;
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            return 'input_change';
        }
        return 'none';
    }""", target_page)

    page_site.wait_for_timeout(1500)
    cur = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText || '?'")
    return cur == str(target_page)


def ensure_company_in_basic(page_basic, item):
    comp_name = item["公司名称"].strip()
    short_name = item.get("简称", "").strip()
    comp_type = item.get("类型", "境外企业").strip()
    ind_name = item.get("行业", "综合").strip()
    location = item.get("地点", "美国").strip()
    ind_id = INDUSTRY_MAP.get(ind_name, ["13"])

    print(f"\n🏢 [公司库] 核对: 【{comp_name}】", flush=True)
    print(f"   画像 -> 简称:{short_name} | 类型:{comp_type} | 行业:{ind_name} | 地点:{location}", flush=True)

    page_basic.bring_to_front()
    close_visible_dialogs(page_basic)

    search_input = page_basic.locator("input[placeholder*='输入关键词搜索']").first
    search_input.fill("")
    search_input.fill(comp_name)
    page_basic.locator("button:has-text('搜索')").first.click()
    page_basic.wait_for_timeout(1200)

    rows = page_basic.evaluate("""() => {
        return Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map(tr => {
            return Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
        });
    }""")

    matched_idx = -1
    matched_data = None
    for i, tds in enumerate(rows):
        if len(tds) > 1 and comp_name.lower() in tds[1].lower():
            matched_idx = i
            matched_data = tds
            break

    # 未找到 -> 手动新增
    if matched_data is None:
        print(f"  ➕ 公司未收录，执行【新增公司 -> 手动新增】...", flush=True)
        page_basic.locator("button:has-text('新增公司')").first.click()
        page_basic.wait_for_timeout(500)
        page_basic.locator("button:has-text('手动新增')").first.click()
        page_basic.wait_for_timeout(700)

        dialog = page_basic.locator(".el-dialog:visible").last
        dialog.locator("input[placeholder*='请输入名称']").first.fill(comp_name)
        page_basic.wait_for_timeout(100)
        dialog.locator("input[placeholder*='请输入简称']").first.fill(short_name)
        page_basic.wait_for_timeout(100)
        if location:
            dialog.locator("input[placeholder*='请输入地点']").first.fill(location)
            page_basic.wait_for_timeout(100)

        _set_org_type(page_basic, comp_type)
        _inject_industry(page_basic, ind_id)

        confirm_btn = dialog.locator("button:has-text('确 定')").last
        confirm_btn.click(force=True)
        page_basic.wait_for_timeout(800)
        wait_modal_gone(page_basic)
        print(f"  ✅ 【{comp_name}】新增档案成功！", flush=True)
        return True

    # 已收录 -> 智能核验并补齐
    cur_short = matched_data[2] if len(matched_data) > 2 else ""
    cur_type = matched_data[3] if len(matched_data) > 3 else ""
    cur_ind = matched_data[4] if len(matched_data) > 4 else ""
    cur_loc = matched_data[6] if len(matched_data) > 6 else ""

    need_short = bool(short_name and cur_short != short_name)
    need_type = bool(comp_type and cur_type != comp_type)
    need_ind = bool(ind_name and cur_ind != ind_name)
    need_loc = bool(location and not cur_loc)  # 地址保护死律：非空严禁覆盖

    if not (need_short or need_type or need_ind or need_loc):
        print(f"  ✅ 档案数据完全齐整 (简称:{cur_short}, 类型:{cur_type}, 行业:{cur_ind}, 地点:{cur_loc})，跳过。", flush=True)
        return True

    print(f"  🔧 存在缺失字段，点击【编辑】补齐...", flush=True)
    edit_btn = page_basic.locator(".el-table__body-wrapper tbody tr").nth(matched_idx).locator("button:has-text('编辑')").first
    edit_btn.click(force=True)
    page_basic.wait_for_timeout(700)

    dialog = page_basic.locator(".el-dialog:visible").last
    if need_short:
        dialog.locator("input[placeholder*='请输入简称']").first.fill(short_name)
        page_basic.wait_for_timeout(100)
    if need_loc:
        dialog.locator("input[placeholder*='请输入地点']").first.fill(location)
        page_basic.wait_for_timeout(100)
    if need_type:
        _set_org_type(page_basic, comp_type)
    if need_ind:
        _inject_industry(page_basic, ind_id)

    confirm_btn = dialog.locator("button:has-text('确 定')").last
    confirm_btn.click(force=True)
    page_basic.wait_for_timeout(800)
    wait_modal_gone(page_basic)
    print(f"  ✅ 【{comp_name}】档案差量修正完成！", flush=True)
    return True


def _set_org_type(page, comp_type):
    type_id_list = ORG_TYPE_MAP.get(comp_type, ["18"])
    page.evaluate("""(typeArr) => {
        const diag = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
            .find(d => window.getComputedStyle(d).display !== 'none');
        if (!diag) return;
        const form = diag.querySelector('.el-form');
        if (form && form.__vue__ && form.__vue__.model) {
            form.__vue__.model.org_type_new = typeArr;
            if (typeof form.__vue__.$set === 'function') {
                form.__vue__.$set(form.__vue__.model, 'org_type_new', typeArr);
            }
        }
        const select = diag.querySelector('.el-form-item .el-select');
        if (select && select.__vue__) {
            select.__vue__.$emit('input', typeArr);
            select.__vue__.$emit('change', typeArr);
        }
    }""", type_id_list)
    page.wait_for_timeout(200)


def _inject_industry(page, ind_id):
    page.evaluate("""(idArr) => {
        const diag = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
            .find(d => window.getComputedStyle(d).display !== 'none');
        if (!diag) return;
        const form = diag.querySelector('.el-form');
        if (form && form.__vue__ && form.__vue__.model) {
            form.__vue__.model.industry_new = idArr;
            if (typeof form.__vue__.$set === 'function') {
                form.__vue__.$set(form.__vue__.model, 'industry_new', idArr);
            }
        }
        const cascader = diag.querySelector('.el-cascader');
        if (cascader && cascader.__vue__) {
            cascader.__vue__.$emit('input', idArr);
            cascader.__vue__.$emit('change', idArr);
        }
    }""", ind_id)
    page.wait_for_timeout(200)


def configure_site_row(page_site, item):
    comp_name = item["公司名称"].strip()
    site_url = item["网站链接"].strip()

    print(f"\n⚡ [网站列表] 配置行: 【{comp_name}】", flush=True)
    print(f"   目标URL: {site_url}", flush=True)

    page_site.bring_to_front()
    close_visible_dialogs(page_site)

    # 动态寻行：按 URL 或关键词匹配
    matched_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
        has=page_site.locator(f"td:has-text('{site_url}')")
    ).first

    if not matched_row.is_visible():
        # 按 URL 核心部分模糊匹配
        url_core = site_url.split("//")[-1].split("?")[0].rstrip("/")
        matched_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
            has=page_site.locator(f"td:has-text('{url_core}')")
        ).first

    if not matched_row.is_visible():
        print(f"  ⚠️ 当前页未找到该链接对应的行: {site_url}", flush=True)
        return False

    # 检查是否已闭环
    tds = matched_row.locator("td").all_inner_texts()
    cur_cname = tds[1].strip() if len(tds) > 1 else ""
    cur_type = tds[2].strip() if len(tds) > 2 else ""
    cur_ind = tds[3].strip() if len(tds) > 3 else ""

    if cur_cname == comp_name and cur_type and cur_ind:
        print(f"  ✅ 该行已齐整闭环 (公司:{cur_cname}, 类型:{cur_type}, 行业:{cur_ind})，跳过配置。", flush=True)
        return True

    cfg_btn = matched_row.locator("button:has-text('配置')").first
    cfg_btn.scroll_into_view_if_needed()
    cfg_btn.click(force=True)

    diag = None
    for attempt in range(3):
        try:
            page_site.wait_for_selector(".el-dialog:visible", timeout=3000)
            diag = page_site.locator(".el-dialog:visible").last
            if diag.is_visible():
                break
        except Exception:
            cfg_btn.click(force=True)
            page_site.wait_for_timeout(800)

    if not diag or not diag.is_visible():
        print(f"  ❌ 无法打开配置弹窗，跳过。", flush=True)
        return False

    comp_input = diag.locator("input[placeholder*='请输入公司名称']").first
    comp_input.fill("")
    comp_input.type(comp_name, delay=35)
    page_site.wait_for_timeout(1000)

    # 从联想下拉中选中
    opt = page_site.locator(".el-select-dropdown:visible .el-select-dropdown__item, .el-autocomplete-suggestion:visible li").filter(has_text=comp_name).first
    try:
        if opt.is_visible(timeout=2500):
            opt.click()
            print(f"  🔘 下拉建议选中: 【{comp_name}】", flush=True)
            page_site.wait_for_timeout(300)
        else:
            comp_input.press("Enter")
            page_site.wait_for_timeout(300)
    except Exception:
        comp_input.press("Enter")
        page_site.wait_for_timeout(300)

    # 确定保存
    confirm_btn = diag.locator("button:has-text('确 定')").last
    confirm_btn.click(force=True)
    page_site.wait_for_timeout(800)

    try:
        msg_box = page_site.locator(".el-message-box:visible").first
        if msg_box.count() > 0 and msg_box.is_visible():
            box_txt = msg_box.inner_text().replace('\n', ' ')
            print(f"  ⚠️ 触发系统拦截弹窗: {box_txt}", flush=True)
            ok_btn = msg_box.locator(".el-message-box__btns button:has-text('确定')").first
            if ok_btn.count() > 0:
                ok_btn.click()
            close_visible_dialogs(page_site)
            print(f"  ⏩ 已跳过该冲突行（后续汇报）", flush=True)
            return "SKIPPED_DUPLICATE"
    except Exception:
        pass

    wait_modal_gone(page_site)
    print(f"  ✅ 【{comp_name}】网站配置保存成功！", flush=True)
    return True


def run_foreign_pipeline(target_pages=[1, 2, 3, 4]):
    tasks_file = r"D:\100_Work\101_Program\Proj\XHS\rpa_company_fill\foreign_tasks_all.json"
    with open(tasks_file, "r", encoding="utf-8") as f:
        tasks_by_page = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]

        page_site = next((pg for pg in ctx.pages if "company-basic" not in pg.url and "admin.jobleap" in pg.url and "/company" in pg.url), None)
        page_basic = next((pg for pg in ctx.pages if "company-basic" in pg.url and "admin.jobleap" in pg.url), None)

        if not page_site:
            raise RuntimeError("❌ 未找到网站列表页面！")
        if not page_basic:
            raise RuntimeError("❌ 未找到公司库页面！")

        for page_num in target_pages:
            p_str = str(page_num)
            items = tasks_by_page.get(p_str, [])
            if not items:
                print(f"\nℹ️ 第 {page_num} 页无国外配置任务，跳过。")
                continue

            print(f"\n{'='*70}", flush=True)
            print(f"🚀 开始处理第 {page_num} 页国外网站任务 (共 {len(items)} 家)", flush=True)
            print(f"{'='*70}", flush=True)

            # 阶段 1: 在公司库确保全部入库
            print(f"\n--- [第 {page_num} 页] 阶段 1: 公司库批量确权与建档 ---", flush=True)
            for item in items:
                ensure_company_in_basic(page_basic, item)

            # 阶段 2: 翻至目标页，在网站列表逐行配置
            print(f"\n--- [第 {page_num} 页] 阶段 2: 网站列表逐行回填 ---", flush=True)
            jump_to_page(page_site, page_num)
            page_site.wait_for_timeout(1000)

            for item in items:
                configure_site_row(page_site, item)

            # 阶段 3: 刷新网站列表并检验
            print(f"\n--- [第 {page_num} 页] 阶段 3: 刷新并核验闭环 ---", flush=True)
            page_site.bring_to_front()
            page_site.reload()
            page_site.wait_for_timeout(1500)
            print(f"🎉 第 {page_num} 页国外任务处理完毕！\n", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", nargs="+", type=int, default=[1, 2, 3, 4], help="目标页码列表")
    args = parser.parse_args()
    run_foreign_pipeline(args.pages)
