# coding: utf-8
"""通用账号配置管理 —— 各平台共享的 config.json 读写"""
import json
from pathlib import Path


def load_account_config(account_dir: Path, defaults: dict) -> dict:
    """读取账号 config.json，缺失字段用 defaults 补全"""
    config_path = account_dir / "config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            return {**defaults, **data}
        except (json.JSONDecodeError, ValueError):
            pass
    return dict(defaults)


def save_account_config(account_dir: Path, config: dict):
    """保存账号 config.json"""
    account_dir.mkdir(parents=True, exist_ok=True)
    config_path = account_dir / "config.json"
    config_path.write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
