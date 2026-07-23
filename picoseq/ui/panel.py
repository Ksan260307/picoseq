"""ドックパネル — PanedWindow のペイン。

タイトルバーの「⧉ 切り離し」で独立したウィンドウに切り離し、「⧈ 戻す」または
ウィンドウを閉じると元の位置へ戻る。Tk の `wm manage` / `wm forget` を使う。
中身 (キャンバス等) の状態はそのまま保たれる (再構築しない)。
"""

import tkinter as tk

from . import theme
from .i18n import t


class DockPanel:
    def __init__(self, paned, title, app, minsize=70, height=None, stretch="always"):
        self.paned = paned
        self.app = app
        self.title = title
        self.minsize = minsize
        self.stretch = stretch
        self.detached = False
        self._after = None

        self.container = tk.Frame(paned, bg=theme.PANEL,
                                  highlightbackground=theme.PANEL_EDGE,
                                  highlightthickness=1)
        self.header = tk.Frame(self.container, bg=theme.PANEL_EDGE)
        self.header.pack(fill="x")
        tk.Label(self.header, text=title, font=theme.FONT_SMALL,
                 bg=theme.PANEL_EDGE, fg=theme.TEXT).pack(side="left", padx=6, pady=1)
        self.toggle_btn = tk.Button(
            self.header, text=t("panel_detach"), font=theme.FONT_SMALL,
            bg=theme.BTN_BG, fg=theme.TEXT, activebackground=theme.BTN_ACTIVE,
            relief="flat", bd=0, padx=6, pady=0, takefocus=0, cursor="hand2",
            command=self.toggle)
        self.toggle_btn.pack(side="right", padx=2, pady=1)

        self.body = tk.Frame(self.container, bg=theme.PANEL)
        self.body.pack(fill="both", expand=True)

        opts = {"minsize": minsize, "stretch": stretch}
        if height is not None:
            opts["height"] = height
        paned.add(self.container, **opts)

    def toggle(self):
        if self.detached:
            self.redock()
        else:
            self.detach()

    def detach(self):
        panes = self.paned.panes()
        path = str(self.container)
        if path in panes:
            idx = panes.index(path)
            self._after = panes[idx + 1] if idx + 1 < len(panes) else None
            self.paned.forget(self.container)
        root = self.app.root
        root.tk.call("wm", "manage", self.container)
        root.tk.call("wm", "title", self.container, self.title)
        w = max(360, self.container.winfo_width())
        h = max(220, self.container.winfo_height())
        root.tk.call("wm", "geometry", self.container, f"{w}x{h}")
        cb = root.register(self.redock)
        root.tk.call("wm", "protocol", self.container._w, "WM_DELETE_WINDOW", cb)
        self.toggle_btn.configure(text=t("panel_redock"))
        self.detached = True

    def redock(self):
        if not self.detached:
            return
        root = self.app.root
        root.tk.call("wm", "forget", self.container)
        panes = self.paned.panes()
        if self._after and str(self._after) in panes:
            self.paned.add(self.container, before=self._after,
                           minsize=self.minsize, stretch=self.stretch)
        else:
            self.paned.add(self.container, minsize=self.minsize, stretch=self.stretch)
        self.toggle_btn.configure(text=t("panel_detach"))
        self.detached = False
