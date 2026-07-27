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
        # 型が 200 種規模あるので、全部を引くにはシードを多めに回す必要がある
        # (クーポンコレクター: 208 種なら平均 208*ln208 ≈ 1100 回)
        for seed in range(1, 6000):
            rng = Rng(seed)
            for i, count in enumerate(counts):
                seen[i].add(rng.next_int(count))
        for chosen, count in zip(seen, counts):
            self.assertEqual(len(chosen), count)

    def test_style_combinations_expanded(self):
        """リズム・ベースが 200 種規模、組み合わせは 2,800 万通り超。"""
        from picoseq.core.composer import (
            BACKING_STYLES,
            BASS_STYLES,
            DRUM_STYLES,
            MELODY_RHYTHMS,
            MOTIF_MODES,
        )
        combos = (BASS_STYLES * BACKING_STYLES * DRUM_STYLES
                  * MELODY_RHYTHMS * MOTIF_MODES)
        self.assertGreaterEqual(combos, 350000000)
        self.assertGreaterEqual(DRUM_STYLES, 200)   # リズムを最重点で増やした
        self.assertGreaterEqual(BASS_STYLES, 280)
        self.assertGreaterEqual(BACKING_STYLES, 100)
        self.assertGreaterEqual(MELODY_RHYTHMS, 10)
        self.assertGreaterEqual(MOTIF_MODES, 6)


class TestDrumPatterns(unittest.TestCase):
    """リズムのパターン表 — 数・重複・拍子対応・密度の幅を担保する。"""

    def _hits(self, style, beats=4, scale="major", seed=42, steps=None):
        from picoseq.core.composer import _compose_drums
        from picoseq.core.constants import MEASURES
        from picoseq.core.prng import Rng
        steps = steps if steps is not None else beats * 4 * MEASURES
        out = []
        _compose_drums(None, lambda p, s, w, d: out.append((s, d)),
                       Rng(seed), beats, scale, steps, style)
        return out

    def test_declared_count_is_the_axis_product(self):
        """宣言数 = 骨格 × 密度 × アクセント (数え間違いを防ぐ)。"""
        from picoseq.core.composer import (
            DRUM_ACCENT_COUNT, DRUM_DENSITY_COUNT, DRUM_SKELETON_COUNT,
            DRUM_STYLES, _DRUM_ACCENTS, _DRUM_FILL, _DRUM_SKELETONS,
        )
        self.assertEqual(DRUM_SKELETON_COUNT, len(_DRUM_SKELETONS))
        self.assertEqual(DRUM_DENSITY_COUNT, len(_DRUM_FILL))
        self.assertEqual(DRUM_ACCENT_COUNT, len(_DRUM_ACCENTS))
        self.assertEqual(
            DRUM_STYLES,
            DRUM_SKELETON_COUNT * DRUM_DENSITY_COUNT * DRUM_ACCENT_COUNT)

    def test_decode_covers_every_style_once(self):
        """style 番号と (骨格,密度,アクセント) が 1 対 1 に対応する。"""
        from picoseq.core.composer import DRUM_STYLES, decode_drum_style
        seen = {decode_drum_style(s) for s in range(DRUM_STYLES)}
        self.assertEqual(len(seen), DRUM_STYLES)

    def test_almost_every_pattern_is_distinct(self):
        """ほぼ全部が違う打点列になる (名前だけ増やしていない)。

        最高密度 (隙間をほぼ埋める) だと骨格やアクセントの差が埋もれて
        数個だけ一致する。それ以外は必ず別の形。
        """
        from picoseq.core.composer import DRUM_STYLES
        sigs = {tuple(self._hits(style)) for style in range(DRUM_STYLES)}
        self.assertGreaterEqual(len(sigs), int(DRUM_STYLES * 0.94),
                                "型の重複が多すぎる (軸が直交していない)")

    def test_density_spans_sparse_to_dense(self):
        """まばらな型から詰まった型まで幅がある (盛り上げ/抜きが作れる)。"""
        from picoseq.core.composer import DRUM_STYLES
        steps = 32
        densities = [len(self._hits(s, steps=steps)) / steps
                     for s in range(DRUM_STYLES)]
        self.assertLess(min(densities), 0.25)      # 抜ける型がある
        self.assertGreater(max(densities), 0.75)   # 詰める型がある

    def test_downbeat_always_present_in_every_pattern(self):
        """どの型・どの拍子でも小節頭は必ず鳴る (拍が見えなくならない)。"""
        from picoseq.core.composer import DRUM_STYLES
        for beats in range(2, 8):
            for style in range(DRUM_STYLES):
                steps = {s for s, _ in self._hits(style, beats=beats)}
                with self.subTest(beats=beats, style=style):
                    self.assertIn(0, steps)
                    self.assertIn(beats * 4, steps)   # 2 小節目の頭

    def test_no_pattern_is_silent(self):
        from picoseq.core.composer import DRUM_STYLES
        for beats in range(2, 8):
            for style in range(DRUM_STYLES):
                with self.subTest(beats=beats, style=style):
                    self.assertTrue(self._hits(style, beats=beats))

    def test_patterns_are_deterministic(self):
        from picoseq.core.composer import DRUM_STYLES
        for style in range(DRUM_STYLES):
            with self.subTest(style=style):
                self.assertEqual(self._hits(style), self._hits(style))

    def test_battle_is_denser_than_sparse_default(self):
        """激しい曲は隙間が埋まる (まばらな型でも厚くなる)。"""
        sparse_major = len(self._hits(5, scale="major"))
        sparse_battle = len(self._hits(5, scale="battle"))
        self.assertGreater(sparse_battle, sparse_major)

    def test_out_of_range_style_wraps_safely(self):
        """スタイル番号が範囲外でも落ちない (表の長さで折り返す)。"""
        self.assertTrue(self._hits(999))


