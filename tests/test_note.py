"""音符ビットパックのテスト — 往復変換と境界値。"""

import unittest

from picoseq.core.note import (
    SOFT_LEVELS, Note, is_active, pack_note, soft_gain, unpack_note,
)


class TestNotePack(unittest.TestCase):
    def test_roundtrip_boundaries(self):
        cases = [
            (36, 0, 0, 1),
            (84, 55, 3, 4),
            (60, 31, 1, 2),
            (255, 255, 3, 255),
            (0, 0, 0, 1),
        ]
        for pitch, step, wave, dur in cases:
            with self.subTest(pitch=pitch, step=step, wave=wave, dur=dur):
                value = pack_note(pitch, step, wave, dur)
                self.assertTrue(is_active(value))
                self.assertEqual(unpack_note(value), Note(pitch, step, wave, dur))

    def test_zero_is_inactive(self):
        self.assertFalse(is_active(0))

    def test_inactive_pack(self):
        value = pack_note(60, 4, 2, 3, active=False)
        self.assertFalse(is_active(value))
        self.assertEqual(unpack_note(value), Note(60, 4, 2, 3))

    def test_duration_zero_becomes_one(self):
        """旧データで duration=0 の音符は 1 として扱う。"""
        value = pack_note(60, 0, 0, 0)
        self.assertEqual(unpack_note(value).dur, 1)

    def test_fields_are_masked(self):
        """幅を超える値はビット幅で切り詰める (異常値を伝播させない)。"""
        value = pack_note(300, 300, 7, 300)
        note = unpack_note(value)
        self.assertEqual(note.pitch, 300 & 0xFF)
        self.assertEqual(note.step, 300 & 0xFF)
        self.assertEqual(note.wave, 7 & 0x3)
        self.assertEqual(note.dur, 300 & 0xFF)

    def test_value_fits_in_32bit(self):
        value = pack_note(255, 255, 3, 255, layer=7, soft=3)
        self.assertTrue(0 <= value < 2 ** 32)


class TestSoft(unittest.TestCase):
    """音符ごとの強弱 — 空いていた 2bit に収め、0 を「そのまま」にする。"""

    def test_roundtrip(self):
        for soft in range(SOFT_LEVELS):
            for layer in (0, 7):
                with self.subTest(soft=soft, layer=layer):
                    value = pack_note(60, 4, 1, 2, layer=layer, soft=soft)
                    note = unpack_note(value)
                    self.assertEqual(note.soft, soft)
                    self.assertEqual(note.layer, layer)

    def test_default_is_full_volume(self):
        """既定 (0) は 100% — 強弱を持たない旧データの音を変えない。"""
        self.assertEqual(Note(60, 0, 0, 1).soft, 0)
        self.assertEqual(soft_gain(0), 100)
        self.assertEqual(unpack_note(pack_note(60, 0, 0, 1)).soft, 0)

    def test_old_packed_values_are_unchanged(self):
        """レイヤーまでしか無い旧データ (bit30-31 = 0) は最強で読める。"""
        legacy = pack_note(60, 4, 1, 2, layer=3) & 0x3FFFFFFF
        self.assertEqual(unpack_note(legacy).soft, 0)

    def test_levels_are_monotonic(self):
        gains = [soft_gain(s) for s in range(SOFT_LEVELS)]
        self.assertEqual(gains, sorted(gains, reverse=True))
        self.assertEqual(gains[0], 100)
        self.assertGreater(gains[-1], 0)      # 消えてはいけない

    def test_out_of_range_is_full_volume(self):
        self.assertEqual(soft_gain(-1), 100)
        self.assertEqual(soft_gain(SOFT_LEVELS), 100)

    def test_soft_is_masked(self):
        self.assertEqual(unpack_note(pack_note(60, 0, 0, 1, soft=9)).soft, 9 & 0x3)


if __name__ == "__main__":
    unittest.main()
