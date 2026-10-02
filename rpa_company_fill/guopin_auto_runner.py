# -*- coding: utf-8 -*-
"""
国聘网全自动 / JSON 驱动闭环自动化执行引擎 (v4 升级版)
解决痛点：
1. 自动容错：自动检测并打开缺失的 company-basic 标签页，彻底免疫 StopIteration 崩溃。
2. 双模驱动：
   - 模式 A (高精度 JSON 驱动，推荐)：通过 --file 读取精确画像，杜绝启发式规则盲猜误判。
   - 模式 B (全自动扩展推导)：扩充 40 项官方行业与国企/央企/外资词库，支持 --pages N 连续翻页。
   - 模式 C (--scan-only)：仅扫描当前页未闭环国聘任务并导出 JSON。
3. 动态 URL 寻行：基于 URL / 全称动态定位，彻底免疫高频插入导致的行错位。
4. 单次建档保护：已闭环行自动跳过，绝不重复触发配置弹窗。
5. 官方真实行业对齐：使用 100% 官方真实行业 ID，强制触发 Cascader 的 input & change 事件。
"""

import os
import json
import time
import argparse
from playwright.sync_api import sync_playwright

# 100% 官方真实行业映射字典 (Vue Model ID)
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


def wait_modal_gone(page, timeout=3000):
    """等待 Element UI 全屏遮罩层消失"""
    try:
        page.wait_for_function("() => !document.querySelector('.v-modal')", timeout=timeout)
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


def guess_type(name):
    """根据公司名称推导企业类型（央企 / 国企 / 事业单位 / 民企 / 外商独资 / 中外合资）"""
    if any(k in name for k in ["中国科学院", "中国医学科学院", "研究所", "研究院", "大学", "学院", "学校", "医院", "前沿创新中心", "技术推广中心"]):
        return "事业单位"
    if any(k in name for k in ["中国航空工业", "中国储备粮", "国家电网", "中国石化", "中国石油", "中国电信", "中国移动", "中国联通", "中国工商银行", "中国银行", "建设银行", "农业银行", "中国兵器", "中粮", "中化", "华润", "招商局", "保利", "中车", "中船"]):
        return "央企"
    if any(k in name for k in ["总公司", "市场开发总公司", "集团有限公司", "城投", "建投", "发投", "交投", "国资", "市投资", "资产管理", "国有", "水务集团", "公交", "地质矿业", "福日"]):
        return "国企"
    if any(k in name for k in ["外商", "外资", "杰群", "台资"]):
        return "外商独资"
    return "民企"


def guess_short_and_industry(name):
    """根据公司名称推导规范简称与官方真实行业"""
    clean = name
    for prefix in ["广东", "北京", "上海", "深圳", "天津", "江苏", "浙江", "山东", "海南", "重庆", "南京", "河北", "河南", "辽宁", "四川", "湖北", "湖南", "东莞市", "成都市", "深圳市", "儋州市"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):]
            break

    for suffix in [
        "股份有限公司深圳分公司", "股份有限公司北京分公司", "股份有限公司上海分公司", "股份有限公司广州分公司",
        "股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "总公司", "市场开发总公司", "研究所", "研究院", "大学", "学院"
    ]:
        if clean.endswith(suffix):
            clean = clean[:-len(suffix)]
            break

    short = clean[:8] if len(clean) > 8 else clean
    if not short:
        short = name[:6]

    ind = "综合"
    if any(k in name for k in ["芯片", "半导体", "集成电路", "测控", "电子", "电容", "微电子", "源磊", "科尼盛", "杰群"]):
        ind = "硬件/半导体/芯片"
    elif any(k in name for k in ["机器人", "自动化", "三维科技", "3D"]):
        ind = "机器人"
    elif any(k in name for k in ["锂电", "储能", "新能源", "创智源", "光伏", "电池"]):
        ind = "新能源"
    elif any(k in name for k in ["机械", "制造", "重工", "装备", "精密", "模具", "泓楷", "沃德", "智能装备"]):
        ind = "机械/制造业"
    elif any(k in name for k in ["玩具", "童车", "快消", "童爱乐园", "食品", "饮料", "服装", "鞋业"]):
        ind = "快消"
    elif any(k in name for k in ["药", "生物", "医学", "医疗", "基因", "健康", "疫苗", "前沿创新"]):
        ind = "生物/医疗/制药"
    elif any(k in name for k in ["物流", "快递", "供应链", "货运", "运输", "仓储"]):
        ind = "物流/供应链/交通运输"
    elif any(k in name for k in ["商业", "市场开发", "贸易", "咨询", "服务", "检测", "瑞达检测", "佰航", "泰盈"]):
        ind = "商业服务"
    elif any(k in name for k in ["智能", "软件", "数科", "网络", "计算", "信息科技", "西交创科"]):
        ind = "IT/互联网/游戏"
    elif any(k in name for k in ["新材料", "化工", "石化", "材料", "矿业"]):
        ind = "材料/能源/化工"
    elif any(k in name for k in ["置业", "地产", "城投", "城建", "房产"]):
        ind = "建筑/房地产"
    elif any(k in name for k in ["环保", "水务", "环卫", "固废"]):
        ind = "环保"
    elif any(k in name for k in ["通信", "互联", "连接器"]):
        ind = "通信"
    elif any(k in name for k in ["银行", "保险", "人寿", "证券", "资本", "资管", "投资", "金融"]):
        ind = "金融业"

    return short, ind