class TestBassPatterns(unittest.TestCase):
    """ベースのパターン — 200 種規模で、すべて別の形になること。"""

    def _notes(self, style, beats=4, scale="major", seed=42):
        from picoseq.core.composer import _compose_bass
        from picoseq.core.constants import MEASURES
        from picoseq.core.music import chord_at
        from picoseq.core.prng import Rng
        steps = beats * 4 * MEASURES
        out = []
        _compose_bass(None, lambda p, s, w, d: out.append((p, s, d)),
                      Rng(seed), beats, scale, steps,
                      lambda s: chord_at(0, "major", s, beats, (0, 3, 1, 4), None),
                      style)
        return out

    def test_declared_count_is_the_axis_product(self):
        from picoseq.core.composer import (
            BASS_MOTION_COUNT, BASS_REGISTER_COUNT, BASS_RHYTHM_COUNT,
            BASS_STYLES, BASS_VARIATION_COUNT, _BASS_MOTIONS, _BASS_REGISTERS,
            _BASS_VARIATIONS,
        )
        self.assertEqual(BASS_MOTION_COUNT, len(_BASS_MOTIONS))
        self.assertEqual(BASS_VARIATION_COUNT, len(_BASS_VARIATIONS))
        self.assertEqual(BASS_REGISTER_COUNT, len(_BASS_REGISTERS))
        self.assertEqual(
            BASS_STYLES,
            BASS_MOTION_COUNT * BASS_RHYTHM_COUNT * BASS_VARIATION_COUNT
            * BASS_REGISTER_COUNT)

    def test_subdivisions_divide_the_bar_evenly(self):
        """刻みは小節を割り切る (拍から浮くポリリズムを土台に使わない)。"""
        from picoseq.core.composer import BASS_RHYTHM_COUNT, _bass_grid
        for msteps in (12, 16, 20):        # 3/4, 4/4, 5/4
            for rhythm in range(BASS_RHYTHM_COUNT):
                grid = _bass_grid(rhythm, msteps)
                with self.subTest(msteps=msteps, grid=grid):
                    self.assertEqual(msteps % grid, 0,
                                     f"刻み {grid} が小節 {msteps} を割り切らない")

    def test_registers_shift_the_whole_line_by_an_octave(self):
        """音域軸は打点を変えずに全音を 1 オクターブ上げる。

        音域は最も内側の軸なので、style と style+1 は音域だけが違う。
        音高が必ず変わるため、同じ打点でも確実に別パターンになる。
        """
        from picoseq.core.composer import BASS_STYLES, decode_bass_style
        checked = 0
        for style in range(0, BASS_STYLES, 2):
            self.assertEqual(decode_bass_style(style)[3], 0)
            self.assertEqual(decode_bass_style(style + 1)[3], 1)
            low = self._notes(style)
            high = self._notes(style + 1)
            with self.subTest(style=style):
                # 打点と長さは同じ
                self.assertEqual([(s, d) for _, s, d in low],
                                 [(s, d) for _, s, d in high])
                # 音高は 1 オクターブ上 (音域下限で折り返した分は除く)
                shifts = {h - l for (l, _, _), (h, _, _) in zip(low, high)}
                self.assertTrue(shifts <= {12, 0}, f"想定外の移動量 {shifts}")
            checked += 1
        self.assertGreater(checked, 100)

    def test_decode_covers_every_style_once(self):
        from picoseq.core.composer import BASS_STYLES, decode_bass_style
        seen = {decode_bass_style(s) for s in range(BASS_STYLES)}
        self.assertEqual(len(seen), BASS_STYLES)

    def test_every_pattern_is_distinct(self):
        """全 192 種が互いに違う (刻みを 2 の冪だけにしないのが効いている)。"""
        from picoseq.core.composer import BASS_STYLES
        sigs = {}
        for style in range(BASS_STYLES):
            sig = tuple(self._notes(style))
            self.assertNotIn(sig, sigs,
                             f"style {style} が style {sigs.get(sig)} と同じ")
            sigs[sig] = style

    def test_no_pattern_is_silent(self):
        from picoseq.core.composer import BASS_STYLES
        for beats in range(2, 8):
            for style in range(BASS_STYLES):
                with self.subTest(beats=beats, style=style):
                    self.assertTrue(self._notes(style, beats=beats))

    def test_downbeat_always_present(self):
        """どの型・どの拍子でも小節頭に土台を置く。"""
        from picoseq.core.composer import BASS_STYLES
        for beats in (3, 4, 5):
            for style in range(BASS_STYLES):
                steps = {s for _, s, _ in self._notes(style, beats=beats)}
                with self.subTest(beats=beats, style=style):
                    self.assertIn(0, steps)
                    self.assertIn(beats * 4, steps)

    def test_pitches_stay_in_range(self):
        from picoseq.core.composer import BASS_STYLES
        from picoseq.core.constants import PITCH_MAX, PITCH_MIN
        for style in range(BASS_STYLES):
            for pitch, _, _ in self._notes(style):
                self.assertTrue(PITCH_MIN <= pitch <= PITCH_MAX)

    def test_patterns_are_deterministic(self):
        from picoseq.core.composer import BASS_STYLES
        for style in range(0, BASS_STYLES, 7):
            with self.subTest(style=style):
                self.assertEqual(self._notes(style), self._notes(style))

    def test_density_spans_sparse_to_dense(self):
        from picoseq.core.composer import BASS_STYLES
        densities = [len(self._notes(s)) / 32 for s in range(BASS_STYLES)]
        self.assertLess(min(densities), 0.3)
        self.assertGreater(max(densities), 0.9)


