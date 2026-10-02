# coding: utf-8
import os
import re
import subprocess

def detect_speech_segments(video_path, noise_db=-30, min_silence_dur=0.35, padding=0.08, log_func=print):
    """
    使用 FFmpeg silencedetect 分析视频中音频的静音与发声区间，
    剔除空白停顿与气口，计算出最终需要保留的有效口播片段。
    
    :param video_path: 输入视频文件绝对路径
    :param noise_db: 静音阈值（分贝），低于此值被判定为静音（默认 -30dB）
    :param min_silence_dur: 最短静音持续时间（秒），超过此长度被视为气口/停顿并切除（默认 0.35s）
    :param padding: 每个发声片段首尾保留的安全缓冲（秒），防止掐字（默认 0.08s）
    :param log_func: 日志输出函数
    :return: (total_duration, speech_ranges)
             total_duration: 视频总时长（秒）
             speech_ranges: 有效口播时间段列表 [(start_s, end_s), ...]
    """
    log_func(f"[SpeechDetector] 正在分析视频音频发声段 (静音阈值: {noise_db}dB, 停顿判定: {min_silence_dur}s)...")

    cmd = [
        "ffmpeg", "-i", video_path,
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence_dur}",
        "-f", "null", "-"
    ]

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            startupinfo=startupinfo,
            check=True
        )
        output = proc.stdout
    except subprocess.CalledProcessError as e:
        output = e.stdout or ""

    # 解析视频总时长
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", output)
    if duration_match:
        h, m, s = duration_match.groups()
        total_duration = int(h) * 3600 + int(m) * 60 + float(s)
    else:
        # fallback 使用 ffprobe 探测
        probe_cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", video_path
        ]
        probe = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True, startupinfo=startupinfo)
        total_duration = float(probe.stdout.strip()) if probe.stdout.strip() else 0.0

    if total_duration <= 0.0:
        log_func("[SpeechDetector] 警告: 未能获取到视频有效时长，返回空区间。")
        return 0.0, []

    silence_starts = [float(x) for x in re.findall(r"silence_start:\s*([\d\.]+)", output)]
    silence_ends = [float(x) for x in re.findall(r"silence_end:\s*([\d\.]+)", output)]

    # 组装静音段 [(s_start, s_end)]
    silence_ranges = []
    for s_start in silence_starts:
        matched_end = None
        for s_end in silence_ends:
            if s_end > s_start:
                matched_end = s_end
                break
        if matched_end:
            silence_ranges.append((s_start, matched_end))
        else:
            silence_ranges.append((s_start, total_duration))

    # 取静音区间的补集作为有效发声区间，并加入 padding 安全缓冲区
    raw_speech_ranges = []
    current_time = 0.0

    for s_start, s_end in silence_ranges:
        speech_start = max(0.0, current_time - padding if current_time > 0 else 0.0)
        speech_end = min(total_duration, s_start + padding)

        # 忽略小于 0.15 秒的零碎杂音
        if speech_end - speech_start >= 0.15:
            raw_speech_ranges.append((speech_start, speech_end))

        current_time = s_end

    # 处理最后一段发声
    if current_time < total_duration:
        speech_start = max(0.0, current_time - padding)
        speech_end = total_duration
        if speech_end - speech_start >= 0.15:
            raw_speech_ranges.append((speech_start, speech_end))

    # 合并相邻或因 padding 产生重叠的区间（间隔小于 60ms 直接连为一段）
    merged_ranges = []
    for seg in raw_speech_ranges:
        if not merged_ranges:
            merged_ranges.append(seg)
        else:
            prev_start, prev_end = merged_ranges[-1]
            if seg[0] <= prev_end + 0.06:
                merged_ranges[-1] = (prev_start, max(prev_end, seg[1]))
            else:
                merged_ranges.append(seg)

    # 统计信息
    kept_duration = sum(end - start for start, end in merged_ranges)
    removed_duration = total_duration - kept_duration
    log_func(f"[SpeechDetector] 分析完成: 原时长 {total_duration:.2f}s ➔ 剪辑后 {kept_duration:.2f}s (共剔除停顿气口 {removed_duration:.2f}s, 分成 {len(merged_ranges)} 个口播切片)")

    return total_duration, merged_ranges
