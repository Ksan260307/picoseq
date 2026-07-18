"""音楽理論モジュールのテスト。"""

import unittest

from picoseq.core.constants import PITCH_COUNT, PITCH_MAX, PITCH_MIN
from picoseq.core.music import (
    KEY_NAMES,
    PITCH_MILLIHZ,
    SCALE_IDS,
    SCALES,
    chord_at,
    in_scale,
    note_name,
    pitch_millihz,
    root_note,
    scale_pitches,
)


class TestNames(unittest.TestCase):
    def test_note_names(self):
        self.assertEqual(note_name(60), "C4")
        self.assertEqual(note_name(69), "A4")
        self.assertEqual(note_name(36), "C2")
        self.assertEqual(note_name(84), "C6")
        self.assertEqual(note_name(61), "C#4")

    def test_key_names(self):
        self.assertEqual(len(KEY_NAMES), 12)
        self.assertEqual(KEY_NAMES[0], "C / Am")


class TestScales(unittest.TestCase):
    def test_four_scales(self):
        self.assertEqual(set(SCALE_IDS), {"major", "minor", "japanese", "battle"})

    def test_intervals_valid(self):
        for scale_id in SCALE_IDS:
            intervals = SCALES[scale_id]["intervals"]
            self.assertEqual(intervals[0], 0)
            for iv in intervals:
                self.assertTrue(0 <= iv < 12)
            self.assertEqual(list(intervals), sorted(intervals))

    def test_progression_degrees_valid(self):
        for scale_id in SCALE_IDS:
            n = len(SCALES[scale_id]["intervals"])
            for degree in SCALES[scale_id]["progression"]:
                self.assertTrue(0 <= degree < n)


class TestPhotoScale(unittest.TestCase):
    def test_get_scale_builtin(self):
        from picoseq.core.music import get_scale
        self.assertEqual(get_scale("minor"), SCALES["minor"])

    def test_get_scale_photo(self):
        from picoseq.core.music import get_scale
        scale = get_scale("photo", (0, 3, 7, 10))
        self.assertEqual(scale["intervals"], (0, 3, 7, 10))
        self.assertEqual(len(scale["progression"]), 4)
        for degree in scale["progression"]:
            self.assertTrue(0 <= degree < 4)

    def test_get_scale_photo_without_custom_raises(self):
        from picoseq.core.music import get_scale
        with self.assertRaises(ValueError):
            get_scale("photo")

    def test_functions_accept_custom(self):
        custom = (0, 3, 7)
        pitches = scale_pitches(0, "photo", custom=custom)
        self.assertTrue(pitches)
        for p in pitches:
            self.assertIn(p % 12, (0, 3, 7))
        self.assertTrue(in_scale(60, 0, "photo", custom))
        self.assertFalse(in_scale(61, 0, "photo", custom))
        chord = chord_at(0, "photo", 0, 4, custom=custom)
        self.assertEqual(chord.root, 48)

    def test_default_progression_short_scale(self):
        from picoseq.core.music import default_progression
        self.assertEqual(default_progression(3), (0, 2, 1, 2))
        for n in range(3, 13):
            for degree in default_progression(n):
                self.assertTrue(0 <= degree < n)


class TestFrequencies(unittest.TestCase):
    def test_table_length(self):
        self.assertEqual(len(PITCH_MILLIHZ), PITCH_COUNT)

    def test_a4_is_440hz(self):
        self.assertEqual(pitch_millihz(69), 440000)

    def test_monotonic(self):
        for a, b in zip(PITCH_MILLIHZ, PITCH_MILLIHZ[1:]):
            self.assertLess(a, b)

    def test_octave_doubles(self):
        for pitch in range(PITCH_MIN, PITCH_MAX - 12 + 1):
            low = pitch_millihz(pitch)
            high = pitch_millihz(pitch + 12)
            self.assertLessEqual(abs(high - low * 2), 2)  # 丸め誤差のみ


class TestScalePitches(unittest.TestCase):
    def test_sorted_and_in_range(self):
        for scale_id in SCALE_IDS:
            for key in (0, 5, 11):
                pitches = scale_pitches(key, scale_id)
                self.assertEqual(pitches, sorted(pitches))
                for p in pitches:
                    self.assertTrue(PITCH_MIN <= p <= PITCH_MAX)
                    self.assertTrue(in_scale(p, key, scale_id))

    def test_contains_root(self):
        for key in range(12):
            self.assertIn(root_note(key), scale_pitches(key, "minor"))

    def test_in_scale_rejects_outside(self):
        # C メジャーに C# は無い
        self.assertTrue(in_scale(60, 0, "major"))
        self.assertFalse(in_scale(61, 0, "major"))


class TestChords(unittest.TestCase):
    def test_minor_first_chord(self):
        chord = chord_at(0, "minor", 0, 4)
        self.assertEqual((chord.root, chord.third, chord.fifth), (48, 51, 55))

    def test_minor_second_chord_octave_bump(self):
        # 半小節 (8 ステップ) で度数 5 へ。3度・5度は折り返してオクターブ上げ。
        chord = chord_at(0, "minor", 8, 4)
        self.assertEqual((chord.root, chord.third, chord.fifth), (56, 60, 63))

    def test_progression_wraps(self):
        self.assertEqual(chord_at(0, "minor", 0, 4), chord_at(0, "minor", 32, 4))

    def test_key_shifts_chord(self):
        base = chord_at(0, "major", 0, 4)
        shifted = chord_at(2, "major", 0, 4)
        self.assertEqual(shifted.root, base.root + 2)
        self.assertEqual(shifted.third, base.third + 2)
        self.assertEqual(shifted.fifth, base.fifth + 2)

    def test_half_measure_boundary(self):
        # 3/4 拍子: 半小節 = 6 ステップ
        self.assertEqual(chord_at(0, "minor", 5, 3), chord_at(0, "minor", 0, 3))
        self.assertNotEqual(chord_at(0, "minor", 6, 3), chord_at(0, "minor", 0, 3))

    def test_custom_progression(self):
        """カスタム進行を渡すと既定進行の代わりに使われる。"""
        # 全ステップ同じ度数
        flat = (0, 0, 0, 0)
        for step in (0, 8, 16, 24):
            self.assertEqual(chord_at(0, "minor", step, 4, flat),
                             chord_at(0, "minor", 0, 4))
        # 度数 1 つだけの進行
        only_five = chord_at(0, "major", 0, 4, (4,))
        self.assertEqual(only_five.root, 48 + 7)  # G

    def test_custom_progression_wraps(self):
        custom = (0, 2)
        self.assertEqual(chord_at(0, "minor", 16, 4, custom),
                         chord_at(0, "minor", 0, 4, custom))


if __name__ == "__main__":
    unittest.main()
