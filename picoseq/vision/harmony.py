"""四角形 → 音楽への写像 (フォト和音)。

写像の仕様 (すべて量子化された決定論写像):

  キー   … 四角形の中心の x 位置 (0..1) を 12 分割 → 0=C .. 11=B
  音階   … 整形度 R = 1 - (Σ|内角-90°|)/180 で選ぶ。
           整うほど明るく、歪むほど激しい:
             R ≥ 0.85 → major / ≥ 0.65 → minor / ≥ 0.45 → japanese / それ未満 → battle
  進行   … スケール既定進行を土台に、各コーナー (TL→TR→BR→BL) の
           角度の 90° からのズレ 15° につき度数を 1 ずらす (±3 まで)。
           完全な正方形なら既定進行そのものになる。
  テンポ … 四角形が画面に占める面積比。大きく写すほど速い。
  シード … コーナー座標 (百分率格子に量子化) の FNV-1a ハッシュ。
           同じ写真からは同じ曲が生まれる。

同じ Quad からは常に同じ PhotoHarmony が得られる。
"""

import math
from typing import NamedTuple

from ..core.constants import BPM_MAX, BPM_MIN, SEED_MAX, SEED_MIN, clamp
from ..core.music import KEY_NAMES, NOTE_NAMES, SCALES, chord_at
from .quad import Quad, polygon_area2


class PhotoHarmony(NamedTuple):
    key: int
    scale: str
    progression: tuple
    bpm: int
    seed: int


def corner_angles(points) -> list:
    """各コーナーの内角 (度)。points は TL, TR, BR, BL の順。"""
    angles = []
    for i in range(4):
        px, py = points[i - 1]
        cx, cy = points[i]
        nx, ny = points[(i + 1) % 4]
        v1 = (px - cx, py - cy)
        v2 = (nx - cx, ny - cy)
        len1 = math.hypot(*v1)
        len2 = math.hypot(*v2)
        if len1 == 0 or len2 == 0:
            angles.append(90.0)
            continue
        cos_a = (v1[0] * v2[0] + v1[1] * v2[1]) / (len1 * len2)
        angles.append(math.degrees(math.acos(max(-1.0, min(1.0, cos_a)))))
    return angles


def regularity(angles) -> float:
    """整形度 0..1。四隅がすべて 90° なら 1。"""
    deviation = sum(abs(a - 90.0) for a in angles)
    return max(0.0, 1.0 - deviation / 180.0)


def _scale_for(reg: float) -> str:
    if reg >= 0.85:
        return "major"
    if reg >= 0.65:
        return "minor"
    if reg >= 0.45:
        return "japanese"
    return "battle"


def harmony_from_quad(quad: Quad) -> PhotoHarmony:
    """検出した四角形を音楽パラメータへ写像する。純粋関数。"""
    points = quad.points
    angles = corner_angles(points)
    reg = regularity(angles)
    scale_id = _scale_for(reg)
    intervals = SCALES[scale_id]["intervals"]
    base = SCALES[scale_id]["progression"]
    n = len(intervals)

    # キー: 中心の x 位置
    center_x = sum(p[0] for p in points) / 4
    key = clamp(int(center_x * 12 / max(1, quad.grid_w)), 0, 11)

    # 進行: 角度ズレで既定進行を変形 (TL→TR→BR→BL)
    progression = []
    for i in range(4):
        offset = clamp(round((angles[i] - 90.0) / 15.0), -3, 3)
        progression.append((base[i % len(base)] + offset) % n)

    # テンポ: 面積比
    area_ratio = polygon_area2(points) / (2 * quad.grid_w * quad.grid_h)
    bpm = clamp(60 + int(area_ratio * 175), BPM_MIN, BPM_MAX)

    # シード: 量子化したコーナー座標のハッシュ
    seed = _seed_from_points(points, quad.grid_w, quad.grid_h)

    return PhotoHarmony(key=key, scale=scale_id, progression=tuple(progression),
                        bpm=bpm, seed=seed)


def _seed_from_points(points, grid_w: int, grid_h: int) -> int:
    """コーナー座標を百分率に量子化して FNV-1a でハッシュする。"""
    h = 0x811C9DC5
    for x, y in points:
        for value in (x * 100 // max(1, grid_w), y * 100 // max(1, grid_h)):
            h ^= value & 0xFF
            h = (h * 0x01000193) & 0xFFFFFFFF
    return h % (SEED_MAX - SEED_MIN + 1) + SEED_MIN


# ---- 表示用 ----

def chord_name(key: int, scale_id: str, degree: int) -> str:
    """度数からコード名 (例: Am, F, Bdim) を作る。"""
    chord = chord_at(key, scale_id, 0, 4, (degree,))
    root = NOTE_NAMES[chord.root % 12]
    third = (chord.third - chord.root) % 12
    fifth = (chord.fifth - chord.root) % 12
    quality = {(4, 7): "", (3, 7): "m", (3, 6): "dim", (4, 8): "aug"}.get(
        (third, fifth), "")
    return root + quality


def describe(harmony: PhotoHarmony) -> str:
    """検出結果の説明文 (ダイアログ・CLI 共用)。"""
    chords = " → ".join(chord_name(harmony.key, harmony.scale, d)
                        for d in harmony.progression)
    label = SCALES[harmony.scale]["label"]
    return (f"キー: {KEY_NAMES[harmony.key]} ・ 曲調: {label} ・ テンポ: {harmony.bpm}\n"
            f"コード進行: {chords}\n"
            f"シード: {harmony.seed}")
