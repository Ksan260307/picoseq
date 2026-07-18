"""ソング自動作成のテスト — 構成・決定論・パート抜き出し。"""

import unittest

from picoseq.core import actions
from picoseq.core.constants import (
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
)
from picoseq.core.note import Note
from picoseq.core.phrase import active_notes, build_phrase, count_notes
from picoseq.core.project import new_project
from picoseq.core.song import get_cell, used_blocks
from picoseq.core.songwriter import (
    PATTERN_ROLES,
    SONG_LAYOUT,
    filter_waves,
    write_song,
)


class TestFilterWaves(unittest.TestCase):
    def test_keeps_only_selected_parts(self):
        buffer = build_phrase([
            Note(60, 0, WAVE_PULSE, 1), Note(48, 0, WAVE_TRIANGLE, 2),
            Note(60, 2, WAVE_NOISE, 1), Note(55, 3, WAVE_SAW, 1),
        ])
        filtered = filter_waves(buffer, {WAVE_TRIANGLE, WAVE_NOISE})
        waves = {n.wave for _, n in active_notes(filtered)}
        self.assertEqual(waves, {WAVE_TRIANGLE, WAVE_NOISE})
        self.assertEqual(count_notes(filtered), 2)

    def test_empty_selection(self):
        buffer = build_phrase([Note(60, 0, WAVE_PULSE, 1)])
        self.assertEqual(count_notes(filter_waves(buffer, set())), 0)


class TestWriteSong(unittest.TestCase):
    def test_four_patterns_and_layout(self):
        buffers, layout = write_song(4, 0, "minor", 7)
        self.assertEqual(len(buffers), 4)
        self.assertEqual(len(PATTERN_ROLES), 4)
        self.assertEqual(layout, SONG_LAYOUT)
        self.assertEqual(len(layout), 16)
        for pattern_id in layout:
            self.assertTrue(0 <= pattern_id < 4)
        for buffer in buffers:
            self.assertGreater(count_notes(buffer), 0)

    def test_intro_has_no_melody(self):
        buffers, _ = write_song(4, 0, "minor", 7)
        intro_waves = {n.wave for _, n in active_notes(buffers[0])}
        self.assertNotIn(WAVE_PULSE, intro_waves)
        self.assertNotIn(WAVE_SAW, intro_waves)

    def test_outro_is_melody_and_bass(self):
        buffers, _ = write_song(4, 0, "minor", 7)
        outro_waves = {n.wave for _, n in active_notes(buffers[3])}
        self.assertLessEqual(outro_waves, {WAVE_PULSE, WAVE_TRIANGLE})

    def test_a_and_b_differ(self):
        buffers, _ = write_song(4, 0, "minor", 7)
        self.assertNotEqual(buffers[1], buffers[2])

    def test_deterministic(self):
        self.assertEqual(write_song(4, 3, "major", 42), write_song(4, 3, "major", 42))

    def test_layout_starts_with_intro_ends_with_outro(self):
        self.assertEqual(SONG_LAYOUT[0], 0)
        self.assertEqual(SONG_LAYOUT[-1], 3)


class TestGenerateSongAction(unittest.TestCase):
    def test_fills_patterns_and_grid(self):
        p = actions.generate_song(actions.set_seed(new_project(), 7))
        self.assertEqual(used_blocks(p.song), 16)
        self.assertTrue(all(pattern.used for pattern in p.patterns[:4]))
        for block, pattern_id in enumerate(SONG_LAYOUT):
            self.assertEqual(get_cell(p.song, 0, block), pattern_id)

    def test_preserves_slots_5_to_8(self):
        p = new_project()
        p, _ = actions.place_note(p, 60, 0, 0)
        p = actions.save_pattern(p, 5)
        kept = p.patterns[5]
        p = actions.generate_song(p)
        self.assertEqual(p.patterns[5], kept)
        self.assertFalse(p.patterns[4].used)

    def test_phrase_opens_a_melody(self):
        p = actions.generate_song(actions.set_seed(new_project(), 7))
        self.assertEqual(p.phrase, p.patterns[1].notes)

    def test_deterministic(self):
        a = actions.generate_song(actions.set_seed(new_project(), 9))
        b = actions.generate_song(actions.set_seed(new_project(), 9))
        self.assertEqual(a, b)

    def test_roundtrip(self):
        from picoseq.core.serialize import dumps, loads
        p = actions.generate_song(actions.set_seed(new_project(), 11))
        self.assertEqual(loads(dumps(p)), p)


if __name__ == "__main__":
    unittest.main()
