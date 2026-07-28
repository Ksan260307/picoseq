"""保存形式 — バージョン付き JSON の読み書きと、旧版セーブデータの移行。

保存データには必ずアプリ ID と形式バージョンを含める。
別アプリのデータ・新しすぎるバージョンは読み込みを拒否する。
数値は読み込み時に必ず範囲へ収め、範囲外の音符は捨てる。
"""

import json

from .constants import (
    APP_ID,
    BEATS_MAX,
    BEATS_MIN,
    BPM_MAX,
    BPM_MIN,
    EMPTY_CELL,
    MAX_LAYERS,
    MAX_STEPS,
    PART_COUNT,
    PATTERN_COUNT,
    PITCH_MAX,
    PITCH_MIN,
    PROGRESSION_MAX_LEN,
    SCHEMA_VERSION,
    SEED_MAX,
    SEED_MIN,
    SONG_BLOCKS,
    SONG_TRACKS,
    clamp,
)
from .constants import CUSTOM_SCALE_MIN, DEFAULT_SOUND, SOUND_SETS
from .music import DEFAULT_SCALE, PHOTO_SCALE, SCALES, get_scale
from .note import SOFT_LEVELS, Note, is_active, unpack_note
from .phrase import active_notes, build_phrase
from .project import PartParams, Pattern, Project
from .song import EMPTY_SONG


class LoadError(ValueError):
    """読み込めないデータ。"""


# ---- 符号化 ----

def to_jsonable(project: Project) -> dict:
    """Project を JSON にできる辞書へ。音符は [pitch, step, wave, dur] で持つ。"""
    return {
        "app": APP_ID,
        "schema": SCHEMA_VERSION,
        "bpm": project.bpm,
        "beats": project.beats,
        "key": project.key,
        "scale": project.scale,
        "seed": project.seed,
        "progression": list(project.progression) if project.progression is not None else None,
        "custom_scale": list(project.custom_scale) if project.custom_scale is not None else None,
        "sound": project.sound,
        # parts[wave] = レイヤーごとの {tone, gate, volume} の並び
        "parts": [[{"tone": p.tone, "gate": p.gate, "volume": p.volume}
                   for p in layers] for layers in project.parts],
        "phrase": _notes_to_json(project.phrase),
        "patterns": [
            {"used": p.used, "notes": _notes_to_json(p.notes), "name": p.name}
            for p in project.patterns
        ],
        "song": [-1 if cell == EMPTY_CELL else cell for cell in project.song],
    }


def dumps(project: Project) -> str:
    """Project を JSON 文字列へ。"""
    return json.dumps(to_jsonable(project), ensure_ascii=False)


def _notes_to_json(buffer: tuple) -> list:
    """音符を配列にする。強弱が無い音符は 5 要素のまま (旧版でもそのまま読める)。"""
    out = []
    for _, n in active_notes(buffer):
        item = [n.pitch, n.step, n.wave, n.dur, n.layer]
        if n.soft:
            item.append(n.soft)
        out.append(item)
    return out


# ---- 復号 ----

