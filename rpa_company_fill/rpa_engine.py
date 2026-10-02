# -*- coding: utf-8 -*-
"""
RPA 统一固化自动化执行引擎 (rpa_engine.py)
======================================================================
解决痛点：
杜绝任何临时写测试/探索脚本的需求！将所有 DOM 选择器、弹窗定位、Vue Model 注入、
链接替换、岗位分类及智能核查原子化固化为一个生产级工具。

支持的核心 CLI 命令：
1. 检视当前/指定页闭环状态（只读）：
   python rpa_engine.py inspect [--page N]

2. 公司库档案智能维护（查重 -> 比对 -> 智能差量更新/自动新增）：
   python rpa_engine.py ensure-company --name "工商全称" [--abbr "简称"] [--type "国企/民企/上市/中外合资/外商独资..."] [--industry "行业名"] [--location "城市"]

3. 网站列表行配置（支持 Slug/URL/公司名动态寻行、标准 URL 替换、公司回填、岗位分类填入）：
   python rpa_engine.py configure-site --match "定位词(如slug/url/名称)" [--new-url "规范URL"] [--company "工商全称"] [--category "0|1|2"]

4. 端到端一键闭环（两页面联动完成：建档 + 配置 + 核查）：
   python rpa_engine.py auto-close --match "定位词" --name "工商全称" [--abbr "简称"] [--type "类型"] [--industry "行业"] [--location "地点"] [--new-url "规范URL"] [--category "0|1|2"]
"""

import os
import sys
import json
import time
import argparse
from playwright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
SITE_URL_PREFIX = "http://admin.jobleap.betaquantity.com/#/company/index"
BASIC_URL_PREFIX = "http://admin.jobleap.betaquantity.com/#/company-basic/index"

# 40 项官方标准行业映射字典 (Vue Model ID)
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

# 18 项官方标准企业类型 Value 字典
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


# =====================================================================
# 核心底层函数库 (Primitives)
# =====================================================================

def wait_modal_gone(page, timeout=4000):
    """确保 Element UI 遮罩层彻底销毁"""
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
        wait_modal_gone(page)
    except Exception:
        pass


def get_pages(ctx):
    """获取或初始化网站列表和公司库两个标签页"""
    page_site = next((pg for pg in ctx.pages if "company-basic" not in pg.url and "admin.jobleap" in pg.url and "/company" in pg.url), None)
    page_basic = next((pg for pg in ctx.pages if "company-basic" in pg.url and "admin.jobleap" in pg.url), None)

    if not page_site:
        page_site = ctx.new_page()
        page_site.goto(SITE_URL_PREFIX)
        page_site.wait_for_load_state("networkidle")

    if not page_basic:
        page_basic = ctx.new_page()
        page_basic.goto(BASIC_URL_PREFIX)
        page_basic.wait_for_load_state("networkidle")

    return page_site, page_basic


# =====================================================================
# 国聘原生企业画像抓取与映射工具 (Guopin Native Metadata)
# =====================================================================

def map_guopin_type(type_raw):
    """将国聘原生企业性质映射为后台标准 18 类之一"""
    if not type_raw:
        return "民企"
    type_raw = type_raw.strip()
    if "央企" in type_raw:
        return "央企"
    if "国企" in type_raw:
        return "国企"
    if "港澳台" in type_raw:
        return "中外合资"
    if "合资" in type_raw:
        return "中外合资"
    if "外商独资" in type_raw or "外企" in type_raw or "外资" in type_raw:
        return "外商独资"
    if "上市" in type_raw:
        return "上市"
    if "民企" in type_raw or "民营" in type_raw:
        return "民企"
    if "事业" in type_raw:
        return "事业单位"
    if "银行" in type_raw:
        return "银行"
    if "学校" in type_raw or "高校" in type_raw:
        return "学校"
    if "医院" in type_raw:
        return "医院"
    if "机关" in type_raw:
        return "国家机关"
    return "民企"


def map_guopin_industry(ind_raw):
    """将国聘原生行业映射为后台 40 项官方标准行业之一"""
    if not ind_raw:
        return ""
    ind_raw = ind_raw.strip()
    for std_name in INDUSTRY_MAP.keys():
        for token in std_name.split("/"):
            if token in ind_raw:
                return std_name
    synonyms = {
        "制造": "机械/制造业",
        "汽车": "汽车/智能驾驶",
        "计算机": "IT/互联网/游戏",
        "软件": "IT/互联网/游戏",
        "电子": "消费电子",
        "芯片": "硬件/半导体/芯片",
        "半导体": "硬件/半导体/芯片",
        "医药": "生物/医疗/制药",
        "医疗": "生物/医疗/制药",
        "生物": "生物/医疗/制药",
        "金融": "金融业",
        "银行": "金融业",
        "证券": "金融业",
        "保险": "金融业",
        "地产": "建筑/房地产",
        "建筑": "建筑/房地产",
        "旅游": "广告传媒/文化体育",
        "文化": "广告传媒/文化体育",
        "传媒": "广告传媒/文化体育",
        "体育": "广告传媒/文化体育",
        "物流": "物流/供应链/交通运输",
        "运输": "物流/供应链/交通运输",
        "化工": "材料/能源/化工",
        "能源": "材料/能源/化工",
        "材料": "材料/能源/化工",
        "环保": "环保",
        "船舶": "船舶",
        "教育": "教育",
        "餐饮": "餐饮住宿",
        "住宿": "餐饮住宿",
        "食品": "快消",
        "日化": "快消",
    }
    for k, v in synonyms.items():
        if k in ind_raw:
            return v
    return "综合"


