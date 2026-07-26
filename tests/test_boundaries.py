"""境界値・堅牢性 — すべてのアクションが極端な入力でも破綻しない。

各 set_* は範囲外を必ずクランプし、編集操作 (音符・レイヤー・移調・反転) は
どんな状態からでも有効な Project を保つ。純粋関数なので元は不変。
"""

import unittest

from picoseq.core import actions
from picoseq.core.constants import (
    BPM_MAX,
    BPM_MIN,
    MAX_LAYERS,
    PART_COUNT,
    PATTERN_COUNT,
    PITCH_MAX,
    PITCH_MIN,
    SEED_MAX,
    SEED_MIN,
)
from picoseq.core.project import layer_count, new_project
from picoseq.core.serialize import dumps


class TestClamps(unittest.TestCase):
    def setUp(self):
        self.p = actions.generate_phrase(actions.set_seed(new_project(), 42))

    def test_bpm_clamped(self):
        self.assertEqual(actions.set_bpm(self.p, -100).bpm, BPM_MIN)
        self.assertEqual(actions.set_bpm(self.p, 10 ** 9).bpm, BPM_MAX)

    def test_beats_clamped(self):
        self.assertEqual(actions.set_beats(self.p, 0).beats, 2)
        self.assertEqual(actions.set_beats(self.p, 999).beats, 7)

    def test_key_clamped(self):
        self.assertEqual(actions.set_key(self.p, -9).key, 0)
        self.assertEqual(actions.set_key(self.p, 99).key, 11)

    def test_seed_clamped(self):
        self.assertEqual(actions.set_seed(self.p, -5).seed, SEED_MIN)
        self.assertEqual(actions.set_seed(self.p, 10 ** 12).seed, SEED_MAX)

    def test_part_params_clamped_every_wave(self):
        for wave in range(PART_COUNT):
            with self.subTest(wave=wave):
                self.assertEqual(actions.set_part_tone(self.p, wave, 999)
                                 .parts[wave][0].tone, 100)
                self.assertEqual(actions.set_part_tone(self.p, wave, -9)
                                 .parts[wave][0].tone, 0)
                self.assertEqual(actions.set_part_gate(self.p, wave, 0)
                                 .parts[wave][0].gate, 10)
                self.assertEqual(actions.set_part_gate(self.p, wave, 999)
                                 .parts[wave][0].gate, 100)
                self.assertEqual(actions.set_part_volume(self.p, wave, -9)
                                 .parts[wave][0].volume, 0)
                self.assertEqual(actions.set_part_volume(self.p, wave, 999)
                                 .parts[wave][0].volume, 100)

    def test_no_change_returns_same_object(self):
        self.assertIs(actions.set_bpm(self.p, self.p.bpm), self.p)
        self.assertIs(actions.set_key(self.p, self.p.key), self.p)
        self.assertIs(actions.set_part_volume(self.p, 0, self.p.parts[0][0].volume),
                      self.p)

    def test_invalid_wave_raises(self):
        for wave in (-1, 4, 99):
            with self.subTest(wave=wave):
                with self.assertRaises((ValueError, IndexError)):
                    actions.set_part_tone(self.p, wave, 50)


class TestPurity(unittest.TestCase):
    """アクションは元のプロジェクトを一切書き換えない (frozen だが二重に確認)。"""

    def test_setters_do_not_mutate(self):
        p = actions.generate_phrase(actions.set_seed(new_project(), 7))
        snapshot = dumps(p)
        actions.set_bpm(p, 200)
        actions.set_part_volume(p, 1, 10)
        actions.transpose(p, 12)
        actions.reverse_phrase(p)
        actions.clear_part(p, 2)
        self.assertEqual(dumps(p), snapshot)


class TestLayerBoundaries(unittest.TestCase):
    def setUp(self):
        self.p = actions.generate_phrase(actions.set_seed(new_project(), 3))

    def test_add_layer_up_to_max_then_stops(self):
        p = self.p
        for _ in range(MAX_LAYERS + 5):
            p = actions.add_layer(p, 0)
        self.assertLessEqual(layer_count(p, 0), MAX_LAYERS)

    def test_remove_layer_never_below_one(self):
        p = actions.add_layer(self.p, 0)
        p = actions.remove_layer(p, 0, 1)      # 追加した層を消す → 1 層に戻る
        self.assertEqual(layer_count(p, 0), 1)
        with self.assertRaises(ValueError):    # 最後の 1 層は消せない
            actions.remove_layer(p, 0, 0)

    def test_remove_invalid_layer_is_safe(self):
        # 例外か無変更 — 落ちさえしなければよい
        try:
            actions.remove_layer(self.p, 0, 99)
        except (ValueError, IndexError):
            pass


class TestTranspose(unittest.TestCase):
    def setUp(self):
        self.p = actions.generate_phrase(actions.set_seed(new_project(), 42))

    def test_extreme_transpose_stays_in_range(self):
        for semis in (-96, -12, 12, 96, 240):
            with self.subTest(semis=semis):
                p = actions.transpose(self.p, semis)
                from picoseq.core.phrase import active_notes
                for _, n in active_notes(p.phrase):
                    self.assertTrue(PITCH_MIN <= n.pitch <= PITCH_MAX)

    def test_transpose_zero_is_noop(self):
        self.assertEqual(actions.transpose(self.p, 0).phrase, self.p.phrase)

    def test_reverse_twice_restores(self):
        once = actions.reverse_phrase(self.p)
        twice = actions.reverse_phrase(once)
        self.assertEqual(twice.phrase, self.p.phrase)


class TestPatternBoundaries(unittest.TestCase):
    def setUp(self):
        self.p = actions.generate_phrase(actions.set_seed(new_project(), 42))

    def test_invalid_slot_raises(self):
        for slot in (-1, PATTERN_COUNT, 999):
            with self.subTest(slot=slot):
                with self.assertRaises((ValueError, IndexError)):
                    actions.save_pattern(self.p, slot)

    def test_name_is_trimmed(self):
        p = actions.save_pattern(self.p, 0)
        p = actions.rename_pattern(p, 0, "  改行\nと  空白  " * 5)
        name = p.patterns[0].name
        self.assertNotIn("\n", name)
        self.assertLessEqual(len(name), 24)

    def test_free_slot_after_fill(self):
        p = self.p
        for slot in range(PATTERN_COUNT):
            p = actions.save_pattern(p, slot)
        self.assertEqual(actions.free_pattern_slot(p), -1)


class TestSongBoundaries(unittest.TestCase):
    def setUp(self):
        self.p = actions.save_pattern(
            actions.generate_phrase(actions.set_seed(new_project(), 42)), 0)

    def test_toggle_out_of_range_is_safe(self):
        for track, block in ((-1, 0), (99, 0), (0, -1), (0, 999)):
            with self.subTest(track=track, block=block):
                try:
                    actions.toggle_song_cell(self.p, track, block, 0)
                except (ValueError, IndexError):
                    pass


if __name__ == "__main__":
    unittest.main()
