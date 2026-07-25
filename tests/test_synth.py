"""固定小数点シンセのテスト — 決定論・波形・エンベロープ。"""

import unittest
import zlib

from picoseq.core.constants import (
    SAMPLE_RATE,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
)
from picoseq.core.renderer import clip_to_pcm
from picoseq.core.synth import (
    LFSR_SEED,
    PEAKS,
    alpha_q15,
    envelope_segments,
    lfsr_step,
    phase_increment,
    render_voice,
    voice_samples,
)

GOLDEN_VOICE_CRC = {
    WAVE_PULSE: 132701679,
    WAVE_TRIANGLE: 71178892,   # 擬似ベース強調 (倍音を重ねて可聴化) 後の波形
    WAVE_NOISE: 3794188056,
    WAVE_SAW: 3051989150,
}


class TestPhase(unittest.TestCase):
    def test_pinned_increment(self):
        self.assertEqual(phase_increment(440000, 44100), 42852281)
        self.assertEqual(phase_increment(880000, 44100), 85704562)

    def test_octave_doubles(self):
        low = phase_increment(440000, 44100)
        high = phase_increment(880000, 44100)
        self.assertLessEqual(abs(high - low * 2), 1)

    def test_frequency_accuracy(self):
        inc = phase_increment(440000, 44100)
        freq = inc * 44100 / 2 ** 32
        self.assertAlmostEqual(freq, 440.0, delta=0.01)


class TestFilterCoeff(unittest.TestCase):
    def test_monotonic_in_cutoff(self):
        values = [alpha_q15(hz, SAMPLE_RATE) for hz in (100, 500, 1000, 5000)]
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[0], 0)

    def test_capped(self):
        self.assertEqual(alpha_q15(100000, SAMPLE_RATE), 31500)


class TestLfsr(unittest.TestCase):
    def test_pinned_states(self):
        s = LFSR_SEED
        states = []
        for _ in range(5):
            s = lfsr_step(s)
            states.append(s)
        self.assertEqual(states, [9485, 21126, 26947, 13473, 23120])

    def test_full_period(self):
        s = LFSR_SEED
        for n in range(1, 32768):
            s = lfsr_step(s)
            if s == LFSR_SEED:
                self.assertEqual(n, 32767)  # 最大周期
                return
        self.fail("周期が見つからない")

    def test_stays_in_15bit(self):
        s = LFSR_SEED
        for _ in range(1000):
            s = lfsr_step(s)
            self.assertTrue(0 < s < 2 ** 15)


class TestVoiceLength(unittest.TestCase):
    def test_gate_scaling(self):
        self.assertEqual(voice_samples(5512, 80), 7165)   # x1.3
        self.assertEqual(voice_samples(5512, 10), 1378)   # x0.25
        self.assertEqual(voice_samples(5512, 100), 8819)  # x1.6


class TestEnvelope(unittest.TestCase):
    def test_segments_cover_total(self):
        for wave in range(4):
            with self.subTest(wave=wave):
                segments = envelope_segments(wave, 10000, SAMPLE_RATE)
                self.assertEqual(sum(n for n, _ in segments), 10000)
                self.assertEqual(segments[0][1], PEAKS[wave])  # 立ち上がりでピーク
                self.assertEqual(segments[-1][1], 0)           # 最後は無音へ

    def test_short_note_still_valid(self):
        segments = envelope_segments(WAVE_PULSE, 100, SAMPLE_RATE)
        self.assertEqual(sum(n for n, _ in segments), 100)


class TestRenderVoice(unittest.TestCase):
    def test_deterministic(self):
        a = render_voice(WAVE_PULSE, 60, 5512, 50, 80)
        b = render_voice(WAVE_PULSE, 60, 5512, 50, 80)
        self.assertEqual(a, b)

    def test_golden_crc(self):
        """波形の回帰検査 — 音を変える変更を検知する。"""
        for wave, crc in GOLDEN_VOICE_CRC.items():
            with self.subTest(wave=wave):
                voice = render_voice(wave, 60, 5512, 50, 80)
                self.assertEqual(zlib.crc32(clip_to_pcm(voice)), crc)

    def test_bass_has_audible_harmonics(self):
        """低いベース音でも可聴域 (>180Hz) に倍音の芯がある (擬似ベース強調)。

        基音のみだと >180Hz の比率は約 0.19 に留まる。倍音を重ねることで
        小型スピーカーやノート PC でもベースが聞こえるようになっている。
        """
        import math

        from picoseq.core.constants import SAMPLE_RATE
        voice = render_voice(WAVE_TRIANGLE, 36, 5512, 50, 80)  # 低い C2
        rc = 1 / (2 * math.pi * 180)                            # 180Hz ハイパス
        alpha = rc / (rc + 1 / SAMPLE_RATE)
        y = xp = 0.0
        hp_sq = 0.0
        for x in voice:
            y = alpha * (y + x - xp)
            xp = x
            hp_sq += y * y
        hp_rms = (hp_sq / len(voice)) ** 0.5
        full_rms = (sum(x * x for x in voice) / len(voice)) ** 0.5
        self.assertGreater(hp_rms, full_rms * 0.25)            # 芯が可聴域にある

    def test_length_matches_gate(self):
        voice = render_voice(WAVE_SAW, 60, 5512, 50, 80)
        self.assertEqual(len(voice), voice_samples(5512, 80))

    def test_amplitude_bounded(self):
        for wave in range(4):
            with self.subTest(wave=wave):
                voice = render_voice(wave, 60, 5512, 50, 80)
                limit = PEAKS[wave] * 2 + 1  # 帯域通過の合成でも 2 倍以内
                self.assertTrue(all(abs(v) <= limit for v in voice))

    def test_not_silent(self):
        for wave in range(4):
            with self.subTest(wave=wave):
                voice = render_voice(wave, 60, 5512, 50, 80)
                self.assertGreater(max(map(abs, voice)), PEAKS[wave] // 4)

    def test_tone_changes_pulse_duty(self):
        thin = render_voice(WAVE_PULSE, 60, 5512, 0, 80)
        square = render_voice(WAVE_PULSE, 60, 5512, 100, 80)
        self.assertNotEqual(thin, square)
        # デューティ比: tone=0 は高区間が短い
        thin_high = sum(1 for v in thin if v > 0)
        square_high = sum(1 for v in square if v > 0)
        self.assertLess(thin_high, square_high)

    def test_noise_filter_modes_differ(self):
        low = render_voice(WAVE_NOISE, 60, 5512, 0, 80)
        band = render_voice(WAVE_NOISE, 60, 5512, 50, 80)
        high = render_voice(WAVE_NOISE, 60, 5512, 100, 80)
        self.assertNotEqual(low, band)
        self.assertNotEqual(band, high)

    def test_pitch_changes_output(self):
        a = render_voice(WAVE_PULSE, 60, 5512, 50, 80)
        b = render_voice(WAVE_PULSE, 72, 5512, 50, 80)
        self.assertNotEqual(a, b)


if __name__ == "__main__":
    unittest.main()
