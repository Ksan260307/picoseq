"""音楽理論モジュールのテスト。"""

import unittest

from picoseq.core.constants import PITCH_COUNT, PITCH_MAX, PITCH_MIN
from picoseq.core.music import (
    KEY_NAMES,
    PITCH_MILLIHZ,
    SCALE_IDS,
    SCALE_PROGRESSIONS,
    SCALES,
    chord_at,
    in_scale,
    note_name,
    pitch_millihz,
    progression_choices,
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
    def test_many_scales(self):
        # 従来の主要曲調を含み、非常に多くの曲調がある
        self.assertGreaterEqual(len(SCALE_IDS), 60)
        for base in ("major", "minor", "japanese", "battle"):
            self.assertIn(base, SCALE_IDS)

    def test_intervals_are_unique(self):
        """曲調ごとに音の並びが異なる (重複した曲調が無い)。"""
        sets = [tuple(SCALES[s]["intervals"]) for s in SCALE_IDS]
        self.assertEqual(len(set(sets)), len(sets))

    def test_labels_present_and_unique(self):
        """各曲調に日本語ラベルがあり、重複しない。"""
        labels = [SCALES[s]["label"] for s in SCALE_IDS]
        for label in labels:
            self.assertTrue(label.strip())
        self.assertEqual(len(set(labels)), len(labels))

    def test_intervals_valid(self):
        for scale_id in SCALE_IDS:
            intervals = SCALES[scale_id]["intervals"]
            self.assertEqual(intervals[0], 0)
            self.assertGreaterEqual(len(intervals), 5)
            self.assertEqual(len(set(intervals)), len(intervals))  # 重複なし
            for iv in intervals:
                self.assertTrue(0 <= iv < 12)
            self.assertEqual(list(intervals), sorted(intervals))

    def test_progression_degrees_valid(self):
        for scale_id in SCALE_IDS:
            n = len(SCALES[scale_id]["intervals"])
            for degree in SCALES[scale_id]["progression"]:
                self.assertTrue(0 <= degree < n)


class TestProgressionLibrary(unittest.TestCase):
    def test_each_scale_has_a_large_library(self):
        """各曲調に十分多くの進行がある。"""
        for scale_id in SCALE_IDS:
            with self.subTest(scale=scale_id):
                self.assertGreaterEqual(len(SCALE_PROGRESSIONS[scale_id]), 100)

    def test_total_is_very_large(self):
        total = sum(len(p) for p in SCALE_PROGRESSIONS.values())
        self.assertGreaterEqual(total, 10000)  # 全曲調あわせて 1 万通り超

    def test_library_was_expanded_about_fivefold(self):
        """進行ライブラリを大幅拡張した (旧 27,480 通りの約 4 倍以上)。"""
        total = sum(len(p) for p in SCALE_PROGRESSIONS.values())
        self.assertGreaterEqual(total, 110000)     # 旧比 約 4.4 倍
        # 7 音音階は理論上限 (7^4=2401) まで使い切る
        seven = next(sid for sid in SCALE_IDS
                     if len(SCALES[sid]["intervals"]) == 7)
        self.assertGreaterEqual(len(SCALE_PROGRESSIONS[seven]), 2000)

    def test_all_degrees_in_range(self):
        for scale_id, progs in SCALE_PROGRESSIONS.items():
            n = len(SCALES[scale_id]["intervals"])
            for prog in progs:
                with self.subTest(scale=scale_id, prog=prog):
                    self.assertEqual(len(prog), 4)
                    for degree in prog:
                        self.assertTrue(0 <= degree < n)

    def test_most_have_a_tonic_function_chord(self):
        """多くの進行にトニック機能の和音が含まれ、調が定まる。

        IV–V–IV–V のような循環進行 (トニックを含まない) も混ざるが、
        大半はトニックで支えられているのが望ましい。
        """
        from picoseq.core.music import _function_groups
        for scale_id, progs in SCALE_PROGRESSIONS.items():
            n = len(SCALES[scale_id]["intervals"])
            tonic = set(_function_groups(n)[0])
            grounded = sum(1 for prog in progs if tonic & set(prog))
            with self.subTest(scale=scale_id):
                self.assertGreater(grounded, len(progs) // 2)

    def test_no_duplicate_progressions(self):
        for scale_id, progs in SCALE_PROGRESSIONS.items():
            with self.subTest(scale=scale_id):
                self.assertEqual(len(progs), len(set(progs)))

    def test_default_progression_is_included(self):
        """従来の既定進行が候補に含まれている (互換性)。"""
        for scale_id in SCALE_IDS:
            self.assertIn(SCALES[scale_id]["progression"],
                          SCALE_PROGRESSIONS[scale_id])

    def test_choices_dispatch(self):
        self.assertEqual(progression_choices("minor"), SCALE_PROGRESSIONS["minor"])

    def test_photo_choices_valid_for_note_count(self):
        for n in range(3, 13):
            custom = tuple(range(n))
            choices = progression_choices("photo", custom)
            self.assertTrue(choices)
            for prog in choices:
                for degree in prog:
                    self.assertTrue(0 <= degree < n)

    def test_generator_is_deterministic(self):
        from picoseq.core.music import _generate_progressions
        self.assertEqual(_generate_progressions(7), _generate_progressions(7))

    def test_generator_grows_with_note_count(self):
        from picoseq.core.music import _generate_progressions
        counts = [len(set(_generate_progressions(n))) for n in (5, 6, 7)]
        self.assertTrue(counts[0] < counts[2])  # 音数が多いほど組み合わせが増える


class TestChordNames(unittest.TestCase):
    def test_qualities(self):
        from picoseq.core.music import chord_name
        self.assertEqual(chord_name(chord_at(0, "major", 0, 4, (0,))), "C")
        self.assertEqual(chord_name(chord_at(0, "major", 0, 4, (5,))), "Am")
        self.assertEqual(chord_name(chord_at(0, "major", 0, 4, (6,))), "Bdim")
        self.assertEqual(chord_name(chord_at(0, "minor", 0, 4, (0,))), "Cm")

    def test_progression_names(self):
        from picoseq.core.music import progression_names
        # A マイナー (key=9) の i–VI–III–VII は Am–F–C–G
        self.assertEqual(progression_names(9, "minor", (0, 5, 2, 6)),
                         ["Am", "F", "C", "G"])

    def test_progression_names_length(self):
        from picoseq.core.music import progression_names
        for scale_id in SCALE_IDS:
            for prog in SCALE_PROGRESSIONS[scale_id]:
                names = progression_names(0, scale_id, prog)
                self.assertEqual(len(names), 4)
                self.assertTrue(all(names))


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
