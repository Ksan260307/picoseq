"""ヘルプ画面 — 使い方・ショートカット・各機能の説明 (日英)。"""

import tkinter as tk

from . import i18n, theme

# (見出し, [(項目, 説明), ...]) の並び。表示順に並べる。
SECTIONS_JA = [
    ("🎵 フレーズを作る", [
        ("音を置く", "マス目を左クリック。もう一度クリックか右クリックで消せます。"),
        ("音を伸ばす", "置いたまま右へドラッグすると長くなります。"),
        ("試聴する", "左端の鍵盤をクリックすると、その高さの音が鳴ります。"),
        ("パート切替", "「パート」ボタン、またはキー 1〜4。メロディ・ベース・リズム・サブの4層。"),
        ("レイヤー", "各パートは「＋ 追加」で最大8層まで重ねられます。層ごとに音色・音を分けられ、自動作成も各層に音を入れます。"),
        ("音色・長さ", "選んだパート (層) ごとに、音の明るさ (音色) と長さを調整できます。"),
        ("移調・反転", "🔼🔽 (または Ctrl+↑↓) で 1 オクターブ上げ下げ。🔄 でフレーズを時間反転。"),
        ("パート消去", "パートのボタンを右クリックすると、そのパートの音だけを消せます。"),
    ]),
    ("✨ 自動で作る", [
        ("自動作成", "押すたびに新しい「シード値」で1フレーズを生成します。番号は上の欄に表示され、"
                    "その番号を入力して Enter を押せばいつでも同じ曲を再現できます。"
                    "作成後は使われたコード進行 (例: Am→F→C→G) が画面下に出ます。"),
        ("🎲 サプライズ", "曲調・音色・シード値をまるごとランダムに選んで一発生成します。"
                        "65 種類の曲調から思いがけない組み合わせに出会えます。"),
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
        ("WAV / MIDI書出", "組み立てた曲を音声ファイル (.wav) や、DAW・楽譜ソフトで開ける"
                          "標準 MIDI ファイル (.mid) に書き出せます。"),
    ]),
    ("▶ 再生と音色", [
        ("再生 / 停止", "Space キー、または再生ボタン。ループ再生します。"),
        ("リアルタイム反映", "演奏中に音を足したり消したりすると、その場で演奏に反映されます (止める必要なし)。"),
        ("テンポ", "上部のスライダーでいつでも変更でき、演奏中でも反映されます。"),
        ("音色セット", "上部の「音色」で全体の音の性格を選べます。ピコピコ 8bit (角の立った音)、"
                     "まろやか 16bit (丸くやさしい音)、きらめき 32bit (明るく厚い音)。"
                     "音色に合わせて画面の配色も衣替えします。"),
        ("言語", "右上の 🌐 で表示を日本語 / English に切り替えられます。設定は次回も引き継がれます。"),
    ]),
    ("💾 保存とやり直し", [
        ("保存 / 読込", "作業内容をパソコンに保存・呼び出し。書出/取込で任意の場所に置けます。"),
        ("元に戻す", "Ctrl+Z / Ctrl+Y。ほとんどの操作を戻せます。"),
        ("旧バージョン", "以前のブラウザ版で作った retro_project.json も取り込めます。"),
    ]),
]

