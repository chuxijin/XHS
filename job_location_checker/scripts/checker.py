import json
import re
import os
import sys
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH_DIR = r"C:\Users\19396\.gemini\antigravity\brain\dedcedd1-e295-47db-8425-0ea9a3700830\scratch"
sys.path.append(SCRATCH_DIR)

import upgrade_semantic_checker

def is_location_matched_bilingual(t_loc, a_loc):
    return upgrade_semantic_checker.is_semantic_location_matched(t_loc, a_loc)

def run_analysis(cache_path, output_md_path):
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data:
        t_loc = item['table_loc']
        a_loc = item['actual_loc']
        matched, status = is_location_matched_bilingual(t_loc, a_loc)
        item['is_match_status'] = status

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    company_stats = {}
    for item in data:
        comp = item['company']
        if comp not in company_stats:
            company_stats[comp] = {'total': 0, 'consistent': 0, 'inconsistent': 0}
        
        company_stats[comp]['total'] += 1
        if item['is_match_status'] == "是":
            company_stats[comp]['consistent'] += 1
        else:
            company_stats[comp]['inconsistent'] += 1

    total_jobs = len(data)
    total_companies = len(company_stats)
    total_consistent = sum(s['consistent'] for s in company_stats.values())
    total_inconsistent = sum(s['inconsistent'] for s in company_stats.values())

    print("="*80)
    print(f"Total Companies: {total_companies}")
    print(f"Total Jobs: {total_jobs}")
    print(f"Total Consistent: {total_consistent}")
    print(f"Total Inconsistent: {total_inconsistent}")
    print("="*80)

    lines = []
    lines.append("# 境外企业国内地点测试与核查对比报告\n")
    lines.append("## 一、 全局核查统计数据\n")
    lines.append(f"- **涵盖公司总数**：`{total_companies}` 家")
    lines.append(f"- **总测试岗位数**：`{total_jobs}` 个")
    lines.append(f"- **地点完全一致岗位数**：`{total_consistent}` 个")
    lines.append(f"- **存在差异/无法比对岗位数**：`{total_inconsistent}` 个\n")

    lines.append("## 二、 58 家公司核查一致性汇总表\n")
    lines.append("| 序号 | 公司名称 | 岗位总数 | 一致岗位数 | 存在差异岗位数 | 一致率 |")
    lines.append("| :---: | :--- | :---: | :---: | :---: | :---: |")

    sorted_companies = sorted(company_stats.items(), key=lambda x: x[1]['total'], reverse=True)
    for idx, (comp, s) in enumerate(sorted_companies, 1):
        rate = (s['consistent'] / s['total']) * 100
        lines.append(f"| {idx} | {comp} | {s['total']} | {s['consistent']} | {s['inconsistent']} | {rate:.1f}% |")

    lines.append("\n## 三、 2000 个岗位详细对比数据\n")
    lines.append("| 表格行号 | 公司名称 | 岗位名称 | 地点 | 链接地点 | 是否一致 | 投递链接 |")
    lines.append("| :---: | :--- | :--- | :--- | :--- | :--- | :--- |")

    for item in data:
        r_num = item['row_num']
        comp = item['company']
        j_name = item['job_name']
        t_loc = item['table_loc']
        a_loc = item['actual_loc']
        status = item['is_match_status']
        link = item['link']
        lines.append(f"| {r_num} | {comp} | {j_name} | {t_loc} | {a_loc} | {status} | {link} |")

    content = "\n".join(lines)

    # Multi-path write to guarantee user UI sync
    sync_paths = [
        output_md_path,
        r"d:\100_Work\101_Program\Proj\XHS\job_location_checker\output\job_location_comparison.md",
        r"d:\100_Work\101_Program\Proj\XHS\job_location_comparison.md",
        r"C:\Users\19396\.gemini\antigravity\brain\dedcedd1-e295-47db-8425-0ea9a3700830\job_location_comparison.md"
    ]

    for p in sync_paths:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception: pass

    print(f"Successfully generated and synced updated Markdown report across all targets!")

if __name__ == "__main__":
    cache_f = os.path.join(BASE_DIR, "output", "job_data_cache_2000.json")
    output_f = os.path.join(BASE_DIR, "output", "job_location_comparison_2000.md")
    run_analysis(cache_f, output_f)