class TestBackingPatterns(unittest.TestCase):
    """伴奏も軸の直積 — 取り方 × 置き方 × 長さ。"""

    def _notes(self, style, scale="major", beats=4, seed=42):
        from picoseq.core.composer import _compose_backing
        from picoseq.core.music import chord_at
        from picoseq.core.prng import Rng
        out = []
        _compose_backing(None, lambda p, s, w, d: out.append((p, s, d)),
                         Rng(seed), scale, beats * 4 * 2,
                         lambda s: chord_at(0, "major", s, beats, (0, 3, 1, 4), None),
                         style, beats)
        return out

    def test_declared_count_is_the_axis_product(self):
        from picoseq.core.composer import (
            BACKING_DUR_COUNT, BACKING_PLACEMENT_COUNT, BACKING_STYLES,
            BACKING_VOICING_COUNT,
        )
        self.assertEqual(
            BACKING_STYLES,
            BACKING_VOICING_COUNT * BACKING_PLACEMENT_COUNT * BACKING_DUR_COUNT)
        self.assertGreaterEqual(BACKING_STYLES, 100)   # 旧 12 種から拡張

    def test_every_pattern_is_distinct(self):
        from picoseq.core.composer import BACKING_STYLES
        sigs = {}
        for style in range(BACKING_STYLES):
            sig = tuple(self._notes(style))
            self.assertNotIn(sig, sigs,
                             f"style {style} が style {sigs.get(sig)} と同じ")
            sigs[sig] = style

    def test_no_pattern_is_silent(self):
        from picoseq.core.composer import BACKING_STYLES
        for beats in (3, 4, 5):
            for style in range(BACKING_STYLES):
                with self.subTest(beats=beats, style=style):
                    self.assertTrue(self._notes(style, beats=beats))

    def test_pitches_stay_in_range(self):
        from picoseq.core.composer import BACKING_STYLES
        from picoseq.core.constants import PITCH_MAX, PITCH_MIN
        for style in range(BACKING_STYLES):
            for pitch, _, _ in self._notes(style):
                self.assertTrue(PITCH_MIN <= pitch <= PITCH_MAX)

    def test_japanese_is_thinner(self):
        """和風は間を活かして薄くなる。"""
        from picoseq.core.composer import BACKING_STYLES
        normal = sum(len(self._notes(s)) for s in range(BACKING_STYLES))
        jp = sum(len(self._notes(s, scale="japanese")) for s in range(BACKING_STYLES))
        self.assertLess(jp, normal)

    def test_patterns_are_deterministic(self):
        from picoseq.core.composer import BACKING_STYLES
        for style in range(0, BACKING_STYLES, 7):
            with self.subTest(style=style):
                self.assertEqual(self._notes(style), self._notes(style))


