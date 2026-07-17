"""ソンググリッド操作 — 4トラック x 16ブロックの純粋関数群。

グリッドは長さ 64 のタプル。値はパターン番号 (0..7) か EMPTY_CELL。
"""

from .constants import EMPTY_CELL, SONG_BLOCKS, SONG_TRACKS

EMPTY_SONG = (EMPTY_CELL,) * (SONG_TRACKS * SONG_BLOCKS)


def cell_index(track: int, block: int) -> int:
    """トラックとブロックからセル番号へ。"""
    if not (0 <= track < SONG_TRACKS and 0 <= block < SONG_BLOCKS):
        raise ValueError(f"セル位置が範囲外です: track={track}, block={block}")
    return track * SONG_BLOCKS + block


def get_cell(song: tuple, track: int, block: int) -> int:
    """セルの値を返す。"""
    return song[cell_index(track, block)]


def set_cell(song: tuple, track: int, block: int, value: int) -> tuple:
    """セルの値を置き換えた新しいグリッドを返す。"""
    index = cell_index(track, block)
    return song[:index] + (value,) + song[index + 1:]


def toggle_cell(song: tuple, track: int, block: int, pattern_id: int) -> tuple:
    """同じパターンなら消去、それ以外なら配置する。"""
    if get_cell(song, track, block) == pattern_id:
        return set_cell(song, track, block, EMPTY_CELL)
    return set_cell(song, track, block, pattern_id)


def clear_pattern_refs(song: tuple, pattern_id: int) -> tuple:
    """指定パターンをグリッド全体から取り除く。"""
    return tuple(EMPTY_CELL if value == pattern_id else value for value in song)


def used_blocks(song: tuple) -> int:
    """使われている右端のブロック番号 + 1 (空なら 0)。"""
    last = -1
    for track in range(SONG_TRACKS):
        for block in range(SONG_BLOCKS):
            if song[track * SONG_BLOCKS + block] != EMPTY_CELL:
                last = max(last, block)
    return last + 1