def loads(text: str) -> Project:
    """JSON 文字列から Project を復元する。旧版 (main.html) の形式も受け付ける。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise LoadError(f"JSON を読めません: {e}") from e
    if not isinstance(data, dict):
        raise LoadError("プロジェクトデータではありません。")
    if "currentBuffer" in data:
        return from_legacy(data)
    return from_jsonable(data)


def from_jsonable(data: dict) -> Project:
    """辞書から Project を復元する。範囲外の値は収めるか捨てる。"""
    if data.get("app") != APP_ID:
        raise LoadError("このアプリの保存データではありません。")
    schema = data.get("schema")
    if not isinstance(schema, int) or schema < 1:
        raise LoadError("スキーマ版が不正です。")
    if schema > SCHEMA_VERSION:
        raise LoadError(f"新しい形式 (schema {schema}) です。アプリを更新してください。")

    custom_scale = _custom_scale_from_json(data.get("custom_scale"))
    scale = data.get("scale")
    if scale == PHOTO_SCALE:
        if custom_scale is None:
            scale = DEFAULT_SCALE  # フォト音階が壊れていたら既定へ
    elif scale not in SCALES:
        scale = DEFAULT_SCALE

    beats = clamp(_as_int(data.get("beats"), 4), BEATS_MIN, BEATS_MAX)
    phrase_notes = _notes_list_from_json(data.get("phrase"))

    patterns = []
    raw_patterns = _as_list(data.get("patterns"), PATTERN_COUNT)
    for i in range(PATTERN_COUNT):
        entry = raw_patterns[i] if isinstance(raw_patterns[i], dict) else {}
        used = bool(entry.get("used"))
        notes = _notes_from_json(entry.get("notes"))
        patterns.append(Pattern(used=used, notes=notes, name=_name_from_json(entry.get("name"))))

    return Project(
        bpm=clamp(_as_int(data.get("bpm"), 120), BPM_MIN, BPM_MAX),
        beats=beats,
        key=clamp(_as_int(data.get("key"), 0), 0, 11),
        scale=scale,
        seed=clamp(_as_int(data.get("seed"), SEED_MIN), SEED_MIN, SEED_MAX),
        progression=_progression_from_json(data.get("progression"), scale, custom_scale),
        custom_scale=custom_scale,
        sound=data.get("sound") if data.get("sound") in SOUND_SETS else DEFAULT_SOUND,
        parts=_cover_layers(_parts_from_json(data.get("parts")), phrase_notes),
        phrase=build_phrase(phrase_notes),
        patterns=tuple(patterns),
        song=_song_from_json(data.get("song")),
    )


def _progression_from_json(raw, scale: str, custom_scale=None):
    """カスタム進行の検証。不正なら None (音階の既定) に落とす。

    schema 1 のデータには存在しないので、常に None になる (後方互換)。
    """
    if not isinstance(raw, list) or not (1 <= len(raw) <= PROGRESSION_MAX_LEN):
        return None
    n = len(get_scale(scale, custom_scale)["intervals"])
    degrees = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value < n):
            return None
        degrees.append(value)
    return tuple(degrees)


def _custom_scale_from_json(raw):
    """フォト音階の検証。0 を含む昇順・重複なしの半音列でなければ None。

    schema 1・2 のデータには存在しないので、常に None になる (後方互換)。
    """
    if not isinstance(raw, list):
        return None
    values = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value <= 11):
            return None
        values.append(value)
    normalized = tuple(sorted(set(values)))
    if len(normalized) < CUSTOM_SCALE_MIN or normalized[0] != 0:
        return None
    return normalized


def _as_int(value, fallback: int) -> int:
    """整数として読む。数でなければ既定値。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return int(value)


def _as_list(value, length: int) -> list:
    """決まった長さのリストにする (足りない分は None)。"""
    items = list(value) if isinstance(value, list) else []
    items += [None] * (length - len(items))
    return items[:length]


def _name_from_json(value) -> str:
    """パターン名を復元する。文字列以外・schema 5 以前 (name 無し) は空文字。"""
    from .constants import PATTERN_NAME_MAX
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:PATTERN_NAME_MAX]


def _valid_note(pitch: int, step: int, wave: int, dur: int, layer: int = 0,
                soft: int = 0):
    """範囲内なら Note、範囲外なら None。dur はグリッド内に収める。"""
    if not (PITCH_MIN <= pitch <= PITCH_MAX):
        return None
    if not (0 <= step < MAX_STEPS):
        return None
    if not (0 <= wave < PART_COUNT):
        return None
    if not (0 <= layer < MAX_LAYERS):
        layer = 0
    if not (0 <= soft < SOFT_LEVELS):
        soft = 0                       # 壊れた値は「そのままの音量」に寄せる
    return Note(pitch, step, wave, clamp(dur, 1, 255), layer, soft)


def _notes_list_from_json(raw) -> list:
    """音符リストを Note の列にする。

    4 要素 (旧) は layer=0、5 要素は layer 付き、6 要素 (schema 8 以降) は
    強弱 (soft) 付き。足りない要素は 0 = 「そのままの音量」で補うので、
    旧データの音は変わらない。
    """
    notes = []
    if isinstance(raw, list):
        for item in raw:
            if not (isinstance(item, list) and len(item) in (4, 5, 6)
                    and all(isinstance(v, int) and not isinstance(v, bool) for v in item)):
                continue
            layer = item[4] if len(item) >= 5 else 0
            soft = item[5] if len(item) >= 6 else 0
            note = _valid_note(item[0], item[1], item[2], item[3], layer, soft)
            if note is not None:
                notes.append(note)
    return notes


def _notes_from_json(raw) -> tuple:
    return build_phrase(_notes_list_from_json(raw))


