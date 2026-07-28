"""画面の組み立て — ウィジェットを作って配置するだけの層。

`PicoSeqApp` が継承する。ここには**作る**処理だけを置き、
何が起きたときに何を描き直すかは app.py 側に置く。
組み立ては一本の長い関数になりやすいので、画面の区画ごとに分けてある
(ヘッダー / フレーズタブ / ソングタブ / パターンタブ / DJ タブ / ステータスバー)。
"""

import tkinter as tk
from tkinter import ttk

from ..core.constants import (
    BPM_MAX, BPM_MIN, PATTERN_COUNT, SEED_MAX, SEED_MIN,
)
from ..core.music import KEY_NAMES
from ..core.project import layer_count
from . import i18n, theme
from .dj_view import DJView
from .flowbar import FlowBar
from .flowbar import group as flow_group
from .i18n import t
from .panel import DockPanel
from .roll_view import RollView
from .song_view import SongView


class UIBuilderMixin:
    """ウィジェットの組み立てとキー割り当て。"""

    # ---- 全体 ----

    def _build_ui(self):
        """画面全体を組み立てる。区画ごとの組み立てを順に呼ぶだけ。"""
        self._build_header(self.root)
        self._build_phrase_tab(self.root)
        self._build_song_tab(self.root)
        self._build_pattern_tab(self.root)
        self._build_dj_tab(self.root)
        self._build_status_bar(self.root)

    # ---- ヘッダー ----

    def _build_header(self, root):
        """タイトル・タブ・音色・テンポ・ファイル操作の 1 行。

        幅が足りなければ自動で折り返す (狭い画面でも保存・読込に手が届くように)。
        """
        header = FlowBar(root, bg=theme.BG)
        header.pack(fill="x", padx=10, pady=(8, 4))
        header.add(tk.Label(header, text="PicoSeq", font=theme.FONT_TITLE,
                            bg=theme.BG, fg=theme.ACCENT))
        header.add(self._build_tab_buttons(header))
        header.add(self._build_sound_picker(header))
        header.add(self._build_tempo_cell(header))

        self.position_var = tk.StringVar(value="")
        header.add(tk.Label(header, textvariable=self.position_var,
                            font=theme.FONT_BOLD, bg=theme.BG,
                            fg=theme.PLAYHEAD, width=12))

        # ファイル操作は 1 行に収まるときだけ右寄せ (従来の見た目)。
        # 折り返すときは左から流れるので、狭い画面でも必ず押せる。
        edit_cell = flow_group(header, theme.BG)
        self._button(edit_cell, "↩", self.undo_action).pack(side="left", padx=2)
        self._button(edit_cell, "↪", self.redo_action).pack(side="left", padx=2)
        header.add(edit_cell, pin_right=True)

        file_cell = flow_group(header, theme.BG)
        for label, command in ((t("btn_save"), self.do_save),
                               (t("btn_load"), self.do_load),
                               (t("btn_export"), self.do_export),
                               (t("btn_import"), self.do_import)):
            self._button(file_cell, label, command).pack(side="left", padx=2)
        header.add(file_cell, pin_right=True)

        header.add(self._build_lang_cell(header), pin_right=True)
        header.done()

    def _build_tab_buttons(self, header):
        """4 つのタブ切替ボタン。"""
        tabs = flow_group(header, theme.BG)
        self.tab_phrase_btn = self._button(tabs, t("tab_phrase"),
                                           lambda: self.switch_tab("phrase"))
        self.tab_pattern_btn = self._button(tabs, t("tab_pattern"),
                                            lambda: self.switch_tab("pattern"))
        self.tab_song_btn = self._button(tabs, t("tab_song"),
                                         lambda: self.switch_tab("song"))
        self.tab_dj_btn = self._button(tabs, t("tab_dj"),
                                       lambda: self.switch_tab("dj"))
        for btn in (self.tab_phrase_btn, self.tab_pattern_btn,
                    self.tab_song_btn, self.tab_dj_btn):
            btn.pack(side="left", padx=2)
        return tabs

    def _build_sound_picker(self, header):
        """音色セットの選択欄 (曲全体の音の性格)。"""
        cell = flow_group(header, theme.BG)
        tk.Label(cell, text=t("lbl_sound"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 2))
        self.sound_box = ttk.Combobox(
            cell, values=[i18n.sound_label(s) for s in theme.SOUND_IDS],
            state="readonly", width=13, font=theme.FONT_SMALL)
        self.sound_box.pack(side="left")
        self.sound_box.bind("<<ComboboxSelected>>", lambda e: self._on_sound_change())
        return cell

    def _build_tempo_cell(self, header):
        """テンポのスライダーと数値表示。"""
        cell = flow_group(header, theme.BG)
        tk.Label(cell, text=t("lbl_tempo"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 2))
        self.bpm_scale = tk.Scale(
            cell, from_=BPM_MIN, to=BPM_MAX, orient="horizontal", length=110,
            showvalue=0, command=self._on_bpm_change, bg=theme.BG, fg=theme.TEXT,
            troughcolor=theme.PANEL, highlightthickness=0, bd=0,
            activebackground=theme.ACCENT,
        )
        self.bpm_scale.pack(side="left")
        self._attach_gesture(self.bpm_scale)
        self.bpm_var = tk.StringVar()
        tk.Label(cell, textvariable=self.bpm_var, font=theme.FONT_BOLD, width=4,
                 bg=theme.BG, fg=theme.TEXT).pack(side="left")
        return cell

    def _build_lang_cell(self, header):
        """表示言語の切替とヘルプボタン。"""
        cell = flow_group(header, theme.BG)
        tk.Label(cell, text="🌐", font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left")
        self.lang_box = ttk.Combobox(
            cell, values=[i18n.LANG_LABELS[l] for l in i18n.LANGS],
            state="readonly", width=8, font=theme.FONT_SMALL)
        self.lang_box.current(i18n.LANGS.index(i18n.get_lang()))
        self.lang_box.pack(side="left", padx=(2, 6))
        self.lang_box.bind("<<ComboboxSelected>>", lambda e: self._on_lang_change())
        self._button(cell, t("btn_help"), self.show_help).pack(side="left", padx=2)
        return cell

    # ---- タブごとの中身 ----

    def _build_phrase_tab(self, root):
        """フレーズタブ (縦分割: 操作パネル / ピアノロール。各パネルは切り離し可)。"""
        self.phrase_frame = tk.Frame(root, bg=theme.BG)
        self.phrase_paned = tk.PanedWindow(
            self.phrase_frame, orient="vertical", bg=theme.BG,
            sashwidth=7, sashrelief="raised", bd=0)
        self.phrase_paned.pack(fill="both", expand=True)

        self.phrase_ctrl_panel = DockPanel(self.phrase_paned, t("panel_transport"),
                                           self, minsize=110, stretch="never")
        self._build_phrase_controls(self.phrase_ctrl_panel.body)

        self.roll_panel = DockPanel(self.phrase_paned, t("panel_roll"), self,
                                    minsize=130)
        self._build_roll_zoom(self.roll_panel.header)
        self.roll = RollView(self.roll_panel.body, self)
        self.roll.frame.pack(fill="both", expand=True)

    def _build_song_tab(self, root):
        """ソングタブ (縦分割: 操作パネル / ソング構成)。"""
        self.song_frame = tk.Frame(root, bg=theme.BG)
        self.song_paned = tk.PanedWindow(
            self.song_frame, orient="vertical", bg=theme.BG,
            sashwidth=7, sashrelief="raised", bd=0)
        self.song_paned.pack(fill="both", expand=True)

        self.song_ctrl_panel = DockPanel(self.song_paned, t("panel_transport"),
                                         self, minsize=80, stretch="never")
        self._build_song_controls(self.song_ctrl_panel.body)

        self.song_panel = DockPanel(self.song_paned, t("panel_song"), self,
                                    minsize=130)
        self.song_view = SongView(self.song_panel.body, self)
        self.song_view.frame.pack(fill="both", expand=True)

    def _build_pattern_tab(self, root):
        """パターン編集タブ (保存したパターンの一覧)。中身は後から作り直す。"""
        self.pattern_frame = tk.Frame(root, bg=theme.PANEL, padx=10, pady=8,
                                      highlightbackground=theme.PANEL_EDGE,
                                      highlightthickness=1)
        top = tk.Frame(self.pattern_frame, bg=theme.PANEL)
        top.pack(fill="x", pady=(0, 4))
        tk.Label(top, text=t("panel_pattern"), font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.ACCENT).pack(side="left")
        self._button(top, t("pat_save_new"), self.save_new_pattern,
                     accent=True).pack(side="right")
        tk.Label(self.pattern_frame, text=t("hint_pattern"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM, anchor="w", justify="left"
                 ).pack(fill="x", pady=(0, 6))
        self.pattern_list = tk.Frame(self.pattern_frame, bg=theme.PANEL)
        self.pattern_list.pack(fill="both", expand=True)

    def _build_dj_tab(self, root):
        """DJ タブ (ターンテーブル 2 枚)。"""
        self.dj_frame = tk.Frame(root, bg=theme.BG)
        self.dj_view = DJView(self.dj_frame, self)
        self.dj_view.frame.pack(fill="both", expand=True, padx=6, pady=6)

    def _build_status_bar(self, root):
        """最下段のステータスバー (状況・音符数・セル説明・再生の案内)。"""
        status = tk.Frame(root, bg=theme.BG)
        status.pack(fill="x", side="bottom", padx=10, pady=(2, 6))
        self.status_var = tk.StringVar()
        tk.Label(status, textvariable=self.status_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM, anchor="w"
                 ).pack(side="left", fill="x", expand=True)
        self.play_hint_var = tk.StringVar()
        tk.Label(status, textvariable=self.play_hint_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.ACCENT).pack(side="right", padx=8)
        self.cell_var = tk.StringVar()
        tk.Label(status, textvariable=self.cell_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM, width=22, anchor="e"
                 ).pack(side="right")
        self.count_var = tk.StringVar()
        tk.Label(status, textvariable=self.count_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="right", padx=8)

    # ---- フレーズ操作パネル (3 行) ----

    def _build_phrase_controls(self, parent):
        """フレーズ操作パネルの中身 (生成・キー/曲調・パート/ミキサー・レイヤー)。

        どの行も FlowBar (幅が足りなければ折り返す) にして、狭い画面でも
        書き出しや★登録が画面外へ消えないようにする。
        """
        inner = tk.Frame(parent, bg=theme.PANEL)
        inner.pack(fill="both", expand=True, padx=8, pady=6)
        bars = (self._build_make_bar(inner), self._build_mixer_bar(inner),
                self._build_mute_bar(inner))
        # 折り返しで行数が変わったら、操作パネルを中身ぴったりに詰め直す
        for bar in bars:
            bar.on_reflow = lambda: self._schedule_fit(self.phrase_paned,
                                                       self.phrase_ctrl_panel)

    def _build_make_bar(self, inner):
        """1 行目: 再生・拍子/キー/曲調・シード・生成・書き出し。"""
        bar = FlowBar(inner, bg=theme.PANEL)
        bar.pack(fill="x", pady=(0, 4))
        self.play_phrase_btn = self._button(bar, t("btn_play"),
                                            lambda: self.toggle_play("phrase"),
                                            accent=True)
        bar.add(self.play_phrase_btn)

        setup = flow_group(bar, theme.PANEL)
        self.beats_box = self._combo(setup, t("lbl_beats"),
                                     [f"{n}/4" for n in range(2, 8)],
                                     self._on_beats_change, width=5)
        self.key_box = self._combo(setup, t("lbl_key"), list(KEY_NAMES),
                                   self._on_key_change, width=8)
        self.scale_box = self._combo(setup, t("lbl_scale"), self._scale_labels(),
                                     self._on_scale_change, width=20)
        bar.add(setup)
        bar.add(self._build_seed_cell(bar))

        make_cell = flow_group(bar, theme.PANEL)
        self._button(make_cell, t("btn_auto"), self.generate_auto).pack(side="left", padx=2)
        self._button(make_cell, t("btn_surprise"), self.generate_surprise).pack(side="left", padx=2)
        self._button(make_cell, t("btn_photo"), self.photo_compose).pack(side="left", padx=2)
        self.arrange_btn = self._button(make_cell, t("btn_arrange"),
                                        self.arrange_accompaniment)
        self.arrange_btn.pack(side="left", padx=2)
        bar.add(make_cell)

        # 出力・保存系は 1 行に収まるときだけ右寄せ (従来の見た目)
        out_cell = flow_group(bar, theme.PANEL)
        self._button(out_cell, t("btn_wav"), lambda: self.do_export_wav("phrase")).pack(side="left", padx=2)
        self._button(out_cell, t("btn_midi"), lambda: self.do_export_midi("phrase")).pack(side="left", padx=2)
        self._button(out_cell, t("btn_register"), self.save_current_pattern).pack(side="left", padx=2)
        self._button(out_cell, t("btn_clear"), self.clear_phrase, danger=True).pack(side="left", padx=2)
        bar.add(out_cell, pin_right=True)
        bar.done()
        return bar

    def _build_seed_cell(self, bar):
        """シード値の入力欄 (Enter でその番号の曲を再現)。"""
        cell = flow_group(bar, theme.PANEL)
        tk.Label(cell, text=t("lbl_seed"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 2))
        self.seed_var = tk.StringVar()
        self.seed_spin = tk.Spinbox(
            cell, from_=SEED_MIN, to=SEED_MAX, textvariable=self.seed_var, width=7,
            font=theme.FONT, bg=theme.BTN_BG, fg=theme.TEXT,
            buttonbackground=theme.BTN_BG, insertbackground=theme.TEXT,
            relief="flat", command=self._on_seed_change,
        )
        self.seed_spin.pack(side="left")
        self.seed_spin.bind("<FocusOut>", lambda e: self._on_seed_change())
        self.seed_spin.bind("<Return>", lambda e: self.generate_from_seed_entry())
        return cell

    def _build_mixer_bar(self, inner):
        """2 行目: パート選択と、そのパートの質感・長さ・音量・移調。"""
        bar = FlowBar(inner, bg=theme.PANEL)
        bar.pack(fill="x", pady=(0, 4))

        part_cell = flow_group(bar, theme.PANEL)
        tk.Label(part_cell, text=t("lbl_part"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.part_buttons = []
        for i in range(4):
            btn = tk.Button(
                part_cell, text=f"{i + 1} {i18n.part_name(i)}", font=theme.FONT_SMALL,
                command=lambda i=i: self.select_part(i), relief="flat", bd=1,
                padx=8, pady=2, takefocus=0, cursor="hand2",
            )
            btn.bind("<Button-3>", lambda e, i=i: self.clear_part_action(i))  # 右クリックで消去
            btn.pack(side="left", padx=2)
            self.part_buttons.append(btn)
        self.wave_label_var = tk.StringVar()
        tk.Label(part_cell, textvariable=self.wave_label_var, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM, width=10).pack(side="left", padx=(4, 0))
        bar.add(part_cell)

        self.tone_scale = self._slider_cell(bar, t("lbl_tone"), 0, 100,
                                            self._on_tone_change)
        self.gate_scale = self._slider_cell(bar, t("lbl_gate"), 10, 100,
                                            self._on_gate_change)
        self.volume_scale = self._slider_cell(bar, t("lbl_volume"), 0, 100,
                                              self._on_volume_change)

        edit_cell = flow_group(bar, theme.PANEL)
        self._button(edit_cell, "🔼", self.transpose_up).pack(side="left", padx=1)
        self._button(edit_cell, "🔽", self.transpose_down).pack(side="left", padx=1)
        self._button(edit_cell, t("btn_reverse"), self.reverse_phrase_action
                     ).pack(side="left", padx=(6, 2))
        bar.add(edit_cell)
        bar.done()
        return bar

    def _build_mute_bar(self, inner):
        """3 行目: 消音とレイヤー。短いので 1 行にまとめ、縦幅を盤面へ回す。"""
        bar = FlowBar(inner, bg=theme.PANEL)
        bar.pack(fill="x")
        mute_cell = flow_group(bar, theme.PANEL)
        tk.Label(mute_cell, text=t("lbl_mute"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.mute_buttons = []
        for i in range(4):
            btn = tk.Button(
                mute_cell, text=f"{i + 1} {i18n.part_name(i)}", font=theme.FONT_SMALL,
                command=lambda i=i: self.toggle_mute(i), relief="flat", bd=1,
                padx=6, pady=2, takefocus=0, cursor="hand2",
            )
            btn.pack(side="left", padx=2)
            self.mute_buttons.append(btn)
        bar.add(mute_cell)

        # レイヤー選択バー (選択中パートの重ね) — 中身は _rebuild_layer_bar が作り直す
        self.layer_frame = flow_group(bar, theme.PANEL)
        bar.add(self.layer_frame)
        self._layer_bar = bar
        bar.done()
        return bar

    # ---- ソング操作パネル ----

    def _build_song_controls(self, parent):
        """ソング操作パネルの中身 (再生・生成・パターンパレット)。"""
        inner = tk.Frame(parent, bg=theme.PANEL)
        inner.pack(fill="both", expand=True, padx=8, pady=6)

        top = tk.Frame(inner, bg=theme.PANEL)
        top.pack(fill="x", pady=(0, 6))
        self.play_song_btn = self._button(top, t("btn_play_song"),
                                          lambda: self.toggle_play("song"),
                                          accent=True)
        self.play_song_btn.pack(side="left", padx=(0, 12))
        self._button(top, t("btn_song_auto"), self.generate_song_auto).pack(side="left", padx=2)
        self._button(top, t("btn_clear_song"), self.clear_song, danger=True).pack(side="left", padx=(12, 2))
        self._button(top, t("btn_wav_song"), lambda: self.do_export_wav("song")).pack(side="left", padx=(12, 2))
        self._button(top, t("btn_midi_song"), lambda: self.do_export_midi("song")).pack(side="left", padx=2)

        self._build_pattern_palette(inner)

        # 配置中のパターン名を大きく表示 (どれを置いているか分かるように)
        placing = tk.Frame(inner, bg=theme.PANEL)
        placing.pack(fill="x", pady=(4, 0))
        self.placing_var = tk.StringVar()
        tk.Label(placing, textvariable=self.placing_var, font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.ACCENT, anchor="w").pack(side="left")

    def _build_pattern_palette(self, inner):
        """ソング画面でマスに置くパターンを選ぶパレット。"""
        palette = tk.Frame(inner, bg=theme.PANEL)
        palette.pack(fill="x")
        tk.Label(palette, text=t("lbl_pattern"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.pattern_buttons = []
        for i in range(PATTERN_COUNT):
            btn = tk.Button(
                palette, text=f"F{i + 1}", font=theme.FONT_BOLD, width=3,
                command=lambda i=i: self.select_pattern(i), relief="flat", bd=1,
                takefocus=0, cursor="hand2",
            )
            btn.bind("<Enter>", lambda e, i=i: self._on_palette_hover(i))  # 名前を状況に表示
            btn.pack(side="left", padx=2)
            self.pattern_buttons.append(btn)
        # 選択中パターンをその場で試聴
        self._button(palette, t("btn_preview"), self.preview_selected_pattern
                     ).pack(side="left", padx=(10, 2))
        self._button(palette, t("song_go_patterns"),
                     lambda: self.switch_tab("pattern")).pack(side="right", padx=2)

    def _build_roll_zoom(self, header):
        """ピアノロール・パネルのタイトルバーに拡大縮小コントロールを載せる。"""
        small = dict(font=theme.FONT_SMALL, bg=theme.BTN_BG, fg=theme.TEXT,
                     activebackground=theme.BTN_ACTIVE, relief="flat", bd=0,
                     padx=6, pady=0, takefocus=0, cursor="hand2")
        tk.Button(header, text="＋", command=self.zoom_in, **small).pack(side="right", padx=(1, 4))
        self.zoom_var = tk.StringVar()
        tk.Button(header, textvariable=self.zoom_var, command=self.zoom_reset,
                  width=5, **small).pack(side="right", padx=1)
        tk.Button(header, text="－", command=self.zoom_out, **small).pack(side="right", padx=1)
        tk.Label(header, text=t("lbl_zoom"), font=theme.FONT_SMALL,
                 bg=theme.PANEL_EDGE, fg=theme.TEXT_DIM).pack(side="right", padx=(10, 2))

    # ---- 部品 ----

    def _button(self, parent, text, command, accent=False, danger=False):
        """アプリ共通の見た目のボタン。"""
        button = tk.Button(
            parent, text=text, command=command, font=theme.FONT,
            bg=theme.BTN_BG, fg=theme.DANGER if danger else theme.TEXT,
            activebackground=theme.BTN_ACTIVE, activeforeground=theme.TEXT,
            relief="flat", bd=1, padx=10, pady=3, takefocus=0, cursor="hand2",
        )
        if accent:
            button.configure(font=theme.FONT_BOLD, fg=theme.ACCENT)
        return button

    def _combo(self, parent, label, values, command, width):
        """ラベル付きの選択欄。"""
        tk.Label(parent, text=label, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(8, 2))
        box = ttk.Combobox(parent, values=values, state="readonly", width=width,
                           font=theme.FONT_SMALL)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: command())
        return box

    def _slider_cell(self, bar, label, lo, hi, command):
        """ラベル+スライダーを 1 単位にして FlowBar へ足す (折り返しで離れない)。"""
        cell = flow_group(bar, theme.PANEL)
        tk.Label(cell, text=label, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left")
        scale = tk.Scale(
            cell, from_=lo, to=hi, orient="horizontal", length=110, showvalue=0,
            command=command, bg=theme.PANEL, troughcolor=theme.BTN_BG,
            highlightthickness=0, bd=0, activebackground=theme.ACCENT,
        )
        scale.pack(side="left", padx=(2, 0))
        self._attach_gesture(scale)
        bar.add(cell)
        return scale

    def _attach_gesture(self, scale_widget):
        """スライダーのドラッグを 1 回の編集としてまとめる (履歴が細切れにならない)。"""
        scale_widget.bind("<ButtonPress-1>", lambda e: self.begin_gesture(), add="+")
        scale_widget.bind("<ButtonRelease-1>", lambda e: self.end_gesture(), add="+")

    # ---- パネルの高さ合わせ ----

    def _schedule_fit(self, paned, panel):
        """操作パネルの高さ合わせを予約する (複数バーの並べ直しを 1 回にまとめる)。

        並べ直しの途中で高さを読むと、まだ確定していないバーの分を取りこぼして
        パネルを小さく固定してしまい、中身が切れる。手が空いてから 1 度だけ行う。
        """
        if self._fit_token is not None:
            self.root.after_cancel(self._fit_token)
        self._fit_token = self.root.after_idle(
            lambda: self._fit_ctrl_pane(paned, panel))

    def _fit_ctrl_pane(self, paned, panel):
        """操作パネルを中身ぴったりの高さに詰めて、余りを盤面へ回す。

        切り離し中のパネルは対象外。中身より小さくは絶対にしない。
        """
        self._fit_token = None
        if getattr(panel, "detached", False) or self._fitting:
            return
        try:
            # panes() は widget 名 (文字列) を返すので str で比べる
            if str(panel.container) not in [str(p) for p in paned.panes()]:
                return
        except Exception:       # noqa: BLE001 - 画面再構築中は無視してよい
            return
        panel.body.update_idletasks()
        need = panel.body.winfo_reqheight() + panel.header.winfo_reqheight() + 4
        if need <= 1 or need == getattr(panel, "_fitted", -1):
            return
        self._fitting = True
        try:
            panel._fitted = need
            paned.paneconfigure(panel.container, height=need)
        except Exception:       # noqa: BLE001 - 表示環境依存。失敗しても致命的でない
            pass
        finally:
            self._fitting = False

    # ---- 表示の更新 (組み立てたウィジェットの見た目だけ) ----

    def _update_mute_buttons(self):
        """消音ボタンの表示を今の状態に合わせる (🔊 / 🔉 一部 / 🔇 全部)。"""
        for i, button in enumerate(self.mute_buttons):
            name = f"{i + 1} {i18n.part_name(i)}"
            if self.is_part_muted(i):
                button.configure(text=f"🔇 {name}", bg=theme.DANGER,
                                 fg=theme.KEY_TEXT, relief="sunken")
            elif any((i, layer) in self.muted
                     for layer in range(layer_count(self.project, i))):
                button.configure(text=f"🔉 {name}", bg=theme.BTN_BG,  # 一部レイヤーのみ
                                 fg=theme.DANGER, relief="raised")
            else:
                button.configure(text=f"🔊 {name}", bg=theme.BTN_BG,
                                 fg=theme.PART_COLORS[i], relief="flat")

    def _update_zoom_label(self):
        """拡大率の表示を更新する。"""
        if hasattr(self, "zoom_var"):
            self.zoom_var.set(f"{int(round(self.roll.zoom * 100))}%")

    def zoom_in(self):
        """ピアノロールを拡大する。"""
        self.roll.zoom_in()
        self._update_zoom_label()

    def zoom_out(self):
        """ピアノロールを縮小する。"""
        self.roll.zoom_out()
        self._update_zoom_label()

    def zoom_reset(self):
        """ピアノロールの拡大率を 100% へ戻す。"""
        self.roll.zoom_reset()
        self._update_zoom_label()

    # ---- キーボード ----

    def _bind_keys(self):
        """アプリ全体のキー割り当て。"""
        root = self.root
        root.bind_all("<space>", self._on_space)
        root.bind_all("<Escape>", lambda e: self.stop_playback())
        root.bind_all("<Control-z>", self.undo_action)
        root.bind_all("<Control-y>", self.redo_action)
        root.bind_all("<Control-Tab>", self._on_tab_key)
        root.bind_all("<F1>", self.show_help)
        root.bind_all("<Control-Up>", self.transpose_up)
        root.bind_all("<Control-Down>", self.transpose_down)
        for i in range(4):
            root.bind_all(str(i + 1), lambda e, i=i: self._on_digit(e, i))

    def _typing(self, event) -> bool:
        """文字入力中はグローバルキーを無効にする。"""
        return event.widget.winfo_class() in (
            "Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox")

    def _on_space(self, event):
        """Space — 今のタブの再生/停止。"""
        if self._typing(event):
            return
        self.toggle_play(self.tab)
        return "break"

    def _on_digit(self, event, part):
        """1〜4 — パート切替。"""
        if self._typing(event):
            return
        self.select_part(part)

    def _on_tab_key(self, _event):
        """Ctrl+Tab — 次のタブへ。"""
        nxt = (self.TABS.index(self.tab) + 1) % len(self.TABS)
        self.switch_tab(self.TABS[nxt])
        return "break"
