# coding: utf-8
import base64
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

SAVE_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "AutoPublisher" / "image_gen"
SAVE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = SAVE_DIR / "history.json"


def build_api_url(base_url: str, path: str = "/v1/images/generations") -> str:
    """智能拼接 API URL，规范化斜杠与 /v1 重复问题"""
    clean_base = base_url.strip().rstrip("/")
    lower_base = clean_base.lower()

    clean_path = path.strip().lstrip("/")
    if clean_path.lower().startswith("v1/"):
        clean_path = clean_path[3:]

    if lower_base.endswith("/v1"):
        return f"{clean_base}/{clean_path}"
    else:
        return f"{clean_base}/v1/{clean_path}"


class ImageGenHistoryManager:
    """生图历史记录本地持久化管理器"""

    @staticmethod
    def load_history() -> list[dict]:
        if not HISTORY_FILE.exists():
            return []
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def save_history(records: list[dict]):
        try:
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(records, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[History] 保存失败: {e}")

    @classmethod
    def add_record(cls, prompt: str, model: str, size: str, quality: str, n: int, image_items: list[dict]) -> dict:
        records = cls.load_history()
        record = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": prompt,
            "model": model,
            "size": size,
            "quality": quality,
            "n": n,
            "images": image_items,
        }
        records.insert(0, record)
        cls.save_history(records)
        return record

    @classmethod
    def delete_record(cls, record_id: str):
        records = cls.load_history()
        records = [r for r in records if r.get("id") != record_id]
        cls.save_history(records)

    @classmethod
    def clear_history(cls):
        cls.save_history([])


class ImageGenThread(QThread):
    logMessage = Signal(str)
    imageGenerated = Signal(int, str, str)  # index, b64, mime
    finished = Signal(bool, str, dict)  # success, message, record_dict

    def __init__(self, base_url: str, api_key: str, model: str, prompt: str,
                 size: str, quality: str, response_format: str, n: int,
                 ref_b64_list: list[str] | None = None, parent=None):
        super().__init__(parent)
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.prompt = prompt
        self.size = size
        self.quality = quality
        self.response_format = response_format
        self.n = n
        self.ref_b64_list = ref_b64_list or []

    def run(self):
        success = False
        message = ""
        record = {}
        try:
            success, message, record = self._run_generate()
        except requests.exceptions.Timeout:
            message = "请求超时，请检查网络或 API 地址"
        except requests.exceptions.ConnectionError:
            message = "连接失败，请检查 API 地址和网络"
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            detail = ""
            try:
                detail = e.response.json().get("error", {}).get("message", e.response.text)
            except Exception:
                detail = e.response.text[:200]
            message = f"HTTP {status}: {detail}"
        except Exception as e:
            message = f"生成失败: {str(e)}"
        finally:
            self.finished.emit(success, message, record)

    def _run_generate(self) -> tuple[bool, str, dict]:
        url = build_api_url(self.base_url, "/v1/images/generations")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "size": self.size,
            "quality": self.quality,
            "n": self.n,
            "response_format": self.response_format,
        }
        if self.ref_b64_list:
            payload["images"] = self.ref_b64_list
            if len(self.ref_b64_list) == 1:
                payload["image"] = self.ref_b64_list[0]

        ref_info = f" (含 {len(self.ref_b64_list)} 张参考图)" if self.ref_b64_list else ""
        self.logMessage.emit(f"请求: POST {url}{ref_info}")
        self.logMessage.emit(f"模型: {self.model} | 尺寸: {self.size} | 质量: {self.quality} | 格式: {self.response_format} | 张数: {self.n}")

        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        resp.raise_for_status()
        data = resp.json()
        return self._process_images(data)

    def _process_images(self, data: dict) -> tuple[bool, str, dict]:
        if "error" in data:
            raise RuntimeError(data["error"].get("message", str(data["error"])))

        images = data.get("data", [])
        if not images:
            raise RuntimeError("接口返回数据为空")

        self.logMessage.emit(f"生成 {len(images)} 张图片，正在解析保存...")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_items = []

        for i, item in enumerate(images):
            b64 = item.get("b64_json") or item.get("b64") or ""
            url_result = item.get("url") or ""
            mime = "image/png"

            if b64:
                try:
                    image_data = base64.b64decode(b64)
                    file_name = f"gen_{timestamp}_{i+1}.png"
                    file_path = SAVE_DIR / file_name
                    file_path.write_bytes(image_data)
                    self.imageGenerated.emit(i, b64, mime)
                    saved_items.append({
                        "file_path": str(file_path),
                        "b64": b64,
                        "mime": mime
                    })
                    self.logMessage.emit(f"  [{i+1}] 已保存: {file_path}")
                except Exception as err:
                    self.logMessage.emit(f"  [{i+1}] 解码失败: {err}")
            elif url_result:
                try:
                    self.logMessage.emit(f"  [{i+1}] 下载外链图片: {url_result[:60]}...")
                    img_resp = requests.get(url_result, timeout=20)
                    img_resp.raise_for_status()
                    b64 = base64.b64encode(img_resp.content).decode()
                    mime = img_resp.headers.get("content-type", "image/png")
                    ext = mime.split("/")[-1] if "/" in mime else "png"
                    file_name = f"gen_{timestamp}_{i+1}.{ext}"
                    file_path = SAVE_DIR / file_name
                    file_path.write_bytes(img_resp.content)
                    self.imageGenerated.emit(i, b64, mime)
                    saved_items.append({
                        "file_path": str(file_path),
                        "b64": b64,
                        "mime": mime
                    })
                    self.logMessage.emit(f"  [{i+1}] 已保存: {file_path}")
                except Exception as dl_err:
                    self.logMessage.emit(f"  [{i+1}] 外链图片下载失败: {dl_err}")
            else:
                self.logMessage.emit(f"  [{i+1}] 数据节点为空，跳过")

        # 写入历史记录
        record = {}
        if saved_items:
            record = ImageGenHistoryManager.add_record(
                prompt=self.prompt,
                model=self.model,
                size=self.size,
                quality=self.quality,
                n=self.n,
                image_items=saved_items
            )

        self.logMessage.emit(f"完成，文件保存在: {SAVE_DIR}")
        return True, f"成功生成 {len(saved_items)} 张图片", record