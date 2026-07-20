"""鼻歌ダイアログ — 録音または WAV ファイルからメロディを作る。"""

import tkinter as tk
import wave
from tkinter import filedialog

from ..core.humming import detect_melody
from ..core.project import steps_of
from . import mic, theme
from .i18n import t

RECORD_SECONDS = 6


class HumDialog:
    """録音 → 解析 → 取り込みの一連を案内する。"""

    def __init__(self, app):
        self.app = app
        self.notes = None

        win = tk.Toplevel(app.root)
        win.title(t("hum_title"))
        win.configure(bg=theme.BG)
        win.transient(app.root)
        win.grab_set()
        win.resizable(False, False)
        self.win = win

        tk.Label(win, text=t("hum_head"), font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.ACCENT).pack(padx=20, pady=(14, 4))
        tk.Label(win, text=t("hum_intro"),
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 justify="left").pack(padx=20, pady=(0, 10))

        self.status_var = tk.StringVar(value=t("hum_ready"))
        tk.Label(win, textvariable=self.status_var, font=theme.FONT,
                 bg=theme.BG, fg=theme.TEXT, wraplength=380,
                 justify="left").pack(padx=20, pady=4)

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=8)
        self.record_btn = app._button(bar, t("hum_record", sec=RECORD_SECONDS),
                                      self._record, accent=True)
        self.record_btn.pack(side="left", padx=6)
        app._button(bar, t("hum_open_wav"), self._open_file).pack(side="left", padx=6)

        bar2 = tk.Frame(win, bg=theme.BG)
        bar2.pack(pady=(4, 14))
        self.apply_btn = app._button(bar2, t("hum_make"), self._apply, accent=True)
        self.apply_btn.configure(state="disabled")
        self.apply_btn.pack(side="left", padx=6)
        app._button(bar2, t("hum_close"), win.destroy).pack(side="left", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())

    # ---- 入力 ----

    def _record(self):
        if not mic.is_supported():
            self.status_var.set(t("hum_no_mic"))
            return
        self.record_btn.configure(state="disabled", text=t("hum_recording_btn"))
        self.status_var.set(t("hum_recording", sec=RECORD_SECONDS))

        def work():
            pcm = mic.record(RECORD_SECONDS)
            return mic.pcm_to_samples(pcm), mic.RECORD_RATE

        def done(result):
            self.record_btn.configure(state="normal",
                                      text=t("hum_record", sec=RECORD_SECONDS))
            self._analyze(*result)

        self.app._run_bg(work, lambda r: self._safe(done, r))

    def _open_file(self):
        path = filedialog.askopenfilename(
            parent=self.win, title=t("hum_open_title"),
            filetypes=[(t("ft_wav"), "*.wav"), (t("ft_all"), "*.*")])
        if not path:
            return
        self.status_var.set(t("hum_analyzing_file"))

        def work():
            return _load_wav_samples(path)

        self.app._run_bg(work, lambda r: self._safe(lambda x: self._analyze(*x), r))

    def _safe(self, func, result):
        """ダイアログが閉じられた後のコールバックを無視する。"""
        if self.win.winfo_exists():
            func(result)

    # ---- 解析と適用 ----

    def _analyze(self, samples, rate):
        project = self.app.project
        self.status_var.set("声の高さを解析中…")

        def work():
            return detect_melody(samples, rate, steps_of(project),
                                 project.key, project.scale, project.custom_scale)

        def done(notes):
            if not notes:
                self.status_var.set(t("hum_not_heard"))
                self.apply_btn.configure(state="disabled")
                return
            self.notes = notes
            self.status_var.set(t("hum_heard", n=len(notes)))
            self.apply_btn.configure(state="normal")

        self.app._run_bg(work, lambda r: self._safe(done, r))

    def _apply(self):
        if not self.notes:
            return
        self.win.destroy()
        self.app.apply_hum_melody(self.notes)


def _load_wav_samples(path):
    """WAV ファイルを整数サンプル列にする (ステレオは左右平均)。"""
    with wave.open(path) as f:
        if f.getsampwidth() != 2:
            raise ValueError(t("hum_err_16bit"))
        rate = f.getframerate()
        channels = f.getnchannels()
        pcm = f.readframes(f.getnframes())
    samples = mic.pcm_to_samples(pcm)
    if channels == 2:
        samples = [(samples[i] + samples[i + 1]) // 2
                   for i in range(0, len(samples) - 1, 2)]
    elif channels != 1:
        raise ValueError(t("hum_err_channels"))
    return samples, rate
