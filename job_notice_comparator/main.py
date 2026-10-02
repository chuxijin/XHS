"""
校园招聘公告自动化核对脚本 (Job Notice Comparator)

功能：
1. 从 Chrome 调试端口 (9222) 中读取飞书《27届校招 Pro 版》指定日期的招聘记录；
2. 在 JobLeap 后台《公司列表》中检索对应公司，遍历所有候选结果行；
3. 智能比对公告链接一致性（支持微信推文参数清洗、多候选行精准命中）；
4. 自动生成并输出 Markdown 格式的核对报告。
"""

import os
import sys
import re
import argparse
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from playwright.sync_api import sync_playwright

# ==========================================
# 1. 配置参数
# ==========================================
CDP_URL = "http://localhost:9222"
FEISHU_TITLE_KEYWORD = "27届校招"
FEISHU_URL_KEYWORD = "feishu.cn/sheets"
JOBLEAP_COMPANY_TITLE_KEYWORD = "公司列表"
JOBLEAP_COMPANY_URL = "http://admin.jobleap.betaquantity.com/#/company-basic/index"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
os.makedirs(REPORTS_DIR, exist_ok=True)


# ==========================================
# 2. URL 规范化与比对引擎
# ==========================================
def normalize_url(url: str) -> str:
    """清洗 URL 参数，去除跟踪标识与协议差异"""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    if not url:
        return ""

    parsed = urlparse(url)
    scheme = "https"
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    if not path:
        path = ""

    tracking_params = {
        "scene", "click_id", "clicktime", "enterid", "from", "isappinstalled",
        "subscene", "sessionid", "ascene", "devicetype", "version", "nettype",
        "abtest_cookie", "lang", "exportkey", "pass_ticket", "wx_header"
    }

    query_dict = parse_qs(parsed.query)
    cleaned_query = {k: v for k, v in query_dict.items() if k.lower() not in tracking_params}
    sorted_query = urlencode(cleaned_query, doseq=True)
    return urlunparse((scheme, netloc, path, "", sorted_query, ""))


def compare_notice(feishu_url: str, jobleap_url: str) -> tuple[str, str]:
    """比对飞书公告链接与 JobLeap 系统公告链接"""
    norm_feishu = normalize_url(feishu_url)
    norm_jobleap = normalize_url(jobleap_url)

    if not norm_feishu:
        return "FEISHU_EMPTY", "飞书表格中未填写公告链接"
    if not norm_jobleap:
        return "JOBLEAP_EMPTY", "JobLeap 系统中公告链接为空"
    if norm_feishu == norm_jobleap:
        return "MATCH", "公告链接完全一致"

    # 微信推文专项对比 (兼容 /s/xxx 与 /s?__biz=xxx)
    if "mp.weixin.qq.com" in norm_feishu and "mp.weixin.qq.com" in norm_jobleap:
        s_match_f = re.search(r'/s/([a-zA-Z0-9_\-]+)', norm_feishu)
        s_match_j = re.search(r'/s/([a-zA-Z0-9_\-]+)', norm_jobleap)
        if s_match_f and s_match_j and s_match_f.group(1) == s_match_j.group(1):
            return "MATCH", "微信推文短链一致"
        return "MISMATCH", f"微信公告链接不一致 (飞书: {feishu_url} vs 系统: {jobleap_url})"

    return "MISMATCH", f"公告链接不一致 (飞书: {feishu_url} vs 系统: {jobleap_url})"


# ==========================================
# 3. 飞书 SpreadJS 数据模型提取器
# ==========================================
def parse_feishu_date(val) -> str | None:
    """将飞书/Excel 日期转换为 YYYY-MM-DD"""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        base_date = datetime(1899, 12, 30)
        target_date = base_date + timedelta(days=float(val))
        return target_date.strftime("%Y-%m-%d")
    
    val_str = str(val).strip()
    match = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', val_str)
    if match:
        return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    
    match2 = re.search(r'(\d{1,2})[-/.](\d{1,2})', val_str)
    if match2:
        year = datetime.now().year
        return f"{year:04d}-{int(match2.group(1)):02d}-{int(match2.group(2)):02d}"
    return None