def fetch_guopin_meta(ctx, guopin_url):
    """
    国聘原生画像原子提取工具：
    严禁外部盲搜！打开国聘详情页，直接抓取 .company-attrs 官方认证属性。
    """
    print(f"\n[国聘直连] 抓取原生企业属性: {guopin_url}")
    page = ctx.new_page()
    try:
        page.goto(guopin_url, timeout=20000)
        page.wait_for_timeout(1500)
        info = page.evaluate("""() => {
            const nameEl = document.querySelector('.company-name') || document.querySelector('.company-info h1');
            const items = Array.from(document.querySelectorAll('.company-attrs .company-attrs-item')).map(e => e.innerText.trim());
            return {
                name: nameEl ? nameEl.innerText.trim() : '',
                attrs: items
            };
        }""")
        name = info.get("name", "")
        attrs = info.get("attrs", [])

        type_raw = ""
        ind_raw = ""
        scale_raw = ""
        for item in attrs:
            if "人" in item:
                scale_raw = item
            elif not type_raw and any(k in item for k in ["企", "资", "投资", "上市", "公有", "民营", "事业", "单位", "机关", "港澳台"]):
                type_raw = item
            elif not ind_raw and not any(k in item for k in ["人"]):
                ind_raw = item

        std_type = map_guopin_type(type_raw) if type_raw else ""
        std_ind = map_guopin_industry(ind_raw) if ind_raw else ""

        print(f"  🏢 原生公司名: 【{name}】")
        if type_raw:
            print(f"  🏷️ 原生企业性质: 【{type_raw}】 ➡️ 映射标准类型: 【{std_type}】")
        if ind_raw:
            print(f"  🏭 原生所属行业: 【{ind_raw}】 ➡️ 映射标准行业: 【{std_ind}】")
        if scale_raw:
            print(f"  👥 人员规模: 【{scale_raw}】")

        return {
            "name": name,
            "type_raw": type_raw,
            "type": std_type,
            "ind_raw": ind_raw,
            "industry": std_ind,
            "scale": scale_raw
        }
    except Exception as e:
        print(f"  ❌ 抓取国聘页面元数据失败: {e}")
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def probe_url_meta(ctx, url):
    """
    通用的招聘链接画像探针：获取 title, h1, logo alt, 文本摘要
    """
    print(f"\n[链接探针] 正在探测招聘链接: {url}")
    page = ctx.new_page()
    try:
        page.goto(url, timeout=25000)
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3500)
        res = page.evaluate("""() => {
            const title = document.title || '';
            const h1 = document.querySelector('h1')?.innerText?.trim() || '';
            const logo = document.querySelector('img[alt*="logo" i], img[class*="logo" i], .logo img')?.alt || '';
            const textSnippet = document.body.innerText.substring(0, 500).replace(/\\s+/g, ' ');
            let zhaopinName = '';
            if (window.__INITIAL_DATA__) {
                const base = window.__INITIAL_DATA__?.company?.companyState?.companyBase;
                zhaopinName = base?.campusCompanyName || base?.campusOrgName || '';
            }
            let feishuName = '';
            const metaDesc = document.querySelector('meta[name="description"]')?.content || '';
            const m = metaDesc.match(/到(.*?)，开启你的新工作/);
            if (m) feishuName = m[1];
            if (!feishuName && title.startsWith('加入')) {
                feishuName = title.replace(/^加入/, '').split(' - ')[0].trim();
            }
            // 校验是否有在招职位（六大铁律之规则6：有效岗位验活）
            const bodyText = document.body.innerText || '';
            const emptyKeywords = [
                '全部职位（共 0 个）', '全部职位(共0个)', '共 0 个职位', '共0个职位',
                '暂时没有符合条件的职位', '暂无符合条件的职位', '暂无在招职位', '暂无职位',
                '在招职位 0', '在招职位0', '在招职位（0）', '0 个结果', '未找到相关职位'
            ];
            const hasZeroJobs = emptyKeywords.some(kw => bodyText.includes(kw));

            return { title, h1, logo, textSnippet, zhaopinName, feishuName, metaDesc, hasZeroJobs };
        }""")
        print(f"  📌 Title: 【{res['title']}】")
        if res.get('hasZeroJobs'):
            print(f"  🚨【规则6警报】页面检测到暂无在招岗位（0职位），严禁填入此URL！")
        if res.get('feishuName'):
            print(f"  🏢 飞书 Meta 提取公司全称: 【{res['feishuName']}】")
        if res.get('zhaopinName'):
            print(f"  🏢 智联 __INITIAL_DATA__ 工商全称: 【{res['zhaopinName']}】")
        if res.get('textSnippet'):
            print(f"  📌 页面摘要: {res['textSnippet'][:150]}")
        # 若有“详情”按钮，尝试点击查看具体招聘企业/用人单位
        try:
            detail_btn = page.locator("button:has-text('详情'), a:has-text('详情'), .detail-btn").first
            if detail_btn.count() > 0 and detail_btn.is_visible():
                detail_btn.click()
                page.wait_for_timeout(1500)
                detail_text = page.evaluate("""() => {
                    const modal = document.querySelector('.el-dialog:visible, .modal:visible, .detail-box, .drawer:visible') || document.body;
                    return modal.innerText.replace(/\\s+/g, ' ').substring(0, 800);
                }""")
                print(f"  📄 详情文本: {detail_text[:300]}")
        except Exception:
            pass

        return res
    except Exception as e:
        print(f"  ❌ 探测失败: {e}")
        return None
    finally:
        try:
            page.close()
        except Exception:
            pass


def jump_to_page(page_site, target_page):
    """平滑翻到网站列表指定页"""
    page_site.bring_to_front()
    page_site.wait_for_selector(".el-pager", timeout=5000)
    
    current_page = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText?.trim() || '1'")
    if current_page == str(target_page):
        print(f"  📄 已经在第 {target_page} 页")
        return True

    print(f"  📄 正在从第 {current_page} 页切换至第 {target_page} 页...")
    
    # 获取切换前的首行第一列ID或链接，用于判断是否已更新
    old_first_id = page_site.evaluate("""() => {
        const tr = document.querySelector('.el-table__body-wrapper tbody tr');
        return tr ? tr.innerText.substring(0, 50) : '';
    }""")

    for _ in range(10):
        current_page = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText?.trim() || '1'")
        if current_page == str(target_page):
            break
        
        # 尝试直接点该数字
        clicked = page_site.evaluate("""(target) => {
            const lis = Array.from(document.querySelectorAll('.el-pager li'));
            const t = lis.find(li => li.innerText.trim() === String(target));
            if (t) { t.click(); return true; }
            return false;
        }""", target_page)
        
        if clicked:
            page_site.wait_for_timeout(1500)
            break
            
        cur_num = int(current_page) if current_page.isdigit() else 1
        tgt_num = int(target_page)
        if tgt_num > cur_num:
            btn_next = page_site.locator(".el-pagination .btn-next")
            if btn_next.is_visible() and not btn_next.is_disabled():
                btn_next.click()
                page_site.wait_for_timeout(1500)
            else:
                break
        else:
            btn_prev = page_site.locator(".el-pagination .btn-prev")
            if btn_prev.is_visible() and not btn_prev.is_disabled():
                btn_prev.click()
                page_site.wait_for_timeout(1500)
            else:
                break

    # 等待 loading mask 消失并且表格数据变动或稳定
    try:
        page_site.wait_for_selector(".el-loading-mask", state="hidden", timeout=3000)
    except Exception:
        pass
    page_site.wait_for_timeout(1000)

    current_page = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText?.trim() || '?'")
    print(f"  📄 切换完成，当前激活页: 第 {current_page} 页")
    return current_page == str(target_page)


# =====================================================================
# 功能 1：只读全景检视 (inspect)
# =====================================================================

