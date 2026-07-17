"""四角形 → 音楽写像のテスト — 決定論・範囲・仕様どおりの対応。"""

import unittest

from picoseq.core.music import SCALES
from picoseq.vision.harmony import (
    PhotoHarmony,
    chord_name,
    corner_angles,
    describe,
    harmony_from_quad,
    regularity,
)
from picoseq.vision.quad import Quad


def _quad(points, grid_w=200, grid_h=150):
    return Quad(points=tuple(points), grid_w=grid_w, grid_h=grid_h,
                pixel_area=1000, fill=1.0)


SQUARE = _quad([(80, 55), (120, 55), (120, 95), (80, 95)])


class TestAngles(unittest.TestCase):
    def test_rectangle_angles(self):
        for angle in corner_angles(SQUARE.points):
            self.assertAlmostEqual(angle, 90.0, delta=0.01)

    def test_angles_sum_360(self):
        quad = [(50, 15), (140, 40), (110, 105), (25, 80)]
        self.assertAlmostEqual(sum(corner_angles(quad)), 360.0, delta=0.1)

    def test_regularity(self):
        self.assertAlmostEqual(regularity([90, 90, 90, 90]), 1.0)
        self.assertAlmostEqual(regularity([60, 120, 60, 120]), 1 - 120 / 180)
        self.assertEqual(regularity([180, 180, 0, 0]), 0.0)


class TestMapping(unittest.TestCase):
    def test_square_gives_major_and_default_progression(self):
        harmony = harmony_from_quad(SQUARE)
        self.assertEqual(harmony.scale, "major")
        self.assertEqual(harmony.progression, SCALES["major"]["progression"])

    def test_skewed_gives_darker_scale(self):
        # 平行四辺形 (約 63°/117°) → 整形度 ~0.4 → battle
        skewed = _quad([(60, 40), (140, 40), (170, 100), (90, 100)])
        harmony = harmony_from_quad(skewed)
        self.assertIn(harmony.scale, ("japanese", "battle"))

    def test_key_follows_center_x(self):
        left = _quad([(4, 55), (36, 55), (36, 95), (4, 95)])
        right = _quad([(164, 55), (196, 55), (196, 95), (164, 95)])
        self.assertEqual(harmony_from_quad(left).key, 1)   # 中心 x=20/200 → 1.2
        self.assertEqual(harmony_from_quad(right).key, 10)  # 中心 x=180/200 → 10.8
        self.assertLess(harmony_from_quad(left).key, harmony_from_quad(right).key)

    def test_bpm_follows_area(self):
        small = _quad([(90, 65), (110, 65), (110, 85), (90, 85)])
        large = _quad([(10, 10), (190, 10), (190, 140), (10, 140)])
        self.assertLess(harmony_from_quad(small).bpm, harmony_from_quad(large).bpm)
        for quad in (small, large):
            self.assertTrue(60 <= harmony_from_quad(quad).bpm <= 240)

    def test_progression_degrees_valid(self):
        quads = [SQUARE,
                 _quad([(60, 40), (140, 40), (170, 100), (90, 100)]),
                 _quad([(50, 15), (140, 40), (110, 105), (25, 80)])]
        for quad in quads:
            harmony = harmony_from_quad(quad)
            n = len(SCALES[harmony.scale]["intervals"])
            self.assertEqual(len(harmony.progression), 4)
            for degree in harmony.progression:
                self.assertTrue(0 <= degree < n)

    def test_deterministic(self):
        quad = _quad([(50, 15), (140, 40), (110, 105), (25, 80)])
        self.assertEqual(harmony_from_quad(quad), harmony_from_quad(quad))

    def test_seed_range_and_sensitivity(self):
        a = harmony_from_quad(SQUARE)
        moved = _quad([(70, 45), (130, 45), (130, 105), (70, 105)])
        b = harmony_from_quad(moved)
        self.assertTrue(1 <= a.seed <= 999_999)
        self.assertNotEqual(a.seed, b.seed)  # 場所が変われば別の曲


class TestNaming(unittest.TestCase):
    def test_chord_names(self):
        self.assertEqual(chord_name(0, "major", 0), "C")
        self.assertEqual(chord_name(0, "major", 5), "Am")
        self.assertEqual(chord_name(0, "major", 6), "Bdim")
        self.assertEqual(chord_name(0, "minor", 0), "Cm")
        self.assertEqual(chord_name(9, "minor", 0), "Am")

    def test_describe_mentions_chords(self):
        harmony = PhotoHarmony(key=0, scale="major", progression=(0, 3, 1, 4),
                               bpm=120, seed=42)
        text = describe(harmony)
        self.assertIn("C", text)
        self.assertIn("テンポ: 120", text)
        self.assertIn("シード: 42", text)


if __name__ == "__main__":
    unittest.main()