def clean_company_name(raw_name: str) -> str:
    """清洗公司名称中的标签和无用字符"""
    if not raw_name:
        return ""
    name = re.sub(r'[\r\n\t]+', ' ', raw_name).strip()
    name = re.sub(r'^(【[^】]*】|\[[^\]]*\])', '', name).strip()
    name = re.sub(r'\(.*?\)|（.*?）', '', name).strip()
    return name


def extract_feishu_records(feishu_page, target_date_str: str) -> list[dict]:
    """从飞书 SpreadJS 数据模型中提取指定日期的记录"""
    print(f"[飞书提取器] 正在读取 SpreadJS 底层数据模型...")
    raw_data = feishu_page.evaluate("""
    () => {
        try {
            let spread = window.spreadApp.collaborativeSpread._spread;
            let sheet = spread.getActiveSheet();
            let model = sheet._dataModel;
            let rowCount = model.getRowCount();
            let colCount = model.getColumnCount();
            
            let records = [];
            for (let r = 0; r < rowCount; r++) {
                let rowValues = [];
                let rowHyperlinks = {};
                for (let c = 0; c < Math.min(colCount, 15); c++) {
                    let v = model.getValue(r, c);
                    rowValues.push(v);
                    let segs = model.getSegmentArray(r, c);
                    if (segs && Array.isArray(segs)) {
                        for (let s of segs) {
                            if (s) {
                                let hl = s.link || s.hyperlink || s.url || "";
                                if (hl) {
                                    rowHyperlinks[c] = hl;
                                    break;
                                }
                            }
                        }
                    }
                }
                records.push({ row: r, values: rowValues, links: rowHyperlinks });
            }
            return { success: true, records: records };
        } catch (e) {
            return { success: false, error: e.toString() };
        }
    }
    """)

    if not raw_data.get("success"):
        raise RuntimeError(f"飞书数据模型提取失败: {raw_data.get('error')}")

    records = raw_data["records"]
    header_row = None
    date_col = 0
    company_col = 1
    notice_col = 2
    apply_col = 3
    loc_col = 4
    nature_col = 5
    ind_col = 6
    memo_col = None

    for r_idx, item in enumerate(records[:15]):
        vals = [str(v).strip() if v is not None else "" for v in item["values"]]
        for c_idx, val in enumerate(vals):
            if "更新时间" in val or "更新日期" in val or "日期" in val:
                date_col = c_idx
                header_row = r_idx
            elif "公司名称" in val or "企业名称" in val:
                company_col = c_idx
            elif "招聘公告" in val or "公告" in val:
                notice_col = c_idx
            elif "投递链接" in val or "网申链接" in val or "投递" in val:
                apply_col = c_idx
            elif "地点" in val or "工作地点" in val:
                loc_col = c_idx
            elif "性质" in val or "企业性质" in val:
                nature_col = c_idx
            elif "行业" in val:
                ind_col = c_idx
            elif "备注" in val or "说明" in val:
                memo_col = c_idx
        if header_row is not None:
            break

    start_row = (header_row + 1) if header_row is not None else 1
    extracted_records = []

    for item in records[start_row:]:
        r_idx = item["row"]
        vals = item["values"]
        links = item["links"]

        raw_date = vals[date_col] if len(vals) > date_col else None
        parsed_d = parse_feishu_date(raw_date)
        if not parsed_d or parsed_d != target_date_str:
            continue

        raw_company = vals[company_col] if len(vals) > company_col else ""
        if not raw_company:
            continue
        clean_company = clean_company_name(str(raw_company))

        raw_notice = vals[notice_col] if len(vals) > notice_col else ""
        notice_url = links.get(str(notice_col)) or links.get(notice_col) or ""
        if not notice_url and str(raw_notice).startswith("http"):
            notice_url = str(raw_notice).strip()

        raw_apply = vals[apply_col] if len(vals) > apply_col else ""
        apply_url = links.get(str(apply_col)) or links.get(apply_col) or ""
        if not apply_url and str(raw_apply).startswith("http"):
            apply_url = str(raw_apply).strip()

        location = str(vals[loc_col]).strip() if len(vals) > loc_col and vals[loc_col] is not None else ""
        nature = str(vals[nature_col]).strip() if len(vals) > nature_col and vals[nature_col] is not None else ""
        industry = str(vals[ind_col]).strip() if len(vals) > ind_col and vals[ind_col] is not None else ""
        feishu_memo = str(vals[memo_col]).strip() if memo_col is not None and len(vals) > memo_col and vals[memo_col] is not None else ""

        extracted_records.append({
            "row_index": r_idx + 1,
            "date": parsed_d,
            "company_name": clean_company,
            "raw_company": str(raw_company).strip(),
            "notice_title": str(raw_notice).strip(),
            "notice_url": notice_url,
            "apply_url": apply_url,
            "location": location,
            "nature": nature,
            "industry": industry,
            "feishu_memo": feishu_memo
        })

    print(f"[飞书提取器] 筛选完成！日期 {target_date_str} 共有 {len(extracted_records)} 条招聘记录。")
    return extracted_records


