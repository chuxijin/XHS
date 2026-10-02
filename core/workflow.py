import os
import time
import random
from . import config
from .jianying import create_jianying_draft
from .speech_detector import detect_speech_segments
from .subtitler import generate_subtitles
import tempfile

def process_video_workflow(video_path, log_func=print):
    """
    智能口播剪辑、字幕识别与极速合并包装流：
    1. 随机选择背景音乐 (BGM)。
    2. 智能口播气口/静音检测，提取有效说话时间段。
    3. 智能语音转录生成对齐字幕文件 (.srt)。
    4. 使用 pyJianYingDraft 一键组装剪映本地草稿（智能跳切排轨 + 新青年体黑字白边字幕 + 拼接物流模板 + 混音 BGM）。
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

    # 解析视频命名元数据 (日期 - 校招/社招 - 物流/法学 - 公司 - 岗位)
    from .cover_generator import parse_video_meta, generate_cover_image
    date_str, recruit_type, category, company, position = parse_video_meta(video_path)
    is_append_needed = (category == "物流")

    start_time = time.time()
    log_func("="*60)
    log_func("    ★ AutoVideo 智能口播粗剪、字幕识别与视频包装流水线 ★")
    log_func(f" 原始视频: {video_path}")
    log_func(f" 业务路由: 【{recruit_type}】 | 【{category}】 (片尾拼接: {'开启' if is_append_needed else '关闭'})")
    log_func(f" 提取实体: 日期 -> '{date_str}' | 公司 -> '{company}' | 岗位 -> '{position}'")
    log_func(f" 随机选中 BGM: {os.path.basename(bgm_path)}")
    log_func(f" 剪映草稿名称: {project_name}")
    log_func("="*60)

    # 2. 智能剪口播检测
    speech_segments = None
    if getattr(config, "SPEECH_CUT_ENABLED", True):
        try:
            _, speech_segments = detect_speech_segments(
                video_path=video_path,
                noise_db=getattr(config, "SPEECH_SILENCE_DB", -30),
                min_silence_dur=getattr(config, "SPEECH_MIN_SILENCE_DUR", 0.35),
                padding=getattr(config, "SPEECH_PADDING", 0.08),
                log_func=log_func
            )
        except Exception as e:
            log_func(f"[Workflow] 智能口播检测异常 ({e})，将回退为完整视频模式导入。")
            speech_segments = None

    # 3. 智能字幕识别与 AI 语义精剪 (口误、结巴与重录自动剔除)
    srt_path = None
    refined_speech_segments = speech_segments
    if getattr(config, "SUBTITLE_ENABLED", True):
        temp_srt_path = os.path.join(tempfile.gettempdir(), f"{project_name}_{int(time.time())}.srt")
        try:
            from .subtitler import transcribe_speech_to_subtitles
            from .ai_cutter import refine_speech_and_subtitles

            # 3.1 Whisper ASR 语音识别
            raw_subs = transcribe_speech_to_subtitles(
                video_path=video_path,
                speech_segments=speech_segments,
                model_size=getattr(config, "SUBTITLE_MODEL_SIZE", "small"),
                log_func=log_func
            )

            # 3.2 AI 语义精剪与音画字幕毫秒级重构
            if raw_subs:
                refined_speech_segments, srt_path = refine_speech_and_subtitles(
                    speech_segments=speech_segments,
                    raw_sub_items=raw_subs,
                    srt_output_path=temp_srt_path,
                    log_func=log_func
                )
        except Exception as e:
            log_func(f"[Workflow] 字幕识别/AI精剪异常 ({e})，安全回退至粗剪切片")
            srt_path = None
            refined_speech_segments = speech_segments

    # 4. 直接同步创建剪映本地草稿 (使用精剪切片与精准对齐的字幕)
    try:
        success = create_jianying_draft(
            project_name=project_name,
            video_path=video_path,
            bgm_path=bgm_path,
            speech_segments=refined_speech_segments,
            srt_path=srt_path,
            append_video=is_append_needed,
            log_func=log_func
        )
    except Exception as e:
        log_func(f"[Workflow] 错误: 创建剪映草稿时发生异常: {e}")
        return False, f"生成草稿异常: {e}"
    finally:
        # 清理临时字幕文件
        if srt_path and os.path.exists(srt_path):
            try:
                os.remove(srt_path)
            except Exception:
                pass

    if success:
        # 5. 自动生成 3:4 独立封面大图并同步至剪映草稿
        cover_path = None
        if getattr(config, "COVER_ENABLED", True):
            try:
                video_dir = os.path.dirname(video_path)
                cover_output_path = os.path.join(video_dir, f"{project_name}_cover.jpg")
                cover_path = generate_cover_image(
                    video_path=video_path,
                    output_cover_path=cover_output_path,
                    company=company,
                    position=position,
                    recruit_type=recruit_type,
                    category=category,
                    date_str=date_str,
                    log_func=log_func
                )
                # 同步复制到剪映草稿目录下，使剪映草稿箱直接显示封面
                drafts_dir = config.JIANYING_DRAFTS_DIR
                target_draft_path = os.path.join(drafts_dir, project_name)
                if os.path.exists(target_draft_path) and os.path.exists(cover_path):
                    import shutil
                    shutil.copyfile(cover_path, os.path.join(target_draft_path, "draft_cover.jpg"))
                    shutil.copyfile(cover_path, os.path.join(target_draft_path, "draft_local_cover.jpg"))
            except Exception as e:
                log_func(f"[Workflow] 警告: 自动生成封面图发生异常: {e}")

        log_func("="*60)
        log_func("  🎉 恭喜！智能剪口播、字幕识别及剪映草稿拼装处理完毕！")
        if speech_segments:
            log_func(f"  ➜ 已智能切除气口停顿，生成 {len(speech_segments)} 个独立口播片段")
        if srt_path:
            log_func("  ➜ 已自动生成并导入新青年体口播专属字幕 (黑心白边12号)")
        if cover_path and os.path.exists(cover_path):
            log_func(f"  ➜ 已全自动生成 3:4 独立小红书封面图: {os.path.basename(cover_path)}")
        if is_append_needed:
            log_func("  ➜ 已随机添加背景乐、拼接物流片尾模板 (物流业务线触发)")
        else:
            log_func("  ➜ 已随机添加背景乐自适应混音 (法学业务线，保持纯口播)")
        log_func("  ➜ 剪映草稿已同步: 现在您只需直接打开 PC 端剪映，即可双击草稿直接一键导出成片！")
        log_func("="*60)
        duration = time.time() - start_time
        log_func(f"[Main] 任务总耗时: {duration:.2f} 秒\n")
        return True, project_name

    return False, "草稿生成失败"
