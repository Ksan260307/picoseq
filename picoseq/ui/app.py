"""PicoSeq メインアプリ — 画面の組み立てと配線。

状態の変更は core.actions の純粋関数だけで行い、ここでは
「いつ呼ぶか」「何を描き直すか」「何を鳴らすか」だけを扱う。
"""

import random
import tempfile
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..core import actions
from ..core.constants import (
    BPM_MAX,
    BPM_MIN,
    MAX_NOTES,
    PATTERN_COUNT,
    SAMPLE_RATE,
    SEED_MAX,
    SEED_MIN,
)
from ..core.history import History, record, redo, undo
from ..core.music import KEY_NAMES, SCALE_IDS, SCALES, note_name
from ..core.note import unpack_note
from ..core.phrase import count_notes, find_note_at
from ..core.project import new_project, steps_of
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
from . import storage, theme
from .help import HelpDialog
from .hum import HumDialog
from .photo import PhotoDialog, analyze_photo
from .playback import PlayClock, SoundPlayer, rotate_pcm
from .roll_view import RollView
from .song_view import SongView

LIVE_DEBOUNCE_MS = 140  # 演奏中の編集をまとめて再レンダリングする間隔

TITLE = "PicoSeq — レトロピコピコ・シーケンサー v2"
HINT_PHRASE = "左クリック: 置く / そのまま右へドラッグ: 伸ばす / 音符クリックか右クリック: 消す / 左端の鍵盤: 試聴"
HINT_SONG = "パレットでフレーズを選び、マスをクリックして配置。同じマスをもう一度で消去。"