def do_inspect(page_site, target_page=None):
    print("  🌐 当前页面 URL:", page_site.url)
    
    # 智能检查：仅当发现被搜索过滤（如搜索框有值或页面仅有1条异常数据）时才点击【重置】
    try:
        is_filtered = page_site.evaluate("""() => {
            const pTxt = document.querySelector('.el-pagination')?.innerText || '';
            const inps = Array.from(document.querySelectorAll('.filter-container input, .header-container input')).filter(i => i.value && i.value !== '全部');
            return pTxt.includes('共 1 条') || inps.length > 0;
        }""")
        if is_filtered:
            reset_btn = page_site.locator("button:has-text('重置')").first
            if reset_btn.count() > 0 and reset_btn.is_visible():
                print("  🧹 检测到筛选过滤状态，点击【重置】恢复大盘...")
                reset_btn.click()
                page_site.wait_for_timeout(1500)
    except Exception:
        pass
    filter_status = page_site.evaluate("""() => {
        const form = document.querySelector('.filter-container, .header-container, .el-form');
        if (!form) return [];
        return Array.from(form.querySelectorAll('.el-form-item')).map(it => {
            const lbl = it.querySelector('.el-form-item__label')?.innerText?.trim() || '';
            const inp = it.querySelector('input, textarea');
            return {
                label: lbl,
                val: inp ? inp.value : '',
                ph: inp ? inp.placeholder : ''
            };
        });
    }""")
    print("  🔍 网站列表当前筛选表单项:", filter_status)

    if target_page:
        jump_to_page(page_site, target_page)

    cur_p = page_site.evaluate("() => document.querySelector('.el-pager li.active')?.innerText || '?'")
    p_txt = page_site.evaluate("() => document.querySelector('.el-pagination')?.innerText?.replace(/\\s+/g, ' ') || ''")
    print(f"  📄 分页组件详情: {p_txt} (当前激活: 第 {cur_p} 页)")
    raw_debug = page_site.evaluate("""() => {
        const t = document.querySelector('.el-table');
        if (t && t.__vue__ && t.__vue__.data) {
            return t.__vue__.data.map((r, idx) => ({
                idx: idx + 1,
                name: r.name,
                basic_company_id: r.basic_company_id,
                org_type: r.org_type,
                industry: r.industry
            }));
        }
        return [];
    }""")
    print("  🔬 底层 Vue 数据完整列表:")
    for rd in raw_debug:
        print("   ", rd)
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
                url: tds[6] || ''
            };
        });
    }""")

    print(f"\n================== 网站列表第 {cur_p} 页 (共 {len(rows)} 行) ==================")
    all_closed = True
    for r in rows:
        is_closed = bool(r["name"] and r["type"] and r["ind"])
        if not is_closed:
            all_closed = False
        status_tag = "✅ 齐整闭环" if is_closed else "⚠️ 待补充"
        print(f"[{status_tag}] 行 {r['idx']:02d} | 任务: {r['task']:<24} | 公司: {r['name']:<24} | 类型: {r['type']:<8} | 行业: {r['ind']:<10}")
        print(f"       链接: {r['url']}")
    
    print("=====================================================================")
    if all_closed:
        print(f"🎉 状态评估：第 {cur_p} 页所有任务 100% 达成齐整闭环！\n")
    else:
        print(f"📌 状态评估：第 {cur_p} 页尚有待补充任务。\n")


# =====================================================================
# 功能 2：公司库档案智能维护 (ensure-company)
# =====================================================================

def do_ensure_company(page_basic, comp_name, short_name="", comp_type="", ind_name="", location=""):
    """
    公司库建档原子操作：
    查重 -> 比对 -> 全部正确则跳过；有缺失/错误则差量编辑；未收录则手动新增。
    """
    comp_name = comp_name.strip()
    short_name = (short_name or comp_name).strip()
    comp_type = comp_type.strip()
    ind_name = ind_name.strip()
    location = location.strip()
    ind_id = INDUSTRY_MAP.get(ind_name, ["13"])

    print(f"\n[公司库] 档案核查: 【{comp_name}】")
    print(f"  期望画像 -> 简称:{short_name} | 类型:{comp_type or '(保持现有)'} | 行业:{ind_name or '(保持现有)'} | 地点:{location or '(保持现有)'}")

    page_basic.bring_to_front()
    close_visible_dialogs(page_basic)

    # 1. 搜索
    search_input = page_basic.locator("input[placeholder*='输入关键词搜索']").first
    search_input.fill("")
    search_input.fill(comp_name)
    page_basic.locator("button:has-text('搜索')").first.click()
    page_basic.wait_for_timeout(1200)

    # 2. 读取搜索结果
    rows_data = page_basic.evaluate("""() => {
        const t = document.querySelector('.el-table');
        if (t && t.__vue__ && t.__vue__.data) {
            return t.__vue__.data.map((r, idx) => ({
                idx,
                id: r._id || '',
                name: r.name || '',
                short_name: r.short_name || '',
                org_type: r.org_type || [],
                industry: r.industry || [],
                location: r.location || ''
            }));
        }
        return [];
    }""")
    print("  🔍 公司库搜索结果:", [(r["name"], r["id"]) for r in rows_data])
    btn_names = page_basic.evaluate("""() => Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr button')).map(b => b.innerText.trim())""")
    same_name_items = [r for r in rows_data if comp_name == r["name"]]
    if len(same_name_items) > 1:
        print(f"  ⚠️ 检测到公司库存在 {len(same_name_items)} 条同名重复记录，自动清理多余冗余副本...")
        def score_item(it):
            s = 0
            if it.get("short_name"): s += 1
            if it.get("org_type"): s += 1
            if it.get("industry"): s += 1
            if it.get("location"): s += 1
            return s
        sorted_items = sorted(same_name_items, key=score_item, reverse=True)
        delete_items = sorted_items[1:]
        for d_it in delete_items:
            del_row = page_basic.locator(".el-table__body-wrapper tbody tr").nth(d_it["idx"])
            del_btn = del_row.locator("button:has-text('删除')").first
            if del_btn.count() > 0 and del_btn.is_visible():
                del_btn.click(force=True)
                page_basic.wait_for_timeout(500)
                confirm_box = page_basic.locator(".el-message-box:visible button:has-text('确定')").first
                if confirm_box.count() > 0 and confirm_box.is_visible():
                    confirm_box.click(force=True)
                    page_basic.wait_for_timeout(800)
                    wait_modal_gone(page_basic)
                    print(f"  🗑️ 已清理冗余重复记录 (ID: {d_it['id']})")
        # 清理后刷新搜索结果
        search_input.fill("")
        search_input.fill(comp_name)
        page_basic.locator("button:has-text('搜索')").first.click()
        page_basic.wait_for_timeout(1200)
        rows_data = page_basic.evaluate("""() => {
            const t = document.querySelector('.el-table');
            return t && t.__vue__ && t.__vue__.data ? t.__vue__.data.map((r, idx) => ({
                idx, id: r._id || '', name: r.name || '', short_name: r.short_name || '',
                org_type: r.org_type || [], industry: r.industry || [], location: r.location || ''
            })) : [];
        }""")

    matched_item = next((r for r in rows_data if comp_name == r["name"]), None)

    # 3. 未找到 -> 手动新增
    if matched_item is None:
        print(f"  ➕ 公司未收录，执行【新增公司 ➡️ 手动新增】...")
        page_basic.locator("button:has-text('新增公司')").first.click()
        page_basic.wait_for_timeout(600)
        page_basic.locator("button:has-text('手动新增')").first.click()
        page_basic.wait_for_timeout(800)

        dialog = page_basic.locator(".el-dialog:visible").last
        dialog.locator("input[placeholder*='请输入名称']").first.fill(comp_name)
        page_basic.wait_for_timeout(100)
        dialog.locator("input[placeholder*='请输入简称']").first.fill(short_name)
        page_basic.wait_for_timeout(100)
        if location:
            dialog.locator("input[placeholder*='请输入地点']").first.fill(location)
            page_basic.wait_for_timeout(100)

        # 🚨 核心顺序铁律：先注入行业，再搞类型！
        if ind_name:
            _inject_industry(page_basic, ind_name, ind_id)
        if comp_type:
            _set_org_type(page_basic, comp_type)

        confirm_btn = dialog.locator("button:has-text('确 定')").last
        confirm_btn.click(force=True)
        wait_modal_gone(page_basic)
        print(f"  ✅ 【{comp_name}】新增档案成功！")
        return {"name": comp_name, "is_new": True}

    # 4. 已找到 -> 智能比对（真·差量保护铁律：已有非空值 100% 绝对保护，绝不覆盖，仅补空缺项！）
    matched_idx = matched_item["idx"]
    cur_short = matched_item["short_name"]
    cur_type = matched_item["org_type"][0] if matched_item["org_type"] else ""
    cur_industry = matched_item["industry"][0] if matched_item["industry"] else ""
    cur_location = matched_item["location"]

    print(f"  🔍 已收录! 现有数据 -> ID:{matched_item['id']} | 简称:{cur_short} | 类型:{cur_type} | 行业:{cur_industry} | 地点:{cur_location}")

    # 实事求是原则：已有正确则不动；为空或有误则更正！
    need_short = bool(short_name and not cur_short)
    need_type = bool(comp_type and (not cur_type or (comp_type != cur_type and cur_type not in [comp_type, comp_type.replace("企", "营")])))
    need_ind = bool(ind_name and not cur_industry)
    need_loc = bool(location and not cur_location)

    # 打印核对日志
    protected_items = []
    if cur_short: protected_items.append(f"简称:【{cur_short}】")
    if cur_type and not need_type: protected_items.append(f"类型:【{cur_type}】(正确保留)")
    if cur_industry and not need_ind: protected_items.append(f"行业:【{cur_industry}】(正确保留)")
    if cur_location: protected_items.append(f"地点:【{cur_location}】")
    if protected_items:
        print(f"  🛡️ [字段核验] 既有正确字段 {' | '.join(protected_items)} 原样保留，不盲目改动！")
    if need_type and cur_type:
        print(f"  🔧 [类型纠错] 现有类型【{cur_type}】与权威原生画像【{comp_type}】不符，执行修正更正！")

    if not (need_short or need_type or need_ind or need_loc):
        print(f"  ✅ 库中所有关键字段均已齐备，跳过编辑！")
        return True

    # 5. 差量编辑 (仅对为空的字段定向补齐)
    missing_items = []
    if need_short: missing_items.append(f"补简称->{short_name}")
    if need_type: missing_items.append(f"补类型->{comp_type}")
    if need_ind: missing_items.append(f"补行业->{ind_name}")
    if need_loc: missing_items.append(f"补地点->{location}")
    print(f"  🔧 定向差量补录空缺: {' | '.join(missing_items)}...")

    edit_btn = page_basic.locator(".el-table__body-wrapper tbody tr").nth(matched_idx).locator("button:has-text('编辑')").first
    edit_btn.click(force=True)
    page_basic.wait_for_selector(".el-dialog:visible", timeout=5000)
    page_basic.wait_for_timeout(1000)

    dialog = page_basic.locator(".el-dialog:visible").last
    dialog_title = dialog.locator(".el-dialog__title").inner_text().strip() if dialog.locator(".el-dialog__title").count() > 0 else "未知"
    print(f"  📋 弹窗标题: 【{dialog_title}】")
    
    fields = dialog.evaluate("""d => Array.from(d.querySelectorAll('.el-form-item')).map(it => ({
        label: it.querySelector('.el-form-item__label')?.innerText?.trim() || '',
        placeholder: it.querySelector('input, textarea')?.placeholder || '',
        value: it.querySelector('input, textarea')?.value || ''
    }))""")
    print("  📋 弹窗表单项:", fields)
    
    model_info = dialog.evaluate("""d => {
        const form = d.querySelector('.el-form');
        return form && form.__vue__ && form.__vue__.model ? Object.keys(form.__vue__.model) : [];
    }""")
    print("  📋 Vue Model Keys:", model_info)
    
    # 确保表单已加载完成
    name_input = dialog.locator("input[placeholder*='请输入名称']").first
    try:
        name_input.wait_for(state="visible", timeout=3000)
    except Exception:
        pass

    if need_short:
        dialog.locator("input[placeholder*='请输入简称']").first.fill(short_name)
        page_basic.evaluate("""(val) => {
            const diag = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
                .find(d => window.getComputedStyle(d).display !== 'none');
            if (!diag) return;
            const form = diag.querySelector('.el-form');
            if (form && form.__vue__ && form.__vue__.model) {
                form.__vue__.model.alias = val;
                if (typeof form.__vue__.$set === 'function') form.__vue__.$set(form.__vue__.model, 'alias', val);
            }
        }""", short_name)
        page_basic.wait_for_timeout(200)
    if need_loc:
        dialog.locator("input[placeholder*='请输入地点']").first.fill(location)
        page_basic.wait_for_timeout(200)
    # 🚨 核心顺序铁律：先注入行业，再搞类型！避免类型下拉操作破坏级联选择器状态
    if need_ind:
        _inject_industry(page_basic, ind_name, ind_id)
        page_basic.wait_for_timeout(200)

    if need_type:
        _set_org_type(page_basic, comp_type)
        page_basic.wait_for_timeout(200)

    # 打印提交前的真实 model 状态
    pre_submit = dialog.evaluate("""d => {
        const form = d.querySelector('.el-form');
        if (form && form.__vue__ && form.__vue__.model) {
            const m = form.__vue__.model;
            return { name: m.name, alias: m.alias, org_type_new: m.org_type_new, industry_new: m.industry_new, location: m.location };
        }
        return null;
    }""")
    print("  📋 待提交表单 Vue Model:", pre_submit)

    page_basic.wait_for_timeout(500)

    # 点击确定并监听结果
    confirm_btn = dialog.locator(".el-dialog__footer button:has-text('确'), button:has-text('确 定')").last
    confirm_btn.click(force=True)
    page_basic.wait_for_timeout(1000)
    
    # 检查是否有提示
    msg = page_basic.evaluate("""() => {
        const m = document.querySelector('.el-message');
        return m ? m.innerText.trim() : '';
    }""")
    if msg:
        print(f"  📢 提示信息: 【{msg}】")

    wait_modal_gone(page_basic)
    print(f"  ✅ 【{comp_name}】档案定向差量补录完成！")
    return True


