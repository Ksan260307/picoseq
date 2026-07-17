"""UI 層のテスト — モジュール読み込みと自己診断 (画面は出さない)。"""

import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class TestUiModules(unittest.TestCase):
    def test_modules_import(self):
        """UI モジュールが読み込めること (文法・依存の検査)。"""
        import picoseq.ui.app        # noqa: F401
        import picoseq.ui.help       # noqa: F401
        import picoseq.ui.photo      # noqa: F401
        import picoseq.ui.playback   # noqa: F401
        import picoseq.ui.roll_view  # noqa: F401
        import picoseq.ui.song_view  # noqa: F401
        import picoseq.ui.storage    # noqa: F401
        import picoseq.ui.theme      # noqa: F401

    def test_theme_dim(self):
        from picoseq.ui.theme import dim
        self.assertEqual(dim("#ffffff", 50), "#7f7f7f")
        self.assertEqual(dim("#000000", 50), "#000000")


class TestUiSelftest(unittest.TestCase):
    def test_selftest_passes(self):
        """アプリの配線一巡 (--selftest) が通ること。"""
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), "--selftest"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SELFTEST OK", result.stdout)


if __name__ == "__main__":
    unittest.main()
