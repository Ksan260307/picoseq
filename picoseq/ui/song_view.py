"""ソンググリッド — 4トラック x 16ブロックの構成キャンバス。"""

import tkinter as tk

from ..core.constants import EMPTY_CELL, SONG_BLOCKS, SONG_TRACKS
from ..core.project import steps_of
from ..core.song import get_cell
from . import theme

MARGIN = 30
CELL_W = 47
CELL_H = 45
WIDTH = MARGIN + CELL_W * SONG_BLOCKS
HEIGHT = CELL_H * SONG_TRACKS


class SongView:
    def __init__(self, parent, app):
        self.app = app
        self.frame = tk.Frame(parent, bg=theme.PANEL)
        self.canvas = tk.Canvas(
            self.frame, width=WIDTH, height=HEIGHT,
            bg=theme.GRID_BG, highlightthickness=1,
            highlightbackground=theme.PANEL_EDGE,
        )
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<Button-3>", self._on_right_press)
        self.rebuild()

    def rebuild(self):
        canvas = self.canvas
        canvas.delete("all")

        for track in range(SONG_TRACKS):
            y = track * CELL_H
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
            canvas.create_line(x, 0, x, HEIGHT, fill=theme.GRID_MEASURE, width=2)

        self.block_tint = canvas.create_rectangle(-99, -99, -99, -99,
                                                  fill=theme.ROW_ROOT, outline="")
        canvas.tag_lower(self.block_tint)
        self.playhead_item = canvas.create_line(-10, 0, -10, HEIGHT,
                                                fill=theme.PLAYHEAD, width=2)
        self.redraw_cells()

    def redraw_cells(self):
        canvas = self.canvas
        canvas.delete("cell")
        song = self.app.project.song
        for track in range(SONG_TRACKS):
            for block in range(SONG_BLOCKS):
                pattern_id = get_cell(song, track, block)
                if pattern_id == EMPTY_CELL:
                    continue
                x = MARGIN + block * CELL_W
                y = track * CELL_H
                color = theme.PATTERN_COLORS[pattern_id % len(theme.PATTERN_COLORS)]
                canvas.create_rectangle(x + 2, y + 2, x + CELL_W - 2, y + CELL_H - 2,
                                        fill=color, outline="", tags="cell")
                canvas.create_text(x + CELL_W // 2, y + CELL_H // 2,
                                   text=f"F{pattern_id + 1}", font=theme.FONT_BOLD,
                                   fill=theme.KEY_TEXT, tags="cell")
        canvas.tag_raise(self.playhead_item)

    def set_playhead(self, tick):
        """再生位置。tick はソング全体の通し Tick (None で隠す)。"""
        if tick is None:
            self.canvas.coords(self.playhead_item, -10, 0, -10, HEIGHT)
            self.canvas.coords(self.block_tint, -99, -99, -99, -99)
            return
        steps = steps_of(self.app.project)
        block = int(tick // steps)
        x = MARGIN + (tick / steps) * CELL_W
        self.canvas.coords(self.playhead_item, x, 0, x, HEIGHT)
        bx = MARGIN + block * CELL_W
        self.canvas.coords(self.block_tint, bx, 0, bx + CELL_W, HEIGHT)

    def _cell_at(self, event):
        x = event.x - MARGIN
        if x < 0:
            return None
        track = event.y // CELL_H
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
