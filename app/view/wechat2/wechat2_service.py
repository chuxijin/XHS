# coding: utf-8
"""微信公众号增强工具业务层。"""
import asyncio
import base64
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from Crypto.Cipher import AES

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
from playwright.async_api import async_playwright

from ...common.setting import DATA_DIR, launch_browser

IMAGE_DOWNLOAD_DIR = DATA_DIR / "downloads" / "wechat_images"
MATERIAL_ACCOUNT_CONFIG = DATA_DIR / "wechat2_material_account.json"
WECHAT_MEDIA_API_BASE_URL = "https://admin.yzxj.vip/api/v1/wechat/media"
WECHAT_MEDIA_SECRET_KEY = "PxeCKsYCVMEItOMnluEkOFdG0/IDbOD4Vgws4hwWNBQ="
WECHAT2_REQUIRED_FIELD_GROUPS = (
    ("{{标题}}",),
    ("{{基本介绍}}", "{{简介}}"),
    ("{{话题标签}}", "{{话题}}"),
    ("{{夸克链接}}", "{{夸克连接}}"),
    ("{{百度链接}}",),
    ("{{图片链接}}",),
)


def load_publish_template(template_path: Path) -> tuple[dict, list[str]]:
    """读取公众号2模板，并返回缺失字段提示。"""
    try:
        data = json.loads(template_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"模板 JSON 读取失败：{error}") from error
    if not isinstance(data, dict):
        raise ValueError("模板根节点必须是 JSON 对象")
    missing = []
    for group in WECHAT2_REQUIRED_FIELD_GROUPS:
        if not any(field in data for field in group):
            missing.append(group[0])
    return data, missing


def load_publish_templates(template_dir: Path) -> tuple[list[Path], dict[str, list[str]]]:
    """加载模板目录中的 JSON 文件，返回文件列表和字段缺失结果。"""
    if not template_dir.exists() or not template_dir.is_dir():
        raise ValueError("模板路径不是有效目录")
    paths = sorted(
        path for path in template_dir.rglob("*.json")
        if path.is_file()
    )
    if not paths:
        raise ValueError("模板目录中没有 JSON 文件")
    missing_by_file = {}
    for path in paths:
        _, missing = load_publish_template(path)
        if missing:
            missing_by_file[path.name] = missing
    return paths, missing_by_file


def load_material_account() -> dict:
    if not MATERIAL_ACCOUNT_CONFIG.exists():
        return {"name": "", "appid": "", "appsecret": ""}
    try:
        data = json.loads(MATERIAL_ACCOUNT_CONFIG.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"name": "", "appid": "", "appsecret": ""}
    return {
        "name": data.get("name", ""),
        "appid": data.get("appid", ""),
        "appsecret": data.get("appsecret", ""),
    }


def save_material_account(data: dict) -> None:
    MATERIAL_ACCOUNT_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": data.get("name", "").strip(),
        "appid": data.get("appid", "").strip(),
        "appsecret": data.get("appsecret", "").strip(),
    }
    MATERIAL_ACCOUNT_CONFIG.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _response_data(response: httpx.Response) -> dict:
    try:
        result = response.json()
    except ValueError as error:
        raise RuntimeError(f"服务器返回了无效响应：HTTP {response.status_code}") from error
    if response.is_error:
        detail = result.get("detail") or result.get("msg") or response.text[:200]
        raise RuntimeError(f"服务器请求失败：HTTP {response.status_code} {detail}")
    if result.get("code") != 200:
        raise RuntimeError(result.get("msg") or "服务器请求失败")
    return result.get("data") or {}


def _encrypt_credentials(appid: str, appsecret: str) -> str:
    payload = json.dumps({
        "appid": appid.strip(),
        "appsecret": appsecret.strip(),
        "iat": int(time.time()),
    }).encode("utf-8")
    key = base64.b64decode(WECHAT_MEDIA_SECRET_KEY)
    nonce = os.urandom(12)
    cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(payload)
    return base64.b64encode(nonce + ciphertext + tag).decode("utf-8")


def test_material_server(appid: str, appsecret: str, timeout: int = 15) -> None:
    response = httpx.post(
        f"{WECHAT_MEDIA_API_BASE_URL}/test",
        data={"payload": _encrypt_credentials(appid, appsecret)},
        timeout=timeout,
    )
    _response_data(response)


