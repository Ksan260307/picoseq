"""ソンググリッド — 4トラック x 16ブロックの構成キャンバス。

上端にブロック番号のルーラー、各セルにパターン名 (無ければ F 番号) を表示する。
配置中のパターンと同じセルは強調表示して、どこに何を置いたか分かりやすくする。
"""

import tkinter as tk
from tkinter import font as tkfont

from ..core.constants import EMPTY_CELL, SONG_BLOCKS, SONG_TRACKS
from ..core.project import steps_of
from ..core.song import get_cell
from . import theme

TOP = 18       # 上端: ブロック番号ルーラー
MARGIN = 34    # 左端: トラック名
CELL_W = 58
CELL_H = 44
CELL_PAD = 8   # セル内テキストの左右余白 (この幅に収まるよう省略する)
WIDTH = MARGIN + CELL_W * SONG_BLOCKS
HEIGHT = TOP + CELL_H * SONG_TRACKS


class SongView:
    def __init__(self, parent, app):
        self.app = app
        self.cell_font = tkfont.Font(font=theme.FONT_SMALL)
        self.frame = tk.Frame(parent, bg=theme.PANEL)
        self.canvas = tk.Canvas(
            self.frame, width=WIDTH, height=HEIGHT,
            bg=theme.GRID_BG, highlightthickness=1,
            highlightbackground=theme.PANEL_EDGE,
        )
        # 左寄せ。素の pack() だと tkinter が盤面を中央へ寄せてしまい、
        # 左に大きな死んだ余白ができて「壊れている」ように見える。
        self.canvas.pack(side="left", anchor="nw")
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<Button-3>", self._on_right_press)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self.app.clear_song_hint())
        self.rebuild()

    def _fit_cell(self, text: str) -> str:
        """セル幅に収まるよう、はみ出す分を「…」に置き換える (全角も実幅で判定)。"""
        max_px = CELL_W - CELL_PAD
        if self.cell_font.measure(text) <= max_px:
            return text
        for i in range(len(text) - 1, 0, -1):
            candidate = text[:i] + "…"
            if self.cell_font.measure(candidate) <= max_px:
                return candidate
        return "…"

    def rebuild(self):
        canvas = self.canvas
        canvas.delete("all")

        # ブロック番号ルーラー (1..16)
        for block in range(SONG_BLOCKS):
            x = MARGIN + block * CELL_W
            canvas.create_text(x + CELL_W // 2, TOP // 2 + 1, text=str(block + 1),
                               font=theme.FONT_MONO, fill=theme.TEXT_DIM)

        for track in range(SONG_TRACKS):
            y = TOP + track * CELL_H
            canvas.create_text(MARGIN - 6, y + CELL_H // 2, anchor="e",
                               text=f"T{track + 1}", font=theme.FONT_SMALL,
                               fill=theme.TEXT_DIM)
            for block in range(SONG_BLOCKS):
                x = MARGIN + block * CELL_W
                canvas.create_rectangle(x, y, x + CELL_W, y + CELL_H,
                                        fill=theme.GRID_BG, outline=theme.GRID_LINE)

        # 2 ブロックごとの区切り線
        for block in range(0, SONG_BLOCKS + 1, 2):
            x = MARGIN + block * CELL_W
            canvas.create_line(x, TOP, x, HEIGHT, fill=theme.GRID_MEASURE, width=2)

        self.block_tint = canvas.create_rectangle(-99, -99, -99, -99,
                                                  fill=theme.ROW_ROOT, outline="")
        canvas.tag_lower(self.block_tint)
        self.playhead_item = canvas.create_line(-10, TOP, -10, HEIGHT,
                                                fill=theme.PLAYHEAD, width=2)
        self.redraw_cells()

    def redraw_cells(self):
        canvas = self.canvas
        canvas.delete("cell")
        song = self.app.project.song
        selected = getattr(self.app, "selected_pattern", -1)
        for track in range(SONG_TRACKS):
            for block in range(SONG_BLOCKS):
                pattern_id = get_cell(song, track, block)
                if pattern_id == EMPTY_CELL:
                    continue
                x = MARGIN + block * CELL_W
                y = TOP + track * CELL_H
                color = theme.PATTERN_COLORS[pattern_id % len(theme.PATTERN_COLORS)]
                # 配置中のパターンと同じセルは明るい枠で強調
                outline = theme.PLAYHEAD if pattern_id == selected else ""
                width = 2 if pattern_id == selected else 0
                canvas.create_rectangle(x + 2, y + 2, x + CELL_W - 2, y + CELL_H - 2,
                                        fill=color, outline=outline, width=width,
                                        tags="cell")
                label = self._fit_cell(self.app.pattern_label(pattern_id))
                canvas.create_text(x + CELL_W // 2, y + CELL_H // 2, text=label,
                                   font=theme.FONT_SMALL, fill=theme.KEY_TEXT,
                                   tags="cell")
        canvas.tag_raise(self.playhead_item)

    def set_playhead(self, tick):
        """再生位置。tick はソング全体の通し Tick (None で隠す)。"""
        if tick is None:
            self.canvas.coords(self.playhead_item, -10, TOP, -10, HEIGHT)
            self.canvas.coords(self.block_tint, -99, -99, -99, -99)
            return
        steps = steps_of(self.app.project)
        block = int(tick // steps)
        x = MARGIN + (tick / steps) * CELL_W
        self.canvas.coords(self.playhead_item, x, TOP, x, HEIGHT)
        bx = MARGIN + block * CELL_W
        self.canvas.coords(self.block_tint, bx, TOP, bx + CELL_W, HEIGHT)

    def _cell_at(self, event):
        x = event.x - MARGIN
        y = event.y - TOP
        if x < 0 or y < 0:
            return None
        track = y // CELL_H
        block = x // CELL_W
        if 0 <= track < SONG_TRACKS and 0 <= block < SONG_BLOCKS:
            return int(track), int(block)
        return None

    def _on_press(self, event):
        cell = self._cell_at(event)
        if cell:
            self.app.song_click(*cell)

    def _on_right_press(self, event):
        cell = self._cell_at(event)
        if cell:
            self.app.song_erase(*cell)

    def _on_motion(self, event):
        cell = self._cell_at(event)
        if cell:
            self.app.show_song_hint(*cell)
        else:
            self.app.clear_song_hint()
