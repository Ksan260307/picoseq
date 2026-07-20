"""ピアノロール — フレーズ編集キャンバス。

座標→セル変換と描画だけを担当し、状態の変更はすべて app のメソッドへ渡す。
"""

import tkinter as tk

from ..core.constants import PITCH_MAX, PITCH_MIN
from ..core.music import in_scale, note_name
from ..core.note import unpack_note
from ..core.phrase import active_notes
from ..core.project import steps_of
from . import theme

CELL_H = 13
KEY_W = 46
ROLL_W = 784   # ノート領域の最大幅
VIEW_H = 416   # 表示高さ (スクロールあり)
ROWS = PITCH_MAX - PITCH_MIN + 1
FULL_H = ROWS * CELL_H

BLACK_KEYS = {1, 3, 6, 8, 10}


class RollView:
    def __init__(self, parent, app):
        self.app = app
        self.cell_w = 24
        self.drag_slot = -1
        self.drag_anchor = -1

        self.frame = tk.Frame(parent, bg=theme.PANEL)
        self.canvas = tk.Canvas(
            self.frame, width=KEY_W + ROLL_W, height=VIEW_H,
            bg=theme.GRID_BG, highlightthickness=1,
            highlightbackground=theme.PANEL_EDGE,
        )
        scrollbar = tk.Scrollbar(self.frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Button-3>", self._on_right_press)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._hide_hover())
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        self.rebuild()
        # C4 付近が見えるようにスクロール
        self.canvas.yview_moveto(((PITCH_MAX - 65) * CELL_H) / FULL_H)

    # ---- 描画 ----

    def rebuild(self):
        """グリッドと鍵盤を描き直す (拍子・キー・スケール変更時)。"""
        project = self.app.project
        steps = steps_of(project)
        self.cell_w = max(10, ROLL_W // steps)
        width = KEY_W + self.cell_w * steps

        canvas = self.canvas
        canvas.delete("all")
        canvas.configure(width=width, scrollregion=(0, 0, width, FULL_H))

        for row in range(ROWS):
            pitch = PITCH_MAX - row
            y = row * CELL_H
            # 行の地色: 基準の音 > 音階に入っている音 > その他
            if pitch % 12 == project.key % 12:
                row_bg = theme.ROW_ROOT
            elif in_scale(pitch, project.key, project.scale, project.custom_scale):
                row_bg = theme.ROW_SCALE
            else:
                row_bg = theme.GRID_BG
            canvas.create_rectangle(KEY_W, y, width, y + CELL_H,
                                    fill=row_bg, outline=theme.GRID_LINE)

            # 鍵盤
            black = pitch % 12 in BLACK_KEYS
            canvas.create_rectangle(0, y, KEY_W, y + CELL_H,
                                    fill=theme.KEY_BLACK if black else theme.KEY_WHITE,
                                    outline=theme.GRID_LINE, tags="keys")
            is_c = pitch % 12 == 0
            canvas.create_text(
                4, y + CELL_H // 2, anchor="w", text=note_name(pitch),
                font=theme.FONT_MONO_BOLD if is_c else theme.FONT_MONO,
                fill=theme.KEY_TEXT_ON_BLACK if black else theme.KEY_TEXT,
                tags="keys",
            )

        # 拍線と小節線
        for step in range(0, steps + 1, 2):
            x = KEY_W + step * self.cell_w
            if step % (project.beats * 4) == 0:
                color, w = theme.GRID_MEASURE, 2
            elif step % 4 == 0:
                color, w = theme.GRID_BEAT, 1
            else:
                color, w = theme.GRID_LINE, 1
            canvas.create_line(x, 0, x, FULL_H, fill=color, width=w)

        self.hover_item = canvas.create_rectangle(
            -10, -10, -10, -10, outline=theme.TEXT, width=1, dash=(2, 2))
        self.playhead_item = canvas.create_line(
            -10, 0, -10, FULL_H, fill=theme.PLAYHEAD, width=2)
        self.redraw_notes()

    def redraw_notes(self):
        """音符を描き直す。選択中の (パート, レイヤー) は明るく、他は暗く。"""
        project = self.app.project
        steps = steps_of(project)
        canvas = self.canvas
        canvas.delete("note")

        current = self.app.part
        current_layer = self.app.layer
        notes = [(s, n) for s, n in active_notes(project.phrase) if n.step < steps]
        # 非選択を先に (暗く)、選択中を後に (明るく) 描いて前面へ
        for slot, note in notes:
            if not (note.wave == current and note.layer == current_layer):
                self._draw_note(note, steps, theme.dim(theme.PART_COLORS[note.wave]), "")
        for slot, note in notes:
            if note.wave == current and note.layer == current_layer:
                self._draw_note(note, steps, theme.PART_COLORS[note.wave], theme.PLAYHEAD)
        canvas.tag_raise(self.hover_item)
        canvas.tag_raise(self.playhead_item)

    def _draw_note(self, note, steps, fill, outline):
        dur = min(note.dur, steps - note.step)
        x0 = KEY_W + note.step * self.cell_w + 1
        y0 = (PITCH_MAX - note.pitch) * CELL_H + 1
        x1 = KEY_W + (note.step + dur) * self.cell_w - 1
        y1 = y0 + CELL_H - 2
        self.canvas.create_rectangle(x0, y0, x1, y1, fill=fill,
                                     outline=outline or fill, tags="note")

    def set_playhead(self, tick):
        """再生位置の縦線。None で隠す。"""
        if tick is None:
            self.canvas.coords(self.playhead_item, -10, 0, -10, FULL_H)
        else:
            x = KEY_W + tick * self.cell_w
            self.canvas.coords(self.playhead_item, x, 0, x, FULL_H)

    # ---- 座標変換 ----

    def _locate(self, event):
        """イベント座標から ('key'|'grid'|None, pitch, step) へ。"""
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        row = int(y // CELL_H)
        if not (0 <= row < ROWS) or x < 0:
            return None, 0, 0
        pitch = PITCH_MAX - row
        if x < KEY_W:
            return "key", pitch, 0
        step = int((x - KEY_W) // self.cell_w)
        if 0 <= step < steps_of(self.app.project):
            return "grid", pitch, step
        return None, 0, 0

    # ---- マウス操作 ----

    def _on_press(self, event):
        zone, pitch, step = self._locate(event)
        if zone == "key":
            self.app.preview_note(pitch)
        elif zone == "grid":
            slot, anchor = self.app.roll_press(pitch, step)
            self.drag_slot = slot
            self.drag_anchor = anchor

    def _on_drag(self, event):
        if self.drag_slot == -1:
            return
        zone, _, step = self._locate(event)
        if zone == "grid" and step >= self.drag_anchor:
            self.app.roll_resize(self.drag_slot, step - self.drag_anchor + 1)

    def _on_release(self, _event):
        if self.drag_slot != -1:
            self.drag_slot = -1
            self.app.roll_release()

    def _on_right_press(self, event):
        zone, pitch, step = self._locate(event)
        if zone == "grid":
            self.app.roll_erase(pitch, step)

    def _on_motion(self, event):
        zone, pitch, step = self._locate(event)
        if zone == "grid":
            x0 = KEY_W + step * self.cell_w
            y0 = (PITCH_MAX - pitch) * CELL_H
            self.canvas.coords(self.hover_item, x0, y0,
                               x0 + self.cell_w, y0 + CELL_H)
            self.app.show_cell_hint(pitch, step)
        else:
            self._hide_hover()

    def _hide_hover(self):
        self.canvas.coords(self.hover_item, -10, -10, -10, -10)

    def _on_wheel(self, event):
        self.canvas.yview_scroll(-event.delta // 120 * 3, "units")
