import subprocess
import os

def extract_audio(video_path, audio_path, log_func=print):
    """
    使用 FFmpeg 从视频中提取 16kHz 单声道的 WAV 音频
    """
    if os.path.exists(audio_path):
        try:
            os.remove(audio_path)
        except Exception:
            pass

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path
    ]

    log_func(f"[Audio] 正在从 {os.path.basename(video_path)} 提取音频...")
    
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    try:
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE, 
            startupinfo=startupinfo,
            check=True
        )
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode('utf-8', errors='ignore')
        raise RuntimeError(f"FFmpeg 提取音频失败: {error_msg}")
    except FileNotFoundError:
        raise RuntimeError("系统未找到 FFmpeg，请确保其已加入环境变量。")

    log_func(f"[Audio] 音频提取成功 -> {audio_path}")
    return audio_path
