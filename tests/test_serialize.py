"""保存形式のテスト — 往復・版検査・値の浄化・旧版移行。"""

import json
import unittest

from picoseq.core import actions
from picoseq.core.constants import APP_ID, EMPTY_CELL, SCHEMA_VERSION
from picoseq.core.note import pack_note
from picoseq.core.phrase import active_notes, count_notes
from picoseq.core.project import new_project
from picoseq.core.serialize import LoadError, dumps, loads, to_jsonable


def _rich_project():
    p = new_project()
    p = actions.set_bpm(p, 150)
    p = actions.set_beats(p, 3)
    p = actions.set_key(p, 7)
    p = actions.set_scale(p, "battle")
    p = actions.set_seed(p, 4649)
    p = actions.set_part_tone(p, 0, 30)
    p = actions.set_part_gate(p, 3, 55)
    p, _ = actions.place_note(p, 60, 0, 0, dur=2)
    p, _ = actions.place_note(p, 48, 4, 1)
    p = actions.save_pattern(p, 0)
    p = actions.rename_pattern(p, 0, "メインリフ")
    p = actions.save_pattern(p, 5)
    p = actions.toggle_song_cell(p, 0, 0, 0)
    p = actions.toggle_song_cell(p, 2, 7, 5)
    return p


class TestRoundtrip(unittest.TestCase):
    def test_full_roundtrip(self):
        p = _rich_project()
        self.assertEqual(loads(dumps(p)), p)

    def test_default_roundtrip(self):
        p = new_project()
        self.assertEqual(loads(dumps(p)), p)

    def test_replay_identity_fields(self):
        """保存データは必ずアプリ ID と形式バージョンを持つ。"""
        data = to_jsonable(new_project())
        self.assertEqual(data["app"], APP_ID)
        self.assertEqual(data["schema"], SCHEMA_VERSION)


class TestPatternName(unittest.TestCase):
    """schema v6 で追加されたパターン名の入出力。"""

    def test_name_roundtrip(self):
        p = actions.rename_pattern(actions.save_pattern(new_project(), 0), 0, "サビ")
        self.assertEqual(loads(dumps(p)).patterns[0].name, "サビ")

    def test_schema5_data_loads_without_name(self):
        """v5 のデータ (name 無し) も読めて空文字になる (後方互換)。"""
        p = actions.save_pattern(new_project(), 0)
        data = to_jsonable(p)
        data["schema"] = 5
        for entry in data["patterns"]:
            entry.pop("name", None)
        restored = loads(json.dumps(data))
        self.assertTrue(restored.patterns[0].used)
        self.assertEqual(restored.patterns[0].name, "")

    def test_non_string_name_becomes_empty(self):
        p = actions.save_pattern(new_project(), 0)
        data = to_jsonable(p)
        data["patterns"][0]["name"] = 12345
        self.assertEqual(loads(json.dumps(data)).patterns[0].name, "")

    def test_name_length_clamped_on_load(self):
        from picoseq.core.constants import PATTERN_NAME_MAX
        p = actions.save_pattern(new_project(), 0)
        data = to_jsonable(p)
        data["patterns"][0]["name"] = "x" * 100
        self.assertEqual(len(loads(json.dumps(data)).patterns[0].name),
                         PATTERN_NAME_MAX)


class TestProgressionField(unittest.TestCase):
    """schema v2 で追加されたカスタム進行の入出力。"""

    def test_roundtrip(self):
        p = actions.set_progression(new_project(), (0, 5, 2, 6))
        self.assertEqual(loads(dumps(p)).progression, (0, 5, 2, 6))

    def test_none_roundtrip(self):
        self.assertIsNone(loads(dumps(new_project())).progression)

    def test_schema1_data_loads_without_progression(self):
        """v1 のデータ (progression 無し) も読めて None になる (後方互換)。"""
        data = to_jsonable(new_project())
        data["schema"] = 1
        del data["progression"]
        p = loads(json.dumps(data))
        self.assertIsNone(p.progression)

    def test_invalid_progression_falls_back(self):
        base = to_jsonable(new_project())
        for bad in ([0, 99], [], [0] * 99, ["x", 1], [True, 2], "0,1,2", 5):
            with self.subTest(bad=bad):
                data = dict(base)
                data["progression"] = bad
                self.assertIsNone(loads(json.dumps(data)).progression)

    def test_progression_validated_against_scale(self):
        """スケールに存在しない度数を含む進行は捨てる (陰音階は 5 音)。"""
        p = actions.set_progression(new_project(), (0, 5, 2, 6))  # minor で有効
        data = to_jsonable(p)
        data["scale"] = "japanese"  # 5 音 → 度数 5, 6 が範囲外になる
        self.assertIsNone(loads(json.dumps(data)).progression)


