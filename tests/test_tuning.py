"""UI の調整値のテスト — サプライズの振れ幅と曲調連動。"""

import unittest

from picoseq.core.constants import BEATS_MAX, BEATS_MIN
from picoseq.core.music import SCALE_FAMILIES, SCALE_IDS, scale_family
from picoseq.ui.tuning import (
    MOOD_BPM,
    SURPRISE_BEATS,
    SURPRISE_BPM,
    surprise_bpm,
)


class TestSurpriseBeats(unittest.TestCase):
    def test_all_meters_are_valid(self):
        for beats in SURPRISE_BEATS:
            self.assertTrue(BEATS_MIN <= beats <= BEATS_MAX)

    def test_common_and_odd_meters_both_appear(self):
        """4/4 に寄せつつ、変拍子も出る (毎回 7/4 だと聴き疲れる)。"""
        self.assertGreater(SURPRISE_BEATS.count(4), 1)      # 4/4 は厚め
        self.assertGreater(len(set(SURPRISE_BEATS)), 3)     # 種類はある
        self.assertIn(7, SURPRISE_BEATS)                    # 変拍子も引ける

    def test_four_four_is_the_most_likely(self):
        best = max(set(SURPRISE_BEATS), key=SURPRISE_BEATS.count)
        self.assertEqual(best, 4)


class TestMoodBpm(unittest.TestCase):
    """テンポも曲調に寄せる — 演奏の型だけ寄せてもテンポが逆なら台無し。"""

    def test_every_family_has_a_range(self):
        """性格グループの取りこぼしを機械的に検出する。

        MOOD_BPM は循環 import を避けるためキーを文字列で持っているので、
        FAMILY_* を増やしたときに気づけるのはこのテストだけ。
        """
        for family in SCALE_FAMILIES:
            with self.subTest(family=family):
                self.assertIn(family, MOOD_BPM)

    def test_ranges_are_inside_the_overall_span(self):
        for family, (lo, hi) in MOOD_BPM.items():
            with self.subTest(family=family):
                self.assertLess(lo, hi)
                self.assertGreaterEqual(lo, SURPRISE_BPM[0])
                self.assertLessEqual(hi, SURPRISE_BPM[1])

    def test_fierce_is_faster_than_dreamy(self):
        self.assertGreater(MOOD_BPM["fierce"][0], MOOD_BPM["dream"][1])

    def test_every_scale_resolves_to_a_range(self):
        """65 曲調すべてがテンポ範囲を引ける (既定値へ落ちない)。"""
        for scale_id in SCALE_IDS:
            with self.subTest(scale=scale_id):
                self.assertIn(scale_family(scale_id), MOOD_BPM)

    def test_battle_never_gets_a_slow_tempo(self):
        """ボス戦が 80 BPM にならない (一様乱数だと 20% で起きていた)。"""
        lo, hi = surprise_bpm(scale_family("battle"))
        self.assertGreaterEqual(lo, 140)

    def test_unknown_family_falls_back_to_the_full_span(self):
        self.assertEqual(surprise_bpm("no-such-family"), SURPRISE_BPM)


if __name__ == "__main__":
    unittest.main()