def upload_article_image(appid: str, appsecret: str, image_path: Path,
                         timeout: int = 60) -> str:
    payload = _encrypt_credentials(appid, appsecret)
    with image_path.open("rb") as image_file:
        response = httpx.post(
            f"{WECHAT_MEDIA_API_BASE_URL}/upload",
            files={
                "file": (image_path.name, image_file),
                "payload": (None, payload),
            },
            timeout=timeout,
        )
    url = _response_data(response).get("url")
    if not url:
        raise RuntimeError("服务器未返回微信图片地址")
    return str(url)


def list_download_folders() -> list[Path]:
    if not IMAGE_DOWNLOAD_DIR.exists():
        return []
    return sorted(
        [path for path in IMAGE_DOWNLOAD_DIR.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def list_uploadable_images(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return [
        path for path in sorted(folder.iterdir())
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    ]


def list_crop_images(folder: Path) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []
    return [
        path for path in sorted(folder.iterdir())
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
    ]


def crop_image_margins(image_path: Path, top: int, bottom: int,
                       left: int, right: int) -> tuple[int, int, int, int]:
    """按边距（像素）裁剪单张图片并直接覆盖原图。

    返回实际裁剪区域 (x, y, width, height)；失败时抛出异常。
    """
    image = QImage(str(image_path))
    if image.isNull():
        raise ValueError(f"无法读取图片：{image_path.name}")
    width, height = image.width(), image.height()
    if top + bottom >= height or left + right >= width:
        raise ValueError(
            f"{image_path.name} 尺寸 {width}x{height}，边距过大，已跳过")
    x, y = left, top
    crop_w, crop_h = width - left - right, height - top - bottom
    cropped = image.copy(x, y, crop_w, crop_h)
    if cropped.isNull():
        raise ValueError(f"{image_path.name} 裁剪失败")
    if not cropped.save(str(image_path)):
        raise ValueError(f"{image_path.name} 保存失败（格式不支持覆盖）")
    return x, y, crop_w, crop_h


class MaterialAccountTestThread(QThread):
    testSuccess = Signal(str)
    testFailed = Signal(str)

    def __init__(self, appid: str, appsecret: str, parent=None):
        super().__init__(parent)
        self.appid = appid.strip()
        self.appsecret = appsecret.strip()

    def run(self):
        try:
            if not self.appid or not self.appsecret:
                raise ValueError("请填写 AppID 和 AppSecret")
            test_material_server(self.appid, self.appsecret)
            self.testSuccess.emit("admin.yzxj.vip")
        except Exception as e:
            self.testFailed.emit(str(e))


class MaterialImageUploadThread(QThread):
    logMessage = Signal(str)
    uploadSuccess = Signal(str, int)
    uploadFailed = Signal(str)

    def __init__(self, folder: Path, count: int | None = None, parent=None):
        super().__init__(parent)
        self.folder = folder
        self.count = count

    def run(self):
        try:
            output, uploaded = self._upload_images()
            self.uploadSuccess.emit(str(output), uploaded)
        except Exception as e:
            self.uploadFailed.emit(str(e))

    def _upload_images(self) -> tuple[Path, int]:
        account = load_material_account()
        appid = account.get("appid", "").strip()
        appsecret = account.get("appsecret", "").strip()
        if not appid or not appsecret:
            raise ValueError("请先配置素材账号 AppID 和 AppSecret")

        images = list_uploadable_images(self.folder)
        if self.count is not None:
            images = images[:self.count]
        if not images:
            raise RuntimeError("选择的文件夹里没有可上传的 jpg/png 图片")

        urls = []
        self.logMessage.emit(
            f"[素材中转] 开始通过 admin.yzxj.vip 上传 {len(images)} 张图片..."
        )
        for image_path in images:
            try:
                url = upload_article_image(appid, appsecret, image_path)
                urls.append(url)
                self.logMessage.emit(f"[素材中转] 已上传 {image_path.name}")
            except Exception as e:
                self.logMessage.emit(
                    f"[素材中转] {image_path.name} 上传失败：{e}")

        if not urls:
            raise RuntimeError("图片均上传失败")

        output = self.folder / "upload_urls.txt"
        output.write_text("\n".join(urls) + "\n", encoding="utf-8")
        return output, len(urls)


def sanitize_filename(name: str, fallback: str = "wechat_article") -> str:
    """清理 Windows/macOS/Linux 都不适合出现在文件名里的字符。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', "", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:80] or fallback


def normalize_article_text(text: str) -> str:
    """保留段落结构，去除浏览器提取出的多余空白。"""
    paragraphs = []
    for paragraph in text.splitlines():
        cleaned = re.sub(r"\s+", " ", paragraph).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return "\n\n".join(paragraphs)


def guess_image_ext(url: str, content_type: str = "") -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    fmt = (query.get("wx_fmt") or query.get("tp") or [""])[0].lower()
    fmt = fmt.replace("jpeg", "jpg")
    if fmt in {"jpg", "png", "gif", "webp", "bmp"}:
        return fmt

    suffix = Path(unquote(parsed.path)).suffix.lower().lstrip(".")
    if suffix in {"jpg", "jpeg", "png", "gif", "webp", "bmp"}:
        return "jpg" if suffix == "jpeg" else suffix

    content_type = content_type.lower()
    if "png" in content_type:
        return "png"
    if "gif" in content_type:
        return "gif"
    if "webp" in content_type:
        return "webp"
    return "jpg"


class WechatImageDownloadThread(QThread):
    logMessage = Signal(str)
    downloadSuccess = Signal(str, int)
    downloadFailed = Signal(str)

    def __init__(self, article_url: str, max_count: int = 0,
                 crop_bottom: int = 0, parent=None):
        super().__init__(parent)
        self.article_url = article_url.strip()
        self.max_count = max_count
        self.crop_bottom = crop_bottom

    def run(self):
        try:
            save_dir, count = asyncio.run(
                self._download_article_images(
                    self.article_url, self.max_count, self.crop_bottom)
            )
            self.downloadSuccess.emit(str(save_dir), count)
        except Exception as e:
            self.downloadFailed.emit(str(e))

    async def _download_article_images(self, article_url: str, max_count: int = 0,
                                       crop_bottom: int = 0) -> tuple[Path, int]:
        if not article_url:
            raise ValueError("请输入公众号文章链接")
        if "mp.weixin.qq.com" not in article_url:
            raise ValueError("请输入 mp.weixin.qq.com 的公众号文章链接")

        self.logMessage.emit("启动浏览器，打开公众号文章...")
        async with async_playwright() as p:
            browser = await launch_browser(p, headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
            )
            page = await context.new_page()
            try:
                await page.goto(article_url, wait_until="domcontentloaded",
                                timeout=45000)
                await page.wait_for_timeout(1800)

                title = await self._get_article_title(page)
                content = await self._get_article_content(page)
                image_urls = await self._get_article_image_urls(page)

                save_dir = IMAGE_DOWNLOAD_DIR / sanitize_filename(title)
                save_dir.mkdir(parents=True, exist_ok=True)
                self.logMessage.emit(f"文章标题：{title}")
                self._save_article_text(save_dir, title, content)
                self.logMessage.emit("已保存正文：article.txt")
                if image_urls:
                    if max_count > 0 and len(image_urls) > max_count:
                        self.logMessage.emit(
                            f"发现 {len(image_urls)} 张图片，将限制仅下载前 {max_count} 张..."
                        )
                    else:
                        self.logMessage.emit(
                            f"发现 {len(image_urls)} 张图片，开始下载..."
                        )
                else:
                    self.logMessage.emit("正文中没有图片，已仅保存标题和文字内容")

                saved_count = 0
                seen: set[str] = set()
                for index, image_url in enumerate(image_urls, start=1):
                    if max_count > 0 and saved_count >= max_count:
                        break
                    if image_url in seen:
                        continue
                    seen.add(image_url)
                    ok = await self._download_one(
                        page, image_url, article_url, save_dir, index,
                        crop_bottom)
                    if ok:
                        saved_count += 1

                return save_dir, saved_count
            finally:
                await context.close()
                await browser.close()

    async def _get_article_title(self, page) -> str:
        title = ""
        try:
            title = await page.locator("#activity-name").inner_text(
                timeout=2500)
        except Exception:
            pass
        if not title:
            title = await page.title()
        return " ".join(title.split())[:120] or "wechat_article"

    async def _get_article_content(self, page) -> str:
        try:
            content = await page.locator("#js_content").inner_text(timeout=2500)
        except Exception:
            content = ""
        return normalize_article_text(content)

    @staticmethod
    def _save_article_text(save_dir: Path, title: str, content: str) -> None:
        body = content or "（未提取到可见正文文字）"
        (save_dir / "article.txt").write_text(
            f"标题：{title}\n\n正文：\n{body}\n",
            encoding="utf-8",
        )

    async def _get_article_image_urls(self, page) -> list[str]:
        urls = await page.evaluate(
            """() => {
                const root = document.querySelector('#js_content') || document;
                return Array.from(root.querySelectorAll('img'))
                    .map(img => img.getAttribute('data-src')
                        || img.getAttribute('data-backsrc')
                        || img.getAttribute('src')
                        || img.currentSrc
                        || '')
                    .map(src => src.trim())
                    .filter(src => src
                        && !src.startsWith('data:')
                        && !src.startsWith('blob:')
                        && !src.includes('res.wx.qq.com')
                        && !src.includes('wx_fmt=svg'));
            }"""
        )
        normalized = []
        for url in urls:
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("http://"):
                url = "https://" + url[7:]
            if url not in normalized:
                normalized.append(url)
        return normalized

    async def _download_one(self, page, image_url: str, referer: str,
                            save_dir: Path, index: int,
                            crop_bottom: int = 0) -> bool:
        try:
            response = await page.request.get(
                image_url,
                headers={"Referer": referer},
                timeout=30000,
            )
            if not response.ok:
                self.logMessage.emit(f"[跳过] 第 {index} 张下载失败：HTTP {response.status}")
                return False
            body = await response.body()
            ext = guess_image_ext(image_url,
                                  response.headers.get("content-type", ""))
            filename = f"{index:02d}.{ext}"
            file_path = save_dir / filename
            file_path.write_bytes(body)

            if crop_bottom > 0:
                try:
                    crop_image_margins(file_path, 0, crop_bottom, 0, 0)
                    self.logMessage.emit(f"[自动裁底] {filename} 裁掉底部 {crop_bottom}px")
                except Exception as e:
                    self.logMessage.emit(f"[自动裁底] {filename} 失败：{e}")

            self.logMessage.emit(f"[完成] {filename}")
            return True
        except Exception as e:
            self.logMessage.emit(f"[跳过] 第 {index} 张下载失败：{e}")
            return False


class ImageCropThread(QThread):
    """按边距批量裁剪图片并直接覆盖原图。"""

    logMessage = Signal(str)
    cropSuccess = Signal(int, int, int)
    cropFailed = Signal(str)

    def __init__(self, target: Path | list[Path], top: int, bottom: int, left: int,
                 right: int, parent=None):
        super().__init__(parent)
        self.target = target
        self.top = top
        self.bottom = bottom
        self.left = left
        self.right = right

    def run(self):
        try:
            total, cropped, failed = self._crop_images()
            self.cropSuccess.emit(total, cropped, failed)
        except Exception as e:
            self.cropFailed.emit(str(e))

    def _crop_images(self) -> tuple[int, int, int]:
        if isinstance(self.target, (list, tuple)):
            images = [Path(p) for p in self.target if Path(p).is_file()]
            target_desc = f"{len(images)} 个文件"
        else:
            images = list_crop_images(Path(self.target))
            target_desc = f"文件夹：{self.target}"

        if not images:
            raise RuntimeError("没有可裁剪的图片")

        self.logMessage.emit(
            f"[快速裁剪] 目标：{target_desc}（共 {len(images)} 张）")
        self.logMessage.emit(
            f"[快速裁剪] 边距：上 {self.top} / 下 {self.bottom} / "
            f"左 {self.left} / 右 {self.right} px，直接覆盖原图")

        cropped, failed = 0, 0
        for image_path in images:
            try:
                x, y, w, h = crop_image_margins(
                    image_path, self.top, self.bottom, self.left, self.right)
                cropped += 1
                self.logMessage.emit(
                    f"[完成] {image_path.name} → {w}x{h}（裁掉 {x}/{y} 起）")
            except Exception as e:
                failed += 1
                self.logMessage.emit(f"[跳过] {e}")

        return len(images), cropped, failed
