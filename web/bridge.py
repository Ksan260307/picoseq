"""ブラウザ版の橋渡し — JavaScript から呼ぶ薄い API。

**作曲・合成は core をそのまま使う**。ここが持つのは
「今の Project を覚えておく」「JS が扱える形 (JSON と bytes) に直す」だけ。
状態の変更はすべて core.actions の純粋関数を通すので、
デスクトップ版とまったく同じ音・同じ再現性になる。

画面 (tkinter) はブラウザで動かないので、描画とイベントは JS 側にある。
ここは tkinter を一切 import しない (import できない環境で動くのが前提)。
"""

import json

from picoseq.core import actions
from picoseq.core.constants import (
    BEATS_MAX, BEATS_MIN, BPM_MAX, BPM_MIN, MAX_NOTES, PART_COUNT,
    PITCH_MAX, PITCH_MIN, SEED_MAX, SEED_MIN, WAVE_NOISE,
)
from picoseq.core.music import (
    KEY_NAMES, SCALE_IDS, SCALES, chord_at, note_name,
)
from picoseq.core.note import SOFT_GAIN, SOFT_LEVELS
from picoseq.core.phrase import active_notes, count_notes, find_note_at
from picoseq.core.project import new_project, part_params, steps_of
from picoseq.core.renderer import render_phrase, render_phrase_loop
from picoseq.core.schedule import phrase_ticks, tick_seconds
from picoseq.core.serialize import dumps, loads
from picoseq.core.wavio import wav_bytes

# ブラウザでの合成は純 Python (numpy 無し) なので、負荷を半分にするため
# 22.05kHz で鳴らす。チップチューンでは違いが分かりにくい。
WEB_RATE = 22050

_state = {"project": new_project(), "part": 0}


# ---- 情報 (起動時に 1 回だけ渡す) ----

def catalog() -> str:
    """選択肢と定数をまとめて JSON で返す (JS 側の初期化用)。"""
    return json.dumps({
        "scales": [{"id": s, "label": SCALES[s]["label"]}
                   for s in SCALE_IDS],
        "keys": list(KEY_NAMES),
        "parts": ["メロディ", "ベース", "リズム", "サブ"],
        "beats": list(range(BEATS_MIN, BEATS_MAX + 1)),
        "bpm": [BPM_MIN, BPM_MAX],
        "seed": [SEED_MIN, SEED_MAX],
        "pitch": [PITCH_MIN, PITCH_MAX],
        "softGain": list(SOFT_GAIN),
        "softLevels": SOFT_LEVELS,
        "maxNotes": MAX_NOTES,
        "rate": WEB_RATE,
    }, ensure_ascii=False)


def snapshot() -> str:
    """今の状態を JSON で返す。描画に必要なものだけを詰める。"""
    project = _state["project"]
    steps = steps_of(project)
    notes = [{"slot": slot, "pitch": n.pitch, "step": n.step, "wave": n.wave,
              "dur": min(n.dur, steps - n.step), "soft": n.soft}
             for slot, n in active_notes(project.phrase) if n.step < steps]
    return json.dumps({
        "scale": project.scale,
        "key": project.key,
        "beats": project.beats,
        "bpm": project.bpm,
        "seed": project.seed,
        "part": _state["part"],
        "steps": steps,
        "notes": notes,
        "count": count_notes(project.phrase),
        "progression": progression_text(),
        "tickSeconds": tick_seconds(project.bpm),
        "loopTicks": phrase_ticks(project),
    }, ensure_ascii=False)


def progression_text() -> str:
    """使われたコード進行を Am→F→C→G の形にする。"""
    from picoseq.core.composer import chosen_progression
    project = _state["project"]
    prog = project.progression or chosen_progression(
        project.scale, project.seed, project.custom_scale)
    half = project.beats * 2
    names = []
    for index in range(len(prog)):
        chord = chord_at(project.key, project.scale, index * half,
                         project.beats, prog, project.custom_scale)
        root = note_name(chord.root)[:-1]
        minor = (chord.third - chord.root) % 12 == 3
        names.append(root + ("m" if minor else ""))
    return "→".join(names)


def pitch_label(pitch: int) -> str:
    """鍵盤の表示名。"""
    return note_name(pitch)


# ---- 設定を変える ----

def set_scale(scale_id: str):
    """曲調を変える。"""
    _state["project"] = actions.set_scale(_state["project"], scale_id)


def set_key(key: int):
    """キーを変える。"""
    _state["project"] = actions.set_key(_state["project"], int(key))


def set_beats(beats: int):
    """拍子を変える。"""
    _state["project"] = actions.set_beats(_state["project"], int(beats))


def set_bpm(bpm: int):
    """テンポを変える。"""
    _state["project"] = actions.set_bpm(_state["project"], int(bpm))


