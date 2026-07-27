"""PicoSeq メインアプリ — 画面の組み立てと配線。

状態の変更は core.actions の純粋関数だけで行い、ここでは
「いつ呼ぶか」「何を描き直すか」「何を鳴らすか」だけを扱う。
"""

import random
import tempfile
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..core import actions
from ..core import dj as dj_core
from ..core.constants import (
    BPM_MAX,
    BPM_MIN,
    EMPTY_CELL,
    MAX_NOTES,
    PART_COUNT,
    PATTERN_COUNT,
    PITCH_MAX,
    PITCH_MIN,
    SAMPLE_RATE,
    SEED_MAX,
    SEED_MIN,
    WAVE_PULSE,
)
from ..core.history import History, record, redo, undo
from ..core.music import KEY_NAMES, SCALE_IDS, SCALES, note_name
from ..core.note import unpack_note
from ..core.phrase import count_notes, find_note_at
from ..core.constants import MAX_LAYERS
from ..core.project import layer_count, new_project, part_params, steps_of
from ..core.midiio import phrase_midi, song_midi
from ..core.renderer import (
    render_phrase,
    render_phrase_loop,
    render_preview,
    render_song,
    render_song_loop,
)
from ..core.schedule import phrase_ticks, samples_per_tick, song_ticks, tick_seconds
from ..core.serialize import LoadError, dumps, loads
from ..core.song import used_blocks
from ..core.wavio import wav_bytes
from . import i18n, storage, theme
from .i18n import t
from .help import HelpDialog
from .panel import DockPanel
from .dj_view import DJView
from .hum import HumDialog
from .photo import PhotoDialog, analyze_photo
from .playback import PlayClock, SoundPlayer, rotate_pcm
from .stream import create_stream
from .dj_control import DJMixin
from .flowbar import FlowBar
from .flowbar import group as flow_group
from .selftest import SelfTestMixin
from .tuning import LIVE_DEBOUNCE_MS, SURPRISE_BPM
from .roll_view import RollView
from .song_view import SongView



