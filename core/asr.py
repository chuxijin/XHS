import os
from faster_whisper import WhisperModel
from . import config

def transcribe_audio_internal(model, audio_path, language):
    """
    内部辅助函数：执行实际的 ASR 转录并提取词级信息。
    """
    segments, info = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500)
    )

    words_list = []
    for segment in segments:
        if segment.words:
            for w in segment.words:
                cleaned_word = w.word.strip()
                if cleaned_word:
                    words_list.append({
                        "word": cleaned_word,
                        "start": w.start,
                        "end": w.end
                    })
    return words_list


def transcribe_audio(audio_path, model_size=config.ASR_MODEL_SIZE, language=config.ASR_LANGUAGE, log_func=print):
    """
    使用 faster-whisper 本地识别音频，返回包含所有词级时间戳（start, end, word）的列表。
    内建 GPU/CPU 自动降级与运行时 CUDA 缺失库的无缝平滑重试机制。
    """
    log_func(f"[ASR] 正在加载 ASR 模型 (大小: {model_size})，首次运行会自动下载模型，这需要一点时间...")

    device = "cuda"
    compute_type = "float16"
    use_gpu = True

    try:
        log_func("[ASR] 尝试初始化 GPU 加速引擎...")
        model = WhisperModel(model_size, device="cuda", compute_type="float16")
    except Exception:
        log_func("[ASR] 初始化 GPU 引擎失败，自动回退到 CPU 模型...")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        device = "cpu"
        compute_type = "int8"
        use_gpu = False

    log_func(f"[ASR] 开始解析语音内容 (推理设备: {device.upper()})...")

    try:
        words_list = transcribe_audio_internal(model, audio_path, language)
    except RuntimeError as e:
        err_msg = str(e).lower()
        if use_gpu and ("cublas" in err_msg or "cudnn" in err_msg or "cannot be loaded" in err_msg):
            log_func(f"[ASR] ⚠️ 检测到 CUDA 运行库加载异常 ({e})。")
            log_func("[ASR] 程序正在自动无缝切换到 CPU 推理模式，并重新运行解析...")
            model = WhisperModel(model_size, device="cpu", compute_type="int8")
            words_list = transcribe_audio_internal(model, audio_path, language)
        else:
            raise e

    log_func(f"[ASR] 解析完毕！共捕获到 {len(words_list)} 个词。")
    return words_list
