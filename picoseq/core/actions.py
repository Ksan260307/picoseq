"""操作 (アクション) — すべて純粋関数。Project を受け取り、新しい Project を返す。

副作用・I/O・実時間・暗黙の乱数を一切持たない。
変化が無い場合は同じオブジェクトをそのまま返す (呼び出し側の無変更検出用)。
"""

from . import phrase as phrase_ops
from . import song as song_ops
from .arranger import arrange
from .composer import compose
from .constants import (
    BEATS_MAX,
    BEATS_MIN,
    BPM_MAX,
    BPM_MIN,
    EMPTY_CELL,
    PART_COUNT,
    PATTERN_COUNT,
    PITCH_MAX,
    PITCH_MIN,
    PROGRESSION_MAX_LEN,
    SEED_MAX,
    SEED_MIN,
    SOUND_SETS,
    clamp,
)
from .music import PHOTO_SCALE, SCALES, get_scale
from .project import Pattern, Project, steps_of, update


# ---- テンポ・拍子・曲調 ----

def set_bpm(project: Project, bpm: int) -> Project:
    bpm = clamp(int(bpm), BPM_MIN, BPM_MAX)
    if bpm == project.bpm:
        return project
    return update(project, bpm=bpm)


def set_beats(project: Project, beats: int) -> Project:
    """拍子を変える。ブロック長が変わるため、ソング構成はリセットする。"""
    beats = clamp(int(beats), BEATS_MIN, BEATS_MAX)
    if beats == project.beats:
        return project
    return update(project, beats=beats, song=song_ops.EMPTY_SONG)


def set_key(project: Project, key: int) -> Project:
    key = clamp(int(key), 0, 11)
    if key == project.key:
        return project
    return update(project, key=key)


def set_scale(project: Project, scale_id: str) -> Project:
    """音階を変える。カスタム進行は度数の意味が変わるためリセットする。

    "photo" (フォト音階) は写真から取り込み済みのときだけ選べる。
    """
    if scale_id == PHOTO_SCALE:
        if project.custom_scale is None:
            raise ValueError("フォト音階がまだありません。📷 写真から取り込んでください。")
    elif scale_id not in SCALES:
        raise ValueError(f"未知の音階です: {scale_id}")
    if scale_id == project.scale:
        return project
    return update(project, scale=scale_id, progression=None)


def set_custom_scale(project: Project, key: int, intervals, bpm: int, seed: int) -> Project:
    """写真から抽出した音階を登録し、その音階へ切り替える。

    intervals は 0 を含む半音の列 (例: (0, 3, 5, 8, 10))。
    キー・テンポ・シードも写真由来の値として一緒に記録する。
    """
    degrees = tuple(sorted(set(int(v) % 12 for v in intervals)))
    if 0 not in degrees:
        degrees = tuple(sorted((0,) + degrees))
    if len(degrees) < 3:
        raise ValueError(f"フォト音階には 3 音以上必要です: {degrees}")
    return update(
        project,
        custom_scale=degrees,
        scale=PHOTO_SCALE,
        key=clamp(int(key), 0, 11),
        bpm=clamp(int(bpm), BPM_MIN, BPM_MAX),
        seed=clamp(int(seed), SEED_MIN, SEED_MAX),
        progression=None,
    )


def set_progression(project: Project, progression) -> Project:
    """カスタムコード進行を設定する。None でスケール既定に戻す。"""
    if progression is not None:
        degrees = tuple(int(d) for d in progression)
        n = len(get_scale(project.scale, project.custom_scale)["intervals"])
        if not (1 <= len(degrees) <= PROGRESSION_MAX_LEN):
            raise ValueError(f"進行の長さが範囲外です: {len(degrees)}")
        for degree in degrees:
            if not (0 <= degree < n):
                raise ValueError(f"度数が範囲外です: {degree} (音階の音数 {n})")
        progression = degrees
    if progression == project.progression:
        return project
    return update(project, progression=progression)


def set_seed(project: Project, seed: int) -> Project:
    seed = clamp(int(seed), SEED_MIN, SEED_MAX)
    if seed == project.seed:
        return project
    return update(project, seed=seed)


def set_sound(project: Project, sound: str) -> Project:
    """音色セットを変える (retro8 / warm16 / clear32)。"""
    if sound not in SOUND_SETS:
        raise ValueError(f"未知の音色セットです: {sound}")
    if sound == project.sound:
        return project
    return update(project, sound=sound)


# ---- パート設定 ----

def set_part_tone(project: Project, part: int, tone: int) -> Project:
    _check_part(part)
    tone = clamp(int(tone), 0, 100)
    if tone == project.parts[part].tone:
        return project
    parts = list(project.parts)
    parts[part] = update(parts[part], tone=tone)
    return update(project, parts=tuple(parts))


def set_part_gate(project: Project, part: int, gate: int) -> Project:
    _check_part(part)
    gate = clamp(int(gate), 10, 100)
    if gate == project.parts[part].gate:
        return project
    parts = list(project.parts)
    parts[part] = update(parts[part], gate=gate)
    return update(project, parts=tuple(parts))


def _check_part(part: int):
    if not (0 <= part < PART_COUNT):
        raise ValueError(f"パート番号が範囲外です: {part}")


# ---- フレーズ編集 ----

