"""自動作成のテスト — 決定論と音楽的な不変条件。"""

import unittest

from picoseq.core.composer import DRUM_PITCH, compose
from picoseq.core.constants import (
    MAX_NOTES,
    PITCH_MAX,
    PITCH_MIN,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
    steps_per_phrase,
)
from picoseq.core.music import SCALE_IDS, in_scale
from picoseq.core.phrase import active_notes, count_notes

ALL_CASES = [(beats, key, scale_id, seed)
             for beats in (3, 4, 7)
             for key in (0, 7)
             for scale_id in SCALE_IDS
             for seed in (1, 99)]


class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        for case in ALL_CASES:
            with self.subTest(case=case):
                self.assertEqual(compose(*case), compose(*case))

    def test_different_seeds_differ(self):
        for seed_a, seed_b in [(1, 2), (10, 11), (500, 501)]:
            with self.subTest(seeds=(seed_a, seed_b)):
                self.assertNotEqual(compose(4, 0, "minor", seed_a),
                                    compose(4, 0, "minor", seed_b))

    def test_default_progression_matches_none(self):
        """progression 省略と None 指定は同一 (既存ゴールデンの保全)。"""
        self.assertEqual(compose(4, 0, "minor", 42),
                         compose(4, 0, "minor", 42, None))

    def test_custom_progression_changes_output(self):
        default = compose(4, 0, "minor", 42)
        custom = compose(4, 0, "minor", 42, (3, 3, 3, 3))
        self.assertNotEqual(default, custom)

    def test_custom_progression_deterministic(self):
        self.assertEqual(compose(4, 0, "major", 9, (0, 4, 5, 3)),
                         compose(4, 0, "major", 9, (0, 4, 5, 3)))

    def test_seed_selects_varied_progressions(self):
        """指定なしのとき、シード値でコード進行が選ばれ、多くの種類が現れる。"""
        from picoseq.core.music import chord_at, progression_choices
        from picoseq.core.prng import Rng

        used = set()
        for scale in ("major", "minor"):
            choices = progression_choices(scale)
            for seed in range(1, 200):
                rng = Rng(seed)
                used.add((scale, choices[rng.next_int(len(choices))]))
        # major13 + minor12 の進行がほぼ出尽くす
        self.assertGreaterEqual(len(used), 20)

    def test_explicit_progression_overrides_seed_pick(self):
        """進行を明示したら、シード選択より優先される。"""
        forced = compose(4, 0, "minor", 5, (0, 0, 0, 0))
        # 同じ進行を明示すれば毎回同じ
        self.assertEqual(forced, compose(4, 0, "minor", 5, (0, 0, 0, 0)))

    def test_chosen_progression_in_choices_and_deterministic(self):
        from picoseq.core.composer import chosen_progression
        from picoseq.core.music import progression_choices
        for scale in ("major", "minor", "japanese", "battle"):
            choices = progression_choices(scale)
            for seed in (1, 7, 42, 300):
                with self.subTest(scale=scale, seed=seed):
                    prog = chosen_progression(scale, seed)
                    self.assertIn(prog, choices)
                    self.assertEqual(prog, chosen_progression(scale, seed))

    def test_chosen_progression_drives_bass_roots(self):
        """表示用の chosen_progression が、実際の曲のベース根音と一致する。

        自動作成のベースは各半小節でコードの根音を土台にするので、
        小節頭のベース音のクラスは進行の各コードの根音クラスに一致する。
        """
        from picoseq.core.composer import chosen_progression
        from picoseq.core.music import chord_at
        from picoseq.core.constants import WAVE_TRIANGLE

        beats, key, scale, seed = 4, 0, "minor", 7
        prog = chosen_progression(scale, seed)
        half = beats * 2  # 半小節のステップ数
        buf = compose(beats, key, scale, seed)
        bass = {n.step: n for _, n in active_notes(buf) if n.wave == WAVE_TRIANGLE}
        # 各半小節の頭のベース (存在すれば) は、その区画のコード根音クラス
        for window in range(4):
            step = window * half
            if step in bass:
                chord = chord_at(key, scale, step, beats, prog)
                self.assertEqual(bass[step].pitch % 12, chord.root % 12)

    def test_chosen_progression_respects_explicit(self):
        from picoseq.core.composer import chosen_progression
        self.assertEqual(chosen_progression("minor", 5, None, (1, 2, 3, 4)),
                         (1, 2, 3, 4))


