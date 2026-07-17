"""自動作成 — シード付きの決定論的な作曲器。

同じ (拍子, キー, スケール, シード) からは常に同じフレーズが生まれる。
コード進行の上に ベース → サブ → リズム → メロディ の順で 4 パートを重ねる。
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


def compose(beats: int, key: int, scale_id: str, seed: int,
            progression=None) -> tuple:
    """フレーズを生成してバッファ (タプル) を返す。純粋関数。

    progression でカスタムコード進行 (度数の列) を差し込める。None は既定。
    """
    notes = _compose_notes(beats, key, scale_id, seed, progression, with_melody=True)
    return build_phrase(notes)


def accompany_notes(beats: int, key: int, scale_id: str, seed: int,
                    progression=None) -> list:
    """メロディを除く伴奏 (ベース・サブ・リズム) の Note 列を返す。純粋関数。

    盤面のメロディに他パートを付ける「自動伴奏」で使う。
    """
    return _compose_notes(beats, key, scale_id, seed, progression, with_melody=False)


def _compose_notes(beats, key, scale_id, seed, progression, with_melody):
    """パート生成の共通処理。生成順 (ベース→サブ→リズム→メロディ) は保つ。"""
    rng = Rng(seed)
    steps = steps_per_phrase(beats)
    notes = []

    def emit(pitch, step, wave, dur):
        dur = min(dur, steps - step)
        if PITCH_MIN <= pitch <= PITCH_MAX and dur >= 1:
            notes.append(Note(pitch, step, wave, dur))

    def chord_of(step):
        return chord_at(key, scale_id, step, beats, progression)

    _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of)
    _compose_backing(notes, emit, rng, scale_id, steps, chord_of)
    _compose_drums(notes, emit, rng, beats, scale_id, steps)
    if with_melody:
        _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of)
    return notes


def _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of):
    """ベース (三角波): コードの根音と5度を土台にする。"""
    msteps = beats * 4
    half = max(2, msteps // 2)
    for step in range(steps):
        chord = chord_of(step)
        hit = False
        pitch = chord.root - 12
        dur = 1

        if scale_id == "battle":
            if step % 2 == 0:
                hit = True
                pitch = chord.root - 12 if step % 4 == 0 else chord.fifth - 12
        elif beats == 3:
            if step % msteps == 0:
                hit = True
                dur = 2
            elif step % msteps == 4 and rng.chance(0.5):
                hit = True
                pitch = chord.fifth - 12
        else:
            if step % msteps == 0:
                hit = True
                dur = 2
            elif step % msteps == half:
                hit = True
                pitch = chord.fifth - 12
                dur = 2
            elif step % 2 == 0 and rng.chance(0.3):
                hit = True
                pitch = chord.root - 12 if rng.chance(0.5) else chord.third - 12

        if pitch < PITCH_MIN:
            pitch += 12
        if hit:
            emit(pitch, step, WAVE_TRIANGLE, dur)


def _compose_backing(notes, emit, rng, scale_id, steps, chord_of):
    """サブ (ノコギリ波): 裏打ちやアルペジオで和音感を足す。"""
    for step in range(steps):
        chord = chord_of(step)
        hit = False
        pitch = chord.root
        dur = 1

        if scale_id == "battle":
            hit = True
            arpeggio = (chord.root, chord.third, chord.fifth, chord.root + 12)
            pitch = arpeggio[step % 4]
        elif scale_id == "japanese":
            if step % 4 == 2:
                hit = True
                pitch = chord.root if rng.chance(0.5) else chord.fifth
                dur = 2
        else:
            if step % 2 == 1 and rng.chance(0.8):
                hit = True
                pitch = chord.third if rng.chance(0.5) else chord.fifth

        if pitch < PITCH_MIN:
            pitch += 12
        if hit:
            emit(pitch, step, WAVE_SAW, dur)


def _compose_drums(notes, emit, rng, beats, scale_id, steps):
    """リズム (ノイズ): キック・スネア・ハイハットの型。"""
    msteps = beats * 4
    for step in range(steps):
        hit = False
        dur = 1

        if scale_id == "battle":
            hit = rng.chance(0.7)
            if step % 4 == 0:
                hit = True
                dur = 2
        elif scale_id == "japanese":
            if step % msteps == 0:
                hit = True
                dur = 4
            elif step % msteps == msteps - 2:
                hit = True
        elif beats == 3:
            if step % msteps == 0:
                hit = True
                dur = 2
            if step % msteps in (4, 8) and rng.chance(0.8):
                hit = True
        else:
            if step % msteps == 0:
                hit = True
                dur = 2
            elif step % 4 == 0:
                hit = True
                dur = 2
            elif step % 2 == 0 and rng.chance(0.5):
                hit = True
            elif rng.chance(0.1):
                hit = True

        if hit:
            emit(DRUM_PITCH, step, WAVE_NOISE, dur)


def _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of):
    """メロディ (パルス波): 1小節目でモチーフを作り、2小節目で反復し終止する。"""
    msteps = beats * 4
    melody_notes = [p for p in scale_pitches(key, scale_id) if p >= root_note(key) + 12]
    if not melody_notes:
        return

    prev_index = len(melody_notes) // 2
    motif = {}  # step -> (音のインデックス, 長さ)。休符は登録しない。

    step = 0
    while step < steps:
        hit = False
        target = prev_index
        dur = 1
        chord = chord_of(step)

        if step < msteps:
            # 1小節目: 跳躍を抑えつつコードトーンに寄せてモチーフを作る
            rest_prob = 0.4 if step % 2 != 0 else 0.1
            if scale_id == "japanese":
                rest_prob += 0.2
            if (step + 1) % msteps == 0:
                rest_prob = 0.9

            if rng.next_float() > rest_prob:
                hit = True
                target = _pick_melody_note(rng, melody_notes, prev_index, chord, step)
                if rng.chance(0.3) and step % 2 == 0:
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
                # 2小節目: モチーフを反復し、コードトーンへ寄せ直す
                found = motif.get(step % msteps)
                if found is not None:
                    hit = True
                    target, dur = _shift_to_chord(melody_notes, found, chord)

        if hit:
            prev_index = target
            emit(melody_notes[target], step, WAVE_PULSE, dur)
            if dur > 1:
                step += dur - 1
        step += 1


def _pick_melody_note(rng, melody_notes, prev_index, chord, step):
    """跳躍ペナルティとコードトーンボーナスで次の音を選ぶ。"""
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
