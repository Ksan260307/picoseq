"""DJ モードの画面 — 2 枚のターンテーブルと、デッキごとのチャンネルストリップ。

見た目 (回転・脈動・スクラッチ) だけを担当し、状態変更はすべて app のメソッドへ渡す。
曲調・キー・音色・テンポ・ノイズ・パート音作り(音色/長さ/音量)・フィルター・固定・KILL は**デッキごと独立**。
中央にあるのは共通の操作 (再生・クロスフェーダー・タップ・★/💾・録音) だけ。
下段は流したフレーズの履歴とお気に入りで、どちらからでもデッキへ呼び戻せる。
"""

import math
import tkinter as tk
from tkinter import ttk

from ..core import dj as dj_core
from ..core.constants import BPM_MAX, BPM_MIN
from .flowbar import FlowBar
from ..core.music import KEY_NAMES, SCALE_IDS, SCALES
from . import i18n, theme
from .i18n import t

PLATTER = 196          # ターンテーブルのキャンバス辺長
R_OUTER = 91
R_LABEL = 34
R_MARK_IN = 38
R_MARK_OUT = 86
DECK_KEYS = ("a", "b")
STRIP_LABEL = 54       # ストリップのラベル列幅
SLIDER_LEN = 88
MOOD_WIDTH = 12        # 曲調セレクタの文字幅
LOG_ROWS = 5           # 一覧の高さ (行数)。これを超えるぶんはスクロールで見る
LOG_ROW_H = 24         # 1 行のおおよその高さ (px)


def angle_diff(a, b):
    """角度 a-b の最短符号つき差 (-180, 180]。"""
    return (a - b + 180) % 360 - 180


def scale_choices():
    """曲調セレクタの選択肢 (表示名の並び。並び順は SCALE_IDS と一致)。"""
    return [i18n.scale_label(s, SCALES[s]["label"]) for s in SCALE_IDS]


