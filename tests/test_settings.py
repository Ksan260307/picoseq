"""アプリ設定 (settings.json) の保存・復元 — 言語・拡大率・ウィンドウ位置など。

storage.data_dir を一時ディレクトリへ差し替えて、実ユーザーの設定に触れずに検証する。
"""

import tempfile
import unittest
from pathlib import Path

from picoseq.ui import storage


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._orig = storage.data_dir
        storage.data_dir = lambda: self.tmp

    def tearDown(self):
        storage.data_dir = self._orig

    def test_roundtrip(self):
        storage.save_settings({"lang": "en", "zoom": 1.5,
                               "window": "800x600+10+20", "phrase_sash": 180})
        s = storage.load_settings()
        self.assertEqual(s["lang"], "en")
        self.assertEqual(s["zoom"], 1.5)
        self.assertEqual(s["window"], "800x600+10+20")
        self.assertEqual(s["phrase_sash"], 180)

    def test_missing_file_returns_empty(self):
        self.assertEqual(storage.load_settings(), {})

    def test_corrupt_file_returns_empty(self):
        storage.settings_path().write_text("{壊れた", encoding="utf-8")
        self.assertEqual(storage.load_settings(), {})

    def test_non_object_returns_empty(self):
        storage.settings_path().write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(storage.load_settings(), {})

    def test_written_without_bom(self):
        """UTF-8 BOM を付けない (BOM 付きは json.loads が拒否し設定が失われる)。"""
        storage.save_settings({"lang": "ja"})
        raw = storage.settings_path().read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))

    def test_partial_update_preserves_other_keys(self):
        storage.save_settings({"lang": "en", "zoom": 2.0})
        s = storage.load_settings()
        s["window"] = "900x700+0+0"
        storage.save_settings(s)
        again = storage.load_settings()
        self.assertEqual(again["lang"], "en")      # 消えない
        self.assertEqual(again["zoom"], 2.0)
        self.assertEqual(again["window"], "900x700+0+0")


if __name__ == "__main__":
    unittest.main()
