"""デモ用の中身づくり (`--demo`) のテスト。

スクリーンショットと動作確認に使う経路なので、黙って壊れると
「デモが空っぽ」に気づけない。環境変数の分岐も含めて一度通す。
"""

import os
import unittest

from tests._ui_util import close_app, make_app, tk_available


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestLoadDemo(unittest.TestCase):
    def setUp(self):
        self.app, self.root = make_app()
        self._env = {k: v for k, v in os.environ.items() if k.startswith("PICOSEQ_")}
        for key in self._env:
            del os.environ[key]

    def tearDown(self):
        for key in list(os.environ):
            if key.startswith("PICOSEQ_"):
                del os.environ[key]
        os.environ.update(self._env)
        close_app(self.app, self.root)

    def test_fills_patterns_and_song(self):
        from picoseq.core.phrase import count_notes
        from picoseq.core.song import used_blocks
        from picoseq.ui.demo import load_demo
        load_demo(self.app)
        self.assertGreater(count_notes(self.app.project.phrase), 0)
        self.assertTrue(self.app.project.patterns[0].used)
        self.assertTrue(self.app.project.patterns[1].used)
        self.assertGreater(used_blocks(self.app.project.song), 0)

    def test_patterns_get_names(self):
        """マス目の省略表示を確かめるため、長い名前が入っている。"""
        from picoseq.ui.demo import load_demo
        load_demo(self.app)
        names = [p.name for p in self.app.project.patterns[:2]]
        self.assertTrue(all(names))
        self.assertGreater(max(len(n) for n in names), 5)

    def test_history_is_cleared(self):
        """デモの組み立て自体はアンドゥ対象にしない。"""
        from picoseq.ui.demo import load_demo
        load_demo(self.app)
        self.app.undo_action()
        self.assertTrue(self.app.project.patterns[0].used)

    def test_tab_env_opens_that_tab(self):
        from picoseq.ui.demo import load_demo
        for tab in ("song", "pattern", "dj"):
            with self.subTest(tab=tab):
                app, root = make_app()
                os.environ["PICOSEQ_DEMO_TAB"] = tab
                try:
                    load_demo(app)
                    self.assertEqual(app.tab, tab)
                finally:
                    del os.environ["PICOSEQ_DEMO_TAB"]
                    close_app(app, root)

    def test_dj_demo_fills_the_log(self):
        """DJ を開くデモでは履歴とお気に入りに中身が入る。"""
        from picoseq.ui.demo import load_demo
        os.environ["PICOSEQ_DEMO_TAB"] = "dj"
        load_demo(self.app)
        self.assertGreater(len(self.app.dj_history), 0)
        self.assertGreater(len(self.app.dj_favorites), 0)

    def test_sound_env_switches_the_theme(self):
        from picoseq.ui import theme
        from picoseq.ui.demo import load_demo
        os.environ["PICOSEQ_DEMO_SOUND"] = "warm16"
        load_demo(self.app)
        self.assertEqual(self.app.project.sound, "warm16")
        self.assertEqual(theme.BG, theme.PALETTES["warm16"]["BG"])

    def test_unknown_env_value_is_ignored(self):
        from picoseq.ui.demo import load_demo
        os.environ["PICOSEQ_DEMO_TAB"] = "no-such-tab"
        os.environ["PICOSEQ_DEMO_SOUND"] = "no-such-sound"
        load_demo(self.app)
        self.assertEqual(self.app.tab, "phrase")


if __name__ == "__main__":
    unittest.main()
