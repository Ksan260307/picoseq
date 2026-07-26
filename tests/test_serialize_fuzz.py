"""シリアライズの堅牢性 — 壊れた入力でも決して落ちず、必ず有効な Project になる。

保存データは手で編集でき、旧版・別実装が書いた可能性もある。loads は
どんな入力でも「例外を投げるか、正しく丸めた Project を返すか」の二択に収める。
"""

import json
import random
import unittest

from picoseq.core import actions
from picoseq.core.constants import (
    BPM_MAX,
    BPM_MIN,
    PART_COUNT,
    PATTERN_COUNT,
    SONG_BLOCKS,
)
from picoseq.core.project import Project, new_project
from picoseq.core.serialize import LoadError, dumps, loads, to_jsonable


def _valid(project):
    """Project が全フィールド有効範囲に収まっているか。"""
    assert isinstance(project, Project)
    assert BPM_MIN <= project.bpm <= BPM_MAX
    assert 2 <= project.beats <= 7
    assert 0 <= project.key <= 11
    assert len(project.parts) == PART_COUNT
    for layers in project.parts:
        assert 1 <= len(layers) <= 8
        for p in layers:
            assert 0 <= p.tone <= 100
            assert 10 <= p.gate <= 100
            assert 0 <= p.volume <= 100
    assert len(project.patterns) == PATTERN_COUNT
    assert len(project.song) == SONG_BLOCKS * 4
    return True


class TestGarbageNeverCrashes(unittest.TestCase):
    """明らかに不正な入力は LoadError にする (無言で壊れた Project を返さない)。"""

    BAD = [
        "", "not json", "[]", "42", "null", "true", '"string"',
        "{}", '{"app": "other"}', '{"schema": 999}',
        '{"app": "picoseq"}',            # schema 無し
    ]

    def test_bad_inputs_raise_loaderror(self):
        for raw in self.BAD:
            with self.subTest(raw=raw):
                with self.assertRaises((LoadError, Exception)):
                    loads(raw)


class TestFieldFuzzing(unittest.TestCase):
    """1 フィールドずつ異常値を入れても、有効な Project に丸まる。"""

    def _base(self):
        return to_jsonable(new_project())

    def _load(self, **override):
        data = self._base()
        data.update(override)
        return loads(json.dumps(data))

    def test_numeric_fields_clamped(self):
        cases = [
            {"bpm": 10 ** 9}, {"bpm": -(10 ** 9)}, {"bpm": "fast"},
            {"beats": 100}, {"beats": -3}, {"beats": None},
            {"key": 99}, {"key": -1}, {"key": 3.7},
            {"seed": 0}, {"seed": "x"}, {"seed": []},
        ]
        for case in cases:
            with self.subTest(case=case):
                self.assertTrue(_valid(self._load(**case)))

    def test_scale_and_sound_fallback(self):
        for bad in ("polka", "", None, 42, "PHOTO", "major "):
            with self.subTest(bad=bad):
                self.assertTrue(_valid(self._load(scale=bad, sound=bad)))

    def test_parts_shapes(self):
        for parts in (None, "x", [], [[], [], [], []],
                      [{"tone": "a", "gate": None, "volume": [1]}],
                      [[{"tone": 999}] * 20],  # 上限超えレイヤー
                      [{}, {}, {}, {}, {}, {}]):  # パート数超過
            with self.subTest(parts=parts):
                self.assertTrue(_valid(self._load(parts=parts)))

    def test_song_shapes(self):
        for song in (None, "x", [999] * 100, [-5, -5], [[0]], list(range(200))):
            with self.subTest(song=song):
                self.assertTrue(_valid(self._load(song=song)))

    def test_patterns_shapes(self):
        for pats in (None, "x", [], [{"used": "yes"}], [{}] * 50,
                     [{"used": True, "notes": "bad", "name": 123}]):
            with self.subTest(pats=pats):
                self.assertTrue(_valid(self._load(patterns=pats)))

    def test_phrase_shapes(self):
        for phrase in (None, "x", [999999], [-1], [[1, 2]], list(range(100))):
            with self.subTest(phrase=phrase):
                self.assertTrue(_valid(self._load(phrase=phrase)))

    def test_progression_and_custom_scale(self):
        for prog in (None, [], [0, 1, 2, 3], [99] * 4, "x", [0.5]):
            with self.subTest(prog=prog):
                self.assertTrue(_valid(self._load(progression=prog)))
        for cs in (None, [], [0, 2, 4], [999], "x"):
            with self.subTest(cs=cs):
                self.assertTrue(_valid(self._load(custom_scale=cs)))


class TestRandomRoundTrip(unittest.TestCase):
    """ランダムに作った多様なプロジェクトが dumps→loads で完全復元する。"""


def _roundtrip_test(seed):
    def test(self):
        rng = random.Random(seed)
        p = actions.generate_phrase(
            actions.set_seed(new_project(), rng.randint(1, 999999)))
        p = actions.set_bpm(p, rng.randint(BPM_MIN, BPM_MAX))
        p = actions.set_beats(p, rng.randint(2, 7))
        p = actions.set_key(p, rng.randint(0, 11))
        for wave in range(PART_COUNT):
            p = actions.set_part_tone(p, wave, rng.randint(0, 100))
            p = actions.set_part_gate(p, wave, rng.randint(10, 100))
            p = actions.set_part_volume(p, wave, rng.randint(0, 100))
        p = actions.save_pattern(p, rng.randint(0, PATTERN_COUNT - 1))
        restored = loads(dumps(p))
        self.assertEqual(restored, p)
        self.assertTrue(_valid(restored))
    return test


for _s in range(1, 41):
    setattr(TestRandomRoundTrip, f"test_seed_{_s}", _roundtrip_test(_s))


if __name__ == "__main__":
    unittest.main()