class TestCustomScaleField(unittest.TestCase):
    """schema v3 で追加されたフォト音階の入出力。"""

    def _photo_project(self):
        return actions.set_custom_scale(new_project(), key=5,
                                        intervals=(0, 3, 5, 8, 10),
                                        bpm=140, seed=99)

    def test_roundtrip(self):
        p = self._photo_project()
        restored = loads(dumps(p))
        self.assertEqual(restored.custom_scale, (0, 3, 5, 8, 10))
        self.assertEqual(restored.scale, "photo")
        self.assertEqual(restored, p)

    def test_schema2_data_loads_without_custom_scale(self):
        """v2 のデータ (custom_scale 無し) も読める (後方互換)。"""
        data = to_jsonable(new_project())
        data["schema"] = 2
        del data["custom_scale"]
        p = loads(json.dumps(data))
        self.assertIsNone(p.custom_scale)

    def test_photo_scale_without_intervals_falls_back(self):
        """scale="photo" なのに音程列が壊れていたら既定の曲調へ。"""
        data = to_jsonable(self._photo_project())
        data["custom_scale"] = None
        p = loads(json.dumps(data))
        self.assertEqual(p.scale, "major")

    def test_invalid_custom_scale_dropped(self):
        base = to_jsonable(self._photo_project())
        for bad in ([0, 1], [1, 5, 9], [0, "x", 5], [0, 3, 99], "035", [True, 0, 3]):
            with self.subTest(bad=bad):
                data = dict(base)
                data["custom_scale"] = bad
                p = loads(json.dumps(data))
                self.assertIsNone(p.custom_scale)
                self.assertEqual(p.scale, "major")

    def test_progression_validated_against_custom_scale(self):
        p = self._photo_project()  # 5 音
        p = actions.set_progression(p, (0, 4, 2, 1))
        restored = loads(dumps(p))
        self.assertEqual(restored.progression, (0, 4, 2, 1))
        # 音階を縮めると範囲外の度数は捨てられる
        data = to_jsonable(p)
        data["custom_scale"] = [0, 4, 7]
        self.assertIsNone(loads(json.dumps(data)).progression)


class TestRejection(unittest.TestCase):
    def test_rejects_other_app(self):
        data = to_jsonable(new_project())
        data["app"] = "otherseq"
        with self.assertRaises(LoadError):
            loads(json.dumps(data))

    def test_rejects_future_schema(self):
        data = to_jsonable(new_project())
        data["schema"] = SCHEMA_VERSION + 1
        with self.assertRaises(LoadError):
            loads(json.dumps(data))

    def test_rejects_missing_schema(self):
        data = to_jsonable(new_project())
        del data["schema"]
        with self.assertRaises(LoadError):
            loads(json.dumps(data))

    def test_rejects_broken_json(self):
        with self.assertRaises(LoadError):
            loads("{こわれたデータ")

    def test_rejects_non_object(self):
        with self.assertRaises(LoadError):
            loads("[1, 2, 3]")


