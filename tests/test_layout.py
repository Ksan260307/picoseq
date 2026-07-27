"""レイアウトの回帰テスト — 狭い画面でも部品が画面外へ消えない。

過去に「1366px のノート PC で保存・読込・書き出しが押せない」「880px では
保存すら画面外」という不具合があった。FlowBar の折り返しが効いていることを
機械的に確かめ、二度と戻らないようにする。
"""

import unittest

try:
    import tkinter as tk
    _r = tk.Tk()
    _r.withdraw()
    _r.destroy()
    _TK_OK = True
except Exception:       # noqa: BLE001 - ディスプレイが無い環境
    _TK_OK = False

if _TK_OK:
    from picoseq.ui.flowbar import FlowBar


# ---- FlowBar 単体 (アプリを建てずに折り返しの規則だけを見る) ----------------


@unittest.skipUnless(_TK_OK, "Tk が使えない環境")
class FlowBarTest(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:   # noqa: BLE001
            pass

    def _bar(self, widths):
        bar = FlowBar(self.root, bg="#000")
        bar.pack(fill="x")
        for w in widths:
            bar.add(tk.Frame(bar, bg="#000", width=w, height=20))
        bar.done()
        return bar

    @staticmethod
    def _pos(child):
        """place で指定した座標。withdraw 中は winfo_x/y が使えないので place_info を見る。"""
        info = child.place_info()
        return int(info["x"]), int(info["y"])

    def _rows(self, bar):
        """置かれた y 座標の種類数 = 行数。"""
        return len({self._pos(c)[1] for c in bar.winfo_children()
                    if c.winfo_manager() == "place"})

    def test_fits_in_one_row_when_wide(self):
        bar = self._bar([100, 100, 100])
        bar._relayout(1000)
        self.assertEqual(self._rows(bar), 1)

    def test_wraps_when_narrow(self):
        bar = self._bar([100, 100, 100, 100])
        bar._relayout(250)
        self.assertGreater(self._rows(bar), 1)

    def test_nothing_exceeds_available_width(self):
        cells = [120, 200, 90, 300, 150]
        bar = self._bar(cells)
        # どの部品も単体では収まる幅で試す (単体超過は別テスト)
        for avail in (320, 500, 700, 1000):
            bar._relayout(avail)
            for child in bar.winfo_children():
                if child.winfo_manager() != "place":
                    continue
                right = self._pos(child)[0] + child.winfo_reqwidth()
                self.assertLessEqual(right, avail,
                                     f"avail={avail} で右へはみ出した")

    def test_oversized_single_cell_still_placed_at_origin(self):
        """1 個だけで幅を超える部品も、少なくとも左端に置かれる (消えない)。"""
        bar = self._bar([800])
        bar._relayout(200)
        self.assertEqual(self._pos(bar.winfo_children()[0])[0], 0)

    def test_height_grows_with_rows(self):
        bar = self._bar([100] * 6)
        bar._relayout(1000)
        one_row = bar.winfo_reqheight()
        bar._relayout(220)
        self.assertGreater(bar.winfo_reqheight(), one_row)

    def test_relayout_is_not_recursive(self):
        """並べ直し中の <Configure> で無限ループしない。"""
        bar = self._bar([100, 100])
        bar._laying_out = True
        bar._relayout(100)          # 何も起きず戻るだけ
        bar._laying_out = False

    def test_resize_during_layout_is_not_lost(self):
        """並べ直し中に届いた幅変更を取り落とさない。

        取り落とすと「ウィンドウを縮めたのに折り返さない」= 部品が画面外に
        残る不具合になる (実際に起きた回帰)。
        """
        bar = self._bar([200, 200, 200])
        bar._relayout(1000)                    # まず 1 行
        bar._laying_out = True                 # 「並べ直し中」を再現
        bar._on_configure(type("E", (), {"width": 260})())
        bar._laying_out = False
        for _ in range(5):                     # after_idle を回す
            bar.update()
            bar.update_idletasks()
        self.assertGreater(self._rows(bar), 1, "縮めたのに折り返していない")

    def test_empty_bar_is_safe(self):
        bar = FlowBar(self.root, bg="#000")
        bar.pack(fill="x")
        bar.done()
        bar._relayout(500)          # 例外が出ないこと


# ---- 実アプリ: どの幅でも部品が画面外に出ない --------------------------------


@unittest.skipUnless(_TK_OK, "Tk が使えない環境")
class AppLayoutTest(unittest.TestCase):
    """回帰の本体。狭い幅でツールバーの部品が到達不能にならないこと。"""

    WIDTHS = (760, 900, 1150, 1366, 1600)

    @classmethod
    def setUpClass(cls):
        from picoseq.ui.app import PicoSeqApp
        cls.root = tk.Tk()
        cls.app = PicoSeqApp(cls.root, silent=True)

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:   # noqa: BLE001
            pass

    def _flowbars(self):
        found = []

        def walk(w):
            if isinstance(w, FlowBar):
                found.append(w)
            for child in w.winfo_children():
                walk(child)
        walk(self.root)
        return found

    def test_no_widget_is_pushed_offscreen(self):
        for width in self.WIDTHS:
            self.root.geometry(f"{width}x780")
            self.root.update()
            self.root.update_idletasks()
            for tab in ("phrase", "pattern", "song", "dj"):
                self.app.switch_tab(tab)
                self.root.update()
                self.root.update_idletasks()
                for bar in self._flowbars():
                    if not bar.winfo_ismapped():
                        continue
                    avail = bar.winfo_width()
                    for child in bar.winfo_children():
                        if child.winfo_manager() != "place":
                            continue
                        right = child.winfo_x() + child.winfo_reqwidth()
                        with self.subTest(width=width, tab=tab):
                            self.assertLessEqual(
                                right, avail + 1,
                                f"{tab} タブ幅 {width}px で部品が画面外へ出た")

    def _settle(self, width):
        self.root.geometry(f"{width}x780")
        self.root.update_idletasks()
        self.root.update()
        self.root.after(150, self.root.quit)
        self.root.mainloop()

    def test_control_panel_fits_its_content(self):
        """操作パネルは中身ぴったり — 死んだ余白も、中身の切れもない。"""
        self.app.switch_tab("phrase")
        panel = self.app.phrase_ctrl_panel
        for width in (900, 1366, 1600):
            self._settle(width)
            got = panel.container.winfo_height()
            need = panel.body.winfo_reqheight() + panel.header.winfo_reqheight()
            with self.subTest(width=width):
                self.assertGreaterEqual(got, need, "操作パネルの中身が切れている")
                self.assertLess(got - need, 24, "操作パネルに無駄な余白がある")

    def test_toolbar_uses_more_rows_when_narrow(self):
        """狭いときは行が増える (= 折り返しが実際に働いている)。"""
        def header_height():
            self.root.update()
            self.root.update_idletasks()
            return self._flowbars()[0].winfo_height()

        self.app.switch_tab("phrase")
        self.root.geometry("1600x780")
        wide = header_height()
        self.root.geometry("820x780")
        narrow = header_height()
        self.assertGreater(narrow, wide)


if __name__ == "__main__":
    unittest.main()
