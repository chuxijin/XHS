import os
from pyJianYingDraft import (
    DraftFolder, VideoMaterial, AudioMaterial, VideoSegment, AudioSegment,
    Timerange, SEC, TrackType, FontType, TextStyle, TextBorder, TextSegment, ClipSettings, TrackSpec
)
from . import config

def create_jianying_draft(project_name, video_path, bgm_path=None, drafts_dir=None, speech_segments=None, srt_path=None, append_video=None, log_func=print):
    """
    构建剪映本地草稿项目：
    1. 主视频轨道上放置口播视频（若提供 speech_segments 则进行智能跳切排轨，否则放置原视频）。
    2. 若 append_video 为 True 则在尾部拼接片尾模板视频（物流业务线触发）。
    3. 音频轨道上注入随机选择的 BGM 并自适应实际总时长。
    4. 文本轨道上导入智能字幕并应用专属样式（新青年体 + 黑色字 + 白色描边 + 12号字）。
    """
    if not drafts_dir:
        drafts_dir = config.JIANYING_DRAFTS_DIR

    if not drafts_dir or not os.path.exists(drafts_dir):
        log_func(f"[Jianying] 警告: 未检测到剪映的本地草稿存放目录 '{drafts_dir}'。")
        log_func(f"请检查剪映专业版是否已安装。您也可以在 config.py 中手动配置 JIANYING_DRAFTS_DIR 路径。")
        return False

    if append_video is not None:
        append_enabled = bool(append_video)
    else:
        append_enabled = getattr(config, "APPEND_VIDEO_ENABLED", False)

    append_video_path = getattr(config, "APPEND_VIDEO_PATH", None)
    if append_enabled and append_video_path and not os.path.exists(append_video_path):
        log_func(f"[Jianying] 警告: 开启了追加片尾但文件不存在: {append_video_path}，将跳过片尾拼接。")
        append_enabled = False

    log_func(f"[Jianying] 开始调用草稿管理器 -> '{drafts_dir}'")
    draft_folder = DraftFolder(drafts_dir)

    # 1. 创建新草稿，允许同名覆盖 (支持占用自动重命名避让)
    temp_project_name = project_name
    suffix = 1
    while True:
        try:
            canvas_w = int(getattr(config, "CANVAS_WIDTH", 1080))
            canvas_h = int(getattr(config, "CANVAS_HEIGHT", 1440))
            script_file = draft_folder.create_draft(
                draft_name=temp_project_name,
                width=canvas_w,
                height=canvas_h,
                fps=30,
                allow_replace=True
            )
            project_name = temp_project_name
            break
        except Exception as e:
            err_msg = str(e).lower()
            if "winerror 32" in err_msg or "locked" in err_msg or "permission" in err_msg or "access" in err_msg:
                log_func(f"[Jianying] 警告: 草稿 '{temp_project_name}' 正在被剪映使用中(已锁定)。")
                temp_project_name = f"{project_name}_{suffix}"
                log_func(f"[Jianying] 自动尝试使用名称 '{temp_project_name}' 创建新副本项目...")
                suffix += 1
                if suffix > 20:
                    raise e
            else:
                log_func(f"[Jianying] 创建/覆盖草稿失败: {e}")
                return False

    target_draft_path = os.path.join(drafts_dir, project_name)
    try:
        # 2. 初始化轨道 (安全兼容 pyJianYingDraft 0.2.x 与 0.3.x)
        video_track_name = "主视频轨"
        bgm_track_name = "背景音乐轨"

        def _add_track_safe(script, track_type, track_name):
            if hasattr(script, "append_track"):
                return script.append_track(TrackSpec(track_type, track_name))
            elif hasattr(script, "add_track"):
                return script.add_track(track_type, track_name)
            raise AttributeError(f"ScriptFile 对象不支持轨道创建方法")

        _add_track_safe(script_file, TrackType.video, video_track_name)
        if bgm_path and os.path.exists(bgm_path):
            _add_track_safe(script_file, TrackType.audio, bgm_track_name)

        # 3. 导入并放置主视频（支持口播智能多片段切片）
        log_func(f"[Jianying] 导入主视频素材: {os.path.basename(video_path)}")
        video_mat = VideoMaterial(video_path)
        script_file.add_material(video_mat)

        if speech_segments:
            log_func(f"[Jianying] 正在装配智能口播切片 (共 {len(speech_segments)} 个片段)...")
            current_timeline_time = 0
            valid_count = 0
            for idx, (s_start, s_end) in enumerate(speech_segments):
                source_start_us = max(0, int(s_start * 1000000))
                source_end_us = int(s_end * 1000000)

                # 边界保护：若起始时间已超出素材物理时长，则舍弃
                if source_start_us >= video_mat.duration:
                    continue

                # 边界保护：若结束时间超出素材物理时长，严格 clamp 限制在 material.duration 以内
                if source_end_us > video_mat.duration:
                    source_end_us = video_mat.duration

                dur_us = source_end_us - source_start_us
                # 忽略过短切片（小于 40ms，约等于单帧）
                if dur_us < 40000:
                    continue

                target_range = Timerange(current_timeline_time, dur_us)
                source_range = Timerange(source_start_us, dur_us)

                seg = VideoSegment(
                    video_mat,
                    target_range,
                    source_timerange=source_range
                )
                script_file.add_segment(seg, video_track_name)
                current_timeline_time += dur_us
                valid_count += 1

            main_video_total_duration = current_timeline_time
            log_func(f"[Jianying] 口播切片排轨完毕 (有效片段 {valid_count} 个)，有效口播总时长: {main_video_total_duration / 1000000:.2f} 秒")
        else:
            # 回退至全片单片段排轨
            video_seg = VideoSegment(video_mat, Timerange(0, video_mat.duration))
            script_file.add_segment(video_seg, video_track_name)
            main_video_total_duration = video_mat.duration

        # 4. 导入并放置追加片尾模板（仅当开启 append_enabled 时生效）
        total_video_duration = main_video_total_duration
        if append_enabled and append_video_path and os.path.exists(append_video_path):
            log_func(f"[Jianying] 拼接追加片尾: {os.path.basename(append_video_path)}")
            append_mat = VideoMaterial(append_video_path)
            script_file.add_material(append_mat)
            
            # 片尾紧接在主视频/口播切片结束后
            append_seg = VideoSegment(append_mat, Timerange(main_video_total_duration, append_mat.duration))
            script_file.add_segment(append_seg, video_track_name)
            total_video_duration += append_mat.duration

        # 5. 导入并放置背景音乐
        if bgm_path and os.path.exists(bgm_path):
            log_func(f"[Jianying] 导入背景音乐: {os.path.basename(bgm_path)}")
            bgm_mat = AudioMaterial(bgm_path)
            script_file.add_material(bgm_mat)

            # 背景音乐长度取视频总长（纯口播视频总长或含片尾总长）
            bgm_duration_usec = min(bgm_mat.duration, total_video_duration)

            bgm_seg = AudioSegment(
                bgm_mat, 
                Timerange(0, bgm_duration_usec), 
                volume=config.BGM_VOLUME
            )
            script_file.add_segment(bgm_seg, bgm_track_name)

        # 6. 导入智能字幕 (若提供 srt_path 且文件存在)
        if srt_path and os.path.exists(srt_path):
            subtitle_track_name = "智能字幕轨"
            log_func(f"[Jianying] 正在导入智能字幕并应用预设样式 (新青年体, 黑色字, 白色描边, 12号)...")
            
            # 获取样式配置
            font_enum = getattr(FontType, getattr(config, "SUBTITLE_FONT_NAME", "新青年体"), FontType.新青年体)
            font_size = float(getattr(config, "SUBTITLE_FONT_SIZE", 12.0))
            text_color = getattr(config, "SUBTITLE_TEXT_COLOR", (0.0, 0.0, 0.0))
            border_color = getattr(config, "SUBTITLE_BORDER_COLOR", (1.0, 1.0, 1.0))
            border_width = float(getattr(config, "SUBTITLE_BORDER_WIDTH", 40.0))
            pos_y = float(getattr(config, "SUBTITLE_POSITION_Y", -0.75))

            # 构造参考样式模板 TextSegment (新青年体 + 黑色文字 + 白色描边 + 12号字)
            style_ref = TextSegment(
                text="",
                timerange=Timerange(0, 1000000),
                font=font_enum,
                style=TextStyle(
                    size=font_size,
                    color=text_color,
                    auto_wrapping=True,
                    align=1
                ),
                border=TextBorder(
                    color=border_color,
                    width=border_width,
                    alpha=1.0
                ),
                clip_settings=ClipSettings(transform_y=pos_y)
            )

            try:
                script_file.import_srt(
                    srt_path=srt_path,
                    track_name=subtitle_track_name,
                    style_reference=style_ref,
                    clip_settings=None
                )
                log_func(f"[Jianying] 智能字幕轨道导入成功！")
            except Exception as e:
                log_func(f"[Jianying] 警告: 导入字幕发生异常 ({e})，跳过字幕直接保存草稿。")

        # 7. 保存并同步草稿
        script_file.save()
        log_func(f"[Jianying] 剪映草稿项目创建并保存成功 -> '{project_name}'")
        return True
    except Exception as e:
        # 如果草稿在保存完成前发生异常，清理未完成的半截目录，避免剪映读取到损坏的半拉子草稿
        if os.path.exists(target_draft_path):
            try:
                import shutil
                shutil.rmtree(target_draft_path, ignore_errors=True)
            except Exception:
                pass
        raise e
