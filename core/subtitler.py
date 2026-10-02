# coding: utf-8
import os
import re
import tempfile
import subprocess
from datetime import timedelta
from faster_whisper import WhisperModel
import srt
from . import config

def extract_speech_audio(video_path, speech_segments, output_audio_path, log_func=print):
    """
    使用 FFmpeg 将视频中由 speech_segments 指定的发声区间音频抽取并拼接为一段连续的 16kHz WAV。
    如果 speech_segments 为空，则提取全视频音频。
    """
    if os.path.exists(output_audio_path):
        try:
            os.remove(output_audio_path)
        except Exception:
            pass

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    if not speech_segments:
        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_audio_path
        ]
    else:
        filter_parts = []
        concat_inputs = ""
        for idx, (start, end) in enumerate(speech_segments):
            filter_parts.append(f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{idx}]")
            concat_inputs += f"[a{idx}]"
        filter_parts.append(f"{concat_inputs}concat=n={len(speech_segments)}:v=0:a=1[outa]")
        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y", "-i", video_path,
            "-filter_complex", filter_complex,
            "-map", "[outa]",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            output_audio_path
        ]

    try:
        subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            check=True
        )
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"FFmpeg 抽取音频失败: {err}")

    return output_audio_path

def smart_split_words(words, max_len=10):
    """
    针对超过 max_len 字的长句，在自然语义边界（虚词/助词后、停顿处）进行平滑拆分，
    保证拆分后每句都在 5~10 字之间，且绝不在词语内部粗暴切断。
    """
    if not words:
        return []
    
    clean_text = ''.join(getattr(w, "word", "").strip('，。！？；、,.!? ') for w in words)
    if len(clean_text) <= max_len:
        return [{
            'text': clean_text,
            'start': getattr(words[0], "start", 0),
            'end': getattr(words[-1], "end", 0)
        }]

    # 计算需要切分为几段
    k = (len(words) + max_len - 1) // max_len
    target_len = len(words) / k

    splits = []
    start_idx = 0
    particles = {'的', '地', '得', '在', '于', '和', '并', '为', '将', '由', '了', '及', '与', '或'}

    for seg_idx in range(k - 1):
        ideal_cut = int((seg_idx + 1) * target_len)
        best_cut = ideal_cut
        best_score = -999

        cand_start = max(start_idx + 4, ideal_cut - 3)
        cand_end = min(len(words) - 4 * (k - 1 - seg_idx), ideal_cut + 4)

        for cand in range(cand_start, cand_end):
            score = 0
            prev_word = getattr(words[cand - 1], "word", "").strip('，。！？；、,.!? ')

            # 1. 优先在虚词/助词之后断句
            if prev_word in particles:
                score += 6
            # 2. 贴近均匀理想切分点
            score -= abs(cand - ideal_cut) * 1.5
            # 3. 停顿与发音拉长判定
            if getattr(words[cand], "start", 0) - getattr(words[cand - 1], "end", 0) > 0.04:
                score += 3
            if getattr(words[cand - 1], "end", 0) - getattr(words[cand - 1], "start", 0) > 0.18:
                score += 2

            if score > best_score:
                best_score = score
                best_cut = cand

        chunk = words[start_idx:best_cut]
        t = ''.join(getattr(w, "word", "").strip('，。！？；、,.!? ') for w in chunk)
        if t:
            splits.append({
                'text': t,
                'start': getattr(chunk[0], "start", 0),
                'end': getattr(chunk[-1], "end", 0)
            })
        start_idx = best_cut

    last_chunk = words[start_idx:]
    if last_chunk:
        t = ''.join(getattr(w, "word", "").strip('，。！？；、,.!? ') for w in last_chunk)
        if t:
            splits.append({
                'text': t,
                'start': getattr(last_chunk[0], "start", 0),
                'end': getattr(last_chunk[-1], "end", 0)
            })

    return splits

