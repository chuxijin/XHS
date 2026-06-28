import os
import time
import random
from . import config
from .jianying import create_jianying_draft

def process_video_workflow(video_path, log_func=print):
    """
    极速合并包装流：
    1. 随机选择背景音乐 (BGM)。
    2. 使用 pyJianYingDraft 一键组装剪映本地草稿。
    """
    video_path = os.path.abspath(video_path)
    if not os.path.exists(video_path):
        log_func(f"[Error] 找不到输入的原始视频文件: {video_path}")
        return False, "找不到原始视频文件"

    # 1. 随机挑选背景音乐
    bgm_path = random.choice(config.BGM_CANDIDATES)
    bgm_path = os.path.abspath(bgm_path)
    if not os.path.exists(bgm_path):
        log_func(f"[Error] 找不到背景音乐文件: {bgm_path}")
        return False, "找不到背景音乐"

    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    project_name = f"AutoVideo_{video_basename}"

    start_time = time.time()
    log_func("="*60)
    log_func("        ★ AutoVideo 自动化视频合并与背景乐包装流水线 ★")
    log_func(f" 原始视频: {video_path}")
    log_func(f" 随机选中 BGM: {os.path.basename(bgm_path)}")
    log_func(f" 剪映草稿名称: {project_name}")
    log_func("="*60)

    # 2. 直接同步创建剪映本地草稿 (无须重编码，瞬时完成)
    success = create_jianying_draft(
        project_name=project_name,
        video_path=video_path,
        bgm_path=bgm_path,
        log_func=log_func
    )

    if success:
        log_func("="*60)
        log_func("  🎉 恭喜！剪映草稿拼装流水线处理完毕！")
        log_func("  ➜ 已随机添加背景乐、拼接物流片尾模板")
        log_func("  ➜ 剪映草稿已同步: 现在您只需直接打开 PC 端剪映，即可双击草稿直接一键导出成片！")
        log_func("="*60)
        duration = time.time() - start_time
        log_func(f"[Main] 任务总耗时: {duration:.2f} 秒\n")
        return True, project_name

    return False, "草稿生成失败"
