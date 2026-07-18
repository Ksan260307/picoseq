"""自動作成 — シード付きの決定論的な作曲器。

同じ (拍子, キー, スケール, シード) からは常に同じフレーズが生まれる。
コード進行の上に ベース → サブ → リズム → メロディ の順で 4 パートを重ねる。

パートごとに多数の「演奏スタイル」を用意し、シード値でその組み合わせを選ぶ。
  ベース  6 種 × 伴奏 5 種 × リズム 6 種 × メロディのリズム 4 種 × 展開 3 種
= 4000 通り超の下地に、各パートの音選びの乱数が乗る。
"""

from .constants import (
    PITCH_MAX,
    PITCH_MIN,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
    steps_per_phrase,
)
from .music import chord_at, root_note, scale_pitches
from .note import Note
from .phrase import build_phrase
from .prng import Rng

DRUM_PITCH = 60  # リズムは音程を持たない (描画位置として使う)

# 各パートのスタイル数 (シード値で 1 つ選ぶ)
BASS_STYLES = 6
BACKING_STYLES = 5
DRUM_STYLES = 6
MELODY_RHYTHMS = 4
MOTIF_MODES = 3


def compose(beats: int, key: int, scale_id: str, seed: int,
            progression=None, custom=None) -> tuple:
    """フレーズを生成してバッファ (タプル) を返す。純粋関数。

    progression でカスタムコード進行、custom でフォト音階 (音程列) を差し込める。
    """
    notes = _compose_notes(beats, key, scale_id, seed, progression, custom,
                           with_melody=True)
    return build_phrase(notes)


def accompany_notes(beats: int, key: int, scale_id: str, seed: int,
                    progression=None, custom=None) -> list:
    """メロディを除く伴奏 (ベース・サブ・リズム) の Note 列を返す。純粋関数。

    盤面のメロディに他パートを付ける「自動伴奏」で使う。
    """
    return _compose_notes(beats, key, scale_id, seed, progression, custom,
                          with_melody=False)


def _compose_notes(beats, key, scale_id, seed, progression, custom, with_melody):
    """パート生成の共通処理。生成順 (ベース→サブ→リズム→メロディ) は保つ。"""
    rng = Rng(seed)
    steps = steps_per_phrase(beats)
    notes = []

    def emit(pitch, step, wave, dur):
        dur = min(dur, steps - step)
        if PITCH_MIN <= pitch <= PITCH_MAX and dur >= 1:
            notes.append(Note(pitch, step, wave, dur))

    def chord_of(step):
        return chord_at(key, scale_id, step, beats, progression, custom)

    # シード値ごとに演奏スタイルを選ぶ (曲の性格が大きく変わる)
    bass_style = rng.next_int(BASS_STYLES)
    backing_style = rng.next_int(BACKING_STYLES)
    drum_style = rng.next_int(DRUM_STYLES)
    melody_rhythm = rng.next_int(MELODY_RHYTHMS)
    motif_mode = rng.next_int(MOTIF_MODES)

    _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of, bass_style)
    _compose_backing(notes, emit, rng, scale_id, steps, chord_of, backing_style)
    _compose_drums(notes, emit, rng, beats, scale_id, steps, drum_style)
    if with_melody:
        _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of,
                        custom, melody_rhythm, motif_mode)
    return notes