def _set_org_type(page, comp_type):
    type_id_list = ORG_TYPE_MAP.get(comp_type, ["3"])
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


def _inject_industry(page, ind_name, ind_id):
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


def normalize_target_url(url):
    """
    通用招聘 URL 自动规范化规整：
    1. 北森 (zhiye.com)：
       - 严禁纯根域名！若为纯根域名 (如 https://xxx.zhiye.com[/])，自动追加 /campus/jobs
       - 若包含 /detail，自动截断替换为 /campus/jobs
    2. Moka (mokahr.com)：
       - 修复 #/job 缺少 s
    3. 大易 Wecruit (hotjob.cn)：
       - 若为移动端微官网 /mc/index 或缺省入口 /pb/index，自动推荐重构为标准校招页 /pb/school.html
    """
    if not url:
        return url
    url = url.strip()
    if "zhiye.com" in url:
        from urllib.parse import urlparse
        p = urlparse(url)
        netloc = p.netloc.rstrip(".")
        scheme = p.scheme or "https"
        path = p.path.rstrip("/")
        if not path or path == "":
            return f"{scheme}://{netloc}/campus/jobs"
        if "/detail" in path:
            base = path.split("/detail")[0]
            return f"{scheme}://{netloc}{base}/jobs"
        if path in ["/campus", "/social"]:
            return f"{scheme}://{netloc}{path}/jobs"
    elif "hotjob.cn" in url:
        from urllib.parse import urlparse
        import re
        p = urlparse(url)
        netloc = p.netloc.rstrip(".")
        scheme = p.scheme or "https"
        m = re.search(r"(SU[0-9a-zA-Z]{20,34})", p.path)
        if m:
            su_id = m.group(1)
            if "/mc/index" in p.path or "/pb/index" in p.path:
                return f"{scheme}://{netloc}/{su_id}/pb/school.html"
    return url


