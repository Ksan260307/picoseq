"""シンセ波形の網羅テスト — 全 音色 × 波形 × 音高 で堅牢性を保証する。

どの組み合わせ・どの (音色つまみ, ゲート) でも
・決定論的 (同じ入力 → 同じ列)
・振幅が上限内 (クリップ前に収まる)
・無音にならない
を満たす。音色/波形/音高ごとにテストを動的生成する。
"""

import unittest

from picoseq.core.constants import (
    SAMPLE_RATE,
    SOUND_SETS,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
)
from picoseq.core.synth import PEAKS, render_voice, voice_samples

WAVES = (WAVE_PULSE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW)
PITCHES = (36, 48, 60, 72, 83)
TONES = (0, 25, 50, 75, 100)
GATES = (10, 40, 80, 100)
# 発音の長さ。ここで見たいのは決定論・振幅の上限・無音でないことで、
# どれも長さに依存しない。1200 通り × 2 回合成するので、短くすると全体が縮む
# (音そのものの回帰は test_synth.py のゴールデン CRC が 5512 サンプルで見張る)。
DUR = 2048


class VoiceDeterminism(unittest.TestCase):
    """同じ入力からは必ず同じサンプル列。"""


class VoiceBounds(unittest.TestCase):
    """振幅は 2*PEAK 以内 (倍音重ねの余裕込み) に収まる。"""


class VoiceNonEmpty(unittest.TestCase):
    """発音が 0 サンプルにならない (無音バグの検出)。"""


def _det_test(sound, wave, pitch):
    def test(self):
        for tone in TONES:
            for gate in GATES:
                a = render_voice(wave, pitch, DUR, tone, gate, SAMPLE_RATE, sound)
                b = render_voice(wave, pitch, DUR, tone, gate, SAMPLE_RATE, sound)
                self.assertEqual(a, b, f"tone={tone} gate={gate}")
    return test


def _bounds_test(sound, wave, pitch):
    def test(self):
        limit = PEAKS[wave] * 2 + 1
        for tone in TONES:
            for gate in GATES:
                voice = render_voice(wave, pitch, DUR, tone, gate, SAMPLE_RATE, sound)
                self.assertTrue(all(-limit <= v <= limit for v in voice),
                                f"tone={tone} gate={gate} が上限超過")
    return test


def _nonempty_test(sound, wave, pitch):
    def test(self):
        for gate in GATES:
            voice = render_voice(wave, pitch, DUR, 50, gate, SAMPLE_RATE, sound)
            self.assertEqual(len(voice), voice_samples(DUR, gate))
            self.assertTrue(any(v != 0 for v in voice), "全サンプルが 0")
    return test


for _snd in SOUND_SETS:
    for _w in WAVES:
        for _pitch in PITCHES:
            tag = f"{_snd}_w{_w}_p{_pitch}"
            setattr(VoiceDeterminism, f"test_{tag}", _det_test(_snd, _w, _pitch))
            setattr(VoiceBounds, f"test_{tag}", _bounds_test(_snd, _w, _pitch))
            setattr(VoiceNonEmpty, f"test_{tag}", _nonempty_test(_snd, _w, _pitch))


class TestBassAudibility(unittest.TestCase):
    """低音ベースは音高が下がっても可聴倍音を持ち続ける (擬似ベース強調)。"""

    def _hp_ratio(self, pitch):
        import math
        voice = render_voice(WAVE_TRIANGLE, pitch, DUR, 50, 80, SAMPLE_RATE)
        rc = 1 / (2 * math.pi * 180)
        alpha = rc / (rc + 1 / SAMPLE_RATE)
        y = xp = 0.0
        hp = 0.0
        for x in voice:
            y = alpha * (y + x - xp)
            xp = x
            hp += y * y
        full = sum(x * x for x in voice) or 1
        return (hp / len(voice)) ** 0.5 / ((full / len(voice)) ** 0.5)

    def test_low_bass_notes_keep_audible_core(self):
        for pitch in (33, 36, 40, 45):
            with self.subTest(pitch=pitch):
                self.assertGreater(self._hp_ratio(pitch), 0.2)


if __name__ == "__main__":
    unittest.main()
