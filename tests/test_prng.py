"""PRNG の決定論と分布のテスト。"""

import unittest

from picoseq.core.prng import Rng


class TestRng(unittest.TestCase):
    def test_pinned_sequence_seed1(self):
        """既知の系列 — 実装を変えたら保存済みの曲の音が変わることを検知する。"""
        rng = Rng(1)
        self.assertEqual(
            [rng.next_u32() for _ in range(5)],
            [2693262067, 11749833, 2265367787, 4213581821, 4159151403],
        )

    def test_pinned_sequence_seed42(self):
        rng = Rng(42)
        self.assertEqual(
            [rng.next_u32() for _ in range(5)],
            [2581720956, 1925393290, 3661312704, 2876485805, 750819978],
        )

    def test_same_seed_same_sequence(self):
        a = Rng(123)
        b = Rng(123)
        self.assertEqual([a.next_u32() for _ in range(100)],
                         [b.next_u32() for _ in range(100)])

    def test_different_seeds_differ(self):
        a = Rng(1)
        b = Rng(2)
        self.assertNotEqual([a.next_u32() for _ in range(10)],
                            [b.next_u32() for _ in range(10)])

    def test_u32_range(self):
        rng = Rng(7)
        for _ in range(1000):
            v = rng.next_u32()
            self.assertTrue(0 <= v < 2 ** 32)

    def test_float_range(self):
        rng = Rng(7)
        for _ in range(1000):
            v = rng.next_float()
            self.assertTrue(0.0 <= v < 1.0)

    def test_float_distribution(self):
        rng = Rng(99)
        mean = sum(rng.next_float() for _ in range(10000)) / 10000
        self.assertTrue(0.45 < mean < 0.55)

    def test_next_int_range(self):
        rng = Rng(5)
        for _ in range(1000):
            self.assertTrue(0 <= rng.next_int(7) < 7)

    def test_chance_deterministic(self):
        a = Rng(11)
        b = Rng(11)
        self.assertEqual([a.chance(0.3) for _ in range(50)],
                         [b.chance(0.3) for _ in range(50)])


if __name__ == "__main__":
    unittest.main()
