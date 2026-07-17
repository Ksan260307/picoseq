"""固定小数点シンセ — 整数演算のみでサンプル列を生成する。

浮動小数点を使わないため、同じ入力からはどの環境でもビット等価の音が出る。
- 位相: 32bit アキュムレータ
- 音量: Q15 (0..32767)
- ノイズ: 15bit LFSR (ファミコン方式のタップ)
"""

from .constants import SAMPLE_RATE, WAVE_NOISE, WAVE_PULSE, WAVE_SAW, WAVE_TRIANGLE
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


def envelope_segments(wave: int, total: int, rate: int) -> list:
    """(サンプル数, 目標レベル Q15) の列。立ち上がりと減衰の折れ線。"""
    peak = PEAKS[wave]
    if wave == WAVE_TRIANGLE:
        attack = rate * 20 // 1000
    elif wave == WAVE_NOISE:
        attack = rate * 5 // 1000
    else:
        attack = rate * 10 // 1000
    attack = min(attack, max(1, total // 4))
    rest = total - attack

    if wave in (WAVE_PULSE, WAVE_SAW):
        # 早めに落としてから尾を引く 2 段減衰
        first = rest // 4
        return [(attack, peak), (first, peak * 45 // 100), (rest - first, 0)]
    return [(attack, peak), (rest, 0)]


def render_voice(wave: int, pitch: int, dur_samples: int, tone: int, gate: int,
                 rate: int = SAMPLE_RATE) -> list:
    """1 音符ぶんのサンプル列 (int, ±ピーク以内) を返す。純粋関数。"""
    total = voice_samples(dur_samples, gate)
    if total <= 0:
        return []

    if wave == WAVE_NOISE:
        raw = _render_noise(total, tone, rate)
    else:
        millihz = pitch_millihz(pitch)
        if wave == WAVE_TRIANGLE:
            millihz //= 2  # ベースは 1 オクターブ下で鳴らす
        inc = phase_increment(millihz, rate)
        if wave == WAVE_PULSE:
            raw = _render_pulse(total, inc, tone)
        elif wave == WAVE_TRIANGLE:
            raw = _render_filtered(total, inc, _oscillate_triangle, 300 + tone * 30, rate)
        else:
            raw = _render_filtered(total, inc, _oscillate_saw, 500 + tone * 50, rate)

    return _apply_envelope(raw, envelope_segments(wave, total, rate))


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