def place_note(project: Project, pitch: int, step: int, wave: int, dur: int = 1):
    """音符を置く。(新しい Project, スロット番号) を返す。満杯なら (元 Project, -1)。"""
    steps = steps_of(project)
    if not (PITCH_MIN <= pitch <= PITCH_MAX):
        raise ValueError(f"音の高さが範囲外です: {pitch}")
    if not (0 <= step < steps):
        raise ValueError(f"ステップが範囲外です: {step}")
    _check_part(wave)
    dur = clamp(int(dur), 1, steps - step)
    buffer, slot = phrase_ops.add_note(project.phrase, pitch, step, wave, dur)
    if slot == -1:
        return project, -1
    return update(project, phrase=buffer), slot


def erase_note(project: Project, slot: int) -> Project:
    """スロットの音符を消す。無効なスロットは何もしない。"""
    if not _valid_slot(project, slot):
        return project
    return update(project, phrase=phrase_ops.remove_note(project.phrase, slot))


def resize_note(project: Project, slot: int, dur: int) -> Project:
    """スロットの音符の長さを変える (グリッド内に収める)。"""
    if not _valid_slot(project, slot):
        return project
    from .note import unpack_note
    note = unpack_note(project.phrase[slot])
    dur = clamp(int(dur), 1, steps_of(project) - note.step)
    if dur == note.dur:
        return project
    return update(project, phrase=phrase_ops.resize_note(project.phrase, slot, dur))


def _valid_slot(project: Project, slot: int) -> bool:
    from .note import is_active
    return 0 <= slot < len(project.phrase) and is_active(project.phrase[slot])


def clear_phrase(project: Project) -> Project:
    if project.phrase == phrase_ops.EMPTY_PHRASE:
        return project
    return update(project, phrase=phrase_ops.EMPTY_PHRASE)


def generate_phrase(project: Project) -> Project:
    """現在の設定 (拍子・キー・音階・シード・進行) からフレーズを自動作成する。"""
    buffer = compose(project.beats, project.key, project.scale, project.seed,
                     project.progression, project.custom_scale)
    return update(project, phrase=buffer)


def arrange_accompaniment(project: Project) -> Project:
    """盤面のメロディに合わせてベース・サブ・リズムを自動生成する。

    メロディから推定したコード進行を進行として記録し、以後の再現性を保つ。
    メロディが無ければ何もしない。
    """
    buffer, progression = arrange(project)
    if progression is None:
        return project
    return update(project, phrase=buffer, progression=progression)


def generate_song(project: Project) -> Project:
    """1 曲ぶんを自動作成する。

    パターン 1〜4 (イントロ / Aメロ / Bメロ / アウトロ) を作って
    ソング構成に並べる。パターン 5〜8 は温存する。
    編集画面には Aメロを開く。
    """
    from .songwriter import write_song
    buffers, layout = write_song(project.beats, project.key, project.scale,
                                 project.seed, project.progression,
                                 project.custom_scale)
    patterns = [Pattern(used=True, notes=buf) for buf in buffers]
    patterns += list(project.patterns[len(buffers):])
    song = list(song_ops.EMPTY_SONG)
    for block, pattern_id in enumerate(layout):
        song[song_ops.cell_index(0, block)] = pattern_id
    return update(project, patterns=tuple(patterns), song=tuple(song),
                  phrase=buffers[1])


# ---- パターン (お気に入り) ----

def save_pattern(project: Project, slot: int) -> Project:
    """現在のフレーズをパターンスロットへ保存する。"""
    _check_pattern(slot)
    patterns = list(project.patterns)
    patterns[slot] = Pattern(used=True, notes=project.phrase)
    return update(project, patterns=tuple(patterns))


def load_pattern(project: Project, slot: int) -> Project:
    """パターンをフレーズエディタへ読み込む。未使用スロットは何もしない。"""
    _check_pattern(slot)
    pattern = project.patterns[slot]
    if not pattern.used:
        return project
    return update(project, phrase=pattern.notes)


def delete_pattern(project: Project, slot: int) -> Project:
    """パターンを削除し、ソング構成からも取り除く。"""
    _check_pattern(slot)
    if not project.patterns[slot].used:
        return project
    patterns = list(project.patterns)
    patterns[slot] = Pattern()
    song = song_ops.clear_pattern_refs(project.song, slot)
    return update(project, patterns=tuple(patterns), song=song)


def free_pattern_slot(project: Project) -> int:
    """空いているパターンスロット番号 (無ければ -1)。"""
    for slot in range(PATTERN_COUNT):
        if not project.patterns[slot].used:
            return slot
    return -1


def _check_pattern(slot: int):
    if not (0 <= slot < PATTERN_COUNT):
        raise ValueError(f"パターン番号が範囲外です: {slot}")


# ---- ソング構成 ----

def toggle_song_cell(project: Project, track: int, block: int, pattern_id: int) -> Project:
    """セルにパターンを配置する。同じパターンなら消去。未使用パターンは何もしない。"""
    _check_pattern(pattern_id)
    if not project.patterns[pattern_id].used:
        return project
    song = song_ops.toggle_cell(project.song, track, block, pattern_id)
    return update(project, song=song)


def erase_song_cell(project: Project, track: int, block: int) -> Project:
    """セルを空にする。"""
    if song_ops.get_cell(project.song, track, block) == EMPTY_CELL:
        return project
    return update(project, song=song_ops.set_cell(project.song, track, block, EMPTY_CELL))


def clear_song(project: Project) -> Project:
    if project.song == song_ops.EMPTY_SONG:
        return project
    return update(project, song=song_ops.EMPTY_SONG)
