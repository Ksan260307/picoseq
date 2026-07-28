"""操作 (アクション) — すべて純粋関数。Project を受け取り、新しい Project を返す。

副作用・I/O・実時間・暗黙の乱数を一切持たない。
変化が無い場合は同じオブジェクトをそのまま返す (呼び出し側の無変更検出用)。
"""

from . import phrase as phrase_ops
from . import song as song_ops
from .arranger import arrange
from .composer import compose, compose_layers
from .constants import (
    BEATS_MAX,
    BEATS_MIN,
    BPM_MAX,
    BPM_MIN,
    EMPTY_CELL,
    MAX_LAYERS,
    PART_COUNT,
    PATTERN_COUNT,
    PITCH_MAX,
    PITCH_MIN,
    PROGRESSION_MAX_LEN,
    SEED_MAX,
    SEED_MIN,
    SOUND_SETS,
    WAVE_NOISE,
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


# ---- パート・レイヤー設定 ----

def _set_layer_field(project, wave, layer, **fields):
    """(wave, layer) の PartParams を書き換える。無変更なら元のまま。"""
    _check_layer(project, wave, layer)
    current = project.parts[wave][layer]
    updated = update(current, **fields)
    if updated == current:
        return project
    parts = [list(layers) for layers in project.parts]
    parts[wave][layer] = updated
    return update(project, parts=tuple(tuple(p) for p in parts))


def set_part_tone(project: Project, wave: int, tone: int, layer: int = 0) -> Project:
    return _set_layer_field(project, wave, layer, tone=clamp(int(tone), 0, 100))


def set_part_gate(project: Project, wave: int, gate: int, layer: int = 0) -> Project:
    return _set_layer_field(project, wave, layer, gate=clamp(int(gate), 10, 100))


def set_part_volume(project: Project, wave: int, volume: int, layer: int = 0) -> Project:
    return _set_layer_field(project, wave, layer, volume=clamp(int(volume), 0, 100))


def add_layer(project: Project, wave: int) -> Project:
    """パートにレイヤーを 1 つ足す (最大 MAX_LAYERS)。既存の設定を引き継ぐ。"""
    _check_part(wave)
    layers = project.parts[wave]
    if len(layers) >= MAX_LAYERS:
        return project
    parts = list(project.parts)
    parts[wave] = layers + (layers[-1],)  # 直前の音作りを引き継ぐ
    return update(project, parts=tuple(parts))


def remove_layer(project: Project, wave: int, layer: int) -> Project:
    """パートのレイヤー (1 層目以外) を消す。そのレイヤーの音符も消し、番号を詰める。"""
    _check_layer(project, wave, layer)
    if layer == 0:
        raise ValueError("1 層目は削除できません。")
    from .note import Note
    layers = list(project.parts[wave])
    del layers[layer]
    parts = list(project.parts)
    parts[wave] = tuple(layers)

    # 対象レイヤーの音符を消し、より上のレイヤーの番号を 1 つ下げる
    kept = []
    for _, note in phrase_ops.active_notes(project.phrase):
        if note.wave == wave and note.layer == layer:
            continue
        if note.wave == wave and note.layer > layer:
            kept.append(Note(note.pitch, note.step, note.wave, note.dur,
                             note.layer - 1, note.soft))
        else:
            kept.append(note)
    return update(project, parts=tuple(parts),
                  phrase=phrase_ops.build_phrase(kept))


def _check_part(part: int):
    if not (0 <= part < PART_COUNT):
        raise ValueError(f"パート番号が範囲外です: {part}")


def _check_layer(project: Project, wave: int, layer: int):
    _check_part(wave)
    if not (0 <= layer < len(project.parts[wave])):
        raise ValueError(f"レイヤー番号が範囲外です: {layer}")


# ---- フレーズ編集 ----

def place_note(project: Project, pitch: int, step: int, wave: int, dur: int = 1,
               layer: int = 0):
    """音符を置く。(新しい Project, スロット番号) を返す。満杯なら (元 Project, -1)。"""
    steps = steps_of(project)
    if not (PITCH_MIN <= pitch <= PITCH_MAX):
        raise ValueError(f"音の高さが範囲外です: {pitch}")
    if not (0 <= step < steps):
        raise ValueError(f"ステップが範囲外です: {step}")
    _check_layer(project, wave, layer)
    dur = clamp(int(dur), 1, steps - step)
    buffer, slot = phrase_ops.add_note(project.phrase, pitch, step, wave, dur, layer)
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


def set_note_soft(project: Project, slot: int, soft: int) -> Project:
    """スロットの音符の強弱を変える (0 = 最強 〜 SOFT_LEVELS-1)。"""
    if not _valid_slot(project, slot):
        return project
    from .note import SOFT_LEVELS, pack_note, unpack_note
    note = unpack_note(project.phrase[slot])
    soft = clamp(int(soft), 0, SOFT_LEVELS - 1)
    if soft == note.soft:
        return project
    value = pack_note(note.pitch, note.step, note.wave, note.dur,
                      layer=note.layer, soft=soft)
    return update(project, phrase=phrase_ops.replace_slot(project.phrase, slot,
                                                          value))


def cycle_note_soft(project: Project, slot: int):
    """強弱を 1 段ずつ回す (最弱の次は最強へ)。(新 Project, 新しい段) を返す。"""
    if not _valid_slot(project, slot):
        return project, 0
    from .note import SOFT_LEVELS, unpack_note
    soft = (unpack_note(project.phrase[slot]).soft + 1) % SOFT_LEVELS
    return set_note_soft(project, slot, soft), soft


def _valid_slot(project: Project, slot: int) -> bool:
    from .note import is_active
    return 0 <= slot < len(project.phrase) and is_active(project.phrase[slot])


def clear_phrase(project: Project) -> Project:
    if project.phrase == phrase_ops.EMPTY_PHRASE:
        return project
    return update(project, phrase=phrase_ops.EMPTY_PHRASE)


def clear_part(project: Project, wave: int, layer: int = None) -> Project:
    """指定パートの音符を消す。layer 指定でそのレイヤーだけ、None で全レイヤー。"""
    _check_part(wave)

    def drop(note):
        if note.wave != wave:
            return False
        return layer is None or note.layer == layer

    kept = [note for _, note in phrase_ops.active_notes(project.phrase)
            if not drop(note)]
    buffer = phrase_ops.build_phrase(kept)
    if buffer == project.phrase:
        return project
    return update(project, phrase=buffer)


def transpose(project: Project, semitones: int) -> Project:
    """メロディ系パートを半音単位で移調する。音域を外れる音は落とす。

    リズム (ノイズ) は音程を持たないので動かさない。
    """
    from .note import Note
    changed = False
    notes = []
    for _, note in phrase_ops.active_notes(project.phrase):
        if note.wave == WAVE_NOISE:
            notes.append(note)
            continue
        pitch = note.pitch + semitones
        if PITCH_MIN <= pitch <= PITCH_MAX:
            notes.append(Note(pitch, note.step, note.wave, note.dur,
                              note.layer, note.soft))
            if semitones:
                changed = True
        else:
            changed = True  # 範囲外は消える
    if not changed:
        return project
    return update(project, phrase=phrase_ops.build_phrase(notes))


def reverse_phrase(project: Project) -> Project:
    """フレーズを時間方向に反転する (逆行)。各パートを丸ごとひっくり返す。"""
    from .note import Note
    steps = steps_of(project)
    notes = []
    for _, note in phrase_ops.active_notes(project.phrase):
        if note.step >= steps:
            continue
        start = steps - (note.step + note.dur)
        if start < 0:
            start = 0
        dur = min(note.dur, steps - start)
        notes.append(Note(note.pitch, start, note.wave, dur, note.layer,
                          note.soft))
    buffer = phrase_ops.build_phrase(notes)
    if buffer == project.phrase:
        return project
    return update(project, phrase=buffer)


def _layer_counts(project: Project) -> tuple:
    return tuple(len(project.parts[wave]) for wave in range(PART_COUNT))


def generate_phrase(project: Project) -> Project:
    """現在の設定 (拍子・キー・音階・シード・進行・レイヤー数) からフレーズを自動作成する。"""
    buffer = compose_layers(project.beats, project.key, project.scale, project.seed,
                            _layer_counts(project), project.progression,
                            project.custom_scale)
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
    # 自動生成のパターンに分かりやすい既定名を付ける (ソング画面が読みやすくなる)
    default_names = ("Intro", "A", "B", "Outro")
    patterns = [Pattern(used=True, notes=buf,
                        name=default_names[i] if i < len(default_names) else "")
                for i, buf in enumerate(buffers)]
    patterns += list(project.patterns[len(buffers):])
    song = list(song_ops.EMPTY_SONG)
    for block, pattern_id in enumerate(layout):
        song[song_ops.cell_index(0, block)] = pattern_id
    return update(project, patterns=tuple(patterns), song=tuple(song),
                  phrase=buffers[1])


# ---- パターン (お気に入り) ----

def save_pattern(project: Project, slot: int, name: str = None) -> Project:
    """現在のフレーズをパターンスロットへ保存する。

    name=None のときは既存スロットの名前を引き継ぐ (上書き保存で名前を失わない)。
    """
    _check_pattern(slot)
    if name is None:
        name = project.patterns[slot].name
    name = _clean_name(name)
    patterns = list(project.patterns)
    patterns[slot] = Pattern(used=True, notes=project.phrase, name=name)
    return update(project, patterns=tuple(patterns))


def rename_pattern(project: Project, slot: int, name: str) -> Project:
    """パターンに名前を付ける。未使用スロット・無変更なら何もしない。"""
    _check_pattern(slot)
    pattern = project.patterns[slot]
    if not pattern.used:
        return project
    name = _clean_name(name)
    if name == pattern.name:
        return project
    patterns = list(project.patterns)
    patterns[slot] = Pattern(used=True, notes=pattern.notes, name=name)
    return update(project, patterns=tuple(patterns))


def duplicate_pattern(project: Project, slot: int):
    """パターンを空きスロットへ複製する。(新しい Project, 複製先) を返す。

    使用中でない・空きが無い場合は (元 Project, -1)。
    """
    _check_pattern(slot)
    source = project.patterns[slot]
    if not source.used:
        return project, -1
    dest = free_pattern_slot(project)
    if dest == -1:
        return project, -1
    name = _clean_name((source.name or "") + " 2") if source.name else ""
    patterns = list(project.patterns)
    patterns[dest] = Pattern(used=True, notes=source.notes, name=name)
    return update(project, patterns=tuple(patterns)), dest


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


def _clean_name(name) -> str:
    """名前を 1 行・前後空白なし・最大長に収める。"""
    from .constants import PATTERN_NAME_MAX
    text = " ".join(str(name).split())  # 改行・連続空白をつぶす
    return text[:PATTERN_NAME_MAX]


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
