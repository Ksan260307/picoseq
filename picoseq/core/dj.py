"""DJ モード用の純粋関数 — 盤面へノイズ (ハイハット風の刻み・盛り上げロール) を足す。

すべて明示シードから決まる決定論的処理。同じ (音符列, 拍子, レベル, シード) からは
常に同じ結果になる。観測層 (DJ 画面) はこれを使って、生成フレーズにノイズを重ねる。
"""

from array import array

from .constants import MAX_NOTES, MEASURES, WAVE_NOISE, clamp
from .note import Note
from .prng import Rng

NOISE_LAYER = 0
NOISE_PITCH = 55           # ノイズは音程に依存しないので任意 (表示・整合用の固定値)
NOISE_MAX_LEVEL = 4

# レベルごとの刻み間隔 (ステップ): 小さいほど密。
_GAP = (4, 2, 2, 1)


def add_noise(notes, beats: int, level: int, seed: int) -> list:
    """音符列 (Note の並び) にノイズの刻みと盛り上げロールを足した新しい列を返す。

    level 0 なら素通し。1〜4 で密度が上がり、2 以上では最後にロール (追い込み) が入る。
    """
    result = list(notes)
    level = clamp(int(level), 0, NOISE_MAX_LEVEL)
    if level <= 0:
        return result

    steps = beats * 4 * MEASURES
    rng = Rng((int(seed) ^ 0xD1B54A32) & 0xFFFFFFFF)

    hit_steps = set()
    gap = _GAP[level - 1]
    for step in range(0, steps, gap):
        if rng.chance(0.85):            # 少し抜いて機械的になりすぎないように
            hit_steps.add(step)

    if level >= 2:                       # 盛り上げロール: 最後の何ステップかを 16 分で埋める
        roll_len = min(steps, 4 * level)
        for step in range(steps - roll_len, steps):
            hit_steps.add(step)

    for step in sorted(hit_steps):
        if len(result) >= MAX_NOTES:
            break
        result.append(Note(NOISE_PITCH, step, WAVE_NOISE, 1, NOISE_LAYER))
    return result


FILTER_OPEN = 100   # これ以上は素通し (フィルターなし)


def lowpass_pcm(pcm: bytes, level: int) -> bytes:
    """16bit PCM に一次ローパスをかけた新しいバイト列を返す (DJ のフィルター掃引)。

    level は 0 (暗い) 〜 100 (開放 = 素通し)。再生専用の効果で、保存データには影響しない。
    ループを想定し、状態を一巡させてから出力するので継ぎ目が滑らか。整数演算のみで決定論的。
    """
    level = clamp(int(level), 0, FILTER_OPEN)
    if level >= FILTER_OPEN or not pcm:
        return pcm
    samples = array("h")
    samples.frombytes(pcm)
    n = len(samples)
    if n == 0:
        return pcm
    alpha = min(32767, 300 + level * 325)   # 暗い(小)〜開放(大)

    # 継ぎ目をなめらかにするため、末尾側だけ通してフィルタの状態を落ち着かせておく
    # (一次フィルタは短時間で収束するので、全体を 2 度通す必要はない)
    y = 0
    for value in samples[max(0, n - 8192):]:
        y += (value - y) * alpha >> 15
    out = array("h", bytes(2 * n))
    for i in range(n):
        y += (samples[i] - y) * alpha >> 15
        out[i] = 32767 if y > 32767 else (-32768 if y < -32768 else y)
    return out.tobytes()
