"""再生アダプタのテスト — PCM 回転と再生時計 (音は鳴らさない)。"""

import struct
import unittest

from picoseq.ui.playback import PlayClock, SoundPlayer, rotate_pcm


def _pcm(values):
    return struct.pack("<%dh" % len(values), *values)


class TestRotate(unittest.TestCase):
    def test_rotate_basic(self):
        pcm = _pcm([1, 2, 3, 4])
        self.assertEqual(rotate_pcm(pcm, 1), _pcm([2, 3, 4, 1]))
        self.assertEqual(rotate_pcm(pcm, 2), _pcm([3, 4, 1, 2]))

    def test_rotate_zero_and_full(self):
        pcm = _pcm([1, 2, 3, 4])
        self.assertEqual(rotate_pcm(pcm, 0), pcm)
        self.assertEqual(rotate_pcm(pcm, 4), pcm)  # 一周 = 元通り

    def test_rotate_wraps_offset(self):
        pcm = _pcm([1, 2, 3, 4])
        self.assertEqual(rotate_pcm(pcm, 5), rotate_pcm(pcm, 1))

    def test_rotate_empty(self):
        self.assertEqual(rotate_pcm(b"", 3), b"")

    def test_rotation_is_reversible(self):
        pcm = _pcm([5, 6, 7, 8, 9])
        rotated = rotate_pcm(pcm, 2)
        self.assertEqual(rotate_pcm(rotated, 3), pcm)  # 2 + 3 = 5 ≡ 0 (mod 5)


class TestPlayClock(unittest.TestCase):
    def test_stopped_returns_none(self):
        clock = PlayClock()
        self.assertIsNone(clock.position())

    def test_start_sets_position_near_offset(self):
        clock = PlayClock()
        clock.start(10.0, offset_seconds=3.0)
        pos = clock.position()
        self.assertIsNotNone(pos)
        self.assertTrue(3.0 <= pos < 3.1)  # ほぼ offset から始まる

    def test_offset_wraps_into_duration(self):
        clock = PlayClock()
        clock.start(4.0, offset_seconds=9.0)  # 9 % 4 = 1
        self.assertTrue(1.0 <= clock.position() < 1.1)

    def test_stop_clears(self):
        clock = PlayClock()
        clock.start(5.0)
        clock.stop()
        self.assertIsNone(clock.position())


class TestSilentPlayer(unittest.TestCase):
    def test_silent_player_is_noop(self):
        player = SoundPlayer(silent=True)
        player.play_file("nonexistent.wav", loop=True)  # 例外を出さない
        player.stop()


if __name__ == "__main__":
    unittest.main()
