"""DJ モードのコントローラ (mixin)。

app.py から DJ 関連のメソッドをまとめて切り出したもの。状態は app インスタンス
が持ち (self.dj_decks など)、共有リソース (self.stream / self.clock / self.project)
も app 側にある。PicoSeqApp がこの mixin を継承して使う。
"""

import random
import time
from pathlib import Path
from tkinter import filedialog

from ..core import actions
from ..core import dj as dj_core
from ..core.constants import (
    BPM_MAX, BPM_MIN, MEASURES, PART_COUNT, PITCH_MAX, PITCH_MIN,
    SAMPLE_RATE, SEED_MAX, SEED_MIN, WAVE_PULSE,
)
from ..core.music import KEY_NAMES, SCALE_IDS
from ..core.phrase import count_notes
from ..core.project import layer_count
from ..core.renderer import render_phrase_loop, render_preview
from ..core.schedule import phrase_ticks, tick_seconds
from ..core.wavio import wav_bytes
from . import i18n, storage, theme
from .i18n import t
from .tuning import (
    DJ_ADVANCE_LOOPS, DJ_HISTORY_COMMIT_MS, DJ_RENDER_DEBOUNCE_MS, DJ_SCRATCH_MS,
)


class DJMixin:
    """DJ モードの状態遷移・再生制御。PicoSeqApp が継承する。"""

    def _init_dj(self):
        """DJ モードの状態を初期化する (__init__ から呼ぶ)。"""
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

    @staticmethod
    def _new_dj_deck(scale, seed, bpm, key=0, sound="retro8"):
        """デッキ 1 台ぶんの設定。

        tones/gates = パートごと (メロディ/ベース/リズム/サブ) の音色と長さ。
        音色 0..100 (メロディならパルス波のデューティ比)、長さ 10..100。
        """
        return {"scale": scale, "key": key, "sound": sound, "seed": seed, "bpm": bpm,
                "noise": 0, "tones": [50, 50, 50, 50], "gates": [80, 80, 80, 80],
                "volumes": [100, 100, 100, 100],
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
        for wave in range(PART_COUNT):              # パートごとの音色・長さ・音量 (全レイヤーへ)
            for layer in range(layer_count(p, wave)):
                p = actions.set_part_tone(p, wave, deck["tones"][wave], layer)
                p = actions.set_part_gate(p, wave, deck["gates"][wave], layer)
                p = actions.set_part_volume(p, wave, deck["volumes"][wave], layer)
        if deck["noise"] > 0:
            from ..core.phrase import active_notes, build_phrase
            notes = [n for _, n in active_notes(p.phrase)]
            notes = dj_core.add_noise(notes, p.beats, deck["noise"], seed)
            p = actions.update(p, phrase=build_phrase(notes))
        return p

    # ---- 連続フロー: 事前レンダリング → ループ境界で継ぎ目なく差し替え ----

    def _dj_queue(self, seed=None, immediate=True):
        """操作の結果を作り直す。immediate なら出来次第その場で音に反映する。

        seed 未指定は「今流しているフレーズを、新しいつまみの値で作り直す」意味。
        `_dj_want_seed` は事前レンダリング (_dj_prepare_auto) が**次フレーズ用の
        ランダム値**へ書き換えてしまうので、ここで必ずデッキの現在シードへ戻す。
        これを省くと、つまみを触るだけで未来のフレーズへ飛んでしまい、
        ループ固定も呼び戻しも効かなくなる。
        """
        self._dj_want_seed = seed if seed is not None else self._dj_deck()["seed"]
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
                tuple(deck["volumes"]), deck["filter"], tuple(sorted(deck["muted"])),
                self.dj_active)

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
                                  tones=state["tones"], gates=state["gates"],
                                  volumes=state["volumes"], deck=index)

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
        clean = dj_core.sanitize_entries([entry])[0]   # tones/gates/volumes を 4 個・整数に
        state["tones"] = [max(0, min(100, v)) for v in clean["tones"]]
        state["gates"] = [max(10, min(100, v)) for v in clean["gates"]]
        state["volumes"] = [max(0, min(100, v)) for v in clean["volumes"]]
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
        keys = ("scale", "key", "sound", "bpm", "noise", "tones", "gates", "volumes")
        backup = {k: saved[k] for k in keys}
        clean = dj_core.sanitize_entries([entry])[0]
        try:                                       # 一時的にエントリの設定で組み立てる
            saved.update({k: entry[k] for k in ("scale", "key", "sound", "bpm", "noise")})
            saved["tones"] = list(clean["tones"])
            saved["gates"] = list(clean["gates"])
            saved["volumes"] = list(clean["volumes"])
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

    def dj_set_part_volume(self, deck, wave, volume):
        """パートの音量 (0..100) を変える。デッキごとにミックスのバランスを作れる。"""
        wave = max(0, min(PART_COUNT - 1, int(wave)))
        volume = max(0, min(100, int(volume)))
        if volume == self.dj_decks[deck]["volumes"][wave]:
            return
        self.dj_decks[deck]["volumes"][wave] = volume
        self._dj_changed(deck)
        self.set_status(t("st_dj_part_volume", deck="AB"[deck],
                          part=i18n.part_name(wave), volume=volume))

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
        self.dj_view.sync_next(self._dj_next_text(spinning))

    def _dj_next_text(self, spinning) -> str:
        """「次のフレーズまで N 小節」/「固定中」の案内文。

        自動進行が動いていること、ループ固定が効いていることを目で確認できるようにする。
        """
        if not spinning:
            return ""
        if self._dj_deck()["hold"]:
            return t("dj_held")
        remain_loops = max(0, DJ_ADVANCE_LOOPS - self._dj_loop_count)
        return t("dj_next_in", bars=remain_loops * MEASURES)