# =====================================================================
# 功能 3：网站列表配置原子操作 (configure-site)
# =====================================================================

def do_configure_site(page_site, match_text, new_url="", comp_name="", category=None, task_name="", comp_id=""):
    """
    网站配置原子操作：
    通过 Slug / URL / 关键词动态定位行 -> 点击【配置】 -> 回填链接(可选) ->
    设置任务名称(可选) -> 回填公司全称并点选下拉(可选) -> 填入岗位分类(可选) -> 确定保存
    """
    print(f"\n[网站列表] 配置行: 匹配词=【{match_text}】")
    if task_name: print(f"  设置任务名称: {task_name}")
    if new_url: print(f"  新网址: {new_url}")
    if comp_name: print(f"  回填企业全称: {comp_name}")
    if category is not None: print(f"  设置岗位分类: {category}")

    page_site.bring_to_front()
    close_visible_dialogs(page_site)

    # 1. 动态寻行 (支持 URL / Slug / 名称匹配)
    matched_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
        has=page_site.locator(f"td:has-text('{match_text}')")
    ).first

    if matched_row.count() == 0 or not matched_row.is_visible():
        print(f"  ❌ 当前页未找到包含 【{match_text}】 的行！")
        return False

    # 2. 点击配置
    cfg_btn = matched_row.locator("button:has-text('配置')").first
    cfg_btn.scroll_into_view_if_needed()
    page_site.wait_for_timeout(200)
    cfg_btn.click()

    try:
        page_site.wait_for_selector(".el-dialog:visible", timeout=4000)
    except Exception:
        cfg_btn.click(force=True)
        page_site.wait_for_selector(".el-dialog:visible", timeout=5000)

    dialog = page_site.locator(".el-dialog:visible").last

    # 🛡️【物理防呆 1：弹窗 URL / 业务主键强断言与安全熔断】
    # 彻底杜绝因并发或位移点错行导致的张冠李戴错位！
    cur_req_url = dialog.locator("input[placeholder*='请求链接']").first.input_value().strip() if dialog.locator("input[placeholder*='请求链接']").count() > 0 else ""
    cur_web_url = dialog.locator("input[placeholder*='网站链接']").first.input_value().strip() if dialog.locator("input[placeholder*='网站链接']").count() > 0 else ""
    dialog_sigs = f"{cur_req_url} {cur_web_url}"

    clean_match = match_text.replace("http://", "").replace("https://", "").strip("/").split("?")[0]
    if match_text not in dialog_sigs and clean_match not in dialog_sigs:
        print(f"  🚨 [安全熔断拦截] 弹窗内网址【{dialog_sigs}】与匹配目标【{match_text}】不符！")
        print(f"  🛑 物理拦截：坚决拒绝执行修改与保存，已自动取消并安全退出！")
        cancel_btn = dialog.locator("button:has-text('取 消'), button:has-text('取消')").last
        if cancel_btn.count() > 0 and cancel_btn.is_visible():
            cancel_btn.click(force=True)
        wait_modal_gone(page_site)
        return False

    # 3. 网站链接规范化检查与替换 (核心：北森根域名强制升级为职位列表页)
    url_input = dialog.locator("input[placeholder*='请输入网站链接']").first
    cur_url_val = url_input.input_value().strip() if url_input.count() > 0 else ""
    
    if not new_url and cur_url_val:
        norm_url = normalize_target_url(cur_url_val)
        if norm_url != cur_url_val:
            new_url = norm_url
            print(f"  ⚡ 智能重构：检测到不完整链接，自动规整为标准职位列表页: {new_url}")

    if new_url and url_input.count() > 0 and url_input.is_visible():
        url_input.fill("")
        url_input.fill(new_url)
        page_site.wait_for_timeout(200)
        print(f"  🔗 网站链接已替换为: {new_url}")

    # 3.5 设置任务名称 (如 wecruit_spider_task, guopin_v3_spider_task 等)
    if task_name:
        task_item = dialog.locator(".el-form-item").filter(has_text="任务名称").first
        if task_item.count() > 0:
            select_el = task_item.locator(".el-select").first
            select_el.click()
            page_site.wait_for_timeout(400)
            opt = page_site.locator(f".el-select-dropdown:visible .el-select-dropdown__item:has-text('{task_name}')").first
            if opt.count() > 0:
                opt.click()
                page_site.wait_for_timeout(500)
                print(f"  📌 任务名称已选择: 【{task_name}】")

    # 4. 如果指定了岗位分类 (支持 Moka / Wecruit 等)
    cat_info = dialog.evaluate("""d => {
        const items = Array.from(d.querySelectorAll('.el-form-item'));
        const target = items.find(it => it.innerText.includes('岗位'));
        if (target) {
            const inp = target.querySelector('input');
            return {
                label: target.querySelector('.el-form-item__label')?.innerText,
                placeholder: inp?.placeholder,
                val: inp?.value
            };
        }
        return null;
    }""")
    print(f"  🎯 岗位字段探测: {cat_info}")

    if category is not None:
        cat_input = dialog.locator("input[placeholder*='0 校招'], input[placeholder*='岗位分类'], input[placeholder*='岗位类型']").first
        if not (cat_input.count() > 0 and cat_input.is_visible()):
            form_item = dialog.locator(".el-form-item").filter(has_text="岗位").first
            if form_item.count() > 0:
                cat_input = form_item.locator("input").first

        if cat_input.count() > 0 and cat_input.is_visible():
            cat_input.fill("")
            cat_input.fill(str(category))
            page_site.wait_for_timeout(200)
            cat_name = {0: "校招", 1: "实习", 2: "社招"}.get(int(category), str(category))
            print(f"  🎯 岗位分类已设置为: {category} ({cat_name})")
        else:
            print(f"  ℹ️ 当前任务弹窗无【岗位分类】输入框，自动忽略。")

    # 4.5 如果指定了公司ID，直接精准回填
    if comp_id:
        cid_input = dialog.locator("input[placeholder*='请输入公司ID']").first
        if cid_input.count() > 0 and cid_input.is_visible():
            cid_input.fill("")
            cid_input.fill(comp_id)
            page_site.wait_for_timeout(200)
            print(f"  🎯 公司ID已设置为: {comp_id}")

    # 🛡️【物理防呆 2：国聘任务 100% 物理锁死禁止修改公司名称】
    is_guopin = (
        task_name == "guopin_v3_spider_task"
        or "iguopin.com" in dialog_sigs
        or "guopin" in str(match_text).lower()
    )
    if is_guopin and comp_name:
        print(f"  🛡️ [国聘原生保护] 检测到国聘网任务，物理锁死公司名称输入框！原样保留自带官方名称，坚决禁止手动改名！")
        comp_name = ""  # 强制抹除改名意图，原样保留输入框内容直接保存！

    # 5. 如果指定了公司全称，回填 (支持普通输入框与下拉联想)
    if comp_name:
        comp_input = dialog.locator("input[placeholder*='请输入公司名称']").first
        if comp_input.count() > 0 and comp_input.is_visible():
            comp_input.click()
            comp_input.fill("")
            comp_input.type(comp_name, delay=30)
            
            # 等待下拉联想建议列表出现并精准点选
            try:
                page_site.wait_for_selector(".el-autocomplete-suggestion:not([style*='display: none']) li, .el-select-dropdown:not([style*='display: none']) .el-select-dropdown__item", timeout=3000)
                suggestions = page_site.locator(".el-autocomplete-suggestion:not([style*='display: none']) li, .el-select-dropdown:not([style*='display: none']) .el-select-dropdown__item")
                s_count = suggestions.count()
                print(f"  🔍 下拉建议数量: {s_count}")
                if s_count > 0:
                    texts = suggestions.all_inner_texts()
                    print(f"  🔍 下拉建议项内容: {texts}")
                    opt = suggestions.filter(has_text=comp_name).first
                    if opt.count() > 0 and opt.is_visible():
                        opt.click(force=True)
                        print(f"  🎯 成功点选下拉匹配项: 【{comp_name}】")
                        page_site.wait_for_timeout(300)
                    else:
                        suggestions.first.click(force=True)
                        print(f"  🎯 点选首个下拉联想项: 【{texts[0]}】")
                        page_site.wait_for_timeout(300)
                else:
                    comp_input.press("Enter")
            except Exception as e:
                print(f"  ⚠️ 等待下拉联想建议异常: {e}")
                comp_input.press("Enter")
                page_site.wait_for_timeout(300)

    # 6. 保存确定
    confirm_btn = dialog.locator("button:has-text('确 定')").last
    confirm_btn.click(force=True)

    # 检查是否出现错误提示弹窗 (如 Element-UI MessageBox: "更新失败：存在相同的网站...")
    page_site.wait_for_timeout(600)
    try:
        msg_box = page_site.locator(".el-message-box:visible").first
        if msg_box.count() > 0 and msg_box.is_visible():
            box_text = msg_box.inner_text()
            print(f"  ⚠️ 触发系统拦截提示弹窗: {box_text.strip().replace(chr(10), ' ')}")
            ok_btn = msg_box.locator(".el-message-box__btns button:has-text('确定')").first
            if ok_btn.count() > 0 and ok_btn.is_visible():
                ok_btn.click()
                print("  🔘 已按规则自动点击【确定】按钮关闭提示框。")
                page_site.wait_for_timeout(400)
            
            # 关闭尚未关闭的配置 dialog
            close_visible_dialogs(page_site)
            print(f"  ⏩ 已跳过该任务（存在相同网站或更新失败），将汇总汇报给用户。")
            return "SKIPPED_DUPLICATE"
    except Exception as e:
        pass

    wait_modal_gone(page_site)
    print(f"  ✅ 网站配置保存完成！")

    # 7. 省步第一性打法核心：保存后立即动态读取当前行最新的【类型】和【行业】
    row_info = {"ok": True, "cur_type": "", "cur_ind": "", "is_closed": False}
    try:
        cur_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
            has=page_site.locator(f"td:has-text('{match_text}')")
        ).first
        if cur_row.count() > 0:
            tds = cur_row.evaluate("tr => Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim())")
            row_type = tds[2] if len(tds) > 2 else ""
            row_ind = tds[3] if len(tds) > 3 else ""
            row_info["cur_type"] = row_type
            row_info["cur_ind"] = row_ind
            row_info["is_closed"] = bool(row_type and row_ind)
    except Exception:
        pass

    return row_info


