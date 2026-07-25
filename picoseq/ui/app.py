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
from .stream import StreamPlayer
from .roll_view import RollView
from .song_view import SongView

LIVE_DEBOUNCE_MS = 140  # 演奏中の編集をまとめて再レンダリングする間隔
DJ_RENDER_DEBOUNCE_MS = 120  # DJ: 次ループの事前レンダリングをまとめる間隔
DJ_ADVANCE_LOOPS = 4    # DJ: 何ループ流したら自動で次へ進むか (2小節×4 = 8小節)
DJ_SCRATCH_MS = 45      # スクラッチ音の最短間隔 (ミリ秒)
DJ_HISTORY_COMMIT_MS = 800  # つまみ操作を履歴へ確定するまでの待ち (デバウンス)
SURPRISE_BPM = (80, 180)    # サプライズのテンポの振れ幅 (極端に速い/遅いを避ける)


class PicoSeqApp:
    def __init__(self, root, silent=False):
        self.root = root
        self.silent = silent
        self.project = new_project()
        self.history = History()
        self.part = 0       # 選択中のパート (波形 0..3)
        self.layer = 0      # 選択中のレイヤー (そのパート内)
        self.muted = set()  # 消音中の (wave, layer) の集合。再生・WAV に反映
        self.roll_zoom = 1.0  # ピアノロールの拡大率 (画面再構築後も保つ)
        self.selected_pattern = -1
        # DJ モード: 2 デッキ。曲調・キー・音色・テンポ・ノイズ・フィルター・固定・消音は
        # すべてデッキごとに独立。
        self.dj_decks = [
            self._new_dj_deck(self.project.scale, self.project.seed,
                              self.project.bpm, self.project.key, self.project.sound),
            self._new_dj_deck(self.project.scale, 2,
                              self.project.bpm, self.project.key, self.project.sound),
        ]
        self.dj_active = 0
        self.dj_history = []        # 流したフレーズ (新しい順)。再起動では持ち越さない
        self._dj_hist_token = None  # つまみ操作を履歴へ確定するデバウンス
        self._dj_recording = False  # セット録音中か
        self.dj_favorites = dj_core.sanitize_entries(
            storage.load_settings().get("dj_favorites", []))   # ★ は設定へ永続化する
        self._dj_last_pos = 0.0
        self._dj_loop_count = 0     # 現フレーズを何ループ流したか
        self._dj_want_seed = self.dj_decks[0]["seed"]  # 次に流すフレーズのシード
        self._dj_pending = None     # 事前レンダリング済みの次ループ (path, bpm, ticks, project, seed)
        self._dj_swap_soon = False  # (フォールバック用) 次の境界で差し替える
        self._dj_apply_now = False  # 出来たら即その場で反映する
        self._dj_render_token = None
        self._dj_render_busy = False
        self._dj_taps = []          # タップテンポの打点 (monotonic 秒)
        self._dj_scratching = False
        self._dj_scratch_last = 0.0
        self._dj_scratch_cache = {}
        self._dj_now = None         # 現在鳴らしているループ スクラッチ復帰用
        self._dj_incoming = None    # 乗り換えを予約した内容 (切替完了時に反映)
        self._dj_last_loops = 0
        self._dj_last_switches = 0
        self.tab = "phrase"

        self.player = SoundPlayer(silent=silent)
        # ストリーミング再生 (継ぎ目なしの乗り換え・効果音の重ね)。使えなければ従来のファイル再生へ。
        self.stream = StreamPlayer(rate=SAMPLE_RATE)
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
        header = tk.Frame(root, bg=theme.BG)
        header.pack(fill="x", padx=10, pady=(8, 4))

        tk.Label(header, text="PicoSeq", font=theme.FONT_TITLE,
                 bg=theme.BG, fg=theme.ACCENT).pack(side="left")

        self.tab_phrase_btn = self._button(header, t("tab_phrase"), lambda: self.switch_tab("phrase"))
        self.tab_pattern_btn = self._button(header, t("tab_pattern"), lambda: self.switch_tab("pattern"))
        self.tab_song_btn = self._button(header, t("tab_song"), lambda: self.switch_tab("song"))
        self.tab_dj_btn = self._button(header, t("tab_dj"), lambda: self.switch_tab("dj"))
        self.tab_phrase_btn.pack(side="left", padx=(16, 2))
        self.tab_pattern_btn.pack(side="left", padx=2)
        self.tab_song_btn.pack(side="left", padx=2)
        self.tab_dj_btn.pack(side="left", padx=2)

        tk.Label(header, text=t("lbl_sound"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(14, 2))
        self.sound_box = ttk.Combobox(
            header, values=[i18n.sound_label(s) for s in theme.SOUND_IDS],
            state="readonly", width=13, font=theme.FONT_SMALL)
        self.sound_box.pack(side="left")
        self.sound_box.bind("<<ComboboxSelected>>", lambda e: self._on_sound_change())

        tk.Label(header, text=t("lbl_tempo"), font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(12, 2))
        self.bpm_scale = tk.Scale(
            header, from_=BPM_MIN, to=BPM_MAX, orient="horizontal", length=110,
            showvalue=0, command=self._on_bpm_change, bg=theme.BG, fg=theme.TEXT,
            troughcolor=theme.PANEL, highlightthickness=0, bd=0,
            activebackground=theme.ACCENT,
        )
        self.bpm_scale.pack(side="left")
        self._attach_gesture(self.bpm_scale)
        self.bpm_var = tk.StringVar()
        tk.Label(header, textvariable=self.bpm_var, font=theme.FONT_BOLD, width=4,
                 bg=theme.BG, fg=theme.TEXT).pack(side="left")

        self.position_var = tk.StringVar(value="")
        tk.Label(header, textvariable=self.position_var, font=theme.FONT_BOLD,
                 bg=theme.BG, fg=theme.PLAYHEAD, width=12).pack(side="left", padx=8)

        self._button(header, t("btn_help"), self.show_help).pack(side="right", padx=2)
        for label, command in ((t("btn_import"), self.do_import), (t("btn_export"), self.do_export),
                               (t("btn_load"), self.do_load), (t("btn_save"), self.do_save)):
            self._button(header, label, command).pack(side="right", padx=2)
        self._button(header, "↪", self.redo_action).pack(side="right", padx=(2, 10))
        self._button(header, "↩", self.undo_action).pack(side="right", padx=2)

        # 言語切替 (日本語 / English)
        self.lang_box = ttk.Combobox(
            header, values=[i18n.LANG_LABELS[l] for l in i18n.LANGS],
            state="readonly", width=8, font=theme.FONT_SMALL)
        self.lang_box.current(i18n.LANGS.index(i18n.get_lang()))
        self.lang_box.pack(side="right", padx=(2, 6))
        self.lang_box.bind("<<ComboboxSelected>>", lambda e: self._on_lang_change())
        tk.Label(header, text="🌐", font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="right")

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

        bar1 = tk.Frame(inner, bg=theme.PANEL)
        bar1.pack(fill="x", pady=(0, 6))
        self.play_phrase_btn = self._button(bar1, t("btn_play"), lambda: self.toggle_play("phrase"), accent=True)
        self.play_phrase_btn.pack(side="left", padx=(0, 12))
        self.beats_box = self._combo(bar1, t("lbl_beats"), [f"{n}/4" for n in range(2, 8)], self._on_beats_change, width=5)
        self.key_box = self._combo(bar1, t("lbl_key"), list(KEY_NAMES), self._on_key_change, width=8)
        self.scale_box = self._combo(bar1, t("lbl_scale"), self._scale_labels(), self._on_scale_change, width=20)

        tk.Label(bar1, text=t("lbl_seed"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(12, 2))
        self.seed_var = tk.StringVar()
        self.seed_spin = tk.Spinbox(
            bar1, from_=SEED_MIN, to=SEED_MAX, textvariable=self.seed_var, width=7,
            font=theme.FONT, bg=theme.BTN_BG, fg=theme.TEXT, buttonbackground=theme.BTN_BG,
            insertbackground=theme.TEXT, relief="flat", command=self._on_seed_change,
        )
        self.seed_spin.pack(side="left")
        self.seed_spin.bind("<FocusOut>", lambda e: self._on_seed_change())
        self.seed_spin.bind("<Return>", lambda e: self.generate_from_seed_entry())

        self._button(bar1, t("btn_auto"), self.generate_auto).pack(side="left", padx=(8, 2))
        self._button(bar1, t("btn_surprise"), self.generate_surprise).pack(side="left", padx=2)
        self._button(bar1, t("btn_hum"), self.hum_compose).pack(side="left", padx=2)
        self._button(bar1, t("btn_photo"), self.photo_compose).pack(side="left", padx=2)
        self.arrange_btn = self._button(bar1, t("btn_arrange"), self.arrange_accompaniment)
        self.arrange_btn.pack(side="left", padx=2)

        bar2 = tk.Frame(inner, bg=theme.PANEL)
        bar2.pack(fill="x", pady=(0, 6))
        tk.Label(bar2, text=t("lbl_part"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.part_buttons = []
        for i in range(4):
            btn = tk.Button(
                bar2, text=f"{i + 1} {i18n.part_name(i)}", font=theme.FONT_SMALL,
                command=lambda i=i: self.select_part(i), relief="flat", bd=1,
                padx=8, pady=2, takefocus=0, cursor="hand2",
            )
            btn.bind("<Button-3>", lambda e, i=i: self.clear_part_action(i))  # 右クリックで消去
            btn.pack(side="left", padx=2)
            self.part_buttons.append(btn)

        self.wave_label_var = tk.StringVar()
        tk.Label(bar2, textvariable=self.wave_label_var, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM, width=10).pack(side="left", padx=(4, 12))

        tk.Label(bar2, text=t("lbl_tone"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left")
        self.tone_scale = tk.Scale(
            bar2, from_=0, to=100, orient="horizontal", length=110, showvalue=0,
            command=self._on_tone_change, bg=theme.PANEL, troughcolor=theme.BTN_BG,
            highlightthickness=0, bd=0, activebackground=theme.ACCENT,
        )
        self.tone_scale.pack(side="left", padx=(2, 12))
        self._attach_gesture(self.tone_scale)

        tk.Label(bar2, text=t("lbl_gate"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left")
        self.gate_scale = tk.Scale(
            bar2, from_=10, to=100, orient="horizontal", length=110, showvalue=0,
            command=self._on_gate_change, bg=theme.PANEL, troughcolor=theme.BTN_BG,
            highlightthickness=0, bd=0, activebackground=theme.ACCENT,
        )
        self.gate_scale.pack(side="left", padx=2)
        self._attach_gesture(self.gate_scale)

        self._button(bar2, "🔼", self.transpose_up).pack(side="left", padx=(8, 1))
        self._button(bar2, "🔽", self.transpose_down).pack(side="left", padx=1)
        self._button(bar2, t("btn_reverse"), self.reverse_phrase_action).pack(side="left", padx=(6, 2))

        self._button(bar2, t("btn_register"), self.save_current_pattern).pack(side="right", padx=2)
        self._button(bar2, t("btn_clear"), self.clear_phrase, danger=True).pack(side="right", padx=2)
        self._button(bar2, t("btn_midi"), lambda: self.do_export_midi("phrase")).pack(side="right", padx=2)
        self._button(bar2, t("btn_wav"), lambda: self.do_export_wav("phrase")).pack(side="right", padx=(2, 8))

        # ミキサー行: パートごとのミュート + 盤面の拡大縮小
        bar_mix = tk.Frame(inner, bg=theme.PANEL)
        bar_mix.pack(fill="x", pady=(0, 6))
        tk.Label(bar_mix, text=t("lbl_mute"), font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.mute_buttons = []
        for i in range(4):
            btn = tk.Button(
                bar_mix, text=f"{i + 1} {i18n.part_name(i)}", font=theme.FONT_SMALL,
                command=lambda i=i: self.toggle_mute(i), relief="flat", bd=1,
                padx=6, pady=2, takefocus=0, cursor="hand2",
            )
            btn.pack(side="left", padx=2)
            self.mute_buttons.append(btn)

        # レイヤー選択バー (選択中パートの重ね)
        self.layer_frame = tk.Frame(inner, bg=theme.PANEL)
        self.layer_frame.pack(fill="x")

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

    @staticmethod
    def _new_dj_deck(scale, seed, bpm, key=0, sound="retro8"):
        """デッキ 1 台ぶんの設定。

        tones/gates = パートごと (メロディ/ベース/リズム/サブ) の音色と長さ。
        音色 0..100 (メロディならパルス波のデューティ比)、長さ 10..100。
        """
        return {"scale": scale, "key": key, "sound": sound, "seed": seed, "bpm": bpm,
                "noise": 0, "tones": [50, 50, 50, 50], "gates": [80, 80, 80, 80],
                "filter": 100, "hold": False, "muted": set()}

    def _dj_scale_label(self, scale_id) -> str:
        from ..core.music import SCALES
        if scale_id not in SCALES:
            scale_id = "major"
        return i18n.scale_label(scale_id, SCALES[scale_id]["label"])

    def _dj_deck(self, deck=None):
        return self.dj_decks[self.dj_active if deck is None else deck]

    def _dj_mute_pairs(self, deck=None):
        """デッキの KILL (パート単位) を、レンダラが使う (wave, layer) 集合にする。"""
        muted = self._dj_deck(deck)["muted"]
        pairs = set()
        for wave in muted:
            for layer in range(layer_count(self.project, wave)):
                pairs.add((wave, layer))
        return frozenset(pairs)

    def _refresh_dj(self):
        """DJ 画面のつまみ・表示を状態に合わせる (タブ表示時)。"""
        if not hasattr(self, "dj_view"):
            return
        self.dj_view.sync_crossfade(self.dj_active)
        self._update_dj_decks()
        self._refresh_dj_log()

    def _update_dj_decks(self):
        for i, key in enumerate(("a", "b")):
            deck = self.dj_decks[i]
            self.dj_view.sync_deck(key, deck, self._dj_scale_label(deck["scale"]),
                                   active=(i == self.dj_active))
        self.dj_view.set_play(self.play_mode == "phrase")

    def _dj_project_for(self, seed, deck=None):
        """デッキの設定 (曲調・キー・音色・テンポ・ノイズ) でループ Project を作る。"""
        deck = self._dj_deck(deck)
        p = actions.set_scale(self.project, deck["scale"])
        p = actions.set_key(p, deck["key"])
        p = actions.set_sound(p, deck["sound"])
        p = actions.set_bpm(p, deck["bpm"])
        p = actions.set_seed(p, seed)
        p = actions.generate_phrase(p)
        for wave in range(PART_COUNT):              # パートごとの音色・長さ (全レイヤーに適用)
            for layer in range(layer_count(p, wave)):
                p = actions.set_part_tone(p, wave, deck["tones"][wave], layer)
                p = actions.set_part_gate(p, wave, deck["gates"][wave], layer)
        if deck["noise"] > 0:
            from ..core.phrase import active_notes, build_phrase
            notes = [n for _, n in active_notes(p.phrase)]
            notes = dj_core.add_noise(notes, p.beats, deck["noise"], seed)
            p = actions.update(p, phrase=build_phrase(notes))
        return p

    # ---- 連続フロー: 事前レンダリング → ループ境界で継ぎ目なく差し替え ----

    def _dj_queue(self, seed=None, immediate=True):
        """操作の結果を作り直す。immediate なら出来次第その場で音に反映する。"""
        if seed is not None:
            self._dj_want_seed = seed
        self._dj_pending = None          # 古い準備は捨てる
        self._dj_apply_now = immediate
        self._dj_schedule_render()

    def _dj_prepare_auto(self):
        """継続フロー用に、新しいランダムシードで次フレーズを仕込む (継ぎ目で乗り換え)。"""
        self._dj_want_seed = random.randint(SEED_MIN, SEED_MAX)
        self._dj_apply_now = False
        self._dj_schedule_render()

    def _dj_apply_immediate(self, result):
        """出来上がったループを、今の再生位置を保ったまま即座に差し替える。"""
        path, pcm, bpm, ticks, project, seed = result
        self.project = project
        self.dj_decks[self.dj_active]["seed"] = seed
        old_duration = self.play_ticks * tick_seconds(self.play_bpm)
        position = self.clock.position() or 0.0
        fraction = (position / old_duration) if old_duration > 0 else 0.0
        self.play_bpm = bpm
        self.play_ticks = ticks
        if self.stream_ok:
            self.stream.replace_loop(pcm)      # 止めずに中身だけ入れ替え
            self._dj_now = (pcm, bpm, ticks)
            self._dj_last_loops = self.stream.loops
            self._dj_last_switches = self.stream.switches
            self.clock.start(ticks * tick_seconds(bpm),
                             offset_seconds=fraction * ticks * tick_seconds(bpm))
        else:
            self._begin_loop(pcm, "phrase", bpm, ticks, offset_tick=fraction * ticks)
        self._update_dj_decks()

    def _dj_schedule_render(self):
        if self.silent or self.play_mode != "phrase":
            return
        if self._dj_render_token is not None:
            self.root.after_cancel(self._dj_render_token)
        self._dj_render_token = self.root.after(DJ_RENDER_DEBOUNCE_MS, self._dj_render_next)

    def _dj_signature(self):
        """次ループを決めるパラメータの指紋 (準備中に変わったか判定する)。"""
        deck = self._dj_deck()
        return (self._dj_want_seed, deck["scale"], deck["key"], deck["sound"],
                deck["bpm"], deck["noise"], tuple(deck["tones"]), tuple(deck["gates"]),
                deck["filter"], tuple(sorted(deck["muted"])), self.dj_active)

    def _dj_render_next(self):
        """予約したフレーズのループを裏スレッドで作り、_dj_pending へ置く。"""
        self._dj_render_token = None
        if self.silent or self.play_mode != "phrase":
            return
        if self._dj_render_busy:
            self._dj_schedule_render()
            return
        seed = self._dj_want_seed
        project = self._dj_project_for(seed)
        mute = self._dj_mute_pairs()
        dj_filter = self._dj_deck()["filter"]
        signature = self._dj_signature()
        self._dj_render_busy = True

        def work():
            from ..core import dj as dj_core
            pcm = render_phrase_loop(project, mute=mute)
            pcm = dj_core.lowpass_pcm(pcm, dj_filter)
            path = None if self.stream_ok else storage.write_play_wav("dj_next", wav_bytes(pcm))
            return path, pcm, project.bpm, phrase_ticks(project), project, seed

        def done(result):
            self._dj_render_busy = False
            if self.play_mode != "phrase":
                return
            if self._dj_signature() != signature:
                self._dj_schedule_render()   # 準備中に変わった → 作り直す
            elif self._dj_apply_now:
                self._dj_apply_now = False
                self._dj_apply_immediate(result)   # 操作の結果をその場で反映
            else:
                self._dj_pending = result

        self._run_bg(work, done)

    def _dj_do_swap(self):
        """準備済みの次ループへ乗り換える。

        ストリーミング再生なら「次はこれ」と渡すだけで、再生を止めずに
        ループの継ぎ目でサンプル単位で切り替わる (無音が入らない)。
        """
        if self._dj_pending is None:
            return False
        path, pcm, bpm, ticks, project, seed = self._dj_pending
        self._dj_pending = None
        self._dj_swap_soon = False
        if self.stream_ok:
            self.stream.set_next(pcm)                 # 継ぎ目で自動的に乗り換わる
            self._dj_incoming = (pcm, bpm, ticks, project, seed)
            return True
        # フォールバック (ファイル再生): その場で鳴らし直す
        self._dj_loop_count = 0
        self.project = project
        self.dj_decks[self.dj_active]["seed"] = seed
        self.player.play_file(path, loop=True)
        self.clock.start(ticks * tick_seconds(bpm), offset_seconds=0.0)
        self.play_bpm = bpm
        self.play_ticks = ticks
        self._dj_now = (path, bpm, ticks)
        self._dj_last_pos = 0.0
        self._update_dj_decks()
        return True

    def _dj_on_switched(self):
        """ストリーム側が実際に乗り換えたので、表示と状態をそれに合わせる。"""
        if self._dj_incoming is None:
            return
        pcm, bpm, ticks, project, seed = self._dj_incoming
        self._dj_incoming = None
        self.project = project
        self.dj_decks[self.dj_active]["seed"] = seed
        self.play_bpm = bpm
        self.play_ticks = ticks
        self._dj_now = (pcm, bpm, ticks)
        self._dj_loop_count = 0
        self.clock.start(ticks * tick_seconds(bpm), offset_seconds=0.0)
        self._update_dj_decks()
        self._dj_record_history()          # 自動進行で次のフレーズが流れ始めた

    @staticmethod
    def _dj_should_swap(loop_count, hold, has_pending, swap_soon, advance_loops):
        """ループ境界で次フレーズへ差し替えるか。手動変更は即、通常は N ループごと。"""
        if not has_pending:
            return False
        if swap_soon:
            return True
        return (not hold) and loop_count >= advance_loops

    def dj_play(self):
        if self.play_mode == "phrase":
            self.stop_playback()
            return
        if count_notes(self.project.phrase) == 0:
            self.project = self._dj_project_for(self.dj_decks[self.dj_active]["seed"])
            self._update_dj_decks()
        self.stop_playback()
        self._dj_pending = None
        self._dj_swap_soon = False
        self._dj_loop_count = 0
        self._dj_last_pos = 0.0
        self.start_playback("phrase")
        self.dj_view.set_play(True)
        self._dj_record_history()

    def dj_roll(self, deck):
        seed = random.randint(SEED_MIN, SEED_MAX)
        self.dj_decks[deck]["seed"] = seed
        if deck == self.dj_active:
            if self.play_mode == "phrase":
                self._dj_queue(seed=seed, immediate=True)
            else:
                self.project = self._dj_project_for(seed)  # 停止中は即差し替え
        self._update_dj_decks()
        self._dj_record_history(deck)
        self.set_status(t("st_dj_rolled", deck="AB"[deck], seed=seed))

    def _dj_changed(self, deck, reseed=False):
        """デッキの設定が変わったときの共通処理。アクティブなら音へ即反映する。"""
        if deck != self.dj_active:
            self._update_dj_decks()      # 待機側は表示だけ更新 (音はそのまま)
            return
        seed = random.randint(SEED_MIN, SEED_MAX) if reseed else None
        if seed is not None:
            self.dj_decks[deck]["seed"] = seed
        if self.play_mode == "phrase":
            self._dj_queue(seed=seed, immediate=True)
        else:
            self.project = self._dj_project_for(self.dj_decks[deck]["seed"])
        self._update_dj_decks()
        self._dj_history_schedule(deck)      # つまみ操作も履歴に残す (デバウンス)

    def dj_set_scale(self, deck, scale_id):
        """デッキの曲調を選ぶ (セレクタから)。フレーズの骨格は保つ (シードは変えない)。"""
        if scale_id not in SCALE_IDS or self.dj_decks[deck]["scale"] == scale_id:
            return
        self.dj_decks[deck]["scale"] = scale_id
        self._dj_changed(deck)
        self.set_status(t("st_dj_mood", deck="AB"[deck],
                          mood=self._dj_scale_label(scale_id)))

    def dj_set_key(self, deck, key):
        """デッキのキーを選ぶ (0=C .. 11=B)。同じフレーズを別のキーで鳴らす。"""
        key = max(0, min(11, int(key)))
        if key == self.dj_decks[deck]["key"]:
            return
        self.dj_decks[deck]["key"] = key
        self._dj_changed(deck)
        self.set_status(t("st_dj_key", deck="AB"[deck], key=KEY_NAMES[key]))

    def dj_set_sound(self, deck, sound):
        """デッキの音色を選ぶ。

        フレーズ画面の音色と違い、**画面の配色は変えない**。演奏中に全体が
        作り直されるとディスクが飛ぶうえ、デッキごとに別の音色を持てなくなるため。
        """
        if sound not in theme.SOUND_IDS or self.dj_decks[deck]["sound"] == sound:
            return
        self.dj_decks[deck]["sound"] = sound
        self._dj_changed(deck)
        self.set_status(t("st_dj_sound", deck="AB"[deck], label=i18n.sound_label(sound)))

    def dj_mood(self, deck):
        """曲調をランダムに選び直す (おまかせ)。"""
        self.dj_set_scale(deck, random.choice(SCALE_IDS))

    def dj_sync(self, deck):
        """このデッキを、もう一方のデッキへ合わせる (テンポ・キー)。

        DJ の SYNC と同じ発想。曲調・音色・フレーズはそのままなので、
        「別の曲調のまま拍とキーだけ揃えて重ねる」ことができる。
        """
        other = self.dj_decks[1 - deck]
        target, key = other["bpm"], other["key"]
        if self.dj_decks[deck]["bpm"] == target and self.dj_decks[deck]["key"] == key:
            self.set_status(t("st_dj_sync_same", deck="AB"[deck]))
            return
        self.dj_decks[deck]["bpm"] = target
        self.dj_decks[deck]["key"] = key
        self._dj_changed(deck)
        self.set_status(t("st_dj_sync", deck="AB"[deck], bpm=target, key=KEY_NAMES[key]))

    # ---- 履歴・お気に入り ----

    def _dj_entry(self, deck=None):
        """今のデッキ設定を、履歴・お気に入り用のエントリにする。"""
        index = self.dj_active if deck is None else deck
        state = self.dj_decks[index]
        return dj_core.make_entry(state["scale"], state["key"], state["bpm"],
                                  state["sound"], state["noise"], state["seed"],
                                  tones=state["tones"], gates=state["gates"], deck=index)

    def _dj_record_history(self, deck=None):
        """フレーズが**流れ始めた**ところで履歴へ残す (自動進行・生成・デッキ切替)。"""
        self.dj_history = dj_core.push_history(self.dj_history, self._dj_entry(deck))
        self._refresh_dj_log()

    def _dj_history_schedule(self, deck=None):
        """つまみ操作を、少し待ってから履歴へ確定する (デバウンス)。

        スライダーを動かすと値ごとにコールバックが飛ぶので、そのたびに履歴へ
        積むと中間値で埋まる。操作が落ち着いてから 1 つだけ確定させる。
        確定した状態は新しい行として残る (元の状態も履歴に残るので後で戻せる)。
        """
        self._dj_hist_deck = self.dj_active if deck is None else deck
        if self._dj_hist_token is not None:
            self.root.after_cancel(self._dj_hist_token)
        self._dj_hist_token = self.root.after(DJ_HISTORY_COMMIT_MS,
                                              self._dj_history_commit)

    def _dj_history_commit(self):
        """デバウンス後、今の設定を履歴へ確定する。"""
        self._dj_hist_token = None
        self._dj_record_history(getattr(self, "_dj_hist_deck", None))

    def _dj_history_flush(self):
        """保留中のデバウンスを即確定する (テスト・タブ離脱時など)。"""
        if self._dj_hist_token is not None:
            self.root.after_cancel(self._dj_hist_token)
            self._dj_history_commit()

    def _refresh_dj_log(self):
        if hasattr(self, "dj_view"):
            self.dj_view.sync_log(self.dj_history, self.dj_favorites)

    def dj_entry_label(self, entry) -> str:
        """履歴・お気に入り 1 行ぶんの表示 (曲調 / キー / テンポ / 音色)。"""
        return t("dj_entry", mood=self._dj_scale_label(entry["scale"]),
                 key=KEY_NAMES[max(0, min(11, entry["key"]))], bpm=entry["bpm"],
                 sound=i18n.sound_label(entry["sound"]))

    def dj_toggle_favorite(self, entry=None):
        """エントリ (既定は今流している音) をお気に入りに登録／解除する。"""
        entry = self._dj_entry() if entry is None else entry
        self.dj_favorites, added = dj_core.toggle_favorite(self.dj_favorites, entry)
        settings = storage.load_settings()
        settings["dj_favorites"] = self.dj_favorites
        storage.save_settings(settings)          # ★ は再起動後も残る
        self._refresh_dj_log()
        self.set_status(t("st_dj_fav_add") if added else t("st_dj_fav_remove"))
        return added

    def dj_clear_history(self):
        """履歴を空にする (お気に入りは消さない)。つまみ操作で溜まった分を掃除する。"""
        self.dj_history = []
        self._refresh_dj_log()
        self.set_status(t("st_dj_hist_cleared"))

    def dj_clear_favorites(self):
        """お気に入りを空にする (設定ファイルからも消す)。"""
        self.dj_favorites = []
        settings = storage.load_settings()
        settings["dj_favorites"] = []
        storage.save_settings(settings)
        self._refresh_dj_log()
        self.set_status(t("st_dj_fav_cleared"))

    def dj_record_toggle(self):
        """セット録音の開始／停止。停止時に WAV として保存する。

        録音するのはストリームが実際に送り出しているミックスそのもの
        (乗り換え・スクラッチ・ノイズ込み)。聞こえた通りに 1 本の WAV になる。
        """
        if self.silent or not self.stream_ok:
            self.alert(t("st_dj_rec_unavailable"))
            return
        if not self._dj_recording:
            self.stream.start_record()
            self._dj_recording = True
            self.dj_view.set_recording(True)
            self.set_status(t("st_dj_rec_start"))
            return
        pcm = self.stream.stop_record()
        self._dj_recording = False
        self.dj_view.set_recording(False)
        self._dj_save_recording(pcm)

    def _dj_save_recording(self, pcm):
        if not pcm:
            self.set_status(t("st_dj_rec_empty"))
            return
        seconds = len(pcm) // (SAMPLE_RATE * 2)
        path = filedialog.asksaveasfilename(
            title=t("dj_rec_save_title"), defaultextension=".wav",
            initialfile=t("dj_rec_filename"),
            filetypes=[("WAV", "*.wav")])
        if not path:
            self.set_status(t("st_dj_rec_discarded"))
            return
        try:
            storage.save_bytes(Path(path), wav_bytes(pcm))
        except OSError as exc:
            self.alert(t("st_dj_rec_error", error=exc))
            return
        self.set_status(t("st_dj_rec_saved", sec=seconds))

    def dj_recall(self, entry, deck=None):
        """履歴・お気に入りのフレーズを、指定デッキ (既定はアクティブ) へ呼び戻す。"""
        index = self.dj_active if deck is None else deck
        state = self.dj_decks[index]
        state["scale"] = entry["scale"] if entry["scale"] in SCALE_IDS else state["scale"]
        state["key"] = max(0, min(11, entry["key"]))
        state["bpm"] = max(BPM_MIN, min(BPM_MAX, entry["bpm"]))
        state["noise"] = max(0, min(4, entry["noise"]))
        clean = dj_core.sanitize_entries([entry])[0]   # tones/gates を 4 個・整数に整える
        state["tones"] = [max(0, min(100, v)) for v in clean["tones"]]
        state["gates"] = [max(10, min(100, v)) for v in clean["gates"]]
        if entry["sound"] in theme.SOUND_IDS:
            state["sound"] = entry["sound"]
        state["seed"] = entry["seed"]
        # 呼び戻したものが勝手に流れ去らないよう、そのデッキをループ固定にする
        state["hold"] = True
        self._dj_changed(index)
        self.set_status(t("st_dj_recall", deck="AB"[index],
                          label=self.dj_entry_label(entry)))

    def dj_keep(self, entry=None):
        """エントリのフレーズを、空いているパターンスロットへ保存する。

        DJ で偶然できた良いフレーズを、フレーズ／ソング画面へ持って行くための出口。
        """
        entry = self._dj_entry() if entry is None else entry
        slot = actions.free_pattern_slot(self.project)
        if slot < 0:
            self.alert(t("st_dj_keep_full"))
            return -1
        saved = self._dj_deck()
        keys = ("scale", "key", "sound", "bpm", "noise", "tones", "gates")
        backup = {k: saved[k] for k in keys}
        clean = dj_core.sanitize_entries([entry])[0]
        try:                                       # 一時的にエントリの設定で組み立てる
            saved.update({k: entry[k] for k in ("scale", "key", "sound", "bpm", "noise")})
            saved["tones"] = list(clean["tones"])
            saved["gates"] = list(clean["gates"])
            project = self._dj_project_for(entry["seed"])
        finally:
            saved.update(backup)
        name = t("dj_keep_name", mood=self._dj_scale_label(entry["scale"]),
                 bpm=entry["bpm"])                 # 名前欄は 24 文字なので短く
        project = actions.save_pattern(project, slot, name)
        # 盤面 (フレーズ) は今のまま、パターン欄だけ増やす
        self.commit(actions.update(self.project, patterns=project.patterns))
        self._rebuild_pattern_list()
        self.set_status(t("st_dj_keep", n=slot + 1))
        return slot

    def dj_set_crossfade(self, value):
        new_active = 0 if value < 50 else 1
        if new_active == self.dj_active:
            return
        self.dj_active = new_active
        if self.play_mode == "phrase":
            self._dj_queue(seed=self.dj_decks[new_active]["seed"], immediate=True)
        else:
            self.project = self._dj_project_for(self.dj_decks[new_active]["seed"])
        self._update_dj_decks()
        self._dj_record_history()          # 反対のデッキが表に出た
        self.set_status(t("st_dj_switch", deck="AB"[new_active]))

    def dj_set_hold(self, deck, on):
        self.dj_decks[deck]["hold"] = bool(on)
        self._update_dj_decks()
        self.set_status(t("st_dj_hold_on") if on else t("st_dj_hold_off"))

    def dj_set_noise(self, deck, level):
        level = max(0, min(4, int(level)))
        if level == self.dj_decks[deck]["noise"]:
            return
        self.dj_decks[deck]["noise"] = level
        self._dj_changed(deck)
        self.set_status(t("st_dj_noise", level=level))

    def dj_set_part_tone(self, deck, wave, tone):
        """パートの音色を変える (0..100)。メロディならパルス波のデューティ比。

        フレーズの音符は変えず音色だけが変わるので、同じフレーズのまま
        各パートの質感 (細い電子音 ⇄ 太い矩形波 など) を作り込める。
        """
        wave = max(0, min(PART_COUNT - 1, int(wave)))
        tone = max(0, min(100, int(tone)))
        if tone == self.dj_decks[deck]["tones"][wave]:
            return
        self.dj_decks[deck]["tones"][wave] = tone
        self._dj_changed(deck)
        self.set_status(t("st_dj_part_tone", deck="AB"[deck],
                          part=i18n.part_name(wave), tone=tone))

    def dj_set_part_gate(self, deck, wave, gate):
        """パートの長さ (ゲート 10..100) を変える。短いほど歯切れよく、長いほど伸びる。"""
        wave = max(0, min(PART_COUNT - 1, int(wave)))
        gate = max(10, min(100, int(gate)))
        if gate == self.dj_decks[deck]["gates"][wave]:
            return
        self.dj_decks[deck]["gates"][wave] = gate
        self._dj_changed(deck)
        self.set_status(t("st_dj_part_gate", deck="AB"[deck],
                          part=i18n.part_name(wave), gate=gate))

    def dj_set_filter(self, deck, level):
        level = max(0, min(100, int(level)))
        if level == self.dj_decks[deck]["filter"]:
            return
        self.dj_decks[deck]["filter"] = level
        self._dj_changed(deck)

    def dj_set_tempo(self, deck, bpm):
        bpm = max(BPM_MIN, min(BPM_MAX, int(bpm)))
        if bpm == self.dj_decks[deck]["bpm"]:
            return
        self.dj_decks[deck]["bpm"] = bpm
        self._dj_changed(deck)

    def dj_tap(self):
        """タップテンポ — 押した間隔の平均から、アクティブデッキの BPM を決める。"""
        now = time.monotonic()
        self._dj_taps = [tap for tap in self._dj_taps if now - tap < 2.0]
        self._dj_taps.append(now)
        bpm = self._tap_bpm(self._dj_taps)
        if bpm is None:
            return
        self.dj_set_tempo(self.dj_active, bpm)
        self.dj_view.set_tempo(self.dj_active, bpm)

    @staticmethod
    def _tap_bpm(taps):
        """打点 (monotonic 秒) の列から BPM を求める。2 打未満・不正なら None。"""
        if len(taps) < 2:
            return None
        intervals = [b - a for a, b in zip(taps, taps[1:])]
        avg = sum(intervals) / len(intervals)
        if avg <= 0:
            return None
        return max(BPM_MIN, min(BPM_MAX, int(round(60.0 / avg))))

    def dj_kill(self, deck, part):
        muted = self.dj_decks[deck]["muted"]
        if part in muted:
            muted.discard(part)
        else:
            muted.add(part)
        self._dj_changed(deck)                  # アクティブなら今のループへ即反映

    # ---- スクラッチ (ディスクをドラッグ) ----

    @staticmethod
    def dj_scratch_pitch(delta):
        """ドラッグ角度の変化からスクラッチ音の高さを決める (前=高い / 後=低い)。"""
        speed = min(28, abs(delta))
        pitch = 56 + int(speed) if delta >= 0 else 56 - int(speed) - 6
        return max(PITCH_MIN, min(PITCH_MAX, pitch))

    def dj_scratch_start(self, deck):
        self._dj_scratching = True
        # ストリーミング再生なら音楽に重ねてスクラッチできるので止めない。
        if not self.silent and not self.stream_ok and self.play_mode == "phrase":
            self.player.stop()          # フォールバック時のみ一旦止める

    def dj_scratch_move(self, deck, delta):
        if not self._dj_scratching or self.silent:
            return
        now = time.monotonic()
        if now - self._dj_scratch_last < DJ_SCRATCH_MS / 1000.0:
            return
        self._dj_scratch_last = now
        self._dj_play_scratch(self.dj_scratch_pitch(delta))

    def dj_scratch_end(self, deck):
        if not self._dj_scratching:
            return
        self._dj_scratching = False
        if self.silent or self.stream_ok:
            return                                # 重ねて鳴らしていたので何も戻さなくてよい
        self.player.stop()
        if self.play_mode == "phrase" and self._dj_now is not None:
            path, bpm, ticks = self._dj_now       # ダウンビートから鳴らし直す
            self.player.play_file(path, loop=True)
            self.clock.start(ticks * tick_seconds(bpm), offset_seconds=0.0)
            self._dj_last_pos = 0.0

    def _dj_play_scratch(self, pitch):
        from ..core.constants import WAVE_PULSE
        pcm = self._dj_scratch_cache.get(pitch)
        if pcm is None:
            pcm = render_preview(WAVE_PULSE, pitch, 70, 100, sound=self.project.sound)
            if len(self._dj_scratch_cache) > 64:
                self._dj_scratch_cache.clear()
            self._dj_scratch_cache[pitch] = pcm
        self._play_oneshot(pcm)

    def _play_oneshot(self, pcm):
        """効果音を 1 回鳴らす。ストリーミング再生なら音楽に重ねて鳴る。"""
        if self.silent:
            return
        if self.stream_ok:
            self.stream.play_oneshot(pcm)
        else:
            self.player.play_file(storage.write_play_wav("oneshot", wav_bytes(pcm)),
                                  loop=False)

    def _dj_spin_tick(self):
        """再生位置に合わせてターンテーブルを回し、境界で継ぎ目なく差し替える。"""
        if self._dj_scratching:
            return                     # スクラッチ中は DJView が手で回す
        spinning = self.play_mode == "phrase"
        beat_level = 0.0
        if spinning:
            pos = self.clock.position() or 0.0
            beat_dur = tick_seconds(self.play_bpm) * 4  # 1 拍 = 16 分 4 つ
            if beat_dur > 0:
                phase = (pos % beat_dur) / beat_dur
                beat_level = max(0.0, 1.0 - phase * 3)
            if self.stream_ok:
                # 実際の再生ストリームのループ/乗り換え回数で進行を数える
                if self.stream.switches != self._dj_last_switches:
                    self._dj_last_switches = self.stream.switches
                    self._dj_on_switched()
                if self.stream.loops != self._dj_last_loops:
                    self._dj_last_loops = self.stream.loops
                    self._dj_loop_count += 1
                    # 最後の 1 周に入ったら次を渡す → その継ぎ目で乗り換わる
                    if self._dj_should_swap(self._dj_loop_count, self._dj_deck()["hold"],
                                            self._dj_pending is not None,
                                            self._dj_swap_soon, DJ_ADVANCE_LOOPS - 1):
                        self._dj_do_swap()
            else:
                if pos < self._dj_last_pos - 0.05:      # ループ折り返し = ダウンビート
                    self._dj_loop_count += 1
                    if self._dj_should_swap(self._dj_loop_count, self._dj_deck()["hold"],
                                            self._dj_pending is not None,
                                            self._dj_swap_soon, DJ_ADVANCE_LOOPS):
                        self._dj_do_swap()
            self._dj_last_pos = pos
            # 常に次の 1 つを仕込んでおく (連続フロー)
            if (self._dj_pending is None and self._dj_incoming is None
                    and not self._dj_render_busy and self._dj_render_token is None):
                self._dj_prepare_auto()
        key = "a" if self.dj_active == 0 else "b"
        self.dj_view.update_spin(key, spinning, beat_level)

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

    def self_test(self) -> bool:
        """画面を出さずに主要な配線を一巡する。"""
        try:
            self.autosave_file = Path(tempfile.mkdtemp()) / "picoseq_selftest.json"

            # フレーズ編集: 置く → 伸ばす → 消す → 元に戻す
            slot, anchor = self.roll_press(60, 0)
            assert slot != -1 and anchor == 0
            self.roll_resize(slot, 4)
            self.roll_release()
            assert count_notes(self.project.phrase) == 1
            self.roll_press(60, 2)  # 音符の中身クリック → 削除
            assert count_notes(self.project.phrase) == 0
            self.undo_action()
            assert count_notes(self.project.phrase) == 1
            self.redo_action()
            assert count_notes(self.project.phrase) == 0

            # 長さ 1 の音符はクリックだけで消せる (旧版の欠点を修正)
            self.roll_press(64, 0)
            self.roll_release()
            assert count_notes(self.project.phrase) == 1
            self.roll_press(64, 0)  # 右端 = 唯一のセル → 伸ばしモード
            self.roll_release()     # ドラッグしていないので削除になる
            assert count_notes(self.project.phrase) == 0

            # 自動作成 (シード値の再現) → パターン登録 → ソング配置
            self._syncing = True
            self.seed_var.set("42")
            self._syncing = False
            self.generate_from_seed_entry()
            assert count_notes(self.project.phrase) > 0
            assert self.project.seed == 42
            assert "→" in self._progression_text()  # コード進行の表示が作れる
            self.generate_auto()  # 統合された自動作成 (新しい番号で作る)
            assert count_notes(self.project.phrase) > 0
            self.save_current_pattern()
            assert self.project.patterns[0].used
            self.switch_tab("song")
            self.song_click(0, 0)
            self.song_click(0, 1)
            assert used_blocks(self.project.song) == 2
            self.song_erase(0, 1)
            assert used_blocks(self.project.song) == 1

            # パターン編集タブ: 保存 → 名称 → 複製 → 編集読込 → 削除
            self.switch_tab("pattern")
            self._rebuild_pattern_list()  # 例外なく一覧が作れる
            self.clear_phrase()
            self.select_part(0)
            self.roll_press(60, 0)
            self.roll_release()
            slot = actions.free_pattern_slot(self.project)
            self.save_pattern_here(slot)
            assert self.project.patterns[slot].used
            self.commit(actions.rename_pattern(self.project, slot, "テスト"))
            assert self.project.patterns[slot].name == "テスト"
            assert self.pattern_label(slot) == "テスト"
            used_before = sum(1 for pp in self.project.patterns if pp.used)
            self.duplicate_pattern_action(slot)
            assert sum(1 for pp in self.project.patterns if pp.used) == used_before + 1
            self.edit_pattern(slot)
            assert self.tab == "phrase"
            self.switch_tab("pattern")
            self.delete_pattern_slot(slot)
            assert not self.project.patterns[slot].used

            # ソング: 長い名前の省略表示・マスのホバー説明・パターン試聴
            self.save_current_pattern()
            long_slot = next(i for i, pp in enumerate(self.project.patterns) if pp.used)
            self.commit(actions.rename_pattern(self.project, long_slot,
                                               "とても長いパターン名前"))
            self.switch_tab("song")
            self.select_pattern(long_slot)
            self.song_click(2, 5)                           # 空きマスへ配置
            fitted = self.song_view._fit_cell(self.pattern_label(long_slot))
            assert fitted.endswith("…") and len(fitted) < len("とても長いパターン名前")
            assert self.song_view._fit_cell("F1") == "F1"  # 短い名前はそのまま
            self.show_song_hint(2, 5)                       # ホバー説明は名前を省略せず出す
            assert "とても長いパターン名前" in self.cell_var.get()
            self.clear_song_hint()
            assert self.cell_var.get() == ""
            self.preview_selected_pattern()                 # 選択パターンを試聴 (silent は無音)
            self.selected_pattern = -1
            self.preview_selected_pattern()                 # 未選択でも落ちない

            # DJ モード: 生成・曲調・ノイズ・クロスフェード・KILL・自動生成・回転更新
            from ..core.phrase import active_notes as _an_dj
            from ..core.constants import WAVE_NOISE as _WN
            self.switch_tab("dj")
            self.dj_roll(0)
            assert count_notes(self.project.phrase) > 0     # デッキから生成される
            # 曲調・キーをセレクタで任意に指定できる (どちらも既定はメジャー/C)
            assert self.dj_decks[0]["scale"] == self.dj_decks[1]["scale"] == "major"
            self.dj_set_scale(0, "battle")
            assert self.dj_decks[0]["scale"] == "battle"
            self.dj_set_scale(0, "major")
            self.dj_set_key(0, 7)
            assert self.dj_decks[0]["key"] == 7 and self.project.key == 7
            self.dj_set_key(1, 3)                            # キーもデッキごとに独立
            assert self.dj_decks[1]["key"] == 3 and self.dj_decks[0]["key"] == 7
            self.dj_set_key(0, 0)
            self.dj_mood(0)                                  # おまかせ (ランダム)
            self.dj_set_noise(0, 3)
            noisy = sum(1 for _, n in _an_dj(self.project.phrase) if n.wave == _WN)
            self.dj_set_noise(0, 0)
            plain = sum(1 for _, n in _an_dj(self.project.phrase) if n.wave == _WN)
            assert noisy > plain                            # ノイズ量で刻みが増える
            # デッキごとに独立して設定できる (待機側をいじっても再生側は変わらない)
            self.dj_set_tempo(1, 200)
            self.dj_set_noise(1, 4)
            self.dj_set_filter(1, 20)
            self.dj_set_hold(1, True)
            self.dj_kill(1, 0)
            assert self.dj_decks[1]["bpm"] == 200 and self.dj_decks[0]["bpm"] != 200
            assert self.dj_decks[1]["noise"] == 4 and self.dj_decks[0]["noise"] == 0
            assert self.dj_decks[1]["filter"] == 20 and self.dj_decks[0]["filter"] == 100
            assert self.dj_decks[1]["hold"] and not self.dj_decks[0]["hold"]
            assert 0 in self.dj_decks[1]["muted"] and 0 not in self.dj_decks[0]["muted"]
            self.dj_set_crossfade(80)
            assert self.dj_active == 1                       # B へ切替
            assert self.project.bpm == 200                   # B のテンポが効く
            self.dj_set_crossfade(10)
            assert self.dj_active == 0                       # A へ戻る
            self.dj_kill(0, 2)
            assert 2 in self.dj_decks[0]["muted"]            # KILL = パート消音
            self.dj_kill(0, 2)
            assert 2 not in self.dj_decks[0]["muted"]
            # HOLD (ループ固定) の切替
            self.dj_set_hold(0, True)
            assert self.dj_decks[0]["hold"]
            self.dj_set_hold(0, False)
            self._dj_spin_tick()                             # 回転更新が例外なく走る
            # 自動進行の判定 (8 小節 = 4 ループごと、手動変更は即)
            assert not self._dj_should_swap(3, False, True, False, 4)   # まだ
            assert self._dj_should_swap(4, False, True, False, 4)       # 4 ループで進む
            assert not self._dj_should_swap(4, True, True, False, 4)    # HOLD 中は進まない
            assert self._dj_should_swap(1, True, True, True, 4)         # 手動は即
            assert not self._dj_should_swap(9, False, False, True, 4)   # 準備前は進まない
            # フィルター: 値が変わる
            self.dj_set_filter(0, 40)
            assert self.dj_decks[0]["filter"] == 40
            self.dj_set_filter(0, 100)
            # タップテンポの計算 (0.5 秒間隔 → 120 BPM)
            assert self._tap_bpm([0.0, 0.5]) == 120
            assert self._tap_bpm([1.0]) is None
            # スクラッチ: ドラッグ量 → 音の高さ (前=高い / 後=低い)、掴む・離す
            assert self.dj_scratch_pitch(20) > self.dj_scratch_pitch(-20)
            self.dj_scratch_start(0)
            assert self._dj_scratching
            self.dj_scratch_move(0, 15)
            self.dj_scratch_end(0)
            assert not self._dj_scratching
            # 境界スワップ (pending 無しでも落ちない)
            self._dj_pending = None
            self._dj_do_swap()

            # 音色もデッキごと。画面の配色 (theme_sound) は変えない
            palette_before = self.theme_sound
            self.dj_set_sound(0, "warm16")
            self.dj_set_sound(1, "clear32")
            assert self.dj_decks[0]["sound"] == "warm16"
            assert self.dj_decks[1]["sound"] == "clear32"
            assert self.project.sound == "warm16"          # 鳴っている側が反映される
            assert self.theme_sound == palette_before      # 演奏中に配色は動かさない

            # SYNC: 相手デッキへテンポとキーを合わせる (曲調・音色はそのまま)
            self.dj_set_tempo(1, 168)
            self.dj_set_key(1, 5)
            self.dj_sync(0)
            assert self.dj_decks[0]["bpm"] == 168 and self.dj_decks[0]["key"] == 5
            assert self.dj_decks[0]["sound"] == "warm16"   # 音色は合わせない
            self.dj_sync(0)                                # 既に合っている → 何も壊れない

            # 音色・長さ: 各パートで調整でき、音符は変えず音作りだけが変わる
            from ..core.constants import WAVE_SAW as _WS
            self.dj_set_part_tone(0, WAVE_PULSE, 100)     # メロディのパルス幅を最大 (矩形)
            square = self.project.parts[WAVE_PULSE][0].tone
            notes_before = [(n.pitch, n.step) for _, n in _an_dj(self.project.phrase)]
            self.dj_set_part_tone(0, WAVE_PULSE, 0)       # 細いパルスへ
            thin = self.project.parts[WAVE_PULSE][0].tone
            notes_after = [(n.pitch, n.step) for _, n in _an_dj(self.project.phrase)]
            assert square == 100 and thin == 0
            assert notes_before == notes_after            # 音符 (メロディ) は不変
            assert self.dj_decks[0]["tones"][WAVE_PULSE] == 0
            # パートごとに独立: サブ (ノコギリ) の音色・長さは別に持つ
            self.dj_set_part_tone(0, _WS, 80)
            self.dj_set_part_gate(0, _WS, 30)
            assert self.dj_decks[0]["tones"][_WS] == 80
            assert self.dj_decks[0]["tones"][WAVE_PULSE] == 0     # メロディは影響なし
            assert self.dj_decks[0]["gates"][_WS] == 30
            assert self.project.parts[_WS][0].tone == 80 and self.project.parts[_WS][0].gate == 30
            # 長さはメロディも: 短く歯切れよく
            self.dj_set_part_gate(0, WAVE_PULSE, 20)
            assert self.project.parts[WAVE_PULSE][0].gate == 20
            self.dj_set_part_tone(0, WAVE_PULSE, 50)
            self.dj_set_part_gate(0, WAVE_PULSE, 80)
            self.dj_set_part_tone(0, _WS, 50)
            self.dj_set_part_gate(0, _WS, 80)

            # 履歴: 流したフレーズが新しい順に積まれ、同じものは繰り上がる
            self.dj_history = []
            self.dj_roll(0)
            first = dict(self.dj_history[0])
            self.dj_roll(0)
            assert len(self.dj_history) == 2
            assert self.dj_history[0]["seed"] != first["seed"]
            # つまみ操作も履歴に残る (デバウンス後に新しい行として確定)
            rows = len(self.dj_history)
            self.dj_set_noise(0, 2)
            self._dj_history_flush()                       # デバウンスを即確定
            assert len(self.dj_history) == rows + 1        # 調整ぶんが 1 行増える
            assert self.dj_history[0]["noise"] == 2
            assert any(e["noise"] == 0 for e in self.dj_history)   # 調整前も残っている
            self.dj_set_noise(0, 0)
            self._dj_history_flush()
            assert self.dj_history[0]["noise"] == 0
            # 履歴のクリア (お気に入りは消えない)
            self.dj_clear_history()
            assert self.dj_history == []

            # お気に入り: 登録・解除と、設定ファイルへの永続化
            # 本物の設定ファイルを触るので、利用者の ★ は最後に必ず戻す
            saved_favorites = list(self.dj_favorites)
            try:
                self.dj_favorites = []
                entry = self._dj_entry()
                assert self.dj_toggle_favorite(entry) is True
                assert dj_core.is_favorite(self.dj_favorites, entry)
                assert dj_core.sanitize_entries(
                    storage.load_settings().get("dj_favorites", []))   # 保存されている
                assert self.dj_toggle_favorite(entry) is False         # もう一度で解除
                assert not dj_core.is_favorite(self.dj_favorites, entry)
            finally:
                self.dj_favorites = saved_favorites
                restore = storage.load_settings()
                restore["dj_favorites"] = saved_favorites
                storage.save_settings(restore)

            # 呼び戻し: エントリの設定 (パート音色・長さ含む) がデッキへ入り、固定される
            recall = dj_core.make_entry("battle", 9, 96, "clear32", 1, 4242,
                                        tones=(20, 30, 40, 50), gates=(15, 25, 35, 45),
                                        deck=0)
            self.dj_recall(recall, 1)
            assert self.dj_decks[1]["scale"] == "battle"
            assert self.dj_decks[1]["key"] == 9 and self.dj_decks[1]["bpm"] == 96
            assert self.dj_decks[1]["seed"] == 4242 and self.dj_decks[1]["hold"]
            assert self.dj_decks[1]["tones"] == [20, 30, 40, 50]   # 音色も復元される
            assert self.dj_decks[1]["gates"] == [15, 25, 35, 45]   # 長さも復元される
            self.dj_set_hold(1, False)

            # 💾 残す: 空きスロットへパターンとして保存 (盤面は変えない)
            board = self.project.phrase
            used_before = sum(1 for p in self.project.patterns if p.used)
            slot = self.dj_keep(recall)
            assert slot >= 0 and self.project.patterns[slot].used
            assert sum(1 for p in self.project.patterns if p.used) == used_before + 1
            assert self.project.phrase == board            # 盤面はそのまま
            assert count_notes(self.project.patterns[slot].notes) > 0
            self.commit(actions.delete_pattern(self.project, slot))

            # 録音: silent では使えないので、案内だけ出して録音状態にならない
            self.dj_record_toggle()
            assert not self._dj_recording
            # 保存ヘルパは空 PCM でも落ちない
            self._dj_save_recording(b"")

            # 一覧の再構築が例外なく走る (空でも行があっても)
            self.dj_view.sync_log([], [])
            self.dj_view.sync_log(self.dj_history, [recall])
            self.dj_set_sound(0, "retro8")
            self.dj_set_sound(1, "retro8")

            # パート・スライダー・各コンボの配線
            self.switch_tab("phrase")
            self.select_part(2)
            self._on_tone_change("70")
            self._on_gate_change("40")
            assert self.project.parts[2][0].tone == 70
            assert self.project.parts[2][0].gate == 40

            # マルチレイヤー: 追加・選択・別設定・自動生成・削除
            self.select_part(0)
            self.add_layer_action()
            assert layer_count(self.project, 0) == 2
            assert self.layer == 1  # 追加した層が選択される
            self._on_tone_change("90")
            assert self.project.parts[0][1].tone == 90
            assert self.project.parts[0][0].tone != 90  # 1 層目は不変
            self.generate_auto()
            layers_present = {n.layer for _, n in
                              __import__("picoseq.core.phrase", fromlist=["active_notes"]).active_notes(self.project.phrase)
                              if n.wave == 0}
            assert 1 in layers_present  # 追加レイヤーにも音が入る
            self.remove_layer_action()
            assert layer_count(self.project, 0) == 1
            self.select_part(2)

            # すべての曲調で自動作成が破綻しない (13 曲調)
            from ..core.music import SCALE_IDS as _SCALE_IDS
            for index, scale_id in enumerate(_SCALE_IDS):
                self._syncing = True
                self.scale_box.current(index)
                self._syncing = False
                self._on_scale_change()
                assert self.project.scale == scale_id
                self.generate_auto()
                assert count_notes(self.project.phrase) > 0
            self.select_part(0)

            # 自動伴奏: メロディだけ → 4パートに増える
            from ..core.arranger import has_only_melody, melody_notes
            self.clear_phrase()
            self.select_part(0)
            for step, pitch in ((0, 72), (4, 76), (8, 74), (12, 72)):
                self.roll_press(pitch, step)
                self.roll_release()
            assert has_only_melody(self.project)
            mel_before = len(melody_notes(self.project))
            self.arrange_accompaniment()
            waves = {n.wave for _, n in
                     __import__("picoseq.core.phrase", fromlist=["active_notes"]).active_notes(self.project.phrase)}
            assert waves == {0, 1, 2, 3}, waves
            assert len(melody_notes(self.project)) == mel_before  # メロディは保たれる
            assert self.project.progression is not None

            # 編集ツール: 移調・反転・パート消去
            self.generate_auto()                       # 乱数シードで一巡 (配線確認)
            from ..core.phrase import active_notes as _an
            # 移調テストは決定論的に。乱数生成だと稀に高音域だけのメロディになり、
            # 1 オクターブ上げると全音符が音域外へ出て空になってしまうため、
            # 中音域のフレーズが出る固定シードで確認する。
            self.commit(actions.generate_phrase(
                actions.set_seed(actions.set_scale(self.project, "major"), 42)))
            pitches_before = sorted(n.pitch for _, n in _an(self.project.phrase)
                                    if n.wave == 0)
            assert pitches_before                      # メロディが存在する
            self.transpose_up()
            pitches_after = sorted(n.pitch for _, n in _an(self.project.phrase)
                                   if n.wave == 0)
            assert pitches_after and pitches_after != pitches_before
            self.transpose_down()  # 戻る
            before_rev = dumps(self.project)
            self.reverse_phrase_action()
            self.reverse_phrase_action()  # 2 回で元に戻る
            assert dumps(self.project) == before_rev
            self.clear_part_action(2)  # リズムだけ消す
            assert not any(n.wave == 2 for _, n in _an(self.project.phrase))
            assert any(n.wave == 0 for _, n in _an(self.project.phrase))  # メロディは残る

            # サプライズ: 曲調・音色・シードがまとめて設定され、配色も追従する
            self.generate_surprise()
            assert count_notes(self.project.phrase) > 0
            assert self.theme_sound == self.project.sound  # 配色と音色が一致
            # テンポ・各パートの音色・長さもランダムに振れ、常に有効範囲に収まる
            voicings, tempos = set(), set()
            for _ in range(12):
                self.generate_surprise()
                assert SURPRISE_BPM[0] <= self.project.bpm <= SURPRISE_BPM[1]
                assert self.bpm_var.get() == str(self.project.bpm)  # 表示も追従
                tempos.add(self.project.bpm)
                for w in range(PART_COUNT):
                    for lyr in self.project.parts[w]:
                        assert 0 <= lyr.tone <= 100 and 25 <= lyr.gate <= 100
                voicings.add(tuple((lyr.tone, lyr.gate)
                                   for w in range(PART_COUNT)
                                   for lyr in self.project.parts[w]))
            assert len(voicings) > 1                        # 質感がランダムに変わる
            assert len(tempos) > 1                          # テンポもランダムに変わる
            self.select_part(0)

            # MIDI 書き出しがフレーズ・ソングとも有効なバイト列を作る
            from ..core.midiio import phrase_midi as _pm
            self.generate_auto()
            assert _pm(self.project)[:4] == b"MThd"

            # 音色をまたぐ保存 → 読込で配色が正しく同期する (回帰: テーマ同期バグ)
            import picoseq.core.actions as _acts
            self.project = _acts.set_sound(self.project, "clear32")
            self._apply_theme("clear32")
            self.do_save()
            self.project = _acts.set_sound(self.project, "retro8")
            self._apply_theme("retro8")
            assert self.theme_sound == "retro8"
            self.do_load()  # clear32 で保存したデータ
            assert self.project.sound == "clear32"
            assert self.theme_sound == "clear32"  # 配色も clear32 に戻っている

            # 保存 → 読込の往復
            self.do_save()
            saved = self.project
            self.clear_phrase()
            self.do_load()
            assert self.project == saved

            # 未保存インジケータ: 編集で立ち、保存で消える
            self.roll_press(72, 0)
            self.roll_release()
            assert self._dirty is True
            self.do_save()
            assert self._dirty is False

            # 旧版データの取り込み (テキスト経由)
            legacy = '{"beats": 4, "currentBuffer": [%d], "favorites": [], "isUsed": []}' % (
                (1 << 18) | 60 | (1 << 19))
            self._load_text(legacy, "legacy ok")
            assert count_notes(self.project.phrase) == 1

            # フォト音階: 合成写真 (四角形 2 個) → 解析 → 曲調へ追加
            body = bytearray()
            for y in range(120):
                for x in range(160):
                    in_a = 15 <= x <= 70 and 20 <= y <= 90
                    in_b = 100 <= x <= 140 and 30 <= y <= 80
                    v = 230 if (in_a or in_b) else 40
                    body += bytes((v, v, v))
            photo_path = Path(tempfile.mkdtemp()) / "quad.ppm"
            photo_path.write_bytes(b"P6\n160 120\n255\n" + bytes(body))
            grid, quads, photo = analyze_photo(photo_path)
            assert len(quads) == 2, len(quads)
            assert photo is not None
            self.apply_photo_scale(photo, generate=True)
            assert self.project.scale == "photo"
            assert self.project.custom_scale == photo.intervals
            assert count_notes(self.project.phrase) > 0
            assert ("フォト" in self._scale_labels()[-1]
                    or "Photo" in self._scale_labels()[-1])
            self.undo_action()  # 1 回のアンドゥで写真適用前へ戻る
            assert self.project.scale != "photo"

            # 鼻歌: 合成音声 (2 音) → メロディ化
            from ..core.humming import detect_melody
            import math as _math
            rate = 22050
            samples = []
            for freq in (220.0, 330.0):
                for i in range(rate):
                    samples.append(int(12000 * _math.sin(2 * _math.pi * freq * i / rate)))
            melody = detect_melody(samples, rate, steps_of(self.project),
                                   self.project.key, self.project.scale,
                                   self.project.custom_scale)
            assert melody, "鼻歌を検出できない"
            self.apply_hum_melody(melody)
            from ..core.arranger import melody_notes as _mel
            assert len(_mel(self.project)) == len(melody)

            # 音色セット: 切替で音・背景テーマの両方が変わり、画面が作り直される
            self._syncing = True
            self.sound_box.current(1)  # warm16
            self._syncing = False
            self._on_sound_change()
            assert self.project.sound == "warm16"
            assert theme.BG == theme.PALETTES["warm16"]["BG"]
            self.roll_press(60, 0)  # 作り直した画面でも操作できる
            self.roll_release()
            self.undo_action()
            self._syncing = True
            self.sound_box.current(0)  # retro8 に戻す
            self._syncing = False
            self._on_sound_change()
            assert theme.BG == theme.PALETTES["retro8"]["BG"]

            # ソング自動作成: 1 曲ぶんの構成ができる
            self.generate_song_auto()
            assert used_blocks(self.project.song) == 16
            assert all(p.used for p in self.project.patterns[:4])
            assert not any(p.used for p in self.project.patterns[4:])

            # 言語切替: 訳語・パート名・曲調ラベルが日英で切り替わる (設定ファイルは触らない)
            prev_lang = i18n.get_lang()
            i18n.set_lang("en")
            assert i18n.t("tab_song") == "🧩 Song"
            assert i18n.part_name(0) == "Melody"
            assert i18n.scale_label("major", "x") == "Bright (Major)"
            i18n.set_lang("ja")
            assert i18n.t("tab_song") == "🧩 ソング"
            assert i18n.scale_label("major", "明るい (メジャー)") == "明るい (メジャー)"
            i18n.set_lang(prev_lang)

            # ミュート: パート単位・レイヤー単位で消音でき、WAV に反映される
            self.generate_auto()
            self.arrange_accompaniment()  # 全パートに音を入れる
            from ..core.renderer import render_phrase as _rp
            full = _rp(self.project)
            self.toggle_mute(2)  # リズムをパートごと消音
            assert self.is_part_muted(2)
            muted = _rp(self.project, mute=self.mute_pairs())
            assert muted != full
            self.toggle_mute(2)  # 解除
            assert not self.is_part_muted(2)
            assert _rp(self.project, mute=self.mute_pairs()) == full
            # レイヤー単位: メロディに 2 層作り、片方だけ消音
            self.select_part(0)
            self.add_layer_action()
            self.generate_auto()
            base = _rp(self.project)
            self.toggle_layer_mute(0, 1)  # メロディ 2 層目だけ消音
            assert (0, 1) in self.muted and (0, 0) not in self.muted
            assert _rp(self.project, mute=self.mute_pairs()) != base
            self.toggle_layer_mute(0, 1)
            self.remove_layer_action()
            self.muted.clear()

            # 盤面の拡大・縮小: セル寸法が変わる
            base_w, base_h = self.roll.cell_w, self.roll.cell_h
            self.zoom_in()
            assert self.roll.cell_w > base_w and self.roll.cell_h > base_h
            self.zoom_out()
            self.zoom_reset()
            assert abs(self.roll.zoom - 1.0) < 1e-6

            # パネルの切り離し / 再ドック (ウィンドウ環境依存なので例外は許容)
            try:
                before = len(self.phrase_paned.panes())
                self.roll_panel.detach()
                assert self.roll_panel.detached
                self.roll_panel.redock()
                assert not self.roll_panel.detached
                assert len(self.phrase_paned.panes()) == before
            except Exception:  # noqa: BLE001 - 表示環境が無い CI などでは skip
                pass

            self.refresh_all()
            self.root.update_idletasks()
            return True
        except Exception:  # noqa: BLE001 - 診断結果として報告する
            traceback.print_exc()
            return False

    # ==============================
    # ウィジェットのコールバック
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
    root.minsize(880, 560)
    # 通常起動は前回のウィンドウ設定を復元。demo や初回は画面に収まる大きさで開く。
    if demo or not app.apply_saved_window():
        width = min(root.winfo_reqwidth() + 8, root.winfo_screenwidth() - 60)
        height = min(root.winfo_reqheight() + 8, root.winfo_screenheight() - 100)
        root.geometry(f"{width}x{height}+30+30")
    root.mainloop()
    return 0
