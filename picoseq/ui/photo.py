"""フォト音階ダイアログ — 写真から見つけた四角形と音階をプレビューして取り込む。"""

import tkinter as tk

from ..vision.harmony import describe, photo_scale_from_quads, scale_note_names
from ..vision.image import load_gray_grid
from ..vision.quad import detect_quads
from . import theme

PREVIEW_ZOOM = 2


def analyze_photo(path):
    """写真 → (格子, 四角形リスト, フォト音階 or None)。裏スレッドで呼べる。"""
    grid = load_gray_grid(path)
    quads = detect_quads(grid)
    if not quads:
        return grid, [], None
    return grid, quads, photo_scale_from_quads(quads)


class PhotoDialog:
    """検出した四角形 (最大 8 個) と音階を見せ、取り込み方を選ばせる。"""

    def __init__(self, app, grid, quads, photo):
        self.app = app
        self.photo_scale = photo

        win = tk.Toplevel(app.root)
        win.title("フォト音階 — 写真から音階を取り込む")
        win.configure(bg=theme.BG)
        win.transient(app.root)
        win.grab_set()
        win.resizable(False, False)
        self.win = win

        grid_w = len(grid[0])
        grid_h = len(grid)
        canvas = tk.Canvas(
            win, width=grid_w * PREVIEW_ZOOM, height=grid_h * PREVIEW_ZOOM,
            bg=theme.BG, highlightthickness=1,
            highlightbackground=theme.PANEL_EDGE,
        )
        canvas.pack(padx=12, pady=(12, 6))

        # グレースケール格子をそのままプレビューにする (解析に使った実データ)
        image = tk.PhotoImage(width=grid_w, height=grid_h)
        rows = ["{" + " ".join(f"#{v:02x}{v:02x}{v:02x}" for v in row) + "}"
                for row in grid]
        image.put(" ".join(rows))
        self.image = image.zoom(PREVIEW_ZOOM, PREVIEW_ZOOM)  # 参照保持 (GC 対策)
        canvas.create_image(0, 0, anchor="nw", image=self.image)

        # 検出した四角形をすべて重ね描きし、番号と音名を添える
        names = scale_note_names(photo)
        for i, quad in enumerate(quads):
            flat = []
            for x, y in quad.points:
                flat += [x * PREVIEW_ZOOM, y * PREVIEW_ZOOM]
            canvas.create_polygon(*flat, outline=theme.ACCENT, fill="", width=3)
            cx = sum(p[0] for p in quad.points) * PREVIEW_ZOOM // 4
            cy = sum(p[1] for p in quad.points) * PREVIEW_ZOOM // 4
            from ..core.music import NOTE_NAMES
            note = NOTE_NAMES[photo.pitch_classes[i]]
            canvas.create_text(cx, cy, text=f"{i + 1}:{note}",
                               font=theme.FONT_BOLD, fill=theme.PLAYHEAD)

        tk.Label(win, text=describe(photo), font=theme.FONT, justify="left",
                 bg=theme.BG, fg=theme.TEXT).pack(padx=14, pady=6, anchor="w")

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=(2, 12))
        app._button(bar, "♪ この音階で自動作成", self._apply_and_generate,
                    accent=True).pack(side="left", padx=6)
        app._button(bar, "🎼 音階だけ取り込む", self._apply_only).pack(side="left", padx=6)
        app._button(bar, "閉じる", win.destroy).pack(side="left", padx=6)
        win.bind("<Return>", lambda e: self._apply_and_generate())
        win.bind("<Escape>", lambda e: win.destroy())

    def _apply_and_generate(self):
        self.win.destroy()
        self.app.apply_photo_scale(self.photo_scale, generate=True)

    def _apply_only(self):
        self.win.destroy()
        self.app.apply_photo_scale(self.photo_scale, generate=False)
