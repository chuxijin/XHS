# coding: utf-8
import os
import re
import tempfile
import subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
from . import config

def parse_video_meta(video_path, default_company=None, default_position=None):
    """
    智能解析视频文件名元数据。
    标准规范格式：
        日期-校招/社招-物流/法学-公司名称-岗位名称.mp4
    例如：
        9.19-校招-法学-360-法务专员.mp4   -> ('9.19', '校招', '法学', '360', '新开法务专员岗位')
        9.19-社招-物流-爱奇迹-采购开发.mp4 -> ('9.19', '社招', '物流', '爱奇迹', '新开采购开发岗位')
        校招-法学-360-法务专员.mp4        -> ('9.19', '校招', '法学', '360', '新开法务专员岗位') （不带日期自动兜底系统日期）
        360_法务专员.mp4                 -> ('9.19', '校招', '法学', '360', '新开法务专员岗位') （向下兼容容错）
    """
    if default_company is None:
        default_company = getattr(config, "COVER_DEFAULT_COMPANY", "360")
    if default_position is None:
        default_position = getattr(config, "COVER_DEFAULT_POSITION", "法务专员")

    basename = os.path.splitext(os.path.basename(video_path))[0]
    if basename.startswith("AutoVideo_"):
        basename = basename[len("AutoVideo_"):]

    # 1. 优先提取开头的日期前缀（例如 9.19-、09.19-、9-19-、9月19日-、2026.9.19- 等）
    date_regex = re.compile(r'^(?:(\d{4})[.\-_/年])?0?([1-9]|1[0-2])[.\-_/月]0?([1-9]|[12]\d|3[01])(?:日|号)?(?:[-_\s]+|$)')
    date_match = date_regex.match(basename)
    if date_match:
        m_month = int(date_match.group(2))
        m_day = int(date_match.group(3))
        date_str = f"{m_month}.{m_day}"
        remaining = basename[date_match.end():]
    else:
        now = datetime.now()
        date_str = f"{now.month}.{now.day}"
        remaining = basename

    # 2. 按下划线、减号分词
    tokens = [t.strip() for t in re.split(r'[-_]+', remaining) if t.strip()]

    recruit_type = "校招"
    category = "法学"
    company = default_company
    position = default_position

    # 3. 按照分段解析：招聘类型-分类-公司-岗位
    if len(tokens) >= 4:
        # 第一段：校招/社招
        if "社招" in tokens[0]:
            recruit_type = "社招"
        else:
            recruit_type = "校招"

        # 第二段：物流/法学
        if "物流" in tokens[1]:
            category = "物流"
        else:
            category = "法学"

        company = tokens[2]
        position = "-".join(tokens[3:])  # 剩余部分作为岗位名

    elif len(tokens) == 3:
        # 3 段情况兼容，如：校招-360-法务专员 或 社招-物流-仓管
        if "社招" in tokens[0]:
            recruit_type = "社招"
        elif "校招" in tokens[0]:
            recruit_type = "校招"

        if "物流" in tokens[1]:
            category = "物流"
            company = tokens[2]
        elif "法学" in tokens[1]:
            category = "法学"
            company = tokens[2]
        else:
            company = tokens[1]
            position = tokens[2]

    elif len(tokens) == 2:
        # 2 段情况兼容，如：360_法务专员
        company = tokens[0]
        position = tokens[1]
        if "社招" in remaining:
            recruit_type = "社招"
        if "物流" in remaining:
            category = "物流"

    else:
        # 1 段或默认命名（如 VID_xxx）
        if "社招" in remaining:
            recruit_type = "社招"
        if "物流" in remaining:
            category = "物流"

    # 规范化岗位修饰：自动补齐“新开...岗位”
    if not position.startswith("新开"):
        position = f"新开{position}"
    if not position.endswith("岗位"):
        position = f"{position}岗位"

    return date_str, recruit_type, category, company, position

# 兼容旧调用名
def parse_video_filename(video_path, default_company=None, default_position=None):
    _, _, _, comp, pos = parse_video_meta(video_path, default_company, default_position)
    return comp, pos

