"""フォト和音ダイアログ — 写真の解析結果をプレビューして適用する。"""

import tkinter as tk

from ..vision.harmony import describe, harmony_from_quad
from ..vision.image import load_gray_grid
from ..vision.quad import detect_quad
from . import theme

PREVIEW_ZOOM = 2


def analyze_photo(path):
    """写真 → (格子, 四角形 or None, 和音 or None)。裏スレッドで呼べる。"""
    grid = load_gray_grid(path)
    quad = detect_quad(grid)
    if quad is None:
        return grid, None, None
    return grid, quad, harmony_from_quad(quad)


class PhotoDialog:
    """検出した四角形と和音を見せ、「この和音で作曲」を選ばせる。"""

    def __init__(self, app, grid, quad, harmony):
        self.app = app
        self.harmony = harmony

        win = tk.Toplevel(app.root)
        win.title("フォト和音 — 写真から作曲")
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

        # 検出した四角形を重ね描き
        flat = []
        for x, y in quad.points:
            flat += [x * PREVIEW_ZOOM, y * PREVIEW_ZOOM]
        canvas.create_polygon(*flat, outline=theme.ACCENT, fill="", width=3)
        for x, y in quad.points:
            cx = x * PREVIEW_ZOOM
            cy = y * PREVIEW_ZOOM
            canvas.create_oval(cx - 5, cy - 5, cx + 5, cy + 5,
                               fill=theme.ACCENT, outline="")

        tk.Label(win, text=describe(harmony), font=theme.FONT, justify="left",
                 bg=theme.BG, fg=theme.TEXT).pack(padx=14, pady=6, anchor="w")

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=(2, 12))
        apply_button = app._button(bar, "♪ この和音で作曲", self._apply, accent=True)
        apply_button.pack(side="left", padx=6)
        app._button(bar, "閉じる", win.destroy).pack(side="left", padx=6)
        win.bind("<Return>", lambda e: self._apply())
        win.bind("<Escape>", lambda e: win.destroy())

    def _apply(self):
        self.win.destroy()
        self.app.apply_photo_harmony(self.harmony)
