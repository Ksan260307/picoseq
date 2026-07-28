"""PicoSeq メインアプリ — 画面の組み立てと配線。

状態の変更は core.actions の純粋関数だけで行い、ここでは
「いつ呼ぶか」「何を描き直すか」「何を鳴らすか」だけを扱う。
"""

import random
import tkinter as tk
from tkinter import messagebox

from ..core import actions
from ..core.constants import (
    MAX_LAYERS,
    MAX_NOTES,
    PART_COUNT,
    PATTERN_COUNT,
    SAMPLE_RATE,
    SEED_MAX,
    SEED_MIN,
)
from ..core.history import History, record, redo, undo
from ..core.music import KEY_NAMES, SCALE_IDS, SCALES, note_name
from ..core.note import unpack_note
from ..core.phrase import count_notes, find_note_at
from ..core.project import layer_count, new_project, part_params
from ..core.renderer import render_preview
from ..core.serialize import dumps, loads
from ..core.song import used_blocks
from . import i18n, storage, theme
from .i18n import soft_label, t
from .builder import UIBuilderMixin
from .fileio import FileIOMixin
from .help import HelpDialog
from .patterns import PatternsMixin
from .photo import PhotoDialog, analyze_photo
from .playback import PlayClock, SoundPlayer
from .stream import create_stream
from .transport import TransportMixin
from .dj_control import DJMixin
from .selftest import SelfTestMixin
from .tuning import SURPRISE_BEATS, surprise_bpm


