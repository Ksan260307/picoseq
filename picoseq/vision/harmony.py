"""写真 → 音階への変換 (フォト音階)。

写真から見つけた四角形 (最大 8 個) を「使える音」の集合に変換する。
できた音階は曲調セレクタに「📷 フォト音階」として追加され、
自動作成でも手入力でも、その音だけを使って作曲できる。

変換の仕様 (すべて決定論。同じ写真 → 同じ音階):

  各四角形の音 … 中心の x 位置 (0..1) を 12 分割した半音 (左 = 低い音)
  キー         … いちばん大きい四角形の音
  音階         … 全四角形の音をキーからの距離に直して並べたもの。
                 3 音に満たないときは 5度 → 長3度 → 短7度 の順で補う
  テンポ       … 四角形が画面に占める面積の合計。大きく写すほど速い
  シード値     … 全コーナー座標 (百分率に量子化) のハッシュ
"""

from typing import NamedTuple

from ..core.constants import BPM_MAX, BPM_MIN, SEED_MAX, SEED_MIN, clamp
from ..core.music import KEY_NAMES, NOTE_NAMES, get_scale
from .quad import polygon_area2

FILL_INTERVALS = (7, 4, 10, 2, 9)  # 音が足りないときに補う音程 (5度, 長3度, ...)


class PhotoScale(NamedTuple):
    key: int          # 0=C .. 11=B
    intervals: tuple  # キーからの半音 (0 始まり・昇順)
    bpm: int
    seed: int
    pitch_classes: tuple  # 各四角形の音 (面積順・表示用)


def quad_pitch_class(quad) -> int:
    """四角形 1 つの音 (半音クラス 0..11)。中心の x 位置で決まる。"""
    center_x = sum(p[0] for p in quad.points) / 4
    return clamp(int(center_x * 12 / max(1, quad.grid_w)), 0, 11)


def photo_scale_from_quads(quads) -> PhotoScale:
    """検出した四角形の列 (面積の大きい順) から音階を作る。純粋関数。"""
    if not quads:
        raise ValueError("四角形がありません。")

    pitch_classes = tuple(quad_pitch_class(q) for q in quads)
    key = pitch_classes[0]

    intervals = sorted({(pc - key) % 12 for pc in pitch_classes})
    for extra in FILL_INTERVALS:
        if len(intervals) >= 3:
            break
        if extra not in intervals:
            intervals.append(extra)
    intervals = tuple(sorted(intervals))

    grid_w = quads[0].grid_w
    grid_h = quads[0].grid_h
    total_area = sum(polygon_area2(q.points) for q in quads)
    area_ratio = min(1.0, total_area / (2 * grid_w * grid_h))
    bpm = clamp(60 + int(area_ratio * 175), BPM_MIN, BPM_MAX)

    seed = _seed_from_quads(quads)
    return PhotoScale(key=key, intervals=intervals, bpm=bpm, seed=seed,
                      pitch_classes=pitch_classes)


def _seed_from_quads(quads) -> int:
    """全四角形のコーナー座標を百分率に量子化して FNV-1a でハッシュする。"""
    h = 0x811C9DC5
    for quad in quads:
        for x, y in quad.points:
            for value in (x * 100 // max(1, quad.grid_w),
                          y * 100 // max(1, quad.grid_h)):
                h ^= value & 0xFF
                h = (h * 0x01000193) & 0xFFFFFFFF
    return h % (SEED_MAX - SEED_MIN + 1) + SEED_MIN


# ---- 表示用 ----

def scale_note_names(photo: PhotoScale) -> list:
    """音階に含まれる音名の一覧 (キーから昇順)。"""
    return [NOTE_NAMES[(photo.key + iv) % 12] for iv in photo.intervals]


def describe(photo: PhotoScale, lang: str = "ja") -> str:
    """検出結果の説明文 (ダイアログ・コマンドライン共用)。"""
    if lang == "en":
        notes = " · ".join(scale_note_names(photo))
        return (f"Rectangles: {len(photo.pitch_classes)} → notes: {notes} ({len(photo.intervals)}-tone)\n"
                f"Key: {KEY_NAMES[photo.key]} · Tempo: {photo.bpm} · Seed: {photo.seed}\n"
                f"You can reselect this scale anytime as mood \"📷 Photo scale\".")
    notes = "・".join(scale_note_names(photo))
    label = get_scale("photo", photo.intervals)["label"]
    return (f"四角形: {len(photo.pitch_classes)} 個 → 使える音: {notes} ({len(photo.intervals)} 音)\n"
            f"キー: {KEY_NAMES[photo.key]} ・ テンポ: {photo.bpm} ・ シード値: {photo.seed}\n"
            f"この音階は 曲調「{label}」としていつでも選び直せます。")
