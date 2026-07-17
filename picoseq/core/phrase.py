"""フレーズ操作 — 固定長バッファ上の純粋関数群。

バッファは長さ MAX_NOTES のタプルで、常に新しいタプルを返す (不変)。
スロット番号は音符の同一性として使う (ドラッグ中の追従など)。
"""

from .constants import MAX_NOTES
from .note import Note, is_active, pack_note, unpack_note

EMPTY_PHRASE = (0,) * MAX_NOTES


def replace_slot(buffer: tuple, slot: int, value: int) -> tuple:
    """スロットの値を置き換えた新しいバッファを返す。"""
    return buffer[:slot] + (value,) + buffer[slot + 1:]


def add_note(buffer: tuple, pitch: int, step: int, wave: int, dur: int = 1):
    """先頭の空きスロットに追加し (新バッファ, スロット番号) を返す。満杯なら (元バッファ, -1)。"""
    for slot, value in enumerate(buffer):
        if not is_active(value):
            return replace_slot(buffer, slot, pack_note(pitch, step, wave, dur)), slot
    return buffer, -1


def remove_note(buffer: tuple, slot: int) -> tuple:
    """スロットの音符を消す。"""
    return replace_slot(buffer, slot, 0)


def resize_note(buffer: tuple, slot: int, dur: int) -> tuple:
    """スロットの音符の長さを変える。"""
    note = unpack_note(buffer[slot])
    dur = max(1, min(dur, 255))
    return replace_slot(buffer, slot, pack_note(note.pitch, note.step, note.wave, dur))


def find_note_at(buffer: tuple, pitch: int, step: int, wave: int) -> int:
    """指定セルを覆っている音符のスロット番号を返す (無ければ -1)。

    同じパートの音符だけが対象。step は音符の継続範囲内でも一致する。
    """
    for slot, value in enumerate(buffer):
        if not is_active(value):
            continue
        note = unpack_note(value)
        if note.pitch == pitch and note.wave == wave and note.step <= step < note.step + note.dur:
            return slot
    return -1


def notes_at_step(buffer: tuple, step: int) -> list:
    """そのステップで発音が始まる音符を返す。"""
    result = []
    for value in buffer:
        if is_active(value):
            note = unpack_note(value)
            if note.step == step:
                result.append(note)
    return result


def active_notes(buffer: tuple) -> list:
    """有効な音符を (スロット番号, Note) の列で返す。"""
    result = []
    for slot, value in enumerate(buffer):
        if is_active(value):
            result.append((slot, unpack_note(value)))
    return result


def count_notes(buffer: tuple) -> int:
    """有効な音符の数。"""
    return sum(1 for value in buffer if is_active(value))


def build_phrase(notes) -> tuple:
    """Note の列からバッファを作る (先頭から順に詰める)。あふれた分は捨てる。"""
    values = [pack_note(n.pitch, n.step, n.wave, n.dur) for n in notes[:MAX_NOTES]]
    values += [0] * (MAX_NOTES - len(values))
    return tuple(values)