class PicoSeqApp(UIBuilderMixin, TransportMixin, PatternsMixin, FileIOMixin,
                 DJMixin, SelfTestMixin):
    """画面の配線 — 入力を core.actions へ渡し、結果を各ビューへ反映する。

    実際の仕事は用途ごとのミックスインへ分けてある:
      builder   画面の組み立て / transport 再生の制御
      patterns  パターンとソング構成 / fileio 保存・書き出し
      dj_control DJ モード / selftest 自己診断
    ここに残すのは、状態遷移の入口 (commit/tweak/履歴) と、
    どのビューを描き直すかという調整だけ。
    """

    def __init__(self, root, silent=False):
        """状態・音声・設定を用意してから画面を組み立てる。"""
        self.root = root
        self.silent = silent
        self._init_state()
        self._init_audio()
        self._init_settings()

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

    def _init_state(self):
        """編集の状態 (曲・履歴・選択・未保存フラグ) を初期化する。"""
        self.project = new_project()
        self.history = History()
        self.part = 0       # 選択中のパート (波形 0..3)
        self.layer = 0      # 選択中のレイヤー (そのパート内)
        self.muted = set()  # 消音中の (wave, layer) の集合。再生・WAV に反映
        self.roll_zoom = 1.0   # ピアノロールの拡大率 (画面再構築後も保つ)
        self._fitting = False  # 操作パネルの高さ調整中 (再帰防止)
        self._fit_token = None  # 高さ合わせの予約
        self.selected_pattern = -1
        self.tab = "phrase"
        self._gesture = None
        self._drag_ctx = None
        self._syncing = False
        self._dirty = False          # 未保存の変更があるか
        self.theme_sound = self.project.sound  # 画面に適用中の音色パレット
        self.autosave_file = storage.autosave_path()
        self.saved_snapshot = dumps(self.project)
        self._init_dj()

    def _init_audio(self):
        """音を出す側の準備。使えない環境でも編集はできるようにする。"""
        self.player = SoundPlayer(silent=self.silent)
        # ストリーミング再生 (継ぎ目なしの乗り換え・効果音の重ね)。
        # 使えなければ従来のファイル再生へ落ちる。
        self.stream = create_stream(rate=SAMPLE_RATE)
        self.stream_ok = (not self.silent) and self.stream.open()
        self.clock = PlayClock()
        self.play_mode = None
        self.play_bpm = 120
        self.play_ticks = 1
        self.render_busy = False
        self._live_token = None      # 保留中のリアルタイム再レンダリング
        self._preview_cache = {}

    def _init_settings(self):
        """前回の設定 (言語・拡大率) を読み込む。壊れていても既定へ落ちる。"""
        settings = storage.load_settings()
        i18n.set_lang(settings.get("lang", "ja"))
        try:  # 前回の拡大率を復元 (0.5〜3.0)
            self.roll_zoom = min(3.0, max(0.5, float(settings.get("zoom", 1.0))))
        except (TypeError, ValueError):
            self.roll_zoom = 1.0

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
        """連続操作の終わり。始点と変わっていれば 1 回だけ履歴へ積む。"""
        if self._gesture is not None and dumps(self.project) != self._gesture:
            self.history = record(self.history, self._gesture)
            self._update_undo_buttons()
        self._gesture = None

    def undo_action(self, _event=None):
        """直前の操作を取り消す。"""
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
        """取り消した操作をやり直す。"""
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
    # 画面の更新
    # ==============================

    def _scale_labels(self) -> list:
        """曲調セレクタの選択肢。フォト音階があれば末尾に加わる。"""
        labels = [i18n.scale_label(s, SCALES[s]["label"]) for s in SCALE_IDS]
        if self.project.custom_scale is not None:
            labels.append(t("photo_scale_label"))
        return labels

    def refresh_all(self):
        """画面全体を今の状態に合わせ直す (設定・盤面・一覧すべて)。"""
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
        """音符を編集した後の軽い更新 (盤面と件数だけ)。"""
        self.roll.redraw_notes()
        self.song_view.redraw_cells()
        self._update_palette()
        self._update_placing()
        self._update_counts()
        self._update_undo_buttons()

    def _update_part_buttons(self):
        """パート選択ボタンの見た目を選択中のものに合わせる。"""
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
        """選択中のパートにレイヤーを 1 つ足す。"""
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
        """選択中のレイヤーを消す (1 層目は消せない)。"""
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
        """ステータスの音符数・パターン数・ブロック数を更新する。"""
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
        """マス目に触れたとき、その位置の音名と拍をステータスへ出す。"""
        beats = self.project.beats
        measure = step // (beats * 4) + 1
        beat = step % (beats * 4) // 4 + 1
        self.cell_var.set(t("cell_hint", note=note_name(pitch), measure=measure, beat=beat))

    TABS = ("phrase", "pattern", "song", "dj")

    def switch_tab(self, name, stop=True):
        """タブを切り替える (必要なら再生を止め、その画面を作り直す)。"""
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
        """ドラッグ中の音符の長さを変える。"""
        context = self._drag_ctx
        if context and context.get("mode") == "edge" and dur != context["dur0"]:
            context["moved"] = True
        if self.tweak(actions.resize_note(self.project, slot, dur)):
            self.roll.redraw_notes()

    def roll_release(self):
        """ドラッグ終了。伸ばさずに離した場合は削除として扱う。"""
        context = self._drag_ctx
        self._drag_ctx = None
        if context and context.get("mode") == "edge" and not context["moved"]:
            # 右端をクリックしただけ → 削除 (ドラッグしていない)
            self._gesture = None
            self.commit(actions.erase_note(self.project, context["slot"]))
            return
        self.end_gesture()

    def roll_erase(self, pitch, step):
        """その位置の音符を消す (右クリック)。"""
        slot = find_note_at(self.project.phrase, pitch, step, self.part, self.layer)
        if slot != -1:
            self.commit(actions.erase_note(self.project, slot))

    def roll_cycle_soft(self, pitch, step):
        """Shift+クリック — その音符の強弱を 1 段回す。"""
        slot = find_note_at(self.project.phrase, pitch, step, self.part, self.layer)
        if slot == -1:
            self.set_status(t("st_soft_no_note"))
            return
        project, soft = actions.cycle_note_soft(self.project, slot)
        self.commit(project)
        self.set_status(t("st_soft_changed", level=soft_label(soft)))

    def select_part(self, part):
        """編集するパートを切り替える。"""
        self.part = part
        self.layer = min(self.layer, layer_count(self.project, part) - 1)
        self._sync_part_sliders()
        self._update_part_buttons()
        self._rebuild_layer_bar()
        self.roll.redraw_notes()

    def select_layer(self, layer):
        """編集するレイヤーを切り替える。"""
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
        """消音を変えた後の共通処理 (表示更新と演奏への反映)。"""
        self._update_part_buttons()
        if hasattr(self, "mute_buttons"):
            self._update_mute_buttons()
        self._rebuild_layer_bar()   # レイヤーごとの 🔊/🔇 表示を更新
        self.roll.redraw_notes()
        # DJ 画面からの消音は DJ 側で即反映するので、汎用の再描画は走らせない
        if self.play_mode and self.tab != "dj":
            self._schedule_live_rerender()

    def _sync_part_sliders(self):
        """質感・長さ・音量のスライダーを選択中パートの値に合わせる。"""
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
        """盤面の音符をすべて消す (確認つき)。"""
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
        """フレーズ全体を半音単位で移調する。"""
        new_project = actions.transpose(self.project, semitones)
        if new_project is self.project:
            self.set_status(t("st_no_transpose"))
            return
        self.commit(new_project)
        self.set_status(t("st_transposed_up") if semitones > 0 else t("st_transposed_down"))

    def reverse_phrase_action(self):
        """フレーズを時間方向に反転する。"""
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
        """サプライズ — 曲調・キー・音色・拍子・テンポ・シードに加え、各パートの音色・長さも振る。

        65 種類の曲調から思いがけない組み合わせに出会うための一発ボタン。
        テンポは曲調の性格に合った範囲から選ぶ (ボス戦が 80 BPM にならないように)。
        拍子はソング構成が空のときだけ振る — 拍子を変えるとブロック長が変わり
        構成をリセットせざるを得ないので、組み立て済みの曲を黙って壊さない。
        """
        from ..core.music import scale_family
        scale = random.choice(SCALE_IDS)
        sound = random.choice(theme.SOUND_IDS)
        key = random.randrange(len(KEY_NAMES))
        bpm = random.randint(*surprise_bpm(scale_family(scale)))
        seed = random.randint(SEED_MIN, SEED_MAX)
        p = self.project
        # フォト音階は写真が要るので通常の曲調から選ぶ (SCALE_IDS は通常のみ)
        p = actions.set_scale(p, scale)
        p = actions.set_key(p, key)
        p = actions.set_sound(p, sound)
        if used_blocks(p.song) == 0:
            p = actions.set_beats(p, random.choice(SURPRISE_BEATS))
        p = actions.set_bpm(p, bpm)
        p = actions.set_seed(p, seed)
        p = actions.generate_phrase(p)
        p = self._randomize_voicing(p)     # 各パートの音色・長さもランダムに
        self.commit(p, full=True)
        self._ensure_theme()  # 選ばれた音色に配色を合わせる
        from ..core.music import SCALES as _SCALES
        self.set_status(t("st_surprise",
                          scale=i18n.scale_label(scale, _SCALES[scale]["label"]),
                          sound=i18n.sound_label(sound), key=KEY_NAMES[key],
                          beats=p.beats, bpm=bpm, seed=seed,
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
    # ダイアログと終了
    # ==============================

    def confirm(self, title, message) -> bool:
        """はい/いいえを尋ねる。silent (自己診断) では常に承諾。"""
        if self.silent:
            return True
        return messagebox.askyesno(title, message)

    def alert(self, message):
        """メッセージを知らせる。silent ではステータス行に出すだけ。"""
        self.set_status(message)
        if not self.silent:
            messagebox.showwarning(t("title"), message)

    def cancel_pending(self):
        """予約してある after コールバックをすべて取り消す。

        取り消さずにウィンドウを壊すと、後から発火した予約が
        「invalid command name」を吐く (テストの出力も汚れる)。
        """
        for name in ("_fit_token", "_live_token", "_dj_render_token",
                     "_dj_hist_token"):
            token = getattr(self, name, None)
            if token is not None:
                try:
                    self.root.after_cancel(token)
                except Exception:   # noqa: BLE001 - すでに実行済みなら何もしない
                    pass
                setattr(self, name, None)

    def on_close(self):
        """ウィンドウを閉じる前に、未保存の確認と設定の保存を行う。"""
        if dumps(self.project) != self.saved_snapshot and not self.silent:
            answer = messagebox.askyesnocancel(t("title"), t("st_close_save_q"))
            if answer is None:
                return
            if answer:
                self.do_save()
        self._save_window_settings()
        self.stop_playback()
        self.cancel_pending()
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
        """テンポのスライダーが動いたとき。"""
        if self._syncing:
            return
        self.tweak(actions.set_bpm(self.project, int(float(value))))
        self.bpm_var.set(str(self.project.bpm))

    def _on_beats_change(self):
        """拍子を変えたとき (ソング構成があれば確認する)。"""
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
        """キーを変えたとき。"""
        if self._syncing:
            return
        self.commit(actions.set_key(self.project, self.key_box.current()), full=True)

    def _on_scale_change(self):
        """曲調を変えたとき。"""
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
        """分割バーの位置を読む (取れなければ None)。"""
        try:
            if len(paned.panes()) >= 2:
                return int(paned.sash_coord(0)[1])
        except tk.TclError:
            pass
        return None

    def _place_sash(self, paned, y):
        """分割バーの位置を復元する。"""
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
        """保存しておいたパネルの分割位置を戻す。"""
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
        """シード値の入力欄が変わったとき (範囲外は丸める)。"""
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
        """質感スライダー — 選択中パートの音色を変える。"""
        if self._syncing:
            return
        self.tweak(actions.set_part_tone(self.project, self.part, int(float(value)),
                                         layer=self.layer))

    def _on_gate_change(self, value):
        """長さスライダー — 選択中パートのゲートを変える。"""
        if self._syncing:
            return
        self.tweak(actions.set_part_gate(self.project, self.part, int(float(value)),
                                         layer=self.layer))

    def _on_volume_change(self, value):
        """音量スライダー — 選択中パートの音量を変える。"""
        if self._syncing:
            return
        self.tweak(actions.set_part_volume(self.project, self.part, int(float(value)),
                                           layer=self.layer))


def run(selftest: bool = False, demo: bool = False) -> int:
    """アプリを起動する。selftest なら画面を出さずに自己診断だけ行う。"""
    root = tk.Tk()
    if selftest:
        root.withdraw()
    app = PicoSeqApp(root, silent=selftest)
    if demo:
        from .demo import load_demo
        load_demo(app)
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
