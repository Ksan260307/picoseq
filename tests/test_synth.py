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

# パートごとのピーク音量 (PEAKS) を実測 RMS で釣り合わせ直した後の波形。
GOLDEN_VOICE_CRC = {
    WAVE_PULSE: 3039640967,
    WAVE_TRIANGLE: 3219326059,  # 擬似ベース強調 (倍音を重ねて可聴化) 後の波形
    WAVE_NOISE: 157465462,
    WAVE_SAW: 4004919461,
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


class TestMixBalance(unittest.TestCase):
    """4 パートを混ぜたときの釣り合い — 実測 RMS で見る。

    ピーク値 (PEAKS) をそのまま音量と思うと外す。ベースは低音の倍音構成で
    実効エネルギーが大きく、伴奏は 2 段減衰で早く落ちるため、
    「ピークは 1/3 なのに聞こえ方は 1/4」のようなずれが出る。
    """

    def _phrases(self, count=8):
        from picoseq.core import actions
        from picoseq.core.music import SCALE_IDS
        from picoseq.core.project import new_project
        out = []
        for i in range(count):
            p = actions.set_scale(new_project(), SCALE_IDS[i % len(SCALE_IDS)])
            out.append(actions.generate_phrase(actions.set_seed(p, i + 1)))
        return out

    def _rms(self, pcm):
        from array import array
        values = array("h")
        values.frombytes(pcm)
        return (sum(v * v for v in values) / len(values)) ** 0.5

    def _part_rms(self, project, wave):
        from picoseq.core.renderer import render_phrase
        others = {(w, 0) for w in range(4) if w != wave}
        return self._rms(render_phrase(project, mute=others))

    def test_no_part_is_buried(self):
        """どのパートもメロディの 0.4 倍以上で鳴る (和音が消えない)。

        伴奏はかつて 0.37 倍で、刻みの型を 6 倍に増やしても聞こえなかった。
        """
        import statistics
        phrases = self._phrases()
        melody = statistics.median(self._part_rms(p, WAVE_PULSE) for p in phrases)
        for wave in (WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW):
            part = statistics.median(self._part_rms(p, wave) for p in phrases)
            with self.subTest(wave=wave):
                self.assertGreater(part, melody * 0.4,
                                   f"パート {wave} がミックスで埋もれている")

    def test_no_part_dominates(self):
        """どのパートもメロディの 2 倍を超えない (主役が埋もれない)。"""
        import statistics
        phrases = self._phrases()
        melody = statistics.median(self._part_rms(p, WAVE_PULSE) for p in phrases)
        for wave in (WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW):
            part = statistics.median(self._part_rms(p, wave) for p in phrases)
            with self.subTest(wave=wave):
                self.assertLess(part, melody * 2.0)

    # 旧配分 (ベース 0.30 / 伴奏 0.10) で実際に 16bit の上限へ達していた組み合わせ。
    # 無作為な標本では 100 フレーズに 1 つしか出ないので、現物を固定して見張る。
    CLIPPED_CASES = (("pentatonic", 9), ("wholetone", 20), ("battle", 8),
                     ("battle", 12), ("battle", 20), ("phrygian", 20))

    def _peak(self, scale_id, seed):
        from array import array

        from picoseq.core import actions
        from picoseq.core.project import new_project
        from picoseq.core.renderer import render_phrase
        p = actions.set_scale(new_project(), scale_id)
        p = actions.generate_phrase(actions.set_seed(p, seed))
        values = array("h")
        values.frombytes(render_phrase(p))
        return max(max(values), -min(values))

    def test_mix_does_not_clip(self):
        """4 パートの立ち上がりが重なっても 16bit の上限に触れない。"""
        for scale_id, seed in self.CLIPPED_CASES:
            with self.subTest(scale=scale_id, seed=seed):
                self.assertLess(self._peak(scale_id, seed), 32767,
                                "ミックスが上限に達している")

    def test_mix_does_not_clip_in_a_wide_sample(self):
        from picoseq.core.music import SCALE_IDS
        for scale_id in SCALE_IDS[:12]:
            for seed in (3, 9, 20):
                with self.subTest(scale=scale_id, seed=seed):
                    self.assertLess(self._peak(scale_id, seed), 32767)

    def test_peak_budget_leaves_headroom(self):
        """ピークの総和が上限の 8 割以内 (重なりの余地を残す)。"""
        self.assertLess(sum(PEAKS.values()), 32767 * 0.8)

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
