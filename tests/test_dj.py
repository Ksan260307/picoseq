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

    def test_never_doubles_an_existing_hit(self):
        """既に打っているステップへは重ねない。

        ノイズは合成時に音程を無視するので、同じステップに 2 音あると
        まったく同じ波形が 2 回鳴るだけ (実測でレベル 1 の 75% が無駄打ちだった)。
        """
        for level in range(1, dj.NOISE_MAX_LEVEL + 1):
            for seed in (1, 42, 999):
                base = [Note(dj.NOISE_PITCH, s, WAVE_NOISE, 1)
                        for s in range(0, 32, 4)]
                out = _noise_notes(dj.add_noise(base, 4, level, seed))
                steps = [n.step for n in out]
                with self.subTest(level=level, seed=seed):
                    self.assertEqual(len(steps), len(set(steps)))

    def test_shifted_hits_stay_in_the_grid(self):
        base = [Note(dj.NOISE_PITCH, s, WAVE_NOISE, 1) for s in range(32)]
        out = _noise_notes(dj.add_noise(base, 4, 4, 7))
        self.assertEqual(len(out), 32)      # 全部埋まっていれば足せない
        for note in out:
            self.assertTrue(0 <= note.step < 32)

    def test_added_hits_are_softer_than_the_core(self):
        """刻みは芯より一段弱く、ロールだけは煽りとして強い。"""
        out = dj.add_noise([], 4, 4, 11)
        softs = {n.soft for n in _noise_notes(out)}
        self.assertIn(dj.NOISE_SOFT, softs)
        self.assertIn(dj.NOISE_ROLL_SOFT, softs)
        self.assertLess(dj.NOISE_ROLL_SOFT, dj.NOISE_SOFT)


class TestFlowSeed(unittest.TestCase):
    """連続フローのシード選び — 疎なフレーズの直後に密なフレーズを置かない。"""

    def test_picks_the_closest_density(self):
        counts = {1: 10, 2: 50, 3: 30}
        self.assertEqual(dj.pick_flow_seed([2, 3, 1], counts.get, 12), 1)

    def test_returns_the_first_within_tolerance(self):
        counts = {1: 40, 2: 45, 3: 44}
        # 45 は許容差 (12) の内側なので、そこで打ち切って候補順の先頭を採る
        self.assertEqual(dj.pick_flow_seed([2, 3, 1], counts.get, 44), 2)

    def test_first_phrase_takes_the_first_candidate(self):
        self.assertEqual(dj.pick_flow_seed([7, 8], lambda s: 0, None), 7)

    def test_is_deterministic(self):
        counts = {1: 10, 2: 50, 3: 30}
        for _ in range(5):
            self.assertEqual(dj.pick_flow_seed([1, 2, 3], counts.get, 28), 3)

    def test_empty_candidates_raise(self):
        with self.assertRaises(ValueError):
            dj.pick_flow_seed([], lambda s: 0, 10)


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


def _entry(seed=1, **over):
    base = dict(scale="major", key=0, bpm=120, sound="retro8", noise=0, seed=seed,
                deck=0)
    base.update(over)
    return dj.make_entry(**base)


class EntryTest(unittest.TestCase):
    def test_entry_id_ignores_deck(self):
        """同じフレーズなら、どちらのデッキで流しても同じもの。"""
        self.assertEqual(dj.entry_id(_entry(seed=7, deck=0)),
                         dj.entry_id(_entry(seed=7, deck=1)))

    def test_entry_id_distinguishes_every_field(self):
        base = _entry(seed=7)
        for field, value in (("scale", "battle"), ("key", 3), ("bpm", 90),
                             ("sound", "warm16"), ("noise", 2),
                             ("tones", (1, 2, 3, 4)), ("gates", (11, 22, 33, 44)),
                             ("volumes", (9, 8, 7, 6)), ("seed", 8)):
            with self.subTest(field=field):
                other = _entry(seed=8) if field == "seed" else _entry(seed=7, **{field: value})
                self.assertNotEqual(dj.entry_id(base), dj.entry_id(other))

    def test_make_entry_coerces_types(self):
        entry = dj.make_entry("major", "5", "120", "retro8", "2", "9",
                              tones=["1", "2", "3", "4"], deck="1")
        self.assertEqual((entry["key"], entry["bpm"], entry["noise"], entry["seed"]),
                         (5, 120, 2, 9))
        self.assertEqual(entry["tones"], (1, 2, 3, 4))
        self.assertEqual(entry["gates"], (80, 80, 80, 80))   # 既定
        self.assertEqual(entry["deck"], 1)

    def test_tones_and_gates_are_per_part(self):
        entry = _entry(tones=(10, 20, 30, 40), gates=(15, 25, 35, 45))
        self.assertEqual(entry["tones"], (10, 20, 30, 40))
        self.assertEqual(entry["gates"], (15, 25, 35, 45))


