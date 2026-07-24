"""ストリーミング再生のチャンク生成 — 継ぎ目なしの乗り換えと重ね合わせ。

音声デバイスは開かない (open() を呼ばない) ので、どこでも実行できる。
"""

import unittest
from array import array

from picoseq.ui.stream import StreamPlayer, mix_into


def _pcm(values):
    return array("h", values).tobytes()


def _samples(pcm):
    out = array("h")
    out.frombytes(pcm)
    return list(out)


class TestMixInto(unittest.TestCase):
    def test_adds_and_advances(self):
        chunk = array("h", [10, 10, 10, 10])
        source = array("h", [1, 2])
        end = mix_into(chunk, source, 0, 0)
        self.assertEqual(list(chunk), [11, 12, 10, 10])
        self.assertEqual(end, 2)

    def test_saturates(self):
        chunk = array("h", [30000, -30000])
        source = array("h", [30000, -30000])
        mix_into(chunk, source, 0, 0)
        self.assertEqual(list(chunk), [32767, -32768])

    def test_partial_source_continues(self):
        chunk = array("h", [0, 0])
        source = array("h", [1, 2, 3, 4])
        end = mix_into(chunk, source, 0, 0)     # chunk に収まる分だけ
        self.assertEqual(end, 2)
        self.assertEqual(list(chunk), [1, 2])


class TestChunks(unittest.TestCase):
    def _player(self, frames):
        return StreamPlayer(rate=44100, frames=frames, buffers=2)   # open() しない

    def test_silence_when_nothing_set(self):
        player = self._player(4)
        self.assertEqual(_samples(player._next_chunk()), [0, 0, 0, 0])

    def test_loop_wraps_and_counts(self):
        player = self._player(4)
        player.set_loop(_pcm([1, 2, 3, 4, 5, 6]))
        self.assertEqual(_samples(player._next_chunk()), [1, 2, 3, 4])
        self.assertEqual(_samples(player._next_chunk()), [5, 6, 1, 2])   # 折り返す
        self.assertEqual(player.loops, 1)

    def test_set_next_switches_at_loop_boundary(self):
        player = self._player(4)
        player.set_loop(_pcm([1, 1, 1, 1]))
        player.set_next(_pcm([9, 9, 9, 9]))
        self.assertEqual(_samples(player._next_chunk()), [1, 1, 1, 1])   # 今の 1 周は最後まで
        self.assertEqual(_samples(player._next_chunk()), [9, 9, 9, 9])   # 次の周から新しい方
        self.assertEqual(player.switches, 1)

    def test_no_silence_at_the_seam(self):
        """乗り換えの継ぎ目に無音サンプルが入らない (これが「途切れ」の正体だった)。"""
        player = self._player(8)
        player.set_loop(_pcm([5] * 4))
        player.set_next(_pcm([7] * 4))
        self.assertEqual(_samples(player._next_chunk()), [5, 5, 5, 5, 7, 7, 7, 7])

    def test_next_keeps_looping_new_content(self):
        player = self._player(4)
        player.set_loop(_pcm([1, 1]))
        player.set_next(_pcm([8, 8]))
        player._next_chunk()                       # 1,1 -> 8,8 へ乗り換え
        self.assertEqual(_samples(player._next_chunk()), [8, 8, 8, 8])  # 以後は新しい方を繰り返す

    def test_set_next_starts_immediately_when_idle(self):
        player = self._player(4)
        player.set_next(_pcm([3, 3, 3, 3]))        # 何も鳴っていなければ即開始
        self.assertEqual(_samples(player._next_chunk()), [3, 3, 3, 3])

    def test_oneshot_mixes_over_the_loop(self):
        player = self._player(4)
        player.set_loop(_pcm([100] * 4))
        player.play_oneshot(_pcm([10, 10]))
        self.assertEqual(_samples(player._next_chunk()), [110, 110, 100, 100])
        self.assertEqual(_samples(player._next_chunk()), [100] * 4)   # 1 回で終わる

    def test_oneshot_spans_chunks(self):
        player = self._player(2)
        player.set_loop(_pcm([0] * 2))
        player.play_oneshot(_pcm([1, 2, 3, 4]))
        self.assertEqual(_samples(player._next_chunk()), [1, 2])
        self.assertEqual(_samples(player._next_chunk()), [3, 4])

    def test_replace_loop_keeps_position(self):
        """パラメータの即時反映: 位置を保ったまま中身だけ差し替える。"""
        player = self._player(2)
        player.set_loop(_pcm([1, 2, 3, 4]))
        self.assertEqual(_samples(player._next_chunk()), [1, 2])   # 位置は 2 へ
        player.replace_loop(_pcm([7, 8, 9, 10]))
        self.assertEqual(_samples(player._next_chunk()), [9, 10])  # 続きから新しい中身

    def test_replace_loop_maps_position_when_length_changes(self):
        """テンポ変更などで長さが変わっても、同じ相対位置へ読み替える。"""
        player = self._player(2)
        player.set_loop(_pcm([0, 0, 0, 0]))
        player._next_chunk()                       # 位置 2/4 = 50%
        player.replace_loop(_pcm([1, 2, 3, 4, 5, 6, 7, 8]))
        self.assertEqual(_samples(player._next_chunk()), [5, 6])   # 8 の 50% = 位置 4

    def test_replace_loop_cancels_queued_next(self):
        player = self._player(4)
        player.set_loop(_pcm([1] * 4))
        player.set_next(_pcm([9] * 4))
        player.replace_loop(_pcm([5] * 4))         # 予約は取り消される
        player._next_chunk()
        self.assertEqual(_samples(player._next_chunk()), [5, 5, 5, 5])
        self.assertEqual(player.switches, 0)

    def test_replace_loop_when_idle_starts_it(self):
        player = self._player(4)
        player.replace_loop(_pcm([2] * 4))
        self.assertEqual(_samples(player._next_chunk()), [2, 2, 2, 2])

    def test_stop_clears_everything(self):
        player = self._player(4)
        player.set_loop(_pcm([1] * 4))
        player.stop()
        self.assertFalse(player.playing)
        self.assertEqual(_samples(player._next_chunk()), [0, 0, 0, 0])


if __name__ == "__main__":
    unittest.main()
