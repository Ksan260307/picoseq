"""DJ モードの判定ロジック (純粋な staticmethod / モジュール関数) のテスト。

Tk のルートは作らない — 純粋関数だけを確認する。
"""

import unittest

from picoseq.core.constants import PITCH_MAX, PITCH_MIN
from picoseq.ui.app import DJ_ADVANCE_LOOPS, PicoSeqApp
from picoseq.ui.dj_view import angle_diff

_swap = PicoSeqApp._dj_should_swap
_pitch = PicoSeqApp.dj_scratch_pitch
N = DJ_ADVANCE_LOOPS


class TestSwapDecision(unittest.TestCase):
    def test_no_pending_never_swaps(self):
        self.assertFalse(_swap(N + 5, False, False, True, N))   # 準備前は進まない

    def test_manual_swaps_immediately(self):
        self.assertTrue(_swap(1, False, True, True, N))
        self.assertTrue(_swap(1, True, True, True, N))          # HOLD 中でも手動は効く

    def test_auto_after_n_loops(self):
        self.assertFalse(_swap(N - 1, False, True, False, N))   # まだ
        self.assertTrue(_swap(N, False, True, False, N))        # ちょうど
        self.assertTrue(_swap(N + 2, False, True, False, N))    # 超過しても進む

    def test_hold_stops_auto(self):
        self.assertFalse(_swap(N + 10, True, True, False, N))   # HOLD は自動進行しない


class TestScratchPitch(unittest.TestCase):
    def test_forward_higher_than_back(self):
        self.assertGreater(_pitch(24), _pitch(-24))

    def test_within_range(self):
        for delta in (-500, -40, -1, 0, 1, 40, 500):
            self.assertTrue(PITCH_MIN <= _pitch(delta) <= PITCH_MAX, delta)

    def test_faster_forward_is_higher(self):
        self.assertGreaterEqual(_pitch(25), _pitch(5))          # 速いほど高い


class TestAngleDiff(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(angle_diff(10, 0), 10)
        self.assertAlmostEqual(angle_diff(0, 10), -10)

    def test_wraps_shortest(self):
        self.assertAlmostEqual(angle_diff(350, 10), -20)        # 反時計回りが最短
        self.assertAlmostEqual(angle_diff(10, 350), 20)

    def test_always_in_range(self):
        for a in range(0, 360, 13):
            for b in range(0, 360, 29):
                self.assertTrue(-180 <= angle_diff(a, b) <= 180)


if __name__ == "__main__":
    unittest.main()
