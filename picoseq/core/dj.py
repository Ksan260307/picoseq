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


# ===========================================================================
# 履歴・お気に入り — 「流したフレーズ」を後から呼び戻すための記録
# ===========================================================================
#
# 記録するのは音そのものではなく**フレーズを決める種**だけ。
# (曲調・キー・テンポ・音色・ノイズ・シード) が揃えば同じフレーズが再生成できる
# ので、PCM を溜め込む必要がない。設定ファイルへもそのまま書ける軽さになる。

HISTORY_MAX = 12
FAVORITES_MAX = 12

# エントリの項目 (種別, 既定値)。フレーズと音作りを一意に決めるのはこれ。
# tones/gates = パートごと (メロディ/ベース/リズム/サブ) の音色と長さ。
# 古い設定ファイルには無い項目もあるので、既定値で補える形にしている。
PARTS = 4
_ENTRY_FIELDS = (
    ("scale", "str", "major"),
    ("key", "int", 0),
    ("bpm", "int", 120),
    ("sound", "str", "retro8"),
    ("noise", "int", 0),
    ("tones", "ints4", (50, 50, 50, 50)),   # パートごとの音色 0..100
    ("gates", "ints4", (80, 80, 80, 80)),   # パートごとの長さ 10..100
    ("seed", "int", 1),
)


def _coerce(kind, value, default):
    """設定ファイル由来の値を、種別に応じて安全な型へ直す。壊れていれば既定。"""
    try:
        if kind == "str":
            return str(value)
        if kind == "int":
            return int(value)
        if kind == "ints4":                 # 長さ 4 の整数タプル (足りなければ既定で補う)
            seq = list(value) if isinstance(value, (list, tuple)) else []
            return tuple(int(seq[i]) if i < len(seq) else default[i]
                         for i in range(PARTS))
    except (TypeError, ValueError):
        pass
    return tuple(default) if kind == "ints4" else default


def make_entry(scale, key, bpm, sound, noise, seed,
               tones=(50, 50, 50, 50), gates=(80, 80, 80, 80), deck=0) -> dict:
    """デッキの現在値から履歴エントリを作る。deck は表示用 (同一性には含めない)。"""
    return {"scale": str(scale), "key": int(key), "bpm": int(bpm),
            "sound": str(sound), "noise": int(noise),
            "tones": tuple(int(v) for v in tones),
            "gates": tuple(int(v) for v in gates),
            "seed": int(seed), "deck": int(deck)}


def entry_id(entry) -> tuple:
    """エントリの同一性。deck は含めない — 同じフレーズをどちらで流しても同じもの。"""
    return tuple(_coerce(kind, entry.get(name, default), default)
                 for name, kind, default in _ENTRY_FIELDS)


def push_history(history, entry, limit=HISTORY_MAX) -> list:
    """履歴の先頭へ足した新しいリストを返す (新しい順・上限あり)。

    同じフレーズが既にあれば、古い方を消して先頭へ繰り上げる。つまみを触るたびに
    似たものが並ぶのを防ぎ、「さっきのあれ」を探しやすくする。
    """
    target = entry_id(entry)
    rest = [e for e in history if entry_id(e) != target]
    return [dict(entry)] + rest[:max(0, limit - 1)]


def toggle_favorite(favorites, entry, limit=FAVORITES_MAX):
    """お気に入りの登録／解除。(新しいリスト, 登録したか) を返す。

    上限に達しているときは、いちばん古いものを押し出す。
    """
    target = entry_id(entry)
    rest = [e for e in favorites if entry_id(e) != target]
    if len(rest) != len(favorites):
        return rest, False                       # 既にあった → 解除
    return [dict(entry)] + rest[:max(0, limit - 1)], True


def is_favorite(favorites, entry) -> bool:
    target = entry_id(entry)
    return any(entry_id(e) == target for e in favorites)


def sanitize_entries(raw, limit=FAVORITES_MAX) -> list:
    """設定ファイルから読んだエントリ列を検証して、使える形だけ残す。

    設定ファイルは手で編集できてしまうので、欠けた項目・型違いは既定値で埋め、
    形になっていないものは捨てる。ここで弾いておかないと再生時に落ちる。
    """
    result = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        entry = {}
        for name, kind, default in _ENTRY_FIELDS:
            entry[name] = _coerce(kind, item.get(name, default), default)
        try:
            entry["deck"] = clamp(int(item.get("deck", 0)), 0, 1)
        except (TypeError, ValueError):
            entry["deck"] = 0
        result.append(entry)
        if len(result) >= limit:
            break
    return result