def set_seed(seed: int):
    """シード値を変える (曲は作り直さない)。"""
    _state["project"] = actions.set_seed(_state["project"], int(seed))


def select_part(part: int):
    """編集するパートを選ぶ。"""
    _state["part"] = max(0, min(PART_COUNT - 1, int(part)))


# ---- 作る・編集する ----

def generate(seed=None):
    """自動作成。seed 省略なら今のシード値で作る。"""
    project = _state["project"]
    if seed is not None:
        project = actions.set_seed(project, int(seed))
    _state["project"] = actions.generate_phrase(project)
    return _state["project"].seed


def surprise(scale_id: str, key: int, beats: int, bpm: int, seed: int):
    """サプライズ — 曲調・キー・拍子・テンポ・シードをまとめて設定して作る。

    どの値を引くかは JS 側 (乱数) が決め、ここは受け取って適用するだけ。
    こうしておくと「同じ値を入れれば同じ曲」がブラウザでも崩れない。
    """
    project = actions.set_scale(_state["project"], scale_id)
    project = actions.set_key(project, int(key))
    project = actions.set_beats(project, int(beats))
    project = actions.set_bpm(project, int(bpm))
    project = actions.set_seed(project, int(seed))
    _state["project"] = actions.generate_phrase(project)


def toggle_note(pitch: int, step: int):
    """その位置に音符が無ければ置き、あれば消す。置いたら True。"""
    project = _state["project"]
    wave = _state["part"]
    pitch, step = int(pitch), int(step)
    slot = find_note_at(project.phrase, pitch, step, wave, 0)
    if slot != -1:
        _state["project"] = actions.erase_note(project, slot)
        return False
    project, slot = actions.place_note(project, pitch, step, wave)
    if slot == -1:
        return False        # 満杯
    _state["project"] = project
    return True


def resize_note(pitch: int, step: int, dur: int):
    """その位置の音符の長さを変える (ドラッグで伸ばす)。"""
    project = _state["project"]
    slot = find_note_at(project.phrase, int(pitch), int(step), _state["part"], 0)
    if slot == -1:
        return
    _state["project"] = actions.resize_note(project, slot, int(dur))


def cycle_soft(pitch: int, step: int):
    """音の強さを 1 段回す (Shift+クリック相当)。"""
    project = _state["project"]
    slot = find_note_at(project.phrase, int(pitch), int(step), _state["part"], 0)
    if slot == -1:
        return -1
    _state["project"], soft = actions.cycle_note_soft(project, slot)
    return soft


def clear_part():
    """選択中のパートの音符を消す。"""
    _state["project"] = actions.clear_part(_state["project"], _state["part"])


def clear_all():
    """盤面を空にする。"""
    _state["project"] = actions.clear_phrase(_state["project"])


def transpose(semitones: int):
    """フレーズ全体を移調する。"""
    _state["project"] = actions.transpose(_state["project"], int(semitones))


def reverse():
    """フレーズを時間反転する。"""
    _state["project"] = actions.reverse_phrase(_state["project"])


def arrange():
    """メロディに合わせて他パートを付ける (伴奏づけ)。"""
    _state["project"] = actions.arrange_accompaniment(_state["project"])


def set_part_tone(tone: int):
    """選択中パートの音色 (質感) を変える。"""
    _state["project"] = actions.set_part_tone(
        _state["project"], _state["part"], int(tone))


def set_part_gate(gate: int):
    """選択中パートの長さ (ゲート) を変える。"""
    _state["project"] = actions.set_part_gate(
        _state["project"], _state["part"], int(gate))


def part_settings() -> str:
    """選択中パートの音色・長さ・音量を JSON で返す。"""
    params = part_params(_state["project"], _state["part"], 0)
    return json.dumps({"tone": params.tone, "gate": params.gate,
                       "volume": params.volume})


# ---- 音 ----

def loop_pcm() -> bytes:
    """ループ再生用の生 PCM (16bit モノラル)。長さはちょうど 1 周。"""
    return render_phrase_loop(_state["project"], rate=WEB_RATE)


def wav_download() -> bytes:
    """ダウンロード用の WAV (余韻付き)。"""
    return wav_bytes(render_phrase(_state["project"], rate=WEB_RATE),
                     rate=WEB_RATE)


# ---- 保存・復元 ----

def export_json() -> str:
    """プロジェクトを JSON 文字列にする (デスクトップ版と同じ形式)。"""
    return dumps(_state["project"])


def import_json(text: str) -> bool:
    """JSON 文字列から読み込む。読めなければ False (今の状態は壊さない)。"""
    from picoseq.core.serialize import LoadError
    try:
        project = loads(text)
    except LoadError:
        return False
    _state["project"] = project
    return True
