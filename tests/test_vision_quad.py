"""四角形検出のテスト — 合成画像での検出精度と決定論。"""

import unittest

from picoseq.vision.quad import (
    best_quad_corners,
    convex_hull,
    detect_quad,
    otsu_threshold,
    polygon_area2,
)
from tests._vision_util import draw_circle_grid, draw_quad_grid


def _close(p, q, tol=3):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


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


if __name__ == "__main__":
    unittest.main()