SECTIONS_EN = [
    ("🎵 Make a phrase", [
        ("Place a note", "Left-click a cell. Click again or right-click to erase it."),
        ("Lengthen a note", "Drag right after placing to make it longer."),
        ("Preview", "Click the keys on the left edge to hear that pitch."),
        ("Switch part", "The \"Part\" buttons, or keys 1-4. Four voices: Melody, Bass, Rhythm, Sub."),
        ("Layers", "Each part can stack up to 8 layers via \"＋ Add\". Layers get their own tone and notes, and Auto fills each one."),
        ("Tone / Length", "Adjust the brightness (tone) and length per selected part (layer)."),
        ("Transpose / Reverse", "🔼🔽 (or Ctrl+↑↓) shift one octave. 🔄 reverses the phrase in time."),
        ("Clear a part", "Right-click a part button to erase just that part's notes."),
    ]),
    ("✨ Make it automatically", [
        ("Auto", "Each press generates one phrase from a new \"seed\". The number shows in the field above; "
                 "type it and press Enter to reproduce the exact same music anytime. "
                 "After generating, the chord progression used (e.g. Am→F→C→G) appears at the bottom."),
        ("🎲 Surprise", "Randomly picks mood, sound and seed all at once for a one-shot creation. "
                       "Discover unexpected combinations from 65 moods."),
        ("🎤 From humming", "Sing into the mic (or open a recorded WAV) and it reads your pitch "
                          "into a melody. Then press \"🎸 Add backing\" to turn it into a song."),
        ("🎸 Add backing", "Place only a melody (part 1) and press it to auto-add matching bass, rhythm and sub."),
        ("📷 From photo", "Reads rectangles (up to 8) in a photo and turns their positions into a \"photo scale\". "
                        "\"📷 Photo scale\" is added to Mood so you can compose using just those notes."),
    ]),
    ("🧩 Build a song", [
        ("Auto song", "Builds a full arrangement (Intro→A→B→Outro) with one button. "
                      "Patterns 1-4 and the song are wholly replaced."),
        ("Save pattern", "Save a phrase you like with ★ (up to 8). They line up in the Song palette."),
        ("Place", "Pick a pattern from the palette and place it on the grid below. Chain horizontally, stack vertically."),
        ("Erase", "Click the same cell again, or right-click, to erase."),
        ("Export WAV / MIDI", "Export the built song as an audio file (.wav) or a standard MIDI file (.mid) "
                             "you can open in a DAW or notation software."),
    ]),
    ("▶ Playback and sound", [
        ("Play / Stop", "Space key, or the play button. It loops."),
        ("Live update", "Add or remove notes while playing and it reflects instantly (no need to stop)."),
        ("Tempo", "Change it anytime with the top slider, even while playing."),
        ("Sound set", "Pick the overall character with \"Sound\" at the top: Chiptune 8-bit (sharp-edged), "
                     "Mellow 16-bit (round and soft), Crystal 32-bit (bright and full). "
                     "The screen colors change to match."),
        ("Language", "Switch the display between 日本語 / English with 🌐 at the top-right. The choice is remembered."),
    ]),
    ("💾 Save and undo", [
        ("Save / Load", "Save and recall your work on the PC. Export/Import to place it anywhere."),
        ("Undo", "Ctrl+Z / Ctrl+Y. Reverts most operations."),
        ("Legacy version", "You can also import retro_project.json made with the older browser version."),
    ]),
]

SHORTCUTS_JA = [
    ("Space", "再生 / 停止"),
    ("Esc", "停止"),
    ("1〜4", "パート切替"),
    ("Ctrl+Z / Y", "元に戻す / やり直す"),
    ("Ctrl+Tab", "フレーズ ⇄ ソング"),
    ("F1", "このヘルプ"),
]

SHORTCUTS_EN = [
    ("Space", "Play / Stop"),
    ("Esc", "Stop"),
    ("1-4", "Switch part"),
    ("Ctrl+Z / Y", "Undo / Redo"),
    ("Ctrl+Tab", "Phrase ⇄ Song"),
    ("F1", "This help"),
]

_TEXT = {
    "ja": {
        "title": "PicoSeq の使い方",
        "subtitle": "ドット絵風の音楽を作って鳴らすアプリです。",
        "keyboard": "⌨ キーボード",
        "close": "閉じる",
    },
    "en": {
        "title": "How to use PicoSeq",
        "subtitle": "An app to make and play pixel-art style music.",
        "keyboard": "⌨ Keyboard",
        "close": "Close",
    },
}


class HelpDialog:
    def __init__(self, app):
        if getattr(app, "silent", False):
            return
        lang = i18n.get_lang()
        text = _TEXT[lang]
        sections = SECTIONS_EN if lang == "en" else SECTIONS_JA
        shortcuts = SHORTCUTS_EN if lang == "en" else SHORTCUTS_JA

        win = tk.Toplevel(app.root)
        win.title(text["title"])
        win.configure(bg=theme.BG)
        win.transient(app.root)
        win.geometry("640x560")
        win.minsize(480, 400)

        tk.Label(win, text=text["title"], font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.ACCENT).pack(pady=(12, 4))
        tk.Label(win, text=text["subtitle"],
                 font=theme.FONT_SMALL, bg=theme.BG, fg=theme.TEXT_DIM).pack()

        body = self._scrollable(win)
        for title, items in sections:
            self._section(body, title, items)
        self._shortcuts(body, shortcuts, text["keyboard"])

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(fill="x", pady=8)
        app._button(bar, text["close"], win.destroy).pack()
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
                     fg=theme.TEXT, width=14, anchor="nw").pack(side="left")
            tk.Label(row, text=desc, font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, justify="left", wraplength=430,
                     anchor="w").pack(side="left", fill="x", expand=True)

    def _shortcuts(self, parent, shortcuts, heading):
        tk.Label(parent, text=heading, font=theme.FONT_BOLD, bg=theme.BG,
                 fg=theme.ACCENT, anchor="w").pack(fill="x", pady=(12, 2))
        for keys, desc in shortcuts:
            row = tk.Frame(parent, bg=theme.BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=keys, font=theme.FONT_MONO_BOLD, bg=theme.PANEL,
                     fg=theme.TEXT, width=14, anchor="w", padx=4).pack(side="left")
            tk.Label(row, text=desc, font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, anchor="w").pack(side="left", padx=6)