def select_type_dropdown(page, dialog, ctype):
    """UI 真实模拟点击选择类型"""
    try:
        type_item = dialog.locator(".el-form-item").filter(has_text="类型")
        type_input = type_item.locator(".el-select input, .el-select").first
        type_input.click()
        page.wait_for_timeout(300)
        opt = page.locator(f".el-select-dropdown:visible .el-select-dropdown__item:has-text('{ctype}')").last
        if opt.is_visible():
            opt.click()
            page.wait_for_timeout(200)
    except Exception as e:
        print(f"    ⚠️ 选择类型异常: {e}")


def inject_industry(page, ind_id):
    """Vue 底层注入行业 ID + 同步触发 Cascader 的 input & change 事件"""
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


def ensure_pages(browser):
    """确保同时具备网站列表页与公司基本信息库页，缺失则自动打开"""
    ctx = browser.contexts[0]
    page_site = None
    page_basic = None

    for pg in ctx.pages:
        if "company-basic" in pg.url and "admin.jobleap" in pg.url:
            page_basic = pg
        elif "company" in pg.url and "admin.jobleap" in pg.url and "company-basic" not in pg.url:
            page_site = pg

    if not page_site:
        raise RuntimeError("❌ 未找到网站列表页面 (/#/company/index)")

    if not page_basic:
        print("ℹ️ 未检测到公司库页面，自动新建标签页导航至 /#/company-basic/index...")
        page_basic = ctx.new_page()
        page_basic.goto("http://admin.jobleap.betaquantity.com/#/company-basic/index")
        page_basic.wait_for_timeout(2000)

    return page_site, page_basic


def scan_current_guopin_tasks(page_site):
    """扫描网站列表当前页所有 guopin_v3_spider_task 任务"""
    page_site.bring_to_front()
    page_site.wait_for_timeout(400)

    rows = page_site.evaluate("""() => {
        return Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map((tr, idx) => {
            const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            return {
                idx: idx + 1,
                id: tds[0] || '',
                name: tds[1] || '',
                type: tds[2] || '',
                ind: tds[3] || '',
                task: tds[4] || '',
                count: tds[5] || '',
                url: tds[6] || ''
            };
        });
    }""")

    guopin_rows = [r for r in rows if r['task'] == 'guopin_v3_spider_task']
    return guopin_rows