class TestDrumDensity(unittest.TestCase):
    """密度の上限 — ノイズ 1 声が「壁」にならないこと。"""

    def _hits(self, style):
        from picoseq.core.composer import _compose_drums
        from picoseq.core.prng import Rng
        out = []
        _compose_drums(None, lambda p, s, w, d: out.append(s),
                       Rng(42), 4, "major", 32, style)
        return out

    def test_few_patterns_are_a_wall_of_noise(self):
        """密度上限を抑えたので、ほぼ全ステップを叩く型はごく少数。"""
        from picoseq.core.composer import DRUM_STYLES
        wall = sum(1 for s in range(DRUM_STYLES)
                   if len(self._hits(s)) / 32 >= 0.85)
        self.assertLess(wall, DRUM_STYLES * 0.05,
                        "壁ノイズの型が多すぎる (密度上限が高い)")

    def test_fill_ceiling_is_moderate(self):
        from picoseq.core.composer import _DRUM_FILL
        self.assertLessEqual(max(_DRUM_FILL), 0.7)
        self.assertEqual(min(_DRUM_FILL), 0.0)      # 芯だけの型も残す


class TestMelodyQuality(unittest.TestCase):
    """メロディが「歌える」ための不変条件 — 実測で見つかった問題への回帰テスト。"""

    def _melody(self, beats=4, key=0, scale_id="major", seed=1):
        return sorted((n for _, n in active_notes(compose(beats, key, scale_id, seed))
                       if n.wave == WAVE_PULSE), key=lambda n: n.step)

    def _chords_of(self, scale_id, seed, beats=4):
        """そのフレーズで実際に鳴っている和音を引く関数 (進行はシードで選ばれる)。"""
        from picoseq.core.composer import chosen_progression
        from picoseq.core.music import chord_at
        prog = chosen_progression(scale_id, seed)
        return lambda step: chord_at(0, scale_id, step, beats, prog)

    def _runs(self, melody):
        """同じ音が連続した長さの列。"""
        out = []
        run = 1
        for a, b in zip(melody, melody[1:]):
            if a.pitch == b.pitch:
                run += 1
            else:
                out.append(run)
                run = 1
        if melody:
            out.append(run)
        return out

    def test_same_pitch_never_exceeds_the_limit(self):
        """同音連打に上限がある (以前は最大 20 音も同じ音が続いた)。"""
        from picoseq.core.composer import MELODY_RUN_LIMIT
        for scale_id in SCALE_IDS[:12]:
            for seed in range(1, 21):
                melody = self._melody(scale_id=scale_id, seed=seed)
                longest = max(self._runs(melody), default=0)
                with self.subTest(scale=scale_id, seed=seed):
                    self.assertLessEqual(longest, MELODY_RUN_LIMIT,
                                         "同じ音が続きすぎる")

    def test_repeat_penalty_pushes_the_note_away(self):
        """留まっている回数が増えるほど「動かない」選択が高くつく。"""
        from picoseq.core.composer import _pick_melody_note
        from picoseq.core.music import chord_at
        from picoseq.core.prng import Rng
        notes = [60, 62, 64, 65, 67, 69, 71, 72]
        chord = chord_at(0, "major", 0, 4)
        stays_fresh = sum(1 for s in range(1, 61)
                          if _pick_melody_note(Rng(s), notes, 4, chord, 2,
                                               repeat=0) == 4)
        stays_tired = sum(1 for s in range(1, 61)
                          if _pick_melody_note(Rng(s), notes, 4, chord, 2,
                                               repeat=2) == 4)
        self.assertGreater(stays_fresh, stays_tired)
        self.assertEqual(stays_tired, 0)  # 2 回続いたらもう留まらない

    def test_step_away_breaks_a_run(self):
        """逃がし先は必ず別の音 (音階に 2 音以上あるかぎり)。"""
        from picoseq.core.composer import _step_away
        from picoseq.core.music import chord_at
        chord = chord_at(0, "major", 0, 4)
        notes = [60, 62, 64, 65, 67, 69, 71]
        for index in range(len(notes)):
            with self.subTest(index=index):
                self.assertNotEqual(_step_away(notes, index, chord), index)

    def test_step_away_has_no_escape_from_a_single_note(self):
        from picoseq.core.composer import _step_away
        from picoseq.core.music import chord_at
        self.assertEqual(_step_away([60], 0, chord_at(0, "major", 0, 4)), 0)

    def test_minimum_note_count(self):
        """疎なリズム型・間を活かす音階でも「メロディの無いフレーズ」を作らない。"""
        for scale_id in SCALE_IDS:
            for seed in range(1, 13):
                with self.subTest(scale=scale_id, seed=seed):
                    self.assertGreaterEqual(len(self._melody(scale_id=scale_id,
                                                             seed=seed)), 4)

    def test_minimum_note_count_in_odd_meters(self):
        for beats in range(2, 8):
            for seed in (1, 4, 77):
                with self.subTest(beats=beats, seed=seed):
                    melody = self._melody(beats=beats, scale_id="japanese",
                                          seed=seed)
                    self.assertGreaterEqual(len(melody), 4)

    def test_onsets_are_filled_up_to_the_minimum(self):
        """発音位置そのものが最低数を満たす (どのリズム型でも)。"""
        from picoseq.core.composer import (
            MELODY_MIN_ONSETS, MELODY_RHYTHMS, _melody_onsets,
        )
        from picoseq.core.prng import Rng
        for rhythm in range(MELODY_RHYTHMS):
            for seed in range(1, 26):
                onsets = _melody_onsets(Rng(seed), 16, rhythm, "japanese")
                with self.subTest(rhythm=rhythm, seed=seed):
                    self.assertGreaterEqual(len(onsets), MELODY_MIN_ONSETS)
                    self.assertEqual(sorted(set(onsets)), list(onsets))

    def test_onset_filling_does_not_touch_the_bar_end(self):
        """補うときも小節末は空けたまま (息継ぎを潰さない)。"""
        from picoseq.core.composer import _melody_onsets
        from picoseq.core.prng import Rng
        for seed in range(1, 40):
            for rhythm in (2, 7):  # 引き延ばし・語り (最も疎な型)
                self.assertNotIn(15, _melody_onsets(Rng(seed), 16, rhythm,
                                                    "japanese"))

    def _chord_tone_rates(self):
        """(拍頭のコードトーン率, 裏拍のコードトーン率)。"""
        counts = {True: [0, 0], False: [0, 0]}  # 拍頭か -> [コードトーン, 総数]
        for scale_id in ("major", "minor", "dorian", "lydian"):
            for seed in range(1, 26):
                chord_of = self._chords_of(scale_id, seed)
                for note in self._melody(scale_id=scale_id, seed=seed):
                    chord = chord_of(note.step)
                    slot = counts[note.step % 4 == 0]
                    slot[0] += note.pitch % 12 in (chord.root % 12,
                                                   chord.third % 12,
                                                   chord.fifth % 12)
                    slot[1] += 1
        return (counts[True][0] / counts[True][1],
                counts[False][0] / counts[False][1])

    def test_beat_heads_stay_chord_tones(self):
        """経過音を許しても拍頭はコードトーンのまま (和音が濁らない)。"""
        head, _ = self._chord_tone_rates()
        self.assertGreater(head, 0.97)

    def test_off_beats_use_passing_tones(self):
        """裏拍では非コードトーンも通る (全部コードトーンだと歌の輪郭が出ない)。"""
        _, off = self._chord_tone_rates()
        passing = 1 - off
        self.assertGreater(passing, 0.1, "裏拍が安全すぎる")
        self.assertLess(passing, 0.5, "裏拍が濁りすぎ")

    def test_passing_tones_stay_in_scale(self):
        """経過音も音階内 (半音のぶつかりは作らない)。"""
        for scale_id in SCALE_IDS[:20]:
            for seed in (3, 21, 99):
                with self.subTest(scale=scale_id, seed=seed):
                    for note in self._melody(scale_id=scale_id, seed=seed):
                        self.assertTrue(in_scale(note.pitch, 0, scale_id))

    def test_leaps_stay_rare(self):
        """大跳躍 (7半音超) は少数のまま — 動かす修正で暴れていないこと。"""
        leaps = steps = 0
        for scale_id in ("major", "minor", "japanese", "battle"):
            for seed in range(1, 26):
                melody = self._melody(scale_id=scale_id, seed=seed)
                for a, b in zip(melody, melody[1:]):
                    steps += 1
                    leaps += abs(a.pitch - b.pitch) > 7
        self.assertLess(leaps / steps, 0.15)

    def test_melody_quality_is_deterministic(self):
        """歌わせ方の制約を足しても「同じシード → 同じ曲」は保たれる。"""
        for scale_id in ("major", "japanese", "wholetone"):
            with self.subTest(scale=scale_id):
                self.assertEqual(compose(4, 0, scale_id, 7),
                                 compose(4, 0, scale_id, 7))