class TestInvariants(unittest.TestCase):
    def test_notes_within_bounds(self):
        for case in ALL_CASES:
            steps = steps_per_phrase(case[0])
            with self.subTest(case=case):
                buffer = compose(*case)
                self.assertLessEqual(count_notes(buffer), MAX_NOTES)
                for _, note in active_notes(buffer):
                    self.assertTrue(PITCH_MIN <= note.pitch <= PITCH_MAX)
                    self.assertTrue(0 <= note.step < steps)
                    self.assertGreaterEqual(note.dur, 1)
                    self.assertLessEqual(note.step + note.dur, steps)

    def test_all_parts_present(self):
        for scale_id in SCALE_IDS:
            with self.subTest(scale=scale_id):
                buffer = compose(4, 0, scale_id, 5)
                waves = {note.wave for _, note in active_notes(buffer)}
                self.assertEqual(waves, {WAVE_PULSE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW})

    def test_melody_stays_in_scale(self):
        for scale_id in SCALE_IDS:
            for key in (0, 7):
                with self.subTest(scale=scale_id, key=key):
                    buffer = compose(4, key, scale_id, 3)
                    for _, note in active_notes(buffer):
                        if note.wave == WAVE_PULSE:
                            self.assertTrue(in_scale(note.pitch, key, scale_id),
                                            f"{note.pitch} がスケール外")

    def test_drums_have_fixed_pitch(self):
        buffer = compose(4, 0, "minor", 8)
        for _, note in active_notes(buffer):
            if note.wave == WAVE_NOISE:
                self.assertEqual(note.pitch, DRUM_PITCH)


class TestStyles(unittest.TestCase):
    def test_battle_is_dense(self):
        """ボス戦は音数が多く、勢いのある伴奏になる。"""
        buffer = compose(4, 0, "battle", 12)
        bass = [n for _, n in active_notes(buffer) if n.wave == WAVE_TRIANGLE]
        backing = [n for _, n in active_notes(buffer) if n.wave == WAVE_SAW]
        self.assertGreaterEqual(len(bass), 12)
        self.assertGreaterEqual(len(backing), 12)

    def test_japanese_drum_anchor(self):
        """和風のリズムは小節頭に長い一打を置く (スタイル 3/5 以外)。"""
        # japanese の太鼓型を確実に引くシードを探す
        for seed in range(1, 60):
            drums = {note.step: note for _, note in
                     active_notes(compose(4, 0, "japanese", seed))
                     if note.wave == WAVE_NOISE}
            if drums.get(0) is not None and drums[0].dur == 4:
                self.assertIn(14, drums)  # 小節末 (16-2)
                return
        self.fail("和風の太鼓型が見つからない")

    def test_downbeat_always_present(self):
        """通常拍子のリズムは、どのスタイル・どの曲調でも小節頭を必ず打つ。"""
        for scale in ("major", "minor", "battle"):
            for seed in (1, 12, 55, 300, 7777):
                with self.subTest(scale=scale, seed=seed):
                    drum_steps = {note.step for _, note in
                                  active_notes(compose(4, 0, scale, seed))
                                  if note.wave == WAVE_NOISE}
                    self.assertIn(0, drum_steps)
                    self.assertIn(16, drum_steps)

    def test_huge_style_variety(self):
        """大量のシード値がすべて異なる曲になる (バリエーションの豊富さ)。"""
        results = {compose(4, 0, "minor", seed) for seed in range(1, 121)}
        self.assertGreaterEqual(len(results), 118)  # ほぼ全部が別の曲

    def test_variety_in_every_scale(self):
        for scale in ("major", "minor", "japanese", "battle"):
            with self.subTest(scale=scale):
                results = {compose(4, 0, scale, seed) for seed in range(1, 41)}
                self.assertGreaterEqual(len(results), 38)

    def test_style_counts_are_reachable(self):
        """各パートのすべてのスタイルが、どこかのシードで実際に選ばれる。"""
        from picoseq.core.composer import (
            BACKING_STYLES,
            BASS_STYLES,
            DRUM_STYLES,
            MELODY_RHYTHMS,
            MOTIF_MODES,
        )
        from picoseq.core.prng import Rng
        seen = [set(), set(), set(), set(), set()]
        counts = (BASS_STYLES, BACKING_STYLES, DRUM_STYLES, MELODY_RHYTHMS, MOTIF_MODES)
        for seed in range(1, 400):
            rng = Rng(seed)
            for i, count in enumerate(counts):
                seen[i].add(rng.next_int(count))
        for chosen, count in zip(seen, counts):
            self.assertEqual(len(chosen), count)


if __name__ == "__main__":
    unittest.main()
