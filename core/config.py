import os

# 视频扫描目录（Downloads）
SCAN_DIR = r"C:\Users\19396\Downloads"

# 用户自定义的剪映草稿基本目录
USER_DRAFT_BASE = r"D:\100_Work\102_Offical\JianyingPro Drafts"
JIANYING_DRAFTS_DIR = os.path.join(USER_DRAFT_BASE, "User Data", "Projects", "com.lved.editor")
if not os.path.exists(JIANYING_DRAFTS_DIR):
    JIANYING_DRAFTS_DIR = USER_DRAFT_BASE

# 是否追加片尾模板视频 (当前法学/招聘类口播无需拼接片尾，设为 False)
APPEND_VIDEO_ENABLED = False
APPEND_VIDEO_PATH = r"C:\Users\19396\Downloads\物流模板.mp4"

# 随机背景音乐候选列表
BGM_CANDIDATES = [
    r"E:\100_Work\103_助理文件\尤克里里.mp3",
    r"E:\100_Work\103_助理文件\动感时尚.mp3"
]

# 背景音乐相对音量比例 (1.0 代表 100% 原音量直接放)
BGM_VOLUME = 1.0

# ========== 本地 ASR 配置 ==========
ASR_MODEL_SIZE = "medium"
ASR_LANGUAGE = "zh"

# ========== 火山引擎 ASR 配置（暂未使用）==========
# VOLCENGINE_APP_ID = ""
# VOLCENGINE_ACCESS_KEY = ""
# VOLCENGINE_SECRET_KEY = ""
# VOLCENGINE_API_KEY = ""

# ========== 视频画面画幅比例配置 ==========
CANVAS_RATIO = "3:4"                  # 画面比例 (默认 3:4 小红书常用比例)
CANVAS_WIDTH = 1080                   # 剪映草稿画布宽度
CANVAS_HEIGHT = 1440                  # 剪映草稿画布高度 (3:4 为 1080x1440, 9:16 为 1080x1920)

# ========== 智能剪口播配置 ==========
SPEECH_CUT_ENABLED = True             # 是否开启智能去气口/静音（True: 开启智能粗剪，False: 保持原片完整）
SPEECH_SILENCE_DB = -30               # 静音判定阈值 (dB)，低于此分贝视为静音
SPEECH_MIN_SILENCE_DUR = 0.35         # 判定为气口/停顿的最短静音时长 (秒)
SPEECH_PADDING = 0.08                 # 片段首尾安全缓冲 (秒)，防止吃字

# ========== 智能字幕及专属样式配置 ==========
SUBTITLE_ENABLED = True               # 是否开启智能语音识别并打上字幕
SUBTITLE_MODEL_SIZE = "small"         # Whisper ASR 模型尺寸（可选：small、medium、large-v3）
SUBTITLE_MAX_CHARS = 10               # 每行字幕最大字数上限（推荐 8~10 字，保持短视频口播节奏）
SUBTITLE_SPLIT_PAUSE = 0.35           # 词间自然停顿断句阈值 (秒)
SUBTITLE_FONT_NAME = "新青年体"       # 剪映内置字体
SUBTITLE_FONT_SIZE = 12.0             # 字号大小
SUBTITLE_TEXT_COLOR = (0.0, 0.0, 0.0) # 文字填充颜色 (黑色)
SUBTITLE_BORDER_COLOR = (1.0, 1.0, 1.0) # 描边颜色 (白色)
SUBTITLE_BORDER_WIDTH = 40.0          # 描边宽度
SUBTITLE_POSITION_Y = -0.72           # 字幕在屏幕中下方纵坐标位置 (-1.0 至 1.0，3:4画幅下 -0.72 视觉更适中)

# Whisper 提示词与专业术语热词引导 (大幅提升同音词、专有名词准确率)
SUBTITLE_INITIAL_PROMPT = "以下是普通话短视频口播，请使用标准规范的简体中文："
SUBTITLE_HOTWORDS = [
    "360安全科技", "招聘", "法务专员", "人工智能", "互联网大厂",
    "岗位", "应届毕业生", "全日制", "本科及以上", "硕士学历", "北京市",
    "小红书", "运营", "求职"
]

# 常见易错词兜底替换映射字典 (后处理自动化清洗)
SUBTITLE_REPLACE_DICT = {
    "人工症": "人工智能",
    "港澳的": "岗位的",
    "港澳": "岗位",
    "3600": "360",
    "法学本科技上": "法学本科及以上",
    "市民运销前日是": "全日制"
}

# 语气词列表
SPEECH_FILLER_WORDS = [
    "嗯", "啊", "呃", "那个", "这个", "其实", "就是", "可能",
    "你知道", "对吧", "然后", "然后呢", "就是说", "怎么说呢",
    "反正", "基本上", "大概", "应该", "好像", "我觉得"
]

# 扫描口播视频的目录
SPEECH_SCAN_DIR = r"C:\Users\19396\Downloads"

# ========== 3:4 自动封面生成配置 ==========
COVER_ENABLED = True                  # 是否自动生成 3:4 独立封面图
COVER_TOP_TITLE = "27届秋招"           # 顶部固定大标题
COVER_BOTTOM_TEXT = "投递链接，进裙自取" # 底部固定引导文字
COVER_DEFAULT_COMPANY = "360"         # 兜底默认公司名（当文件名无法提取时）
COVER_DEFAULT_POSITION = "法务专员"    # 兜底默认岗位名（当文件名无法提取时）
COVER_FONT_PATH = r"C:\Windows\Fonts\msyhbd.ttc" # 封面粗体字体文件路径
COVER_DATE_FONT_SIZE = 112            # 封面日期字号（微调适中）
COVER_DATE_STROKE_WIDTH = 10          # 封面日期粗黑描边宽度

# ========== AI 语义精剪配置 (口误、结巴与重录自动剔除) ==========
AI_CUTTER_ENABLED = True              # 是否开启 AI 语义精剪
AI_BASE_URL = "https://runanytime.hxi.me/v1"
AI_API_KEY = "sk-1ELa0JAQYv8spaTwqv3cdUWPDzllzqbMEz4UpNmYAFh2iywy"
AI_MODEL_NAME = "gpt-4o-mini"
AI_TIMEOUT = 20                       # 请求超时时间（秒）