class TestMoodStyleAffinity(unittest.TestCase):
    """曲調ごとの得意なリズム/ベース — 性格を出しつつ多様性は殺さない。"""

    def _picks(self, scale_id, count_key="drums", trials=300):
        from collections import Counter

        from picoseq.core.composer import (
            BASS_STYLES, DRUM_STYLES, _style_prefs, _weighted_pick,
        )
        from picoseq.core.prng import Rng
        prefs = _style_prefs(scale_id)
        count = DRUM_STYLES if count_key == "drums" else BASS_STYLES
        picks = Counter()
        for seed in range(1, trials + 1):
            picks[_weighted_pick(Rng(seed), count, prefs[count_key])] += 1
        return picks, prefs[count_key], count

    def test_every_scale_has_preferences(self):
        """65 曲調すべて、4 パート分の得意な型が割り当たっている。"""
        from picoseq.core.composer import _style_prefs
        from picoseq.core.music import SCALE_IDS
        for sid in SCALE_IDS:
            prefs = _style_prefs(sid)
            for part in ("drums", "bass", "backing", "melody"):
                with self.subTest(scale=sid, part=part):
                    self.assertTrue(prefs[part], f"{sid} の {part} に得意型が無い")

    def test_melody_and_backing_also_follow_the_mood(self):
        """リズム/ベースだけでなく、メロディと伴奏も曲調に寄る。"""
        from picoseq.core.composer import (
            BACKING_STYLES, MELODY_RHYTHMS, _style_prefs, _weighted_pick,
        )
        from picoseq.core.prng import Rng
        for sid in ("major", "japanese", "battle"):
            prefs = _style_prefs(sid)
            for part, count in (("melody", MELODY_RHYTHMS),
                                ("backing", BACKING_STYLES)):
                picked = [_weighted_pick(Rng(s), count, prefs[part])
                          for s in range(1, 501)]
                share = sum(1 for p in picked if p in prefs[part]) / len(picked)
                uniform = len(prefs[part]) / count
                with self.subTest(scale=sid, part=part):
                    self.assertGreater(share, uniform * 1.4,
                                       f"{sid} の {part} が曲調に寄っていない")

    def test_preferred_styles_appear_more_often(self):
        """得意な型は明らかに出やすい (曲調の性格が出る)。"""
        for sid in ("major", "minor", "japanese", "battle", "wholetone"):
            picks, preferred, count = self._picks(sid)
            total = sum(picks.values())
            share = sum(picks[i] for i in preferred) / total
            uniform = len(preferred) / count      # 重み無しならこの割合
            with self.subTest(scale=sid):
                self.assertGreater(share, uniform * 1.5,
                                   f"{sid} で得意型が優遇されていない")

    def test_all_styles_remain_reachable(self):
        """禁止はしない — どの曲調でも全部の型が出る余地がある。

        型が 200 種規模なので、全部を引くにはシードを多めに回す必要がある。
        """
        for sid in ("major", "japanese", "battle", "persian"):
            picks, _, count = self._picks(sid, trials=8000)
            with self.subTest(scale=sid):
                self.assertEqual(len(picks), count,
                                 f"{sid} で出ない型がある (多様性が失われた)")

    def test_bass_preferences_also_applied(self):
        picks, preferred, count = self._picks("battle", count_key="bass")
        share = sum(picks[i] for i in preferred) / sum(picks.values())
        self.assertGreater(share, len(preferred) / count * 1.5)

    def test_weighted_pick_consumes_one_random_value(self):
        """乱数の消費数が一定 (再現性のため)。"""
        from picoseq.core.composer import _weighted_pick
        from picoseq.core.prng import Rng
        a, b = Rng(9), Rng(9)
        _weighted_pick(a, 21, (0, 3, 5))
        b.next_int(21 + 3 * 3)
        self.assertEqual(a.next_int(1000), b.next_int(1000))

    def test_weighted_pick_stays_in_range(self):
        from picoseq.core.composer import _weighted_pick
        from picoseq.core.prng import Rng
        for seed in range(1, 200):
            for preferred in ((), (0,), (5, 9), (0, 20), (99,)):
                got = _weighted_pick(Rng(seed), 21, preferred)
                self.assertTrue(0 <= got < 21)

    def test_mood_affinity_is_deterministic(self):
        """曲調連動でも「同じシード→同じ曲」は保たれる。"""
        for sid in ("major", "japanese", "battle"):
            with self.subTest(scale=sid):
                self.assertEqual(compose(4, 0, sid, 42), compose(4, 0, sid, 42))

    def test_moods_differ_from_each_other(self):
        """同じシードでも曲調が違えばリズムの選ばれ方が変わる。"""
        picks_a, _, _ = self._picks("battle")
        picks_b, _, _ = self._picks("minor")
        self.assertNotEqual(picks_a.most_common(3), picks_b.most_common(3))


if __name__ == "__main__":
    unittest.main()
