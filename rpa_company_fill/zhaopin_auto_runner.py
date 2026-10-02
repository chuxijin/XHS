# -*- coding: utf-8 -*-
"""
智联招聘爬虫任务全自动 / JSON 驱动闭环处理脚本 (zhaopin_auto_runner.py)
----------------------------------------------------------------------
支持两种工作流：
1. 全自动模式（默认）：
   扫描网站列表当前页所有 zhao_pin_spider_task 行，秒级解析智联底层数据提取法定全称，
   自动到公司库查重建档，自动回填网站配置，并实时核验完整度闭环。
2. 中间 JSON 驱动模式 (--file zhaopin_companies.json)：
   由 AI / 人工准备精准的 JSON 数据，脚本极速执行双页面回填与核验。
3. 纯扫描提取模式 (--scan-only)：
   仅提取当前页任务并生成 zhaopin_companies.json，方便审查。
"""

import argparse
import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
DEFAULT_JSON_PATH = os.path.join(os.path.dirname(__file__), "zhaopin_companies.json")

# 官方 40 项行业字典映射
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
    "招聘会来源": ["19"],
}


def normalize_name(s):
    """企业名称全半角括号正规化，统一为全角中文括号"""
    if not s:
        return ""
    return s.replace("(", "（").replace(")", "）").strip()


def wait_modal_gone(page, timeout=3000):
    """等待遮罩层销毁"""
    try:
        page.wait_for_function("() => !document.querySelector('.v-modal')", timeout=timeout)
    except Exception:
        pass
    page.wait_for_timeout(300)


def close_visible_dialogs(page):
    """安全关闭页面残留弹窗"""
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