def _parts_from_json(raw) -> tuple:
    """パート設定を復元する。新形式はレイヤーの並び、旧 (v4以前) は単一 dict。"""
    per_wave = _as_list(raw, PART_COUNT)
    parts = []
    for i in range(PART_COUNT):
        entry = per_wave[i]
        if isinstance(entry, list):
            layer_dicts = entry
        elif isinstance(entry, dict):
            layer_dicts = [entry]  # 旧形式: パートに 1 レイヤー
        else:
            layer_dicts = [{}]
        layers = []
        for d in layer_dicts[:MAX_LAYERS]:
            d = d if isinstance(d, dict) else {}
            tone = clamp(_as_int(d.get("tone"), 50), 0, 100)
            gate = clamp(_as_int(d.get("gate"), 80), 10, 100)
            volume = clamp(_as_int(d.get("volume"), 100), 0, 100)  # 旧データは 100
            layers.append(PartParams(tone=tone, gate=gate, volume=volume))
        parts.append(tuple(layers) if layers else (PartParams(),))
    return tuple(parts)


def _cover_layers(parts: tuple, notes: list) -> tuple:
    """音符が使うレイヤーを必ずパートが持つよう、足りない分を補う。"""
    max_layer = [0] * PART_COUNT
    for note in notes:
        if note.layer > max_layer[note.wave]:
            max_layer[note.wave] = note.layer
    out = []
    for wave in range(PART_COUNT):
        layers = list(parts[wave])
        while len(layers) <= max_layer[wave] and len(layers) < MAX_LAYERS:
            layers.append(layers[-1])
        out.append(tuple(layers))
    return tuple(out)


def _song_from_json(raw) -> tuple:
    """ソング構成を復元する (範囲外は空きマスへ)。"""
    cells = []
    items = _as_list(raw, SONG_TRACKS * SONG_BLOCKS)
    for value in items:
        cell = _as_int(value, -1)
        cells.append(cell if 0 <= cell < PATTERN_COUNT else EMPTY_CELL)
    return tuple(cells)


# ---- 旧版 (main.html) からの移行 ----

def from_legacy(data: dict) -> Project:
    """旧アプリの保存データ (retro_project.json / localStorage) を移行する。

    旧形式は音符をパック済み 32bit 整数の配列で持つ。ビットレイアウトは
    本アプリと同一なので、展開して検証してから詰め直す。
    """
    beats = clamp(_as_int(data.get("beats"), 4), BEATS_MIN, BEATS_MAX)
    phrase = _legacy_buffer(data.get("currentBuffer"))

    used_flags = _as_list(data.get("isUsed"), PATTERN_COUNT)
    raw_favorites = _as_list(data.get("favorites"), PATTERN_COUNT)
    patterns = []
    for i in range(PATTERN_COUNT):
        notes = _legacy_buffer(raw_favorites[i])
        patterns.append(Pattern(used=bool(used_flags[i]), notes=notes))

    song = _song_from_legacy(data.get("songGrid"))
    parts = _parts_from_legacy(data.get("partSettings"))

    return Project(beats=beats, phrase=phrase, patterns=tuple(patterns),
                   song=song, parts=parts)


def _legacy_buffer(raw) -> tuple:
    """旧版の音符バッファを読む。"""
    notes = []
    if isinstance(raw, list):
        for value in raw:
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            if not is_active(value):
                continue
            n = unpack_note(value)
            note = _valid_note(n.pitch, n.step, n.wave, n.dur)
            if note is not None:
                notes.append(note)
    return build_phrase(notes)


def _song_from_legacy(raw) -> tuple:
    """旧版のソング構成を読む。"""
    if not isinstance(raw, list):
        return EMPTY_SONG
    cells = []
    items = _as_list(raw, SONG_TRACKS * SONG_BLOCKS)
    for value in items:
        cell = _as_int(value, EMPTY_CELL)
        cells.append(cell if 0 <= cell < PATTERN_COUNT else EMPTY_CELL)
    return tuple(cells)


def _parts_from_legacy(raw) -> tuple:
    """旧版のパート設定を読む (レイヤー 1 つとして扱う)。"""
    parts = []
    for i in range(PART_COUNT):
        entry = None
        if isinstance(raw, dict):
            entry = raw.get(str(i), raw.get(i))
        if not isinstance(entry, dict):
            entry = {}
        tone = entry.get("tone")
        gate = entry.get("length")
        tone = int(round(tone * 100)) if isinstance(tone, (int, float)) and not isinstance(tone, bool) else 50
        gate = int(round(gate * 100)) if isinstance(gate, (int, float)) and not isinstance(gate, bool) else 80
        # 旧データはパートあたり 1 レイヤー
        parts.append((PartParams(tone=clamp(tone, 0, 100), gate=clamp(gate, 10, 100)),))
    return tuple(parts)
