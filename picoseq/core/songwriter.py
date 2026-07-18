"""ソング自動作成 — 1 曲ぶんの構成を丸ごと組み立てる。

シード値から 4 種類のパターンを作り、16 ブロックに並べる:

  イントロ … Aメロからベースとリズムだけを抜き出した静かな導入
  Aメロ    … メインのフレーズ
  Bメロ    … 別のシード値で作った対比フレーズ
  アウトロ … メロディとベースだけの余韻

構成: イントロ×2 → A×4 → B×2 → A×2 → B×2 → A×2 → アウトロ×2
すべて純粋関数で、同じ設定からは常に同じ曲ができる。
"""

from .composer import compose
from .constants import WAVE_NOISE, WAVE_PULSE, WAVE_TRIANGLE
from .note import is_active, unpack_note
from .phrase import active_notes, build_phrase

# B メロ用のシード値のずらし幅 (同じシード値でも A と B が別の曲想になる)
B_SEED_OFFSET = 7919

# 16 ブロックの並び (値はパターン番号 0..3)
SONG_LAYOUT = (0, 0, 1, 1, 1, 1, 2, 2, 1, 1, 2, 2, 1, 1, 3, 3)

PATTERN_ROLES = ("イントロ", "Aメロ", "Bメロ", "アウトロ")


def filter_waves(buffer: tuple, waves) -> tuple:
    """指定パートの音符だけを残したバッファを返す。"""
    kept = [note for _, note in active_notes(buffer) if note.wave in waves]
    return build_phrase(kept)


def write_song(beats: int, key: int, scale_id: str, seed: int,
               progression=None, custom=None):
    """(パターン 4 つのバッファ, 16 ブロックの並び) を返す。純粋関数。"""
    melody_a = compose(beats, key, scale_id, seed, progression, custom)
    melody_b = compose(beats, key, scale_id, seed + B_SEED_OFFSET,
                       progression, custom)
    intro = filter_waves(melody_a, {WAVE_TRIANGLE, WAVE_NOISE})
    outro = filter_waves(melody_a, {WAVE_PULSE, WAVE_TRIANGLE})
    return (intro, melody_a, melody_b, outro), SONG_LAYOUT
