"""固定小数点シンセ — 整数演算のみでサンプル列を生成する。

浮動小数点を使わないため、同じ入力からはどの環境でも完全一致の音が出る。
- 位相: 32bit アキュムレータ
- 音量: Q15 (0..32767)
- ノイズ: 15bit LFSR

音色セット (sound):
  retro8  … 角の立ったピコピコ音 (既定。従来とビット単位で同じ音)
  warm16  … 立ち上がりが柔らかく、こもった丸い音
  clear32 … 1 オクターブ上を薄く重ねた、明るくきらびやかな音
"""

from .constants import (
    DEFAULT_SOUND,
    SAMPLE_RATE,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
)
from .music import pitch_millihz

PHASE_MASK = 0xFFFFFFFF
Q15 = 32767
LFSR_SEED = 0x4A1B  # ノイズの初期状態 (15bit, 非零なら周期 32767)
TWO_PI_Q15 = 205887  # round(2 * pi * 2^15)

# パートごとのピーク音量 (Q15)
PEAKS = {
    WAVE_PULSE: 4915,      # 0.15
    WAVE_TRIANGLE: 9830,   # 0.30
    WAVE_NOISE: 6554,      # 0.20
    WAVE_SAW: 3277,        # 0.10
}


def phase_increment(millihz: int, rate: int) -> int:
    """周波数 (ミリヘルツ) から 1 サンプルあたりの位相増分を求める。"""
    return (millihz << 32) // (rate * 1000)


