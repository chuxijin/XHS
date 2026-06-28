import os
from pyJianYingDraft import DraftFolder, VideoMaterial, AudioMaterial, VideoSegment, AudioSegment, Timerange, SEC, TrackType
from . import config

def create_jianying_draft(project_name, video_path, bgm_path=None, drafts_dir=None, log_func=print):
    """
    构建剪映本地草稿项目：
    1. 主视频轨道上依次拼接主视频与物流模板视频。
    2. 音频轨道上注入随机选择的 BGM。
    """
    if not drafts_dir:
        drafts_dir = config.JIANYING_DRAFTS_DIR

    if not drafts_dir or not os.path.exists(drafts_dir):
        log_func(f"[Jianying] 警告: 未检测到剪映的本地草稿存放目录 '{drafts_dir}'。")
        log_func(f"请检查剪映专业版是否已安装。您也可以在 config.py 中手动配置 JIANYING_DRAFTS_DIR 路径。")
        return False

    append_video_path = config.APPEND_VIDEO_PATH
    if not os.path.exists(append_video_path):
        log_func(f"[Jianying] 错误: 找不到后置追加视频 (物流模板): {append_video_path}")
        return False

    log_func(f"[Jianying] 开始调用草稿管理器 -> '{drafts_dir}'")
    draft_folder = DraftFolder(drafts_dir)

    # 1. 创建新草稿，允许同名覆盖 (支持占用自动重命名避让)
    temp_project_name = project_name
    suffix = 1
    while True:
        try:
            script_file = draft_folder.create_draft(
                draft_name=temp_project_name,
                width=1080,
                height=1920,
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

    # 2. 初始化轨道
    video_track_name = "主视频轨"
    bgm_track_name = "背景音乐轨"
    
    script_file.add_track(TrackType.video, video_track_name)
    if bgm_path and os.path.exists(bgm_path):
        script_file.add_track(TrackType.audio, bgm_track_name)

    # 3. 导入并放置主视频
    log_func(f"[Jianying] 导入主视频: {os.path.basename(video_path)}")
    video_mat = VideoMaterial(video_path)
    script_file.add_material(video_mat)
    
    # 视频段 A 放在第 0 秒开始，持续 video_mat.duration 微秒
    video_seg = VideoSegment(video_mat, Timerange(0, video_mat.duration))
    script_file.add_segment(video_seg, track_name=video_track_name)

    # 4. 导入并放置物流片尾模板
    log_func(f"[Jianying] 拼接追加片尾: {os.path.basename(append_video_path)}")
    append_mat = VideoMaterial(append_video_path)
    script_file.add_material(append_mat)
    
    # 视频段 B 放在 video_mat.duration 微秒开始，持续 append_mat.duration 微秒
    append_seg = VideoSegment(append_mat, Timerange(video_mat.duration, append_mat.duration))
    script_file.add_segment(append_seg, track_name=video_track_name)

    # 5. 导入并放置背景音乐
    if bgm_path and os.path.exists(bgm_path):
        log_func(f"[Jianying] 导入背景音乐: {os.path.basename(bgm_path)}")
        bgm_mat = AudioMaterial(bgm_path)
        script_file.add_material(bgm_mat)

        # 背景音乐长度取视频总长
        total_duration_usec = video_mat.duration + append_mat.duration
        bgm_duration_usec = min(bgm_mat.duration, total_duration_usec)

        bgm_seg = AudioSegment(
            bgm_mat, 
            Timerange(0, bgm_duration_usec), 
            volume=config.BGM_VOLUME
        )
        script_file.add_segment(bgm_seg, track_name=bgm_track_name)

    # 6. 保存并同步草稿
    script_file.save()
    log_func(f"[Jianying] 剪映草稿项目创建并保存成功 -> '{project_name}'")
    return True
