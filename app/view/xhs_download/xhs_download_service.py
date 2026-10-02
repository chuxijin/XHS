# coding: utf-8
"""小红书下载业务层。"""
import asyncio
import json
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from ...common.setting import DATA_DIR
from .xhs_note_downloader import XhsNoteDownloader

XHS_DOWNLOAD_DIR = DATA_DIR / "downloads" / "xhs"
XHS_MEDIA_DIR = XHS_DOWNLOAD_DIR / "media"


def sanitize_filename(name: str, fallback: str = "xhs_note") -> str:
    cleaned = "".join(ch for ch in name if ch not in '\\/:*?"<>|\r\n\t')
    cleaned = " ".join(cleaned.split())
    return cleaned[:80] or fallback


def extract_note_fields(data: dict) -> dict:
    title = data.get("作品标题") or data.get("标题") or ""
    desc = data.get("作品描述") or data.get("描述") or data.get("文案") or ""
    tags = data.get("作品标签") or data.get("标签") or []
    if isinstance(tags, str):
        tags = [tag for tag in tags.replace("#", " #").split() if tag]
    return {
        "title": title,
        "desc": desc,
        "tags": tags,
    }


class XhsNoteDownloadThread(QThread):
    logMessage = Signal(str)
    downloadSuccess = Signal(str, dict)
    downloadFailed = Signal(str)

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url.strip()

    def run(self):
        try:
            if not self.url:
                raise ValueError("请输入小红书链接")
            data = asyncio.run(self._download_with_embedded_xhs())
            if isinstance(data, list):
                data = data[0] if data else {}
            if not data:
                raise RuntimeError("未获取到作品数据")

            fields = extract_note_fields(data)
            save_dir = self._get_latest_media_dir(fields["title"])
            save_dir.mkdir(parents=True, exist_ok=True)
            metadata_path = save_dir / "metadata.json"
            metadata_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            summary_path = save_dir / "summary.txt"
            summary_path.write_text(
                self._format_summary(fields),
                encoding="utf-8",
            )
            self.downloadSuccess.emit(str(save_dir), fields)
        except Exception as e:
            self.downloadFailed.emit(str(e))

    async def _download_with_embedded_xhs(self) -> list[dict]:
        XHS_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        self.logMessage.emit("使用当前项目内置的小红书图文下载逻辑...")
        downloader = XhsNoteDownloader(XHS_MEDIA_DIR, self.logMessage.emit)
        return [await downloader.download(self.url)]

    def _get_latest_media_dir(self, title: str) -> Path:
        folders = [
            path for path in XHS_MEDIA_DIR.iterdir()
            if path.is_dir()
        ] if XHS_MEDIA_DIR.exists() else []
        if folders:
            return max(folders, key=lambda path: path.stat().st_mtime)
        return XHS_MEDIA_DIR / sanitize_filename(title, "xhs_note")

    def _format_summary(self, fields: dict) -> str:
        tags = fields.get("tags") or []
        tag_text = " ".join(tags) if isinstance(tags, list) else str(tags)
        return (
            f"标题：{fields.get('title', '')}\n\n"
            f"文案：\n{fields.get('desc', '')}\n\n"
            f"标签：\n{tag_text}\n"
        )
