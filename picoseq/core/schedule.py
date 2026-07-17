"""時刻計算とイベント展開。

Tick = 16分音符 1 個。時間はサンプル数 (整数) で扱い、環境差を持ち込まない。
イベント列は (tick, wave, pitch, dur) で整列するため、展開順によらず同一になる。
"""

from typing import NamedTuple

from .constants import EMPTY_CELL, SAMPLE_RATE, SONG_TRACKS
from .phrase import active_notes
from .project import Project, steps_of
from .song import get_cell, used_blocks


class Event(NamedTuple):
    tick: int
    pitch: int
    wave: int
    dur: int


def samples_per_tick(bpm: int, rate: int = SAMPLE_RATE) -> int:
    """1 Tick のサンプル数 (切り捨て)。"""
    return rate * 15 // bpm


def tick_seconds(bpm: int, rate: int = SAMPLE_RATE) -> float:
    """1 Tick の秒数 (表示・再生位置の計算用)。"""
    return samples_per_tick(bpm, rate) / rate


def phrase_ticks(project: Project) -> int:
    """フレーズ再生の総 Tick 数。"""
    return steps_of(project)


def song_ticks(project: Project) -> int:
    """ソング再生の総 Tick 数 (使用ブロックまで。空なら 1 ブロック分)。"""
    blocks = max(1, used_blocks(project.song))
    return blocks * steps_of(project)


def phrase_events(project: Project) -> list:
    """現在のフレーズをイベント列にする。"""
    steps = steps_of(project)
    events = []
    for _, note in active_notes(project.phrase):
        if note.step < steps:
            events.append(Event(note.step, note.pitch, note.wave, note.dur))
    events.sort()
    return events


def song_events(project: Project) -> list:
    """ソング構成全体をイベント列にする。"""
    steps = steps_of(project)
    blocks = used_blocks(project.song)
    events = []
    for track in range(SONG_TRACKS):
        for block in range(blocks):
            pattern_id = get_cell(project.song, track, block)
            if pattern_id == EMPTY_CELL:
                continue
            pattern = project.patterns[pattern_id]
            if not pattern.used:
                continue
            for _, note in active_notes(pattern.notes):
                if note.step < steps:
                    events.append(Event(block * steps + note.step, note.pitch, note.wave, note.dur))
    events.sort()
    return events
