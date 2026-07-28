"""ピアノロールのテスト — 座標変換・拡大縮小・描画。

画面を出さない (withdraw した Tk) 状態で組み立て、
「クリック位置がどのセルになるか」「拡大で何が変わるか」を直接確かめる。
selftest では通しの流れしか見ないので、境界の計算はここで押さえる。
"""

import unittest

from picoseq.core.constants import PITCH_MAX, PITCH_MIN
from picoseq.core.project import steps_of

from tests._ui_util import close_app, make_app, tk_available


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestRollGeometry(unittest.TestCase):
    """座標 → (種別, 音高, ステップ) の変換。"""

    @classmethod
    def setUpClass(cls):
        cls.app, cls.root = make_app()
        cls.roll = cls.app.roll

    @classmethod
    def tearDownClass(cls):
        close_app(cls.app, cls.root)

    def _locate(self, canvas_x, canvas_y):
        """キャンバス座標を指してクリックしたことにする。

        盤面は起動時に中央あたりへスクロールされているので、
        ウィジェット座標へ直してから渡す (でないと行がずれる)。
        """
        canvas = self.roll.canvas
        class Event:
            pass
        event = Event()
        event.x = canvas_x - canvas.canvasx(0)
        event.y = canvas_y - canvas.canvasy(0)
        return self.roll._locate(event)

    def test_left_edge_is_the_keyboard(self):
        zone, pitch, step = self._locate(5, 0)
        self.assertEqual(zone, "key")
        self.assertEqual(pitch, PITCH_MAX)      # 一番上の行は最高音

    def test_grid_maps_to_pitch_and_step(self):
        from picoseq.ui.roll_view import KEY_W
        zone, pitch, step = self._locate(KEY_W + 1, 0)
        self.assertEqual(zone, "grid")
        self.assertEqual(pitch, PITCH_MAX)
        self.assertEqual(step, 0)

    def test_row_height_maps_each_pitch(self):
        from picoseq.ui.roll_view import KEY_W
        for row in (0, 1, 5, 20):
            y = row * self.roll.cell_h + 1
            _, pitch, _ = self._locate(KEY_W + 1, y)
            with self.subTest(row=row):
                self.assertEqual(pitch, PITCH_MAX - row)

    def test_step_advances_by_cell_width(self):
        from picoseq.ui.roll_view import KEY_W
        for step in (0, 1, 7):
            x = KEY_W + step * self.roll.cell_w + 1
            _, _, got = self._locate(x, 0)
            with self.subTest(step=step):
                self.assertEqual(got, step)

    def test_beyond_the_last_step_is_outside(self):
        from picoseq.ui.roll_view import KEY_W
        steps = steps_of(self.app.project)
        x = KEY_W + steps * self.roll.cell_w + 2
        zone, _, _ = self._locate(x, 0)
        self.assertIsNone(zone)

    def test_lowest_row_is_the_lowest_pitch(self):
        from picoseq.ui.roll_view import KEY_W, ROWS
        y = (ROWS - 1) * self.roll.cell_h + 1
        _, pitch, _ = self._locate(KEY_W + 1, y)
        self.assertEqual(pitch, PITCH_MIN)


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestRollZoom(unittest.TestCase):
    """拡大縮小 — 上限下限と、アプリ側への引き継ぎ。"""

    def setUp(self):
        self.app, self.root = make_app()
        self.roll = self.app.roll

    def tearDown(self):
        close_app(self.app, self.root)

    def test_zoom_in_out_returns_to_start(self):
        from picoseq.ui.roll_view import ZOOM_STEP
        before = self.roll.zoom
        self.roll.zoom_in()
        self.assertAlmostEqual(self.roll.zoom, before * ZOOM_STEP)
        self.roll.zoom_out()
        self.assertAlmostEqual(self.roll.zoom, before)

    def test_zoom_is_clamped(self):
        from picoseq.ui.roll_view import ZOOM_MAX, ZOOM_MIN
        for _ in range(20):
            self.roll.zoom_in()
        self.assertAlmostEqual(self.roll.zoom, ZOOM_MAX)
        for _ in range(40):
            self.roll.zoom_out()
        self.assertAlmostEqual(self.roll.zoom, ZOOM_MIN)

    def test_zoom_changes_cell_size(self):
        small = (self.roll.cell_w, self.roll.cell_h)
        self.roll.zoom_in()
        big = (self.roll.cell_w, self.roll.cell_h)
        self.assertGreater(big[0], small[0])
        self.assertGreater(big[1], small[1])

    def test_zoom_is_kept_on_the_app(self):
        """画面を作り直しても拡大率が続くよう、app 側へ書き戻す。"""
        self.roll.zoom_in()
        self.assertAlmostEqual(self.app.roll_zoom, self.roll.zoom)

    def test_reset_returns_to_100(self):
        """アプリ側の zoom_reset は表示ラベルも 100% に戻す。"""
        self.app.zoom_in()
        self.app.zoom_reset()
        self.assertAlmostEqual(self.roll.zoom, 1.0)
        self.assertEqual(self.app.zoom_var.get(), "100%")


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestRollDrawing(unittest.TestCase):
    """描画 — 音符の数と、強弱による明るさ。"""

    def setUp(self):
        self.app, self.root = make_app()
        self.roll = self.app.roll

    def tearDown(self):
        close_app(self.app, self.root)

    def _note_items(self):
        return self.roll.canvas.find_withtag("note")

    def test_notes_are_drawn_once_each(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(
            actions.set_seed(self.app.project, 42)))
        from picoseq.core.phrase import count_notes
        self.assertEqual(len(self._note_items()),
                         count_notes(self.app.project.phrase))

    def test_soft_notes_are_drawn_darker(self):
        """弱い音ほど暗く描く (自動作成が付けた強弱を目で追えるように)。"""
        from picoseq.core import actions
        self.app.roll_press(60, 0)
        self.app.roll_release()
        loud = self._fill_of_first_note()
        slot = next(s for s, _ in self._active())
        self.app.commit(actions.set_note_soft(self.app.project, slot, 3))
        soft = self._fill_of_first_note()
        self.assertNotEqual(loud, soft)
        self.assertLess(self._brightness(soft), self._brightness(loud))

    def _active(self):
        from picoseq.core.phrase import active_notes
        return active_notes(self.app.project.phrase)

    def _fill_of_first_note(self):
        item = self._note_items()[0]
        return self.roll.canvas.itemcget(item, "fill")

    @staticmethod
    def _brightness(color):
        return sum(int(color[i:i + 2], 16) for i in (1, 3, 5))

    def test_playhead_can_be_placed_and_hidden(self):
        self.roll.set_playhead(4)
        coords = self.roll.canvas.coords(self.roll.playhead_item)
        self.assertGreater(coords[0], 0)
        self.roll.set_playhead(None)
        self.assertLess(self.roll.canvas.coords(self.roll.playhead_item)[0], 0)


if __name__ == "__main__":
    unittest.main()
