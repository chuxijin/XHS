import os

# 视频扫描目录（Downloads）
SCAN_DIR = r"C:\Users\19396\Downloads"

# 用户自定义的剪映草稿基本目录
USER_DRAFT_BASE = r"D:\100_Work\102_Offical\JianyingPro Drafts"
JIANYING_DRAFTS_DIR = os.path.join(USER_DRAFT_BASE, "User Data", "Projects", "com.lved.editor")
if not os.path.exists(JIANYING_DRAFTS_DIR):
    JIANYING_DRAFTS_DIR = USER_DRAFT_BASE

# 固定需要追加到尾部的视频文件路径
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

# ========== 智能剪口播配置（暂未使用）==========
# 语气词列表
SPEECH_FILLER_WORDS = [
    "嗯", "啊", "呃", "那个", "这个", "其实", "就是", "可能",
    "你知道", "对吧", "然后", "然后呢", "就是说", "怎么说呢",
    "反正", "基本上", "大概", "应该", "好像", "我觉得"
]

# 扫描口播视频的目录
SPEECH_SCAN_DIR = r"C:\Users\19396\Downloads"
