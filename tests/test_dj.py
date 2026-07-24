"""DJ モードのコア — ノイズ注入 (add_noise) とフィルター (lowpass_pcm)。"""

import unittest
from array import array

from picoseq.core import dj
from picoseq.core.constants import MAX_NOTES, MEASURES, WAVE_NOISE
from picoseq.core.note import Note


def _pcm(samples):
    return array("h", samples).tobytes()


def _samples(pcm):
    a = array("h")
    a.frombytes(pcm)
    return list(a)


def _noise_notes(notes):
    return [n for n in notes if n.wave == WAVE_NOISE]


class TestAddNoise(unittest.TestCase):
    def test_level_zero_is_passthrough(self):
        base = [Note(60, 0, 0, 4)]
        out = dj.add_noise(base, 4, 0, 123)
        self.assertEqual(out, base)
        self.assertIsNot(out, base)          # コピーは返す

    def test_deterministic(self):
        a = dj.add_noise([], 4, 3, 777)
        b = dj.add_noise([], 4, 3, 777)
        self.assertEqual(a, b)

    def test_different_seed_differs(self):
        a = dj.add_noise([], 4, 1, 1)
        b = dj.add_noise([], 4, 1, 2)
        self.assertNotEqual([n.step for n in a], [n.step for n in b])

    def test_higher_level_adds_more(self):
        counts = [len(_noise_notes(dj.add_noise([], 4, lvl, 42))) for lvl in (1, 2, 3, 4)]
        self.assertEqual(counts, sorted(counts))     # 単調非減少
        self.assertGreater(counts[-1], counts[0])    # 4 は 1 より明確に多い

    def test_all_within_grid(self):
        steps = 4 * 4 * MEASURES
        for note in _noise_notes(dj.add_noise([], 4, 4, 9)):
            self.assertTrue(0 <= note.step < steps)
            self.assertEqual(note.wave, WAVE_NOISE)

    def test_keeps_existing_notes(self):
        base = [Note(60, 0, 0, 4), Note(48, 4, 1, 2)]
        out = dj.add_noise(base, 4, 2, 5)
        for note in base:
            self.assertIn(note, out)

    def test_respects_max_notes(self):
        base = [Note(60, i % 20, 0, 1) for i in range(MAX_NOTES)]
        out = dj.add_noise(base, 7, 4, 5)
        self.assertLessEqual(len(out), MAX_NOTES)

    def test_level_clamped(self):
        low = dj.add_noise([], 4, 4, 3)
        high = dj.add_noise([], 4, 99, 3)   # 4 に丸められる
        self.assertEqual(low, high)


class TestLowpass(unittest.TestCase):
    def _hf_signal(self, n=2000, amp=20000):
        """1 サンプルごとに符号が反転する最高周波数の信号 (ローパスで最も削れる)。"""
        return _pcm([amp if i % 2 == 0 else -amp for i in range(n)])

    def test_open_is_passthrough(self):
        pcm = self._hf_signal()
        self.assertEqual(dj.lowpass_pcm(pcm, 100), pcm)   # 開放は素通し
        self.assertEqual(dj.lowpass_pcm(pcm, 150), pcm)   # 上限超えも素通し

    def test_empty_passthrough(self):
        self.assertEqual(dj.lowpass_pcm(b"", 10), b"")

    def test_deterministic(self):
        pcm = self._hf_signal()
        self.assertEqual(dj.lowpass_pcm(pcm, 30), dj.lowpass_pcm(pcm, 30))

    def test_reduces_high_frequency(self):
        """高周波信号はフィルターで振幅が小さくなる。"""
        pcm = self._hf_signal()
        peak_in = max(abs(v) for v in _samples(pcm))
        peak_out = max(abs(v) for v in _samples(dj.lowpass_pcm(pcm, 20)))
        self.assertLess(peak_out, peak_in)

    def test_darker_reduces_more(self):
        pcm = self._hf_signal()
        dark = max(abs(v) for v in _samples(dj.lowpass_pcm(pcm, 10)))
        bright = max(abs(v) for v in _samples(dj.lowpass_pcm(pcm, 80)))
        self.assertLessEqual(dark, bright)          # 暗いほど強く削れる

    def test_dc_signal_preserved(self):
        """一定値 (直流) はローパスを通しても概ね保たれる。"""
        pcm = _pcm([10000] * 2000)
        out = _samples(dj.lowpass_pcm(pcm, 30))
        self.assertGreater(min(out[100:]), 9000)    # 立ち上がり後はほぼ 10000

    def test_length_preserved(self):
        pcm = self._hf_signal(n=1234)
        self.assertEqual(len(dj.lowpass_pcm(pcm, 40)), len(pcm))

    def test_stays_in_16bit(self):
        pcm = self._hf_signal(amp=32767)
        for v in _samples(dj.lowpass_pcm(pcm, 5)):
            self.assertTrue(-32768 <= v <= 32767)


if __name__ == "__main__":
    unittest.main()
