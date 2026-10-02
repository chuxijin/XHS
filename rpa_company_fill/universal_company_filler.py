# -*- coding: utf-8 -*-
"""
Universal Company & ATS Website Auto-Filler (v2)
严格遵循 RPA_Guide.md 规范。

核心改进：
- 搜到公司后，先读取表格行做智能比对（简称/类型/行业/地点）
- 全部正确 → 直接跳过，秒切下一家
- 只有不对的字段才打开编辑弹窗修正，已经正确的字段不碰
- 未搜到 → 新增公司 → 手动新增 → 填写全部字段
"""

import os
import json
import argparse
from playwright.sync_api import sync_playwright

# =========================================================
# 任务类型范围 (task_name) 套系定义
# =========================================================
# 套系一：国外主流 ATS 平台任务（境外企业 / 外商独资）
TASK_SUITE_FOREIGN_ATS = [
    "green_house_spider_task",
    "workday_spider_task",
    "smart_spider_task",
    "lever_spider_task",
    "oracle_hcm_spider_task",
    "taleo_spider_task",
    "ashby_spider_task",
    "icims_spider_task",
    "eight_fold_spider_task",
]

# 套系二：国聘网爬虫任务（国内：央企 / 国企 / 事业单位 / 民企等）（待扩展占位）
TASK_SUITE_GUOPIN = [
    "guopin_v3_spider_task",
]

# RPA_Guide.md 全量 40 项官方真实行业字典
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

# 全量 18 项官方真实企业类型 Value 字典
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
    "其他股份有限公司": ["14"],
    "会计师事务所": ["15"],
    "中外合作": ["16"],
    "其他有限责任公司": ["17"],
    "境外企业": ["18"],
    "招聘会来源": ["19"]
}



def wait_modal_gone(page, timeout=3000):
    """等待 Element UI 全屏遮罩层 (.v-modal) 消失"""
    try:
        page.wait_for_function(
            "() => !document.querySelector('.v-modal')",
            timeout=timeout
        )
    except Exception:
        pass
    page.wait_for_timeout(300)


def close_visible_dialogs(page):
    """安全关闭所有可见弹窗"""
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


def fill_basic_company(page2, item):
    """
    在公司库 (company-basic) 处理一家公司。
    智能比对：搜到后先读表格行，全对就跳过，只改不对的。
    """
    comp_name = item["公司名称"].strip()
    short_name = item["简称"].strip()
    comp_type = item["类型"].strip()
    ind_name = item["行业"].strip()
    ind_id = INDUSTRY_MAP.get(ind_name, ["13"])
    location = item["地点"].strip()

    print(f"\n{'='*50}", flush=True)
    print(f"[公司库] 处理: 【{comp_name}】", flush=True)
    print(f"  目标 -> 简称:{short_name} | 类型:{comp_type} | 行业:{ind_name} | 地点:{location}", flush=True)

    page2.bring_to_front()
    close_visible_dialogs(page2)

    # --- 搜索公司 ---
    search_input = page2.locator("input[placeholder*='输入关键词搜索']").first
    search_input.fill("")
    search_input.fill(comp_name)
    page2.locator("button:has-text('搜索')").first.click()
    page2.wait_for_timeout(1200)

    # --- 读取搜索结果表格 ---
    rows = page2.evaluate("""() => {
        return Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map(tr => {
            return Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
        });
    }""")

    # 查找完全匹配的行
    matched_row_data = None
    matched_row_idx = -1
    for i, tds in enumerate(rows):
        if len(tds) > 1 and comp_name in tds[1]:
            matched_row_data = tds
            matched_row_idx = i
            break

    if matched_row_data is None:
        # ========== 未找到 → 新增公司 → 手动新增 ==========
        print(f"  ➕ 公司未收录，新增公司 → 手动新增...", flush=True)
        page2.locator("button:has-text('新增公司')").first.click()
        page2.wait_for_timeout(600)
        page2.locator("button:has-text('手动新增')").first.click()
        page2.wait_for_timeout(800)

        dialog = page2.locator(".el-dialog:visible").last

        # 填全部字段
        dialog.locator("input[placeholder*='请输入名称']").first.fill(comp_name)
        page2.wait_for_timeout(100)
        dialog.locator("input[placeholder*='请输入简称']").first.fill(short_name)
        page2.wait_for_timeout(100)
        dialog.locator("input[placeholder*='请输入地点']").first.fill(location)
        page2.wait_for_timeout(100)

        # Vue Model 纯净设置【类型】
        _set_org_type(page2, dialog, comp_type)

        # Vue 底层注入行业 ID
        _inject_industry(page2, ind_name, ind_id)

        # 确定保存
        _click_confirm_and_wait(page2, dialog)
        print(f"  ✅ 【{comp_name}】新增成功！", flush=True)
        return

    # ========== 已找到 → 智能比对 ==========
    # 表格列: [序号, 公司名称, 简称, 类型, 行业, 标签, 地点, ...]
    cur_short = matched_row_data[2] if len(matched_row_data) > 2 else ""
    cur_type = matched_row_data[3] if len(matched_row_data) > 3 else ""
    cur_industry = matched_row_data[4] if len(matched_row_data) > 4 else ""
    cur_location = matched_row_data[6] if len(matched_row_data) > 6 else ""

    print(f"  🔍 已收录! 当前库中 -> 简称:{cur_short} | 类型:{cur_type} | 行业:{cur_industry} | 地点:{cur_location}", flush=True)

    need_fix_short = bool(short_name and cur_short != short_name)
    need_fix_type = bool(comp_type and cur_type != comp_type)
    need_fix_industry = bool(ind_name and cur_industry != ind_name)
    # 地址保护死律：已有地址绝对严禁覆盖修改！仅当现有地址为空且指定了新地点时才填入
    need_fix_location = bool(location and not cur_location)

    if not (need_fix_short or need_fix_type or need_fix_industry or need_fix_location):
        print(f"  ✅ 全部字段已正确，跳过！秒切下一家。", flush=True)
        return

    # 有不对的 → 点击编辑
    diffs = []
    if need_fix_short: diffs.append(f"简称:{cur_short}→{short_name}")
    if need_fix_type: diffs.append(f"类型:{cur_type}→{comp_type}")
    if need_fix_industry: diffs.append(f"行业:{cur_industry}→{ind_name}")
    if need_fix_location: diffs.append(f"地点:{cur_location}→{location}")
    print(f"  🔧 需要修正: {' | '.join(diffs)}", flush=True)

    edit_btn = page2.locator(".el-table__body-wrapper tbody tr").nth(matched_row_idx).locator("button:has-text('编辑')").first
    edit_btn.click(force=True)
    page2.wait_for_timeout(800)

    dialog = page2.locator(".el-dialog:visible").last

    # 只改需要改的字段
    if need_fix_short:
        dialog.locator("input[placeholder*='请输入简称']").first.fill(short_name)
        page2.wait_for_timeout(100)

    if need_fix_location:
        dialog.locator("input[placeholder*='请输入地点']").first.fill(location)
        page2.wait_for_timeout(100)

    if need_fix_type:
        _set_org_type(page2, dialog, comp_type)

    if need_fix_industry:
        _inject_industry(page2, ind_name, ind_id)

    _click_confirm_and_wait(page2, dialog)
    print(f"  ✅ 【{comp_name}】修正保存成功！", flush=True)


