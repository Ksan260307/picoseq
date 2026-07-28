"""ピアノロール — フレーズ編集キャンバス。

座標→セル変換と描画だけを担当し、状態の変更はすべて app のメソッドへ渡す。
盤面は拡大・縮小 (zoom) でき、セルの幅・高さが一緒に変わる。
"""

import tkinter as tk

from ..core.constants import PITCH_MAX, PITCH_MIN
from ..core.music import in_scale, note_name
from ..core.note import soft_gain
from ..core.phrase import active_notes
from ..core.project import steps_of
from . import theme

BASE_CELL_H = 13
KEY_W = 46
ROLL_W = 784   # ノート領域の基準幅 (zoom=1.0 でこの幅に収める)
VIEW_H = 416   # 表示高さ (スクロールあり)
ROWS = PITCH_MAX - PITCH_MIN + 1

BLACK_KEYS = {1, 3, 6, 8, 10}

ZOOM_MIN = 0.5
ZOOM_MAX = 3.0
ZOOM_STEP = 1.25   # ボタン 1 回あたりの倍率


class RollView:
    def __init__(self, parent, app):
        """ピアノロールを組み立てる (鍵盤・グリッド・スクロール)。"""
        self.app = app
        self.zoom = getattr(app, "roll_zoom", 1.0)
        self.cell_w = 24
        self.cell_h = BASE_CELL_H
        self.full_h = ROWS * self.cell_h
        self.drag_slot = -1
        self.drag_anchor = -1

        self.frame = tk.Frame(parent, bg=theme.PANEL)
        self.canvas = tk.Canvas(
            self.frame, width=KEY_W + ROLL_W, height=VIEW_H,
            bg=theme.GRID_BG, highlightthickness=1,
            highlightbackground=theme.PANEL_EDGE,
        )
        vbar = tk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        hbar = tk.Scrollbar(self.frame, orient="horizontal", command=self._xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<Shift-Button-1>", self._on_shift_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_right_press)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._hide_hover())
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_wheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_wheel)
        self.canvas.bind("<Configure>", self._on_configure)
        self._last_w = 0

        self.rebuild()
        # C4 付近が見えるようにスクロール
        self.canvas.yview_moveto(((PITCH_MAX - 65) * self.cell_h) / self.full_h)

    # ---- ズーム ----

    def set_zoom(self, zoom: float):
        """拡大率を設定して描き直す (スクロール位置は概ね保つ)。"""
        zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
        if abs(zoom - self.zoom) < 1e-6:
            return
        top = self.canvas.yview()[0]
        left = self.canvas.xview()[0]
        self.zoom = zoom
        self.app.roll_zoom = zoom  # 画面再構築後も引き継ぐ
        self.rebuild()
        self.canvas.yview_moveto(top)
        self.canvas.xview_moveto(left)

    def zoom_in(self):
        self.set_zoom(self.zoom * ZOOM_STEP)

    def zoom_out(self):
        self.set_zoom(self.zoom / ZOOM_STEP)

    def zoom_reset(self):
        self.set_zoom(1.0)

    def _xview(self, *args):
        """横スクロール — 鍵盤を左端に貼り付けたまま動かす。"""
        self.canvas.xview(*args)
        self._pin_keys()

    # ---- 描画 ----

    def _on_configure(self, event):
        """パネルの幅が変わったら、盤面を幅いっぱいに引き直す。"""
        if abs(event.width - self._last_w) < 2:
            return
        self._last_w = event.width
        self.rebuild()

    def rebuild(self):
        """グリッドと鍵盤を描き直す (拍子・キー・スケール・ズーム・幅変更時)。"""
        project = self.app.project
        steps = steps_of(project)
        # 表示中のキャンバス幅に合わせて 1 セル幅を決める (zoom=1 で幅いっぱい)。
        avail = self.canvas.winfo_width() - KEY_W
        if avail < 50:            # まだレイアウトされていない初回は基準幅を使う
            avail = ROLL_W
        base_w = max(10, avail // steps)
        self.cell_w = max(4, int(round(base_w * self.zoom)))
        self.cell_h = max(6, int(round(BASE_CELL_H * self.zoom)))
        self.full_h = ROWS * self.cell_h
        width = KEY_W + self.cell_w * steps

        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(scrollregion=(0, 0, width, self.full_h))

        for row in range(ROWS):
            pitch = PITCH_MAX - row
            y = row * self.cell_h
            # 行の地色: 基準の音 > 音階に入っている音 > その他
            if pitch % 12 == project.key % 12:
                row_bg = theme.ROW_ROOT
            elif in_scale(pitch, project.key, project.scale, project.custom_scale):
                row_bg = theme.ROW_SCALE
            else:
                row_bg = theme.GRID_BG
            canvas.create_rectangle(KEY_W, y, width, y + self.cell_h,
                                    fill=row_bg, outline=theme.GRID_LINE)

        # 拍線と小節線
        for step in range(0, steps + 1, 2):
            x = KEY_W + step * self.cell_w
            if step % (project.beats * 4) == 0:
                color, w = theme.GRID_MEASURE, 2
            elif step % 4 == 0:
                color, w = theme.GRID_BEAT, 1
            else:
                color, w = theme.GRID_LINE, 1
            canvas.create_line(x, 0, x, self.full_h, fill=color, width=w)

        self._draw_keys()

        self.hover_item = canvas.create_rectangle(
            -10, -10, -10, -10, outline=theme.TEXT, width=1, dash=(2, 2))
        self.playhead_item = canvas.create_line(
            -10, 0, -10, self.full_h, fill=theme.PLAYHEAD, width=2)
        self.redraw_notes()

    def _draw_keys(self):
        """左端の鍵盤列 (タグ keys)。横スクロール時は _pin_keys で貼り付ける。"""
        canvas = self.canvas
        canvas.delete("keys")
        show_names = self.cell_h >= 9  # 小さすぎるときは音名を省く
        for row in range(ROWS):
            pitch = PITCH_MAX - row
            y = row * self.cell_h
            black = pitch % 12 in BLACK_KEYS
            canvas.create_rectangle(0, y, KEY_W, y + self.cell_h,
                                    fill=theme.KEY_BLACK if black else theme.KEY_WHITE,
                                    outline=theme.GRID_LINE, tags="keys")
            if show_names:
                is_c = pitch % 12 == 0
                canvas.create_text(
                    4, y + self.cell_h // 2, anchor="w", text=note_name(pitch),
                    font=theme.FONT_MONO_BOLD if is_c else theme.FONT_MONO,
                    fill=theme.KEY_TEXT_ON_BLACK if black else theme.KEY_TEXT,
                    tags="keys",
                )

    def _pin_keys(self):
        """鍵盤列を現在の横スクロール位置の左端へ移動する (常に見えるように)。"""
        try:
            bbox = self.canvas.bbox("keys")
        except tk.TclError:
            return
        if not bbox:
            return
        offset = self.canvas.canvasx(0)
        self.canvas.move("keys", offset - bbox[0], 0)
        self.canvas.tag_raise("keys")

    def redraw_notes(self):
        """音符を描き直す。選択中の (パート, レイヤー) は明るく、他は暗く。"""
        project = self.app.project
        steps = steps_of(project)
        canvas = self.canvas
        canvas.delete("note")

        current = self.app.part
        current_layer = self.app.layer
        muted = getattr(self.app, "muted", set())
        notes = [(s, n) for s, n in active_notes(project.phrase) if n.step < steps]
        # 非選択を先に (暗く)、選択中を後に (明るく) 描いて前面へ
        for slot, note in notes:
            if not (note.wave == current and note.layer == current_layer):
                base = theme.PART_COLORS[note.wave]
                is_muted = (note.wave, note.layer) in muted
                self._draw_note(note, steps,
                                theme.dim(base, 20 if is_muted else 45), "")
        for slot, note in notes:
            if note.wave == current and note.layer == current_layer:
                base = theme.PART_COLORS[note.wave]
                is_muted = (note.wave, note.layer) in muted
                fill = theme.dim(base, 40) if is_muted else base
                if not is_muted and note.soft:
                    # 弱い音は暗く描く (自動作成が付けた強弱を目で追えるように)
                    fill = theme.dim(fill, soft_gain(note.soft))
                self._draw_note(note, steps, fill, theme.PLAYHEAD)
        canvas.tag_raise(self.hover_item)
        canvas.tag_raise(self.playhead_item)
        self._pin_keys()

    def _draw_note(self, note, steps, fill, outline):
        """音符を 1 つ描く。"""
        dur = min(note.dur, steps - note.step)
        x0 = KEY_W + note.step * self.cell_w + 1
        y0 = (PITCH_MAX - note.pitch) * self.cell_h + 1
        x1 = KEY_W + (note.step + dur) * self.cell_w - 1
        y1 = y0 + self.cell_h - 2
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill,
                                     outline=outline or fill, tags="note")

    def set_playhead(self, tick):
        """再生位置の縦線。None で隠す。"""
        if tick is None:
            self.canvas.coords(self.playhead_item, -10, 0, -10, self.full_h)
        else:
            x = KEY_W + tick * self.cell_w
            self.canvas.coords(self.playhead_item, x, 0, x, self.full_h)

    # ---- 座標変換 ----

    def _locate(self, event):
        """イベント座標から ('key'|'grid'|None, pitch, step) へ。"""
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        row = int(y // self.cell_h)
        if not (0 <= row < ROWS) or x < 0:
            return None, 0, 0
        pitch = PITCH_MAX - row
        # 鍵盤は横スクロールに追従して左端に貼り付いている
        key_left = self.canvas.canvasx(0)
        if x < key_left + KEY_W:
            return "key", pitch, 0
        step = int((x - KEY_W) // self.cell_w)
        if 0 <= step < steps_of(self.app.project):
            return "grid", pitch, step
        return None, 0, 0

    # ---- マウス操作 ----

    def _on_press(self, event):
        """左クリック — 鍵盤なら試聴、マス目なら置く/消す。"""
        zone, pitch, step = self._locate(event)
        if zone == "key":
            self.app.preview_note(pitch)
        elif zone == "grid":
            slot, anchor = self.app.roll_press(pitch, step)
            self.drag_slot = slot
            self.drag_anchor = anchor

    def _on_drag(self, event):
        """ドラッグ — 音符を右へ伸ばす。"""
        if self.drag_slot == -1:
            return
        zone, _, step = self._locate(event)
        if zone == "grid" and step >= self.drag_anchor:
            self.app.roll_resize(self.drag_slot, step - self.drag_anchor + 1)

    def _on_release(self, _event):
        if self.drag_slot != -1:
            self.drag_slot = -1
            self.app.roll_release()

    def _on_shift_press(self, event):
        """Shift+クリックで強弱を 1 段回す (置く/消すとは別操作)。"""
        zone, pitch, step = self._locate(event)
        if zone == "grid":
            self.app.roll_cycle_soft(pitch, step)
        return "break"      # 通常のクリック (置く) を走らせない

    def _on_right_press(self, event):
        """右クリック — その位置の音符を消す。"""
        zone, pitch, step = self._locate(event)
        if zone == "grid":
            self.app.roll_erase(pitch, step)

    def _on_motion(self, event):
        """マウス移動 — 枠を追従させ、位置の説明を出す。"""
        zone, pitch, step = self._locate(event)
        if zone == "grid":
            x0 = KEY_W + step * self.cell_w
            y0 = (PITCH_MAX - pitch) * self.cell_h
            self.canvas.coords(self.hover_item, x0, y0,
                               x0 + self.cell_w, y0 + self.cell_h)
            self.app.show_cell_hint(pitch, step)
        else:
            self._hide_hover()

    def _hide_hover(self):
        self.canvas.coords(self.hover_item, -10, -10, -10, -10)

    def _on_wheel(self, event):
        """ホイール — 縦スクロール。"""
        self.canvas.yview_scroll(-event.delta // 120 * 3, "units")
        self._pin_keys()

    def _on_shift_wheel(self, event):
        """Shift+ホイール — 横スクロール。"""
        self.canvas.xview_scroll(-event.delta // 120 * 3, "units")
        self._pin_keys()

    def _on_ctrl_wheel(self, event):
        """Ctrl+ホイール — 拡大縮小。"""
        if event.delta > 0:
            self.zoom_in()
        else:
            self.zoom_out()
        return "break"
