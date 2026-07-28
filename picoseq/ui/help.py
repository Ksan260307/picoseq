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
        ("質感・長さ・音量", "選んだパート (層) ごとに、音の質感 (明るさ・太さ)・長さ・音量を調整できます。"
                       "ヘッダーの「音色」は曲全体の音色セットで、こちらとは別物です。"),
        ("音の強さ", "音符を Shift+クリックすると、その音の強さが 最強→強→弱→最弱→最強 と切り替わります。"
                   "弱い音ほど暗く描かれ、再生・WAV・MIDI にも反映されます。"),
        ("移調・反転", "🔼🔽 (または Ctrl+↑↓) で 1 オクターブ上げ下げ。🔄 でフレーズを時間反転。"),
        ("パート消去", "パートのボタンを右クリックすると、そのパートの音だけを消せます。"),
    ]),
    ("✨ 自動で作る", [
        ("自動作成", "押すたびに新しい「シード値」で1フレーズを生成します。番号は上の欄に表示され、"
                    "その番号を入力して Enter を押せばいつでも同じ曲を再現できます。"
                    "作成後は使われたコード進行 (例: Am→F→C→G) が画面下に出ます。"),
        ("演奏スタイル", "シード値ごとにパートの演奏型が変わります。"
                    "リズム 208 種 (骨格 13 × 密度 4 × アクセント 4)、"
                    "ベース 384 種 (動き 8 × 刻み 3 × 変化 8 × 音域 2)、"
                    "伴奏 600 種 (取り方 5 × 置き方 4 × 変化 6 × 長さ 5)、"
                    "メロディのリズム 10 種を組み合わせます。"
                    "音程や長さを変える軸では刻みは増えないので、"
                    "刻みの形そのものも リズム 52 / ベース 24 / 伴奏 22 通り用意しています。"),
        ("メロディの作り", "同じ音が続く回数に上限があり、どんなに疎なリズム型でも最低音数を保証します。"
                        "拍の頭はコードの音を守りつつ、裏拍には経過音を通すので、"
                        "安全すぎない歌になります。ベースの動きも見ていて、"
                        "土台と同じ向き・同じ音名へ進むのを避けます (反行)。"),
        ("強弱", "音符ごとに 4 段の強さが付きます (小節頭 > 拍頭 > 裏拍 > 埋めの音)。"
               "フレーズ最後の半小節はリズムが一段強くなり、次のループへの煽りになります。"
               "ピアノロールでは弱い音ほど暗く描かれ、WAV と MIDI にも反映されます。"),
        ("曲調に合う演奏", "曲調の性格に合った演奏が 4 パートすべてで出やすくなります "
                      "(和風なら太鼓と薄い伴奏、ボス戦なら倍テンと 16 分ベース、幻想ならボサとパッド)。"
                      "絞り込みではなく重み付けなので、どの曲調でも全部の型が出る余地があります。"),
        ("🎲 サプライズ", "曲調・キー・音色・拍子・テンポ・シード値に加え、各パートの音色 (パルス幅など) と長さも"
                        "まるごとランダムに選んで一発生成します。65 種類の曲調から、質感まで思いがけない"
                        "組み合わせに出会えます。テンポは曲調に合った範囲から選ばれます "
                        "(激しい曲調なら速く、幻想なら遅く)。拍子はソング構成を組み立て済みのときは"
                        "変わりません (ブロックの長さが変わると構成を作り直すことになるため)。"
                        "どのキーでもメロディの音域は 2 オクターブで一定です。"),
        ("🎸 伴奏づけ", "メロディ (パート1) だけを置いて押すと、その旋律に合うベース・リズム・サブを自動で付けます。"),
        ("📷 写真から", "写真の中の四角形 (最大8個) を読み取り、それぞれの位置を音に変えて「フォト音階」を作ります。"
                      "曲調に「📷 フォト音階」が追加され、その音だけを使った作曲を楽しめます。"),
    ]),
    ("🗂 パターンを管理する", [
        ("パターン編集タブ", "フレーズとソングの間の専用タブ。保存したパターン (最大8) を一覧で管理します。"),
        ("編集・名称・複製・削除", "各パターンを盤面へ読み込んで編集、名前を付ける、複製する、削除する、"
                              "▶ で試聴する — がその場でできます。"),
        ("★ 登録 / ＋ 保存", "気に入ったフレーズは フレーズ画面の ★ 登録、または パターン画面の空きスロットへ保存。"),
    ]),
    ("🎧 DJ モード", [
        ("回して流す", "▶ で開始すると、8 小節ごとに次のフレーズを自動生成して継ぎ目なく流し続けます"
                     "(次ループを裏で先に用意し、ループの境目で滑らかに差し替え)。"
                     "次のフレーズは候補をいくつか作って、今の音数に近いものを選びます — "
                     "疎なフレーズの直後に密なフレーズが来て段差になるのを防ぎます。"),
        ("🔁 ループ固定", "チェックを入れると自動で進まず、現在のフレーズをループし続けます。"
                       "固定中はつまみを触ってもフレーズは変わりません (音作りだけが変わります)。"
                       "中央の「次のフレーズまで N 小節」表示で進行のタイミングが分かります。"),
        ("スクラッチ", "ディスクをドラッグ (マウス) するとスクラッチできます。掴むと止まり、離すと再開。"
                    "動かさずにクリック (タップ) すると、そのデッキで新しいフレーズを生成します。"),
        ("クロスフェーダー", "デッキ A ⇄ B を切り替え。別の曲調のデッキを仕込んで展開できます。"),
        ("曲調 / キー / 音色", "どれもデッキごとに任意設定できます。キーをずらせば転調、揃えれば自然につながります。"
                          "DJ 中の音色変更では画面の配色は変わりません (ディスクが飛ばないように)。"
                          "曲調・キー・音色を変えてもフレーズの骨格は保たれます (作り直すのは 🎲 生成 のみ)。"),
        ("SYNC", "もう一方のデッキへテンポとキーを合わせます。曲調・音色はそのままなので、"
                 "別の曲調のまま拍とキーだけ揃えて重ねられます。"),
        ("質感 / 長さ / 音量 (パートごと)", "「パート」で メロディ/ベース/リズム/サブ を選び、そのパートの質感・長さ・音量を調整します。"
                              "質感はメロディならパルス波のデューティ比 (細い電子音⇄太い矩形波)、長さはゲート (歯切れ⇄伸び)、音量はミックスのバランス。"
                              "ヘッダーの「音色」(音色セット) とは別のつまみです。音符は変えず音作りだけが変わります。"),
        ("ノイズ / フィルター / KILL", "ノイズや掃引フィルターで盛り上げ、KILL で各パートを即消音。タップでテンポ合わせ。"
                                  "つまみはすべてデッキごとに独立し、その場で音に反映されます。"
                                  "ノイズは既にリズムが鳴っているステップを避けて刻みを足すので、"
                                  "上げるほど「太くなる」のではなく「細かくなる」。"),
        ("🕘 履歴 / ★ お気に入り", "流したフレーズが新しい順に並びます。行の →A / →B で任意のデッキへ呼び戻し、"
                             "★ でお気に入り登録 (次回起動でも残ります)、💾 でパターンとして保存。"
                             "つまみを調整した状態も履歴に残るので、作り込む前へいつでも戻せます (クリアで掃除)。"
                             "中央の ★ 登録 / 💾 残す は、今鳴っている音をそのまま残すショートカットです。"),
        ("⏺ 録音", "中央の録音ボタンで、鳴っているミックス (乗り換え・スクラッチ・ノイズ込み) を"
                 "そのまま WAV に書き出せます。もう一度押すと停止して保存先を選べます。"),
    ]),
    ("🧩 曲を組み立てる (ソング)", [
        ("ソング自動作成", "1 曲ぶんの構成 (イントロ→Aメロ→Bメロ→アウトロ) をワンボタンで作ります。"
                         "パターン 1〜4 とソング構成が丸ごと入れ替わります。"
                         "曲の設計図もシード値で選ばれます — 並び 6 種 (王道 / AABA / 交互 / "
                         "B主体 / 長いイントロ / 畳みかけ) × イントロの厚み 3 種 × "
                         "アウトロの余韻 3 種 = 54 通りです。"),
        ("配置する", "パレットでパターンを選ぶと「配置中」に名前が出ます。下のマス目に置きます。"
                   "横に連結・縦に重ねられます。マス目にはパターン名とブロック番号が出ます。"),
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
        ("Tone / Length / Volume", "Adjust the brightness (tone), length and volume per selected part (layer). Volume balances the mix."),
        ("Note strength", "Shift+click a note to cycle its strength: loudest → loud → soft → softest → loudest. "
                          "Softer notes are drawn darker and carry into playback, WAV and MIDI."),
        ("Transpose / Reverse", "🔼🔽 (or Ctrl+↑↓) shift one octave. 🔄 reverses the phrase in time."),
        ("Clear a part", "Right-click a part button to erase just that part's notes."),
    ]),
    ("✨ Make it automatically", [
        ("Auto", "Each press generates one phrase from a new \"seed\". The number shows in the field above; "
                 "type it and press Enter to reproduce the exact same music anytime. "
                 "After generating, the chord progression used (e.g. Am→F→C→G) appears at the bottom."),
        ("How melodies are written", "Repeats of the same pitch are capped and a minimum note count is "
                                    "guaranteed even for the sparsest rhythms. Beat heads stay on chord "
                                    "tones while off-beats let passing tones through, so it never sounds too safe. "
                                    "The melody also watches the bass and favours contrary motion."),
        ("Dynamics", "Every note carries one of four strengths (bar head > beat head > off-beat > ghost). "
                     "The last half-bar of drums is pushed one level as a lead-in to the next loop. "
                     "Softer notes are drawn darker in the piano roll, and it carries into WAV and MIDI."),
        ("🎲 Surprise", "Randomly picks mood, key, sound, meter, tempo and seed — plus each part's tone "
                       "(pulse width, etc.) and length — all at once. Discover unexpected textures from "
                       "65 moods. The tempo comes from a range that fits the mood (fast for fierce scales, "
                       "slow for dreamy ones). The meter is left alone once you have built a song, since "
                       "changing it would reset the arrangement. The melody keeps the same two-octave "
                       "span in every key."),
        ("🎸 Add backing", "Place only a melody (part 1) and press it to auto-add matching bass, rhythm and sub."),
        ("📷 From photo", "Reads rectangles (up to 8) in a photo and turns their positions into a \"photo scale\". "
                        "\"📷 Photo scale\" is added to Mood so you can compose using just those notes."),
    ]),
    ("🗂 Manage patterns", [
        ("Pattern editor tab", "A dedicated tab between Phrase and Song to manage saved patterns (up to 8)."),
        ("Edit / Rename / Duplicate / Delete", "Load a pattern onto the board to edit, give it a name, "
                                              "duplicate it, delete it, or preview with ▶ — right there."),
        ("★ Save / ＋ Save here", "Save a phrase with ★ on the Phrase screen, or into an empty slot on the Pattern screen."),
    ]),
    ("🎧 DJ mode", [
        ("Spin & flow", "Press ▶ and it auto-generates a new phrase every 8 bars and flows on with no gap "
                        "(the next loop is pre-rendered and swapped in on the downbeat). It drafts a few "
                        "candidates and picks the one closest in note count to what is playing, so a sparse "
                        "phrase is never followed by a wall of notes."),
        ("🔁 Hold", "Tick it to stop advancing and loop the current phrase instead. While held, "
                    "turning a knob only changes the sound — never the phrase. The centre shows "
                    "\"Next phrase in N bars\" so you can see the advance coming."),
        ("Scratch", "Drag a disc (with the mouse) to scratch — grabbing pauses, releasing resumes. "
                    "Click without moving (a tap) to generate a fresh phrase on that deck."),
        ("Crossfader", "Switch between decks A ⇄ B — cue up a different-mood deck, then bring it in."),
        ("Mood / Key / Sound", "All three are per-deck. Offset the keys to modulate, or match them to blend. "
                               "Changing the sound in DJ mode leaves the palette alone (so the discs don't jump). "
                               "None of them rewrite the phrase's shape — only 🎲 Roll does."),
        ("SYNC", "Matches tempo and key to the other deck. Mood and sound are left alone, so you can "
                 "layer two different moods that share a beat and a key."),
        ("Tone / Length / Volume (per part)", "Pick Melody/Bass/Rhythm/Sub under \"Part\", then adjust that part's tone, length and volume. "
                                     "Tone is the melody's pulse-wave duty cycle (thin blip ⇄ fat square); length is the gate (punchy ⇄ sustained); volume balances the mix. "
                                     "The notes stay the same, only the sound design changes."),
        ("Noise / Filter / KILL", "Add noise or sweep a filter to build energy; KILL instantly mutes a part. Tap sets tempo. "
                                  "Every control is per-deck and applies immediately. Noise fills the gaps between "
                                  "the existing drum hits, so turning it up makes the groove busier, not just louder."),
        ("🕘 History / ★ Favorites", "Every phrase you played, newest first. Use →A / →B on a row to recall it "
                                    "onto a deck, ★ to favorite it (kept between runs), 💾 to save it as a pattern. "
                                    "Control tweaks are logged too, so you can jump back before you dialed it in (Clear to tidy). "
                                    "The centre ★ Save / 💾 Keep do the same for whatever is playing now."),
        ("⏺ Record", "The record button in the centre captures the live mix (switches, scratches, noise and all) "
                     "straight to a WAV. Press again to stop and pick where to save."),
    ]),
    ("🧩 Build a song", [
        ("Auto song", "Builds a full arrangement (Intro→A→B→Outro) with one button. "
                      "Patterns 1-4 and the song are wholly replaced. The blueprint is picked by "
                      "the seed as well — 6 arrangements × 3 intro thicknesses × 3 outro fades "
                      "= 54 structures."),
        ("Place", "Pick a pattern from the palette — its name shows under \"Placing\" — and place it on the grid. "
                  "Chain horizontally, stack vertically. Cells show pattern names and block numbers."),
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
    ("Shift+クリック", "音の強さを切り替え"),
    ("Ctrl+Z / Y", "元に戻す / やり直す"),
    ("Ctrl+Tab", "フレーズ → パターン → ソング → DJ"),
    ("F1", "このヘルプ"),
]

SHORTCUTS_EN = [
    ("Space", "Play / Stop"),
    ("Esc", "Stop"),
    ("1-4", "Switch part"),
    ("Shift+click", "Cycle note strength"),
    ("Ctrl+Z / Y", "Undo / Redo"),
    ("Ctrl+Tab", "Phrase → Patterns → Song → DJ"),
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
        """ヘルプウィンドウを組み立てる。"""
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
        """見出しと項目の並びを 1 区画ぶん描く。"""
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
        """キーボードショートカットの一覧を描く。"""
        tk.Label(parent, text=heading, font=theme.FONT_BOLD, bg=theme.BG,
                 fg=theme.ACCENT, anchor="w").pack(fill="x", pady=(12, 2))
        for keys, desc in shortcuts:
            row = tk.Frame(parent, bg=theme.BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=keys, font=theme.FONT_MONO_BOLD, bg=theme.PANEL,
                     fg=theme.TEXT, width=14, anchor="w", padx=4).pack(side="left")
            tk.Label(row, text=desc, font=theme.FONT_SMALL, bg=theme.BG,
                     fg=theme.TEXT_DIM, anchor="w").pack(side="left", padx=6)
