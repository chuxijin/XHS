# coding: utf-8
"""小红书图文笔记的最小解析与下载逻辑。

代码依据 XHS-Downloader 的页面状态提取和图片地址生成方式整理，只保留
当前桌面端需要的链接解析、文案提取和图片下载，不包含 API 或服务端功能。
"""
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx
import yaml


LogFunc = Callable[[str], None]


class XhsNoteDownloader:
    """解析一篇小红书图文笔记并保存其图片。"""

    SHORT_LINK = re.compile(r"(?:https?://)?xhslink\.com/[^\s\"<>\\^`{|}\uff0c\u3002\uff1b\uff01\uff1f\u3001\u3010\u3011\u300a\u300b]+")
    NOTE_LINK = re.compile(
        r"(?:https?://)?(?:www\.)?(?:xiaohongshu\.com|rednote\.com)/(?:explore|discovery/item)/[^\s\"<>]+"
    )
    INITIAL_STATE = re.compile(
        r"<script[^>]*>\s*(window\.__INITIAL_STATE__\s*=.*?)(?:</script>)",
        re.IGNORECASE | re.DOTALL,
    )
    HEADERS = {
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 "
            "Safari/537.36 Edg/143.0.0.0"
        ),
        "referer": "https://www.xiaohongshu.com/",
    }

    def __init__(self, output_dir: Path, log: LogFunc | None = None):
        self.output_dir = output_dir
        self.log = log or (lambda _: None)

    async def download(self, raw_url: str) -> dict:
        async with httpx.AsyncClient(
            headers=self.HEADERS,
            timeout=20,
            follow_redirects=True,
        ) as client:
            note_url = await self._resolve_note_url(client, raw_url)
            self.log("正在读取小红书作品信息...")
            response = await client.get(note_url)
            response.raise_for_status()
            note = self._extract_note(response.text)
            if not note:
                raise RuntimeError("页面中未找到作品数据，链接可能失效或需要登录后访问")

            data = self._build_metadata(note, note_url)
            image_urls = self._extract_image_urls(note)
            if not image_urls:
                raise RuntimeError("该作品没有可下载的图片，当前仅支持图文作品")

            folder = self.output_dir / self._safe_filename(
                data["作品标题"] or data["作品ID"] or "xhs_note"
            )
            folder.mkdir(parents=True, exist_ok=True)
            self.log(f"开始下载 {len(image_urls)} 张图片...")
            for index, image_url in enumerate(image_urls, start=1):
                await self._download_image(client, image_url, folder, index)
            data["保存目录"] = str(folder)
            return data

    async def _resolve_note_url(self, client: httpx.AsyncClient, raw_url: str) -> str:
        short = self.SHORT_LINK.search(raw_url)
        if short:
            response = await client.get(self._with_scheme(short.group()))
            raw_url = str(response.url)
        note = self.NOTE_LINK.search(raw_url)
        if not note:
            raise ValueError("请输入有效的小红书作品链接")
        return self._with_scheme(note.group())

    @staticmethod
    def _with_scheme(url: str) -> str:
        return url if url.startswith("http") else f"https://{url}"

    def _extract_note(self, html: str) -> dict:
        matches = self.INITIAL_STATE.findall(html)
        for script in reversed(matches):
            try:
                initial_state = yaml.safe_load(
                    script.removeprefix("window.__INITIAL_STATE__=").rstrip(";")
                )
            except yaml.YAMLError:
                continue
            note = self._deep_get(initial_state, ("noteData", "data", "noteData"))
            if isinstance(note, dict):
                return note
            note_map = self._deep_get(initial_state, ("note", "noteDetailMap"))
            if isinstance(note_map, dict) and note_map:
                last_note = next(reversed(note_map.values()))
                if isinstance(last_note, dict):
                    return last_note.get("note") or last_note
        return {}

    def _build_metadata(self, note: dict, note_url: str) -> dict:
        tags = [
            item.get("name", "")
            for item in note.get("tagList") or []
            if isinstance(item, dict) and item.get("name")
        ]
        user = note.get("user") or {}
        return {
            "作品ID": str(note.get("noteId") or self._note_id(note_url)),
            "作品标题": str(note.get("title") or ""),
            "作品描述": str(note.get("desc") or ""),
            "作品标签": tags,
            "作者昵称": str(user.get("nickname") or user.get("nickName") or ""),
            "作品链接": note_url,
        }

    def _extract_image_urls(self, note: dict) -> list[str]:
        urls = []
        for image in note.get("imageList") or []:
            if not isinstance(image, dict):
                continue
            source_url = image.get("urlDefault") or image.get("url")
            if not source_url:
                continue
            token = "/".join(source_url.split("/")[5:]).split("!")[0]
            urls.append(
                f"https://ci.xiaohongshu.com/{token}?imageView2/format/jpeg"
                if token else source_url
            )
        return urls

    async def _download_image(
        self,
        client: httpx.AsyncClient,
        url: str,
        folder: Path,
        index: int,
    ) -> None:
        response = await client.get(url)
        response.raise_for_status()
        suffix = self._image_suffix(response.headers.get("content-type", ""))
        path = folder / f"image_{index:02d}.{suffix}"
        path.write_bytes(response.content)
        self.log(f"已下载：{path.name}")

    @staticmethod
    def _deep_get(data: object, keys: tuple[str, ...]) -> object:
        for key in keys:
            if not isinstance(data, dict):
                return None
            data = data.get(key)
        return data

    @staticmethod
    def _safe_filename(value: str) -> str:
        value = re.sub(r'[\\/:*?"<>|\r\n\t]', "", value)
        return " ".join(value.split())[:80] or "xhs_note"

    @staticmethod
    def _note_id(url: str) -> str:
        return Path(urlparse(url).path).name

    @staticmethod
    def _image_suffix(content_type: str) -> str:
        return {
            "image/png": "png",
            "image/webp": "webp",
            "image/avif": "avif",
        }.get(content_type.split(";", 1)[0].lower(), "jpg")
