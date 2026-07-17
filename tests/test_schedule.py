"""時刻計算とイベント展開のテスト。"""

import unittest

from picoseq.core import actions
from picoseq.core.constants import EMPTY_CELL
from picoseq.core.note import Note
from picoseq.core.phrase import build_phrase
from picoseq.core.project import Pattern, new_project, steps_of, update
from picoseq.core.schedule import (
    Event,
    phrase_events,
    phrase_ticks,
    samples_per_tick,
    song_events,
    song_ticks,
    tick_seconds,
)
from picoseq.core.song import EMPTY_SONG, set_cell


class TestTiming(unittest.TestCase):
    def test_samples_per_tick(self):
        self.assertEqual(samples_per_tick(120, 44100), 5512)
        self.assertEqual(samples_per_tick(60, 44100), 11025)
        self.assertEqual(samples_per_tick(240, 44100), 2756)

    def test_tick_seconds_matches_samples(self):
        self.assertAlmostEqual(tick_seconds(120), 5512 / 44100)


class TestPhraseEvents(unittest.TestCase):
    def test_ticks(self):
        p = new_project()
        self.assertEqual(phrase_ticks(p), 32)
        self.assertEqual(phrase_ticks(actions.set_beats(p, 7)), 56)

    def test_events_sorted_and_complete(self):
        p = new_project()
        p, _ = actions.place_note(p, 60, 4, 0, dur=2)
        p, _ = actions.place_note(p, 48, 0, 1)
        events = phrase_events(p)
        self.assertEqual(events, [Event(0, 48, 1, 1), Event(4, 60, 0, 2)])

    def test_note_beyond_grid_excluded(self):
        """拍子を縮めた後、グリッド外に残った音符は鳴らさない (旧版と同じ)。"""
        p = new_project()
        buffer = build_phrase([Note(60, 40, 0, 1), Note(62, 3, 0, 1)])
        p = update(p, phrase=buffer)  # steps=32 なので step40 は外
        events = phrase_events(p)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].tick, 3)


class TestSongEvents(unittest.TestCase):
    def _project_with_pattern(self):
        p = new_project()
        p, _ = actions.place_note(p, 60, 0, 0, dur=2)
        p, _ = actions.place_note(p, 48, 4, 1)
        return actions.save_pattern(p, 0)

    def test_ticks_empty_song(self):
        p = new_project()
        self.assertEqual(song_ticks(p), steps_of(p))  # 最低 1 ブロックぶん

    def test_ticks_follow_used_blocks(self):
        p = self._project_with_pattern()
        p = actions.toggle_song_cell(p, 0, 3, 0)
        self.assertEqual(song_ticks(p), 4 * steps_of(p))

    def test_block_offset(self):
        p = self._project_with_pattern()
        p = actions.toggle_song_cell(p, 0, 2, 0)
        events = song_events(p)
        steps = steps_of(p)
        self.assertEqual(events, [Event(2 * steps + 0, 60, 0, 2),
                                  Event(2 * steps + 4, 48, 1, 1)])

    def test_tracks_merge_sorted(self):
        p = self._project_with_pattern()
        p = actions.toggle_song_cell(p, 0, 0, 0)
        p = actions.toggle_song_cell(p, 3, 0, 0)
        events = song_events(p)
        self.assertEqual(len(events), 4)
        self.assertEqual(events, sorted(events))

    def test_unused_pattern_reference_skipped(self):
        """グリッドが未使用パターンを指していても鳴らさない (防御)。"""
        p = new_project()
        song = set_cell(EMPTY_SONG, 0, 0, 5)  # パターン5 は未使用
        p = update(p, song=song)
        self.assertEqual(song_events(p), [])
        self.assertEqual(song_ticks(p), steps_of(p))

    def test_empty_cell_skipped(self):
        p = self._project_with_pattern()
        p = actions.toggle_song_cell(p, 0, 1, 0)
        events = song_events(p)
        for event in events:
            self.assertGreaterEqual(event.tick, steps_of(p))
        self.assertEqual(EMPTY_CELL, 255)


if __name__ == "__main__":
    unittest.main()