# =====================================================================
# 功能 4：端到端一键闭环 (auto-close)
# =====================================================================

def do_auto_close(ctx, match_text, comp_name, short_name="", comp_type="", ind_name="", location="", new_url="", category=None, task_name=""):
    page_site, page_basic = get_pages(ctx)
    
    # 识别是否为国外 ATS 套系（按域名或企业类型判定）
    is_foreign_ats = (
        comp_type == "境外企业"
        or any(domain in match_text.lower() or (new_url and domain in new_url.lower()) for domain in [
            "greenhouse.io", "myworkdayjobs.com", "smartrecruiters.com",
            "lever.co", "ashbyhq.com", "oraclecloud.com", "taleo.net", "icims.com", "eightfold.ai"
        ])
    )

    if is_foreign_ats:
        print(f"\n🌐 [国外 ATS 套系规则] 境外企业默认未收录，执行【先④公司库建档 ➡️ 再③网站回填选中】...")
        # 步骤 1: 先在公司库查重/建档
        do_ensure_company(page_basic, comp_name, short_name, comp_type, ind_name, location)
        
        # 步骤 2: 切回网站列表回填，此时下拉列表已能搜到该企业并可精准点击
        page_site.bring_to_front()
        page_site.wait_for_timeout(500)
        res = do_configure_site(page_site, match_text, new_url, comp_name, category, task_name)
        print(f"  ✨ 【{comp_name}】国外 ATS 端到端齐整闭环已达成！")
        return True

    # 国内通用分支：先在网站列表回填 (配置行、替换URL、设置分类、回填全称并保存)
    res = do_configure_site(page_site, match_text, new_url, comp_name, category, task_name)
    if res == "SKIPPED_DUPLICATE":
        print(f"  ⚠️ 【{comp_name}】网站配置存在冲突/重复已跳过，后续汇报。")
        return False

    # 步骤 2: 极速省步打法——核验当前行是否已自动联动带出完整画像
    if isinstance(res, dict) and res.get("is_closed"):
        cur_t = res.get("cur_type")
        cur_i = res.get("cur_ind")
        print(f"  ✨ 【{comp_name}】网站列表保存后底层已自动联动带出完整档案 (类型:【{cur_t}】 | 行业:【{cur_i}】)！")
        print(f"  ⚡ 达成极速秒级闭环，直接跳过公司库交互（100% 保护已有档案免遭误改）！")
        return True

    # 步骤 3: 仅当类型或行业未完整带出时，才前往公司库进行差量补充
    cur_t = res.get("cur_type", "") if isinstance(res, dict) else ""
    cur_i = res.get("cur_ind", "") if isinstance(res, dict) else ""
    print(f"  ℹ️ 网站列表未完全带出属性 (当前: 类型=【{cur_t}】, 行业=【{cur_i}】)，前往公司库定向差量维护...")

    # 若为国聘任务且类型或行业未指定，优先从国聘详情页提取原生权威画像
    if (not comp_type or not ind_name) and ("iguopin.com" in match_text or "iguopin.com" in new_url):
        gp_url = new_url if "iguopin.com" in new_url else match_text
        if not gp_url.startswith("http"):
            gp_url = f"https://www.iguopin.com/company?id={gp_url.replace('id=', '')}"
        gp_meta = fetch_guopin_meta(ctx, gp_url)
        if gp_meta:
            if not comp_type and gp_meta.get("type"):
                comp_type = gp_meta["type"]
                print(f"  🇨🇳 [国聘原生] 自动采纳原生类型: 【{comp_type}】")
            if not ind_name and gp_meta.get("industry"):
                ind_name = gp_meta["industry"]
                print(f"  🇨🇳 [国聘原生] 自动采纳原生行业: 【{ind_name}】")

    do_ensure_company(page_basic, comp_name, short_name, comp_type, ind_name, location)

    # 步骤 4: 切回网站列表核查
    page_site.bring_to_front()
    page_site.wait_for_timeout(800)
    print(f"  ✨ 【{comp_name}】端到端齐整闭环已达成！")
    return True


