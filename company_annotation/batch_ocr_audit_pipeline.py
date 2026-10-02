import sys
import os
import json
import re
import time
import html
import base64
import urllib.request
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from PIL import Image

API_KEY = "76PS7evGoZgw2oEHimGwQqC1"
SECRET_KEY = "4FG8XGtlmQeUZgEZ8AEAO5EzX3WMwG07"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Referer': 'https://mp.weixin.qq.com/'
}

POSTER_DIR = r"D:\100_Work\101_Program\Proj\XHS\company_annotation\posters"
os.makedirs(POSTER_DIR, exist_ok=True)

def get_baidu_token():
    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {
        "grant_type": "client_credentials",
        "client_id": API_KEY,
        "client_secret": SECRET_KEY
    }
    resp = requests.post(url, params=params, timeout=10)
    return resp.json().get("access_token")

def ocr_single_image(token, img_bytes):
    try:
        img = Image.open(BytesIO(img_bytes))
        # 限制最大尺寸
        if max(img.size) > 2000:
            ratio = 2000 / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        buf = BytesIO()
        img.save(buf, format='JPEG', quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        url = f"https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic?access_token={token}"
        resp = requests.post(url, data={'image': b64}, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=30)
        res = resp.json()
        lines = [w['words'] for w in res.get('words_result', [])]
        return '\n'.join(lines)
    except Exception as e:
        return f"[OCR Error: {str(e)}]"

def process_record_ocr(token, record):
    cname = record["name"]
    url = record["posting_url"]
    page = record["page"]
    info = record.get("parsed_info", {})
    
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', cname)
    cache_file = os.path.join(POSTER_DIR, f"P{page}_{safe_name}.json")
    
    # 如果已有有效缓存且字数>50，直接读取
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                cached = json.load(f)
                if len(cached.get("ocr_text", "")) > 50:
                    return cached
        except Exception:
            pass

    result = {
        "name": cname,
        "page": page,
        "url": url,
        "img_count": 0,
        "ocr_text": "",
        "ocr_grades": [],
        "ocr_deadlines": [],
        "ocr_positions": [],
        "ocr_benefits": []
    }

    if not url:
        return result

    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw_html = resp.read().decode('utf-8', 'ignore')
        
        # 提取所有正文/展示图片
        raw_img_urls = re.findall(r'<img[^>]+data-src=["\']([^"\']+)["\']', raw_html)
        # 兜底：如果是新版图集
        if not raw_img_urls:
            raw_img_urls = re.findall(r'https?://(?:mmbiz|mmecoa)\.qpic\.cn/[^\s"\'<>]+', raw_html)
        
        valid_img_urls = []
        for raw_u in raw_img_urls:
            u = html.unescape(raw_u)
            if 'qpic.cn' in u and u not in valid_img_urls:
                valid_img_urls.append(u)
        
        result["img_count"] = len(valid_img_urls)

        # 下载并按大小排序，优先识别长图海报
        downloaded = []
        for u in valid_img_urls[:5]: # 最多检查前 5 张
            try:
                i_req = urllib.request.Request(u, headers=HEADERS)
                with urllib.request.urlopen(i_req, timeout=10) as i_resp:
                    b = i_resp.read()
                # 过滤太小的纯装饰图（小于 15KB）
                if len(b) > 15360:
                    downloaded.append((len(b), b))
            except Exception:
                pass
        
        # 优先识别文件体积最大的前 2 张长图海报
        downloaded.sort(key=lambda x: x[0], reverse=True)
        
        ocr_lines_all = []
        for sz, b in downloaded[:2]:
            t = ocr_single_image(token, b)
            if t and not t.startswith("[OCR Error"):
                ocr_lines_all.append(t)
        
        full_ocr = '\n'.join(ocr_lines_all)
        result["ocr_text"] = full_ocr

        # 从 OCR 文本中提取届数
        grades = set()
        for gm in re.finditer(r'(?:20)?(2[5-9])\s*届', full_ocr):
            grades.add(f"{gm.group(1)}届")
        if "提前批" in full_ocr:
            grades.add("提前批")
        # 毕业范围
        grad_range = re.findall(r'202[5-7]年\d{1,2}月[至\-~到]202[6-8]年\d{1,2}月', full_ocr)
        if grad_range:
            grades.add(f"毕业时间:{grad_range[0]}")
        result["ocr_grades"] = sorted(list(grades))

        # 从 OCR 文本中提取截止时间
        dls = []
        if "招满即止" in full_ocr or "招满即停" in full_ocr:
            dls.append("招满即止")
        dl_matches = re.findall(r'(?:截止|网申截止|投递截止|简历投递截止)(?:时间|日期)?(?:\s*[:：到至]?\s*)((?:202[4-7]年)?\d{1,2}月\d{1,2}日?)', full_ocr)
        if dl_matches:
            dls.extend(dl_matches)
        result["ocr_deadlines"] = list(dict.fromkeys(dls))

        # 提取关键福利
        benefits = []
        if any(k in full_ocr for k in ["北京户口", "落户指标", "落户北京", "协助落户", "落户"]):
            benefits.append("户口/落户指标")
        if "六险二金" in full_ocr or "八险三金" in full_ocr:
            benefits.append("六险二金/八险三金")
        elif "五险一金" in full_ocr:
            benefits.append("五险一金")
        if any(k in full_ocr for k in ["包吃住", "包吃包住", "提供吃住", "员工宿舍", "免费食堂", "公寓"]):
            benefits.append("包吃住/宿舍")
        if "年终奖" in full_ocr:
            benefits.append("年终奖")
        result["ocr_benefits"] = benefits

    except Exception as e:
        result["ocr_text"] = f"[Pipeline Error: {str(e)}]"

    # 写入单个缓存
    with open(cache_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result

def main():
    with open(r'D:\100_Work\101_Program\Proj\XHS\company_annotation\raw_wechat_cache.json', 'r', encoding='utf-8') as f:
        records = json.load(f)

    token = get_baidu_token()
    if not token:
        print("错误：无法获取百度 OCR Token")
        return

    print(f"Token 有效，启动多线程海报深度视觉识别流水线，共 {len(records)} 家企业...")
    all_results = []
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(process_record_ocr, token, r): r for r in records}
        done = 0
        for f in as_completed(futures):
            done += 1
            res = f.result()
            all_results.append(res)
            if done % 20 == 0 or done == len(records):
                elapsed = time.time() - start_time
                print(f"视觉识别进度: {done}/{len(records)} (耗时: {elapsed:.1f}s)")

    # 保持原有排序
    target_name_map = {r["name"]: i for i, r in enumerate(records)}
    all_results.sort(key=lambda x: target_name_map.get(x["name"], 999))

    with open(r'D:\100_Work\101_Program\Proj\XHS\company_annotation\all_poster_ocr_results.json', 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)

    print("海报全量深度视觉识别已完成，结果已保存至 all_poster_ocr_results.json")

if __name__ == "__main__":
    main()
