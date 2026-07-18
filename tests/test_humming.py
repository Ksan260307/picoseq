"""鼻歌解析のテスト — 合成音声からのメロディ検出。"""

import math
import unittest
from statistics import median

from picoseq.core.humming import (
    _correct_octaves,
    decimate,
    detect_melody,
    frame_pitches,
    pitches_to_notes,
)
from picoseq.core.music import in_scale

RATE = 22050


def _tone(freq, seconds, rate=RATE, volume=12000, harmonics=None):
    """サイン波 (声の代わり)。harmonics=[(倍率, 振幅比)] で倍音を足せる。"""
    out = []
    for i in range(int(seconds * rate)):
        s = volume * math.sin(2 * math.pi * freq * i / rate)
        for mult, amp in (harmonics or ()):
            s += volume * amp * math.sin(2 * math.pi * freq * mult * i / rate)
        out.append(int(s))
    return out


def _silence(seconds, rate=RATE):
    return [0] * int(seconds * rate)


def _detected_midi(samples):
    reduced, rate = decimate(samples, RATE)
    voiced = [p for p in frame_pitches(reduced, rate) if p is not None]
    return median(voiced) if voiced else None


class TestDecimate(unittest.TestCase):
    def test_reduces_rate(self):
        samples, rate = decimate([100] * 22050, 22050)
        self.assertLessEqual(rate, 11025)
        self.assertGreater(len(samples), 0)

    def test_low_rate_passthrough(self):
        samples, rate = decimate([1, 2, 3], 8000)
        self.assertEqual((samples, rate), ([1, 2, 3], 8000))


class TestFramePitches(unittest.TestCase):
    def test_a3_detected(self):
        samples, rate = decimate(_tone(220.0, 1.0), RATE)
        pitches = frame_pitches(samples, rate)
        voiced = [p for p in pitches if p is not None]
        self.assertGreater(len(voiced), len(pitches) // 2)
        # A3 = MIDI 57。±1 半音まで許す
        for p in voiced[2:-2]:
            self.assertTrue(abs(p - 57) <= 1, f"{p} != 57")

    def test_silence_is_rest(self):
        samples, rate = decimate(_silence(1.0), RATE)
        pitches = frame_pitches(samples, rate)
        self.assertTrue(all(p is None for p in pitches))

    def test_deterministic(self):
        samples, rate = decimate(_tone(330.0, 0.5), RATE)
        self.assertEqual(frame_pitches(samples, rate), frame_pitches(samples, rate))


class TestPitchesToNotes(unittest.TestCase):
    def test_two_tones_become_two_notes(self):
        # 前半 A、後半 E 相当のフレーム列
        pitches = [57] * 20 + [64] * 20
        notes = pitches_to_notes(pitches, 32, key=9, scale_id="minor")
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].step, 0)
        self.assertEqual(notes[0].step + notes[0].dur, notes[1].step)
        self.assertEqual(notes[1].step + notes[1].dur, 32)

    def test_rest_gap_preserved(self):
        pitches = [60] * 10 + [None] * 10 + [67] * 10
        notes = pitches_to_notes(pitches, 30, key=0, scale_id="major")
        self.assertEqual(len(notes), 2)
        self.assertGreater(notes[1].step, notes[0].step + notes[0].dur)

    def test_snapped_to_scale(self):
        # 半音 (C#) を歌っても C メジャーの音に寄る
        pitches = [61] * 20
        notes = pitches_to_notes(pitches, 16, key=0, scale_id="major")
        for note in notes:
            self.assertTrue(in_scale(note.pitch, 0, "major"))

    def test_custom_scale_snap(self):
        pitches = [60] * 20
        notes = pitches_to_notes(pitches, 16, key=0, scale_id="photo",
                                 custom=(0, 3, 7))
        for note in notes:
            self.assertTrue(in_scale(note.pitch, 0, "photo", (0, 3, 7)))

    def test_low_voice_transposed_into_range(self):
        pitches = [45] * 20  # 低い声 (A2)
        notes = pitches_to_notes(pitches, 16, key=9, scale_id="minor")
        self.assertTrue(notes)
        for note in notes:
            self.assertTrue(60 <= note.pitch <= 84)

    def test_empty_and_silent(self):
        self.assertEqual(pitches_to_notes([], 32, 0, "major"), [])
        self.assertEqual(pitches_to_notes([None] * 10, 32, 0, "major"), [])


