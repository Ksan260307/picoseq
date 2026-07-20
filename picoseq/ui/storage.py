"""ファイル置き場 — 自動保存と再生用一時 WAV。"""

import json
from pathlib import Path


def data_dir() -> Path:
    """ユーザーデータの置き場所 (~/.picoseq)。無ければ作る。"""
    path = Path.home() / ".picoseq"
    path.mkdir(parents=True, exist_ok=True)
    return path


def autosave_path() -> Path:
    return data_dir() / "autosave.json"


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> dict:
    """アプリ設定 (言語・ライセンス等)。無い・壊れていれば空の辞書。"""
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_settings(settings: dict):
    settings_path().write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")


def save_text(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def load_text(path: Path):
    """ファイルの中身。無い・読めないときは None。"""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return None


def write_play_wav(name: str, data: bytes) -> str:
    """再生用の一時 WAV を書き、そのパスを返す (winsound はファイル再生のみ非同期対応)。"""
    path = data_dir() / f"{name}.wav"
    path.write_bytes(data)
    return str(path)