class DJView:
    def __init__(self, parent, app):
        """DJ 画面を組み立てる (デッキ 2 枚とミキサー)。"""
        self.app = app
        self.deck_angle = {"a": 0.0, "b": 0.0}
        self.platters = {}
        self.decks = {}              # key -> ウィジェット一式
        self._part_focus = {"a": 0, "b": 0}   # 音色・長さスライダーが編集するパート
        self._active_key = "a"
        self._grab = None
        self._syncing = False        # 同期中はコールバックを無視する

        self.frame = tk.Frame(parent, bg=theme.BG)
        # 幅が足りなければデッキ B が下へ折り返す (狭い画面で画面外に消えない)。
        # 素の pack だと中央寄せ・見切れのどちらかになり、B が操作できなくなる。
        self.console = FlowBar(self.frame, bg=theme.BG, gap=10)
        self.console.pack(side="top", fill="x", padx=6, pady=(2, 0))

        self._build_deck("a", strip_side="right")
        self._build_mixer()
        self._build_deck("b", strip_side="left")
        self.console.done()
        self._build_log()

    # ---- デッキ (ターンテーブル + チャンネルストリップ) ----

    def _build_deck(self, key, strip_side):
        """片方のデッキ (ターンテーブルとつまみ) を作る。"""
        color = _deck_color(key)
        deck = DECK_KEYS.index(key)
        wrap = tk.Frame(self.console, bg=theme.BG)
        self.console.add(wrap)

        tk.Label(wrap, text=t("dj_deck", deck=key.upper()), font=theme.FONT_BOLD,
                 bg=theme.BG, fg=color).pack(pady=(0, 2))

        body = tk.Frame(wrap, bg=theme.BG)
        body.pack()

        disc = tk.Frame(body, bg=theme.BG)
        strip = tk.Frame(body, bg=theme.PANEL, padx=8, pady=6,
                         highlightbackground=theme.PANEL_EDGE, highlightthickness=1)
        if strip_side == "right":
            disc.pack(side="left")
            strip.pack(side="left", padx=(8, 0), anchor="n")
        else:
            strip.pack(side="left", padx=(0, 8), anchor="n")
            disc.pack(side="left")

        canvas = tk.Canvas(disc, width=PLATTER, height=PLATTER, bg=theme.BG,
                           highlightthickness=0, cursor="hand2")
        canvas.pack()
        canvas.bind("<ButtonPress-1>", lambda e, k=key: self._on_platter_press(k, e))
        canvas.bind("<B1-Motion>", lambda e, k=key: self._on_platter_motion(k, e))
        canvas.bind("<ButtonRelease-1>", lambda e, k=key: self._on_platter_release(k, e))
        self.platters[key] = {"canvas": canvas, "color": color,
                              **self._draw_platter(canvas, color, key.upper())}

        name_var = tk.StringVar()
        seed_var = tk.StringVar()
        tk.Label(disc, textvariable=name_var, font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.TEXT).pack(pady=(4, 0))
        tk.Label(disc, textvariable=seed_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack()

        self.decks[key] = {"name": name_var, "seed": seed_var}
        self._build_strip(strip, key, deck)

    def _build_strip(self, strip, key, deck):
        """デッキ 1 台ぶんの操作列。区画ごとに分けて上から積む。

        各 _strip_* は「使った次の行番号」を返す。行番号を持ち回るのは
        つまみを足し引きしたときに他の区画をいちいち直さないため。
        """
        widgets = self.decks[key]
        strip.columnconfigure(0, minsize=STRIP_LABEL)
        row = self._strip_pickers(strip, widgets, deck, 0)
        row = self._strip_mix_sliders(strip, widgets, deck, row)
        row = self._strip_part_editor(strip, widgets, deck, row)
        row = self._strip_toggles(strip, widgets, deck, row)
        self._strip_foot(strip, deck, row)

    # ---- 操作列の部品 ----

    def _strip_label(self, strip, key_name, row):
        """左列のラベル (右寄せ)。"""
        tk.Label(strip, text=t(key_name), font=theme.FONT_SMALL, bg=theme.PANEL,
                 fg=theme.TEXT_DIM, anchor="e").grid(row=row, column=0, sticky="e",
                                                     padx=(0, 6), pady=2)

    def _strip_slider(self, strip, row, label_key, lo, hi, command, active,
                      width=4):
        """ラベル｜スライダー＋数値 の 1 行を作り、(スライダー, 数値 var) を返す。"""
        self._strip_label(strip, label_key, row)
        holder = tk.Frame(strip, bg=theme.PANEL)
        holder.grid(row=row, column=1, sticky="w", pady=2)
        scale = tk.Scale(holder, from_=lo, to=hi, orient="horizontal",
                         length=SLIDER_LEN, showvalue=0, command=command,
                         bg=theme.PANEL, troughcolor=theme.BTN_BG,
                         highlightthickness=0, bd=0, sliderlength=16, width=11,
                         activebackground=active)
        scale.pack(side="left")
        var = tk.StringVar()
        tk.Label(holder, textvariable=var, font=theme.FONT_SMALL, width=width,
                 bg=theme.PANEL, fg=theme.TEXT, anchor="w").pack(side="left",
                                                                 padx=(4, 0))
        return scale, var

    def _strip_glyph_row(self, strip, row, label_key, command):
        """M/B/R/S の 4 ボタンを 1 行に並べ、ボタンの並びを返す。"""
        self._strip_label(strip, label_key, row)
        holder = tk.Frame(strip, bg=theme.PANEL)
        holder.grid(row=row, column=1, sticky="w", pady=2)
        buttons = []
        for i, glyph in enumerate(("M", "B", "R", "S")):
            btn = tk.Button(holder, text=glyph, font=theme.FONT_SMALL, width=2,
                            relief="flat", bd=1, takefocus=0, cursor="hand2",
                            command=lambda i=i: command(i))
            btn.pack(side="left", padx=1)
            buttons.append(btn)
        return buttons

    def _strip_pickers(self, strip, widgets, deck, row):
        """曲調・キー・音色の選択欄 (どれもデッキごとに独立)。"""
        specs = (
            ("mood", "dj_mood_label", scale_choices(), self._on_mood),
            ("key", "dj_key_label", list(KEY_NAMES), self._on_key),
            # 音色はデッキごと。フレーズ画面と違い配色は変えない
            ("sound", "lbl_sound",
             [i18n.sound_label(s) for s in theme.SOUND_IDS], self._on_sound),
        )
        for name, label_key, values, handler in specs:
            self._strip_label(strip, label_key, row)
            combo = ttk.Combobox(strip, values=values, state="readonly",
                                 width=MOOD_WIDTH, font=theme.FONT_SMALL)
            combo.grid(row=row, column=1, sticky="w", pady=2)
            combo.bind("<<ComboboxSelected>>",
                       lambda e, d=deck, c=combo, h=handler: h(d, c))
            widgets[name] = combo
            row += 1
        return row

    def _strip_mix_sliders(self, strip, widgets, deck, row):
        """テンポとノイズ。"""
        widgets["tempo"], widgets["tempo_var"] = self._strip_slider(
            strip, row, "dj_tempo", BPM_MIN, BPM_MAX,
            lambda v, d=deck: self._on_tempo(d, v), theme.ACCENT)
        row += 1
        widgets["noise"], widgets["noise_var"] = self._strip_slider(
            strip, row, "dj_noise", 0, 4,
            lambda v, d=deck: self._on_noise(d, v), theme.DANGER, width=2)
        return row + 1

    def _strip_part_editor(self, strip, widgets, deck, row):
        """パート選択 (M/B/R/S) と、そのパートの音色・長さ・音量・フィルター。"""
        widgets["part_btns"] = self._strip_glyph_row(
            strip, row, "dj_part_label", lambda i, d=deck: self._focus_part(d, i))
        row += 1
        sliders = (
            ("part_tone", "lbl_tone", 0, 100, self._on_part_tone),
            ("part_gate", "lbl_gate", 10, 100, self._on_part_gate),
            ("part_volume", "lbl_volume", 0, 100, self._on_part_volume),
            ("filter", "dj_filter", 0, 100, self._on_filter),
        )
        for name, label_key, lo, hi, handler in sliders:
            widgets[name], widgets[f"{name}_var"] = self._strip_slider(
                strip, row, label_key, lo, hi,
                lambda v, d=deck, h=handler: h(d, v), theme.ACCENT)
            row += 1
        return row

    def _strip_toggles(self, strip, widgets, deck, row):
        """ループ固定のチェックと、KILL (パート消音)。"""
        hold_var = tk.BooleanVar(value=False)
        widgets["hold_var"] = hold_var
        tk.Checkbutton(
            strip, text=t("dj_hold"), variable=hold_var,
            command=lambda d=deck, v=hold_var: self.app.dj_set_hold(d, v.get()),
            font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.TEXT,
            selectcolor=theme.BTN_BG, activebackground=theme.PANEL,
            activeforeground=theme.TEXT, highlightthickness=0, bd=0,
            takefocus=0, cursor="hand2").grid(row=row, column=1, sticky="w",
                                              pady=(4, 2))
        row += 1
        widgets["kill"] = self._strip_glyph_row(
            strip, row, "dj_kill", lambda i, d=deck: self.app.dj_kill(d, i))
        return row + 1

    def _strip_foot(self, strip, deck, row):
        """生成 (新しいフレーズ) と SYNC (もう一方へテンポ・キーを合わせる)。"""
        foot = tk.Frame(strip, bg=theme.PANEL)
        foot.grid(row=row, column=0, columnspan=2, pady=(6, 0))
        self.app._button(foot, t("dj_roll"), lambda d=deck: self.app.dj_roll(d),
                         accent=True).pack(side="left", padx=2)
        self.app._button(foot, t("dj_sync"),
                         lambda d=deck: self.app.dj_sync(d)).pack(side="left", padx=2)

    def _draw_platter(self, canvas, color, letter):
        """ターンテーブルの円盤を描く。"""
        c = PLATTER // 2
        canvas.create_oval(c - R_OUTER, c - R_OUTER, c + R_OUTER, c + R_OUTER,
                           fill="#0a0a0a", outline=theme.PANEL_EDGE, width=2)
        for r in range(R_LABEL + 8, R_OUTER, 12):
            canvas.create_oval(c - r, c - r, c + r, c + r, outline="#1c1c1c")
        glow = canvas.create_oval(c - R_OUTER, c - R_OUTER, c + R_OUTER, c + R_OUTER,
                                  outline=color, width=2)
        canvas.create_oval(c - R_LABEL, c - R_LABEL, c + R_LABEL, c + R_LABEL,
                           fill=color, outline="#0a0a0a", width=2)
        # センターラベルはデッキ記号のみ。曲調名を入れると円に収まらず欠けるので、
        # 名前はディスク下のラベルに任せる。
        label_text = canvas.create_text(c, c, text=letter, fill=theme.KEY_TEXT,
                                        font=(theme.FONT_BOLD[0], 20, "bold"))
        marks = [canvas.create_line(c, c, c, c, fill="#e8e8e8", width=3)
                 for _ in range(2)]
        dots = [canvas.create_oval(0, 0, 0, 0, fill=theme.PLAYHEAD, outline="")
                for _ in range(2)]
        canvas.create_oval(c - 4, c - 4, c + 4, c + 4, fill="#c0c0c0", outline="")
        return {"glow": glow, "label_text": label_text, "marks": marks, "dots": dots}

    # ---- 中央 (共通操作) ----

    def _build_mixer(self):
        """中央のミキサー (クロスフェーダー・録音・履歴) を作る。"""
        mix = tk.Frame(self.console, bg=theme.PANEL, padx=12, pady=10,
                       highlightbackground=theme.PANEL_EDGE, highlightthickness=1)
        self.console.add(mix)

        self.play_btn = self.app._button(mix, t("dj_play"), self.app.dj_play, accent=True)
        self.play_btn.configure(font=theme.FONT_BOLD, padx=18, pady=5)
        self.play_btn.pack(pady=(0, 2))

        # 次のフレーズまでの小節数 (ループ固定中はその表示)。
        # 自動進行が動いていること・固定が効いていることを目で確かめられるようにする。
        self.next_var = tk.StringVar(value="")
        tk.Label(mix, textvariable=self.next_var, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.PLAYHEAD).pack(pady=(0, 8))

        tk.Label(mix, text=t("dj_crossfade"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack()
        cross_row = tk.Frame(mix, bg=theme.PANEL)
        cross_row.pack(pady=(2, 10))
        tk.Label(cross_row, text="A", font=theme.FONT_BOLD, bg=theme.PANEL,
                 fg=_deck_color("a")).pack(side="left")
        self.cross = tk.Scale(cross_row, from_=0, to=100, orient="horizontal",
                              length=130, showvalue=0, command=self._on_cross,
                              bg=theme.PANEL, troughcolor=theme.BTN_BG,
                              highlightthickness=0, bd=0, sliderlength=18, width=12,
                              activebackground=theme.ACCENT)
        self.cross.set(0)
        self.cross.pack(side="left", padx=4)
        tk.Label(cross_row, text="B", font=theme.FONT_BOLD, bg=theme.PANEL,
                 fg=_deck_color("b")).pack(side="left")

        self.app._button(mix, t("dj_tap"), self.app.dj_tap).pack()
        # 今流している音をその場で ★ / パターンへ (履歴から探さずに残せる)
        keep_row = tk.Frame(mix, bg=theme.PANEL)
        keep_row.pack(pady=(8, 0))
        self.app._button(keep_row, t("dj_fav_now"),
                         self.app.dj_toggle_favorite).pack(side="left", padx=2)
        self.app._button(keep_row, t("dj_keep_now"),
                         self.app.dj_keep).pack(side="left", padx=2)
        # セット録音 (鳴っているミックスをそのまま WAV に)
        self.rec_btn = self.app._button(mix, t("dj_record"), self.app.dj_record_toggle)
        self.rec_btn.pack(pady=(8, 0))

    # ---- 履歴 / お気に入り ----

    def _build_log(self):
        """流したフレーズの履歴と、★ お気に入りを左右に並べる。

        どちらの行も「呼び戻す (デッキ A / B へ)」「★」「パターンへ保存」ができる。
        表示しているのはフレーズを決める種 (曲調・キー・テンポ・音色) だけなので、
        押せばいつでも同じフレーズが決定論的に再生成される。
        """
        wrap = tk.Frame(self.frame, bg=theme.BG)
        wrap.pack(side="top", fill="both", expand=True, anchor="w", padx=6, pady=(8, 0))
        self.log_lists = {}
        self._log_canvas = {}
        clear = {"history": self.app.dj_clear_history,
                 "favorites": self.app.dj_clear_favorites}
        for kind, title in (("history", "dj_history"), ("favorites", "dj_favorites")):
            box = tk.Frame(wrap, bg=theme.PANEL, padx=8, pady=6,
                           highlightbackground=theme.PANEL_EDGE, highlightthickness=1)
            box.pack(side="left", fill="both", expand=True, padx=(0, 8))
            head = tk.Frame(box, bg=theme.PANEL)
            head.pack(fill="x", pady=(0, 4))
            tk.Label(head, text=t(title), font=theme.FONT_BOLD, bg=theme.PANEL,
                     fg=theme.TEXT_DIM, anchor="w").pack(side="left")
            btn = tk.Button(head, text=t("dj_clear"), font=theme.FONT_SMALL,
                            relief="flat", bd=1, takefocus=0, cursor="hand2",
                            bg=theme.BTN_BG, fg=theme.TEXT, command=clear[kind])
            btn.pack(side="right")
            self.log_lists[kind] = self._scroll_list(box, kind)

    def _scroll_list(self, parent, kind):
        """縦スクロールする行の入れ物を作って返す。

        ディスクを大きく取っているぶん DJ タブは背が高い。ウィンドウが低くても
        古い履歴に手が届くよう、一覧側をスクロールさせて逃がす。
        """
        holder = tk.Frame(parent, bg=theme.PANEL)
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, bg=theme.PANEL, highlightthickness=0,
                           height=LOG_ROWS * LOG_ROW_H)
        bar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")

        rows = tk.Frame(canvas, bg=theme.PANEL)
        window = canvas.create_window(0, 0, window=rows, anchor="nw")
        rows.bind("<Configure>",
                  lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        # 行を横幅いっぱいに広げる (キャンバス内の窓は既定で中身の幅のまま)
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        self._log_canvas[kind] = canvas
        self._bind_wheel(canvas, canvas)
        return rows

    def _bind_wheel(self, widget, canvas):
        """widget とその子すべてでホイール回転を canvas のスクロールに繋ぐ。

        行 (ラベルやボタン) の上でホイールを回してもスクロールできるよう、
        毎回一覧を組み直したあとに子まで束ねる。
        """
        widget.bind("<MouseWheel>",
                    lambda e, c=canvas: c.yview_scroll(-e.delta // 120, "units"))
        for child in widget.winfo_children():
            self._bind_wheel(child, canvas)

    def sync_log(self, history, favorites):
        """履歴・お気に入りの一覧を作り直す (行数が少ないので毎回組み直す)。"""
        for kind, entries in (("history", history), ("favorites", favorites)):
            rows = self.log_lists[kind]
            for child in rows.winfo_children():
                child.destroy()
            if not entries:
                tk.Label(rows, text=t("dj_log_empty"), font=theme.FONT_SMALL,
                         bg=theme.PANEL, fg=theme.TEXT_DIM,
                         anchor="w").pack(fill="x", pady=1)
            else:
                for entry in entries:        # 全件出す (入り切らない分はスクロール)
                    self._log_row(rows, entry, favorites)
            self._bind_wheel(rows, self._log_canvas[kind])   # 行の上でも回せるように

    def _log_row(self, parent, entry, favorites):
        """履歴/お気に入りの 1 行を作る。"""
        row = tk.Frame(parent, bg=theme.PANEL)
        row.pack(fill="x", pady=1)
        deck_key = DECK_KEYS[max(0, min(1, entry.get("deck", 0)))]
        tk.Label(row, text=deck_key.upper(), font=theme.FONT_BOLD, width=2,
                 bg=theme.PANEL, fg=_deck_color(deck_key)).pack(side="left")

        starred = dj_core.is_favorite(favorites, entry)
        # 呼び戻しは「→A」「→B」。先頭のデッキ記号と見分けがつくようにする。
        for text, command, tip in (
                ("★" if starred else "☆", lambda e=entry: self.app.dj_toggle_favorite(e),
                 "dj_tip_fav"),
                ("→A", lambda e=entry: self.app.dj_recall(e, 0), "dj_tip_recall_a"),
                ("→B", lambda e=entry: self.app.dj_recall(e, 1), "dj_tip_recall_b"),
                ("💾", lambda e=entry: self.app.dj_keep(e), "dj_tip_keep")):
            btn = tk.Button(row, text=text, font=theme.FONT_SMALL, width=3, relief="flat",
                            bd=1, takefocus=0, cursor="hand2", command=command,
                            bg=theme.BTN_BG,
                            fg=theme.ACCENT if text == "★" else theme.TEXT)
            btn.bind("<Enter>", lambda e, k=tip: self.app.set_status(t(k)))  # 役割を状況に表示
            btn.pack(side="left", padx=1)
        tk.Label(row, text=self.app.dj_entry_label(entry), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT, anchor="w").pack(side="left", padx=(6, 0))

    # ---- スクラッチ ----

    def _mouse_angle(self, event):
        """円盤の中心から見たマウスの角度。"""
        c = PLATTER // 2
        return math.degrees(math.atan2(event.y - c, event.x - c))

    def _on_platter_press(self, key, event):
        self._grab = {"key": key, "angle": self._mouse_angle(event),
                      "moved": False, "started": False}

    def _on_platter_motion(self, key, event):
        """円盤をドラッグ中 — 回した量をスクラッチへ渡す。"""
        grab = self._grab
        if not grab or grab["key"] != key:
            return
        angle = self._mouse_angle(event)
        delta = angle_diff(angle, grab["angle"])
        grab["angle"] = angle
        if not grab["started"]:
            grab["started"] = True
            self.app.dj_scratch_start(DECK_KEYS.index(key))
        grab["moved"] = True
        self.deck_angle[key] = (self.deck_angle[key] + delta) % 360
        self._place_marks(key, self.deck_angle[key], key == self._active_key, 0.4)
        self.app.dj_scratch_move(DECK_KEYS.index(key), delta)

    def _on_platter_release(self, key, event):
        """円盤から手を離した。"""
        grab = self._grab
        self._grab = None
        if not grab:
            return
        if grab["moved"]:
            self.app.dj_scratch_end(DECK_KEYS.index(key))
        else:
            self.app.dj_roll(DECK_KEYS.index(key))     # タップ = 生成

    # ---- ウィジェットのコールバック ----

    def _on_cross(self, value):
        if not self._syncing:
            self.app.dj_set_crossfade(int(float(value)))

    def _on_mood(self, deck, combo):
        """曲調セレクタが変わった。"""
        if self._syncing:
            return
        index = combo.current()
        if 0 <= index < len(SCALE_IDS):
            self.app.dj_set_scale(deck, SCALE_IDS[index])

    def _on_key(self, deck, combo):
        """キーセレクタが変わった。"""
        if self._syncing:
            return
        index = combo.current()
        if 0 <= index < len(KEY_NAMES):
            self.app.dj_set_key(deck, index)

    def _on_sound(self, deck, combo):
        """音色セレクタが変わった。"""
        if self._syncing:
            return
        index = combo.current()
        if 0 <= index < len(theme.SOUND_IDS):
            self.app.dj_set_sound(deck, theme.SOUND_IDS[index])

    def _on_tempo(self, deck, value):
        """テンポつまみが動いた。"""
        key = DECK_KEYS[deck]
        self.decks[key]["tempo_var"].set(str(int(float(value))))
        if not self._syncing:
            self.app.dj_set_tempo(deck, int(float(value)))

    def _on_noise(self, deck, value):
        """ノイズつまみが動いた。"""
        key = DECK_KEYS[deck]
        self.decks[key]["noise_var"].set(str(int(float(value))))
        if not self._syncing:
            self.app.dj_set_noise(deck, int(float(value)))

    def _focus_part(self, deck, wave):
        """音色・長さスライダーが編集するパートを切り替える (音は変えない)。"""
        key = DECK_KEYS[deck]
        self._part_focus[key] = wave
        self.app._update_dj_decks()      # スライダーを選んだパートの値へ合わせる

    def _on_part_tone(self, deck, value):
        """パートの質感つまみが動いた。"""
        key = DECK_KEYS[deck]
        self.decks[key]["part_tone_var"].set(str(int(float(value))))
        if not self._syncing:
            self.app.dj_set_part_tone(deck, self._part_focus[key], int(float(value)))

    def _on_part_gate(self, deck, value):
        """パートの長さつまみが動いた。"""
        key = DECK_KEYS[deck]
        self.decks[key]["part_gate_var"].set(str(int(float(value))))
        if not self._syncing:
            self.app.dj_set_part_gate(deck, self._part_focus[key], int(float(value)))

    def _on_part_volume(self, deck, value):
        """パートの音量つまみが動いた。"""
        key = DECK_KEYS[deck]
        self.decks[key]["part_volume_var"].set(str(int(float(value))))
        if not self._syncing:
            self.app.dj_set_part_volume(deck, self._part_focus[key], int(float(value)))

    def _on_filter(self, deck, value):
        """フィルターつまみが動いた。"""
        key = DECK_KEYS[deck]
        self.decks[key]["filter_var"].set(str(int(float(value))))
        if not self._syncing:
            self.app.dj_set_filter(deck, int(float(value)))

    # ---- app からの更新 ----

    def sync_deck(self, key, deck_state, name, active):
        """デッキ 1 台ぶんの表示・つまみを状態に合わせる。"""
        self._syncing = True
        try:
            widgets = self.decks[key]
            widgets["name"].set(name)
            widgets["seed"].set(t("dj_seed", seed=deck_state["seed"]))
            scale_id = deck_state["scale"]
            if scale_id in SCALE_IDS:
                widgets["mood"].current(SCALE_IDS.index(scale_id))
            widgets["key"].current(max(0, min(len(KEY_NAMES) - 1, deck_state["key"])))
            if deck_state["sound"] in theme.SOUND_IDS:
                widgets["sound"].current(theme.SOUND_IDS.index(deck_state["sound"]))
            widgets["tempo"].set(deck_state["bpm"])
            widgets["noise"].set(deck_state["noise"])
            widgets["filter"].set(deck_state["filter"])
            widgets["tempo_var"].set(str(deck_state["bpm"]))
            widgets["noise_var"].set(str(deck_state["noise"]))
            widgets["filter_var"].set(str(deck_state["filter"]))
            # パートごとの音色・長さ・音量: 選択中のパートの値をスライダーへ
            focus = self._part_focus[key]
            tone = deck_state["tones"][focus]
            gate = deck_state["gates"][focus]
            volume = deck_state["volumes"][focus]
            widgets["part_tone"].set(tone)
            widgets["part_gate"].set(gate)
            widgets["part_volume"].set(volume)
            widgets["part_tone_var"].set(str(tone))
            widgets["part_gate_var"].set(str(gate))
            widgets["part_volume_var"].set(str(volume))
            for i, btn in enumerate(widgets["part_btns"]):
                on = (i == focus)
                btn.configure(bg=theme.ACCENT if on else theme.BTN_BG,
                              fg=theme.KEY_TEXT if on else theme.PART_COLORS[i],
                              relief="sunken" if on else "flat")
            widgets["hold_var"].set(bool(deck_state["hold"]))
            for i, btn in enumerate(widgets["kill"]):
                if i in deck_state["muted"]:
                    btn.configure(bg=theme.DANGER, fg=theme.KEY_TEXT, relief="sunken")
                else:
                    btn.configure(bg=theme.BTN_BG, fg=theme.PART_COLORS[i],
                                  relief="flat")
            plat = self.platters[key]
            plat["canvas"].itemconfigure(
                plat["glow"], width=4 if active else 2,
                outline=plat["color"] if active else theme.PANEL_EDGE)
            if active:
                self._active_key = key
        finally:
            self._syncing = False

    def sync_crossfade(self, active):
        """クロスフェーダーの位置を今のデッキに合わせる。"""
        self._syncing = True
        try:
            self.cross.set(0 if active == 0 else 100)
        finally:
            self._syncing = False

    def set_tempo(self, deck, bpm):
        """テンポ表示を更新する。"""
        key = DECK_KEYS[deck]
        self._syncing = True
        try:
            self.decks[key]["tempo"].set(bpm)
            self.decks[key]["tempo_var"].set(str(bpm))
        finally:
            self._syncing = False

    def set_play(self, playing):
        self.play_btn.configure(text=t("dj_stop") if playing else t("dj_play"))

    def sync_next(self, text):
        """次のフレーズまでの案内 (小節数 / 固定中) を表示する。"""
        if hasattr(self, "next_var"):
            self.next_var.set(text)

    def set_recording(self, recording):
        """録音ボタンの見た目を切り替える (録音中は赤く「■ 停止」)。"""
        if not hasattr(self, "rec_btn"):
            return
        if recording:
            self.rec_btn.configure(text=t("dj_record_stop"), bg=theme.DANGER,
                                   fg=theme.KEY_TEXT)
        else:
            self.rec_btn.configure(text=t("dj_record"), bg=theme.BTN_BG, fg=theme.TEXT)

    def update_spin(self, active_key, spinning, beat_level):
        """円盤の回転位置を更新する (再生位置に追従)。"""
        if spinning:
            self.deck_angle[active_key] = (self.deck_angle[active_key] + 11) % 360
        for key in DECK_KEYS:
            self._place_marks(key, self.deck_angle[key], key == active_key, beat_level)

    def _place_marks(self, key, angle_deg, active, beat_level):
        """円盤の目印を回転位置へ置き直す。"""
        plat = self.platters[key]
        canvas = plat["canvas"]
        c = PLATTER // 2
        base = math.radians(angle_deg)
        for i, (line, dot) in enumerate(zip(plat["marks"], plat["dots"])):
            theta = base + i * math.pi
            cos, sin = math.cos(theta), math.sin(theta)
            canvas.coords(line, c + R_MARK_IN * cos, c + R_MARK_IN * sin,
                          c + R_MARK_OUT * cos, c + R_MARK_OUT * sin)
            dx, dy = c + (R_MARK_OUT - 4) * cos, c + (R_MARK_OUT - 4) * sin
            canvas.coords(dot, dx - 5, dy - 5, dx + 5, dy + 5)
            canvas.itemconfigure(line, fill="#e8e8e8" if active else "#555555")
            canvas.itemconfigure(dot, fill=theme.PLAYHEAD if active else "#555555")
        if active:
            canvas.itemconfigure(plat["glow"], width=int(4 + beat_level * 6),
                                 outline=plat["color"])


def _deck_color(key):
    return theme.PART_COLORS[0] if key == "a" else theme.PART_COLORS[3]