class TestDetectMelody(unittest.TestCase):
    def test_hum_two_notes(self):
        samples = _tone(220.0, 1.0) + _silence(0.3) + _tone(330.0, 1.0)
        notes = detect_melody(samples, RATE, 32, key=9, scale_id="minor")
        self.assertGreaterEqual(len(notes), 2)
        # 2 音の高さの差はおよそ完全5度 (7 半音)
        pitch_a = notes[0].pitch
        pitch_b = notes[-1].pitch
        self.assertTrue(6 <= abs(pitch_b - pitch_a) <= 8,
                        f"{pitch_a} -> {pitch_b}")

    def test_all_notes_are_melody_part(self):
        notes = detect_melody(_tone(262.0, 1.0), RATE, 32, 0, "major")
        for note in notes:
            self.assertEqual(note.wave, 0)
            self.assertTrue(0 <= note.step < 32)
            self.assertLessEqual(note.step + note.dur, 32)

    def test_deterministic(self):
        samples = _tone(262.0, 0.8)
        self.assertEqual(detect_melody(samples, RATE, 32, 0, "major"),
                         detect_melody(samples, RATE, 32, 0, "major"))

    def test_quiet_input_gives_nothing(self):
        notes = detect_melody(_silence(1.0), RATE, 32, 0, "major")
        self.assertEqual(notes, [])


class TestPitchAccuracy(unittest.TestCase):
    """音高の推定精度 (純音は誤差ゼロを狙う)。"""

    def test_pure_tones_exact(self):
        for freq, expected in [(220, 57), (262, 60), (330, 64),
                               (440, 69), (523, 72)]:
            with self.subTest(freq=freq):
                self.assertEqual(_detected_midi(_tone(freq, 0.7)), expected)

    def test_harmonic_rich_no_octave_error(self):
        """倍音の多い (声に近い) 音でもオクターブを取り違えない。"""
        harmonics = [(2, 0.6), (3, 0.4), (4, 0.25)]
        for freq, expected in [(220, 57), (330, 64), (196, 55)]:
            with self.subTest(freq=freq):
                got = _detected_midi(_tone(freq, 0.7, harmonics=harmonics))
                self.assertEqual(got, expected)

    def test_level_independent(self):
        """音量が変わっても同じ高さに検出される。"""
        loud = _detected_midi(_tone(262, 0.6, volume=20000))
        quiet = _detected_midi(_tone(262, 0.6, volume=3000))
        self.assertEqual(loud, quiet)


class TestOctaveCorrection(unittest.TestCase):
    def test_keeps_fifth(self):
        """完全5度 (7半音) の跳躍は畳まない。"""
        self.assertEqual(_correct_octaves([57] * 5 + [64] * 5),
                         [57] * 5 + [64] * 5)

    def test_fixes_octave_glitch(self):
        """1 フレームだけオクターブ跳んだ誤りを中央値へ戻す。"""
        self.assertEqual(_correct_octaves([60] * 8 + [72] + [60] * 3),
                         [60] * 12)

    def test_keeps_octave_span_melody(self):
        """オクターブ幅の旋律 (C4→C5) はそのまま残す。"""
        self.assertEqual(_correct_octaves([60] * 4 + [72] * 4),
                         [60] * 4 + [72] * 4)

    def test_ignores_none(self):
        self.assertEqual(_correct_octaves([None, 60, None]), [None, 60, None])

    def test_empty(self):
        self.assertEqual(_correct_octaves([]), [])


if __name__ == "__main__":
    unittest.main()