class PicoSeqApp(DJMixin, SelfTestMixin):
    def __init__(self, root, silent=False):
        self.root = root
        self.silent = silent
        self.project = new_project()
        self.history = History()
        self.part = 0       # 選択中のパート (波形 0..3)
        self.layer = 0      # 選択中のレイヤー (そのパート内)
        self.muted = set()  # 消音中の (wave, layer) の集合。再生・WAV に反映
        self.roll_zoom = 1.0  # ピアノロールの拡大率 (画面再構築後も保つ)
        self._fitting = False  # 操作パネルの高さ調整中 (再帰防止)
        self._fit_token = None  # 高さ合わせの予約
        self.selected_pattern = -1
        self._init_dj()
        self.tab = "phrase"

        self.player = SoundPlayer(silent=silent)
        # ストリーミング再生 (継ぎ目なしの乗り換え・効果音の重ね)。使えなければ従来のファイル再生へ。
        self.stream = create_stream(rate=SAMPLE_RATE)
        self.stream_ok = (not silent) and self.stream.open()
        self.clock = PlayClock()
        self.play_mode = None
        self.play_bpm = 120
        self.play_ticks = 1
        self.render_busy = False
        self._live_token = None      # 保留中のリアルタイム再レンダリング
        self._preview_cache = {}
        self._gesture = None
        self._drag_ctx = None
        self._syncing = False
        self._dirty = False          # 未保存の変更があるか
        self.theme_sound = self.project.sound  # 画面に適用中の音色パレット
        self.autosave_file = storage.autosave_path()
        self.saved_snapshot = dumps(self.project)

        settings = storage.load_settings()
        i18n.set_lang(settings.get("lang", "ja"))
        try:  # 前回の拡大率を復元 (0.5〜3.0)
            self.roll_zoom = min(3.0, max(0.5, float(settings.get("zoom", 1.0))))
        except (TypeError, ValueError):
            self.roll_zoom = 1.0

        theme.set_palette(self.project.sound)
        root.configure(bg=theme.BG)
        root.title(t("title"))
        self._build_ui()
        self._bind_keys()
        self.refresh_all()
        self.switch_tab("phrase")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        if not silent:
            self._tick_playhead()

    # ==============================
    # 状態遷移の入口
    # ==============================

    def commit(self, new_project, full=False) -> bool:
        """履歴に積んでから状態を置き換える (アンドゥ 1 単位)。"""
        if new_project is self.project:
            return False
        self.history = record(self.history, dumps(self.project))
        self.project = new_project
        self._mark_edit()
        if full:
            self.refresh_all()
        else:
            self.refresh_after_edit()
        return True

    def tweak(self, new_project) -> bool:
        """履歴に積まずに置き換える (スライダー等の連続操作用)。"""
        if new_project is self.project:
            return False
        self.project = new_project
        self._mark_edit()
        return True

    def begin_gesture(self):
        """連続操作の開始 (この時点の状態を 1 回だけ履歴に積む)。"""
        self._gesture = dumps(self.project)

    def end_gesture(self):
        if self._gesture is not None and dumps(self.project) != self._gesture:
            self.history = record(self.history, self._gesture)
            self._update_undo_buttons()
        self._gesture = None

    def undo_action(self, _event=None):
        result = undo(self.history, dumps(self.project))
        if not result:
            self.set_status(t("st_no_undo"))
            return
        self.history, snapshot = result
        self.project = loads(snapshot)
        if not self._ensure_theme():  # 音色をまたぐ場合は画面ごと作り直す
            self.refresh_all()
        self._update_title()
        self.set_status(t("st_undone"))

    def redo_action(self, _event=None):
        result = redo(self.history, dumps(self.project))
        if not result:
            self.set_status(t("st_no_redo"))
            return
        self.history, snapshot = result
        self.project = loads(snapshot)
        if not self._ensure_theme():
            self.refresh_all()
        self._update_title()
        self.set_status(t("st_redone"))

    def _mark_edit(self):
        """状態が変わったとき呼ばれる。演奏中なら再生へリアルタイム反映する。"""
        self._set_dirty(True)
        if self.play_mode:
            self.play_hint_var.set(t("live_reflect"))
            self._schedule_live_rerender()

    def _set_dirty(self, dirty: bool):
        """未保存フラグを更新し、変化したときだけタイトルに ● を出す。"""
        if dirty == self._dirty:
            return
        self._dirty = dirty
        if not self.silent:
            self.root.title((t("unsaved_prefix") if dirty else "") + t("title"))

    def _update_title(self):
        """保存済みの内容と比べて未保存表示を正確に合わせる (読込・元に戻す後)。"""
        self._set_dirty(dumps(self.project) != self.saved_snapshot)

    # ==============================
    # 画面の組み立て
    # ==============================

    def _build_ui(self):
        root = self.root

        # ---- ヘッダー: タイトル・タブ・テンポ・入出力 ----
        # 幅が足りなければ自動で折り返す (狭い画面でも保存・読込に手が届くように)。
        header = FlowBar(root, bg=theme.BG)
        header.pack(fill="x", padx=10, pady=(8, 4))

        header.add(tk.Label(header, text="PicoSeq", font=theme.FONT_TITLE,
                            bg=theme.BG, fg=theme.ACCENT))

        tabs = flow_group(header, theme.BG)
        self.tab_phrase_btn = self._button(tabs, t("tab_phrase"), lambda: self.switch_tab("phrase"))
        self.tab_pattern_btn = self._button(tabs, t("tab_pattern"), lambda: self.switch_tab("pattern"))
        self.tab_song_btn = self._button(tabs, t("tab_song"), lambda: self.switch_tab("song"))
        self.tab_dj_btn = self._button(tabs, t("tab_dj"), lambda: self.switch_tab("dj"))
        for btn in (self.tab_phrase_btn, self.tab_pattern_btn,
                    self.tab_song_btn, self.tab_dj_btn):
            btn.pack(side="left", padx=2)
        header.add(tabs)

        sound_cell = flow_group(header, theme.BG)
        tk.Label(sound_cell, text=t("lbl_sound"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 2))
        self.sound_box = ttk.Combobox(
            sound_cell, values=[i18n.sound_label(s) for s in theme.SOUND_IDS],
            state="readonly", width=13, font=theme.FONT_SMALL)
        self.sound_box.pack(side="left")
        self.sound_box.bind("<<ComboboxSelected>>", lambda e: self._on_sound_change())
        header.add(sound_cell)

        tempo_cell = flow_group(header, theme.BG)
        tk.Label(tempo_cell, text=t("lbl_tempo"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 2))
        self.bpm_scale = tk.Scale(
            tempo_cell, from_=BPM_MIN, to=BPM_MAX, orient="horizontal", length=110,
            showvalue=0, command=self._on_bpm_change, bg=theme.BG, fg=theme.TEXT,
            troughcolor=theme.PANEL, highlightthickness=0, bd=0,
            activebackground=theme.ACCENT,
        )
        self.bpm_scale.pack(side="left")
        self._attach_gesture(self.bpm_scale)
        self.bpm_var = tk.StringVar()
        tk.Label(tempo_cell, textvariable=self.bpm_var, font=theme.FONT_BOLD, width=4,
                 bg=theme.BG, fg=theme.TEXT).pack(side="left")
        header.add(tempo_cell)

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
        for label, command in ((t("btn_save"), self.do_save), (t("btn_load"), self.do_load),
                               (t("btn_export"), self.do_export), (t("btn_import"), self.do_import)):
            self._button(file_cell, label, command).pack(side="left", padx=2)
        header.add(file_cell, pin_right=True)

        # 言語切替 (日本語 / English) とヘルプ
        lang_cell = flow_group(header, theme.BG)
        tk.Label(lang_cell, text="🌐", font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left")
        self.lang_box = ttk.Combobox(
            lang_cell, values=[i18n.LANG_LABELS[l] for l in i18n.LANGS],
            state="readonly", width=8, font=theme.FONT_SMALL)
        self.lang_box.current(i18n.LANGS.index(i18n.get_lang()))
        self.lang_box.pack(side="left", padx=(2, 6))
        self.lang_box.bind("<<ComboboxSelected>>", lambda e: self._on_lang_change())
        self._button(lang_cell, t("btn_help"), self.show_help).pack(side="left", padx=2)
        header.add(lang_cell, pin_right=True)
        header.done()

        # ---- フレーズタブ (縦分割: 操作パネル / ピアノロール、各パネルは切り離し可) ----
        self.phrase_frame = tk.Frame(root, bg=theme.BG)
        self.phrase_paned = tk.PanedWindow(
            self.phrase_frame, orient="vertical", bg=theme.BG,
            sashwidth=7, sashrelief="raised", bd=0)
        self.phrase_paned.pack(fill="both", expand=True)

        self.phrase_ctrl_panel = DockPanel(self.phrase_paned, t("panel_transport"),
                                           self, minsize=110, stretch="never")
        self._build_phrase_controls(self.phrase_ctrl_panel.body)

        self.roll_panel = DockPanel(self.phrase_paned, t("panel_roll"), self, minsize=130)
        self._build_roll_zoom(self.roll_panel.header)
        self.roll = RollView(self.roll_panel.body, self)
        self.roll.frame.pack(fill="both", expand=True)

        # ---- ソングタブ (縦分割: 操作パネル / ソング構成) ----
        self.song_frame = tk.Frame(root, bg=theme.BG)
        self.song_paned = tk.PanedWindow(
            self.song_frame, orient="vertical", bg=theme.BG,
            sashwidth=7, sashrelief="raised", bd=0)
        self.song_paned.pack(fill="both", expand=True)

        self.song_ctrl_panel = DockPanel(self.song_paned, t("panel_transport"),
                                         self, minsize=80, stretch="never")
        self._build_song_controls(self.song_ctrl_panel.body)

        self.song_panel = DockPanel(self.song_paned, t("panel_song"), self, minsize=130)
        self.song_view = SongView(self.song_panel.body, self)
        self.song_view.frame.pack(fill="both", expand=True)

        # ---- パターンタブ ----
        self.pattern_frame = tk.Frame(root, bg=theme.PANEL, padx=10, pady=8,
                                      highlightbackground=theme.PANEL_EDGE,
                                      highlightthickness=1)
        ptop = tk.Frame(self.pattern_frame, bg=theme.PANEL)
        ptop.pack(fill="x", pady=(0, 4))
        tk.Label(ptop, text=t("panel_pattern"), font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.ACCENT).pack(side="left")
        self._button(ptop, t("pat_save_new"), self.save_new_pattern, accent=True
                     ).pack(side="right")
        tk.Label(self.pattern_frame, text=t("hint_pattern"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM, anchor="w", justify="left"
                 ).pack(fill="x", pady=(0, 6))
        self.pattern_list = tk.Frame(self.pattern_frame, bg=theme.PANEL)
        self.pattern_list.pack(fill="both", expand=True)

        # ---- DJ タブ ----
        self.dj_frame = tk.Frame(root, bg=theme.BG)
        self.dj_view = DJView(self.dj_frame, self)
        self.dj_view.frame.pack(fill="both", expand=True, padx=6, pady=6)

        # ---- ステータスバー ----
        status = tk.Frame(root, bg=theme.BG)
        status.pack(fill="x", side="bottom", padx=10, pady=(2, 6))
        self.status_var = tk.StringVar()
        tk.Label(status, textvariable=self.status_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM, anchor="w").pack(side="left", fill="x", expand=True)
        self.play_hint_var = tk.StringVar()
        tk.Label(status, textvariable=self.play_hint_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.ACCENT).pack(side="right", padx=8)
        self.cell_var = tk.StringVar()
        tk.Label(status, textvariable=self.cell_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM, width=22, anchor="e").pack(side="right")
        self.count_var = tk.StringVar()
        tk.Label(status, textvariable=self.count_var, font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="right", padx=8)

    def _build_phrase_controls(self, parent):
        """フレーズ操作パネルの中身 (生成・キー/曲調・パート/ミキサー・レイヤー)。"""
        inner = tk.Frame(parent, bg=theme.PANEL)
        inner.pack(fill="both", expand=True, padx=8, pady=6)

        # どの行も FlowBar (幅が足りなければ折り返す) にして、狭い画面でも
        # 書き出しや★登録が画面外へ消えないようにする。
        bar1 = FlowBar(inner, bg=theme.PANEL)
        bar1.pack(fill="x", pady=(0, 4))
        self.play_phrase_btn = self._button(bar1, t("btn_play"), lambda: self.toggle_play("phrase"), accent=True)
        bar1.add(self.play_phrase_btn)

        setup = flow_group(bar1, theme.PANEL)
        self.beats_box = self._combo(setup, t("lbl_beats"), [f"{n}/4" for n in range(2, 8)], self._on_beats_change, width=5)
        self.key_box = self._combo(setup, t("lbl_key"), list(KEY_NAMES), self._on_key_change, width=8)
        self.scale_box = self._combo(setup, t("lbl_scale"), self._scale_labels(), self._on_scale_change, width=20)
        bar1.add(setup)

        seed_cell = flow_group(bar1, theme.PANEL)
        tk.Label(seed_cell, text=t("lbl_seed"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 2))
        self.seed_var = tk.StringVar()
        self.seed_spin = tk.Spinbox(
            seed_cell, from_=SEED_MIN, to=SEED_MAX, textvariable=self.seed_var, width=7,
            font=theme.FONT, bg=theme.BTN_BG, fg=theme.TEXT, buttonbackground=theme.BTN_BG,
            insertbackground=theme.TEXT, relief="flat", command=self._on_seed_change,
        )
        self.seed_spin.pack(side="left")
        self.seed_spin.bind("<FocusOut>", lambda e: self._on_seed_change())
        self.seed_spin.bind("<Return>", lambda e: self.generate_from_seed_entry())
        bar1.add(seed_cell)

        make_cell = flow_group(bar1, theme.PANEL)
        self._button(make_cell, t("btn_auto"), self.generate_auto).pack(side="left", padx=2)
        self._button(make_cell, t("btn_surprise"), self.generate_surprise).pack(side="left", padx=2)
        self._button(make_cell, t("btn_hum"), self.hum_compose).pack(side="left", padx=2)
        self._button(make_cell, t("btn_photo"), self.photo_compose).pack(side="left", padx=2)
        self.arrange_btn = self._button(make_cell, t("btn_arrange"), self.arrange_accompaniment)
        self.arrange_btn.pack(side="left", padx=2)
        bar1.add(make_cell)

        # 出力・保存系は 1 行に収まるときだけ右寄せ (従来の見た目)
        out_cell = flow_group(bar1, theme.PANEL)
        self._button(out_cell, t("btn_wav"), lambda: self.do_export_wav("phrase")).pack(side="left", padx=2)
        self._button(out_cell, t("btn_midi"), lambda: self.do_export_midi("phrase")).pack(side="left", padx=2)
        self._button(out_cell, t("btn_register"), self.save_current_pattern).pack(side="left", padx=2)
        self._button(out_cell, t("btn_clear"), self.clear_phrase, danger=True).pack(side="left", padx=2)
        bar1.add(out_cell, pin_right=True)
        bar1.done()

        bar2 = FlowBar(inner, bg=theme.PANEL)
        bar2.pack(fill="x", pady=(0, 4))
        part_cell = flow_group(bar2, theme.PANEL)
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
        bar2.add(part_cell)

        self.tone_scale = self._slider_cell(bar2, t("lbl_tone"), 0, 100,
                                           self._on_tone_change)
        self.gate_scale = self._slider_cell(bar2, t("lbl_gate"), 10, 100,
                                            self._on_gate_change)
        self.volume_scale = self._slider_cell(bar2, t("lbl_volume"), 0, 100,
                                              self._on_volume_change)

        edit_cell = flow_group(bar2, theme.PANEL)
        self._button(edit_cell, "🔼", self.transpose_up).pack(side="left", padx=1)
        self._button(edit_cell, "🔽", self.transpose_down).pack(side="left", padx=1)
        self._button(edit_cell, t("btn_reverse"), self.reverse_phrase_action).pack(side="left", padx=(6, 2))
        bar2.add(edit_cell)
        bar2.done()

        # 消音とレイヤーは短いので 1 行にまとめる (ピアノロールへ縦幅を回す)
        bar3 = FlowBar(inner, bg=theme.PANEL)
        bar3.pack(fill="x")
        mute_cell = flow_group(bar3, theme.PANEL)
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
        bar3.add(mute_cell)

        # レイヤー選択バー (選択中パートの重ね) — 中身は _rebuild_layer_bar が作り直す
        self.layer_frame = flow_group(bar3, theme.PANEL)
        bar3.add(self.layer_frame)
        self._layer_bar = bar3
        bar3.done()

        # 折り返しで行数が変わったら、操作パネルを中身ぴったりに詰め直す
        for bar in (bar1, bar2, bar3):
            bar.on_reflow = lambda: self._schedule_fit(self.phrase_paned,
                                                       self.phrase_ctrl_panel)

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

    def _build_song_controls(self, parent):
        """ソング操作パネルの中身 (再生・生成・パターンパレット)。"""
        inner = tk.Frame(parent, bg=theme.PANEL)
        inner.pack(fill="both", expand=True, padx=8, pady=6)

        bar3 = tk.Frame(inner, bg=theme.PANEL)
        bar3.pack(fill="x", pady=(0, 6))
        self.play_song_btn = self._button(bar3, t("btn_play_song"), lambda: self.toggle_play("song"), accent=True)
        self.play_song_btn.pack(side="left", padx=(0, 12))
        self._button(bar3, t("btn_song_auto"), self.generate_song_auto).pack(side="left", padx=2)
        self._button(bar3, t("btn_clear_song"), self.clear_song, danger=True).pack(side="left", padx=(12, 2))
        self._button(bar3, t("btn_wav_song"), lambda: self.do_export_wav("song")).pack(side="left", padx=(12, 2))
        self._button(bar3, t("btn_midi_song"), lambda: self.do_export_midi("song")).pack(side="left", padx=2)

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

        # 配置中のパターン名を大きく表示 (どれを置いているか分かるように)
        placing = tk.Frame(inner, bg=theme.PANEL)
        placing.pack(fill="x", pady=(4, 0))
        self.placing_var = tk.StringVar()
        tk.Label(placing, textvariable=self.placing_var, font=theme.FONT_BOLD,
                 bg=theme.PANEL, fg=theme.ACCENT, anchor="w").pack(side="left")

    def _update_mute_buttons(self):
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
        if hasattr(self, "zoom_var"):
            self.zoom_var.set(f"{int(round(self.roll.zoom * 100))}%")

    def zoom_in(self):
        self.roll.zoom_in()
        self._update_zoom_label()

    def zoom_out(self):
        self.roll.zoom_out()
        self._update_zoom_label()

    def zoom_reset(self):
        self.roll.zoom_reset()
        self._update_zoom_label()

    def _button(self, parent, text, command, accent=False, danger=False):
        fg = theme.TEXT
        if danger:
            fg = theme.DANGER
        button = tk.Button(
            parent, text=text, command=command, font=theme.FONT,
            bg=theme.BTN_BG, fg=fg, activebackground=theme.BTN_ACTIVE,
            activeforeground=theme.TEXT, relief="flat", bd=1, padx=10, pady=3,
            takefocus=0, cursor="hand2",
        )
        if accent:
            button.configure(font=theme.FONT_BOLD, fg=theme.ACCENT)
        return button

    def _combo(self, parent, label, values, command, width):
        tk.Label(parent, text=label, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(8, 2))
        box = ttk.Combobox(parent, values=values, state="readonly", width=width,
                           font=theme.FONT_SMALL)
        box.pack(side="left")
        box.bind("<<ComboboxSelected>>", lambda e: command())
        return box

    def _attach_gesture(self, scale_widget):
        scale_widget.bind("<ButtonPress-1>", lambda e: self.begin_gesture(), add="+")
        scale_widget.bind("<ButtonRelease-1>", lambda e: self.end_gesture(), add="+")

    def _bind_keys(self):
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
        return event.widget.winfo_class() in ("Entry", "TEntry", "Spinbox", "TSpinbox", "TCombobox")

    def _on_space(self, event):
        if self._typing(event):
            return
        self.toggle_play(self.tab)
        return "break"

    def _on_digit(self, event, part):
        if self._typing(event):
            return
        self.select_part(part)

    def _on_tab_key(self, _event):
        nxt = (self.TABS.index(self.tab) + 1) % len(self.TABS)
        self.switch_tab(self.TABS[nxt])
        return "break"

    # ==============================
    # 画面の更新
    # ==============================

    def _scale_labels(self) -> list:
        """曲調セレクタの選択肢。フォト音階があれば末尾に加わる。"""
        labels = [i18n.scale_label(s, SCALES[s]["label"]) for s in SCALE_IDS]
        if self.project.custom_scale is not None:
            labels.append(t("photo_scale_label"))
        return labels

    def refresh_all(self):
        self._syncing = True
        try:
            p = self.project
            self.bpm_scale.set(p.bpm)
            self.bpm_var.set(str(p.bpm))
            self.beats_box.current(p.beats - 2)
            self.key_box.current(p.key)
            self.scale_box.configure(values=self._scale_labels())
            if p.scale == "photo":
                self.scale_box.current(len(SCALE_IDS))
            else:
                self.scale_box.current(SCALE_IDS.index(p.scale))
            self.sound_box.current(theme.SOUND_IDS.index(p.sound))
            self.seed_var.set(str(p.seed))
            self.layer = min(self.layer, layer_count(p, self.part) - 1)
            params = part_params(p, self.part, self.layer)
            self.tone_scale.set(params.tone)
            self.gate_scale.set(params.gate)
            self.volume_scale.set(params.volume)
        finally:
            self._syncing = False
        self._update_part_buttons()
        self._update_mute_buttons()
        self._update_zoom_label()
        self._rebuild_layer_bar()
        self.roll.rebuild()
        self.song_view.rebuild()
        self._update_palette()
        self._update_placing()
        self._rebuild_pattern_list()
        self._update_counts()
        self._update_undo_buttons()

    def refresh_after_edit(self):
        self.roll.redraw_notes()
        self.song_view.redraw_cells()
        self._update_palette()
        self._update_placing()
        self._update_counts()
        self._update_undo_buttons()

    def _update_part_buttons(self):
        for i, button in enumerate(self.part_buttons):
            color = theme.PART_COLORS[i]
            count = layer_count(self.project, i)
            suffix = f" ×{count}" if count > 1 else ""
            button.configure(text=f"{i + 1} {i18n.part_name(i)}{suffix}")
            if i == self.part:
                button.configure(bg=color, fg=theme.KEY_TEXT, relief="sunken")
            else:
                button.configure(bg=theme.BTN_BG, fg=color, relief="flat")
        self.wave_label_var.set(i18n.part_wave(self.part))

    def _rebuild_layer_bar(self):
        """選択中パートのレイヤー一覧を作り直す (＋追加 / 番号選択 / ✕削除)。"""
        for child in self.layer_frame.winfo_children():
            child.destroy()
        count = layer_count(self.project, self.part)
        color = theme.PART_COLORS[self.part]
        tk.Label(self.layer_frame, text=t("lbl_layers_of", part=i18n.part_name(self.part)),
                 font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.TEXT_DIM
                 ).pack(side="left", padx=(0, 6))
        for layer in range(count):
            btn = tk.Button(
                self.layer_frame, text=str(layer + 1), font=theme.FONT_SMALL,
                width=3, relief="sunken" if layer == self.layer else "raised", bd=1,
                bg=color if layer == self.layer else theme.BTN_BG,
                fg=theme.KEY_TEXT if layer == self.layer else theme.TEXT,
                takefocus=0, cursor="hand2",
                command=lambda k=layer: self.select_layer(k),
            )
            btn.pack(side="left", padx=(2, 0))
            muted = self.is_layer_muted(self.part, layer)
            mbtn = tk.Button(
                self.layer_frame, text="🔇" if muted else "🔊", font=theme.FONT_SMALL,
                relief="sunken" if muted else "flat", bd=1, padx=1, takefocus=0,
                cursor="hand2", bg=theme.DANGER if muted else theme.BTN_BG,
                fg=theme.KEY_TEXT if muted else theme.TEXT_DIM,
                command=lambda k=layer: self.toggle_layer_mute(self.part, k),
            )
            mbtn.pack(side="left", padx=(0, 3))
        if count < MAX_LAYERS:
            self._button(self.layer_frame, t("btn_add_layer"), self.add_layer_action
                         ).pack(side="left", padx=(6, 2))
        if self.layer > 0:
            self._button(self.layer_frame, t("btn_remove_layer", n=self.layer + 1),
                         self.remove_layer_action, danger=True).pack(side="left", padx=2)
        # 中身が変わって幅が伸び縮みするので、同じ行の折り返しを引き直す
        if getattr(self, "_layer_bar", None) is not None:
            self._layer_bar.refresh()

    def add_layer_action(self):
        new_project = actions.add_layer(self.project, self.part)
        if new_project is self.project:
            self.set_status(t("st_layer_max", max=MAX_LAYERS))
            return
        self.commit(new_project)
        self.layer = layer_count(new_project, self.part) - 1  # 追加したレイヤーを選ぶ
        self._sync_part_sliders()
        self._rebuild_layer_bar()
        self.roll.redraw_notes()
        self.set_status(t("st_layer_added", part=i18n.part_name(self.part), n=self.layer + 1))

    def remove_layer_action(self):
        if self.layer == 0:
            return
        target = self.layer
        self.commit(actions.remove_layer(self.project, self.part, target))
        self.layer = min(target, layer_count(self.project, self.part) - 1)
        self._sync_part_sliders()
        self._rebuild_layer_bar()
        self._update_part_buttons()
        self.roll.redraw_notes()
        self.set_status(t("st_layer_removed", n=target + 1))

    def _update_palette(self):
        for i, button in enumerate(self.pattern_buttons):
            pattern = self.project.patterns[i]
            if pattern.used:
                button.configure(bg=theme.PATTERN_COLORS[i], fg=theme.KEY_TEXT,
                                 state="normal",
                                 relief="sunken" if i == self.selected_pattern else "raised")
            else:
                button.configure(bg=theme.BTN_BG, fg=theme.TEXT_DIM,
                                 state="disabled", relief="flat")

    def _update_counts(self):
        p = self.project
        used = sum(1 for pattern in p.patterns if pattern.used)
        extra = t("counts_extra_photo") if p.progression is not None else ""
        self.count_var.set(t(
            "counts", notes=count_notes(p.phrase), max=MAX_NOTES,
            used=used, pats=PATTERN_COUNT, blocks=used_blocks(p.song), extra=extra))

    def _update_undo_buttons(self):
        pass  # ボタンは常時有効。押せないときはステータスで知らせる。

    def set_status(self, text):
        self.status_var.set(text)

    def show_cell_hint(self, pitch, step):
        beats = self.project.beats
        measure = step // (beats * 4) + 1
        beat = step % (beats * 4) // 4 + 1
        self.cell_var.set(t("cell_hint", note=note_name(pitch), measure=measure, beat=beat))

    TABS = ("phrase", "pattern", "song", "dj")

    def switch_tab(self, name, stop=True):
        if stop:
            self.stop_playback()
        self.tab = name
        frames = {"phrase": self.phrase_frame, "pattern": self.pattern_frame,
                  "song": self.song_frame, "dj": self.dj_frame}
        hints = {"phrase": t("hint_phrase"), "pattern": t("hint_pattern"),
                 "song": t("hint_song"), "dj": t("hint_dj")}
        for key, frame in frames.items():
            if key == name:
                frame.pack(fill="both", expand=True, padx=10, pady=4)
            else:
                frame.pack_forget()
        if name == "pattern":
            self._rebuild_pattern_list()
        elif name == "dj":
            self._refresh_dj()
        self.set_status(hints[name])
        on = dict(bg=theme.BTN_ON, fg=theme.BTN_ON_TEXT)
        off = dict(bg=theme.BTN_BG, fg=theme.TEXT)
        self.tab_phrase_btn.configure(**(on if name == "phrase" else off))
        self.tab_pattern_btn.configure(**(on if name == "pattern" else off))
        self.tab_song_btn.configure(**(on if name == "song" else off))
        self.tab_dj_btn.configure(**(on if name == "dj" else off))

    # ==============================
    # フレーズ編集 (RollView から呼ばれる)
    # ==============================

    def roll_press(self, pitch, step):
        """クリック位置に応じて 置く / 消す / 伸ばし開始。(スロット, 起点) を返す。

        既存音符の右端は「ドラッグで伸ばす」起点。ただしドラッグせずに
        離した場合は削除として扱う (roll_release で判定)。
        """
        project = self.project
        slot = find_note_at(project.phrase, pitch, step, self.part, self.layer)
        if slot == -1:
            new_project, new_slot = actions.place_note(project, pitch, step,
                                                       self.part, layer=self.layer)
            if new_slot == -1:
                self.set_status(t("st_notes_full", max=MAX_NOTES))
                return -1, -1
            self.commit(new_project)
            self._drag_ctx = {"mode": "new"}
            self.preview_note(pitch)
            return new_slot, step
        note = unpack_note(project.phrase[slot])
        if step == note.step + note.dur - 1:
            self.begin_gesture()  # 右端 → 伸ばしモード
            self._drag_ctx = {"mode": "edge", "slot": slot, "dur0": note.dur, "moved": False}
            return slot, note.step
        self.commit(actions.erase_note(project, slot))
        self._drag_ctx = None
        return -1, -1

    def roll_resize(self, slot, dur):
        context = self._drag_ctx
        if context and context.get("mode") == "edge" and dur != context["dur0"]:
            context["moved"] = True
        if self.tweak(actions.resize_note(self.project, slot, dur)):
            self.roll.redraw_notes()

    def roll_release(self):
        context = self._drag_ctx
        self._drag_ctx = None
        if context and context.get("mode") == "edge" and not context["moved"]:
            # 右端をクリックしただけ → 削除 (ドラッグしていない)
            self._gesture = None
            self.commit(actions.erase_note(self.project, context["slot"]))
            return
        self.end_gesture()

    def roll_erase(self, pitch, step):
        slot = find_note_at(self.project.phrase, pitch, step, self.part, self.layer)
        if slot != -1:
            self.commit(actions.erase_note(self.project, slot))

    def select_part(self, part):
        self.part = part
        self.layer = min(self.layer, layer_count(self.project, part) - 1)
        self._sync_part_sliders()
        self._update_part_buttons()
        self._rebuild_layer_bar()
        self.roll.redraw_notes()

    def select_layer(self, layer):
        self.layer = layer
        self._sync_part_sliders()
        self._rebuild_layer_bar()
        self.roll.redraw_notes()

    def mute_pairs(self) -> frozenset:
        """レンダラへ渡す消音集合 (wave, layer)。"""
        return frozenset(self.muted)

    def is_layer_muted(self, wave, layer) -> bool:
        return (wave, layer) in self.muted

    def is_part_muted(self, wave) -> bool:
        """パートの全レイヤーが消音されていれば True。"""
        count = layer_count(self.project, wave)
        return all((wave, layer) in self.muted for layer in range(count))

    def toggle_mute(self, wave):
        """パート全体の消音を切り替える (全レイヤーまとめて)。確定状態は変えない。"""
        count = layer_count(self.project, wave)
        if self.is_part_muted(wave):
            for layer in range(count):
                self.muted.discard((wave, layer))
            self.set_status(t("st_unmuted", part=i18n.part_name(wave)))
        else:
            for layer in range(count):
                self.muted.add((wave, layer))
            self.set_status(t("st_muted", part=i18n.part_name(wave)))
        self._after_mute_change(wave)

    def toggle_layer_mute(self, wave, layer):
        """特定レイヤーの消音を切り替える。"""
        if (wave, layer) in self.muted:
            self.muted.discard((wave, layer))
            self.set_status(t("st_layer_unmuted", part=i18n.part_name(wave), n=layer + 1))
        else:
            self.muted.add((wave, layer))
            self.set_status(t("st_layer_muted", part=i18n.part_name(wave), n=layer + 1))
        self._after_mute_change(wave)

    def _after_mute_change(self, wave):
        self._update_part_buttons()
        if hasattr(self, "mute_buttons"):
            self._update_mute_buttons()
        self._rebuild_layer_bar()   # レイヤーごとの 🔊/🔇 表示を更新
        self.roll.redraw_notes()
        # DJ 画面からの消音は DJ 側で即反映するので、汎用の再描画は走らせない
        if self.play_mode and self.tab != "dj":
            self._schedule_live_rerender()

    def _sync_part_sliders(self):
        params = part_params(self.project, self.part, self.layer)
        self._syncing = True
        try:
            self.tone_scale.set(params.tone)
            self.gate_scale.set(params.gate)
            self.volume_scale.set(params.volume)
        finally:
            self._syncing = False

    def preview_note(self, pitch):
        """鍵盤の試聴。ストリーミング再生なら演奏に重ねて鳴らせる。"""
        if self.silent:
            return
        if self.play_mode and not self.stream_ok:
            return                       # 重ねられない環境では演奏を邪魔しない
        params = part_params(self.project, self.part, self.layer)
        key = (self.part, pitch, params.tone, params.gate, self.project.sound)
        pcm = self._preview_cache.get(key)
        if pcm is None:
            pcm = render_preview(self.part, pitch, params.tone,
                                 params.gate, sound=self.project.sound)
            if len(self._preview_cache) > 48:
                self._preview_cache.clear()
            self._preview_cache[key] = pcm
        self._play_oneshot(pcm)

    def clear_phrase(self):
        if count_notes(self.project.phrase) == 0:
            return
        if self.confirm(t("ttl_clear"), t("st_clear_phrase_q")):
            self.commit(actions.clear_phrase(self.project))
            self.set_status(t("st_phrase_cleared"))

    def clear_part_action(self, wave):
        """指定パートの音符だけを消す (パートボタンの右クリック)。"""
        from ..core.phrase import active_notes
        if not any(n.wave == wave for _, n in active_notes(self.project.phrase)):
            self.set_status(t("st_part_empty", part=i18n.part_name(wave)))
            return
        self.commit(actions.clear_part(self.project, wave))
        self.set_status(t("st_part_cleared", part=i18n.part_name(wave)))

    def transpose_up(self, _event=None):
        self._transpose(12)

    def transpose_down(self, _event=None):
        self._transpose(-12)

    def _transpose(self, semitones):
        new_project = actions.transpose(self.project, semitones)
        if new_project is self.project:
            self.set_status(t("st_no_transpose"))
            return
        self.commit(new_project)
        self.set_status(t("st_transposed_up") if semitones > 0 else t("st_transposed_down"))

    def reverse_phrase_action(self):
        if count_notes(self.project.phrase) == 0:
            self.set_status(t("st_no_reverse"))
            return
        self.commit(actions.reverse_phrase(self.project))
        self.set_status(t("st_reversed"))

    def _progression_text(self) -> str:
        """今のフレーズで使われているコード進行を音名で返す (例: Am→F→C→G)。"""
        from picoseq.core.composer import chosen_progression
        from picoseq.core.music import progression_names
        p = self.project
        progression = chosen_progression(p.scale, p.seed, p.custom_scale, p.progression)
        return "→".join(progression_names(p.key, p.scale, progression, p.custom_scale))

    def generate_auto(self):
        """自動作成 — 毎回新しい「シード値」を選んで作る。番号は記録され再現できる。"""
        seed = random.randint(SEED_MIN, SEED_MAX)  # 番号選びだけ乱数。結果は project に記録される
        p = actions.set_seed(self.project, seed)
        self.commit(actions.generate_phrase(p))
        self._syncing = True
        try:
            self.seed_var.set(str(seed))
        finally:
            self._syncing = False
        self.set_status(t("st_auto_made", seed=seed, prog=self._progression_text()))

    def generate_from_seed_entry(self):
        """シード値の欄で Enter — その番号の曲を再現する。"""
        self._on_seed_change()
        self.commit(actions.generate_phrase(self.project))
        self.set_status(t("st_seed_reproduced", seed=self.project.seed,
                          prog=self._progression_text()))

    def generate_surprise(self):
        """サプライズ — 曲調・音色・テンポ・シードに加え、各パートの音色・長さも丸ごとランダムに。

        65 種類の曲調から思いがけない組み合わせに出会うための一発ボタン。
        テンポも、パートごとの音色 (パルス幅など) と長さ (ゲート) も振るので、毎回別物になる。
        """
        scale = random.choice(SCALE_IDS)
        sound = random.choice(theme.SOUND_IDS)
        bpm = random.randint(*SURPRISE_BPM)
        seed = random.randint(SEED_MIN, SEED_MAX)
        p = self.project
        # フォト音階は写真が要るので通常の曲調から選ぶ (SCALE_IDS は通常のみ)
        p = actions.set_scale(p, scale)
        p = actions.set_sound(p, sound)
        p = actions.set_bpm(p, bpm)
        p = actions.set_seed(p, seed)
        p = actions.generate_phrase(p)
        p = self._randomize_voicing(p)     # 各パートの音色・長さもランダムに
        self.commit(p, full=True)
        self._ensure_theme()  # 選ばれた音色に配色を合わせる
        from ..core.music import SCALES as _SCALES
        self.set_status(t("st_surprise",
                          scale=i18n.scale_label(scale, _SCALES[scale]["label"]),
                          sound=i18n.sound_label(sound), bpm=bpm, seed=seed,
                          prog=self._progression_text()))

    @staticmethod
    def _randomize_voicing(project):
        """各パート・各レイヤーの音色 (0..100) と長さ (10..100) をランダムに振る。

        音を決めるのは音符 (シード由来) のままで、質感だけを変える。極端すぎて
        鳴りにくくならないよう、長さは 25 以上に寄せる。
        """
        for wave in range(PART_COUNT):
            for layer in range(layer_count(project, wave)):
                project = actions.set_part_tone(project, wave,
                                                random.randint(0, 100), layer)
                project = actions.set_part_gate(project, wave,
                                                random.randint(25, 100), layer)
        return project

    def arrange_accompaniment(self):
        """盤面のメロディに合わせて他パート (ベース・サブ・リズム) を自動生成する。"""
        from ..core.arranger import has_only_melody, melody_notes
        if not melody_notes(self.project):
            self.set_status(t("st_no_melody"))
            return
        if not has_only_melody(self.project) and not self.confirm(
                t("ttl_arrange"), t("st_arrange_q")):
            return
        new_project = actions.arrange_accompaniment(self.project)
        self.commit(new_project)
        self.set_status(t("st_arranged"))

    def show_help(self, _event=None):
        HelpDialog(self)

    # ==============================
    # 鼻歌 (歌ってメロディを作る)
    # ==============================

    def hum_compose(self):
        """鼻歌ダイアログを開く。"""
        if self.silent:
            return
        HumDialog(self)

    def apply_hum_melody(self, notes):
        """聞き取ったメロディをメロディパートへ置く (他のパートは残す)。"""
        from ..core.constants import WAVE_PULSE
        from ..core.phrase import active_notes, build_phrase
        others = [n for _, n in active_notes(self.project.phrase)
                  if n.wave != WAVE_PULSE]
        buffer = build_phrase(list(notes) + others)
        self.commit(actions.update(self.project, phrase=buffer))
        self.switch_tab("phrase")
        self.select_part(0)
        self.set_status(t("st_hum_placed", n=len(notes)))

    # ==============================
    # フォト音階 (写真から音階を取り込む)
    # ==============================

    def photo_compose(self):
        """写真を選んで四角形を解析し、ダイアログで確認してから取り込む。"""
        if self.silent:
            return
        path = filedialog.askopenfilename(
            title=t("dlg_pick_photo"),
            filetypes=[(t("ft_image"), "*.png *.jpg *.jpeg *.bmp *.ppm"), (t("ft_all"), "*.*")])
        if not path:
            return
        self.set_status(t("st_analyzing_photo"))

        def work():
            return analyze_photo(path)

        def done(result):
            grid, quads, photo = result
            if not quads:
                self.alert(t("st_no_quads"))
                return
            self.set_status(t("st_quads_found", n=len(quads)))
            PhotoDialog(self, grid, quads, photo)

        self._run_bg(work, done)

    def apply_photo_scale(self, photo, generate: bool):
        """写真から抽出した音階を「📷 フォト音階」として曲調に追加する。

        キー・テンポ・シード値も写真由来の値で設定される。
        generate=True ならそのまま自動作成まで行う。1 回のアンドゥで戻せる。
        """
        p = actions.set_custom_scale(self.project, photo.key, photo.intervals,
                                     photo.bpm, photo.seed)
        if generate:
            p = actions.generate_phrase(p)
        self.commit(p, full=True)
        self.switch_tab("phrase")
        if generate:
            self.set_status(t("st_photo_composed"))
        else:
            self.set_status(t("st_photo_added"))

    # ==============================
    # パターンとソング
    # ==============================

    def pattern_label(self, slot: int) -> str:
        """パターンの表示名。名前があればそれ、無ければ F 番号。"""
        pattern = self.project.patterns[slot]
        return pattern.name if pattern.name else f"F{slot + 1}"

    def save_current_pattern(self):
        """フレーズ画面の ★登録 — 空きスロットへ現在のフレーズを保存する。"""
        slot = actions.free_pattern_slot(self.project)
        if slot == -1:
            self.alert(t("st_pat_no_room"))
            return
        self.commit(actions.save_pattern(self.project, slot))
        self.selected_pattern = slot
        self.set_status(t("st_pat_saved", n=slot + 1))

    def select_pattern(self, slot):
        if self.project.patterns[slot].used:
            self.selected_pattern = slot
            self._update_palette()
            self._update_placing()
            self.song_view.redraw_cells()  # 選択パターンのセル強調を更新

    # ---- パターン編集タブ ----

    def _rebuild_pattern_list(self):
        if not hasattr(self, "pattern_list"):
            return
        for child in self.pattern_list.winfo_children():
            child.destroy()
        for slot in range(PATTERN_COUNT):
            self._pattern_row(slot)

    def _pattern_row(self, slot):
        pattern = self.project.patterns[slot]
        row = tk.Frame(self.pattern_list, bg=theme.PANEL)
        row.pack(fill="x", pady=2)
        color = theme.PATTERN_COLORS[slot % len(theme.PATTERN_COLORS)]
        tk.Label(row, text=f"F{slot + 1}", font=theme.FONT_BOLD, width=4,
                 bg=color if pattern.used else theme.BTN_BG,
                 fg=theme.KEY_TEXT if pattern.used else theme.TEXT_DIM
                 ).pack(side="left", padx=(0, 8), ipady=2)
        if pattern.used:
            name = pattern.name or t("pat_unnamed")
            tk.Label(row, text=name, font=theme.FONT_BOLD, bg=theme.PANEL,
                     fg=theme.TEXT if pattern.name else theme.TEXT_DIM,
                     anchor="w", width=18).pack(side="left")
            tk.Label(row, text=t("pat_notes", n=count_notes(pattern.notes)),
                     font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.TEXT_DIM,
                     width=6, anchor="w").pack(side="left", padx=(6, 10))
            # コンパクトな操作ボタン (アイコン中心) で行幅を抑える
            self._row_button(row, "🗑", t("pat_del"),
                             lambda s=slot: self.delete_pattern_slot(s), danger=True)
            self._row_button(row, "⧉", t("pat_dup"),
                             lambda s=slot: self.duplicate_pattern_action(s))
            self._row_button(row, "🏷", t("pat_rename"),
                             lambda s=slot: self.rename_pattern_action(s))
            self._row_button(row, "▶", t("pat_play"),
                             lambda s=slot: self.play_pattern(s))
            self._row_button(row, t("pat_edit"), t("pat_edit"),
                             lambda s=slot: self.edit_pattern(s), accent=True)
        else:
            tk.Label(row, text=t("pat_empty"), font=theme.FONT, bg=theme.PANEL,
                     fg=theme.TEXT_DIM, anchor="w", width=24).pack(side="left")
            self._button(row, t("pat_save_here"), lambda s=slot: self.save_pattern_here(s)
                         ).pack(side="right", padx=2)

    def _row_button(self, parent, label, tip, command, accent=False, danger=False):
        """パターン行用の小さめボタン (右詰め)。label は文字/絵文字。"""
        fg = theme.ACCENT if accent else (theme.DANGER if danger else theme.TEXT)
        btn = tk.Button(parent, text=label, command=command,
                        font=theme.FONT_BOLD if accent else theme.FONT,
                        bg=theme.BTN_BG, fg=fg, activebackground=theme.BTN_ACTIVE,
                        relief="flat", bd=1, padx=6, pady=2, takefocus=0, cursor="hand2")
        btn.pack(side="right", padx=2)
        return btn

    def save_new_pattern(self):
        slot = actions.free_pattern_slot(self.project)
        if slot == -1:
            self.alert(t("st_pat_no_room"))
            return
        if count_notes(self.project.phrase) == 0:
            self.alert(t("st_pat_phrase_empty"))
            return
        self.commit(actions.save_pattern(self.project, slot))
        self.selected_pattern = slot
        self._rebuild_pattern_list()
        self.set_status(t("st_pat_saved", n=slot + 1))

    def save_pattern_here(self, slot):
        if count_notes(self.project.phrase) == 0:
            self.alert(t("st_pat_phrase_empty"))
            return
        self.commit(actions.save_pattern(self.project, slot))
        self.selected_pattern = slot
        self._rebuild_pattern_list()
        self.set_status(t("st_pat_saved", n=slot + 1))

    def edit_pattern(self, slot):
        if not self.project.patterns[slot].used:
            return
        self.commit(actions.load_pattern(self.project, slot))
        self.selected_pattern = slot
        self.switch_tab("phrase")
        self.set_status(t("st_pat_loaded", n=slot + 1))

    def rename_pattern_action(self, slot):
        pattern = self.project.patterns[slot]
        if not pattern.used:
            return
        name = self._ask_text(t("dlg_rename_title"), t("dlg_rename_prompt"), pattern.name)
        if name is None:
            return
        new_project = actions.rename_pattern(self.project, slot, name)
        if new_project is self.project:
            return
        self.commit(new_project)
        self._rebuild_pattern_list()
        final = self.project.patterns[slot].name
        if final:
            self.set_status(t("st_pat_renamed", n=slot + 1, name=final))
        else:
            self.set_status(t("st_pat_cleared_name", n=slot + 1))

    def duplicate_pattern_action(self, slot):
        new_project, dest = actions.duplicate_pattern(self.project, slot)
        if dest == -1:
            self.alert(t("st_pat_no_room"))
            return
        self.commit(new_project)
        self.selected_pattern = dest
        self._rebuild_pattern_list()
        self.set_status(t("st_pat_duplicated", src=slot + 1, dst=dest + 1))

    def delete_pattern_slot(self, slot):
        if not self.project.patterns[slot].used:
            return
        if self.confirm(t("ttl_delete"), t("st_delete_pat_q", n=slot + 1)):
            self.commit(actions.delete_pattern(self.project, slot))
            if self.selected_pattern == slot:
                self.selected_pattern = next(
                    (i for i, p in enumerate(self.project.patterns) if p.used), -1)
            self._rebuild_pattern_list()

    def play_pattern(self, slot):
        pattern = self.project.patterns[slot]
        if not pattern.used or self.silent:
            return
        if self.play_mode and not self.stream_ok:
            return                       # 重ねられない環境では演奏中は試聴しない
        temp = actions.update(self.project, phrase=pattern.notes)
        self._play_oneshot(render_phrase(temp, mute=self.mute_pairs()))
        self.set_status(t("st_pat_previewing", n=slot + 1, label=self.pattern_label(slot)))

    def _ask_text(self, title, prompt, initial=""):
        """1 行テキストを尋ねる小さなダイアログ。OK で文字列、キャンセルで None。"""
        if self.silent:
            return None
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=theme.BG)
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        tk.Label(win, text=prompt, font=theme.FONT, bg=theme.BG, fg=theme.TEXT
                 ).pack(padx=18, pady=(16, 4))
        var = tk.StringVar(value=initial)
        entry = tk.Entry(win, textvariable=var, font=theme.FONT, width=30,
                         bg=theme.BTN_BG, fg=theme.TEXT, insertbackground=theme.TEXT,
                         relief="flat")
        entry.pack(padx=18, pady=4)
        result = {"value": None}

        def ok():
            result["value"] = var.get()
            win.destroy()

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=(8, 16))
        self._button(bar, t("ok"), ok, accent=True).pack(side="left", padx=6)
        self._button(bar, t("cancel"), win.destroy).pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())
        win.after(10, lambda: (entry.focus_set(), entry.select_range(0, "end")))
        self.root.wait_window(win)
        return result["value"]

    def _update_placing(self):
        if hasattr(self, "placing_var"):
            if self.selected_pattern == -1:
                self.placing_var.set(t("song_placing_none"))
            else:
                self.placing_var.set(t("song_placing",
                                       label=self.pattern_label(self.selected_pattern)))

    def song_click(self, track, block):
        if self.selected_pattern == -1:
            self.set_status(t("st_pick_pattern_first"))
            return
        self.commit(actions.toggle_song_cell(self.project, track, block, self.selected_pattern))

    def song_erase(self, track, block):
        self.commit(actions.erase_song_cell(self.project, track, block))

    def show_song_hint(self, track, block):
        """マス目に触れたら、そこにあるパターン名をステータスに出す。"""
        from ..core.song import get_cell
        pid = get_cell(self.project.song, track, block)
        if pid == EMPTY_CELL:
            self.cell_var.set(t("song_cell_empty", track=track + 1, block=block + 1))
        else:
            self.cell_var.set(t("song_cell_hint", track=track + 1, block=block + 1,
                                label=self.pattern_label(pid)))

    def clear_song_hint(self):
        self.cell_var.set("")

    def _on_palette_hover(self, slot):
        """パレットのボタンに触れたら、その中身の名前を出す (F番号だけでは分かりにくいので)。"""
        if self.project.patterns[slot].used:
            self.cell_var.set(t("palette_hint", n=slot + 1, label=self.pattern_label(slot)))

    def preview_selected_pattern(self):
        """ソング画面で、選択中のパターンをその場で 1 回試聴する。"""
        if self.selected_pattern == -1:
            self.set_status(t("st_preview_pick"))
            return
        self.play_pattern(self.selected_pattern)

    def generate_song_auto(self):
        """1 曲ぶんの自動作成 — 新しいシード値でパターンと構成を丸ごと作る。"""
        touched = (used_blocks(self.project.song) > 0
                   or any(p.used for p in self.project.patterns[:4]))
        if touched and not self.confirm(
                t("ttl_song_auto"), t("st_song_auto_q")):
            return
        seed = random.randint(SEED_MIN, SEED_MAX)
        p = actions.set_seed(self.project, seed)
        self.commit(actions.generate_song(p), full=True)
        self.selected_pattern = 1  # Aメロを選んでおく
        self._update_palette()
        self.set_status(t("st_song_made", seed=seed))

    def clear_song(self):
        if used_blocks(self.project.song) == 0:
            return
        if self.confirm(t("ttl_clear"), t("st_clear_song_q")):
            self.commit(actions.clear_song(self.project))

    # ==============================
    # DJ モード
    # ==============================

    def _play_oneshot(self, pcm):
        """効果音を 1 回鳴らす。ストリーミング再生なら音楽に重ねて鳴る。"""
        if self.silent:
            return
        if self.stream_ok:
            self.stream.play_oneshot(pcm)
        else:
            self.player.play_file(storage.write_play_wav("oneshot", wav_bytes(pcm)),
                                  loop=False)

    # ==============================
    # 再生
    # ==============================

    def toggle_play(self, mode):
        if self.play_mode == mode:
            self.stop_playback()
            return
        self.stop_playback()
        self.start_playback(mode)

    def _playable(self, mode) -> bool:
        if mode == "song" and used_blocks(self.project.song) == 0:
            self.set_status(t("st_song_empty"))
            return False
        if mode == "phrase" and count_notes(self.project.phrase) == 0:
            self.set_status(t("st_phrase_empty"))
            return False
        return True

    def _render_loop_pcm(self, mode, project) -> bytes:
        mute = self.mute_pairs()
        if mode == "phrase":
            return render_phrase_loop(project, mute=mute)
        return render_song_loop(project, mute=mute)

    def _loop_ticks(self, mode, project) -> int:
        return phrase_ticks(project) if mode == "phrase" else song_ticks(project)

    def start_playback(self, mode):
        if self.render_busy or self.silent or not self._playable(mode):
            return
        project = self.project
        button = self.play_phrase_btn if mode == "phrase" else self.play_song_btn
        button.configure(text=t("btn_preparing"))
        self.render_busy = True

        def work():
            return self._render_loop_pcm(mode, project)

        def done(pcm):
            self.render_busy = False
            self._begin_loop(pcm, mode, project.bpm,
                             self._loop_ticks(mode, project), offset_tick=0.0)
            self.play_hint_var.set("")
            self.set_status(t("st_looping"))

        self._run_bg(work, done, button)

    def _begin_loop(self, pcm, mode, bpm, ticks, offset_tick):
        """PCM をループ再生する。offset_tick から始まるよう回転して再生位置を合わせる。"""
        spt = samples_per_tick(bpm)
        offset_tick %= ticks
        offset_samples = int(offset_tick * spt)
        if offset_samples:
            pcm = rotate_pcm(pcm, offset_samples)
        if self.stream_ok:
            self.stream.set_loop(pcm)          # 送り続ける方式 (継ぎ目なしで乗り換えられる)
            duration = len(pcm) / 2 / SAMPLE_RATE
            self._dj_now = (pcm, bpm, ticks)
            self._dj_last_loops = self.stream.loops
            self._dj_last_switches = self.stream.switches
        else:
            wav = wav_bytes(pcm)
            path = storage.write_play_wav("play", wav)
            self.player.play_file(path, loop=True)
            duration = (len(wav) - 44) / 2 / SAMPLE_RATE
            self._dj_now = (path, bpm, ticks)  # スクラッチからの復帰用
        self.clock.start(duration, offset_seconds=offset_tick * tick_seconds(bpm))
        self.play_mode = mode
        self.play_bpm = bpm
        self.play_ticks = ticks
        self._dj_loop_count = 0
        self._dj_incoming = None
        self._sync_play_buttons()

    def _sync_play_buttons(self):
        self.play_phrase_btn.configure(
            text=t("btn_stop") if self.play_mode == "phrase" else t("btn_play"))
        self.play_song_btn.configure(
            text=t("btn_stop") if self.play_mode == "song" else t("btn_play_song"))
        if hasattr(self, "dj_view"):
            self.dj_view.set_play(self.play_mode == "phrase")

    def stop_playback(self):
        if self._live_token is not None:
            self.root.after_cancel(self._live_token)
            self._live_token = None
        if self._dj_render_token is not None:
            self.root.after_cancel(self._dj_render_token)
            self._dj_render_token = None
        self._dj_pending = None
        self._dj_incoming = None
        self.player.stop()
        if self.stream_ok:
            self.stream.stop()
        self.clock.stop()
        self.play_mode = None
        self.position_var.set("")
        self.play_hint_var.set("")
        self._sync_play_buttons()
        self.roll.set_playhead(None)
        self.song_view.set_playhead(None)

    # ---- 演奏中のリアルタイム反映 ----

    def _schedule_live_rerender(self):
        """編集をまとめて反映するため、少し遅らせて再レンダリングを予約する。"""
        if self.silent:
            return
        if self._live_token is not None:
            self.root.after_cancel(self._live_token)
        self._live_token = self.root.after(LIVE_DEBOUNCE_MS, self._fire_live_rerender)

    def _fire_live_rerender(self):
        self._live_token = None
        if not self.play_mode:
            return
        if self.render_busy:
            self._schedule_live_rerender()  # 前の描画中なら少し待って再試行
            return
        mode = self.play_mode
        if not self._still_playable(mode):
            self.stop_playback()
            self.set_status(t("st_stopped_empty"))
            return
        project = self.project
        snapshot = dumps(project)
        self.render_busy = True

        def work():
            return self._render_loop_pcm(mode, project)

        def done(pcm):
            self.render_busy = False
            if self.play_mode != mode:  # 途中で停止・タブ切替した
                return
            # 現在の再生位置 (旧テンポ基準) を新ループのステップへ写す
            pos = self.clock.position() or 0.0
            new_ticks = self._loop_ticks(mode, project)
            offset_tick = (pos / tick_seconds(self.play_bpm)) % new_ticks
            self._begin_loop(pcm, mode, project.bpm, new_ticks, offset_tick)
            if dumps(self.project) != snapshot:
                self._schedule_live_rerender()  # 描画中にさらに編集された

        self._run_bg(work, done)

    def _still_playable(self, mode) -> bool:
        if mode == "phrase":
            return count_notes(self.project.phrase) > 0
        return used_blocks(self.project.song) > 0

    def _tick_playhead(self):
        if self.play_mode:
            position = self.clock.position()
            if position is not None:
                tick = position / tick_seconds(self.play_bpm)
                tick = min(tick, self.play_ticks - 0.001)
                beats = self.project.beats
                measure = int(tick // (beats * 4)) + 1
                beat = int(tick % (beats * 4) // 4) + 1
                self.position_var.set(f"▶ {measure} : {beat}")
                if self.play_mode == "phrase":
                    self.roll.set_playhead(tick)
                else:
                    self.song_view.set_playhead(tick)
        if self.tab == "dj" and hasattr(self, "dj_view"):
            self._dj_spin_tick()
        self.root.after(33, self._tick_playhead)

    def _run_bg(self, work, done, button=None):
        """裏スレッドで work を実行し、終わったら UI スレッドで done を呼ぶ。"""
        box = {}

        def runner():
            try:
                box["result"] = work()
            except Exception as error:  # noqa: BLE001 - UI へ報告する
                box["error"] = error

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()

        def poll():
            if thread.is_alive():
                self.root.after(50, poll)
                return
            if "error" in box:
                self.render_busy = False
                if button is not None:
                    self.stop_playback()
                self.set_status(t("st_error", msg=box["error"]))
                return
            done(box["result"])

        poll()

    # ==============================
    # 入出力
    # ==============================

    def do_save(self):
        storage.save_text(self.autosave_file, dumps(self.project))
        self.saved_snapshot = dumps(self.project)
        self._set_dirty(False)
        self.set_status(t("st_saved", path=self.autosave_file))

    def do_load(self):
        text = storage.load_text(self.autosave_file)
        if text is None:
            self.set_status(t("st_no_savedata"))
            return
        self._load_text(text, t("st_loaded_from", path=self.autosave_file))

    def do_export(self):
        path = self._ask_save_path(t("dlg_export_project"), "picoseq_project.json",
                                   [(t("ft_project"), "*.json")])
        if not path:
            return
        storage.save_text(Path(path), dumps(self.project))
        self.set_status(t("st_exported", path=path))

    def do_import(self):
        path = None if self.silent else filedialog.askopenfilename(
            title=t("dlg_import_project"),
            filetypes=[(t("ft_project_json"), "*.json"), (t("ft_all"), "*.*")])
        if not path:
            return
        text = storage.load_text(Path(path))
        if text is None:
            self.alert(t("st_file_unreadable"))
            return
        self._load_text(text, t("st_imported_from", path=path))

    def _load_text(self, text, ok_message):
        try:
            project = loads(text)
        except LoadError as error:
            self.alert(str(error))
            return
        if not self.confirm(t("ttl_load"), t("st_replace_q")):
            return
        self.stop_playback()
        self.project = project
        self.history = History()
        self.saved_snapshot = dumps(project)
        self.selected_pattern = next(
            (i for i, p in enumerate(project.patterns) if p.used), -1)
        if not self._ensure_theme():  # 別の音色で保存したデータなら配色も合わせる
            self.refresh_all()
        self._set_dirty(False)
        self.set_status(ok_message)

    def do_export_wav(self, mode):
        project = self.project
        if mode == "song" and used_blocks(project.song) == 0:
            self.alert(t("st_song_empty_export"))
            return
        if mode == "phrase" and count_notes(project.phrase) == 0:
            self.alert(t("st_phrase_empty_export"))
            return
        name = "picoseq_song.wav" if mode == "song" else "picoseq_phrase.wav"
        path = self._ask_save_path(t("dlg_export_wav"), name, [(t("ft_wav"), "*.wav")])
        if not path:
            return
        self.set_status(t("st_exporting_wav"))

        mute = self.mute_pairs()

        def work():
            pcm = (render_song(project, mute=mute) if mode == "song"
                   else render_phrase(project, mute=mute))
            return wav_bytes(pcm)

        def done(wav):
            Path(path).write_bytes(wav)
            seconds = (len(wav) - 44) / 2 / SAMPLE_RATE
            self.set_status(t("st_wav_exported", path=path, sec=f"{seconds:.1f}"))

        self._run_bg(work, done)

    def do_export_midi(self, mode):
        """フレーズ／ソングを MIDI ファイルとして書き出す (DAW や楽譜ソフト用)。"""
        project = self.project
        if mode == "song" and used_blocks(project.song) == 0:
            self.alert(t("st_song_empty_export"))
            return
        if mode == "phrase" and count_notes(project.phrase) == 0:
            self.alert(t("st_phrase_empty_export"))
            return
        name = "picoseq_song.mid" if mode == "song" else "picoseq_phrase.mid"
        path = self._ask_save_path(t("dlg_export_midi"), name, [(t("ft_midi"), "*.mid")])
        if not path:
            return
        data = song_midi(project) if mode == "song" else phrase_midi(project)
        Path(path).write_bytes(data)
        self.set_status(t("st_midi_exported", path=path))

    def _ask_save_path(self, title, initial, filetypes):
        if self.silent:
            return None
        return filedialog.asksaveasfilename(
            title=title, initialfile=initial, defaultextension=filetypes[0][1][1:],
            filetypes=filetypes)

    # ==============================
    # ダイアログと終了
    # ==============================

    def confirm(self, title, message) -> bool:
        if self.silent:
            return True
        return messagebox.askyesno(title, message)

    def alert(self, message):
        self.set_status(message)
        if not self.silent:
            messagebox.showwarning(t("title"), message)

    def on_close(self):
        if dumps(self.project) != self.saved_snapshot and not self.silent:
            answer = messagebox.askyesnocancel(t("title"), t("st_close_save_q"))
            if answer is None:
                return
            if answer:
                self.do_save()
        self._save_window_settings()
        self.stop_playback()
        if self.stream_ok:
            self.stream.close()
        self.root.destroy()

    def _save_window_settings(self):
        """ウィンドウの大きさ・位置・分割サイズ・拡大率を設定ファイルへ保存する。"""
        if self.silent:
            return
        try:
            settings = storage.load_settings()
            settings["window"] = self.root.geometry()
            settings["zoom"] = round(self.roll_zoom, 4)
            sash = self._sash_y(self.phrase_paned)
            if sash is not None:
                settings["phrase_sash"] = sash
            settings["tab"] = self.tab
            storage.save_settings(settings)
        except Exception:  # noqa: BLE001 - 保存失敗は起動を妨げない
            pass

    def apply_saved_window(self) -> bool:
        """保存済みのウィンドウ設定を適用する。適用できたら True (既定サイズを使わない)。"""
        settings = storage.load_settings()
        geometry = settings.get("window")
        applied = False
        if isinstance(geometry, str) and geometry:
            try:
                self.root.geometry(geometry)
                applied = True
            except tk.TclError:
                pass
        if settings.get("tab") in self.TABS:
            self.switch_tab(settings["tab"], stop=False)
        self.root.update_idletasks()
        sash = settings.get("phrase_sash")
        if isinstance(sash, int):
            self._place_sash(self.phrase_paned, sash)
        return applied

    # ==============================
    # 自己診断 (--selftest)
    # ==============================

    def _on_bpm_change(self, value):
        if self._syncing:
            return
        self.tweak(actions.set_bpm(self.project, int(float(value))))
        self.bpm_var.set(str(self.project.bpm))

    def _on_beats_change(self):
        if self._syncing:
            return
        beats = self.beats_box.current() + 2
        if beats == self.project.beats:
            return
        if used_blocks(self.project.song) > 0:
            if not self.confirm(t("ttl_beats_change"), t("st_beats_change_q")):
                self._syncing = True
                self.beats_box.current(self.project.beats - 2)
                self._syncing = False
                return
        self.commit(actions.set_beats(self.project, beats), full=True)

    def _on_key_change(self):
        if self._syncing:
            return
        self.commit(actions.set_key(self.project, self.key_box.current()), full=True)

    def _on_scale_change(self):
        if self._syncing:
            return
        index = self.scale_box.current()
        scale_id = "photo" if index >= len(SCALE_IDS) else SCALE_IDS[index]
        self.commit(actions.set_scale(self.project, scale_id), full=True)

    def _on_sound_change(self):
        """音色セットの切替。音と一緒に画面の配色も変わる。"""
        if self._syncing:
            return
        sound = theme.SOUND_IDS[self.sound_box.current()]
        if not self.commit(actions.set_sound(self.project, sound)):
            return
        self._apply_theme(sound)
        self.set_status(t("st_sound_changed", label=i18n.sound_label(sound)))

    def _on_lang_change(self):
        """表示言語の切替。設定を保存し、文字列を反映するため画面を作り直す。"""
        lang = i18n.LANGS[self.lang_box.current()]
        if lang == i18n.get_lang():
            return
        i18n.set_lang(lang)
        settings = storage.load_settings()
        settings["lang"] = lang
        storage.save_settings(settings)
        self._rebuild_screen()
        self.set_status(t("st_lang_changed"))

    def _apply_theme(self, sound):
        """パレットを切り替えて画面全体を作り直す (曲データはそのまま)。"""
        theme.set_palette(sound)
        self.theme_sound = sound
        self._rebuild_screen()

    def _rebuild_screen(self):
        """今のパレット・言語で画面全体を作り直す (曲データ・再生・レイアウトはそのまま)。

        音色や言語を変えても、分割パネルの大きさ・切り離し状態が崩れないように
        作り直しの前後でレイアウトを保存・復元する。
        """
        layout = self._capture_layout()
        for child in self.root.winfo_children():
            child.destroy()
        self.root.configure(bg=theme.BG)
        self._build_ui()
        self.switch_tab(self.tab, stop=False)  # 再生は止めない
        self.refresh_all()
        self._restore_layout(layout)

    # ---- レイアウト (分割サイズ・切り離し) の保存と復元 ----

    def _paned_of(self, name):
        return {"phrase": self.phrase_paned, "song": self.song_paned}[name]

    def _panels(self) -> dict:
        return {"phrase_ctrl": self.phrase_ctrl_panel, "roll": self.roll_panel,
                "song_ctrl": self.song_ctrl_panel, "song": self.song_panel}

    def _sash_y(self, paned):
        try:
            if len(paned.panes()) >= 2:
                return int(paned.sash_coord(0)[1])
        except tk.TclError:
            pass
        return None

    def _place_sash(self, paned, y):
        if y is None:
            return
        try:
            if len(paned.panes()) >= 2:
                paned.sash_place(0, 1, int(y))
        except tk.TclError:
            pass

    def _capture_layout(self) -> dict:
        return {
            "phrase_sash": self._sash_y(self.phrase_paned),
            "song_sash": self._sash_y(self.song_paned),
            "detached": {name: panel.detached for name, panel in self._panels().items()},
        }

    def _restore_layout(self, layout):
        if not layout:
            return
        self.root.update_idletasks()
        self._place_sash(self.phrase_paned, layout.get("phrase_sash"))
        self._place_sash(self.song_paned, layout.get("song_sash"))
        for name, panel in self._panels().items():
            if layout.get("detached", {}).get(name):
                try:
                    panel.detach()
                except Exception:  # noqa: BLE001 - 表示環境依存。失敗してもドック状態でよい
                    pass

    def _ensure_theme(self) -> bool:
        """プロジェクトの音色と画面の配色がずれていたら合わせ直す。

        別の音色で保存したデータを読み込んだり、音色をまたいで元に戻したときに
        「音は変わったのに背景が古いまま」になるのを防ぐ。画面を作り直したら True。
        """
        if self.project.sound != self.theme_sound:
            self._apply_theme(self.project.sound)
            return True
        return False

    def _on_seed_change(self):
        if self._syncing:
            return
        try:
            seed = int(self.seed_var.get())
        except ValueError:
            seed = SEED_MIN
        self.tweak(actions.set_seed(self.project, seed))
        self._syncing = True
        self.seed_var.set(str(self.project.seed))
        self._syncing = False

    def _on_tone_change(self, value):
        if self._syncing:
            return
        self.tweak(actions.set_part_tone(self.project, self.part, int(float(value)),
                                         layer=self.layer))

    def _on_gate_change(self, value):
        if self._syncing:
            return
        self.tweak(actions.set_part_gate(self.project, self.part, int(float(value)),
                                         layer=self.layer))

    def _on_volume_change(self, value):
        if self._syncing:
            return
        self.tweak(actions.set_part_volume(self.project, self.part, int(float(value)),
                                           layer=self.layer))


def _load_demo(app):
    """デモ用に一曲ぶんの中身を入れる (スクリーンショット・体験用)。"""
    app.project = actions.set_seed(app.project, 42)
    app.project = actions.generate_phrase(app.project)
    app.project = actions.save_pattern(app.project, 0)
    app.project = actions.set_scale(app.project, "battle")
    app.project = actions.set_seed(app.project, 7)
    app.project = actions.generate_phrase(app.project)
    app.project = actions.save_pattern(app.project, 1)
    app.project = actions.rename_pattern(app.project, 0, "メインリフレイン")  # 長い名前 (省略表示の確認用)
    app.project = actions.rename_pattern(app.project, 1, "サビ")
    app.project = actions.load_pattern(app.project, 0)
    for track, block, pid in [(0, 0, 0), (0, 1, 0), (0, 2, 1), (0, 3, 1),
                              (1, 0, 0), (1, 2, 1), (3, 1, 1)]:
        app.project = actions.toggle_song_cell(app.project, track, block, pid)
    app.selected_pattern = 0
    app.history = History()
    app.refresh_all()
    import os
    if os.environ.get("PICOSEQ_DEMO_TAB") in ("song", "pattern", "dj"):
        app.switch_tab(os.environ["PICOSEQ_DEMO_TAB"])
        if os.environ["PICOSEQ_DEMO_TAB"] == "dj":
            app.dj_set_noise(0, 2)
            app.dj_set_part_tone(0, 3, 80)           # サブの音色を変えて見た目確認
            app.dj_set_part_gate(0, 3, 40)
            app.dj_view._focus_part(0, 3)            # サブを選択した状態で開く
            app.dj_view.update_spin("a", True, 0.8)  # 見た目確認用に回転位置をずらす
            for i, (scale, key, bpm) in enumerate(   # 履歴・お気に入りの見た目確認用
                    (("major", 0, 120), ("battle", 7, 150), ("minor", 3, 96),
                     ("dorian", 5, 128), ("majpent", 9, 110), ("blues", 2, 88))):
                app.dj_history.append(dj_core.make_entry(scale, key, bpm, "retro8",
                                                         0, 100 + i, deck=i % 2))
            app.dj_favorites = app.dj_history[1:3]
            app._refresh_dj_log()
    photo_path = os.environ.get("PICOSEQ_DEMO_PHOTO")
    if photo_path:
        def open_photo():
            grid, quads, photo = analyze_photo(photo_path)
            if quads:
                PhotoDialog(app, grid, quads, photo)
        app.root.after(400, open_photo)
    demo_sound = os.environ.get("PICOSEQ_DEMO_SOUND")
    if demo_sound in theme.SOUND_IDS:
        app.project = actions.set_sound(app.project, demo_sound)
        app._apply_theme(demo_sound)
    if os.environ.get("PICOSEQ_DEMO_HELP"):
        app.root.after(400, app.show_help)
    if os.environ.get("PICOSEQ_DEMO_MUTE"):
        app.toggle_mute(2)  # リズムを消音 (見た目確認用)
    if os.environ.get("PICOSEQ_DEMO_LAYERMUTE"):
        app.select_part(0)
        app.add_layer_action()          # メロディに 2 層目
        app.toggle_layer_mute(0, 1)     # 2 層目だけ消音 (レイヤーバー確認用)
    if os.environ.get("PICOSEQ_DEMO_DETACH"):
        app.root.after(500, app.roll_panel.detach)


def run(selftest: bool = False, demo: bool = False) -> int:
    root = tk.Tk()
    if selftest:
        root.withdraw()
    app = PicoSeqApp(root, silent=selftest)
    if demo:
        _load_demo(app)
    if selftest:
        ok = app.self_test()
        root.destroy()
        print("SELFTEST OK" if ok else "SELFTEST NG")
        return 0 if ok else 1
    root.update_idletasks()
    # ツールバー・DJ コンソールは幅が足りなければ折り返すので、狭くしても
    # 部品が画面外へ消えない。ターンテーブル 1 枚 (196px) と盤面が成立する
    # 最低限だけを下限にする。
    root.minsize(760, 560)
    # 通常起動は前回のウィンドウ設定を復元。demo や初回は画面に収まる大きさで開く。
    if demo or not app.apply_saved_window():
        width = min(root.winfo_reqwidth() + 8, root.winfo_screenwidth() - 60)
        height = min(root.winfo_reqheight() + 8, root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}+30+30")
    root.mainloop()
    return 0