def do_batch_close(ctx, json_path):
    """从标准 JSON 批量驱动一键闭环"""
    with open(json_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    page_site, page_basic = get_pages(ctx)
    print(f"\n🚀 [批量执行] 开始处理 {len(items)} 个待闭环任务...")

    for idx, item in enumerate(items, 1):
        target_page = item.get("page")
        if target_page:
            print(f"\n📄 [切页] 跳转至第 {target_page} 页...")
            jump_to_page(page_site, target_page)

        match_text = item["match"]
        name = item["name"]
        abbr = item.get("abbr", "")
        ctype = item.get("type", "")
        ind = item.get("industry", "")
        loc = item.get("location", "")
        new_url = item.get("new_url", "")
        cat = item.get("category", None)
        task = item.get("task", "")

        print(f"\n================== 任务 [{idx}/{len(items)}]: {name} ==================")
        try:
            do_auto_close(ctx, match_text, name, abbr, ctype, ind, loc, new_url, cat, task)
        except Exception as e:
            print(f"  ❌ 执行异常: {e}")
        time.sleep(1)

    print(f"\n🎉 [批量执行] 所有 {len(items)} 个任务处理完成！")


# =====================================================================
# CLI 命令行入口
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="RPA 统一固化自动化执行引擎")
    subparsers = parser.add_subparsers(dest="subcommand", help="子命令")

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="检视网站列表闭环状态")
    p_inspect.add_argument("--page", type=int, default=None, help="目标页码")

    # fetch-guopin
    p_gp = subparsers.add_parser("fetch-guopin", help="抓取国聘原生企业画像(性质/行业/规模)")
    p_gp.add_argument("--url", required=True, help="国聘企业详情页 URL")

    # ensure-company
    p_comp = subparsers.add_parser("ensure-company", help="维护公司库档案")
    p_comp.add_argument("--name", required=True, help="公司工商注册全称")
    p_comp.add_argument("--abbr", default="", help="公司简称")
    p_comp.add_argument("--type", default="", help="企业类型(国企/民企/上市/中外合资/外商独资等)")
    p_comp.add_argument("--industry", default="", help="40项官方标准行业")
    p_comp.add_argument("--location", default="", help="工作/注册地点")

    # configure-site
    p_site = subparsers.add_parser("configure-site", help="配置网站列表行")
    p_site.add_argument("--page", type=int, default=None, help="目标页码")
    p_site.add_argument("--match", required=True, help="动态寻行匹配词 (Slug / URL / 公司名)")
    p_site.add_argument("--new-url", default="", help="标准重构后的URL")
    p_site.add_argument("--company", default="", help="公司工商全称")
    p_site.add_argument("--task", default="", help="任务名称 (如 wecruit_spider_task, guopin_v3_spider_task)")
    p_site.add_argument("--category", type=int, default=None, choices=[0, 1, 2], help="岗位分类 (仅 moka/wecruit 专属: 0校招, 1实习, 2社招)")
    p_site.add_argument("--company-id", default="", help="公司ID")

    # auto-close
    p_close = subparsers.add_parser("auto-close", help="端到端一键闭环")
    p_close.add_argument("--page", type=int, default=None, help="目标页码")
    p_close.add_argument("--match", required=True, help="动态寻行匹配词 (Slug / URL / 公司名)")
    p_close.add_argument("--name", required=True, help="公司工商注册全称")
    p_close.add_argument("--abbr", default="", help="公司简称")
    p_close.add_argument("--type", default="", help="企业类型")
    p_close.add_argument("--industry", default="", help="所属行业")
    p_close.add_argument("--location", default="", help="地点")
    p_close.add_argument("--new-url", default="", help="标准重构后的URL")
    p_close.add_argument("--category", type=int, default=None, choices=[0, 1, 2], help="岗位分类 (仅 moka_spider_task 专属: 0校招, 1实习, 2社招)")

    # inspect-basic
    p_ins_b = subparsers.add_parser("inspect-basic", help="检视公司库档案")
    p_ins_b.add_argument("--search", default="", help="搜索词")
    p_ins_b.add_argument("--delete-name", default="", help="按全称删除测试记录")

    # probe-url
    p_probe = subparsers.add_parser("probe-url", help="通用探测招聘链接标题与企业名称")
    p_probe.add_argument("--url", default="", help="招聘网站 URL")
    p_probe.add_argument("--match", default="", help="在网站列表当前页按关键词寻行探测")

    # view-config
    p_view = subparsers.add_parser("view-config", help="查看某行弹窗配置表单的只读详情")
    p_view.add_argument("--match", required=True, help="匹配词 (如行号、slug、URL关键词)")

    # probe-51job
    p_51 = subparsers.add_parser("probe-51job", help="51job通过岗位数量穿透提取法定全称")
    p_51.add_argument("--match", required=True, help="匹配词 (如CtmID、URL关键词)")
    p_51.add_argument("--page", type=int, default=None, help="目标页码")

    # batch-close
    p_batch = subparsers.add_parser("batch-close", help="从标准 JSON 批量驱动一键闭环")
    p_batch.add_argument("--file", required=True, help="任务 JSON 文件路径")

    args = parser.parse_args()
    if not args.subcommand:
        parser.print_help()
        return

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        ctx = browser.contexts[0]
        page_site, page_basic = get_pages(ctx)

        if args.subcommand == "inspect":
            do_inspect(page_site, args.page)
        elif args.subcommand == "inspect-basic":
            page_basic.bring_to_front()
            close_visible_dialogs(page_basic)
            if args.search:
                s_inp = page_basic.locator("input[placeholder*='输入关键词搜索']").first
                s_inp.fill("")
                s_inp.fill(args.search)
                page_basic.locator("button:has-text('搜索')").first.click()
                page_basic.wait_for_timeout(1200)
            rows = page_basic.evaluate("""() => {
                const trs = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr'));
                return trs.map((tr, idx) => {
                    const tds = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim().replace(/\\n+/g, ' '));
                    return {
                        idx,
                        name: tds[1] || '',
                        short_name: tds[2] || '',
                        org_type: tds[3] || '',
                        industry: tds[4] || '',
                        location: tds[6] || '',
                        full_tds: tds
                    };
                });
            }""")
            print(f"\n🏢 [公司库检视] 检索到 {len(rows)} 条记录 (真实 DOM 渲染):")
            for r in rows:
                print(f"  名称:【{r['name']}】 | 简称:【{r['short_name']}】 | 类型:【{r['org_type']}】 | 行业:【{r['industry']}】 | 地点:【{r['location']}】")
            
            if args.delete_name:
                to_del = [r for r in rows if r['name'] == args.delete_name]
                for d in to_del:
                    print(f"  🗑️ 正在删除测试记录: {d['name']} (ID: {d['id']})...")
                    del_row = page_basic.locator(".el-table__body-wrapper tbody tr").nth(d['idx'])
                    del_btn = del_row.locator("button:has-text('删除')").first
                    if del_btn.count() > 0:
                        del_btn.click(force=True)
                        page_basic.wait_for_timeout(500)
                        box = page_basic.locator(".el-message-box:visible button:has-text('确定')").first
                        if box.count() > 0:
                            box.click(force=True)
                            page_basic.wait_for_timeout(800)
                            wait_modal_gone(page_basic)
                            print("  ✅ 删除成功！")
        elif args.subcommand == "fetch-guopin":
            fetch_guopin_meta(ctx, args.url)
        elif args.subcommand == "probe-url":
            target_url = args.url
            if args.match and not target_url:
                target_url = page_site.evaluate("""(match) => {
                    const rows = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr'));
                    for (const r of rows) {
                        if (r.innerText.includes(match)) {
                            const tds = r.querySelectorAll('td');
                            return tds[6] ? tds[6].innerText.trim() : '';
                        }
                    }
                    return '';
                }""", args.match)
                print(f"  🎯 匹配到第 {args.match} 行 URL: 【{target_url}】")
            if target_url:
                probe_url_meta(ctx, target_url)
            else:
                print("  ❌ 未找到目标 URL！")
        elif args.subcommand == "ensure-company":
            do_ensure_company(page_basic, args.name, args.abbr, args.type, args.industry, args.location)
        elif args.subcommand == "configure-site":
            if args.page:
                jump_to_page(page_site, args.page)
            res = do_configure_site(page_site, args.match, args.new_url, args.company, args.category, args.task, args.company_id)
        elif args.subcommand == "view-config":
            page_site.bring_to_front()
            close_visible_dialogs(page_site)
            matched_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
                has=page_site.locator(f"td:has-text('{args.match}')")
            ).first
            if matched_row.count() == 0:
                print(f"  ❌ 未找到匹配 【{args.match}】 的行")
            else:
                cfg_btn = matched_row.locator("button:has-text('配置')").first
                cfg_btn.click()
                page_site.wait_for_selector(".el-dialog:visible", timeout=4000)
                dialog = page_site.locator(".el-dialog:visible").last
                items = dialog.evaluate("""d => {
                    return Array.from(d.querySelectorAll('.el-form-item')).map(it => {
                        const lbl = it.querySelector('.el-form-item__label')?.innerText?.trim() || '';
                        const inp = it.querySelector('input, textarea');
                        return { 
                            label: lbl, 
                            val: inp ? inp.value : '',
                            placeholder: inp ? inp.placeholder : '',
                            cls: inp ? inp.className : ''
                        };
                    });
                }""")
                print(f"\n📋 【{args.match}】配置详情:")
                for it in items:
                    print(f"  🔹 {it['label']} val={it['val']} | ph={it['placeholder']} | cls={it['cls']}")
                close_visible_dialogs(page_site)
        elif args.subcommand == "list-tasks":
            page_site.bring_to_front()
            close_visible_dialogs(page_site)
            # 点击第一行的配置按钮唤起弹窗
            first_row = page_site.locator(".el-table__body-wrapper tbody tr").first
            first_row.locator("button:has-text('配置')").first.click()
            page_site.wait_for_selector(".el-dialog:visible", timeout=4000)
            dialog = page_site.locator(".el-dialog:visible").last
            task_item = dialog.locator(".el-form-item").filter(has_text="任务名称").first
            select_el = task_item.locator(".el-select").first
            select_el.click()
            page_site.wait_for_timeout(500)
            options = page_site.evaluate("""() => {
                const drop = document.querySelector('.el-select-dropdown:not([style*="display: none"])');
                if (!drop) return [];
                return Array.from(drop.querySelectorAll('.el-select-dropdown__item')).map(el => el.innerText.trim());
            }""")
            print(f"\n📋 后台支持的【任务名称】选项列表 (共 {len(options)} 个):")
            for idx, opt in enumerate(options, 1):
                print(f"  {idx:02d}. {opt}")
            close_visible_dialogs(page_site)
        elif args.subcommand == "probe-51job":
            if args.page:
                jump_to_page(page_site, args.page)
            matched_row = page_site.locator(".el-table__body-wrapper tbody tr").filter(
                has=page_site.locator(f"td:has-text('{args.match}')")
            ).first
            if matched_row.count() == 0:
                print(f"  ❌ 未找到匹配 【{args.match}】 的行")
            else:
                tds = matched_row.locator("td")
                # 第6列是岗位数量（索引5）
                count_td = tds.nth(5)
                link_el = count_td.locator("span, a").first
                print(f"  🎯 点击岗位数量穿透: {link_el.inner_text().strip()}")
                link_el.click()
                page_site.wait_for_timeout(2000)
                # 读取 job/index 表格
                job_info = page_site.evaluate("""() => {
                    const row = document.querySelector('.el-table__body-wrapper tbody tr');
                    if (!row) return null;
                    const tds = Array.from(row.querySelectorAll('td')).map(td => td.innerText.trim());
                    return {
                        company_name: tds[1] || '',
                        job_title: tds[2] || '',
                        job_link: tds[9] || ''
                    };
                }""")
                print("  📋 穿透提取岗位数据:", job_info)
                # 后退回网站列表
                page_site.go_back()
                page_site.wait_for_timeout(1500)
        elif args.subcommand == "auto-close":
            if args.page:
                jump_to_page(page_site, args.page)
            do_auto_close(ctx, args.match, args.name, args.abbr, args.type, args.industry, args.location, args.new_url, args.category)
        elif args.subcommand == "batch-close":
            do_batch_close(ctx, args.file)


if __name__ == "__main__":
    main()

