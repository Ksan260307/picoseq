"""音符の 32bit パック表現 — 全属性を 1 つの整数に詰める。

bit 0-7   pitch    MIDI ノート番号
bit 8-15  step     フレーズ内の開始ステップ
bit 16-17 wave     パート (波形)
bit 18    active   1 = 有効
bit 19-26 duration 継続ステップ数 (0 は 1 とみなす)
bit 27-29 layer    同じパート内のレイヤー番号 (0〜7)
bit 30-31 soft     弱さ 0〜3 (**0 = 最強**。SOFT_GAIN の段で音量が下がる)

bit 0-26 は旧版 (main.html) と同一。旧セーブデータは layer=0 として読める。
soft は最後の 2bit に収めた。**0 を「そのまま」にしてあるので、
値を持たない旧データはそのままの音量で鳴る**(強弱を後付けするときの要点)。
4 段しか無いのは 32bit を広げないため。チップチューンのアクセントには足りる。
"""

from typing import NamedTuple

SOFT_LEVELS = 4
# 弱さの段ごとの音量 (%)。0 は 100% = 旧データと完全に同じ音。
SOFT_GAIN = (100, 84, 68, 52)


class Note(NamedTuple):
    pitch: int
    step: int
    wave: int
    dur: int
    layer: int = 0
    soft: int = 0


def pack_note(pitch: int, step: int, wave: int, dur: int = 1,
              active: bool = True, layer: int = 0, soft: int = 0) -> int:
    """音符を 32bit 整数に詰める。"""
    value = ((pitch & 0xFF) | ((step & 0xFF) << 8) | ((wave & 0x3) << 16)
             | ((dur & 0xFF) << 19) | ((layer & 0x7) << 27)
             | ((soft & 0x3) << 30))
    if active:
        value |= 1 << 18
    return value


def unpack_note(value: int) -> Note:
    """32bit 整数から音符を取り出す。"""
    dur = (value >> 19) & 0xFF
    if dur == 0:
        dur = 1  # 旧データへのフェールセーフ
    return Note(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0x3,
                dur, (value >> 27) & 0x7, (value >> 30) & 0x3)


def soft_gain(soft: int) -> int:
    """弱さの段に対応する音量 (%)。範囲外は 100% として扱う。"""
    if 0 <= soft < SOFT_LEVELS:
        return SOFT_GAIN[soft]
    return 100


def is_active(value: int) -> bool:
    """有効な音符か。"""
    return bool(value & (1 << 18))
