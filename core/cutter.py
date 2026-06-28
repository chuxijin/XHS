import subprocess
import os
import srt
from datetime import timedelta
from . import config

def calculate_keep_intervals(words_list):
    """
    根据词列表，过滤水词，扩展词区间并合并，计算出最终需要保留的视频时间区间。
    """
    valid_intervals = []
    for w in words_list:
        word_text = w["word"]
        if word_text not in config.WATER_WORDS:
            start = max(0.0, w["start"] - config.WORD_PADDING)
            end = w["end"] + config.WORD_PADDING
            valid_intervals.append([start, end])

    if not valid_intervals:
        return []

    valid_intervals.sort(key=lambda x: x[0])
    
    merged_intervals = [valid_intervals[0]]
    for current in valid_intervals[1:]:
        prev = merged_intervals[-1]
        if current[0] - prev[1] <= config.MAX_GAP_TO_MERGE:
            prev[1] = max(prev[1], current[1])
        else:
            merged_intervals.append(current)

    return merged_intervals


def generate_srt_subtitles(words_list, keep_intervals, srt_output_path, log_func=print):
    """
    将保留词的时间戳重新映射到剪切后的新视频时间轴上，并生成标准的 SRT 字幕文件。
    """
    offsets = []
    current_offset = 0.0
    for interval in keep_intervals:
        offsets.append(current_offset)
        current_offset += (interval[1] - interval[0])

    subtitles = []
    sentence_words = []
    current_interval_idx = 0

    for w in words_list:
        if w["word"] in config.WATER_WORDS:
            continue
        
        w_start, w_end = w["start"], w["end"]
        found = False
        
        for idx, interval in enumerate(keep_intervals):
            if interval[0] <= w_start + 0.01 and w_end - 0.01 <= interval[1]:
                current_interval_idx = idx
                found = True
                break
        
        if not found:
            continue
            
        new_start = w_start - keep_intervals[current_interval_idx][0] + offsets[current_interval_idx]
        new_end = w_end - keep_intervals[current_interval_idx][0] + offsets[current_interval_idx]
        
        w_new = {
            "word": w["word"],
            "start": new_start,
            "end": new_end
        }
        
        if not sentence_words:
            sentence_words.append(w_new)
        else:
            last_w = sentence_words[-1]
            if w_new["start"] - last_w["end"] > 1.5 or len("".join([x["word"] for x in sentence_words])) > 10:
                subtitles.append(create_srt_item(len(subtitles) + 1, sentence_words))
                sentence_words = [w_new]
            else:
                sentence_words.append(w_new)

    if sentence_words:
        subtitles.append(create_srt_item(len(subtitles) + 1, sentence_words))

    with open(srt_output_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))
    log_func(f"[Cutter] 字幕重映射生成成功 -> {srt_output_path}")


def create_srt_item(index, words):
    content = "".join([w["word"] for w in words])
    start_time = timedelta(seconds=words[0]["start"])
    end_time = timedelta(seconds=words[-1]["end"])
    return srt.Subtitle(index=index, start=start_time, end=end_time, content=content)


def cut_video(video_path, keep_intervals, output_path, log_func=print):
    """
    调用 FFmpeg 基于 filter_complex 裁剪拼接保留的片段
    """
    if not keep_intervals:
        raise ValueError("没有需要保留的视频片段！")

    if os.path.exists(output_path):
        try:
            os.remove(output_path)
        except Exception:
            pass

    filter_parts = []
    concat_inputs = ""
    for idx, (start, end) in enumerate(keep_intervals):
        filter_parts.append(f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{idx}]")
        filter_parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{idx}]")
        concat_inputs += f"[v{idx}][a{idx}]"
    
    filter_parts.append(f"{concat_inputs}concat=n={len(keep_intervals)}:v=1:a=1[outv][outa]")
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "superfast",
        "-crf", "20",
        "-c:a", "aac",
        output_path
    ]

    log_func(f"[Cutter] 正在对视频进行智能裁剪拼接 (共 {len(keep_intervals)} 个片段)...")

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='ignore')
        raise RuntimeError(f"FFmpeg 裁剪失败: {error_msg}")

    log_func(f"[Cutter] 视频自动精简裁剪成功 -> {output_path}")
    return output_path