def _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of, style=0):
    """ベース (三角波): 6 種類の型から選ぶ。曲調で細部が変わる。"""
    msteps = beats * 4
    half = max(2, msteps // 2)
    drive = scale_id == "battle"  # 激しい曲は隙間を詰める
    for step in range(steps):
        chord = chord_of(step)
        hit = False
        pitch = chord.root - 12
        dur = 1
        pos = step % msteps

        if beats == 3 and style not in (2, 5):
            # 3拍子は素直な型を優先 (ワルツ感)
            if pos == 0:
                hit, dur = True, 2
            elif pos == 4 and rng.chance(0.6):
                hit, pitch = True, chord.fifth - 12
        elif style == 0:
            # ペダル: 根音を長めに置く土台
            if pos == 0:
                hit, dur = True, max(2, half)
            elif pos == half:
                hit, pitch, dur = True, chord.fifth - 12, 2
            elif drive and step % 2 == 0:
                hit = True
        elif style == 1:
            # 根音と5度の交互 (4分)
            if step % 4 == 0:
                hit, dur = True, 2
                pitch = (chord.root if (step // 4) % 2 == 0 else chord.fifth) - 12
            elif drive and step % 2 == 0:
                hit, pitch = True, chord.fifth - 12
        elif style == 2:
            # 歩くベース: 8分で 根音→根音→5度→3度
            if step % 2 == 0 or drive:
                hit = True
                cycle = (chord.root, chord.root, chord.fifth, chord.third)
                pitch = cycle[(step // 2) % 4] - 12
                if pos == 0:
                    dur = 2
        elif style == 3:
            # オクターブ跳ね: 低い根音と高い根音を往復
            if step % 2 == 0:
                hit = True
                pitch = chord.root - 12 if step % 4 == 0 else chord.root
        elif style == 4:
            # シンコペーション: 表拍を抜いて裏で押す
            if pos == 0:
                hit, dur = True, 2
            elif step % 4 == 3 and rng.chance(0.8):
                hit, pitch = True, chord.fifth - 12
            elif step % 2 == 1 and rng.chance(0.4):
                hit, pitch = True, chord.third - 12
        else:
            # アルペジオ・ベース: 小節をかけて 根音→3度→5度→8度
            if step % 2 == 0 or drive:
                hit = True
                arp = (chord.root, chord.third, chord.fifth, chord.root + 12)
                pitch = arp[(step // 2) % 4] - 12

        if pitch < PITCH_MIN:
            pitch += 12
        if hit:
            emit(pitch, step, WAVE_TRIANGLE, dur)


def _compose_backing(notes, emit, rng, scale_id, steps, chord_of, style=0):
    """サブ (ノコギリ波): 5 種類の和音の添え方。"""
    for step in range(steps):
        chord = chord_of(step)
        hit = False
        pitch = chord.root
        dur = 1

        if scale_id == "japanese" and style not in (2, 3):
            # 和風は間を活かして薄く
            if step % 4 == 2:
                hit = True
                pitch = chord.root if rng.chance(0.5) else chord.fifth
                dur = 2
        elif style == 0:
            # 裏打ちの刺し込み
            if step % 2 == 1 and rng.chance(0.8):
                hit = True
                pitch = chord.third if rng.chance(0.5) else chord.fifth
        elif style == 1:
            # 上行アルペジオ (8分)
            if step % 2 == 0 and rng.chance(0.9):
                hit = True
                arp = (chord.root, chord.third, chord.fifth, chord.root + 12)
                pitch = arp[(step // 2) % 4]
        elif style == 2:
            # 上下アルペジオ
            if step % 2 == 0:
                hit = True
                arp = (chord.root, chord.third, chord.fifth, chord.third)
                pitch = arp[(step // 2) % 4]
        elif style == 3:
            # 持続パッド: 半小節ごとに和音の芯を伸ばす
            if step % 4 == 0:
                hit, dur = True, 3
                pitch = chord.third if (step // 4) % 2 else chord.fifth
        else:
            # シンコペーションの刺し (16分の裏)
            if step % 4 == 1 or step % 4 == 3:
                if rng.chance(0.7):
                    hit = True
                    pitch = chord.fifth if step % 4 == 1 else chord.third

        if pitch < PITCH_MIN:
            pitch += 12
        if hit:
            emit(pitch, step, WAVE_SAW, dur)


def _compose_drums(notes, emit, rng, beats, scale_id, steps, style=0):
    """リズム (ノイズ): 6 種類のドラムパターン。小節頭は必ず芯を置く。"""
    msteps = beats * 4
    heavy = scale_id == "battle"
    for step in range(steps):
        hit = False
        dur = 1
        pos = step % msteps

        if scale_id == "japanese" and style not in (3, 5):
            # 和風の太鼓: 小節頭に長い一打
            if pos == 0:
                hit, dur = True, 4
            elif pos == msteps - 2:
                hit = True
        elif pos == 0:
            hit, dur = True, 2  # どのスタイルも小節頭は必ず鳴らす
        elif style == 0:
            # 標準ロック
            if step % 4 == 0:
                hit, dur = True, 2
            elif step % 2 == 0 and rng.chance(0.5):
                hit = True
            elif rng.chance(0.1):
                hit = True
        elif style == 1:
            # 細かい 8分
            if step % 4 == 0:
                hit, dur = True, 2
            elif rng.chance(0.6 if not heavy else 0.85):
                hit = True
        elif style == 2:
            # ハーフタイム: 半小節のスネアが主役
            if pos == msteps // 2:
                hit, dur = True, 2
            elif step % 4 == 0 and rng.chance(0.5):
                hit = True
        elif style == 3:
            # 四つ打ち: すべての拍頭
            if step % 4 == 0:
                hit, dur = True, 2
            elif step % 2 == 0 and rng.chance(0.3):
                hit = True
        elif style == 4:
            # ブレイクビート: 裏拍を強調
            if step % 4 == 2:
                hit, dur = True, 2
            elif step % 2 == 1 and rng.chance(0.6):
                hit = True
            elif rng.chance(0.2):
                hit = True
        else:
            # まばら: 芯だけ残す
            if pos == msteps // 2:
                hit, dur = True, 2
            elif step % 4 == 0 and rng.chance(0.3):
                hit = True

        if heavy and not hit and step % 2 == 0 and rng.chance(0.5):
            hit = True  # 激しい曲は隙間を埋める
        if hit:
            emit(DRUM_PITCH, step, WAVE_NOISE, dur)


def _onset_prob(step, msteps, rhythm):
    """メロディのリズム型ごとに、そのステップで音を出す確率を返す。

    rhythm 0: なめらか (表拍中心) / 1: 弾む (裏拍多め) /
           2: 引き延ばし (音数少なめ) / 3: 細かい (16分多め)
    """
    on_beat = step % 4 == 0
    off_beat = step % 2 == 1
    if rhythm == 0:
        return 0.9 if on_beat else (0.35 if not off_beat else 0.15)
    if rhythm == 1:
        return 0.85 if on_beat else (0.7 if off_beat else 0.4)
    if rhythm == 2:
        return 0.85 if on_beat else 0.12
    return 0.9 if on_beat else 0.6  # rhythm 3: 細かい


def _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of,
                    custom=None, rhythm=0, motif_mode=0):
    """メロディ (パルス波): 1小節目でモチーフを作り、2小節目で展開して終止する。

    rhythm でリズムの型、motif_mode で 2 小節目の展開の仕方が変わる。
      motif_mode 0: そのまま反復 / 1: 全体を音階内で上へずらす (シーケンス) /
                 2: 山を上下反転 (ミラー)
    """
    msteps = beats * 4
    melody_notes = [p for p in scale_pitches(key, scale_id, custom=custom)
                    if p >= root_note(key) + 12]
    if not melody_notes:
        return

    prev_index = len(melody_notes) // 2
    center = prev_index
    motif = {}  # step -> (音のインデックス, 長さ)。休符は登録しない。

    step = 0
    while step < steps:
        hit = False
        target = prev_index
        dur = 1
        chord = chord_of(step)

        if step < msteps:
            # 1小節目: リズム型に沿ってモチーフを作る
            rest_prob = 1.0 - _onset_prob(step, msteps, rhythm)
            if scale_id == "japanese":
                rest_prob += 0.15
            if (step + 1) % msteps == 0:
                rest_prob = max(rest_prob, 0.85)

            if rng.next_float() > rest_prob:
                hit = True
                rise = step < msteps // 2  # 前半は上へ、後半は下へ (山なり)
                target = _pick_melody_note(rng, melody_notes, prev_index, chord,
                                           step, rise)
                if rhythm == 2 and rng.chance(0.5):
                    dur = 2  # 引き延ばし型は長い音を好む
                elif rng.chance(0.3) and step % 2 == 0:
                    dur = 2
            if hit:
                motif[step] = (target, dur)
        else:
            in_cadence = step % msteps >= msteps - 4
            if in_cadence:
                # 終止形: ルート音へ着地して伸ばす
                if rng.chance(0.7) and step % 2 == 0:
                    hit = True
                    dur = 4
                    final_chord = chord_of(steps - 1)
                    root_pc = final_chord.root % 12
                    for i, p in enumerate(melody_notes):
                        if p % 12 == root_pc:
                            target = i
                            break
            else:
                # 2小節目: モチーフを展開してからコードトーンへ寄せ直す
                found = motif.get(step % msteps)
                if found is not None:
                    hit = True
                    developed = _develop_motif(found, motif_mode, center,
                                               len(melody_notes))
                    target, dur = _shift_to_chord(melody_notes, developed, chord)

        if hit:
            prev_index = target
            emit(melody_notes[target], step, WAVE_PULSE, dur)
            if dur > 1:
                step += dur - 1
        step += 1


def _develop_motif(motif_entry, mode, center, count):
    """2 小節目でモチーフを展開する。返り値は (音のインデックス, 長さ)。"""
    index, dur = motif_entry
    if mode == 1:
        # シーケンス: 音階内で 2 度上へ持ち上げる
        return min(count - 1, index + 2), dur
    if mode == 2:
        # ミラー: 中心の音を軸に上下を反転する
        return max(0, min(count - 1, 2 * center - index)), dur
    return index, dur  # そのまま反復


def _pick_melody_note(rng, melody_notes, prev_index, chord, step, rise=True):
    """跳躍ペナルティとコードトーンボーナスで次の音を選ぶ。

    rise で旋律の向きを軽く誘導し、山なりの起伏を作る。
    """
    best = prev_index
    best_score = None
    chord_pcs = (chord.root % 12, chord.third % 12, chord.fifth % 12)
    for i, pitch in enumerate(melody_notes):
        jump = abs(i - prev_index)
        penalty = jump * 3 if jump > 4 else jump

        bonus = 0
        pc = pitch % 12
        if pc == chord_pcs[0]:
            bonus = -5
        elif pc == chord_pcs[1] or pc == chord_pcs[2]:
            bonus = -3

        if step % 4 == 0 and bonus == 0:
            penalty += 10  # 拍の頭はコードトーンを強く推す

        if (i > prev_index) == rise and i != prev_index:
            bonus -= 1  # 旋律の起伏 (前半は上行、後半は下行を好む)

        score = penalty + bonus + rng.next_float() * 4
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _shift_to_chord(melody_notes, motif_entry, chord):
    """モチーフの音を、今のコードの構成音のうち最も近い音へ寄せる。"""
    index, dur = motif_entry
    base = melody_notes[index]
    chord_pcs = (chord.root % 12, chord.third % 12, chord.fifth % 12)

    best = index
    best_diff = None
    for i, pitch in enumerate(melody_notes):
        if pitch % 12 in chord_pcs:
            diff = abs(pitch - base)
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best = i
    if best_diff is not None and best_diff <= 4:
        return best, dur
    return index, dur
