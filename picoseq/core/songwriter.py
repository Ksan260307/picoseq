"""ソング自動作成 — 1 曲ぶんの構成を丸ごと組み立てる。

シード値から 4 種類のパターンを作り、16 ブロックに並べる:

  イントロ … Aメロからメロディを抜いた導入 (残すパートはシード値で変わる)
  Aメロ    … メインのフレーズ
  Bメロ    … 別のシード値で作った対比フレーズ (コード進行も別になる)
  アウトロ … リズムを抜いた余韻 (残すパートはシード値で変わる)

**構成そのものもシード値で選ぶ**。ここが定数だと、フレーズは毎回変わるのに
曲の設計図が一つしかなく、どのシードでも同じ展開の曲になってしまう。
並び 6 種 × イントロ 3 種 × アウトロ 3 種 = 54 通りの曲の形がある。
すべて純粋関数で、同じ設定からは常に同じ曲ができる。
"""

from .composer import compose
from .constants import WAVE_NOISE, WAVE_PULSE, WAVE_SAW, WAVE_TRIANGLE
from .phrase import active_notes, build_phrase
from .prng import Rng

# B メロ用のシード値のずらし幅 (同じシード値でも A と B が別の曲想になる)
B_SEED_OFFSET = 7919

# 構成を選ぶ乱数のずらし幅。フレーズ生成と同じ種を使うと
# 「この並びのときはいつもこの曲想」という相関が出るので離しておく。
LAYOUT_SEED_OFFSET = 104729

SONG_BLOCKS = 16


def _layout(*sections):
    """(パターン番号, ブロック数) の列を 16 ブロックの並びへ展開する。"""
    out = []
    for pattern_id, count in sections:
        out.extend([pattern_id] * count)
    return tuple(out)


# 16 ブロックの並び (値はパターン番号 0..3)。
# どれも イントロで始まりアウトロで終わる。A と B の出方で曲の性格が変わる。
SONG_LAYOUTS = (
    # 王道 — イントロ → A×4 → B → A → B → A → アウトロ
    _layout((0, 2), (1, 4), (2, 2), (1, 2), (2, 2), (1, 2), (3, 2)),
    # AABA — A を長く聴かせてから B へ
    _layout((0, 1), (1, 4), (2, 2), (1, 4), (2, 2), (1, 1), (3, 2)),
    # 交互 — A と B を 2 ブロックずつ行き来する
    _layout((0, 2), (1, 2), (2, 2), (1, 2), (2, 2), (1, 2), (2, 2), (3, 2)),
    # B 主体 — B メロを主役にする (サビ先行)
    _layout((0, 1), (2, 2), (1, 2), (2, 4), (1, 2), (2, 3), (3, 2)),
    # 長いイントロ — 土台だけで 4 ブロック引っぱる
    _layout((0, 4), (1, 4), (2, 2), (1, 2), (2, 2), (3, 2)),
    # 畳みかけ — 後半で B を連打して押し切る
    _layout((0, 1), (1, 2), (2, 2), (1, 2), (2, 4), (1, 3), (3, 2)),
)

# 旧称。既存の保存データや外部参照のために王道の並びを指しておく。
SONG_LAYOUT = SONG_LAYOUTS[0]

# イントロで残すパート。メロディは必ず外す (主役は A メロで初めて出す)。
INTRO_PARTS = (
    frozenset({WAVE_TRIANGLE, WAVE_NOISE}),            # 土台だけ
    frozenset({WAVE_NOISE}),                           # リズムのみで静かに立ち上げる
    frozenset({WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW}),  # 和音も入れて厚く始める
)

# アウトロで残すパート。リズムは必ず外す (余韻にするため)。
OUTRO_PARTS = (
    frozenset({WAVE_PULSE, WAVE_TRIANGLE}),            # 旋律と土台
    frozenset({WAVE_PULSE}),                           # 旋律だけを残す
    frozenset({WAVE_PULSE, WAVE_TRIANGLE, WAVE_SAW}),  # 和音を敷いて終わる
)

PATTERN_ROLES = ("イントロ", "Aメロ", "Bメロ", "アウトロ")


def filter_waves(buffer: tuple, waves) -> tuple:
    """指定パートの音符だけを残したバッファを返す。"""
    kept = [note for _, note in active_notes(buffer) if note.wave in waves]
    return build_phrase(kept)


def song_shape(seed: int):
    """シード値から (並び, イントロのパート, アウトロのパート) を選ぶ。純粋関数。"""
    rng = Rng(seed + LAYOUT_SEED_OFFSET)
    layout = SONG_LAYOUTS[rng.next_int(len(SONG_LAYOUTS))]
    intro = INTRO_PARTS[rng.next_int(len(INTRO_PARTS))]
    outro = OUTRO_PARTS[rng.next_int(len(OUTRO_PARTS))]
    return layout, intro, outro


def write_song(beats: int, key: int, scale_id: str, seed: int,
               progression=None, custom=None):
    """(パターン 4 つのバッファ, 16 ブロックの並び) を返す。純粋関数。"""
    layout, intro_parts, outro_parts = song_shape(seed)
    melody_a = compose(beats, key, scale_id, seed, progression, custom)
    melody_b = compose(beats, key, scale_id, seed + B_SEED_OFFSET,
                       progression, custom)
    intro = filter_waves(melody_a, intro_parts)
    outro = filter_waves(melody_a, outro_parts)
    return (intro, melody_a, melody_b, outro), layout
