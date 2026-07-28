"""自己診断 (--selftest) を app 本体から切り出した mixin。

GUI を出さずにアプリの配線を一巡させ、壊れていないかを確認する。
PicoSeqApp がこの mixin を継承し、run() から self.self_test() を呼ぶ。
"""

import tempfile
import traceback
from pathlib import Path

from ..core import actions
from ..core import dj as dj_core
from ..core.constants import BEATS_MAX, BEATS_MIN, PART_COUNT, WAVE_PULSE
from ..core.phrase import count_notes
from ..core.project import layer_count, steps_of
from ..core.serialize import dumps
from ..core.song import used_blocks
from . import i18n, storage, theme
from .photo import analyze_photo
from .tuning import SURPRISE_BPM


class SelfTestMixin:
    """アプリ配線の自己診断。"""

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

            # Shift+クリック: 音の強さが 1 段ずつ回り、一周して戻る
            from ..core.note import SOFT_LEVELS, unpack_note
            from ..core.phrase import active_notes as _active
            slot = next(s for s, _ in _active(self.project.phrase))
            assert unpack_note(self.project.phrase[slot]).soft == 0
            for expect in list(range(1, SOFT_LEVELS)) + [0]:
                self.roll_cycle_soft(60, 0)
                assert unpack_note(self.project.phrase[slot]).soft == expect
            self.roll_cycle_soft(72, 5)          # 音符が無い場所は案内を出すだけ
            assert count_notes(self.project.phrase) == 1

            self.roll_press(60, 2)  # 音符の中身クリック → 削除
            assert count_notes(self.project.phrase) == 0
            self.undo_action()
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
            # 音量もパートごとに独立して調整でき、レンダリングにも反映される
            self.dj_set_part_volume(0, WAVE_PULSE, 40)
            self.dj_set_part_volume(0, _WS, 100)
            assert self.dj_decks[0]["volumes"][WAVE_PULSE] == 40
            assert self.dj_decks[0]["volumes"][_WS] == 100
            assert self.project.parts[WAVE_PULSE][0].volume == 40
            self.dj_set_part_volume(0, WAVE_PULSE, 100)

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

            # 呼び戻し: エントリの設定 (パート音色・長さ・音量含む) がデッキへ入り、固定される
            recall = dj_core.make_entry("battle", 9, 96, "clear32", 1, 4242,
                                        tones=(20, 30, 40, 50), gates=(15, 25, 35, 45),
                                        volumes=(60, 70, 80, 90), deck=0)
            self.dj_recall(recall, 1)
            assert self.dj_decks[1]["scale"] == "battle"
            assert self.dj_decks[1]["key"] == 9 and self.dj_decks[1]["bpm"] == 96
            assert self.dj_decks[1]["seed"] == 4242 and self.dj_decks[1]["hold"]
            assert self.dj_decks[1]["tones"] == [20, 30, 40, 50]   # 音色も復元される
            assert self.dj_decks[1]["gates"] == [15, 25, 35, 45]   # 長さも復元される
            assert self.dj_decks[1]["volumes"] == [60, 70, 80, 90]  # 音量も復元される
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
            self._on_volume_change("55")
            assert self.project.parts[2][0].tone == 70
            assert self.project.parts[2][0].gate == 40
            assert self.project.parts[2][0].volume == 55       # パートごとの音量
            # 音量 100 はレンダリング無変化 (完全な no-op)、下げると音が変わる
            from ..core.renderer import render_phrase as _rp, clear_cache as _cc
            _cc(); full = _rp(actions.set_part_volume(self.project, 2, 100))
            _cc(); unit = _rp(actions.set_part_volume(self.project, 2, 100))
            _cc(); down = _rp(actions.set_part_volume(self.project, 2, 30))
            assert full == unit and down != full               # 100=無変化 / 下げると変わる
            self._on_volume_change("100")

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
            # テンポ・拍子・各パートの音色・長さもランダムに振れ、常に有効範囲に収まる
            # (拍子はソング構成が空のときだけ振れるので、先に空にしておく)
            self.commit(actions.clear_song(self.project))
            voicings, tempos, meters, keys = set(), set(), set(), set()
            for _ in range(16):
                self.generate_surprise()
                assert SURPRISE_BPM[0] <= self.project.bpm <= SURPRISE_BPM[1]
                assert self.bpm_var.get() == str(self.project.bpm)  # 表示も追従
                assert BEATS_MIN <= self.project.beats <= BEATS_MAX
                assert self.beats_box.current() + 2 == self.project.beats  # 表示も追従
                assert 0 <= self.project.key <= 11
                assert self.key_box.current() == self.project.key  # 表示も追従
                tempos.add(self.project.bpm)
                meters.add(self.project.beats)
                keys.add(self.project.key)
                for w in range(PART_COUNT):
                    for lyr in self.project.parts[w]:
                        assert 0 <= lyr.tone <= 100 and 25 <= lyr.gate <= 100
                voicings.add(tuple((lyr.tone, lyr.gate)
                                   for w in range(PART_COUNT)
                                   for lyr in self.project.parts[w]))
            assert len(voicings) > 1                        # 質感がランダムに変わる
            assert len(tempos) > 1                          # テンポもランダムに変わる
            assert len(meters) > 1                          # 拍子もランダムに変わる
            assert len(keys) > 1                            # キーもランダムに変わる

            # 組み立て済みのソング構成があるときは拍子を振らない (黙って壊さない)
            self.generate_auto()
            self.save_current_pattern()
            self.switch_tab("song")
            self.song_click(0, 0)
            assert used_blocks(self.project.song) > 0
            kept_beats, kept_song = self.project.beats, self.project.song
            for _ in range(8):
                self.generate_surprise()
                assert self.project.beats == kept_beats   # 拍子は据え置き
                assert self.project.song == kept_song     # 構成も消えない
            self.commit(actions.clear_song(self.project))
            self.switch_tab("phrase")
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
