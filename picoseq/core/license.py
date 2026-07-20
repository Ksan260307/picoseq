"""プロダクトコード — オフラインで検証できる製品コードの純粋関数。

サーバーを持たないため、コードは「ペイロード + チェック文字列」の自己完結形式にする。
チェックは塩を混ぜたハッシュから決まるので、正しいコードは手元だけで検証できる。
（暗号学的な完全防御ではない。市販シェアウェアのキー程度の抑止力という位置づけ。）

このモジュールは I/O も時刻参照もしない純粋関数だけ。日付ベースの無料枠管理は
観測層 (ui.licensing) が持つ。
"""

import hashlib

FREE_DAILY_LIMIT = 100  # 無料版で 1 日に自動生成できる回数

_PREFIX = "PICO"
_SALT = "picoseq-pro-2026"        # 難読化のための塩 (完全な秘匿ではない)
# 紛らわしい文字 (I/O/0/1) を除いた 32 文字。表示・手入力しやすい。
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_PAYLOAD_LEN = 8
_CHECK_LEN = 4


def normalize_code(code: str) -> str:
    """区切り・空白・大小を無視した英数字だけの正規形にする。"""
    return "".join(ch for ch in str(code).upper() if ch.isalnum())


def _checksum(payload: str) -> str:
    digest = hashlib.sha256((_SALT + payload).encode("ascii")).digest()
    return "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:_CHECK_LEN])


def is_valid_code(code: str) -> bool:
    """コードが正しい形式かつチェックが一致すれば True。"""
    norm = normalize_code(code)
    if not norm.startswith(_PREFIX):
        return False
    body = norm[len(_PREFIX):]
    if len(body) != _PAYLOAD_LEN + _CHECK_LEN:
        return False
    payload, check = body[:_PAYLOAD_LEN], body[_PAYLOAD_LEN:]
    if any(ch not in _ALPHABET for ch in payload + check):
        return False
    return _checksum(payload) == check


def make_code(serial: int) -> str:
    """通し番号から正しいプロダクトコードを発行する (発行・テスト用)。

    表示は PICO-XXXX-XXXX-YYYY (XXXX=ペイロード, YYYY=チェック)。
    """
    n = int(serial)
    chars = []
    for _ in range(_PAYLOAD_LEN):
        chars.append(_ALPHABET[n % len(_ALPHABET)])
        n //= len(_ALPHABET)
    payload = "".join(chars)
    check = _checksum(payload)
    return f"{_PREFIX}-{payload[:4]}-{payload[4:]}-{check}"
