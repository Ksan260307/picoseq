"""音符ビットパックのテスト — 論理スキーマの往復と境界値。"""

import unittest

from picoseq.core.note import Note, is_active, pack_note, unpack_note


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
        value = pack_note(255, 255, 3, 255)
        self.assertTrue(0 <= value < 2 ** 32)


if __name__ == "__main__":
    unittest.main()
