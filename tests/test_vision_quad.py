"""四角形検出のテスト — 合成画像での検出精度と決定論。"""

import unittest

from picoseq.vision.quad import (
    best_quad_corners,
    convex_hull,
    detect_quad,
    detect_quads,
    otsu_threshold,
    polygon_area2,
    quantile_threshold,
)
from tests._vision_util import draw_circle_grid, draw_quad_grid


def _close(p, q, tol=3):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def _multi_quad_grid(width, height, rects, fg=230, bg=40):
    """複数の軸並行の矩形を塗った格子。rects は (x0, y0, x1, y1) の列。"""
    grid = [[bg] * width for _ in range(height)]
    for x0, y0, x1, y1 in rects:
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                grid[y][x] = fg
    return grid


class TestOtsu(unittest.TestCase):
    def test_bimodal_split(self):
        grid = [[40] * 50 + [220] * 50 for _ in range(20)]
        t = otsu_threshold(grid)
        self.assertTrue(40 <= t < 220)

    def test_deterministic(self):
        grid = draw_quad_grid(60, 40, [(10, 10), (50, 10), (50, 30), (10, 30)])
        self.assertEqual(otsu_threshold(grid), otsu_threshold(grid))


class TestGeometry(unittest.TestCase):
    def test_convex_hull_square(self):
        points = [(x, y) for x in range(5) for y in range(5)]
        hull = set(convex_hull(points))
        self.assertEqual(hull, {(0, 0), (4, 0), (4, 4), (0, 4)})

    def test_polygon_area2(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4)]
        self.assertEqual(polygon_area2(square), 32)  # 面積 16 の 2 倍

    def test_best_quad_orders_corners(self):
        hull = convex_hull([(x, y) for x in range(3, 20) for y in range(5, 15)])
        tl, tr, br, bl = best_quad_corners(hull)
        self.assertEqual(tl, (3, 5))
        self.assertEqual(tr, (19, 5))
        self.assertEqual(br, (19, 14))
        self.assertEqual(bl, (3, 14))


class TestDetect(unittest.TestCase):
    def test_axis_aligned_rect(self):
        expected = [(30, 20), (130, 20), (130, 90), (30, 90)]
        grid = draw_quad_grid(160, 120, expected)
        quad = detect_quad(grid)
        self.assertIsNotNone(quad)
        for point, truth in zip(quad.points, expected):
            self.assertTrue(_close(point, truth), f"{point} != {truth}")

    def test_rotated_quad(self):
        corners = [(50, 15), (140, 40), (110, 105), (25, 80)]
        grid = draw_quad_grid(160, 120, corners)
        quad = detect_quad(grid)
        self.assertIsNotNone(quad)
        for point, truth in zip(quad.points, corners):
            self.assertTrue(_close(point, truth, tol=4), f"{point} != {truth}")

    def test_dark_object_on_light(self):
        expected = [(30, 20), (130, 20), (130, 90), (30, 90)]
        grid = draw_quad_grid(160, 120, expected, fg=30, bg=220)
        quad = detect_quad(grid)
        self.assertIsNotNone(quad)
        self.assertTrue(_close(quad.points[0], expected[0]))

    def test_uniform_image_is_none(self):
        grid = [[128] * 100 for _ in range(80)]
        self.assertIsNone(detect_quad(grid))

    def test_circle_is_rejected(self):
        grid = draw_circle_grid(160, 120, 80, 60, 40)
        self.assertIsNone(detect_quad(grid))  # fill 比が四角形の範囲外

    def test_tiny_blob_is_ignored(self):
        grid = draw_quad_grid(160, 120, [(80, 60), (84, 60), (84, 63), (80, 63)])
        self.assertIsNone(detect_quad(grid))

    def test_deterministic(self):
        corners = [(50, 15), (140, 40), (110, 105), (25, 80)]
        grid = draw_quad_grid(160, 120, corners)
        self.assertEqual(detect_quad(grid), detect_quad(grid))

    def test_reports_grid_size_and_fill(self):
        grid = draw_quad_grid(160, 120, [(30, 20), (130, 20), (130, 90), (30, 90)])
        quad = detect_quad(grid)
        self.assertEqual((quad.grid_w, quad.grid_h), (160, 120))
        self.assertTrue(0.7 <= quad.fill <= 1.3)
        self.assertGreater(quad.pixel_area, 100)


class TestDetectMulti(unittest.TestCase):
    def test_two_quads_found(self):
        grid = _multi_quad_grid(160, 120, [(15, 20, 70, 90), (100, 30, 140, 80)])
        quads = detect_quads(grid)
        self.assertEqual(len(quads), 2)
        # 面積の大きい順
        self.assertGreaterEqual(quads[0].pixel_area, quads[1].pixel_area)

    def test_up_to_eight(self):
        rects = []
        for row in range(2):
            for col in range(5):  # 10 個置いても 8 個まで
                x0 = 8 + col * 30
                y0 = 10 + row * 60
                rects.append((x0, y0, x0 + 22, y0 + 40))
        grid = _multi_quad_grid(160, 120, rects)
        quads = detect_quads(grid)
        self.assertTrue(1 <= len(quads) <= 8)
        self.assertGreaterEqual(len(quads), 6)  # ほとんどは拾える

    def test_no_duplicates_for_single_object(self):
        """複数しきい値でも、同じ四角形が重複して返らない。"""
        grid = draw_quad_grid(160, 120, [(30, 20), (130, 20), (130, 90), (30, 90)])
        quads = detect_quads(grid)
        self.assertEqual(len(quads), 1)

    def test_mid_gray_object_found(self):
        """背景と近い中間調でも補助しきい値で拾える (精度向上の検査)。"""
        grid = draw_quad_grid(160, 120, [(40, 30), (120, 30), (120, 90), (40, 90)],
                              fg=150, bg=90)
        self.assertEqual(len(detect_quads(grid)), 1)

    def test_deterministic(self):
        grid = _multi_quad_grid(160, 120, [(15, 20, 70, 90), (100, 30, 140, 80)])
        self.assertEqual(detect_quads(grid), detect_quads(grid))

    def test_empty_grid(self):
        self.assertEqual(detect_quads([[128] * 100 for _ in range(80)]), [])


class TestQuantile(unittest.TestCase):
    def test_quantile_positions(self):
        grid = [[10] * 50 + [200] * 50 for _ in range(10)]
        self.assertLessEqual(quantile_threshold(grid, 30), 10)
        self.assertGreaterEqual(quantile_threshold(grid, 70), 10)


if __name__ == "__main__":
    unittest.main()
