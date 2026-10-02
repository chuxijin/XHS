# coding: utf-8
import os
import json
import urllib.request
import urllib.error
from datetime import timedelta
import srt
from . import config

def call_ai_semantic_review(sub_items, log_func=print):
    """
    调用大语言模型分析口播字幕，识别口误、半截错句重录和严重无意义卡顿片段。
    :param sub_items: [{'id': int, 'text': str, 'start': float, 'end': float}, ...]
    :return: (keep_ids, drop_ids, reasons)
    """
    if not sub_items:
        return [], [], {}

    api_url = getattr(config, "AI_BASE_URL", "https://runanytime.hxi.me/v1").rstrip("/") + "/chat/completions"
    api_key = getattr(config, "AI_API_KEY", "")
    model_name = getattr(config, "AI_MODEL_NAME", "gpt-4o-mini")
    timeout = getattr(config, "AI_TIMEOUT", 20)

    if not api_key:
        log_func("[AI精剪] 未配置 AI_API_KEY，跳过语义精剪。")
        all_ids = [item['id'] for item in sub_items]
        return all_ids, [], {}

    prompt_data = [{"id": item["id"], "text": item["text"]} for item in sub_items]

    user_prompt = f"""你是一个专业的短视频口播剪辑师。请分析以下通过语音识别生成的口播文字片段列表。
口播录制过程中常常有【口误读错、半截话放弃、结巴后重新整句重录】等情况。
你的核心任务是：
1. 仔细对比上下文：当某一句说错或没说完，紧接着在下一句重新说了正确完整的版本时，必须把说错/没说完的那前半句放入 drop_ids 中予以切除。
2. 对于通顺、完整、表达正常语义的有效句子，必须保留，放入 keep_ids。
3. 务必谨慎精准，绝对不要误删正常推进剧情或阐述观点的有效短句！

输入片段列表：
{json.dumps(prompt_data, ensure_ascii=False, indent=2)}

请严格以 JSON 格式输出，格式如下：
{{
  "keep_ids": [0, 2, 3],
  "drop_ids": [1],
  "reasons": {{
    "1": "口误断句，紧接着在第2句重新完整录制"
  }}
}}
"""

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": "你是一个资深的专业短视频口播剪辑AI助手，必须只输出合法规范的JSON对象，不要输出任何多余闲聊。"},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    try:
        log_func(f"[AI精剪] 正在请求大模型 ({model_name}) 分析 {len(sub_items)} 个口播片段...")
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "XHS-AutoVideo-AICutter/1.0"
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp_data = json.loads(resp.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"]
            result = json.loads(content)

            keep_ids = result.get("keep_ids", [])
            drop_ids = result.get("drop_ids", [])
            reasons = result.get("reasons", {})

            # 校验与保底
            all_ids = {item['id'] for item in sub_items}
            keep_set = set(keep_ids)
            drop_set = set(drop_ids)

            # 如果模型遗漏了某些 id，默认保留
            missing = all_ids - keep_set - drop_set
            if missing:
                for m in missing:
                    keep_set.add(m)

            final_keep_ids = [item['id'] for item in sub_items if item['id'] in keep_set and item['id'] not in drop_set]
            final_drop_ids = [item['id'] for item in sub_items if item['id'] in drop_set]

            return final_keep_ids, final_drop_ids, reasons

    except Exception as e:
        log_func(f"[AI精剪] 请求大模型分析异常 ({e})，安全回退为保留全部粗剪片段。")
        all_ids = [item['id'] for item in sub_items]
        return all_ids, [], {}


def map_audio_time_to_video_time(t, speech_segments):
    """
    将连续拼接音频上的时间戳 t，精准映射回原始视频的物理时间戳。
    """
    if not speech_segments:
        return t
    current_cum = 0.0
    for s_start, s_end in speech_segments:
        dur = s_end - s_start
        if current_cum <= t <= (current_cum + dur + 1e-6):
            offset = max(0.0, t - current_cum)
            return s_start + offset
        current_cum += dur
    return speech_segments[-1][1]


def refine_speech_and_subtitles(speech_segments, raw_sub_items, srt_output_path, log_func=print):
    """
    结合 AI 语义决策，对粗剪切片与字幕执行双重精剪：
    1. 剔除被标记为 drop 的口误与重录片段；
    2. 基于保留的语句重新计算原视频切片 (refined_speech_segments)；
    3. 重排保留字幕在剪映时间轴上的起止时间，并输出新的 SRT 文件；
    4. 确保视频切片与字幕轨 100% 毫秒级音画同步。

    :param speech_segments: 粗剪后的原视频发声区间 [(start, end), ...]
    :param raw_sub_items: Whisper 转录的字幕片段 [{'id': int, 'text': str, 'start': float, 'end': float}, ...]
    :param srt_output_path: 目标 SRT 输出路径
    :return: (refined_speech_segments, srt_output_path)
    """
    if not raw_sub_items:
        # 无字幕内容，保持原样
        return speech_segments, None

    if not getattr(config, "AI_CUTTER_ENABLED", True):
        log_func("[AI精剪] AI 语义精剪功能已关闭，直接使用粗剪切片与原始字幕。")
        _save_srt(raw_sub_items, srt_output_path)
        return speech_segments, srt_output_path

    # 为每个片段标记序号 id（0-indexed）
    indexed_subs = []
    for i, item in enumerate(raw_sub_items):
        item_copy = dict(item)
        item_copy["id"] = i
        indexed_subs.append(item_copy)

    # 1. 语义决策
    keep_ids, drop_ids, reasons = call_ai_semantic_review(indexed_subs, log_func=log_func)

    if not drop_ids:
        log_func("[AI精剪] 语义分析完成：未发现口误或废话，全部片段通顺，保持完整呈现。")
        _save_srt(raw_sub_items, srt_output_path)
        return speech_segments, srt_output_path

    # 打印精剪剔除详情
    log_func("=" * 60)
    log_func(f"[AI精剪] ★ 成功识别并精准剔除 {len(drop_ids)} 处口误/废弃片段 ★")
    for d_id in drop_ids:
        sub = indexed_subs[d_id]
        reason = reasons.get(str(d_id), reasons.get(d_id, "上下文判断为口误或重录"))
        log_func(f"  ❌ 剔除片段 #{d_id}: 【{sub['text']}】 -> 原因: {reason}")
    log_func("=" * 60)

    # 2. 构造保留片段并映射回原视频物理时间
    keep_subs = [indexed_subs[i] for i in keep_ids]

    # 将每个保留句子映射为原视频物理时间区间，带有微小安全缓冲 (0.05s)
    pad = 0.05
    orig_spans = []
    for sub in keep_subs:
        orig_s = max(0.0, map_audio_time_to_video_time(sub['start'], speech_segments) - pad)
        orig_e = map_audio_time_to_video_time(sub['end'], speech_segments) + pad
        orig_spans.append({
            "sub": sub,
            "orig_start": orig_s,
            "orig_end": orig_e
        })

    # 3. 构造精剪后的原视频切片 (refined_speech_segments)
    # 如果两个保留句子在原视频中原本就是紧挨着的（且中间没有被 drop 的切片），平滑合并为一个连续切片
    refined_speech_segments = []
    curr_start = None
    curr_end = None

    for i, span in enumerate(orig_spans):
        s = span["orig_start"]
        e = span["orig_end"]

        if curr_start is None:
            curr_start = s
            curr_end = e
        else:
            # 检查前一个句子与当前句子之间是否有被 drop 的句子
            prev_sub_id = orig_spans[i - 1]["sub"]["id"]
            curr_sub_id = span["sub"]["id"]
            is_contiguous = (curr_sub_id == prev_sub_id + 1)

            # 若两者相邻且未被剔除切断，且在原视频时间间隔很小（<= 0.35s），则平滑缝合
            if is_contiguous and (s <= curr_end + 0.35):
                curr_end = max(curr_end, e)
            else:
                refined_speech_segments.append((round(curr_start, 3), round(curr_end, 3)))
                curr_start = s
                curr_end = e

    if curr_start is not None:
        refined_speech_segments.append((round(curr_start, 3), round(curr_end, 3)))

    # 4. 根据 refined_speech_segments 重新计算剪映时间线上字幕的时间戳
    # 建立映射函数：原视频物理时间 -> 剪映时间线时间
    def map_video_time_to_timeline(v_time):
        tl_time = 0.0
        for seg_s, seg_e in refined_speech_segments:
            seg_dur = seg_e - seg_s
            if v_time < seg_s:
                return tl_time
            elif seg_s <= v_time <= seg_e:
                return tl_time + (v_time - seg_s)
            tl_time += seg_dur
        return tl_time

    realigned_subs = []
    for span in orig_spans:
        sub = span["sub"]
        # 精准对齐到剪映草稿主视频轨上的时间轴
        tl_start = map_video_time_to_timeline(span["orig_start"] + pad)
        tl_end = map_video_time_to_timeline(span["orig_end"] - pad)
        if tl_end > tl_start + 0.1:
            realigned_subs.append({
                "text": sub["text"],
                "start": tl_start,
                "end": tl_end
            })

    _save_srt(realigned_subs, srt_output_path)
    log_func(f"[AI精剪] 精简后有效视频切片: {len(refined_speech_segments)} 段，字幕对齐完毕 ➔ {os.path.basename(srt_output_path)}")
    return refined_speech_segments, srt_output_path


def _save_srt(sub_items, srt_path):
    """
    将带有 start, end, text 的字幕列表保存为标准 SRT 格式。
    """
    subtitles = []
    for index, sub in enumerate(sub_items, start=1):
        sub_item = srt.Subtitle(
            index=index,
            start=timedelta(seconds=max(0.0, sub['start'])),
            end=timedelta(seconds=max(0.0, sub['end'])),
            content=sub['text']
        )
        subtitles.append(sub_item)

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt.compose(subtitles))
