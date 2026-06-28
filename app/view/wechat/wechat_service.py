# coding: utf-8
"""微信公众号业务层 —— 账号管理、模板加载、历史记录、登录"""
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from playwright.async_api import async_playwright

from ...common.setting import DATA_DIR, launch_browser

WECHAT_URL = "https://mp.weixin.qq.com/"
ACCOUNTS_DIR = DATA_DIR / "accounts" / "wechat"
WECHAT_ACCOUNT_PRESETS = ["物流", "财会", "法学"]
TEMPLATE_CATEGORIES = ["校招", "实习", "社招"]


# ---- 账号管理 ----

def get_accounts() -> list[str]:
    """返回预置账号和所有已登录账号名称列表"""
    ACCOUNTS_DIR.mkdir(parents=True, exist_ok=True)
    logged_accounts = sorted(
        d.name for d in ACCOUNTS_DIR.iterdir()
        if d.is_dir() and (d / "session.json").exists()
    )
    return list(dict.fromkeys([*WECHAT_ACCOUNT_PRESETS, *logged_accounts]))


def account_exists(name: str) -> bool:
    return (ACCOUNTS_DIR / name / "session.json").exists()


def get_account_dir(name: str) -> Path:
    return ACCOUNTS_DIR / name


# ---- 模板 ----

def get_today_templates_dir(account_name: str) -> Path:
    today = datetime.now().strftime("%#m.%d") if sys.platform == "win32" \
        else datetime.now().strftime("%-m.%d")
    return ACCOUNTS_DIR / account_name / "templates" / today


def get_next_day_templates_dir(current_dir: Path) -> Path:
    """基于当前模板目录计算下一天的目录路径"""
    from datetime import timedelta
    today = datetime.now().date()
    templates_root = current_dir.parent

    # 尝试从当前目录名解析日期
    try:
        parts = current_dir.name.split(".")
        month, day = int(parts[0]), int(parts[1])
        base_date = today.replace(month=month, day=day)
    except (ValueError, IndexError):
        base_date = today

    next_day = base_date + timedelta(days=1)
    fmt = f"{next_day.month}.{next_day.day:02d}"
    return templates_root / fmt


def load_templates(templates_dir: Path,
                   category: str = "校招") -> list[tuple[str, dict]]:
    """按文件名排序加载 category 子文件夹下的 1.json, 2.json, ... 模板"""
    cat_dir = templates_dir / category
    if not cat_dir.exists():
        return []
    templates = []
    for f in sorted(cat_dir.glob("*.json")):
        if f.stem.isdigit():
            data = json.loads(f.read_text(encoding="utf-8"))
            templates.append((f.name, data))
    return templates


def load_date_range_templates(
    account_name: str,
    start_date,
    end_date,
    category: str,
) -> list[tuple]:
    """加载日期范围内多个文件夹的模板。

    Parameters
    ----------
    category : "校招"、"实习" 或 "社招"

    Returns
    -------
    list of (date, [(filename, data), ...])
    跳过不存在的文件夹或文件。
    """
    from datetime import timedelta
    templates_root = ACCOUNTS_DIR / account_name / "templates"
    results = []
    current = start_date
    while current <= end_date:
        folder_name = f"{current.month}.{current.day:02d}"
        cat_dir = templates_root / folder_name / category
        day_templates = []
        if cat_dir.exists():
            for f in sorted(cat_dir.glob("*.json")):
                if f.stem.isdigit():
                    try:
                        data = json.loads(
                            f.read_text(encoding="utf-8"))
                        day_templates.append((f.name, data))
                    except (json.JSONDecodeError, ValueError):
                        pass
        if day_templates:
            results.append((current, day_templates))
        current += timedelta(days=1)
    return results


def compute_month_and_week(end_date) -> tuple[int, int]:
    """根据结束日期计算月数和月内周数。"""
    month = end_date.month
    week = (end_date.day - 1) // 7 + 1
    return month, week


TEMPLATE_SKELETON = {
    "{{公司简称}}": "",
    "{{岗位名称}}": "",
    "{{亮点}}": "",
    "{{公司名称}}": "",
    "{{公司具体简介}}": "",
    "{{工作地点}}": "",
    "{{岗位职责内容}}": "",
    "{{岗位需求内容}}": "",
    "{{小程序链接}}": "",
}