def extract_background_frame(video_path, target_w=1080, target_h=1440, timestamp_sec=1.0, log_func=print):
    """
    使用 FFmpeg 从原视频中提取指定时间戳的高清帧，并等比缩放、居中裁剪铺满 3:4 (target_w x target_h) 画布。
    """
    temp_frame_path = os.path.join(tempfile.gettempdir(), f"cover_bg_{os.getpid()}_{int(timestamp_sec*10)}.jpg")
    if os.path.exists(temp_frame_path):
        try:
            os.remove(temp_frame_path)
        except Exception:
            pass

    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{timestamp_sec:.2f}",
        "-i", video_path,
        "-vframes", "1",
        "-q:v", "2",
        temp_frame_path
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
        log_func(f"[Cover] FFmpeg 截帧失败: {err}")
        return Image.new("RGB", (target_w, target_h), (240, 240, 240))

    try:
        with Image.open(temp_frame_path) as raw_img:
            img = raw_img.convert("RGB")
            
            # 等比缩放铺满目标尺寸
            scale = max(target_w / img.width, target_h / img.height)
            new_w = int(img.width * scale)
            new_h = int(img.height * scale)
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            # 居中裁剪到 target_w x target_h
            left = (new_w - target_w) // 2
            top = (new_h - target_h) // 2
            cropped = resized.crop((left, top, left + target_w, top + target_h))
            return cropped
    finally:
        if os.path.exists(temp_frame_path):
            try:
                os.remove(temp_frame_path)
            except Exception:
                pass

def draw_text_with_stroke(draw, text, font, center_x, center_y, fill_color, stroke_color, stroke_width=10):
    """
    在指定中心坐标绘制带粗描边的文字。
    """
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = center_x - w // 2 - bbox[0]
    y = center_y - h // 2 - bbox[1]

    draw.text(
        (x, y),
        text,
        font=font,
        fill=fill_color,
        stroke_width=stroke_width,
        stroke_fill=stroke_color
    )
    return y + h

def draw_badge_text(draw, text, font, center_x, center_y, bg_color, text_color, pad_x=45, pad_y=20, radius=24):
    """
    绘制带有圆角矩形背景卡片的醒目大字（如公司名、岗位名）。
    """
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    box_w = text_w + pad_x * 2
    box_h = text_h + pad_y * 2
    x0 = center_x - box_w // 2
    y0 = center_y - box_h // 2
    x1 = x0 + box_w
    y1 = y0 + box_h

    # 绘制圆角底卡
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=bg_color)

    # 居中绘制文本
    tx = center_x - text_w // 2 - bbox[0]
    ty = center_y - text_h // 2 - bbox[1]
    draw.text((tx, ty), text, font=font, fill=text_color)
    return y1

