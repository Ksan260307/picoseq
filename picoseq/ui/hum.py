"""鼻歌ダイアログ — 録音または WAV ファイルからメロディを作る。"""

import tkinter as tk
import wave
from tkinter import filedialog

from ..core.humming import detect_melody
from ..core.project import steps_of
from . import mic, theme

RECORD_SECONDS = 6


class HumDialog:
    """録音 → 解析 → 取り込みの一連を案内する。"""

    def __init__(self, app):
        self.app = app
        self.notes = None

        win = tk.Toplevel(app.root)
        win.title("鼻歌からメロディを作る")
        win.configure(bg=theme.BG)
        win.transient(app.root)
        win.grab_set()
        win.resizable(False, False)
        self.win = win

        tk.Label(win, text="🎤 鼻歌からメロディを作る", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.ACCENT).pack(padx=20, pady=(14, 4))
        tk.Label(win,
                 text="「ラララ〜」と口ずさんだ声の高さを読み取って、\n"
                      "いま選んでいるキー・曲調の音に合わせたメロディにします。",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM,
                 justify="left").pack(padx=20, pady=(0, 10))

        self.status_var = tk.StringVar(value="録音するか、録音済みの WAV ファイルを選んでください。")
        tk.Label(win, textvariable=self.status_var, font=theme.FONT,
                 bg=theme.BG, fg=theme.TEXT, wraplength=380,
                 justify="left").pack(padx=20, pady=4)

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=8)
        self.record_btn = app._button(bar, f"● 録音する ({RECORD_SECONDS}秒)",
                                      self._record, accent=True)
        self.record_btn.pack(side="left", padx=6)
        app._button(bar, "📁 WAV を開く", self._open_file).pack(side="left", padx=6)

        bar2 = tk.Frame(win, bg=theme.BG)
        bar2.pack(pady=(4, 14))
        self.apply_btn = app._button(bar2, "♪ メロディにする", self._apply, accent=True)
        self.apply_btn.configure(state="disabled")
        self.apply_btn.pack(side="left", padx=6)
        app._button(bar2, "閉じる", win.destroy).pack(side="left", padx=6)
        win.bind("<Escape>", lambda e: win.destroy())

    # ---- 入力 ----

    def _record(self):
        if not mic.is_supported():
            self.status_var.set("この環境ではマイク録音できません。WAV ファイルを使ってください。")
            return
        self.record_btn.configure(state="disabled", text="● 録音中… 歌ってください!")
        self.status_var.set(f"録音中です ({RECORD_SECONDS} 秒間)。マイクに向かって歌ってください。")

        def work():
            pcm = mic.record(RECORD_SECONDS)
            return mic.pcm_to_samples(pcm), mic.RECORD_RATE

        def done(result):
            self.record_btn.configure(state="normal",
                                      text=f"● 録音する ({RECORD_SECONDS}秒)")
            self._analyze(*result)

        self.app._run_bg(work, lambda r: self._safe(done, r))

    def _open_file(self):
        path = filedialog.askopenfilename(
            parent=self.win, title="鼻歌の WAV を開く",
            filetypes=[("WAV 音声", "*.wav"), ("すべて", "*.*")])
        if not path:
            return
        self.status_var.set("ファイルを解析中…")

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
                self.status_var.set("メロディを聞き取れませんでした。\n"
                                    "もう少し大きな声で、ゆっくり歌ってみてください。")
                self.apply_btn.configure(state="disabled")
                return
            self.notes = notes
            self.status_var.set(f"{len(notes)} 個の音を聞き取りました。"
                                "「♪ メロディにする」で盤面に置きます。")
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
            raise ValueError("16bit の WAV のみ対応しています。")
        rate = f.getframerate()
        channels = f.getnchannels()
        pcm = f.readframes(f.getnframes())
    samples = mic.pcm_to_samples(pcm)
    if channels == 2:
        samples = [(samples[i] + samples[i + 1]) // 2
                   for i in range(0, len(samples) - 1, 2)]
    elif channels != 1:
        raise ValueError("モノラルかステレオの WAV のみ対応しています。")
    return samples, rate
