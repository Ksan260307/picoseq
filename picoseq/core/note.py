"""音符の 32bit パック表現 — 全属性を 1 つの整数に詰める。

bit 0-7   pitch    MIDI ノート番号
bit 8-15  step     フレーズ内の開始ステップ
bit 16-17 wave     パート (波形)
bit 18    active   1 = 有効
bit 19-26 duration 継続ステップ数 (0 は 1 とみなす)
bit 27-29 layer    同じパート内のレイヤー番号 (0〜7)

bit 0-26 は旧版 (main.html) と同一。旧セーブデータは layer=0 として読める。
"""

from typing import NamedTuple


class Note(NamedTuple):
    pitch: int
    step: int
    wave: int
    dur: int
    layer: int = 0


def pack_note(pitch: int, step: int, wave: int, dur: int = 1,
              active: bool = True, layer: int = 0) -> int:
    """音符を 32bit 整数に詰める。"""
    value = ((pitch & 0xFF) | ((step & 0xFF) << 8) | ((wave & 0x3) << 16)
             | ((dur & 0xFF) << 19) | ((layer & 0x7) << 27))
    if active:
        value |= 1 << 18
    return value


def unpack_note(value: int) -> Note:
    """32bit 整数から音符を取り出す。"""
    dur = (value >> 19) & 0xFF
    if dur == 0:
        dur = 1  # 旧データへのフェールセーフ
    return Note(value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0x3,
                dur, (value >> 27) & 0x7)


def is_active(value: int) -> bool:
    """有効な音符か。"""
    return bool(value & (1 << 18))