def generate_cover_image(
    video_path,
    output_cover_path,
    company=None,
    position=None,
    recruit_type=None,
    category=None,
    date_str=None,
    background_image=None,
    log_func=print
):
    """
    全自动生成小红书 3:4 独立爆款口播封面：
    1. 顶部标题：若 recruit_type 为“社招”则显示为“社招”，否则显示“27届秋招”
    2. 公司名卡片（黄底黑字圆角卡片）
    3. 岗位名卡片（砖红底白字圆角卡片）
    4. 日期（黄字粗黑边：如 9.16）
    5. 底部固定语（白字细黑边：投递链接，进裙自取）
    """
    target_w = int(getattr(config, "CANVAS_WIDTH", 1080))
    target_h = int(getattr(config, "CANVAS_HEIGHT", 1440))

    # 1. 智能解析元数据
    p_date, p_recruit, p_cat, p_comp, p_pos = parse_video_meta(video_path)
    if not date_str:
        date_str = p_date
    if not recruit_type:
        recruit_type = p_recruit
    if not category:
        category = p_cat
    if not company:
        company = p_comp
    if not position:
        position = p_pos

    # 2. 动态确定顶部标题
    if recruit_type == "社招":
        top_title = "社招"
        top_font_size = 110 # 社招只有两个字，稍微饱满一些
    else:
        top_title = getattr(config, "COVER_TOP_TITLE", "27届秋招")
        top_font_size = 95

    # 3. 确定日期兜底
    if not date_str:
        now = datetime.now()
        date_str = f"{now.month}.{now.day}"

    bottom_text = getattr(config, "COVER_BOTTOM_TEXT", "投递链接，进裙自取")
    font_path = getattr(config, "COVER_FONT_PATH", r"C:\Windows\Fonts\msyhbd.ttc")
    if not os.path.exists(font_path):
        font_path = r"C:\Windows\Fonts\simhei.ttf"

    log_func(f"[Cover] 开始自动生成 3:4 封面大图 (类型: '{recruit_type}', 标题: '{top_title}', 公司: '{company}', 岗位: '{position}', 日期: '{date_str}')...")

    # 4. 准备背景图
    if background_image:
        bg_img = background_image.copy()
        if bg_img.size != (target_w, target_h):
            bg_img = bg_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
    else:
        bg_img = extract_background_frame(video_path, target_w=target_w, target_h=target_h, timestamp_sec=1.0, log_func=log_func)
    
    draw = ImageDraw.Draw(bg_img)

    def get_fitting_badge_font(text, font_path, desired_size, max_box_width, pad_x, min_size=48):
        """
        根据最大允许底卡宽度动态寻找最大不换行字号，保证字体尽可能大且 100% 单行不溢出。
        """
        curr_size = desired_size
        while curr_size >= min_size:
            f = ImageFont.truetype(font_path, curr_size)
            bbox = draw.textbbox((0, 0), text, font=f)
            t_w = bbox[2] - bbox[0]
            if t_w + pad_x * 2 <= max_box_width:
                return f, curr_size
            curr_size -= 2
        return ImageFont.truetype(font_path, min_size), min_size

    # 5. 加载字体（公司与岗位字体明显加大，并由算法严格锁定单行绝不折行）
    max_badge_width = target_w - 80 # 最大允许底卡宽度 1000px，两边留 40px 安全边距
    
    date_font_size = int(getattr(config, "COVER_DATE_FONT_SIZE", 112))
    date_stroke_width = int(getattr(config, "COVER_DATE_STROKE_WIDTH", 10))

    font_top = ImageFont.truetype(font_path, top_font_size)
    font_company, _ = get_fitting_badge_font(company, font_path, desired_size=128, max_box_width=max_badge_width, pad_x=60) # 公司名放大至 128
    font_position, _ = get_fitting_badge_font(position, font_path, desired_size=98, max_box_width=max_badge_width, pad_x=50) # 岗位名保持 98
    font_date = ImageFont.truetype(font_path, date_font_size)
    font_bottom = ImageFont.truetype(font_path, 45) # 底部行动语缩小至 45 磅

    center_x = target_w // 2

    color_yellow = (255, 222, 20)      # 亮黄色
    color_black = (0, 0, 0)            # 纯黑
    color_white = (255, 255, 255)      # 纯白
    color_brick_red = (182, 72, 58)    # 砖红/深橘红

    # ① 顶部标题（社招 或 27届秋招）
    draw_text_with_stroke(
        draw,
        text=top_title,
        font=font_top,
        center_x=center_x,
        center_y=74,
        fill_color=color_yellow,
        stroke_color=color_black,
        stroke_width=10
    )

    # ② 公司名卡片（亮黄色背景底卡 + 黑色粗字，放大至 128 磅）
    draw_badge_text(
        draw,
        text=company,
        font=font_company,
        center_x=center_x,
        center_y=324,
        bg_color=color_yellow,
        text_color=color_black,
        pad_x=60,
        pad_y=22,
        radius=28
    )

    # ③ 岗位名卡片（砖红背景底卡 + 白色粗字，严格单行）
    draw_badge_text(
        draw,
        text=position,
        font=font_position,
        center_x=center_x,
        center_y=540,
        bg_color=color_brick_red,
        text_color=color_white,
        pad_x=50,
        pad_y=24,
        radius=28
    )

    # ④ 日期（亮黄色 + 纯黑超粗描边：9.16）
    draw_text_with_stroke(
        draw,
        text=date_str,
        font=font_date,
        center_x=center_x,
        center_y=875,
        fill_color=color_yellow,
        stroke_color=color_black,
        stroke_width=date_stroke_width
    )

    # ⑤ 底部常驻行动语（白色粗字 + 黑色细描边：缩小至 45 磅，精致不抢戏）
    draw_text_with_stroke(
        draw,
        text=bottom_text,
        font=font_bottom,
        center_x=center_x,
        center_y=1224,
        fill_color=color_white,
        stroke_color=color_black,
        stroke_width=3
    )

    # 保存封面文件
    os.makedirs(os.path.dirname(os.path.abspath(output_cover_path)), exist_ok=True)
    bg_img.save(output_cover_path, quality=95)
    log_func(f"[Cover] 3:4 高清独立封面图生成完毕 ➔ {output_cover_path}")
    return output_cover_path