class TestSanitize(unittest.TestCase):
    def _load_with(self, **overrides):
        data = to_jsonable(new_project())
        data.update(overrides)
        return loads(json.dumps(data))

    def test_clamps_numbers(self):
        p = self._load_with(bpm=9999, key=-5, seed=0, beats=100)
        self.assertEqual(p.bpm, 240)
        self.assertEqual(p.key, 0)
        self.assertEqual(p.seed, 1)
        self.assertEqual(p.beats, 7)

    def test_unknown_scale_falls_back(self):
        self.assertEqual(self._load_with(scale="polka").scale, "major")

    def test_invalid_notes_dropped(self):
        p = self._load_with(phrase=[
            [60, 0, 0, 2],      # 正常
            [200, 0, 0, 1],     # 音域外
            [60, 100, 0, 1],    # ステップ外
            [60, 0, 7, 1],      # パート外
            [60, 0, 0, 999],    # 長すぎ → 255 に収める
            "garbage",          # 型違い
            [60, 0],            # 要素不足
        ])
        notes = [n for _, n in active_notes(p.phrase)]
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].dur, 2)
        self.assertEqual(notes[1].dur, 255)

    def test_invalid_song_cells_emptied(self):
        p = self._load_with(song=[8, -2, 3, "x"] + [-1] * 60)
        self.assertEqual(p.song[0], EMPTY_CELL)
        self.assertEqual(p.song[1], EMPTY_CELL)
        self.assertEqual(p.song[2], 3)
        self.assertEqual(p.song[3], EMPTY_CELL)

    def test_short_lists_padded(self):
        p = self._load_with(song=[0], parts=[{"tone": 10, "gate": 20}], patterns=[])
        self.assertEqual(len(p.song), 64)
        self.assertEqual(len(p.parts), 4)
        self.assertEqual(p.parts[0][0].tone, 10)
        self.assertEqual(p.parts[1][0].tone, 50)  # 既定値
        self.assertEqual(len(p.patterns), 8)


class TestLegacyImport(unittest.TestCase):
    """旧版 (main.html) の retro_project.json を移行できる。"""

    def _legacy_data(self):
        buffer = [0] * 1024
        buffer[0] = pack_note(60, 0, 0, 2)
        buffer[1] = pack_note(48, 4, 1, 0)   # 旧データは dur=0 がありうる
        buffer[2] = pack_note(60, 1, 0, 1, active=False)  # 無効スロット
        favorites = [[0] * 1024 for _ in range(8)]
        favorites[2][0] = pack_note(72, 8, 3, 4)
        return {
            "beats": 5,
            "currentBuffer": buffer,
            "favorites": favorites,
            "isUsed": [False, False, True, False, False, False, False, False],
            "songGrid": [2] * 3 + [255] * 61,
            "partSettings": {
                "0": {"tone": 0.25, "length": 0.9},
                "1": {"tone": 0.5, "length": 0.8},
                "2": {"tone": 0.75, "length": 0.5},
                "3": {"tone": 1.0, "length": 0.3},
            },
        }

    def test_full_migration(self):
        p = loads(json.dumps(self._legacy_data()))
        self.assertEqual(p.beats, 5)
        notes = [n for _, n in active_notes(p.phrase)]
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0].dur, 2)
        self.assertEqual(notes[1].dur, 1)  # dur=0 → 1
        self.assertTrue(p.patterns[2].used)
        self.assertFalse(p.patterns[0].used)
        self.assertEqual(count_notes(p.patterns[2].notes), 1)
        self.assertEqual(p.song[0], 2)
        self.assertEqual(p.song[3], EMPTY_CELL)
        self.assertEqual(p.parts[0][0].tone, 25)
        self.assertEqual(p.parts[0][0].gate, 90)
        self.assertEqual(p.parts[3][0].gate, 30)
        # 旧形式に無い値は既定
        self.assertEqual(p.bpm, 120)
        self.assertEqual(p.scale, "major")

    def test_migrated_project_roundtrips_as_new_format(self):
        p = loads(json.dumps(self._legacy_data()))
        self.assertEqual(loads(dumps(p)), p)

    def test_partial_legacy_data(self):
        p = loads(json.dumps({"currentBuffer": [pack_note(60, 0, 0, 1)]}))
        self.assertEqual(count_notes(p.phrase), 1)
        self.assertEqual(p.beats, 4)


if __name__ == "__main__":
    unittest.main()
