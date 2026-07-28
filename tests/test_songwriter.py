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
    INTRO_PARTS,
    OUTRO_PARTS,
    PATTERN_ROLES,
    SONG_BLOCKS,
    SONG_LAYOUTS,
    filter_waves,
    song_shape,
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
        for seed in range(1, 31):
            buffers, layout = write_song(4, 0, "minor", seed)
            with self.subTest(seed=seed):
                self.assertEqual(len(buffers), 4)
                self.assertEqual(len(PATTERN_ROLES), 4)
                self.assertEqual(len(layout), SONG_BLOCKS)
                self.assertEqual(set(layout), {0, 1, 2, 3})  # 全パターンを使う
                for buffer in buffers:
                    self.assertGreater(count_notes(buffer), 0)

    def test_intro_has_no_melody(self):
        """イントロは主役を出さない (メロディは A メロで初めて鳴る)。"""
        for seed in range(1, 31):
            buffers, _ = write_song(4, 0, "minor", seed)
            with self.subTest(seed=seed):
                waves = {n.wave for _, n in active_notes(buffers[0])}
                self.assertNotIn(WAVE_PULSE, waves)
                self.assertTrue(waves)

    def test_outro_is_a_fade(self):
        """アウトロは余韻 — メロディを残し、リズムは入れない。"""
        for seed in range(1, 31):
            buffers, _ = write_song(4, 0, "minor", seed)
            with self.subTest(seed=seed):
                waves = {n.wave for _, n in active_notes(buffers[3])}
                self.assertIn(WAVE_PULSE, waves)
                self.assertNotIn(WAVE_NOISE, waves)

    def test_a_and_b_differ(self):
        for seed in (7, 42, 1234):
            buffers, _ = write_song(4, 0, "minor", seed)
            with self.subTest(seed=seed):
                self.assertNotEqual(buffers[1], buffers[2])

    def test_deterministic(self):
        self.assertEqual(write_song(4, 3, "major", 42), write_song(4, 3, "major", 42))

    def test_every_layout_is_well_formed(self):
        """どの並びも 16 ブロックで、イントロで始まりアウトロで終わる。"""
        for i, layout in enumerate(SONG_LAYOUTS):
            with self.subTest(layout=i):
                self.assertEqual(len(layout), SONG_BLOCKS)
                self.assertEqual(layout[0], 0)
                self.assertEqual(layout[-1], 3)
                self.assertEqual(set(layout), {0, 1, 2, 3})
                # A メロと B メロで全体の半分以上を占める (イントロ/アウトロは脇役)
                main = sum(1 for p in layout if p in (1, 2))
                self.assertGreater(main, SONG_BLOCKS // 2)


class TestSongShape(unittest.TestCase):
    """曲の形はシード値で選ばれる — 構成が定数だと展開が毎回同じになる。"""

    def test_deterministic(self):
        for seed in (1, 99, 40000):
            self.assertEqual(song_shape(seed), song_shape(seed))

    def test_all_shapes_are_reachable(self):
        layouts, intros, outros, combos = set(), set(), set(), set()
        for seed in range(1, 601):
            layout, intro, outro = song_shape(seed)
            layouts.add(layout)
            intros.add(intro)
            outros.add(outro)
            combos.add((layout, intro, outro))
        self.assertEqual(len(layouts), len(SONG_LAYOUTS))
        self.assertEqual(len(intros), len(INTRO_PARTS))
        self.assertEqual(len(outros), len(OUTRO_PARTS))
        self.assertEqual(len(combos),
                         len(SONG_LAYOUTS) * len(INTRO_PARTS) * len(OUTRO_PARTS))

    def test_seeds_give_different_songs(self):
        """近いシード値でも同じ形に固まらない。"""
        shapes = {song_shape(seed) for seed in range(1, 21)}
        self.assertGreaterEqual(len(shapes), 10)

    def test_intro_never_keeps_the_melody(self):
        for parts in INTRO_PARTS:
            self.assertNotIn(WAVE_PULSE, parts)

    def test_outro_never_keeps_the_drums(self):
        for parts in OUTRO_PARTS:
            self.assertNotIn(WAVE_NOISE, parts)
            self.assertIn(WAVE_PULSE, parts)


class TestGenerateSongAction(unittest.TestCase):
    def test_fills_patterns_and_grid(self):
        p = actions.generate_song(actions.set_seed(new_project(), 7))
        self.assertEqual(used_blocks(p.song), SONG_BLOCKS)
        self.assertTrue(all(pattern.used for pattern in p.patterns[:4]))
        layout, _, _ = song_shape(7)
        for block, pattern_id in enumerate(layout):
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
