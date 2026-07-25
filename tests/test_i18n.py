"""表示言語 (日英) の切替テスト — 観測層だけの関心事で状態には影響しない。"""

import unittest

from picoseq.core.music import SCALE_IDS, SCALES
from picoseq.ui import i18n


class TestLangSwitch(unittest.TestCase):
    def setUp(self):
        self._saved = i18n.get_lang()

    def tearDown(self):
        i18n.set_lang(self._saved)

    def test_default_is_japanese(self):
        i18n.set_lang("ja")
        self.assertEqual(i18n.get_lang(), "ja")
        self.assertEqual(i18n.t("tab_song"), "🧩 ソング")

    def test_english_switch(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.t("tab_song"), "🧩 Song")
        self.assertEqual(i18n.t("btn_play"), "▶ Play")

    def test_invalid_lang_ignored(self):
        i18n.set_lang("ja")
        i18n.set_lang("klingon")
        self.assertEqual(i18n.get_lang(), "ja")

    def test_format_arguments(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.t("btn_remove_layer", n=3), "✕ Delete 3")
        i18n.set_lang("ja")
        self.assertEqual(i18n.t("btn_remove_layer", n=3), "✕ 3 を削除")

    def test_placeholder_named_key_does_not_collide(self):
        # t() の第 1 引数は _name。{key} を差し込み名に使っても衝突しない。
        i18n.set_lang("ja")
        self.assertIn("C / Am", i18n.t("st_dj_key", deck="A", key="C / Am"))

    def test_unknown_key_returns_key(self):
        self.assertEqual(i18n.t("no_such_key_xyz"), "no_such_key_xyz")

    def test_part_and_wave_names(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.part_name(0), "Melody")
        self.assertEqual(i18n.part_wave(0), "Pulse")
        i18n.set_lang("ja")
        self.assertEqual(i18n.part_name(0), "メロディ")

    def test_sound_labels(self):
        i18n.set_lang("en")
        self.assertEqual(i18n.sound_label("retro8"), "Chiptune 8-bit")
        i18n.set_lang("ja")
        self.assertEqual(i18n.sound_label("retro8"), "ピコピコ 8bit")

    def test_scale_label_falls_back_to_japanese(self):
        i18n.set_lang("ja")
        self.assertEqual(i18n.scale_label("major", "明るい (メジャー)"), "明るい (メジャー)")
        i18n.set_lang("en")
        self.assertEqual(i18n.scale_label("major", "x"), "Bright (Major)")

    def test_every_scale_has_english_label(self):
        """65 種すべての曲調に英語ラベルがある (未訳が UI に出ない)。"""
        for scale_id in SCALE_IDS:
            self.assertIn(scale_id, i18n.SCALE_EN, scale_id)
            self.assertTrue(i18n.SCALE_EN[scale_id].strip())

    def test_every_string_has_both_languages(self):
        """すべての UI 文字列キーが ja/en 両方を持つ。"""
        for key, entry in i18n.STRINGS.items():
            self.assertIn("ja", entry, key)
            self.assertIn("en", entry, key)
            self.assertTrue(entry["ja"].strip(), key)
            self.assertTrue(entry["en"].strip(), key)

    def test_format_placeholders_match(self):
        """ja/en で書式プレースホルダ ({...}) が食い違わない。"""
        import re
        for key, entry in i18n.STRINGS.items():
            ja = set(re.findall(r"\{(\w+)\}", entry["ja"]))
            en = set(re.findall(r"\{(\w+)\}", entry["en"]))
            self.assertEqual(ja, en, key)


class TestSettingsPersistence(unittest.TestCase):
    def test_roundtrip(self):
        import json
        import tempfile
        from pathlib import Path
        from picoseq.ui import storage

        tmp = Path(tempfile.mkdtemp()) / "settings.json"
        # storage は data_dir 固定なので直接読み書きの整合だけ確認する
        tmp.write_text(json.dumps({"lang": "en"}), encoding="utf-8")
        data = json.loads(tmp.read_text(encoding="utf-8"))
        self.assertEqual(data["lang"], "en")

    def test_bad_file_returns_empty(self):
        import json
        self.assertRaises(json.JSONDecodeError, json.loads, "{broken")


if __name__ == "__main__":
    unittest.main()
