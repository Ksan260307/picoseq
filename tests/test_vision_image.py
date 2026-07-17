"""画像デコーダのテスト — PPM / BMP / PNG と縮小グレースケール化。"""

import tempfile
import unittest
from pathlib import Path

from picoseq.vision.image import (
    decode_bmp,
    decode_png,
    decode_ppm,
    downsample_gray,
    load_gray_grid,
    load_rgb,
)
from tests._vision_util import make_bmp, make_png, make_ppm_p3, make_ppm_p6

PIXELS_2X2 = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255)]


class TestPpm(unittest.TestCase):
    def test_p6_roundtrip(self):
        w, h, pixels = decode_ppm(make_ppm_p6(2, 2, PIXELS_2X2))
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(pixels, PIXELS_2X2)

    def test_p6_with_comment(self):
        data = make_ppm_p6(2, 2, PIXELS_2X2, comment=b"camera photo")
        self.assertEqual(decode_ppm(data)[2], PIXELS_2X2)

    def test_p3_roundtrip(self):
        w, h, pixels = decode_ppm(make_ppm_p3(2, 2, PIXELS_2X2))
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(pixels, PIXELS_2X2)

    def test_truncated_raises(self):
        data = make_ppm_p6(4, 4, [(1, 2, 3)] * 16)[:-8]
        with self.assertRaises(ValueError):
            decode_ppm(data)


class TestBmp(unittest.TestCase):
    def test_bottom_up(self):
        w, h, pixels = decode_bmp(make_bmp(2, 2, PIXELS_2X2))
        self.assertEqual((w, h), (2, 2))
        self.assertEqual(pixels, PIXELS_2X2)

    def test_top_down(self):
        w, h, pixels = decode_bmp(make_bmp(2, 2, PIXELS_2X2, top_down=True))
        self.assertEqual(pixels, PIXELS_2X2)

    def test_row_padding(self):
        # 幅 3 (9 バイト行 → 12 バイトへパディング) が正しく読める
        pix = [(i, i, i) for i in range(9)]
        w, h, pixels = decode_bmp(make_bmp(3, 3, pix))
        self.assertEqual(pixels, pix)

    def test_unsupported_raises(self):
        data = bytearray(make_bmp(2, 2, PIXELS_2X2))
        data[28] = 8  # 8bit パレット BMP は非対応
        with self.assertRaises(ValueError):
            decode_bmp(bytes(data))


class TestPng(unittest.TestCase):
    def test_rgb_all_filters(self):
        pix = [(x * 40 % 256, y * 70 % 256, (x + y) * 30 % 256)
               for y in range(5) for x in range(5)]
        for filter_type in range(5):
            with self.subTest(filter=filter_type):
                data = make_png(5, 5, pix, color_type=2, filter_type=filter_type)
                w, h, pixels = decode_png(data)
                self.assertEqual((w, h), (5, 5))
                self.assertEqual(pixels, pix)

    def test_grayscale(self):
        values = [0, 64, 128, 255]
        w, h, pixels = decode_png(make_png(2, 2, values, color_type=0))
        self.assertEqual(pixels, [(v, v, v) for v in values])

    def test_palette(self):
        palette = [(255, 0, 0), (0, 255, 0)]
        w, h, pixels = decode_png(
            make_png(2, 2, [0, 1, 1, 0], color_type=3, palette=palette))
        self.assertEqual(pixels, [palette[0], palette[1], palette[1], palette[0]])

    def test_rgba_alpha_ignored(self):
        pix = [(10, 20, 30, 255), (40, 50, 60, 0), (1, 2, 3, 128), (7, 8, 9, 64)]
        w, h, pixels = decode_png(make_png(2, 2, pix, color_type=6))
        self.assertEqual(pixels, [p[:3] for p in pix])

    def test_16bit_rejected(self):
        data = bytearray(make_png(2, 2, PIXELS_2X2, color_type=2))
        data[24] = 16  # IHDR の bit depth
        with self.assertRaises(ValueError):
            decode_png(bytes(data))


class TestDownsample(unittest.TestCase):
    def test_small_image_unchanged_size(self):
        pixels = [(v, v, v) for v in (10, 20, 30, 40)]
        grid = downsample_gray(2, 2, pixels, max_dim=200)
        self.assertEqual(grid, [[10, 20], [30, 40]])

    def test_block_average(self):
        # 4x4 → max_dim 2 → ブロック 2x2 の平均
        pixels = [(v, v, v) for v in
                  [0, 0, 100, 100,
                   0, 0, 100, 100,
                   200, 200, 50, 50,
                   200, 200, 50, 50]]
        grid = downsample_gray(4, 4, pixels, max_dim=2)
        self.assertEqual(grid, [[0, 100], [200, 50]])  # 係数和 1000 なので損失なし

    def test_luma_weights(self):
        grid = downsample_gray(1, 1, [(255, 0, 0)], max_dim=10)
        self.assertEqual(grid, [[76]])  # 255*299//1000


class TestLoadDispatch(unittest.TestCase):
    def test_magic_bytes_dispatch(self):
        cases = [
            ("q.ppm", make_ppm_p6(2, 2, PIXELS_2X2)),
            ("q.bmp", make_bmp(2, 2, PIXELS_2X2)),
            ("q.png", make_png(2, 2, PIXELS_2X2, color_type=2)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in cases:
                with self.subTest(name=name):
                    path = Path(tmp) / name
                    path.write_bytes(data)
                    w, h, pixels = load_rgb(path)
                    self.assertEqual(pixels, PIXELS_2X2)

    def test_load_gray_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.ppm"
            path.write_bytes(make_ppm_p6(2, 1, [(255, 255, 255), (0, 0, 0)]))
            self.assertEqual(load_gray_grid(path), [[255, 0]])


if __name__ == "__main__":
    unittest.main()
