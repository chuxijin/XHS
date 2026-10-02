#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
脚本名称: sync_notice_date_and_remark.py
功能描述:
    在 JobLeap 企业管理后台（company-basic）中：
    1. 严格全等过滤【备注】列等于指定文本（默认: "自动新增公告链接，须核查"）的记录；
    2. 打开【标注】信息弹窗；
    3. 点击【网申开始时间】输入框，选择快捷选项【公告发布日期】将开始时间自动对齐；
    4. 将【备注】更新为追加后缀的新内容（默认: "自动新增公告链接，须核查 1"）；
    5. 保存并等待接口确认 200，循环处理直到当前页全部完成；
    6. 可选支持自动翻页（--pages 参数）。

运行示例:
    python sync_notice_date_and_remark.py
    python sync_notice_date_and_remark.py --pages 3
    python sync_notice_date_and_remark.py --target-remark "自动新增公告链接，须核查" --suffix " 1"
"""

import sys
import argparse
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright, Page, Locator

async def close_any_dialog(page: Page):
    """兜底关闭所有可见弹窗，防止界面阻塞"""
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        await page.evaluate('''() => {
            const wrappers = Array.from(document.querySelectorAll('.el-dialog__wrapper'))
                .filter(w => window.getComputedStyle(w).display !== 'none');
            wrappers.forEach(w => {
                const btn = w.querySelector('.el-dialog__headerbtn, button.el-button--default');
                if (btn) btn.click();
            });
        }''')
        await page.wait_for_timeout(400)
    except Exception:
        pass

async def update_single_row(page: Page, row_locator: Locator, new_remark: str) -> str:
    """处理单条记录：点击标注 -> 对齐时间 -> 修改备注 -> 保存"""
    # 1. 点击标注
    annotate_btn = row_locator.locator("button:has-text('标注')")
    await annotate_btn.click()
    
    main_dialog = page.locator(".el-dialog__wrapper:visible .el-dialog:has(.el-dialog__title:has-text('标注信息'))")
    await main_dialog.wait_for(state="visible", timeout=6000)

    # 2. 点击网申开始时间输入框
    start_time_input = main_dialog.locator("input[placeholder='请选择网申开始时间']")
    await start_time_input.click()
    await page.wait_for_timeout(300)

    # 3. 点击快捷选项【公告发布日期】
    shortcut_btn = page.locator("button.el-picker-panel__shortcut:has-text('公告发布日期')").last
    try:
        await shortcut_btn.wait_for(state="visible", timeout=2500)
        await shortcut_btn.click()
        await page.wait_for_timeout(300)
    except Exception:
        print(" [⚠️ 无快捷选项保持原值]", end="", flush=True)
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)

    new_time = await start_time_input.input_value()

    # 4. 修改备注
    remark_textarea = main_dialog.locator("textarea[placeholder='请输入备注信息']")
    await remark_textarea.fill(new_remark)

    # 5. 点击【确 定】并等待接口响应 200
    confirm_btn = main_dialog.locator(".el-dialog__footer button.el-button--primary:has-text('确 定')").last
    async with page.expect_response(
        lambda r: ("update_manual" in r.url or "update" in r.url) and r.status == 200,
        timeout=10000
    ):
        await confirm_btn.click()

    # 等待弹窗完全消失
    await main_dialog.wait_for(state="hidden", timeout=5000)
    await page.wait_for_timeout(500)
    return new_time

async def process_current_page(page: Page, target_remark: str, new_remark: str):
    """处理当前页所有符合条件的行"""
    success_list = []
    fail_list = []
    processed_count = 0

    while True:
        # 动态检索当前页第一条符合条件的行（规避更新后行位移问题）
        rows = page.locator(".el-table__body-wrapper tbody tr")
        count = await rows.count()
        target_idx = -1
        target_company = ""

        for i in range(count):
            r = rows.nth(i)
            remark_td = r.locator("td").nth(11)  # 第 11 列为备注
            text = (await remark_td.inner_text()).strip()
            if text == target_remark:
                target_idx = i
                target_company = (await r.locator("td").nth(1).inner_text()).strip()
                break

        if target_idx == -1:
            break

        processed_count += 1
        print(f"  [{processed_count}] 行 {target_idx + 1:02d}: {target_company} ...", end=" ", flush=True)

        try:
            target_row = rows.nth(target_idx)
            new_time = await update_single_row(page, target_row, new_remark)
            print(f"✅ 对齐日期: {new_time}")
            success_list.append((target_company, new_time))
        except Exception as e:
            print(f"❌ 失败: {e}")
            fail_list.append((target_company, str(e)))
            await close_any_dialog(page)
            # 遇到严重报错暂停避免死循环
            break

    return success_list, fail_list

async def go_next_page(page: Page) -> bool:
    """尝试点击下一页按钮"""
    try:
        next_btn = page.locator(".el-pagination button.btn-next")
        if not await next_btn.is_visible():
            return False
        is_disabled = await next_btn.is_disabled()
        if is_disabled:
            return False
        await next_btn.click()
        await page.wait_for_timeout(1500)
        return True
    except Exception:
        return False

async def main():
    parser = argparse.ArgumentParser(description="自动对齐网申开始时间至公告发布日期并更新备注")
    parser.add_argument("--cdp-url", default="http://localhost:9222", help="Chrome CDP 连接地址 (默认: http://localhost:9222)")
    parser.add_argument("--target-remark", default="自动新增公告链接，须核查", help="目标匹配备注（严格全等，默认: '自动新增公告链接，须核查'）")
    parser.add_argument("--suffix", default=" 1", help="备注追加的后缀（默认: ' 1'）")
    parser.add_argument("--pages", type=int, default=1, help="处理的页数（默认: 1，仅当前页）")
    args = parser.parse_args()

    new_remark = f"{args.target_remark}{args.suffix}"

    print(f"==================================================")
    print(f"  JobLeap 公告发布日期对齐与备注批量更新工具")
    print(f"  匹配条件 (严格全等): '{args.target_remark}'")
    print(f"  更新后备注:        '{new_remark}'")
    print(f"  计划处理页数:      {args.pages} 页")
    print(f"==================================================")

    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(args.cdp_url)
        except Exception as e:
            print(f"❌ 连接 CDP 失败 ({args.cdp_url})，请确认 Chrome 是否已带 --remote-debugging-port=9222 启动。")
            print(f"错误信息: {e}")
            return

        page = None
        for pg in browser.contexts[0].pages:
            if "company-basic" in pg.url:
                page = pg
                break

        if not page:
            print("❌ 未在当前浏览器中找到包含 'company-basic' 的企业管理页面，请先在浏览器打开。")
            return

        total_success = []
        total_fail = []

        for p_idx in range(1, args.pages + 1):
            print(f"\n>>> 正在处理第 {p_idx} / {args.pages} 页...")
            success, fail = await process_current_page(page, args.target_remark, new_remark)
            total_success.extend(success)
            total_fail.extend(fail)
            print(f">>> 第 {p_idx} 页完成: 成功 {len(success)} 家, 失败 {len(fail)} 家")

            if p_idx < args.pages:
                print(">>> 正在翻到下一页...")
                has_next = await go_next_page(page)
                if not has_next:
                    print(">>> 已到达最后一页，停止翻页。")
                    break

        print("\n==================================================")
        print(f"🎉 全部执行完毕！总计成功: {len(total_success)} 家，总计失败: {len(total_fail)} 家")
        print("==================================================")
        if total_success:
            print("\n【成功更新清单】:")
            for idx, (comp, t) in enumerate(total_success, 1):
                print(f"  {idx:02d}. {comp} (开始时间: {t})")

if __name__ == "__main__":
    asyncio.run(main())