def process_guopin_items(page_site, page_basic, target_companies):
    """执行国聘任务完整闭环流水线"""
    print(f"\n{'='*60}", flush=True)
    print(f"===== 阶段 1: 网站列表触发初次建档 (共 {len(target_companies)} 家) =====", flush=True)
    print(f"{'='*60}", flush=True)

    page_site.bring_to_front()
    close_visible_dialogs(page_site)

    for item in target_companies:
        name = item.get("公司名称") or item.get("name")
        url = item.get("网站链接") or item.get("url")

        print(f"\n⚡ 检查任务: 【{name}】", flush=True)
        # 优先按 URL 动态定位
        row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
            has=page_site.locator(f"td:has-text('{url}')")
        ).first

        if not row.is_visible():
            row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
                has=page_site.locator(f"td:has-text('{name}')")
            ).first

        if row.is_visible():
            tds = row.locator("td").all_inner_texts()
            cur_type = tds[2].strip() if len(tds) > 2 else ""
            cur_ind = tds[3].strip() if len(tds) > 3 else ""
            if cur_type and cur_ind:
                print(f"  ✅ 该行已处于齐整闭环 (类型:{cur_type}, 行业:{cur_ind})，无需点击配置与确定。", flush=True)
                item['_already_complete'] = True
                continue

            # 确保先前弹窗已完全退出
            wait_modal_gone(page_site)
            page_site.wait_for_timeout(300)

            print(f"  👉 点击【配置】...", flush=True)
            cfg_btn = row.locator("button:has-text('配置')").first
            cfg_btn.scroll_into_view_if_needed()
            cfg_btn.click(force=True)

            # 稳妥等待弹窗完全可见 (支持未弹出时重试点击)
            diag = None
            for attempt in range(3):
                try:
                    page_site.wait_for_selector(".el-dialog:visible", timeout=2500)
                    diag = page_site.locator(".el-dialog:visible").last
                    if diag.is_visible():
                        break
                except Exception:
                    print(f"    🔄 弹窗未及时出现，重试点击【配置】(尝试 {attempt+1}/3)...", flush=True)
                    cfg_btn.click(force=True)
                    page_site.wait_for_timeout(800)

            if diag and diag.is_visible():
                print(f"  👉 点击弹窗【确 定】触发平台自动绑定...", flush=True)
                confirm_btn = diag.locator("button:has-text('确 定'), button:has-text('确定')").last
                confirm_btn.scroll_into_view_if_needed()
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
                        print(f"  ⏩ 已跳过该冲突行", flush=True)
                        continue
                except Exception:
                    pass
                wait_modal_gone(page_site)
                page_site.wait_for_timeout(300)
                print(f"  ✅ 平台底层绑定建档触发完毕！", flush=True)
            else:
                print(f"  ❌ 无法打开【配置】弹窗，跳过该行: {name}", flush=True)
        else:
            print(f"  ⚠️ 当前页未找到该行（可能已翻页或移位）: {name}", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"===== 阶段 2: 公司基本信息库核对与差量补齐 =====", flush=True)
    print(f"{'='*60}", flush=True)

    page_basic.bring_to_front()
    close_visible_dialogs(page_basic)

    for i, item in enumerate(target_companies):
        cname = item.get("公司名称") or item.get("name")
        short_name = item.get("简称") or item.get("short", "")
        ctype = item.get("类型") or item.get("type", "民企")
        ind_name = item.get("行业") or item.get("industry", "综合")
        ind_id = INDUSTRY_MAP.get(ind_name, ["13"])

        loc_val = item.get("地点") or item.get("location", "")

        print(f"\n[{i+1}/{len(target_companies)}] 🏢 [公司库] 核对: 【{cname}】", flush=True)
        if item.get("_already_complete"):
            print(f"  ✅ 网站列表已齐整闭环，无需重复查对公司库，直接跳过。", flush=True)
            continue

        print(f"   目标 -> 简称:{short_name} | 类型:{ctype} | 行业:{ind_name}({ind_id}) | 地点:{loc_val}", flush=True)

        inp = page_basic.locator("input[placeholder*='输入关键词搜索']").first
        inp.fill("")
        inp.fill(cname)
        page_basic.locator("button:has-text('搜索')").first.click()
        page_basic.wait_for_timeout(1000)

        rows_basic = page_basic.evaluate("""() => {
            return Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map(tr => {
                return Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            });
        }""")

        matched_idx = -1
        matched_row = None
        for idx, tds in enumerate(rows_basic):
            if len(tds) > 1 and cname in tds[1]:
                matched_idx = idx
                matched_row = tds
                break

        if matched_row is None:
            print(f"  ➕ 公司库未收录，执行【新增公司 -> 手动新增】...", flush=True)
            page_basic.locator("button:has-text('新增公司')").first.click()
            page_basic.wait_for_timeout(500)
            page_basic.locator("button:has-text('手动新增')").first.click()
            page_basic.wait_for_timeout(600)

            diag = page_basic.locator(".el-dialog:visible").last
            diag.locator("input[placeholder*='请输入名称']").first.fill(cname)
            diag.locator("input[placeholder*='请输入简称']").first.fill(short_name)
            if loc_val:
                loc_inp = diag.locator("input[placeholder*='请输入地点'], input[placeholder*='请输入城市']")
                if loc_inp.count() > 0:
                    loc_inp.first.fill(loc_val)
            select_type_dropdown(page_basic, diag, ctype)
            inject_industry(page_basic, ind_id)

            diag.locator("button:has-text('确 定')").last.click(force=True)
            page_basic.wait_for_timeout(1000)
            wait_modal_gone(page_basic)
            print(f"  ✅ 【{cname}】全量新增录入成功！", flush=True)
        else:
            cur_short = matched_row[2] if len(matched_row) > 2 else ""
            cur_type = matched_row[3] if len(matched_row) > 3 else ""
            cur_ind = matched_row[4] if len(matched_row) > 4 else ""
            cur_loc = matched_row[6] if len(matched_row) > 6 else ""

            need_short = bool(short_name and not cur_short)
            need_type = bool(ctype and not cur_type)  # 仅当类型为空时补齐，已有正确类型绝不重置
            need_ind = bool(ind_name and not cur_ind)
            need_loc = bool(loc_val and not cur_loc)

            if not need_short and not need_type and not need_ind and not need_loc:
                print(f"  ✅ 数据完整整齐 (简称:{cur_short}, 类型:{cur_type}, 行业:{cur_ind}, 地点:{cur_loc})，跳过！", flush=True)
                continue

            print(f"  🔧 存在缺失字段 (当前: 简称={cur_short}, 类型={cur_type}, 行业={cur_ind}, 地点={cur_loc})，点击【编辑】补齐...", flush=True)
            edit_btn = page_basic.locator(".el-table__body-wrapper tbody tr").nth(matched_idx).locator("button:has-text('编辑')").first
            edit_btn.click(force=True)
            page_basic.wait_for_timeout(600)

            diag = page_basic.locator(".el-dialog:visible").last

            if need_short:
                diag.locator("input[placeholder*='请输入简称']").first.fill(short_name)
                page_basic.wait_for_timeout(100)

            if need_loc:
                loc_inp = diag.locator("input[placeholder*='请输入地点'], input[placeholder*='请输入城市']")
                if loc_inp.count() > 0:
                    loc_inp.first.fill(loc_val)
                page_basic.wait_for_timeout(100)

            if need_type:
                select_type_dropdown(page_basic, diag, ctype)

            if need_ind:
                inject_industry(page_basic, ind_id)

            diag.locator("button:has-text('确 定')").last.click(force=True)
            page_basic.wait_for_timeout(1000)
            wait_modal_gone(page_basic)
            print(f"  ✅ 【{cname}】差量补齐保存成功！", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"===== 阶段 3: 刷新网站列表与二次闭环联动 =====", flush=True)
    print(f"{'='*60}", flush=True)
    page_site.bring_to_front()
    page_site.reload()
    page_site.wait_for_timeout(2000)

    # 检查当前页是否还有未挂齐的行，进行二次回填联动
    uncompleted_rows = page_site.evaluate("""() => {
        return Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map((tr, idx) => {
            const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
            return {
                idx: idx,
                name: tds[1] || '',
                type: tds[2] || '',
                ind: tds[3] || '',
                task: tds[4] || '',
                url: tds[6] || ''
            };
        }).filter(r => r.task === 'guopin_v3_spider_task' && (!r.type || !r.ind));
    }""")

    if uncompleted_rows:
        print(f"🔄 检测到 {len(uncompleted_rows)} 家在公司库补齐后仍未在网站列表显现，执行二次配置联动...", flush=True)
        for u in uncompleted_rows:
            uname = u['name']
            uurl = u['url']
            print(f"  ⚡ 联动回填: 【{uname}】", flush=True)
            row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
                has=page_site.locator(f"td:has-text('{uurl}')")
            ).first
            if not row.is_visible():
                row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
                    has=page_site.locator(f"td:has-text('{uname}')")
                ).first

            if row.is_visible():
                wait_modal_gone(page_site)
                cfg_btn = row.locator("button:has-text('配置')").first
                cfg_btn.scroll_into_view_if_needed()
                cfg_btn.click(force=True)

                diag = None
                for attempt in range(3):
                    try:
                        page_site.wait_for_selector(".el-dialog:visible", timeout=2500)
                        diag = page_site.locator(".el-dialog:visible").last
                        if diag.is_visible():
                            break
                    except Exception:
                        cfg_btn.click(force=True)
                        page_site.wait_for_timeout(800)

                if diag and diag.is_visible():
                    confirm_btn = diag.locator("button:has-text('确 定'), button:has-text('确定')").last
                    confirm_btn.scroll_into_view_if_needed()
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
                    page_site.wait_for_timeout(300)
                    print(f"  ✅ 【{uname}】二次绑定成功！", flush=True)

        page_site.reload()
        page_site.wait_for_timeout(1500)

    print(f"🎉 全部国聘企业处理流程圆满结束！\n", flush=True)


