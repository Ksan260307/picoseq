"""再生の制御 — 何を鳴らし、いつ差し替え、どこまで進んだかを扱う層。

`PicoSeqApp` が継承する。音を出す仕組み (ストリーム / WAV 再生) は
playback.py・stream.py にあり、ここはその呼び分けと再生位置の管理だけを持つ。
編集中でも止めずに鳴らし続けるため、再レンダリングは裏スレッドで行い、
出来上がったら**再生位置を保ったまま**差し替える。
"""

import threading

from ..core.constants import SAMPLE_RATE
from ..core.phrase import count_notes
from ..core.renderer import render_phrase_loop, render_song_loop
from ..core.schedule import (
    phrase_ticks, samples_per_tick, song_ticks, tick_seconds,
)
from ..core.serialize import dumps
from ..core.song import used_blocks
from ..core.wavio import wav_bytes
from . import storage
from .i18n import t
from .playback import rotate_pcm
from .tuning import LIVE_DEBOUNCE_MS


class TransportMixin:
    """再生・停止・演奏中の反映・再生位置の表示。"""

    # ---- 開始と停止 ----

    def toggle_play(self, mode):
        """再生中なら止め、そうでなければ鳴らす。"""
        if self.play_mode == mode:
            self.stop_playback()
            return
        self.stop_playback()
        self.start_playback(mode)

    def start_playback(self, mode):
        """合成を裏で回し、出来上がったらループ再生を始める。"""
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

    def stop_playback(self):
        """再生を止め、予約していた再レンダリングも取り消す。"""
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

    def _playable(self, mode) -> bool:
        """鳴らす中身があるか。無ければ案内を出して False。"""
        if mode == "song" and used_blocks(self.project.song) == 0:
            self.set_status(t("st_song_empty"))
            return False
        if mode == "phrase" and count_notes(self.project.phrase) == 0:
            self.set_status(t("st_phrase_empty"))
            return False
        return True

    def _still_playable(self, mode) -> bool:
        """演奏中に中身が空になっていないか。"""
        if mode == "phrase":
            return count_notes(self.project.phrase) > 0
        return used_blocks(self.project.song) > 0

    def _render_loop_pcm(self, mode, project) -> bytes:
        """そのモードのループ用 PCM を作る (消音の反映込み)。"""
        mute = self.mute_pairs()
        if mode == "phrase":
            return render_phrase_loop(project, mute=mute)
        return render_song_loop(project, mute=mute)

    def _loop_ticks(self, mode, project) -> int:
        """ループ 1 周の Tick 数。"""
        return phrase_ticks(project) if mode == "phrase" else song_ticks(project)

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
        """再生ボタンの文言を今の状態に合わせる。"""
        self.play_phrase_btn.configure(
            text=t("btn_stop") if self.play_mode == "phrase" else t("btn_play"))
        self.play_song_btn.configure(
            text=t("btn_stop") if self.play_mode == "song" else t("btn_play_song"))
        if hasattr(self, "dj_view"):
            self.dj_view.set_play(self.play_mode == "phrase")

    # ---- 演奏中のリアルタイム反映 ----

    def _schedule_live_rerender(self):
        """編集をまとめて反映するため、少し遅らせて再レンダリングを予約する。"""
        if self.silent:
            return
        if self._live_token is not None:
            self.root.after_cancel(self._live_token)
        self._live_token = self.root.after(LIVE_DEBOUNCE_MS, self._fire_live_rerender)

    def _fire_live_rerender(self):
        """予約された再レンダリングを実行し、再生位置を保ったまま差し替える。"""
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

    # ---- 再生位置の表示 ----

    def _tick_playhead(self):
        """33ms ごとに再生位置を読み、小節:拍の表示と再生線を更新する。"""
        if self.play_mode:
            self._update_playhead()
        if self.tab == "dj" and hasattr(self, "dj_view"):
            self._dj_spin_tick()
        self.root.after(33, self._tick_playhead)

    def _update_playhead(self):
        """今の再生位置を小節:拍として表示し、盤面へ再生線を引く。"""
        position = self.clock.position()
        if position is None:
            return
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

    # ---- 裏スレッド ----

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