class HistoryTest(unittest.TestCase):
    def test_newest_first(self):
        history = dj.push_history(dj.push_history([], _entry(seed=1)), _entry(seed=2))
        self.assertEqual([e["seed"] for e in history], [2, 1])

    def test_same_phrase_moves_to_top_without_growing(self):
        history = []
        for seed in (1, 2, 3):
            history = dj.push_history(history, _entry(seed=seed))
        history = dj.push_history(history, _entry(seed=1))
        self.assertEqual([e["seed"] for e in history], [1, 3, 2])

    def test_limit(self):
        history = []
        for seed in range(30):
            history = dj.push_history(history, _entry(seed=seed), limit=5)
        self.assertEqual(len(history), 5)
        self.assertEqual(history[0]["seed"], 29)

    def test_push_does_not_mutate_input(self):
        original = [_entry(seed=1)]
        dj.push_history(original, _entry(seed=2))
        self.assertEqual(len(original), 1)

    def test_param_change_same_seed_is_a_distinct_row(self):
        """つまみを触ると (シードは同じでも) 別のエントリとして履歴に残る。"""
        history = dj.push_history([], _entry(seed=5, noise=0))
        history = dj.push_history(history, _entry(seed=5, noise=3))
        self.assertEqual(len(history), 2)                     # 調整前も残る
        self.assertEqual(history[0]["noise"], 3)
        self.assertTrue(any(e["noise"] == 0 for e in history))


class FavoritesTest(unittest.TestCase):
    def test_toggle_adds_then_removes(self):
        favorites, added = dj.toggle_favorite([], _entry(seed=1))
        self.assertTrue(added)
        self.assertTrue(dj.is_favorite(favorites, _entry(seed=1)))
        favorites, added = dj.toggle_favorite(favorites, _entry(seed=1))
        self.assertFalse(added)
        self.assertEqual(favorites, [])

    def test_toggle_matches_by_content_not_deck(self):
        """デッキ B で登録したものは、デッキ A から見ても同じ ★。"""
        favorites, _ = dj.toggle_favorite([], _entry(seed=1, deck=1))
        self.assertTrue(dj.is_favorite(favorites, _entry(seed=1, deck=0)))

    def test_limit_pushes_out_the_oldest(self):
        favorites = []
        for seed in range(10):
            favorites, _ = dj.toggle_favorite(favorites, _entry(seed=seed), limit=3)
        self.assertEqual([e["seed"] for e in favorites], [9, 8, 7])

    def test_does_not_mutate_input(self):
        original = [_entry(seed=1)]
        dj.toggle_favorite(original, _entry(seed=2))
        self.assertEqual(len(original), 1)


class SanitizeTest(unittest.TestCase):
    def test_fills_missing_fields(self):
        [entry] = dj.sanitize_entries([{"seed": 5}])
        self.assertEqual(entry["seed"], 5)
        self.assertEqual(entry["scale"], "major")
        self.assertEqual((entry["key"], entry["bpm"], entry["noise"]), (0, 120, 0))

    def test_drops_non_dict_rows(self):
        self.assertEqual(dj.sanitize_entries(["x", 3, None, {"seed": 1}]),
                         dj.sanitize_entries([{"seed": 1}]))

    def test_bad_types_fall_back_to_defaults(self):
        [entry] = dj.sanitize_entries([{"seed": "nope", "bpm": [1], "key": None}])
        self.assertEqual((entry["seed"], entry["bpm"], entry["key"]), (1, 120, 0))

    def test_tones_gates_default_when_missing(self):
        [entry] = dj.sanitize_entries([{"seed": 1}])
        self.assertEqual(entry["tones"], (50, 50, 50, 50))
        self.assertEqual(entry["gates"], (80, 80, 80, 80))

    def test_tones_padded_and_coerced(self):
        [entry] = dj.sanitize_entries([{"tones": ["7", "8"], "gates": "bad"}])
        self.assertEqual(entry["tones"], (7, 8, 50, 50))     # 足りない分は既定で補う
        self.assertEqual(entry["gates"], (80, 80, 80, 80))   # 壊れていれば既定

    def test_old_favorite_without_tones_still_loads(self):
        """tones/gates が無い旧い設定ファイルも既定で補って読める (後方互換)。"""
        old = {"scale": "battle", "key": 7, "bpm": 150, "sound": "retro8",
               "noise": 2, "seed": 99}                       # tone/tones 無し
        [entry] = dj.sanitize_entries([old])
        self.assertEqual(entry["tones"], (50, 50, 50, 50))
        self.assertEqual(entry["seed"], 99)

    def test_deck_is_clamped(self):
        [a], [b] = (dj.sanitize_entries([{"deck": 99}]), dj.sanitize_entries([{"deck": -5}]))
        self.assertEqual((a["deck"], b["deck"]), (1, 0))

    def test_not_a_list(self):
        self.assertEqual(dj.sanitize_entries({"seed": 1}), [])
        self.assertEqual(dj.sanitize_entries(None), [])

    def test_limit(self):
        self.assertEqual(len(dj.sanitize_entries([{"seed": i} for i in range(50)],
                                                 limit=4)), 4)

    def test_round_trips_through_json(self):
        """設定ファイルへ書いて読み直しても同じ (JSON で表せる形になっている)。"""
        import json
        entries = [_entry(seed=3, scale="battle", key=7)]
        restored = dj.sanitize_entries(json.loads(json.dumps(entries)))
        self.assertEqual(dj.entry_id(restored[0]), dj.entry_id(entries[0]))


if __name__ == "__main__":
    unittest.main()