def set_clean_org_type(page, comp_type):
    """纯净覆盖企业类型，杜绝 Element UI 多选组件历史残留"""
    type_id_list = ORG_TYPE_MAP.get(comp_type, ["3"])
    return page.evaluate("""(typeArr) => {
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


def inject_industry_safely(page, ind_id):
    """Vue 底层注入行业 ID + Cascader 事件同步双向派发"""
    return page.evaluate("""(idArr) => {
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


def guess_type(name):
    """根据公司名称推导企业类型"""
    if any(k in name for k in ["研究所", "研究院", "大学", "学院", "医院", "实验室", "中心", "科学院"]):
        return "事业单位"
    if any(k in name for k in ["中国航发", "中国航空", "中国船舶", "中国兵器", "国家电网", "中国石油", "中国石化", "中国电信", "中国移动", "中国联通", "中粮", "中化"]):
        return "央企"
    if any(k in name for k in ["集团有限公司", "城投", "建投", "交投", "国资", "市投资", "银行股份有限公司", "资产管理", "国有"]):
        return "国企"
    return "民企"


def guess_short_and_industry(name):
    """根据公司名称推导规范简称与官方行业"""
    clean = normalize_name(name)
    for prefix in ["中国", "国家", "北京", "上海", "深圳", "天津", "江苏", "浙江", "广东", "山东", "四川", "重庆", "湖北", "湖南"]:
        if clean.startswith(prefix) and len(clean) > len(prefix) + 2:
            clean = clean[len(prefix):]
            break

    for suffix in [
        "股份有限公司分公司", "股份有限公司", "有限责任公司", "有限公司", "集团有限公司", "集团",
        "研究所", "研究院", "实验室"
    ]:
        if clean.endswith(suffix) and len(clean) > len(suffix):
            clean = clean[:-len(suffix)]
            break

    short = clean[:6] if len(clean) > 6 else clean
    if not short:
        short = name[:6]

    ind = "综合"
    if any(k in name for k in ["航发", "航空", "航天", "军工", "兵器"]): ind = "军工/航天/航空"
    elif any(k in name for k in ["银行", "证券", "期货", "信托", "保险", "投资", "基金", "金融"]): ind = "金融业"
    elif any(k in name for k in ["邮政", "物流", "快递", "供应链", "运输", "海运", "港务"]): ind = "物流/供应链/交通运输"
    elif any(k in name for k in ["机器人", "自动化"]): ind = "机器人"
    elif any(k in name for k in ["芯片", "半导体", "集成电路", "微电子"]): ind = "硬件/半导体/芯片"
    elif any(k in name for k in ["人工智能", "大模型", "算法"]): ind = "人工智能"
    elif any(k in name for k in ["软件", "信息技术", "互联网", "网络"]): ind = "IT/互联网/游戏"
    elif any(k in name for k in ["材料", "化工", "能源", "石化"]): ind = "材料/能源/化工"
    elif any(k in name for k in ["环保", "废气", "治污", "水务", "固废"]): ind = "环保"
    elif any(k in name for k in ["新能源", "光伏", "风电", "储能", "锂电"]): ind = "新能源"
    elif any(k in name for k in ["机械", "机电", "装备", "制造", "重工"]): ind = "机械/制造业"

    return short, ind


def extract_zhaopin_info(context, url):
    """
    通过底层 window.__INITIAL_DATA__ 秒级解析智联校园招聘页面的法定工商全称与地址
    """
    page = context.new_page()
    try:
        page.goto(url, timeout=20000)
        page.wait_for_timeout(2500)

        info = page.evaluate("""() => {
            const data = {
                fullName: null,
                shortName: null,
                address: null,
                city: null,
                desc: null
            };

            const initial = window.__INITIAL_DATA__;
            if (initial && initial.company) {
                const base = initial.company.companyState?.companyBase;
                if (base) {
                    data.fullName = base.campusCompanyName || base.campusOrgName;
                    data.shortName = base.campusCompanyName;
                    data.city = base.cityName;
                    data.address = base.address;
                    data.desc = base.companyDescription || base.companyDescWithHtml || '';
                }
            }
            return data;
        }""")

        raw_name = info.get("fullName") or ""
        city = info.get("city") or ""
        desc = info.get("desc") or ""

        # 检查是否为简称（如“中邮投资”），需从正文首句寻找工商全称
        full_name = raw_name
        if desc:
            import re
            m = re.search(r'([\u4e00-\u9fa5（）\(\)]{4,25}(?:有限公司|股份有限公司|研究所|研究院))', desc)
            if m:
                extracted = m.group(1)
                if raw_name in extracted or len(extracted) > len(raw_name):
                    full_name = extracted

        full_name = normalize_name(full_name)
        short_name, industry = guess_short_and_industry(full_name)
        comp_type = guess_type(full_name)
        location = city if city else (info.get("address", "")[:10] or "北京")

        return {
            "网站链接": url,
            "公司名称": full_name,
            "简称": short_name,
            "类型": comp_type,
            "行业": industry,
            "地点": location.strip()
        }
    except Exception as e:
        print(f"  ⚠️ 解析 URL 异常: {url}, 错误: {e}")
        return None
    finally:
        page.close()


def ensure_company_in_basic(page_basic, item):
    """
    在公司列表 (company-basic) 查重并保证存在且完整
    """
    cname = normalize_name(item["公司名称"])
    short = item.get("简称", "").strip()
    ctype = item.get("类型", "").strip()
    ind = item.get("行业", "综合").strip()
    loc = item.get("地点", "").strip()
    ind_id = INDUSTRY_MAP.get(ind, ["13"])

    page_basic.bring_to_front()
    close_visible_dialogs(page_basic)

    # 查重搜索
    search_input = page_basic.locator("input[placeholder*='输入关键词搜索']").first
    search_btn = page_basic.locator("button:has-text('搜索')").first
    search_input.fill("")
    search_input.fill(cname)
    search_btn.click()
    page_basic.wait_for_timeout(1500)

    rows = page_basic.locator(".el-table__body-wrapper tbody tr")
    matched_idx = -1
    matched_row = None

    for i in range(rows.count()):
        tds = [rows.nth(i).locator("td").nth(j).inner_text().strip() for j in range(7)]
        if len(tds) > 1 and normalize_name(tds[1]) == cname:
            matched_idx = i
            matched_row = tds
            break

    if matched_idx == -1:
        # 未收录，执行【手动新增】
        print(f"  ➕ 公司库未收录【{cname}】，执行【新增公司 -> 手动新增】...", flush=True)
        page_basic.locator("button:has-text('新增公司')").first.click()
        page_basic.wait_for_timeout(600)
        page_basic.locator("button:has-text('手动新增')").first.click()
        page_basic.wait_for_timeout(800)

        diag = page_basic.locator(".el-dialog:visible").last
        diag.locator("input[placeholder*='请输入名称']").first.fill(cname)
        if short:
            diag.locator("input[placeholder*='请输入简称']").first.fill(short)
        if loc:
            diag.locator("input[placeholder*='请输入地点']").first.fill(loc)

        # 纯净注入类型
        if ctype:
            set_clean_org_type(page_basic, ctype)

        # 注入行业
        inject_industry_safely(page_basic, ind_id)
        page_basic.wait_for_timeout(200)

        diag.locator("button:has-text('确 定')").last.click(force=True)
        wait_modal_gone(page_basic)
        page_basic.wait_for_timeout(1000)
        print(f"  ✅ 【{cname}】新增建档成功！", flush=True)
        return True

    # 已收录，检查是否缺字段需要补齐
    cur_short = matched_row[2] if len(matched_row) > 2 else ""
    cur_type = matched_row[3] if len(matched_row) > 3 else ""
    cur_ind = matched_row[4] if len(matched_row) > 4 else ""

    need_fix_short = bool(short and not cur_short)
    need_fix_type = bool(ctype and cur_type != ctype)
    need_fix_ind = bool(ind and cur_ind != ind)

    if not (need_fix_short or need_fix_type or need_fix_ind):
        print(f"  ✅ 公司库已收录【{cname}】且档案完整，无需补齐。", flush=True)
        return True

    print(f"  🔧 公司库【{cname}】字段不完整 (简称:'{cur_short}', 类型:'{cur_type}', 行业:'{cur_ind}')，执行编辑补齐...", flush=True)
    edit_btn = rows.nth(matched_idx).locator("button:has-text('编辑')").first
    edit_btn.click(force=True)
    page_basic.wait_for_timeout(600)

    diag = page_basic.locator(".el-dialog:visible").last
    if need_fix_short:
        diag.locator("input[placeholder*='请输入简称']").first.fill(short)
    if need_fix_type:
        set_clean_org_type(page_basic, ctype)
    if need_fix_ind:
        inject_industry_safely(page_basic, ind_id)

    diag.locator("button:has-text('确 定')").last.click(force=True)
    wait_modal_gone(page_basic)
    page_basic.wait_for_timeout(1000)
    print(f"  ✅ 【{cname}】档案补齐成功！", flush=True)
    return True


def configure_website_row(page_site, url, comp_name):
    """
    在网站列表页回填公司全称并保存闭环（URL 动态寻行 + 弹窗 URL 签名双向熔断校验）
    """
    page_site.bring_to_front()
    close_visible_dialogs(page_site)
    clean_name = normalize_name(comp_name)

    # 1. 动态实时寻行，彻底杜绝并发行号错位
    matched_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
        has=page_site.locator(f"td:has-text('{url}')")
    ).first

    if matched_row.count() == 0 or not matched_row.is_visible():
        print(f"  ⚠️ 当前页未找到包含 URL [{url}] 的行", flush=True)
        return False

    print(f"  🎯 命中匹配行，点击【配置】...", flush=True)
    matched_row.locator("button:has-text('配置')").first.click(force=True)
    page_site.wait_for_timeout(800)

    diag = page_site.locator(".el-dialog:visible").last

    # 2. 弹窗 URL 双向熔断锁
    dialog_url = diag.locator("input[placeholder='请输入网站链接']").first.input_value().strip()
    if dialog_url != url:
        print(f"  🚨 [安全熔断] 弹窗URL [{dialog_url}] != 目标URL [{url}]，立即关闭！", flush=True)
        diag.locator(".el-dialog__headerbtn").click()
        page_site.wait_for_timeout(400)
        return False

    # 3. 回填公司工商全称（严禁填简称）
    comp_input = diag.locator("input[placeholder='请输入公司名称']").first
    comp_input.fill("")
    comp_input.type(clean_name, delay=50)
    page_site.wait_for_timeout(1200)

    # 4. 下拉精准点选（兼容全半角括号）
    selected = page_site.evaluate("""(name) => {
        const norm = (s) => (s || '').replace(/\\(/g, '（').replace(/\\)/g, '）').trim();
        const target = norm(name);
        const items = Array.from(document.querySelectorAll(
            '.el-select-dropdown:not([style*="display: none"]) .el-select-dropdown__item, ' +
            '.el-autocomplete-suggestion:not([style*="display: none"]) li'
        ));
        for (const it of items) {
            const txt = norm(it.innerText);
            if (txt === target || (target && txt.includes(target)) || (txt && target.includes(txt))) {
                it.click();
                return it.innerText.trim();
            }
        }
        return null;
    }""", clean_name)

    if selected:
        print(f"  🔘 下拉精准选中: 【{selected}】", flush=True)
        page_site.wait_for_timeout(400)
    else:
        print(f"  ⚠️ 未在下拉建议中直接命中，尝试 Enter 提交...", flush=True)
        comp_input.press("Enter")
        page_site.wait_for_timeout(300)

    # 5. 点击确定保存
    diag.locator("button:has-text('确 定')").last.click(force=True)
    wait_modal_gone(page_site)
    page_site.wait_for_timeout(1000)

    # 6. 重新动态核验当前行闭环状态
    re_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
        has=page_site.locator(f"td:has-text('{url}')")
    ).first
    if re_row.count() > 0:
        tds = [re_row.locator("td").nth(j).inner_text().strip() for j in range(5)]
        r_name = tds[1] if len(tds) > 1 else ""
        r_type = tds[2] if len(tds) > 2 else ""
        r_ind = tds[3] if len(tds) > 3 else ""
        if r_type and r_ind:
            print(f"  🎉 闭环成功 -> 公司:{r_name} | 类型:{r_type} | 行业:{r_ind}", flush=True)
            return True
        else:
            print(f"  ⚠️ 配置后字段仍未完整带出: 公司:{r_name}, 类型:{r_type}, 行业:{r_ind}", flush=True)
            return False
    return True