def alpha_q15(cutoff_hz: int, rate: int) -> int:
    """一次ローパスの係数 (Q15)。alpha ≒ 2*pi*fc/fs を上限付きで使う。"""
    return min(31500, cutoff_hz * TWO_PI_Q15 // rate)


def lfsr_step(state: int) -> int:
    """15bit LFSR を 1 歩進める (bit0 xor bit1 帰還)。"""
    bit = (state ^ (state >> 1)) & 1
    return (state >> 1) | (bit << 14)


def voice_samples(dur_samples: int, gate: int) -> int:
    """発音の実サンプル数。gate (10..100) で 0.25〜1.6 倍に伸縮する (旧版と同じ係数)。"""
    return dur_samples * (15 * gate + 100) // 1000


def envelope_segments(wave: int, total: int, rate: int,
                      sound: str = DEFAULT_SOUND) -> list:
    """(サンプル数, 目標レベル Q15) の列。立ち上がりと減衰の折れ線。"""
    peak = PEAKS[wave]
    if wave == WAVE_TRIANGLE:
        attack = rate * 20 // 1000
    elif wave == WAVE_NOISE:
        attack = rate * 5 // 1000
    else:
        attack = rate * 10 // 1000
    if sound == "warm16":
        attack *= 3  # 柔らかい立ち上がり
    attack = min(attack, max(1, total // 4))
    rest = total - attack

    if wave in (WAVE_PULSE, WAVE_SAW):
        # 早めに落としてから尾を引く 2 段減衰 (warm16/clear32 は減衰を浅く)
        sustain = 45 if sound == "retro8" else 60
        first = rest // 4
        return [(attack, peak), (first, peak * sustain // 100), (rest - first, 0)]
    return [(attack, peak), (rest, 0)]


# ベースの倍音バランス (Q8, 256=等倍)。基音 (≈30–60Hz) はほとんど聞こえず、
# 音量ピークだけを食う。基音を少し下げて空いたヘッドルームを可聴域の倍音へ回すと、
# 全体のピークをほぼ変えずに「聞こえるベース」になる (擬似ベース強調)。
TRI_SUB = 205           # ×1 基音 (÷2 済み)。控えめにしてピークを抑える
TRI_HARMONIC = 120      # ×2 (≈65–120Hz): 低音の下支え
TRI_HARMONIC2 = 84      # ×4 (≈130–250Hz): 小型スピーカーでも聞こえる芯

# 音色セットごとのフィルタ開き具合 (三角波 / ノコギリ波)
_TRI_CUTOFF = {"retro8": (300, 30), "warm16": (300, 30), "clear32": (600, 60)}
_SAW_CUTOFF = {"retro8": (500, 50), "warm16": (300, 25), "clear32": (900, 80)}


def render_voice(wave: int, pitch: int, dur_samples: int, tone: int, gate: int,
                 rate: int = SAMPLE_RATE, sound: str = DEFAULT_SOUND) -> list:
    """1 音符ぶんのサンプル列を返す。純粋関数。sound で音の性格が変わる。"""
    total = voice_samples(dur_samples, gate)
    if total <= 0:
        return []

    raw = _render_raw(wave, pitch, total, tone, rate, sound)
    voice = _apply_envelope(raw, envelope_segments(wave, total, rate, sound))
    if sound == "warm16":
        voice = _soften(voice, 1800 + tone * 40, rate)  # 全体を丸くする仕上げ
    return voice


def _render_raw(wave, pitch, total, tone, rate, sound):
    """音色セットに応じた生波形。retro8 は従来と同一の経路。"""
    if wave == WAVE_NOISE:
        if sound == "warm16":
            tone = min(tone, 25)          # こもった打楽器
        elif sound == "clear32":
            tone = min(100, tone + 15)    # 明るめの打楽器
        return _render_noise(total, tone, rate)

    millihz = pitch_millihz(pitch)
    if wave == WAVE_TRIANGLE:
        millihz //= 2  # ベースは 1 オクターブ下で鳴らす
    inc = phase_increment(millihz, rate)

    if wave == WAVE_PULSE:
        duty_tone = 50 + tone // 2 if sound == "warm16" else tone
        raw = _render_pulse(total, inc, duty_tone)
    elif wave == WAVE_TRIANGLE:
        base, slope = _TRI_CUTOFF[sound]
        cutoff = base + tone * slope
        raw = _render_filtered(total, inc, _oscillate_triangle, cutoff, rate)
        # ベースの基音 (≈30–60Hz) は小型スピーカーではほとんど鳴らず、耳の感度も低い。
        # 深い土台は残したまま、1・2 オクターブ上の倍音を重ねて可聴域に「芯」を作る
        # (擬似ベース強調)。書かれた音の高さは millihz*2 (÷2 済みのため)。
        oct1 = _render_filtered(total, phase_increment(millihz * 2, rate),
                                _oscillate_triangle, cutoff * 2, rate)
        oct2 = _render_filtered(total, phase_increment(millihz * 4, rate),
                                _oscillate_triangle, cutoff * 4, rate)
        raw = [(a * TRI_SUB >> 8) + (b * TRI_HARMONIC >> 8) + (c * TRI_HARMONIC2 >> 8)
               for a, b, c in zip(raw, oct1, oct2)]
    else:
        base, slope = _SAW_CUTOFF[sound]
        raw = _render_filtered(total, inc, _oscillate_saw, base + tone * slope, rate)

    if sound == "clear32" and wave in (WAVE_PULSE, WAVE_SAW):
        # 1 オクターブ上を約 30% で重ね、きらめきを足す
        inc2 = phase_increment(millihz * 2, rate)
        if wave == WAVE_PULSE:
            shadow = _render_pulse(total, inc2, tone)
        else:
            base, slope = _SAW_CUTOFF[sound]
            shadow = _render_filtered(total, inc2, _oscillate_saw, base + tone * slope, rate)
        raw = [a + (b * 77 >> 8) for a, b in zip(raw, shadow)]
    return raw


def _soften(voice: list, cutoff_hz: int, rate: int) -> list:
    """仕上げの一次ローパス (warm16 用)。"""
    alpha = alpha_q15(cutoff_hz, rate)
    y = 0
    out = []
    for v in voice:
        y += (v - y) * alpha >> 15
        out.append(y)
    return out


def _render_pulse(total: int, inc: int, tone: int) -> list:
    """パルス波。tone でデューティ比 12.5%..50% を変える。"""
    threshold = (125 + tone * 375 // 100) * 65536 // 1000  # 16bit 位相での高区間
    out = []
    phase = 0
    for _ in range(total):
        p16 = phase >> 16
        out.append(Q15 if p16 < threshold else -Q15)
        phase = (phase + inc) & PHASE_MASK
    return out


def _oscillate_triangle(p16: int) -> int:
    q = p16 & 32767
    if p16 < 32768:
        return q * 2 - Q15
    return Q15 - q * 2


def _oscillate_saw(p16: int) -> int:
    return p16 - 32768


def _render_filtered(total: int, inc: int, oscillate, cutoff_hz: int, rate: int) -> list:
    """発振してから一次ローパスをかける。"""
    alpha = alpha_q15(cutoff_hz, rate)
    out = []
    phase = 0
    y = 0
    for _ in range(total):
        v = oscillate(phase >> 16)
        y += (v - y) * alpha >> 15
        out.append(y)
        phase = (phase + inc) & PHASE_MASK
    return out


def _render_noise(total: int, tone: int, rate: int) -> list:
    """LFSR ノイズ。tone で低域寄り / 帯域 / 高域寄りに変わる (旧版と同じ区分)。"""
    out = []
    state = LFSR_SEED
    if tone < 30:
        alpha = alpha_q15(100 + tone * 10, rate)
        y = 0
        for _ in range(total):
            state = lfsr_step(state)
            v = Q15 if state & 1 else -Q15
            y += (v - y) * alpha >> 15
            out.append(y)
    elif tone < 70:
        center = 1000 + (tone - 30) * 50
        alpha_low = alpha_q15(max(50, center // 2), rate)
        alpha_high = alpha_q15(center * 2, rate)
        y_low = 0
        y_high = 0
        for _ in range(total):
            state = lfsr_step(state)
            v = Q15 if state & 1 else -Q15
            y_low += (v - y_low) * alpha_low >> 15
            y_high += (v - y_high) * alpha_high >> 15
            out.append(y_high - y_low)  # 帯域通過 = 広いLP - 狭いLP
    else:
        alpha = alpha_q15(5000 + (tone - 70) * 100, rate)
        y = 0
        for _ in range(total):
            state = lfsr_step(state)
            v = Q15 if state & 1 else -Q15
            y += (v - y) * alpha >> 15
            out.append(v - y)  # 高域通過 = 原音 - LP
    return out


def _apply_envelope(raw: list, segments: list) -> list:
    """折れ線エンベロープを整数補間で適用する。"""
    out = []
    pos = 0
    level = 0
    for seg_len, target in segments:
        if seg_len <= 0:
            level = target
            continue
        start = level
        span = target - start
        for i in range(seg_len):
            if pos >= len(raw):
                return out
            amp = start + span * (i + 1) // seg_len
            out.append(raw[pos] * amp >> 15)
            pos += 1
        level = target
    while pos < len(raw):
        out.append(0)
        pos += 1
    return out
