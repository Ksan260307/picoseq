"""切り離しパネルのテスト — 切り離しと復帰で並び順が壊れないこと。

selftest では切り離し 1 往復しか通らないので、
「元の位置へ戻るか」「戻した後もパネルの中身が生きているか」をここで押さえる。
"""

import unittest

from tests._ui_util import close_app, make_app, tk_available


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestDockPanel(unittest.TestCase):
    def setUp(self):
        self.app, self.root = make_app()
        self.paned = self.app.phrase_paned
        self.top = self.app.phrase_ctrl_panel     # 操作パネル (上)
        self.bottom = self.app.roll_panel          # ピアノロール (下)

    def tearDown(self):
        close_app(self.app, self.root)

    def _order(self):
        return [str(p) for p in self.paned.panes()]

    def test_panels_are_dock_panels(self):
        from picoseq.ui.panel import DockPanel
        for panel in (self.top, self.bottom):
            self.assertIsInstance(panel, DockPanel)

    def test_pane_names_are_plain_strings(self):
        """`panes()` の Tcl_Obj を文字列へ直して扱う。

        直さずに比べると常に一致せず、戻す位置を取りこぼして
        パネルの順序が入れ替わる (実際にそうなっていた)。
        """
        names = self.top._pane_names()
        self.assertTrue(all(isinstance(n, str) for n in names))
        self.assertIn(str(self.top.container), names)

    def test_starts_docked_in_order(self):
        self.assertEqual(self._order(),
                         [str(self.top.container), str(self.bottom.container)])
        self.assertFalse(self.top.detached)

    def test_detach_removes_from_the_paned(self):
        self.top.detach()
        self.assertTrue(self.top.detached)
        self.assertNotIn(str(self.top.container), self._order())
        self.assertIn(str(self.bottom.container), self._order())

    def test_redock_restores_the_original_order(self):
        """上のパネルを切り離して戻すと、下より前に戻る (入れ替わらない)。"""
        self.top.detach()
        self.top.redock()
        self.assertFalse(self.top.detached)
        self.assertEqual(self._order(),
                         [str(self.top.container), str(self.bottom.container)])

    def test_detach_last_pane_and_redock(self):
        """末尾のパネルは戻す位置の目印が無い — それでも戻せる。"""
        self.bottom.detach()
        self.assertIsNone(self.bottom._after)
        self.bottom.redock()
        self.assertEqual(self._order(),
                         [str(self.top.container), str(self.bottom.container)])

    def test_toggle_switches_both_ways(self):
        self.top.toggle()
        self.assertTrue(self.top.detached)
        self.top.toggle()
        self.assertFalse(self.top.detached)

    def test_redock_twice_is_harmless(self):
        self.top.redock()          # 切り離していない状態で呼んでも何もしない
        self.assertFalse(self.top.detached)
        self.assertEqual(len(self._order()), 2)

    def test_body_survives_the_round_trip(self):
        """切り離しても中身 (ピアノロール) は作り直さない。"""
        canvas = self.app.roll.canvas
        self.bottom.detach()
        self.bottom.redock()
        self.assertIs(self.app.roll.canvas, canvas)
        self.assertTrue(canvas.winfo_exists())

    def test_button_label_follows_the_state(self):
        from picoseq.ui.i18n import t
        self.assertEqual(self.top.toggle_btn.cget("text"), t("panel_detach"))
        self.top.detach()
        self.assertEqual(self.top.toggle_btn.cget("text"), t("panel_redock"))
        self.top.redock()
        self.assertEqual(self.top.toggle_btn.cget("text"), t("panel_detach"))


if __name__ == "__main__":
    unittest.main()