def save_template(templates_dir: Path, data: dict,
                  category: str = "校招") -> tuple[bool, str]:
    """保存模板到 category 子文件夹的下一个可用编号"""
    cat_dir = templates_dir / category
    cat_dir.mkdir(parents=True, exist_ok=True)
    existing = [int(f.stem) for f in cat_dir.glob("*.json")
                if f.stem.isdigit()]
    next_num = max(existing, default=0) + 1
    path = cat_dir / f"{next_num}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return True, f"已保存为 {category}/{next_num}.json"


# 模板所有合法 key 的"裸名"（去掉 {{}} 后的名称）
_REQUIRED_KEYS = [k.strip("{}") for k in TEMPLATE_SKELETON]


def repair_template_json(text: str) -> tuple[dict | None, list[str]]:
    """尝试修复并校验模板 JSON，返回 (data | None, 修复/错误消息列表)"""
    messages: list[str] = []

    # --- 1. 提取 JSON 块：去掉 markdown 代码块包裹 ---
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if m:
        text = m.group(1)
        messages.append("已自动去除代码块包裹")

    text = text.strip()

    # --- 2. 常见语法修复 ---
    # 去掉末尾多余逗号（如 ,"  } ）
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    if fixed != text:
        messages.append("已修复末尾多余逗号")
        text = fixed

    # 中文逗号 → 英文逗号（仅替换引号外面的，即 JSON 分隔符位置）
    fixed = re.sub(r'(?<=[\"\}])\s*\uff0c\s*(?=[\"\{])', ',', text)
    if fixed != text:
        messages.append("已修复中文逗号分隔符")
        text = fixed

    # 中文引号 → 英文引号
    for ch_open, ch_close, en in [('\u201c', '\u201d', '"'),
                                   ('\u2018', '\u2019', "'")]:
        if ch_open in text or ch_close in text:
            text = text.replace(ch_open, en).replace(ch_close, en)
            messages.append("已修复中文引号")
            break

    # 字符串值内的真实换行 → \n（AI 生成的多行内容常见问题）
    lines = text.split('\n')
    merged = []
    i = 0
    newline_fixed = False
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^(\s*".*?"\s*:\s*")(.*)', line)
        if m:
            rest = m.group(2)
            # 值在本行闭合（以 " 或 ", 结尾）
            if re.search(r'(?<!\\)"\s*,?\s*$', rest):
                merged.append(line)
                i += 1
            else:
                # 多行值：收集后续行直到闭合
                parts = [line.rstrip()]
                i += 1
                while i < len(lines):
                    next_stripped = lines[i].strip()
                    if re.search(r'(?<!\\)"\s*,?\s*$', next_stripped):
                        parts.append(next_stripped)
                        i += 1
                        newline_fixed = True
                        break
                    elif next_stripped in ('{', '}', '},' , ']', '],'):
                        break
                    else:
                        parts.append(next_stripped)
                        i += 1
                merged.append('\\n'.join(parts))
        else:
            merged.append(line)
            i += 1
    if newline_fixed:
        text = '\n'.join(merged)
        messages.append("已修复值中的换行符")

    # 值内未转义的双引号：逐行检测 "key": "...未转义"引号"..." 并修复
    lines = text.split('\n')
    fixed_lines = []
    quote_fixed = False
    for line in lines:
        m = re.match(r'^(\s*"[^"]*"\s*:\s*")(.*)("\s*,?\s*)$', line)
        if m:
            prefix, value, suffix = m.groups()
            escaped = value.replace('\\"', '\x00')
            escaped = escaped.replace('"', '\\"')
            escaped = escaped.replace('\x00', '\\"')
            if escaped != value:
                line = prefix + escaped + suffix
                quote_fixed = True
        fixed_lines.append(line)
    if quote_fixed:
        text = '\n'.join(fixed_lines)
        messages.append("已修复值中未转义的双引号")

    # --- 3. 尝试解析 ---
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, [f"JSON 解析失败: {e}"]

    if not isinstance(data, dict):
        return None, ["JSON 顶层必须是对象 {{}}"]

    # --- 4. key 修复：如果 key 缺少 {{}} 则自动补上 ---
    new_data = {}
    for k, v in data.items():
        bare = k.strip("{}")
        if bare in _REQUIRED_KEYS and not (k.startswith("{{") and k.endswith("}}")):
            new_key = "{{" + bare + "}}"
            messages.append(f"已修复 key: {k} → {new_key}")
            new_data[new_key] = v
        else:
            new_data[k] = v
    data = new_data

    # --- 5. 检查缺少的必填 key ---
    existing_bare = {k.strip("{}"): k for k in data}
    missing = [f"{{{{{name}}}}}" for name in _REQUIRED_KEYS
               if name not in existing_bare]
    if missing:
        messages.append(f"缺少字段: {', '.join(missing)}")
        return None, messages

    # --- 6. 检查多余的 key ---
    extra = [k for k in data if k.strip("{}") not in _REQUIRED_KEYS]
    if extra:
        messages.append(f"多余字段已忽略: {', '.join(extra)}")
        data = {k: v for k, v in data.items()
                if k.strip("{}") in _REQUIRED_KEYS}

    return data, messages


PROMPT_TEXT = """角色设定：你是一个高效的数据处理助手，擅长从非结构化文本中提取结构化信息并生成 JSON 文件。

任务描述： 我会给你一段招聘文本（可能包含表格数据、公司简介图片或文本或小程序链接）。请参考 示例模板.json（注意不要遗漏{{}},然后不要更改小程序链接包括空格什么的都不要添加 小程序链接给你是什么样的，放到模板里就需要是什么样的他是带有#的 比如 #小程序://塔塔网申/yEX2pAjxWkauDRG）
{
  "{{公司简称}}": "",
  "{{岗位名称}}": "",
  "{{亮点}}": "",
  "{{公司名称}}": "",
  "{{公司具体简介}}": "",
  "{{工作地点}}": "",
  "{{岗位职责内容}}": "",
  "{{岗位需求内容}}": "",
  "{{小程序链接}}": ""
的结构，新建并填写 JSON 内容。

操作规则：
如果提供的是英文内容，请自动翻译并整理为易读的中文。
提取字段包括：{{公司简称}}、{{岗位名称}}、{{亮点}}、{{公司名称}}、{{公司具体简介}}、{{工作地点}}、{{岗位职责内容}}、{{岗位需求内容}}、{{小程序链接}}。
亮点提取：根据文中信息总结，如"央企、国企、知名互联网、转正机会、高薪、500强"等，用中文全角感叹号（！）分隔。
简介提取：如果没有现成简介，请根据公司名简单生成一段（约100字），涵盖行业地位和成立背景。公司具体简介开头如果重复了公司全称，自动删掉开头的公司名称，直接从业务 / 背景开始写。
格式要求：职责和需求内容需保留原有的分点序号，并使用 \\n 进行换行一定要记得用 \\n ，如果没有则使用一个空格。
简洁原则：没有提到的字段留空或不填写，不要添加无关的解释，用代码块包裹，不要加其他说明。"""


# ---- 历史记录 ----

def save_history(account_dir: Path, template_name: str,
                 replacements: dict, status: str, error: str = "",
                 max_records: int = 200):
    history_path = account_dir / "history.json"
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            history = []
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "template": template_name,
        "replacements": replacements,
        "status": status,
        "error": error,
    })
    history = history[-max_records:]
    history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def load_history(account_dir: Path) -> list[dict]:
    history_path = account_dir / "history.json"
    if not history_path.exists():
        return []
    try:
        return json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []


def save_history_list(account_dir: Path, history: list[dict]):
    """直接保存整个历史记录列表（用于删除操作后回写）"""
    history_path = account_dir / "history.json"
    history_path.write_text(
        json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- Playwright: 登录线程 ----

class WechatLoginThread(QThread):
    loginSuccess = Signal(str)
    loginFailed = Signal(str)

    def __init__(self, account_name: str, parent=None):
        super().__init__(parent)
        self.account_name = account_name
        self.account_dir = ACCOUNTS_DIR / account_name
        self.session_path = self.account_dir / "session.json"

    def run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._login())
        except Exception as e:
            self.loginFailed.emit(str(e))
        finally:
            loop.close()

    async def _login(self):
        self.account_dir.mkdir(parents=True, exist_ok=True)
        (self.account_dir / "templates").mkdir(exist_ok=True)

        async with async_playwright() as p:
            browser = await launch_browser(p)
            context = await browser.new_context(no_viewport=True)
            page = await context.new_page()
            try:
                await page.goto(WECHAT_URL)
            except Exception:
                pass

            max_wait = 180
            elapsed = 0
            while elapsed < max_wait:
                try:
                    if "cgi-bin/home" in page.url or "cgi-bin/frame" in page.url:
                        break
                except Exception:
                    pass
                await asyncio.sleep(1)
                elapsed += 1
            else:
                await browser.close()
                self.loginFailed.emit("登录超时，请重试")
                return

            await context.storage_state(path=str(self.session_path))
            await browser.close()
            self.loginSuccess.emit(self.account_name)