def check_row_tidy(page_site, url):
    """动态检查某 URL 行是否已达成齐整闭环"""
    re_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
        has=page_site.locator(f"td:has-text('{url}')")
    ).first
    if re_row.count() > 0:
        tds = [re_row.locator("td").nth(j).inner_text().strip() for j in range(5)]
        r_name = tds[1] if len(tds) > 1 else ""
        r_type = tds[2] if len(tds) > 2 else ""
        r_ind = tds[3] if len(tds) > 3 else ""
        return bool(r_name and r_type and r_ind), r_name, r_type, r_ind
    return False, "", "", ""


def main():
    parser = argparse.ArgumentParser(description="智联招聘爬虫任务自动处理脚本")
    parser.add_argument("--file", "-f", type=str, default=None, help="指定 JSON 文件路径进行驱动处理")
    parser.add_argument("--scan-only", action="store_true", help="仅扫描当前页并导出 JSON")
    args = parser.parse_args()

    print("=" * 65)
    print("🚀 启动智联招聘爬虫任务自动化处理器 (zhaopin_auto_runner)")
    print("=" * 65)

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(CDP_URL)
        except Exception as e:
            print(f"❌ 无法连接到 CDP 调试端口 ({CDP_URL}): {e}")
            print("请确认 Chrome 已通过 --remote-debugging-port=9222 启动！")
            return

        ctx = browser.contexts[0]
        page_site = None
        page_basic = None

        for pg in ctx.pages:
            if "/#/company/index" in pg.url:
                page_site = pg
            elif "/#/company-basic/index" in pg.url:
                page_basic = pg

        if not page_site:
            print("❌ 未在浏览器中找到【网站列表】页面 (/#/company/index)！")
            print(f"当前页面列表: {[pg.url for pg in ctx.pages]}")
            return

        if not page_basic:
            print("ℹ️ 未检测到【公司列表】页面，自动新建标签页打开公司基本信息库...")
            page_basic = ctx.new_page()
            page_basic.goto("http://admin.jobleap.betaquantity.com/#/company-basic/index")
            page_basic.wait_for_timeout(2500)

        print("✅ 成功连接目标页面：")
        print(f"  网站列表页: {page_site.url}")
        print(f"  公司列表页: {page_basic.url}\n")

        # -------------------------------------------------------------
        # 1. 确定待处理的企业清单
        # -------------------------------------------------------------
        task_items = []

        if args.file:
            print(f"📂 读取指定的中间 JSON 文件: {args.file}")
            with open(args.file, "r", encoding="utf-8") as f:
                task_items = json.load(f)
        else:
            print("🔍 自动扫描网站列表当前页所有未闭环的【zhao_pin_spider_task】行...")
            rows_data = page_site.evaluate("""() => {
                return Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr')).map((tr, idx) => {
                    const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                    return {
                        idx,
                        id: tds[0],
                        name: tds[1],
                        type: tds[2],
                        industry: tds[3],
                        task: tds[4],
                        url: tds[6]
                    };
                });
            }""")

            zp_rows = [r for r in rows_data if r["task"] == "zhao_pin_spider_task"]
            print(f"  找到 {len(zp_rows)} 条智联招聘任务行")

            unfilled = [r for r in zp_rows if not (r["name"] and r["type"] and r["industry"])]
            print(f"  其中 {len(unfilled)} 条尚未完整闭环，需要处理\n")

            if not unfilled:
                print("🎉 当前页所有智联招聘任务已全部完整闭环，无需处理！")
                return

            # 对每一条 URL，通过智联底层一秒提取法定全称
            print("🌐 正在通过底层架构数据解析各任务的法定工商全称...")
            for r in unfilled:
                u = r["url"]
                if not u:
                    continue
                print(f"  正在解析: {u}")
                item = extract_zhaopin_info(ctx, u)
                if item and item.get("公司名称"):
                    print(f"  👉 解析成功: 【{item['公司名称']}】 (简称:{item['简称']}, 类型:{item['类型']}, 行业:{item['行业']}, 地点:{item['地点']})")
                    task_items.append(item)
                else:
                    print(f"  ⚠️ 无法解析该链接对应的企业: {u}")

            # 导出保存中间 JSON 备份
            with open(DEFAULT_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(task_items, f, ensure_ascii=False, indent=2)
            print(f"💾 中间任务清单已同步保存至: {DEFAULT_JSON_PATH}\n")

            if args.scan_only:
                print("✅ 纯扫描模式执行完毕。")
                return

        # -------------------------------------------------------------
        # 2. 闭环工作流：检查已闭环跳过 ➡️ 回填网站配置 ➡️ 未完整则公司库补齐并再次回填
        # -------------------------------------------------------------
        print("=" * 65)
        print(f"⚙️ 开始批量执行 {len(task_items)} 家企业的极简闭环流程")
        print("=" * 65)

        success_count = 0
        for idx, item in enumerate(task_items, 1):
            cname = normalize_name(item["公司名称"])
            u = item["网站链接"]
            print(f"\n[{idx}/{len(task_items)}] 处理企业: 【{cname}】")

            # 检查当前行是否早已闭环
            is_already_tidy, r_name, r_type, r_ind = check_row_tidy(page_site, u)
            if is_already_tidy:
                print(f"  ✨ 该行已达成齐整闭环 (名称:{r_name}, 类型:{r_type}, 行业:{r_ind})，跳过！")
                success_count += 1
                continue

            # 步骤 1：在网站列表回填公司工商全称并确定
            is_tidy = configure_website_row(page_site, u, cname)

            if is_tidy:
                print(f"  ⚡ 网站列表已自动关联出完整类型与行业，无需访问公司库，秒级闭环！")
                success_count += 1
            else:
                # 步骤 2：若类型或行业仍为空，前往公司列表补齐/建档
                print(f"  ⚠️ 网站列表未完整带出属性，前往公司列表补充完善...")
                ensure_company_in_basic(page_basic, item)

                # 步骤 3：公司库补齐后，切回网站列表再次点选回填
                print(f"  🔄 公司库档案补充完毕，切回网站列表重新回填并精准绑定...")
                is_tidy_again = configure_website_row(page_site, u, cname)
                if is_tidy_again:
                    print(f"  🎉 二次回填绑定成功，已达成齐整闭环！")
                    success_count += 1
                else:
                    # 尝试刷新网站列表页面看是否联动
                    print(f"  🔄 刷新网站列表页检查是否联动...")
                    page_site.reload()
                    page_site.wait_for_timeout(2500)
                    is_tidy_reload, r_name, r_type, r_ind = check_row_tidy(page_site, u)
                    if is_tidy_reload:
                        print(f"  🎉 刷新后已成功联动闭环 -> 类型:{r_type} | 行业:{r_ind}")
                        success_count += 1
                    else:
                        print(f"  ⚠️ 提示：该公司在公司库已完善，但在网站列表仍未自动带出 (类型:{r_type}, 行业:{r_ind})，符合死律特殊情况")

        print("\n" + "=" * 65)
        print(f"🏁 全部执行完毕！成功闭环: {success_count}/{len(task_items)}")
        print("=" * 65)


if __name__ == "__main__":
    main()