def _set_org_type(page, dialog, comp_type):
    """纯净覆盖企业类型，杜绝 Element UI 多选组件历史残留"""
    type_id_list = ORG_TYPE_MAP.get(comp_type, ["18"])
    print(f"    🏢 设置企业类型 -> 【{comp_type}】(ID:{type_id_list})...", flush=True)
    res = page.evaluate("""(typeArr) => {
        const diag = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
            .find(d => window.getComputedStyle(d).display !== 'none');
        if (!diag) return { ok: false };

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
        return { ok: true, val: form ? form.__vue__.model.org_type_new : null };
    }""", type_id_list)
    print(f"    🏢 类型设置结果: {res}", flush=True)
    page.wait_for_timeout(200)


def _inject_industry(page, ind_name, ind_id):
    """Vue 底层注入行业 ID + Cascader 事件同步触发"""
    print(f"    🌿 注入行业 ID -> 【{ind_name}】(ID:{ind_id})...", flush=True)
    res = page.evaluate("""(idArr) => {
        const diag = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
            .find(d => window.getComputedStyle(d).display !== 'none');
        if (!diag) return { ok: false, msg: 'no dialog' };

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

        return { ok: true, val: form ? form.__vue__.model.industry_new : null };
    }""", ind_id)
    print(f"    🌿 注入结果: {res}", flush=True)
    page.wait_for_timeout(200)


def _click_confirm_and_wait(page, dialog):
    """点击确定并等待遮罩层消失"""
    confirm = dialog.locator("button:has-text('确 定')").last
    confirm.click(force=True)
    page.wait_for_timeout(800)
    wait_modal_gone(page)
    page.wait_for_timeout(500)


