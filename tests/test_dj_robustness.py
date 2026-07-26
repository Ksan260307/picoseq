"""DJ の履歴・お気に入りの堅牢性 — 壊れた設定ファイルでも落ちない。

エントリは設定ファイルに JSON で残り手編集され得る。sanitize_entries は
どんな入力でも「必ず 4 個・整数のリスト、有効範囲」に丸める。entry_id は
同一性の判定に使うので、丸めた後も安定していなければならない。
"""

import json
import random
import unittest

from picoseq.core import dj


def _entry(seed=1, **over):
    base = dict(scale="major", key=0, bpm=120, sound="retro8", noise=0, seed=seed,
                deck=0)
    base.update(over)
    return dj.make_entry(**base)


class TestSanitizeNeverCrashes(unittest.TestCase):
    """あらゆる壊れた入力でも例外を出さず、使える形だけ返す。"""

    GARBAGE = [
        None, "x", 42, {"seed": 1}, [1, 2, 3], [None, "x", 42],
        [{"tones": "bad"}], [{"gates": {}}], [{"volumes": 5}],
        [{"tones": [1, 2, 3, 4, 5, 6]}],      # 多すぎ
        [{"tones": [1]}],                      # 少なすぎ
        [{"scale": None, "key": "x", "bpm": [1], "seed": {}}],
        [{"deck": 999}], [{"deck": -5}],
        [{}] * 100,                            # 上限超え
    ]

    def test_all_garbage_returns_list(self):
        for raw in self.GARBAGE:
            with self.subTest(raw=raw):
                out = dj.sanitize_entries(raw)
                self.assertIsInstance(out, list)
                self.assertLessEqual(len(out), dj.FAVORITES_MAX)

    def test_sanitized_entries_are_well_formed(self):
        messy = [{"tones": [999, -5], "gates": "x", "volumes": [50], "seed": "9"},
                 {"scale": 5, "key": 99}, {}]
        for e in dj.sanitize_entries(messy):
            for field in ("tones", "gates", "volumes"):
                self.assertEqual(len(e[field]), 4)
                self.assertTrue(all(isinstance(v, int) for v in e[field]))
            self.assertIn(e["deck"], (0, 1))
            self.assertIsInstance(e["scale"], str)


class TestEntryIdStability(unittest.TestCase):
    def test_sanitize_is_idempotent(self):
        raw = [{"tones": [999], "gates": "x", "seed": "5", "scale": 9}]
        once = dj.sanitize_entries(raw)
        twice = dj.sanitize_entries([dict(once[0])])
        self.assertEqual(dj.entry_id(once[0]), dj.entry_id(twice[0]))

    def test_json_roundtrip_preserves_identity(self):
        for seed in range(1, 21):
            rng = random.Random(seed)
            e = dj.make_entry(
                "battle", rng.randint(0, 11), rng.randint(60, 240), "warm16",
                rng.randint(0, 4), rng.randint(1, 999999),
                tones=[rng.randint(0, 100) for _ in range(4)],
                gates=[rng.randint(10, 100) for _ in range(4)],
                volumes=[rng.randint(0, 100) for _ in range(4)])
            back = dj.sanitize_entries(json.loads(json.dumps([e])))[0]
            self.assertEqual(dj.entry_id(back), dj.entry_id(e))

    def test_deck_not_in_identity(self):
        self.assertEqual(dj.entry_id(_entry(seed=5, deck=0)),
                         dj.entry_id(_entry(seed=5, deck=1)))


class TestHistoryInvariants(unittest.TestCase):
    """push_history はランダム操作でも上限・新しさ・重複除去を保つ。"""


def _history_test(seed):
    def test(self):
        rng = random.Random(seed)
        history = []
        seeds_pushed = []
        for _ in range(60):
            s = rng.randint(1, 6)          # わざと衝突させて重複除去を試す
            history = dj.push_history(history, _entry(seed=s))
            seeds_pushed.append(s)
            self.assertLessEqual(len(history), dj.HISTORY_MAX)
            # 先頭は必ず今入れたもの
            self.assertEqual(history[0]["seed"], s)
            # 同一 id の重複は無い
            ids = [dj.entry_id(e) for e in history]
            self.assertEqual(len(ids), len(set(ids)))
    return test


for _s in range(1, 21):
    setattr(TestHistoryInvariants, f"test_seed_{_s}", _history_test(_s))


class TestFavoritesInvariants(unittest.TestCase):
    def test_toggle_is_involutive(self):
        for seed in range(1, 15):
            e = _entry(seed=seed)
            favs, added = dj.toggle_favorite([], e)
            self.assertTrue(added and dj.is_favorite(favs, e))
            favs2, added2 = dj.toggle_favorite(favs, e)
            self.assertFalse(added2)
            self.assertFalse(dj.is_favorite(favs2, e))

    def test_limit_respected(self):
        favs = []
        for seed in range(50):
            favs, _ = dj.toggle_favorite(favs, _entry(seed=seed))
        self.assertLessEqual(len(favs), dj.FAVORITES_MAX)

    def test_inputs_not_mutated(self):
        original = [_entry(seed=1)]
        dj.toggle_favorite(original, _entry(seed=2))
        dj.push_history(original, _entry(seed=3))
        self.assertEqual(len(original), 1)


class TestNoiseAndFilterRobustness(unittest.TestCase):
    """ノイズ注入・フィルターは極端な引数でも決定論的で範囲内。"""

    def test_add_noise_deterministic_and_bounded(self):
        from picoseq.core.constants import MAX_NOTES
        for level in range(-2, 8):
            a = dj.add_noise([], 4, level, 42)
            b = dj.add_noise([], 4, level, 42)
            self.assertEqual([(n.pitch, n.step, n.wave) for n in a],
                             [(n.pitch, n.step, n.wave) for n in b])
            self.assertLessEqual(len(a), MAX_NOTES)

    def test_lowpass_deterministic_and_length_kept(self):
        from array import array
        pcm = array("h", [((i * 37) % 20000) - 10000 for i in range(2000)]).tobytes()
        for level in (-10, 0, 30, 100, 200):
            a = dj.lowpass_pcm(pcm, level)
            b = dj.lowpass_pcm(pcm, level)
            self.assertEqual(a, b)
            self.assertEqual(len(a), len(pcm))


if __name__ == "__main__":
    unittest.main()
