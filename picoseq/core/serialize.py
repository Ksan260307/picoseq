"""保存形式 — 版付き JSON の符号化・復号と、旧版セーブデータの移行。

保存データには必ずアプリ ID とスキーマ版を含める (再生同一性)。
未知のアプリ ID・新しすぎるスキーマ版は拒否する。
数値は復号時に必ず範囲へ収め、範囲外の音符は捨てる。
"""

import json

from .constants import (
    APP_ID,
    BEATS_MAX,
    BEATS_MIN,
    BPM_MAX,
    BPM_MIN,
    EMPTY_CELL,
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
from .music import DEFAULT_SCALE, SCALES
from .note import Note, is_active, unpack_note
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
        "parts": [{"tone": p.tone, "gate": p.gate} for p in project.parts],
        "phrase": _notes_to_json(project.phrase),
        "patterns": [
            {"used": p.used, "notes": _notes_to_json(p.notes)} for p in project.patterns
        ],
        "song": [-1 if cell == EMPTY_CELL else cell for cell in project.song],
    }


def dumps(project: Project) -> str:
    """Project を JSON 文字列へ。"""
    return json.dumps(to_jsonable(project), ensure_ascii=False)


def _notes_to_json(buffer: tuple) -> list:
    return [[n.pitch, n.step, n.wave, n.dur] for _, n in active_notes(buffer)]


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

    scale = data.get("scale")
    if scale not in SCALES:
        scale = DEFAULT_SCALE

    beats = clamp(_as_int(data.get("beats"), 4), BEATS_MIN, BEATS_MAX)

    patterns = []
    raw_patterns = _as_list(data.get("patterns"), PATTERN_COUNT)
    for i in range(PATTERN_COUNT):
        entry = raw_patterns[i] if isinstance(raw_patterns[i], dict) else {}
        used = bool(entry.get("used"))
        notes = _notes_from_json(entry.get("notes"))
        patterns.append(Pattern(used=used, notes=notes))

    return Project(
        bpm=clamp(_as_int(data.get("bpm"), 120), BPM_MIN, BPM_MAX),
        beats=beats,
        key=clamp(_as_int(data.get("key"), 0), 0, 11),
        scale=scale,
        seed=clamp(_as_int(data.get("seed"), SEED_MIN), SEED_MIN, SEED_MAX),
        progression=_progression_from_json(data.get("progression"), scale),
        parts=_parts_from_json(data.get("parts")),
        phrase=_notes_from_json(data.get("phrase")),
        patterns=tuple(patterns),
        song=_song_from_json(data.get("song")),
    )


def _progression_from_json(raw, scale: str):
    """カスタム進行の検証。不正なら None (スケール既定) に落とす。

    schema 1 のデータには存在しないので、常に None になる (後方互換)。
    """
    if not isinstance(raw, list) or not (1 <= len(raw) <= PROGRESSION_MAX_LEN):
        return None
    n = len(SCALES[scale]["intervals"])
    degrees = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or not (0 <= value < n):
            return None
        degrees.append(value)
    return tuple(degrees)


def _as_int(value, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return int(value)


def _as_list(value, length: int) -> list:
    items = list(value) if isinstance(value, list) else []
    items += [None] * (length - len(items))
    return items[:length]


def _valid_note(pitch: int, step: int, wave: int, dur: int):
    """範囲内なら Note、範囲外なら None。dur はグリッド内に収める。"""
    if not (PITCH_MIN <= pitch <= PITCH_MAX):
        return None
    if not (0 <= step < MAX_STEPS):
        return None
    if not (0 <= wave < PART_COUNT):
        return None
    return Note(pitch, step, wave, clamp(dur, 1, 255))


def _notes_from_json(raw) -> tuple:
    notes = []
    if isinstance(raw, list):
        for item in raw:
            if not (isinstance(item, list) and len(item) == 4
                    and all(isinstance(v, int) and not isinstance(v, bool) for v in item)):
                continue
            note = _valid_note(item[0], item[1], item[2], item[3])
            if note is not None:
                notes.append(note)
    return build_phrase(notes)


def _parts_from_json(raw) -> tuple:
    parts = []
    items = _as_list(raw, PART_COUNT)
    for i in range(PART_COUNT):
        entry = items[i] if isinstance(items[i], dict) else {}
        tone = clamp(_as_int(entry.get("tone"), 50), 0, 100)
        gate = clamp(_as_int(entry.get("gate"), 80), 10, 100)
        parts.append(PartParams(tone=tone, gate=gate))
    return tuple(parts)


def _song_from_json(raw) -> tuple:
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
    if not isinstance(raw, list):
        return EMPTY_SONG
    cells = []
    items = _as_list(raw, SONG_TRACKS * SONG_BLOCKS)
    for value in items:
        cell = _as_int(value, EMPTY_CELL)
        cells.append(cell if 0 <= cell < PATTERN_COUNT else EMPTY_CELL)
    return tuple(cells)


def _parts_from_legacy(raw) -> tuple:
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
        parts.append(PartParams(tone=clamp(tone, 0, 100), gate=clamp(gate, 10, 100)))
    return tuple(parts)