class PicoSeqApp:
    def __init__(self, root, silent=False):
        self.root = root
        self.silent = silent
        self.project = new_project()
        self.history = History()
        self.part = 0
        self.selected_pattern = -1
        self.tab = "phrase"

        self.player = SoundPlayer(silent=silent)
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
        self.autosave_file = storage.autosave_path()
        self.saved_snapshot = dumps(self.project)

        root.configure(bg=theme.BG)
        root.title(TITLE)
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
            self.set_status("戻れる操作がありません。")
            return
        self.history, snapshot = result
        self.project = loads(snapshot)
        self.refresh_all()
        self.set_status("元に戻しました。")

    def redo_action(self, _event=None):
        result = redo(self.history, dumps(self.project))
        if not result:
            self.set_status("やり直せる操作がありません。")
            return
        self.history, snapshot = result
        self.project = loads(snapshot)
        self.refresh_all()
        self.set_status("やり直しました。")

    def _mark_edit(self):
        """状態が変わったとき呼ばれる。演奏中なら再生へリアルタイム反映する。"""
        if self.play_mode:
            self.play_hint_var.set("♻ リアルタイム反映")
            self._schedule_live_rerender()

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

        self.tab_phrase_btn = self._button(header, "🎵 フレーズ", lambda: self.switch_tab("phrase"))
        self.tab_song_btn = self._button(header, "🧩 ソング", lambda: self.switch_tab("song"))
        self.tab_phrase_btn.pack(side="left", padx=(16, 2))
        self.tab_song_btn.pack(side="left", padx=2)

        tk.Label(header, text="音色", font=theme.FONT_SMALL,
                 bg=theme.BG, fg=theme.TEXT_DIM).pack(side="left", padx=(14, 2))
        self.sound_box = ttk.Combobox(
            header, values=[theme.SOUND_LABELS[s] for s in theme.SOUND_IDS],
            state="readonly", width=13, font=theme.FONT_SMALL)
        self.sound_box.pack(side="left")
        self.sound_box.bind("<<ComboboxSelected>>", lambda e: self._on_sound_change())

        tk.Label(header, text="テンポ", font=theme.FONT_SMALL,
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

        self._button(header, "❓ ヘルプ", self.show_help).pack(side="right", padx=2)
        for text, command in (("⬆ 取込", self.do_import), ("⬇ 書出", self.do_export),
                              ("📂 読込", self.do_load), ("💾 保存", self.do_save)):
            self._button(header, text, command).pack(side="right", padx=2)
        self._button(header, "↪", self.redo_action).pack(side="right", padx=(2, 10))
        self._button(header, "↩", self.undo_action).pack(side="right", padx=2)

        # ---- フレーズタブ ----
        self.phrase_frame = tk.Frame(root, bg=theme.PANEL, padx=10, pady=8,
                                     highlightbackground=theme.PANEL_EDGE,
                                     highlightthickness=1)

        bar1 = tk.Frame(self.phrase_frame, bg=theme.PANEL)
        bar1.pack(fill="x", pady=(0, 6))
        self.play_phrase_btn = self._button(bar1, "▶ 再生", lambda: self.toggle_play("phrase"), accent=True)
        self.play_phrase_btn.pack(side="left", padx=(0, 12))

        self.beats_box = self._combo(bar1, "拍子", [f"{n}/4" for n in range(2, 8)], self._on_beats_change, width=5)
        self.key_box = self._combo(bar1, "キー", list(KEY_NAMES), self._on_key_change, width=8)
        self.scale_box = self._combo(bar1, "曲調", self._scale_labels(), self._on_scale_change, width=16)

        tk.Label(bar1, text="シード値", font=theme.FONT_SMALL,
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

        self._button(bar1, "✨ 自動作成", self.generate_auto).pack(side="left", padx=(8, 2))
        self._button(bar1, "🎤 鼻歌から", self.hum_compose).pack(side="left", padx=2)
        self._button(bar1, "📷 写真から", self.photo_compose).pack(side="left", padx=2)
        self.arrange_btn = self._button(bar1, "🎸 伴奏づけ", self.arrange_accompaniment)
        self.arrange_btn.pack(side="left", padx=2)

        bar2 = tk.Frame(self.phrase_frame, bg=theme.PANEL)
        bar2.pack(fill="x", pady=(0, 6))
        tk.Label(bar2, text="パート", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.part_buttons = []
        for i in range(4):
            btn = tk.Button(
                bar2, text=f"{i + 1} {theme.PART_NAMES[i]}", font=theme.FONT_SMALL,
                command=lambda i=i: self.select_part(i), relief="flat", bd=1,
                padx=8, pady=2, takefocus=0, cursor="hand2",
            )
            btn.pack(side="left", padx=2)
            self.part_buttons.append(btn)

        self.wave_label_var = tk.StringVar()
        tk.Label(bar2, textvariable=self.wave_label_var, font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM, width=9).pack(side="left", padx=(4, 12))

        tk.Label(bar2, text="音色", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left")
        self.tone_scale = tk.Scale(
            bar2, from_=0, to=100, orient="horizontal", length=120, showvalue=0,
            command=self._on_tone_change, bg=theme.PANEL, troughcolor=theme.BTN_BG,
            highlightthickness=0, bd=0, activebackground=theme.ACCENT,
        )
        self.tone_scale.pack(side="left", padx=(2, 12))
        self._attach_gesture(self.tone_scale)

        tk.Label(bar2, text="長さ", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left")
        self.gate_scale = tk.Scale(
            bar2, from_=10, to=100, orient="horizontal", length=120, showvalue=0,
            command=self._on_gate_change, bg=theme.PANEL, troughcolor=theme.BTN_BG,
            highlightthickness=0, bd=0, activebackground=theme.ACCENT,
        )
        self.gate_scale.pack(side="left", padx=2)
        self._attach_gesture(self.gate_scale)

        self._button(bar2, "★ 登録", self.save_current_pattern).pack(side="right", padx=2)
        self._button(bar2, "🗑 クリア", self.clear_phrase, danger=True).pack(side="right", padx=2)
        self._button(bar2, "🎧 WAV書出", lambda: self.do_export_wav("phrase")).pack(side="right", padx=(2, 8))

        self.roll = RollView(self.phrase_frame, self)
        self.roll.frame.pack()

        # ---- ソングタブ ----
        self.song_frame = tk.Frame(root, bg=theme.PANEL, padx=10, pady=8,
                                   highlightbackground=theme.PANEL_EDGE,
                                   highlightthickness=1)

        bar3 = tk.Frame(self.song_frame, bg=theme.PANEL)
        bar3.pack(fill="x", pady=(0, 6))
        self.play_song_btn = self._button(bar3, "▶ ソング再生", lambda: self.toggle_play("song"), accent=True)
        self.play_song_btn.pack(side="left", padx=(0, 12))
        self._button(bar3, "✨ ソング自動作成", self.generate_song_auto).pack(side="left", padx=2)
        self._button(bar3, "🗑 構成クリア", self.clear_song, danger=True).pack(side="left", padx=(12, 2))
        self._button(bar3, "🎵 WAV書出", lambda: self.do_export_wav("song")).pack(side="left", padx=(12, 2))

        palette = tk.Frame(self.song_frame, bg=theme.PANEL)
        palette.pack(fill="x", pady=(0, 6))
        tk.Label(palette, text="パターン", font=theme.FONT_SMALL,
                 bg=theme.PANEL, fg=theme.TEXT_DIM).pack(side="left", padx=(0, 4))
        self.pattern_buttons = []
        for i in range(PATTERN_COUNT):
            btn = tk.Button(
                palette, text=f"F{i + 1}", font=theme.FONT_BOLD, width=3,
                command=lambda i=i: self.select_pattern(i), relief="flat", bd=1,
                takefocus=0, cursor="hand2",
            )
            btn.pack(side="left", padx=2)
            self.pattern_buttons.append(btn)
        self._button(palette, "🗑 削除", self.delete_selected_pattern, danger=True).pack(side="right", padx=2)
        self._button(palette, "✏ 編集へ読込", self.load_selected_pattern).pack(side="right", padx=2)

        self.song_view = SongView(self.song_frame, self)
        self.song_view.frame.pack()

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
        self.switch_tab("song" if self.tab == "phrase" else "phrase")
        return "break"

    # ==============================
    # 画面の更新
    # ==============================

    def _scale_labels(self) -> list:
        """曲調セレクタの選択肢。フォト音階があれば末尾に加わる。"""
        labels = [SCALES[s]["label"] for s in SCALE_IDS]
        if self.project.custom_scale is not None:
            labels.append("📷 フォト音階")
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
            self.tone_scale.set(p.parts[self.part].tone)
            self.gate_scale.set(p.parts[self.part].gate)
        finally:
            self._syncing = False
        self._update_part_buttons()
        self.roll.rebuild()
        self.song_view.rebuild()
        self._update_palette()
        self._update_counts()
        self._update_undo_buttons()

    def refresh_after_edit(self):
        self.roll.redraw_notes()
        self.song_view.redraw_cells()
        self._update_palette()
        self._update_counts()
        self._update_undo_buttons()

    def _update_part_buttons(self):
        for i, button in enumerate(self.part_buttons):
            color = theme.PART_COLORS[i]
            if i == self.part:
                button.configure(bg=color, fg=theme.KEY_TEXT, relief="sunken")
            else:
                button.configure(bg=theme.BTN_BG, fg=color, relief="flat")
        self.wave_label_var.set(theme.PART_WAVES[self.part])

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
        extra = " ・ 進行: フォト" if p.progression is not None else ""
        self.count_var.set(
            f"音符 {count_notes(p.phrase)}/{MAX_NOTES} ・ "
            f"パターン {used}/{PATTERN_COUNT} ・ ブロック {used_blocks(p.song)}/16{extra}"
        )

    def _update_undo_buttons(self):
        pass  # ボタンは常時有効。押せないときはステータスで知らせる。

    def set_status(self, text):
        self.status_var.set(text)

    def show_cell_hint(self, pitch, step):
        beats = self.project.beats
        measure = step // (beats * 4) + 1
        beat = step % (beats * 4) // 4 + 1
        self.cell_var.set(f"{note_name(pitch)} ・ {measure}小節 {beat}拍")

    def switch_tab(self, name, stop=True):
        if stop:
            self.stop_playback()
        self.tab = name
        if name == "phrase":
            self.song_frame.pack_forget()
            self.phrase_frame.pack(fill="both", expand=True, padx=10, pady=4)
            self.set_status(HINT_PHRASE)
        else:
            self.phrase_frame.pack_forget()
            self.song_frame.pack(fill="both", expand=True, padx=10, pady=4)
            self.set_status(HINT_SONG)
        on = dict(bg=theme.BTN_ON, fg=theme.BTN_ON_TEXT)
        off = dict(bg=theme.BTN_BG, fg=theme.TEXT)
        self.tab_phrase_btn.configure(**(on if name == "phrase" else off))
        self.tab_song_btn.configure(**(off if name == "phrase" else on))

    # ==============================
    # フレーズ編集 (RollView から呼ばれる)
    # ==============================

    def roll_press(self, pitch, step):
        """クリック位置に応じて 置く / 消す / 伸ばし開始。(スロット, 起点) を返す。

        既存音符の右端は「ドラッグで伸ばす」起点。ただしドラッグせずに
        離した場合は削除として扱う (roll_release で判定)。
        """
        project = self.project
        slot = find_note_at(project.phrase, pitch, step, self.part)
        if slot == -1:
            new_project, new_slot = actions.place_note(project, pitch, step, self.part)
            if new_slot == -1:
                self.set_status(f"音符が一杯です (最大 {MAX_NOTES})。")
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
        slot = find_note_at(self.project.phrase, pitch, step, self.part)
        if slot != -1:
            self.commit(actions.erase_note(self.project, slot))

    def select_part(self, part):
        self.part = part
        self._syncing = True
        try:
            self.tone_scale.set(self.project.parts[part].tone)
            self.gate_scale.set(self.project.parts[part].gate)
        finally:
            self._syncing = False
        self._update_part_buttons()
        self.roll.redraw_notes()

    def preview_note(self, pitch):
        """鍵盤の試聴。再生中は邪魔しない。"""
        if self.play_mode or self.silent:
            return
        params = self.project.parts[self.part]
        key = (self.part, pitch, params.tone, params.gate, self.project.sound)
        wav = self._preview_cache.get(key)
        if wav is None:
            wav = wav_bytes(render_preview(self.part, pitch, params.tone,
                                           params.gate, sound=self.project.sound))
            if len(self._preview_cache) > 48:
                self._preview_cache.clear()
            self._preview_cache[key] = wav
        path = storage.write_play_wav("preview", wav)
        self.player.play_file(path, loop=False)

    def clear_phrase(self):
        if count_notes(self.project.phrase) == 0:
            return
        if self.confirm("クリア", "現在のフレーズをすべて消しますか?"):
            self.commit(actions.clear_phrase(self.project))
            self.set_status("フレーズを消しました (↩ で戻せます)。")

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
        self.set_status(f"シード値 {seed} で作成しました。気に入ったら ★ 登録! "
                        "(番号を入力して Enter で同じ曲を再現できます)")

    def generate_from_seed_entry(self):
        """シード値の欄で Enter — その番号の曲を再現する。"""
        self._on_seed_change()
        self.commit(actions.generate_phrase(self.project))
        self.set_status(f"シード値 {self.project.seed} の曲を再現しました。")

    def arrange_accompaniment(self):
        """盤面のメロディに合わせて他パート (ベース・サブ・リズム) を自動生成する。"""
        from ..core.arranger import has_only_melody, melody_notes
        if not melody_notes(self.project):
            self.set_status("メロディがありません。メロディ (パート1) を置いてから「🎸 伴奏づけ」を押してください。")
            return
        if not has_only_melody(self.project) and not self.confirm(
                "伴奏づけ", "メロディ以外のパートは作り直されます。続けますか?"):
            return
        new_project = actions.arrange_accompaniment(self.project)
        self.commit(new_project)
        self.set_status("メロディに合わせて伴奏を付けました。曲調・シードを変えると雰囲気が変わります。")

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
        self.set_status(f"鼻歌から {len(notes)} 音のメロディを置きました。"
                        "「🎸 伴奏づけ」で伴奏も付けられます。")

    # ==============================
    # フォト音階 (写真から音階を取り込む)
    # ==============================

    def photo_compose(self):
        """写真を選んで四角形を解析し、ダイアログで確認してから取り込む。"""
        if self.silent:
            return
        path = filedialog.askopenfilename(
            title="写真を選ぶ",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.ppm"), ("すべて", "*.*")])
        if not path:
            return
        self.set_status("写真を解析中…")

        def work():
            return analyze_photo(path)

        def done(result):
            grid, quads, photo = result
            if not quads:
                self.alert("四角形が見つかりませんでした。\n"
                           "被写体 (紙・カードなど) と背景の明暗差をはっきりさせてください。")
                return
            self.set_status(f"四角形を {len(quads)} 個検出しました。内容を確認してください。")
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
            self.set_status("写真の音階で作曲しました。曲調に「📷 フォト音階」が追加されています。")
        else:
            self.set_status("曲調に「📷 フォト音階」を追加しました。この音だけで作曲してみましょう。")

    # ==============================
    # パターンとソング
    # ==============================

    def save_current_pattern(self):
        slot = actions.free_pattern_slot(self.project)
        if slot == -1:
            self.alert("パターンが一杯です (最大 8 個)。ソング画面で不要なものを削除してください。")
            return
        self.commit(actions.save_pattern(self.project, slot))
        self.selected_pattern = slot
        self._update_palette()
        self.set_status(f"パターン F{slot + 1} に登録しました。ソング画面で配置できます。")

    def select_pattern(self, slot):
        if self.project.patterns[slot].used:
            self.selected_pattern = slot
            self._update_palette()
            self.set_status(f"F{slot + 1} を選択中。マスをクリックで配置。")

    def load_selected_pattern(self):
        slot = self.selected_pattern
        if slot == -1 or not self.project.patterns[slot].used:
            self.set_status("先にパターンを選んでください。")
            return
        if self.confirm("読込", f"編集中のフレーズを F{slot + 1} で置き換えますか?"):
            self.commit(actions.load_pattern(self.project, slot))
            self.switch_tab("phrase")
            self.set_status(f"F{slot + 1} を編集画面へ読み込みました。")

    def delete_selected_pattern(self):
        slot = self.selected_pattern
        if slot == -1 or not self.project.patterns[slot].used:
            self.set_status("先にパターンを選んでください。")
            return
        if self.confirm("削除", f"パターン F{slot + 1} を削除しますか?\nソング構成からも取り除かれます。"):
            self.commit(actions.delete_pattern(self.project, slot))
            self.selected_pattern = next(
                (i for i, p in enumerate(self.project.patterns) if p.used), -1)
            self._update_palette()

    def song_click(self, track, block):
        if self.selected_pattern == -1:
            self.set_status("先に上のパレットからパターンを選んでください。")
            return
        self.commit(actions.toggle_song_cell(self.project, track, block, self.selected_pattern))

    def song_erase(self, track, block):
        self.commit(actions.erase_song_cell(self.project, track, block))

    def generate_song_auto(self):
        """1 曲ぶんの自動作成 — 新しいシード値でパターンと構成を丸ごと作る。"""
        touched = (used_blocks(self.project.song) > 0
                   or any(p.used for p in self.project.patterns[:4]))
        if touched and not self.confirm(
                "ソング自動作成",
                "パターン 1〜4 とソング構成を作り直します。続けますか?\n(パターン 5〜8 は残ります)"):
            return
        seed = random.randint(SEED_MIN, SEED_MAX)
        p = actions.set_seed(self.project, seed)
        self.commit(actions.generate_song(p), full=True)
        self.selected_pattern = 1  # Aメロを選んでおく
        self._update_palette()
        self.set_status(f"シード値 {seed} で 1 曲作りました。"
                        "イントロ→Aメロ→Bメロ→アウトロの構成です。▶ で聴いてみましょう。")

    def clear_song(self):
        if used_blocks(self.project.song) == 0:
            return
        if self.confirm("クリア", "ソング構成をすべて消しますか?\n(パターン自体は残ります)"):
            self.commit(actions.clear_song(self.project))

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
            self.set_status("ソングが空です。パレットからフレーズを配置してください。")
            return False
        if mode == "phrase" and count_notes(self.project.phrase) == 0:
            self.set_status("フレーズが空です。音符を置くか ✨ 自動作成 を試してください。")
            return False
        return True

    def _render_loop_pcm(self, mode, project) -> bytes:
        if mode == "phrase":
            return render_phrase_loop(project)
        return render_song_loop(project)

    def _loop_ticks(self, mode, project) -> int:
        return phrase_ticks(project) if mode == "phrase" else song_ticks(project)

    def start_playback(self, mode):
        if self.render_busy or self.silent or not self._playable(mode):
            return
        project = self.project
        button = self.play_phrase_btn if mode == "phrase" else self.play_song_btn
        button.configure(text="⏳ 準備中…")
        self.render_busy = True

        def work():
            return self._render_loop_pcm(mode, project)

        def done(pcm):
            self.render_busy = False
            self._begin_loop(pcm, mode, project.bpm,
                             self._loop_ticks(mode, project), offset_tick=0.0)
            self.play_hint_var.set("")
            self.set_status("ループ再生中。編集するとリアルタイムで反映されます。Space か ■ で停止。")

        self._run_bg(work, done, button)

    def _begin_loop(self, pcm, mode, bpm, ticks, offset_tick):
        """PCM をループ再生する。offset_tick から始まるよう回転して再生位置を合わせる。"""
        spt = samples_per_tick(bpm)
        offset_tick %= ticks
        offset_samples = int(offset_tick * spt)
        if offset_samples:
            pcm = rotate_pcm(pcm, offset_samples)
        wav = wav_bytes(pcm)
        path = storage.write_play_wav("play", wav)
        self.player.play_file(path, loop=True)
        duration = (len(wav) - 44) / 2 / SAMPLE_RATE
        self.clock.start(duration, offset_seconds=offset_tick * tick_seconds(bpm))
        self.play_mode = mode
        self.play_bpm = bpm
        self.play_ticks = ticks
        self._sync_play_buttons()

    def _sync_play_buttons(self):
        self.play_phrase_btn.configure(
            text="■ 停止" if self.play_mode == "phrase" else "▶ 再生")
        self.play_song_btn.configure(
            text="■ 停止" if self.play_mode == "song" else "▶ ソング再生")

    def stop_playback(self):
        if self._live_token is not None:
            self.root.after_cancel(self._live_token)
            self._live_token = None
        self.player.stop()
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
            self.set_status("盤面が空になったので停止しました。")
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
                self.set_status(f"エラー: {box['error']}")
                return
            done(box["result"])

        poll()

    # ==============================
    # 入出力
    # ==============================

    def do_save(self):
        storage.save_text(self.autosave_file, dumps(self.project))
        self.saved_snapshot = dumps(self.project)
        self.set_status(f"保存しました → {self.autosave_file}")

    def do_load(self):
        text = storage.load_text(self.autosave_file)
        if text is None:
            self.set_status("保存データがまだありません。")
            return
        self._load_text(text, f"読み込みました ← {self.autosave_file}")

    def do_export(self):
        path = self._ask_save_path("プロジェクトを書き出す", "picoseq_project.json",
                                   [("PicoSeq プロジェクト", "*.json")])
        if not path:
            return
        storage.save_text(Path(path), dumps(self.project))
        self.set_status(f"書き出しました → {path}")

    def do_import(self):
        path = None if self.silent else filedialog.askopenfilename(
            title="プロジェクトを取り込む",
            filetypes=[("プロジェクト JSON (旧版も可)", "*.json"), ("すべて", "*.*")])
        if not path:
            return
        text = storage.load_text(Path(path))
        if text is None:
            self.alert("ファイルを読めませんでした。")
            return
        self._load_text(text, f"取り込みました ← {path}")

    def _load_text(self, text, ok_message):
        try:
            project = loads(text)
        except LoadError as error:
            self.alert(str(error))
            return
        if not self.confirm("読込", "現在の内容を置き換えます。よろしいですか?"):
            return
        self.stop_playback()
        self.project = project
        self.history = History()
        self.saved_snapshot = dumps(project)
        self.selected_pattern = next(
            (i for i, p in enumerate(project.patterns) if p.used), -1)
        self.refresh_all()
        self.set_status(ok_message)

    def do_export_wav(self, mode):
        project = self.project
        if mode == "song" and used_blocks(project.song) == 0:
            self.alert("ソングが空です。先にフレーズを配置してください。")
            return
        if mode == "phrase" and count_notes(project.phrase) == 0:
            self.alert("フレーズが空です。")
            return
        name = "picoseq_song.wav" if mode == "song" else "picoseq_phrase.wav"
        path = self._ask_save_path("WAV を書き出す", name, [("WAV 音声", "*.wav")])
        if not path:
            return
        self.set_status("WAV を書き出し中…")

        def work():
            pcm = render_song(project) if mode == "song" else render_phrase(project)
            return wav_bytes(pcm)

        def done(wav):
            Path(path).write_bytes(wav)
            seconds = (len(wav) - 44) / 2 / SAMPLE_RATE
            self.set_status(f"書き出しました → {path} ({seconds:.1f} 秒)")

        self._run_bg(work, done)

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
            messagebox.showwarning(TITLE, message)

    def on_close(self):
        if dumps(self.project) != self.saved_snapshot and not self.silent:
            answer = messagebox.askyesnocancel(TITLE, "終了する前に保存しますか?")
            if answer is None:
                return
            if answer:
                self.do_save()
        self.stop_playback()
        self.root.destroy()

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

            # パート・スライダー・各コンボの配線
            self.switch_tab("phrase")
            self.select_part(2)
            self._on_tone_change("70")
            self._on_gate_change("40")
            assert self.project.parts[2].tone == 70
            assert self.project.parts[2].gate == 40

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

            # 保存 → 読込の往復
            self.do_save()
            saved = self.project
            self.clear_phrase()
            self.do_load()
            assert self.project == saved

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
            assert "フォト音階" in self._scale_labels()[-1]
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
            if not self.confirm("拍子の変更", "拍子を変えるとソング構成はリセットされます。続けますか?"):
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
        label = theme.SOUND_LABELS[sound]
        self.set_status(f"音色を「{label}」に変えました。背景も衣替えしています。")

    def _apply_theme(self, sound):
        """パレットを切り替えて画面全体を作り直す (曲データはそのまま)。"""
        theme.set_palette(sound)
        for child in self.root.winfo_children():
            child.destroy()
        self.root.configure(bg=theme.BG)
        self._build_ui()
        self.switch_tab(self.tab, stop=False)  # 再生は止めない
        self.refresh_all()

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
        self.tweak(actions.set_part_tone(self.project, self.part, int(float(value))))

    def _on_gate_change(self, value):
        if self._syncing:
            return
        self.tweak(actions.set_part_gate(self.project, self.part, int(float(value))))


def _load_demo(app):
    """デモ用に一曲ぶんの中身を入れる (スクリーンショット・体験用)。"""
    app.project = actions.set_seed(app.project, 42)
    app.project = actions.generate_phrase(app.project)
    app.project = actions.save_pattern(app.project, 0)
    app.project = actions.set_scale(app.project, "battle")
    app.project = actions.set_seed(app.project, 7)
    app.project = actions.generate_phrase(app.project)
    app.project = actions.save_pattern(app.project, 1)
    app.project = actions.load_pattern(app.project, 0)
    for track, block, pid in [(0, 0, 0), (0, 1, 0), (0, 2, 1), (0, 3, 1),
                              (1, 0, 0), (1, 2, 1), (3, 1, 1)]:
        app.project = actions.toggle_song_cell(app.project, track, block, pid)
    app.selected_pattern = 0
    app.history = History()
    app.refresh_all()
    import os
    if os.environ.get("PICOSEQ_DEMO_TAB") == "song":
        app.switch_tab("song")
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
    # 画面に収まる大きさで開く
    root.update_idletasks()
    width = min(root.winfo_reqwidth() + 8, root.winfo_screenwidth() - 60)
    height = min(root.winfo_reqheight() + 8, root.winfo_screenheight() - 100)
    root.geometry(f"{width}x{height}+30+30")
    root.minsize(880, 560)
    root.mainloop()
    return 0
