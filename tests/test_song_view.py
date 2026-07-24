"""ソングビューの表示ロジック — セル名のピクセル単位の省略 (長い名前を「…」に)。

実フォント計測が要るので Tk のルートを作る。表示環境が無ければ skip。
"""

import unittest
import tkinter as tk


class _FakeApp:
    def __init__(self, root):
        from picoseq.core.project import new_project
        self.root = root
        self.project = new_project()
        self.selected_pattern = -1

    def pattern_label(self, slot):
        return f"F{slot + 1}"

    def song_click(self, *a):
        pass

    def song_erase(self, *a):
        pass

    def show_song_hint(self, *a):
        pass

    def clear_song_hint(self):
        pass


class TestCellTruncation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as error:  # 表示環境が無い CI など
            raise unittest.SkipTest(f"no display: {error}")

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def _view(self):
        from picoseq.ui.song_view import SongView
        return SongView(self.root, _FakeApp(self.root))

    def test_short_name_unchanged(self):
        view = self._view()
        self.assertEqual(view._fit_cell("F1"), "F1")
        self.assertEqual(view._fit_cell("サビ"), "サビ")

    def test_long_name_gets_ellipsis(self):
        view = self._view()
        out = view._fit_cell("とても長いパターン名前です")
        self.assertTrue(out.endswith("…"))
        self.assertLess(len(out), len("とても長いパターン名前です"))

    def test_result_always_fits_cell(self):
        """ASCII でも全角でも、省略後は必ずセル幅に収まる。"""
        from picoseq.ui.song_view import CELL_W, CELL_PAD
        view = self._view()
        for name in ("A", "サビ", "メインリフレイン", "x" * 40, "あ" * 40, "F8"):
            out = view._fit_cell(name)
            self.assertLessEqual(view.cell_font.measure(out), CELL_W - CELL_PAD, name)


if __name__ == "__main__":
    unittest.main()
