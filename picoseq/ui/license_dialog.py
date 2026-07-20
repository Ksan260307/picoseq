"""ライセンス画面 — 状態表示とプロダクトコードの入力。"""

import tkinter as tk

from . import licensing, theme
from .i18n import t
from ..core.license import FREE_DAILY_LIMIT


class LicenseDialog:
    def __init__(self, app):
        if getattr(app, "silent", False):
            return
        self.app = app

        win = tk.Toplevel(app.root)
        win.title(t("lic_title"))
        win.configure(bg=theme.BG)
        win.transient(app.root)
        win.grab_set()
        win.resizable(False, False)
        self.win = win

        tk.Label(win, text=t("lic_title"), font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.ACCENT).pack(padx=24, pady=(16, 8))

        self.status_var = tk.StringVar()
        tk.Label(win, textvariable=self.status_var, font=theme.FONT, justify="left",
                 bg=theme.BG, fg=theme.TEXT, wraplength=400).pack(padx=24, pady=4)

        tk.Label(win, text=t("lic_intro"), font=theme.FONT_SMALL, justify="left",
                 bg=theme.BG, fg=theme.TEXT_DIM, wraplength=400).pack(padx=24, pady=(4, 8))

        row = tk.Frame(win, bg=theme.BG)
        row.pack(padx=24, pady=(0, 4), fill="x")
        tk.Label(row, text=t("lic_prompt"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 6))
        self.entry = tk.Entry(row, font=theme.FONT_MONO_BOLD, width=26,
                              bg=theme.BTN_BG, fg=theme.TEXT, relief="flat",
                              insertbackground=theme.TEXT)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", lambda e: self._activate())

        self.msg_var = tk.StringVar()
        tk.Label(win, textvariable=self.msg_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.ACCENT, wraplength=400).pack(padx=24, pady=2)

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=(6, 16))
        self.activate_btn = app._button(bar, t("lic_activate"), self._activate, accent=True)
        self.activate_btn.pack(side="left", padx=6)
        app._button(bar, t("lic_close"), win.destroy).pack(side="left", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())

        self._refresh()
        win.after(10, self.entry.focus_set)

    def _refresh(self):
        if licensing.is_pro():
            self.status_var.set(t("lic_status_pro"))
            self.entry.configure(state="disabled")
            self.activate_btn.configure(state="disabled")
        else:
            remaining = licensing.auto_gen_remaining()
            self.status_var.set(t("lic_status_free", limit=FREE_DAILY_LIMIT,
                                  remaining=remaining))

    def _activate(self):
        if licensing.is_pro():
            self.msg_var.set(t("lic_already_pro"))
            return
        code = self.entry.get().strip()
        if licensing.activate(code):
            self.msg_var.set(t("lic_activated"))
            self._refresh()
            self.app.on_license_changed()
        else:
            self.msg_var.set(t("lic_invalid"))
