"""写真 → 音階変換のテスト — 決定論・範囲・仕様どおりの対応。"""

import unittest

from picoseq.vision.harmony import (
    PhotoScale,
    describe,
    photo_scale_from_quads,
    quad_pitch_class,
    scale_note_names,
)
from picoseq.vision.quad import Quad


def _quad(points, grid_w=200, grid_h=150, area=1000):
    return Quad(points=tuple(points), grid_w=grid_w, grid_h=grid_h,
                pixel_area=area, fill=1.0)


def _rect(cx, cy, half_w=16, half_h=12, **kw):
    return _quad([(cx - half_w, cy - half_h), (cx + half_w, cy - half_h),
                  (cx + half_w, cy + half_h), (cx - half_w, cy + half_h)], **kw)


class TestQuadPitch(unittest.TestCase):
    def test_left_is_low_right_is_high(self):
        self.assertEqual(quad_pitch_class(_rect(8, 75, half_w=8)), 0)
        self.assertEqual(quad_pitch_class(_rect(192, 75, half_w=8)), 11)
        self.assertLess(quad_pitch_class(_rect(50, 75)),
                        quad_pitch_class(_rect(150, 75)))

    def test_x_position_maps_to_12_tones(self):
        # 中心 x=100/200 → 0.5 * 12 = 6
        self.assertEqual(quad_pitch_class(_rect(100, 75)), 6)


class TestPhotoScale(unittest.TestCase):
    def test_key_is_largest_quad(self):
        quads = [_rect(100, 75, area=5000),  # 最大 → キー (半音 6)
                 _rect(20, 40, area=1000)]
        photo = photo_scale_from_quads(quads)
        self.assertEqual(photo.key, 6)
        self.assertIn(0, photo.intervals)

    def test_intervals_relative_to_key(self):
        quads = [_rect(100, 75, area=5000),   # 半音 6 = キー
                 _rect(150, 40, area=2000),   # 半音 9 → +3
                 _rect(50, 100, area=1000)]   # 半音 3 → +9
        photo = photo_scale_from_quads(quads)
        self.assertEqual(photo.intervals, (0, 3, 9))

    def test_few_quads_padded_to_three_tones(self):
        photo = photo_scale_from_quads([_rect(100, 75)])
        self.assertGreaterEqual(len(photo.intervals), 3)
        self.assertEqual(photo.intervals[0], 0)

    def test_max_eight_quads_all_contribute(self):
        quads = [_rect(10 + i * 25, 75, half_w=8, area=8000 - i)
                 for i in range(8)]
        photo = photo_scale_from_quads(quads)
        self.assertEqual(len(photo.pitch_classes), 8)
        for iv in photo.intervals:
            self.assertTrue(0 <= iv <= 11)

    def test_bpm_grows_with_total_area(self):
        small = photo_scale_from_quads([_rect(100, 75, half_w=10, half_h=8)])
        large = photo_scale_from_quads([_rect(60, 75, half_w=50, half_h=60),
                                        _rect(160, 75, half_w=30, half_h=60)])
        self.assertLess(small.bpm, large.bpm)
        for photo in (small, large):
            self.assertTrue(60 <= photo.bpm <= 240)

    def test_deterministic(self):
        quads = [_rect(100, 75, area=500), _rect(30, 40, area=300)]
        self.assertEqual(photo_scale_from_quads(quads),
                         photo_scale_from_quads(quads))

    def test_seed_range_and_sensitivity(self):
        a = photo_scale_from_quads([_rect(100, 75)])
        b = photo_scale_from_quads([_rect(90, 65)])
        self.assertTrue(1 <= a.seed <= 999_999)
        self.assertNotEqual(a.seed, b.seed)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            photo_scale_from_quads([])


class TestDescribe(unittest.TestCase):
    def test_names_and_text(self):
        photo = PhotoScale(key=0, intervals=(0, 4, 7), bpm=120, seed=42,
                           pitch_classes=(0, 4, 7))
        self.assertEqual(scale_note_names(photo), ["C", "E", "G"])
        text = describe(photo)
        self.assertIn("C・E・G", text)
        self.assertIn("テンポ: 120", text)
        self.assertIn("フォト音階", text)


if __name__ == "__main__":
    unittest.main()
