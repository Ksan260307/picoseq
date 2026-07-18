"""ヘルプ画面 — 使い方・ショートカット・各機能の説明。"""

import tkinter as tk

from . import theme

# (見出し, [(項目, 説明), ...]) の並び。表示順に並べる。
SECTIONS = [
    ("🎵 フレーズを作る", [
        ("音を置く", "マス目を左クリック。もう一度クリックか右クリックで消せます。"),
        ("音を伸ばす", "置いたまま右へドラッグすると長くなります。"),
        ("試聴する", "左端の鍵盤をクリックすると、その高さの音が鳴ります。"),
        ("パート切替", "「パート」ボタン、またはキー 1〜4。メロディ・ベース・リズム・サブの4層。"),
        ("音色・長さ", "選んだパートごとに、音の明るさ (音色) と長さを調整できます。"),
    ]),
    ("✨ 自動で作る", [
        ("自動作成", "押すたびに新しい「シード値」で1フレーズを生成します。番号は上の欄に表示され、"
                    "その番号を入力して Enter を押せばいつでも同じ曲を再現できます。"),
        ("🎤 鼻歌から", "マイクに向かって歌う (または録音済み WAV を開く) と、声の高さを読み取って"
                      "メロディにします。そのあと「🎸 伴奏づけ」を押すと曲になります。"),
        ("🎸 伴奏づけ", "メロディ (パート1) だけを置いて押すと、その旋律に合うベース・リズム・サブを自動で付けます。"),
        ("📷 写真から", "写真の中の四角形 (最大8個) を読み取り、それぞれの位置を音に変えて「フォト音階」を作ります。"
                      "曲調に「📷 フォト音階」が追加され、その音だけを使った作曲を楽しめます。"),
    ]),
    ("🧩 曲を組み立てる (ソング)", [
        ("ソング自動作成", "1 曲ぶんの構成 (イントロ→Aメロ→Bメロ→アウトロ) をワンボタンで作ります。"
                         "パターン 1〜4 とソング構成が丸ごと入れ替わります。"),
        ("パターン登録", "気に入ったフレーズを ★ で保存 (最大8個)。ソング画面のパレットに並びます。"),
        ("配置する", "パレットでパターンを選び、下のマス目に置きます。横に連結・縦に重ねられます。"),
        ("消す", "同じマスをもう一度クリック、または右クリックで消去。"),
        ("WAV書出", "組み立てた曲を音声ファイル (.wav) に書き出せます。"),
    ]),
    ("▶ 再生と音色", [
        ("再生 / 停止", "Space キー、または再生ボタン。ループ再生します。"),
        ("リアルタイム反映", "演奏中に音を足したり消したりすると、その場で演奏に反映されます (止める必要なし)。"),
        ("テンポ", "上部のスライダーでいつでも変更でき、演奏中でも反映されます。"),
        ("音色セット", "上部の「音色」で全体の音の性格を選べます。ピコピコ 8bit (角の立った音)、"
                     "まろやか 16bit (丸くやさしい音)、きらめき 32bit (明るく厚い音)。"
                     "音色に合わせて画面の配色も衣替えします。"),
    ]),
    ("💾 保存とやり直し", [
        ("保存 / 読込", "作業内容をパソコンに保存・呼び出し。書出/取込で任意の場所に置けます。"),
        ("元に戻す", "Ctrl+Z / Ctrl+Y。ほとんどの操作を戻せます。"),
        ("旧バージョン", "以前のブラウザ版で作った retro_project.json も取り込めます。"),
    ]),
]

SHORTCUTS = [
    ("Space", "再生 / 停止"),
    ("Esc", "停止"),
    ("1〜4", "パート切替"),
    ("Ctrl+Z / Y", "元に戻す / やり直す"),
    ("Ctrl+Tab", "フレーズ ⇄ ソング"),
    ("F1", "このヘルプ"),
]


class HelpDialog:
    def __init__(self, app):
        if getattr(app, "silent", False):
            return
        win = tk.Toplevel(app.root)
        win.title("PicoSeq の使い方")
        win.configure(bg=theme.BG)
        win.transient(app.root)
        win.geometry("640x560")
        win.minsize(480, 400)

        tk.Label(win, text="PicoSeq の使い方", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.ACCENT).pack(pady=(12, 4))
        tk.Label(win, text="ドット絵風の音楽を作って鳴らすアプリです。",
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM).pack()

        body = self._scrollable(win)
        for title, items in SECTIONS:
            self._section(body, title, items)
        self._shortcuts(body)

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(fill="x", pady=8)
        app._button(bar, "閉じる", win.destroy).pack()
        win.bind("<Escape>", lambda e: win.destroy())
        win.bind("<F1>", lambda e: win.destroy())
        # 表示できたら前面へ (掴みは取らず、裏で再生を続けられるように)
        win.after(10, win.lift)

    def _scrollable(self, win):
        """縦スクロールできる内側フレームを返す。"""
        outer = tk.Frame(win, bg=theme.BG)
        outer.pack(fill="both", expand=True, padx=12, pady=6)
        canvas = tk.Canvas(outer, bg=theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=theme.BG)
        inner.bind("<Configure>",
                   lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-e.delta // 120, "units"))
        return inner

    def _section(self, parent, title, items):
        tk.Label(parent, text=title, font=theme.FONT_BOLD, bg=theme.BG,
                 fg=theme.ACCENT, anchor="w").pack(fill="x", pady=(10, 2))
        for name, desc in items:
            row = tk.Frame(parent, bg=theme.BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=name, font=theme.FONT_BOLD, bg=theme.BG,
                     fg=theme.TEXT, width=12, anchor="nw").pack(side="left")
            tk.Label(row, text=desc, font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, justify="left", wraplength=440,
                     anchor="w").pack(side="left", fill="x", expand=True)

    def _shortcuts(self, parent):
        tk.Label(parent, text="⌨ キーボード", font=theme.FONT_BOLD, bg=theme.BG,
                 fg=theme.ACCENT, anchor="w").pack(fill="x", pady=(12, 2))
        for keys, desc in SHORTCUTS:
            row = tk.Frame(parent, bg=theme.BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=keys, font=theme.FONT_MONO_BOLD, bg=theme.PANEL,
                     fg=theme.TEXT, width=14, anchor="w", padx=4).pack(side="left")
            tk.Label(row, text=desc, font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, anchor="w").pack(side="left", padx=6)