def fill_site_config(page1, item):
    """在网站列表页匹配链接，点击配置，回填公司全称（采用 URL 动态寻行 + 弹窗熔断双保险）"""
    comp_name = item["公司名称"].strip()
    site_url = item["网站链接"].strip().rstrip("/")

    print(f"\n[网站列表] 配置: 【{comp_name}】", flush=True)
    print(f"  目标URL: {site_url}", flush=True)

    page1.bring_to_front()
    close_visible_dialogs(page1)

    # 1. 动态寻行：彻底杜绝固定行号下标导致并发错位
    matched_row = page1.locator(".el-table__body-wrapper tbody tr").filter(
        has=page1.locator(f"td:has-text('{site_url}')")
    ).first

    if matched_row.count() == 0 or not matched_row.is_visible():
        print(f"  ⚠️ 当前页未找到包含链接 [{site_url}] 的行", flush=True)
        return False

    print(f"  🎯 命中匹配行，点击【配置】...", flush=True)
    cfg_btn = matched_row.locator("button:has-text('配置')").first
    cfg_btn.scroll_into_view_if_needed()
    page1.wait_for_timeout(300)
    cfg_btn.click()

    try:
        page1.wait_for_selector(".el-dialog:visible", timeout=4000)
    except Exception:
        cfg_btn.click(force=True)
        page1.wait_for_selector(".el-dialog:visible", timeout=5000)

    dialog = page1.locator(".el-dialog:visible").last

    # 2. 弹窗 URL 双向校验锁（Fail-Safe 终极熔断）
    dialog_url = dialog.locator("input[placeholder='请输入网站链接']").first.input_value().strip().rstrip("/")
    if dialog_url != site_url:
        print(f"  🚨 [安全熔断] 弹窗URL [{dialog_url}] != 目标URL [{site_url}]，立即关闭！", flush=True)
        dialog.locator(".el-dialog__headerbtn").click()
        page1.wait_for_timeout(400)
        return False

    # 3. 精准定位【公司名称】输入框，填入工商全称（严禁填简称）
    comp_input = dialog.locator("input[placeholder='请输入公司名称']").first
    comp_input.fill("")
    comp_input.type(comp_name, delay=50)
    page1.wait_for_timeout(800)

    # 4. 从下拉联想中精准选中
    opt = page1.locator(".el-select-dropdown:visible .el-select-dropdown__item, .el-autocomplete-suggestion:visible li").filter(has_text=comp_name).first
    try:
        if opt.is_visible(timeout=2000):
            opt.click()
            print(f"  🔘 下拉选中全称: 【{comp_name}】", flush=True)
            page1.wait_for_timeout(400)
        else:
            print(f"  ℹ️ 下拉未出现，按回车确认...", flush=True)
            comp_input.press("Enter")
            page1.wait_for_timeout(300)
    except Exception:
        comp_input.press("Enter")
        page1.wait_for_timeout(300)

    # 5. 点确定保存并等待遮罩层自然销毁
    confirm = dialog.locator("button:has-text('确 定')").last
    confirm.click(force=True)
    page1.wait_for_timeout(800)

    try:
        msg_box = page1.locator(".el-message-box:visible").first
        if msg_box.count() > 0 and msg_box.is_visible():
            box_txt = msg_box.inner_text().replace('\n', ' ')
            print(f"  ⚠️ 触发系统拦截弹窗: {box_txt}", flush=True)
            ok_btn = msg_box.locator(".el-message-box__btns button:has-text('确定')").first
            if ok_btn.count() > 0:
                ok_btn.click()
            close_visible_dialogs(page1)
            print(f"  ⏩ 已跳过该冲突行（后续汇报）", flush=True)
            return "SKIPPED_DUPLICATE"
    except Exception:
        pass

    wait_modal_gone(page1)
    print(f"  ✅ 【{comp_name}】网站配置完成！", flush=True)
    return True


def run(json_path):
    if not os.path.exists(json_path):
        print(f"❌ 找不到: {json_path}", flush=True)
        return

    with open(json_path, "r", encoding="utf-8") as f:
        companies = json.load(f)

    print(f"🚀 待处理: {len(companies)} 家公司", flush=True)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]

        page_site = next((pg for pg in ctx.pages if "company-basic" not in pg.url and "admin.jobleap" in pg.url and "/company" in pg.url), None)
        page_basic = next((pg for pg in ctx.pages if "company-basic" in pg.url and "admin.jobleap" in pg.url), None)

        if not page_site or not page_basic:
            print("❌ 未找到对应标签页！", flush=True)
            return

        # ===== 阶段 1: 公司库 =====
        print(f"\n{'='*60}", flush=True)
        print("===== 阶段 1: 公司库查重/校准/新增 =====", flush=True)
        print(f"{'='*60}", flush=True)
        for item in companies:
            fill_basic_company(page_basic, item)

        # ===== 阶段 2: 网站列表配置 =====
        print(f"\n{'='*60}", flush=True)
        print("===== 阶段 2: 网站列表回填公司全称 =====", flush=True)
        print(f"{'='*60}", flush=True)
        remaining = list(companies)

        for attempt in range(5):
            if not remaining:
                break

            print(f"\n📄 扫描网站列表当前页 (轮次 {attempt+1})...", flush=True)
            unmatched = []
            for item in remaining:
                ok = fill_site_config(page_site, item)
                if not ok:
                    unmatched.append(item)
            remaining = unmatched

            if remaining:
                nxt = page_site.locator(".el-pagination button.btn-next")
                if nxt.is_visible() and not nxt.is_disabled():
                    print(f"  ➡️ 翻到下一页...", flush=True)
                    nxt.click()
                    page_site.wait_for_timeout(1500)
                else:
                    print(f"  ⚠️ 无法翻页", flush=True)
                    break

        if not remaining:
            print(f"\n🎉 全部 {len(companies)} 家企业处理完毕！", flush=True)
        else:
            print(f"\n⚠️ {len(remaining)} 家未在网站列表找到:", flush=True)
            for r in remaining:
                print(f"  - {r['公司名称']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=r"D:\100_Work\101_Program\Proj\XHS\rpa_company_fill\foreign_companies.json")
    args = parser.parse_args()
    run(args.file)
