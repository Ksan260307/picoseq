"""鼻歌の解析 — 録音した声からメロディ (音符の列) を取り出す。

流れ:
  1. 音を 8kHz 相当まで間引き、約 50ms ごとの区間 (フレーム) に分ける
  2. 各フレームの高さを差分関数 (YIN 系) で推定する。声の基本周波数を
     オクターブ違いに取り違えにくく、音量にも左右されない方式。
  3. オクターブの飛びをならし、5 点メディアンで安定させる
  4. 録音全体をフレーズの長さ (ステップ数) に割り付け、
     同じ高さが続く区間を 1 つの音符にまとめる
  5. 音の高さは現在の音階 (キー・曲調) の音へ寄せる

同じ録音からは常に同じメロディが出る。
"""

import math

from .constants import WAVE_PULSE
from .music import scale_pitches
from .note import Note

TARGET_RATE = 8000     # 解析用のサンプリングレート (声の高さ検出には十分)
FRAME_MS = 45
FREQ_MIN = 75          # 検出する声の低さの下限 (Hz)
FREQ_MAX = 600         # 上限
YIN_THRESHOLD = 0.15   # 差分関数がこの値を下回る最初の谷を基本周期とする
CLARITY_MIN = 0.55     # 「声がある」と判定する明瞭度 (1 - 谷の深さ) の下限
ENERGY_RATIO = 0.04    # 最大音量に対してこの比率未満のフレームは休符
OCTAVE_RESIDUAL = 4    # ±12 で畳んで中央値にこの半音以内へ収まるものだけ直す
MELODY_LO = 60         # メロディを収める音域 (C4〜C6)
MELODY_HI = 84