def transcribe_speech_to_subtitles(video_path, speech_segments, model_size=None, log_func=print):
    """
    对粗剪后的口播音频执行语音识别，返回切分清洗后的结构化字幕列表。
    :return: [{'text': str, 'start': float, 'end': float}, ...] 或 None
    """
    if model_size is None:
        model_size = getattr(config, "SUBTITLE_MODEL_SIZE", "small")

    max_chars = int(getattr(config, "SUBTITLE_MAX_CHARS", 10))

    # 动态组装 Whisper Prompt 提示词与专业术语热词
    initial_prompt = getattr(config, "SUBTITLE_INITIAL_PROMPT", "以下是普通话短视频口播，请使用标准规范的简体中文：")
    hotwords = getattr(config, "SUBTITLE_HOTWORDS", [])
    if hotwords:
        hotwords_str = "，".join(hotwords)
        full_prompt = f"{initial_prompt} 提示词与专业术语：{hotwords_str}。"
    else:
        full_prompt = initial_prompt

    replace_dict = getattr(config, "SUBTITLE_REPLACE_DICT", {})

    def _clean_and_correct(text_str):
        if not text_str:
            return ""
        text_str = text_str.strip().strip("，。！？；、,.!? ")
        if replace_dict:
            for wrong, correct in replace_dict.items():
                if wrong in text_str:
                    text_str = text_str.replace(wrong, correct)
        return text_str

    # 临时音频文件
    temp_wav = os.path.join(tempfile.gettempdir(), f"koubo_speech_{os.getpid()}.wav")
    try:
        log_func(f"[Subtitler] 正在抽取粗剪音频片段以进行语音识别...")
        extract_speech_audio(video_path, speech_segments, temp_wav, log_func=log_func)

        log_func(f"[Subtitler] 加载本地 Whisper 模型 ({model_size}) 并转录文字 (开启智能语义断句，单行上限 {max_chars} 字)...")
        if hotwords:
            log_func(f"[Subtitler] 已注入专有名词与领域热词提示 (共 {len(hotwords)} 个): {', '.join(hotwords[:6])}...")

        model = WhisperModel(model_size, device="cpu", compute_type="int8")

        segments, info = model.transcribe(
            temp_wav,
            language="zh",
            word_timestamps=True,
            initial_prompt=full_prompt,
            beam_size=5,
            condition_on_previous_text=False,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=400)
        )

        split_subs = []
        for seg in segments:
            if hasattr(seg, "words") and seg.words:
                raw_splits = smart_split_words(seg.words, max_len=max_chars)
                for item in raw_splits:
                    item['text'] = _clean_and_correct(item['text'])
                    if item['text']:
                        split_subs.append(item)
            else:
                text = _clean_and_correct(seg.text)
                if text:
                    split_subs.append({
                        "text": text,
                        "start": seg.start,
                        "end": seg.end
                    })

        if not split_subs:
            log_func("[Subtitler] 警告: 未能在音频中识别到有效文字内容。")
            return None

        return split_subs

    except Exception as e:
        log_func(f"[Subtitler] 语音识别异常: {e}")
        return None
    finally:
        if os.path.exists(temp_wav):
            try:
                os.remove(temp_wav)
            except Exception:
                pass

def generate_subtitles(video_path, speech_segments, srt_output_path, model_size=None, log_func=print):
    """
    兼容调用：识别文字并直接生成 SRT 文件。
    """
    subs = transcribe_speech_to_subtitles(video_path, speech_segments, model_size=model_size, log_func=log_func)
    if not subs:
        return None

    subtitles = []
    for index, sub in enumerate(subs, start=1):
        sub_item = srt.Subtitle(
            index=index,
            start=timedelta(seconds=sub['start']),
            end=timedelta(seconds=sub['end']),
            content=sub['text']
        )
        subtitles.append(sub_item)

    with open(srt_output_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))

    log_func(f"[Subtitler] 智能短句字幕切分完成！共生成 {len(subtitles)} 行短字幕 ➔ {os.path.basename(srt_output_path)}")
    return srt_output_path