# ==========================================
# 4. JobLeap 检索与全候选行比对
# ==========================================
def search_jobleap_companies(jobleap_page, company_name: str) -> list[dict]:
    """在 JobLeap 中搜索公司并返回所有匹配结果行"""
    clean_name = company_name.strip()
    
    inp = jobleap_page.locator("input[placeholder*='关键词']").first
    inp.click()
    inp.fill("")
    jobleap_page.wait_for_timeout(150)
    inp.fill(clean_name)
    jobleap_page.wait_for_timeout(250)

    s_btn = jobleap_page.locator("button:has-text('搜索'), button:has-text('查询')").first
    s_btn.click()
    # 增加等待时间，确保后端查询和表格渲染彻底完成
    jobleap_page.wait_for_timeout(2200)

    results = jobleap_page.evaluate("""
    () => {
        let rows = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr'));
        let data = [];
        for (let r of rows) {
            let cells = Array.from(r.querySelectorAll('td')).map(c => c.innerText.trim());
            if (cells.length >= 11 && /^\\d+$/.test(cells[0])) {
                data.push({
                    id: cells[0] || '',
                    name: cells[1] || '',
                    short_name: cells[2] || '',
                    latest_job: cells[8] || '',
                    apply_time: cells[9] || '',
                    notice: cells[10] || '',
                    memo: cells[11] || '',
                    op_log: cells[12] || ''
                });
            }
        }
        return data;
    }
    """)
    # 每次搜索完成后预留间隔时间
    jobleap_page.wait_for_timeout(600)
    return results


def sanitize_cell(text: str) -> str:
    """清洗表格单元格文本，避免换行和管道符破坏 Markdown 表格"""
    if not text:
        return "-"
    # 将换行符转为 <br> 或空格
    s = str(text).replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>").replace("|", "｜").strip()
    return s if s else "-"