def decimate(samples, rate: int, target: int = TARGET_RATE):
    """ブロック平均で target レートまで間引く。(新サンプル列, 新レート)"""
    factor = max(1, rate // target)
    if factor == 1:
        return list(samples), rate
    out = []
    total = len(samples) // factor * factor
    for i in range(0, total, factor):
        out.append(sum(samples[i:i + factor]) // factor)
    return out, rate // factor


def frame_pitches(samples, rate: int):
    """フレームごとの (MIDI ノート番号 or None) の列。None は休符。"""
    win = rate * FRAME_MS // 1000
    hop = win // 2
    if len(samples) < win:
        return []

    lag_min = max(2, rate // FREQ_MAX)
    lag_max = min(win - 1, rate // FREQ_MIN)
    if lag_max <= lag_min:
        return []

    # まず全フレームのエネルギーを求め、休符のしきい値を決める
    frames = []
    energies = []
    for start in range(0, len(samples) - win + 1, hop):
        frame = samples[start:start + win]
        energies.append(sum(v * v for v in frame))
        frames.append(frame)
    if not frames:
        return []
    gate = max(energies) * ENERGY_RATIO

    pitches = []
    for frame, energy in zip(frames, energies):
        if energy <= gate or energy == 0:
            pitches.append(None)
        else:
            pitches.append(_pitch_of_frame(frame, rate, lag_min, lag_max))
    return _median_smooth(_correct_octaves(pitches))


def _difference(frame, lag_min, lag_max):
    """差分関数 d(τ) = Σ (x[i] - x[i+τ])² を τ=1..lag_max で返す。

    積算窓を全 τ で共通 (先頭 W サンプル) にするため、低音側が不利にならず
    オクターブの取り違えが起きにくい。
    """
    width = len(frame) - lag_max
    d = [0] * (lag_max + 1)
    for tau in range(1, lag_max + 1):
        total = 0
        for i in range(width):
            diff = frame[i] - frame[i + tau]
            total += diff * diff
        d[tau] = total
    return d


def _pitch_of_frame(frame, rate, lag_min, lag_max):
    """1 フレームの高さ (MIDI)。声が無ければ None。"""
    d = _difference(frame, lag_min, lag_max)

    # 累積平均で正規化 (YIN)。d'(τ) = d(τ)·τ / Σ_{j≤τ} d(j)
    d_prime = [1.0] * (lag_max + 1)
    running = 0
    for tau in range(1, lag_max + 1):
        running += d[tau]
        if running > 0:
            d_prime[tau] = d[tau] * tau / running

    # しきい値を下回る最初の谷を選ぶ。無ければ最小値。
    best = -1
    for tau in range(lag_min, lag_max):
        if d_prime[tau] < YIN_THRESHOLD and d_prime[tau] <= d_prime[tau + 1]:
            best = tau
            break
    if best == -1:
        best = min(range(lag_min, lag_max + 1), key=lambda t: d_prime[t])

    if 1 - d_prime[best] < CLARITY_MIN:
        return None

    # 谷の周辺 3 点を放物線補間して精度を上げる
    tau = float(best)
    if lag_min < best < lag_max:
        a, b, c = d_prime[best - 1], d_prime[best], d_prime[best + 1]
        denom = a + c - 2 * b
        if denom != 0:
            shift = 0.5 * (a - c) / denom
            if -1.0 < shift < 1.0:
                tau += shift

    freq = rate / tau
    if not (FREQ_MIN <= freq <= FREQ_MAX):
        return None
    return round(69 + 12 * math.log2(freq / 440.0))


def _correct_octaves(pitches):
    """孤立したオクターブ誤り (スパイク) だけを両隣に合わせて直す。

    両隣がそろって約オクターブ離れているフレームだけを、隣の高さへ ±12 で
    畳む。5 度などの跳躍や、持続するオクターブの移動はそのまま残す。
    """
    out = list(pitches)
    n = len(pitches)
    for i in range(n):
        p = pitches[i]
        if p is None:
            continue
        neighbors = [pitches[j] for j in (i - 1, i + 1)
                     if 0 <= j < n and pitches[j] is not None]
        if not neighbors or not all(abs(nb - p) > OCTAVE_RESIDUAL for nb in neighbors):
            continue  # 隣と近い音は本物の音とみなす
        ref = sorted(neighbors)[len(neighbors) // 2]
        best = min((p + k for k in (-24, -12, 0, 12, 24)),
                   key=lambda c: abs(c - ref))
        if abs(best - ref) <= OCTAVE_RESIDUAL < abs(p - ref):
            out[i] = best
    return out


def _median_smooth(pitches, radius=2):
    """(2·radius+1) 点メディアンで高さのふらつきをならす。"""
    n = len(pitches)
    if n < 2 * radius + 1:
        return pitches
    out = list(pitches)
    for i in range(radius, n - radius):
        if pitches[i] is None:
            continue
        window = [p for p in pitches[i - radius:i + radius + 1] if p is not None]
        if len(window) > radius:  # 過半が有声なら中央値を採る
            out[i] = sorted(window)[len(window) // 2]
    return out


def _trim_silence(pitches):
    """先頭と末尾の休符を取り除く。"""
    start = 0
    end = len(pitches)
    while start < end and pitches[start] is None:
        start += 1
    while end > start and pitches[end - 1] is None:
        end -= 1
    return pitches[start:end]


def pitches_to_notes(pitches, steps: int, key: int, scale_id: str, custom=None):
    """フレーム列をステップに割り付けて音符にまとめる。

    録音全体をフレーズの長さへ引き延ばし (縮め)、同じ高さが続く区間を
    1 つの音符にする。高さは音階の最寄りの音へ寄せ、C4〜C6 に収める。
    """
    pitches = _trim_silence(pitches)
    if not pitches or all(p is None for p in pitches):
        return []

    allowed = scale_pitches(key, scale_id, MELODY_LO, MELODY_HI, custom)
    if not allowed:
        return []

    # 全体の高さの中央値を音域の中心に寄せるオクターブ移動量を決める
    voiced = sorted(p for p in pitches if p is not None)
    median = voiced[len(voiced) // 2]
    offset = 0
    center = (MELODY_LO + MELODY_HI) // 2
    while median + offset < center - 6:
        offset += 12
    while median + offset > center + 6:
        offset -= 12

    # ステップごとの高さ (そのステップに重なるフレームの多数決)
    per_step = []
    total = len(pitches)
    for step in range(steps):
        lo = step * total // steps
        hi = max(lo + 1, (step + 1) * total // steps)
        window = [p for p in pitches[lo:hi] if p is not None]
        if len(window) * 2 <= hi - lo:  # 半分以上が休符なら休符
            per_step.append(None)
            continue
        raw = sorted(window)[len(window) // 2] + offset
        per_step.append(min(allowed, key=lambda a: (abs(a - raw), a)))

    # 連続する同じ高さを 1 音符へ
    notes = []
    step = 0
    while step < steps:
        pitch = per_step[step]
        if pitch is None:
            step += 1
            continue
        dur = 1
        while step + dur < steps and per_step[step + dur] == pitch:
            dur += 1
        notes.append(Note(pitch, step, WAVE_PULSE, dur))
        step += dur
    return notes


def detect_melody(samples, rate: int, steps: int, key: int, scale_id: str,
                  custom=None):
    """録音 (整数サンプル列) からメロディの音符列を作る。純粋関数。"""
    reduced, new_rate = decimate(samples, rate)
    pitches = frame_pitches(reduced, new_rate)
    return pitches_to_notes(pitches, steps, key, scale_id, custom)
