"""自動作成のテスト — 決定論と音楽的な不変条件。"""

import unittest

from picoseq.core.composer import DRUM_PITCH, compose
from picoseq.core.constants import (
    MAX_NOTES,
    PITCH_MAX,
    PITCH_MIN,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
    steps_per_phrase,
)
from picoseq.core.music import SCALE_IDS, in_scale
from picoseq.core.phrase import active_notes, count_notes

ALL_CASES = [(beats, key, scale_id, seed)
             for beats in (3, 4, 7)
             for key in (0, 7)
             for scale_id in SCALE_IDS
             for seed in (1, 99)]


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        for case in ALL_CASES:
            with self.subTest(case=case):
                self.assertEqual(compose(*case), compose(*case))

    def test_different_seeds_differ(self):
        for seed_a, seed_b in [(1, 2), (10, 11), (500, 501)]:
            with self.subTest(seeds=(seed_a, seed_b)):
                self.assertNotEqual(compose(4, 0, "minor", seed_a),
                                    compose(4, 0, "minor", seed_b))

    def test_default_progression_matches_none(self):
        """progression 省略と None 指定は同一 (既存ゴールデンの保全)。"""
        self.assertEqual(compose(4, 0, "minor", 42),
                         compose(4, 0, "minor", 42, None))

    def test_custom_progression_changes_output(self):
        default = compose(4, 0, "minor", 42)
        custom = compose(4, 0, "minor", 42, (3, 3, 3, 3))
        self.assertNotEqual(default, custom)

    def test_custom_progression_deterministic(self):
        self.assertEqual(compose(4, 0, "major", 9, (0, 4, 5, 3)),
                         compose(4, 0, "major", 9, (0, 4, 5, 3)))


class TestInvariants(unittest.TestCase):
    def test_notes_within_bounds(self):
        for case in ALL_CASES:
            steps = steps_per_phrase(case[0])
            with self.subTest(case=case):
                buffer = compose(*case)
                self.assertLessEqual(count_notes(buffer), MAX_NOTES)
                for _, note in active_notes(buffer):
                    self.assertTrue(PITCH_MIN <= note.pitch <= PITCH_MAX)
                    self.assertTrue(0 <= note.step < steps)
                    self.assertGreaterEqual(note.dur, 1)
                    self.assertLessEqual(note.step + note.dur, steps)

    def test_all_parts_present(self):
        for scale_id in SCALE_IDS:
            with self.subTest(scale=scale_id):
                buffer = compose(4, 0, scale_id, 5)
                waves = {note.wave for _, note in active_notes(buffer)}
                self.assertEqual(waves, {WAVE_PULSE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW})

    def test_melody_stays_in_scale(self):
        for scale_id in SCALE_IDS:
            for key in (0, 7):
                with self.subTest(scale=scale_id, key=key):
                    buffer = compose(4, key, scale_id, 3)
                    for _, note in active_notes(buffer):
                        if note.wave == WAVE_PULSE:
                            self.assertTrue(in_scale(note.pitch, key, scale_id),
                                            f"{note.pitch} がスケール外")

    def test_drums_have_fixed_pitch(self):
        buffer = compose(4, 0, "minor", 8)
        for _, note in active_notes(buffer):
            if note.wave == WAVE_NOISE:
                self.assertEqual(note.pitch, DRUM_PITCH)


class TestStyles(unittest.TestCase):
    def test_battle_bass_is_driving(self):
        """ボス戦のベースは偶数ステップを刻む。"""
        buffer = compose(4, 0, "battle", 12)
        bass_steps = sorted(note.step for _, note in active_notes(buffer)
                            if note.wave == WAVE_TRIANGLE)
        self.assertEqual(bass_steps, [s for s in range(32) if s % 2 == 0])

    def test_battle_backing_is_arpeggio(self):
        """ボス戦のサブは全ステップのアルペジオ。"""
        buffer = compose(4, 0, "battle", 12)
        backing = [note for _, note in active_notes(buffer) if note.wave == WAVE_SAW]
        self.assertEqual(len(backing), 32)

    def test_japanese_drum_anchor(self):
        """和風のリズムは小節頭に長い一打を置く。"""
        buffer = compose(4, 0, "japanese", 12)
        drums = {note.step: note for _, note in active_notes(buffer)
                 if note.wave == WAVE_NOISE}
        self.assertIn(0, drums)
        self.assertEqual(drums[0].dur, 4)
        self.assertIn(14, drums)  # 小節末 (16-2)

    def test_straight_beat_has_downbeats(self):
        """通常拍子のリズムは小節頭と 4 分刻みを打つ。"""
        buffer = compose(4, 0, "minor", 12)
        drum_steps = {note.step for _, note in active_notes(buffer)
                      if note.wave == WAVE_NOISE}
        for step in (0, 4, 8, 12, 16, 20, 24, 28):
            self.assertIn(step, drum_steps)


if __name__ == "__main__":
    unittest.main()
