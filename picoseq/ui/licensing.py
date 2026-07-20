"""有料化 — プロダクトコードの保存と、無料版の 1 日あたり自動生成枠の管理。

観測層/アプリの関心事で、確定状態 (Project) には一切影響しない。
- プロダクトコードの検証は core.license (純粋関数)。
- 有効なコードと当日の使用回数は settings.json に記録する (日付が変われば自動リセット)。
- 有料版の解放機能: 自動生成の回数無制限 + MIDI 書き出し。

ロジックは「settings 辞書を受け取る純粋関数」と「load/save する薄いラッパ」に分ける。
テストは前者を辞書で直接叩けるので、実ファイルに触れずに検証できる。
"""

import datetime

from ..core.license import FREE_DAILY_LIMIT, is_valid_code, normalize_code
from . import storage


def _today() -> str:
    return datetime.date.today().isoformat()


# ---- 純粋ロジック (settings 辞書を引数に取る) ----

def is_pro_in(settings: dict) -> bool:
    return is_valid_code(settings.get("product_code", ""))


def used_today_in(settings: dict, today: str = None) -> int:
    today = today or _today()
    usage = settings.get("auto_gen_usage")
    if isinstance(usage, dict) and usage.get("date") == today:
        try:
            return max(0, int(usage.get("count", 0)))
        except (TypeError, ValueError):
            return 0
    return 0


def remaining_in(settings: dict, today: str = None):
    """本日の残り自動生成回数。有料版なら None (無制限)。"""
    if is_pro_in(settings):
        return None
    return max(0, FREE_DAILY_LIMIT - used_today_in(settings, today))


def can_generate_in(settings: dict, today: str = None) -> bool:
    remaining = remaining_in(settings, today)
    return remaining is None or remaining > 0


def with_recorded(settings: dict, today: str = None) -> dict:
    """自動生成を 1 回消費した新しい settings を返す (有料版はそのまま)。"""
    today = today or _today()
    if is_pro_in(settings):
        return settings
    updated = dict(settings)
    updated["auto_gen_usage"] = {"date": today, "count": used_today_in(settings, today) + 1}
    return updated


def with_activated(settings: dict, code: str):
    """コードが正しければ有効化した settings を返す。(settings, 成否) を返す。"""
    if not is_valid_code(code):
        return settings, False
    updated = dict(settings)
    updated["product_code"] = normalize_code(code)
    return updated, True


# ---- I/O ラッパ (settings.json を読み書き) ----

def is_pro() -> bool:
    return is_pro_in(storage.load_settings())


def activate(code: str) -> bool:
    settings, ok = with_activated(storage.load_settings(), code)
    if ok:
        storage.save_settings(settings)
    return ok


def auto_gen_used_today() -> int:
    return used_today_in(storage.load_settings())


def auto_gen_remaining():
    return remaining_in(storage.load_settings())


def can_auto_generate() -> bool:
    return can_generate_in(storage.load_settings())


def record_auto_generate():
    settings = storage.load_settings()
    updated = with_recorded(settings)
    if updated is not settings:
        storage.save_settings(updated)


def can_export_midi() -> bool:
    return is_pro()