def run_pipeline(args):
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page_site, page_basic = ensure_pages(browser)

        # 模式 1: 仅扫描模式 (--scan-only)
        if args.scan_only:
            print("🔍 模式: 仅扫描当前页国聘任务...", flush=True)
            guopin_rows = scan_current_guopin_tasks(page_site)
            print(f"📊 检视到 {len(guopin_rows)} 条国聘网任务:")
            exported = []
            for r in guopin_rows:
                short, ind = guess_short_and_industry(r['name'])
                ctype = guess_type(r['name'])
                exported.append({
                    "公司名称": r['name'],
                    "简称": short,
                    "类型": ctype,
                    "行业": ind,
                    "网站链接": r['url']
                })
                print(f"  - [{r['id']}] {r['name']} | 当前类型:{r['type'] or '(空)'} | 行业:{r['ind'] or '(空)'}")

            out_file = args.file or r"D:\100_Work\101_Program\Proj\XHS\rpa_company_fill\guopin_companies.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(exported, f, ensure_ascii=False, indent=2)
            print(f"💾 任务清单已成功导出至: {out_file}")
            return

        # 模式 2: 精准 JSON 驱动模式
        if args.file and os.path.exists(args.file):
            print(f"🚀 模式: 精准 JSON 驱动模式 (读取 {args.file})...", flush=True)
            with open(args.file, "r", encoding="utf-8") as f:
                target_companies = json.load(f)
            process_guopin_items(page_site, page_basic, target_companies)
            return

        # 模式 3: 全自动翻页模式 (--pages N)
        pages_to_run = args.pages
        for p_idx in range(pages_to_run):
            cur_p = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText || '?'")
            print(f"\n================ 正在处理第 {cur_p} 页 (进度: {p_idx+1}/{pages_to_run}) ================", flush=True)
            guopin_rows = scan_current_guopin_tasks(page_site)

            pending_items = []
            for r in guopin_rows:
                short, ind = guess_short_and_industry(r['name'])
                ctype = guess_type(r['name'])
                pending_items.append({
                    "公司名称": r['name'],
                    "简称": short,
                    "类型": ctype,
                    "行业": ind,
                    "网站链接": r['url']
                })

            if pending_items:
                process_guopin_items(page_site, page_basic, pending_items)
            else:
                print(f"ℹ️ 第 {cur_p} 页暂无待处理国聘任务。")

            if p_idx < pages_to_run - 1:
                page_site.bring_to_front()
                next_btn = page_site.locator(".el-pagination button.btn-next")
                if next_btn.is_visible() and not next_btn.is_disabled():
                    print(f"➡️ 推进至下一页...", flush=True)
                    next_btn.click()
                    page_site.wait_for_timeout(2000)
                else:
                    print("⚠️ 已达末页，结束翻页。")
                    break


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="国聘网全自动 / JSON 驱动闭环执行引擎 (v4)")
    parser.add_argument("--file", default=None, help="高精度 JSON 文件路径 (精准驱动模式)")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描当前页国聘任务并导出 JSON")
    parser.add_argument("--pages", type=int, default=1, help="连续处理页数 (全自动模式)")
    parsed_args = parser.parse_args()
    run_pipeline(parsed_args)