# ==========================================
# 5. Markdown 报告生成器
# ==========================================
def generate_markdown_report(target_date_str: str, results: list[dict], output_path: str):
    """根据比对结果生成 Markdown 报告"""
    total = len(results)
    matches = [r for r in results if r["status"] == "MATCH"]
    mismatches = [r for r in results if r["status"] == "MISMATCH"]
    jobleap_empty = [r for r in results if r["status"] == "JOBLEAP_EMPTY"]
    not_found = [r for r in results if r["status"] == "NOT_FOUND"]
    feishu_empty = [r for r in results if r["status"] == "FEISHU_EMPTY"]

    dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    date_display = f"{dt.month}.{dt.day}"

    lines = []
    lines.append(f"# {date_display} 校园招聘公告核对与比对报告\n")
    lines.append(f"> 生成时间：`{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  ")
    lines.append(f"> 数据来源：飞书《27届校招 Pro 版》 ↔ JobLeap《公司列表》\n")

    lines.append("## 一、 全局核查统计数据\n")
    lines.append(f"- **今日更新公司总数**：`{total}` 家")
    lines.append(f"- **公告完全一致公司数**：`{len(matches)}` 家 (`{len(matches)/total*100:.1f}%`)" if total > 0 else "- **公告完全一致**：0 家")
    lines.append(f"- **公告存在差异公司数**：`{len(mismatches)}` 家")
    lines.append(f"- **系统未录入公告公司数**：`{len(jobleap_empty)}` 家")
    lines.append(f"- **系统未收录公司数**：`{len(not_found)}` 家\n")
    lines.append("---\n")

    if mismatches:
        lines.append("## 二、 ⚠️ 公告存在差异清单 (需重点核对)\n")
        lines.append("| 序号 | 公司名称 | 飞书公告链接 | 系统中维护的公告 | 投递链接 | 备注 | 后台最新操作 | 详情说明 |")
        lines.append("| :---: | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for idx, r in enumerate(mismatches, 1):
            f_link = f"[{r['notice_title'] or '飞书公告'}]({r['feishu_notice_url']})" if r['feishu_notice_url'] else "无"
            j_link = f"[系统公告]({r['jobleap_notice_url']})" if r['jobleap_notice_url'] else "无"
            a_link = f"[投递入口]({r['apply_url']})" if r['apply_url'] else "无"
            memo_raw = r.get("jobleap_memo") or r.get("feishu_memo") or "-"
            memo_sanitized = sanitize_cell(memo_raw)
            op_raw = r.get("jobleap_op_log") or "-"
            op_sanitized = sanitize_cell(op_raw)
            detail_sanitized = sanitize_cell(r['detail'])
            lines.append(f"| {idx} | **{sanitize_cell(r['company_name'])}** | {f_link} | {j_link} | {a_link} | {memo_sanitized} | {op_sanitized} | {detail_sanitized} |")
        lines.append("\n---\n")

    if jobleap_empty:
        lines.append("## 三、 📝 系统未录入公告清单 (需补充公告链接)\n")
        lines.append("| 序号 | 公司名称 | 飞书公告链接 (明文) | 官网投递链接 (明文) | 备注 | 后台最新操作 |")
        lines.append("| :---: | :--- | :--- | :--- | :--- | :--- |")
        for idx, r in enumerate(jobleap_empty, 1):
            f_url = r['feishu_notice_url'].strip() if r.get('feishu_notice_url') else "无"
            a_url = r['apply_url'].strip() if r.get('apply_url') else "无"
            memo_raw = r.get("jobleap_memo") or r.get("feishu_memo") or "-"
            memo_sanitized = sanitize_cell(memo_raw)
            op_raw = r.get("jobleap_op_log") or "-"
            op_sanitized = sanitize_cell(op_raw)
            lines.append(f"| {idx} | **{sanitize_cell(r['company_name'])}** | {f_url} | {a_url} | {memo_sanitized} | {op_sanitized} |")
        lines.append("\n---\n")

    if not_found:
        lines.append("## 四、 🔍 系统未收录公司清单 (需在后台新建)\n")
        lines.append("| 序号 | 公司名称 | 地点 | 性质 | 行业 | 备注 | 公告链接 | 投递链接 | 后台最新操作 |")
        lines.append("| :---: | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for idx, r in enumerate(not_found, 1):
            f_link = f"[{r['notice_title'] or '公告详情'}]({r['feishu_notice_url']})" if r['feishu_notice_url'] else "无"
            a_link = f"[投递入口]({r['apply_url']})" if r['apply_url'] else "无"
            memo_raw = r.get("feishu_memo") or "-"
            memo_sanitized = sanitize_cell(memo_raw)
            lines.append(f"| {idx} | **{sanitize_cell(r['company_name'])}** | {sanitize_cell(r['location'])} | {sanitize_cell(r['nature'])} | {sanitize_cell(r['industry'])} | {memo_sanitized} | {f_link} | {a_link} | 未收录 |")
        lines.append("\n---\n")

    if matches:
        lines.append("## 五、 ✅ 公告完全一致清单\n")
        lines.append("| 序号 | 公司名称 | 公告链接 | 投递链接 | 备注 | 后台最新操作 | 判定结论 |")
        lines.append("| :---: | :--- | :--- | :--- | :--- | :--- | :--- |")
        for idx, r in enumerate(matches, 1):
            f_link = f"[{r['notice_title'] or '公告详情'}]({r['feishu_notice_url']})" if r['feishu_notice_url'] else "一致"
            a_link = f"[投递入口]({r['apply_url']})" if r['apply_url'] else "无"
            memo_raw = r.get("jobleap_memo") or r.get("feishu_memo") or "-"
            memo_sanitized = sanitize_cell(memo_raw)
            op_raw = r.get("jobleap_op_log") or "-"
            op_sanitized = sanitize_cell(op_raw)
            lines.append(f"| {idx} | {sanitize_cell(r['company_name'])} | {f_link} | {a_link} | {memo_sanitized} | {op_sanitized} | 完全一致 |")
        lines.append("\n")

    content = "\n".join(lines)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"[报告生成器] 报告已成功生成并保存至：{output_path}")


# ==========================================
# 6. 主执行流水线
# ==========================================
def run_pipeline(target_date_str: str = None, output_file: str = None):
    if not target_date_str:
        target_date_str = datetime.now().strftime("%Y-%m-%d")

    dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    date_display = f"{dt.month}.{dt.day}"

    if not output_file:
        output_file = os.path.join(REPORTS_DIR, f"{date_display}.md")

    print("=" * 50)
    print(f"🚀 开始执行校园招聘公告核对流水线")
    print(f"📅 目标核查日期: {target_date_str} (显示: {date_display})")
    print(f"📄 输出报告路径: {output_file}")
    print("=" * 50)

    with sync_playwright() as p:
        print(f"[1/4] 正在连接 Chrome 调试端口 ({CDP_URL})...")
        browser = p.chromium.connect_over_cdp(CDP_URL)
        context = browser.contexts[0]

        feishu_page = None
        jobleap_page = None
        any_jobleap_page = None

        for pg in context.pages:
            try:
                url = pg.url or ""
            except Exception:
                url = ""
            
            if "feishu.cn/sheets" in url or "Q8u4sOqwLhkNWpt86khcVFTSnoC" in url:
                feishu_page = pg
            elif "admin.jobleap.betaquantity.com" in url:
                any_jobleap_page = pg
                if "company-basic/index" in url:
                    jobleap_page = pg

        if not feishu_page:
            for pg in context.pages:
                try:
                    title = pg.title()
                    if FEISHU_TITLE_KEYWORD in title:
                        feishu_page = pg
                        break
                except Exception:
                    pass

        if not feishu_page:
            print("[错误] 未找到飞书《27届校招 Pro 版》页面，请确保在 Chrome 中已打开！")
            return

        if not jobleap_page:
            if any_jobleap_page:
                jobleap_page = any_jobleap_page
            else:
                jobleap_page = context.new_page()
                jobleap_page.goto(JOBLEAP_COMPANY_URL)

        # 确保当前页面真正处于【公司列表】
        if "company-basic" not in jobleap_page.url:
            print("[提示] 定位到 JobLeap 页面，正在切换至【公司列表】...")
            try:
                menu_item = jobleap_page.locator(".el-menu-item:has-text('公司列表'), a:has-text('公司列表')").first
                if menu_item.is_visible():
                    menu_item.click()
                    jobleap_page.wait_for_timeout(1000)
            except Exception:
                pass
            if "company-basic" not in jobleap_page.url:
                jobleap_page.goto(JOBLEAP_COMPANY_URL)

        jobleap_page.wait_for_selector("input[placeholder*='关键词']", timeout=10000)

        print("[2/4] 已定位浏览器标签页：")
        print(f"  - 飞书页面: {feishu_page.title()[:25]}...")
        print(f"  - 公司列表: {jobleap_page.title()[:25]}...")

        records = extract_feishu_records(feishu_page, target_date_str)
        if not records:
            print(f"[提示] 未提取到 {target_date_str} 的招聘记录，流程结束。")
            return

        print(f"[3/4] 开始在 JobLeap 中逐一检索公司并核对公告 (共 {len(records)} 家)...")
        results = []

        for idx, rec in enumerate(records, 1):
            comp_name = rec["company_name"]
            feishu_notice = rec["notice_url"]
            print(f"  [{idx}/{len(records)}] 正在检索: {comp_name} ...", end="", flush=True)

            candidates = search_jobleap_companies(jobleap_page, comp_name)

            if not candidates:
                status = "NOT_FOUND"
                detail = "系统中未收录"
                jobleap_notice = ""
                jobleap_memo = ""
                jobleap_op = ""
                matched_company_name = "-"
                print(f" -> ❌ 未收录")
            else:
                matched_cand = None
                for cand in candidates:
                    st, _ = compare_notice(feishu_notice, cand.get("notice", ""))
                    if st == "MATCH":
                        matched_cand = cand
                        status = "MATCH"
                        detail = "在搜索候选记录中找到一致公告"
                        break

                if matched_cand:
                    target_row = matched_cand
                    jobleap_notice = target_row.get("notice", "")
                    jobleap_memo = target_row.get("memo", "")
                    jobleap_op = target_row.get("op_log", "")
                    matched_company_name = target_row.get("name", comp_name)
                    print(f" -> ✅ 一致 (命中: {matched_company_name})")
                else:
                    target_row = candidates[0]
                    jobleap_notice = target_row.get("notice", "")
                    jobleap_memo = target_row.get("memo", "")
                    jobleap_op = target_row.get("op_log", "")
                    matched_company_name = target_row.get("name", comp_name)

                    status, detail = compare_notice(feishu_notice, jobleap_notice)
                    if status == "JOBLEAP_EMPTY":
                        print(f" -> ⚠️ 系统无公告")
                    elif status == "MISMATCH":
                        if len(candidates) > 1:
                            detail = f"共返回 {len(candidates)} 条记录，所有公告均不一致"
                        print(f" -> ❗ 不一致 (共 {len(candidates)} 条候选均不符)")
                    else:
                        print(f" -> ℹ️ {status}")

            results.append({
                "row_index": rec["row_index"],
                "company_name": comp_name,
                "matched_name": matched_company_name,
                "notice_title": rec["notice_title"],
                "feishu_notice_url": feishu_notice,
                "jobleap_notice_url": jobleap_notice,
                "apply_url": rec["apply_url"],
                "location": rec.get("location", ""),
                "nature": rec.get("nature", ""),
                "industry": rec.get("industry", ""),
                "feishu_memo": rec.get("feishu_memo", ""),
                "status": status,
                "detail": detail,
                "jobleap_memo": jobleap_memo,
                "jobleap_op_log": jobleap_op
            })

        print("[4/4] 正在生成核对报告...")
        generate_markdown_report(target_date_str, results, output_file)
        print(f"🎉 全部比对完成！已输出报告: {output_file}\n")


# ==========================================
# 7. 命令行入口
# ==========================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="飞书校招公告与 JobLeap 系统一致性核对工具")
    parser.add_argument("--date", "-d", type=str, default=None, help="目标核查日期，格式如 2026-08-25")
    parser.add_argument("--output", "-o", type=str, default=None, help="输出 Markdown 报告路径")
    args = parser.parse_args()

    run_pipeline(target_date_str=args.date, output_file=args.output)
