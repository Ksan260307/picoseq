"""自動作成 — シード付きの決定論的な作曲器。

同じ (拍子, キー, スケール, シード) からは常に同じフレーズが生まれる。
コード進行の上に ベース → サブ → リズム → メロディ の順で 4 パートを重ねる。

パートごとに多数の「演奏スタイル」を用意し、シード値でその組み合わせを選ぶ。
  ベース 288 種 × 伴奏 100 種 × リズム 208 種 × メロディのリズム 10 種 × 展開 6 種
= 3.5 億通り超の下地に、各パートの音選びの乱数が乗る。

型が数百あるので 1 つずつ手書きせず**軸の直積**で組み立てる
(コード進行を機能和声のひな型から自動生成しているのと同じ考え方)。
  リズム = 骨格 13 × 密度 4 × アクセント 4        = 208 種 (実際に異なる形 200)
  ベース = 動き 8 × 刻み 3 × 変化 6 × 音域 2      = 288 種 (実際に異なる形 288)
  伴奏   = 取り方 5 × 置き方 4 × 長さ 5           = 100 種 (実際に異なる形 100)

軸が直交していれば型が潰れない。過去に踏んだ罠と対策:
  ・**数を稼ぐために音楽性を犠牲にしない**。ベースの刻みに 3/6 を混ぜると重複は
    消えるが、16 ステップの小節を割り切れず土台が拍から浮く。刻みは 2 の冪だけに
    戻し、重複は「音域 (オクターブ)」という音楽的に意味のある軸で稼ぐ。
  ・密度の上限を上げすぎるとノイズ 1 声が「壁」になり骨格の差も埋もれる (上限 0.65)。
  ・アクセントを拍の位置だけで決めると、その位置を叩かない骨格で一度も効かない
    → 「何打目か」でも張るようにしてある。

メロディは型の数ではなく**歌えるか**で決まる。実測して見つかった罠 (_compose_melody):
  ・スコアが跳躍ペナルティだけだと「動かない」が跳躍 0 で常に最安になり、
    同じ音が延々続く。留まるほど高くつく連続ペナルティと上限で切る。
  ・疎なリズム型 (語り・引き延ばし) で発音のサイコロを毎ステップ振ると、
    全部外れて 1〜2 音しか鳴らないフレーズが出る。位置を先に決めて最低数を保証する。
  ・拍頭も裏拍もコードトーンだけにすると安全すぎて歌の輪郭が出ない。
    拍頭は守り、裏拍に経過音を通す。
"""

from .constants import (
    PART_COUNT,
    PITCH_MAX,
    PITCH_MIN,
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
    steps_per_phrase,
)
from . import music as music_mod
from .music import chord_at, progression_choices, root_note, scale_pitches
from .note import Note
from .phrase import build_phrase
from .prng import Rng

DRUM_PITCH = 60  # リズムは音程を持たない (描画位置として使う)

# 各パートのスタイル数 (シード値で 1 つ選ぶ)
# ベースとリズムは「軸の直積」で決まるので、定義から算出する (下部を参照)。
MELODY_RHYTHMS = 10
MOTIF_MODES = 6

# メロディの歌わせ方の調整値。値の由来は _compose_melody の解説を参照。
MELODY_MIN_ONSETS = 3     # 1小節あたりの最低発音数 (疎な型でも「無音のフレーズ」を作らない)
MELODY_RUN_LIMIT = 3      # 同じ音を続けて置ける上限
MELODY_REPEAT_PENALTY = 6  # 同音が続くほど「留まる」を高くする係数
MELODY_PASSING_PROB = 0.35  # 裏拍で経過音 (非コードトーン) を通す確率


def compose(beats: int, key: int, scale_id: str, seed: int,
            progression=None, custom=None) -> tuple:
    """フレーズを生成してバッファ (タプル) を返す。純粋関数。

    progression でカスタムコード進行、custom でフォト音階 (音程列) を差し込める。
    """
    notes = _compose_notes(beats, key, scale_id, seed, progression, custom,
                           with_melody=True)
    return build_phrase(notes)


def compose_layers(beats: int, key: int, scale_id: str, seed: int,
                   layer_counts, progression=None, custom=None) -> tuple:
    """パートごとのレイヤー数を考慮してフレーズを作る。

    layer_counts は各パート (波形) のレイヤー数のタプル。
    レイヤー 0 は従来どおりの 4 パート。1 層目以降は、同じコード進行の上に
    別のシードで重ねる (旋律なら別のフレーズ、伴奏なら別のパターン)。
    """
    base = _compose_notes(beats, key, scale_id, seed, progression, custom,
                          with_melody=True)  # レイヤー 0 (全パート)
    notes = list(base)
    prog = chosen_progression(scale_id, seed, custom, progression)  # base と同じ進行
    for wave in range(PART_COUNT):
        count = layer_counts[wave] if wave < len(layer_counts) else 1
        for layer in range(1, count):
            notes.extend(_compose_extra_layer(wave, layer, beats, key, scale_id,
                                              seed, prog, custom))
    return build_phrase(notes)


def _compose_extra_layer(wave, layer, beats, key, scale_id, seed, prog, custom):
    """1 パートの追加レイヤーを 1 つ作る。そのパートの音だけを返す。"""
    rng = Rng((seed * 7919 + wave * 131 + layer * 977 + 12345) & 0xFFFFFFFF)
    steps = steps_per_phrase(beats)
    out = []

    def emit(pitch, step, w, dur):
        dur = min(dur, steps - step)
        if PITCH_MIN <= pitch <= PITCH_MAX and dur >= 1:
            out.append(Note(pitch, step, w, dur, layer))

    def chord_of(step):
        return chord_at(key, scale_id, step, beats, prog, custom)

    prefs = _style_prefs(scale_id, custom)   # 重ねる層も曲調の得意な型に寄せる
    if wave == WAVE_PULSE:
        _compose_melody(None, emit, rng, beats, key, scale_id,
                        steps, chord_of, custom,
                        _weighted_pick(rng, MELODY_RHYTHMS, prefs["melody"]),
                        rng.next_int(MOTIF_MODES))
    elif wave == WAVE_TRIANGLE:
        _compose_bass(None, emit, rng, beats, scale_id, steps, chord_of,
                      _weighted_pick(rng, BASS_STYLES, prefs["bass"]))
    elif wave == WAVE_NOISE:
        _compose_drums(None, emit, rng, beats, scale_id, steps,
                       _weighted_pick(rng, DRUM_STYLES, prefs["drums"]))
    else:  # WAVE_SAW
        _compose_backing(None, emit, rng, scale_id, steps, chord_of,
                         _weighted_pick(rng, BACKING_STYLES, prefs["backing"]),
                         beats)
    return out


def accompany_notes(beats: int, key: int, scale_id: str, seed: int,
                    progression=None, custom=None) -> list:
    """メロディを除く伴奏 (ベース・サブ・リズム) の Note 列を返す。純粋関数。

    盤面のメロディに他パートを付ける「自動伴奏」で使う。
    """
    return _compose_notes(beats, key, scale_id, seed, progression, custom,
                          with_melody=False)


def _pick_progression(rng, scale_id, custom, progression):
    """進行指定が無ければ、rng の最初の一手でコード進行を選ぶ。

    compose と chosen_progression が同じ結果を返すよう、選択はここに一本化する。
    """
    if progression is not None:
        return tuple(progression)
    choices = progression_choices(scale_id, custom)
    return choices[rng.next_int(len(choices))]


def chosen_progression(scale_id: str, seed: int, custom=None, progression=None) -> tuple:
    """その設定で実際に使われるコード進行を返す (表示用)。

    compose と同じ Rng(seed) の最初の一手を使うので、結果は必ず一致する。
    """
    return _pick_progression(Rng(seed), scale_id, custom, progression)


def _compose_notes(beats, key, scale_id, seed, progression, custom, with_melody):
    """パート生成の共通処理。生成順 (ベース→サブ→リズム→メロディ) は保つ。"""
    rng = Rng(seed)
    steps = steps_per_phrase(beats)
    notes = []

    def emit(pitch, step, wave, dur):
        dur = min(dur, steps - step)
        if PITCH_MIN <= pitch <= PITCH_MAX and dur >= 1:
            notes.append(Note(pitch, step, wave, dur))

    # 進行が指定されていなければ、シード値でコード進行を 1 つ選ぶ
    progression = _pick_progression(rng, scale_id, custom, progression)

    def chord_of(step):
        return chord_at(key, scale_id, step, beats, progression, custom)

    # シード値ごとに演奏スタイルを選ぶ (曲の性格が大きく変わる)。
    # リズムとベースは曲調が得意な型を出やすくする (禁止はしない)。
    prefs = _style_prefs(scale_id, custom)
    bass_style = _weighted_pick(rng, BASS_STYLES, prefs["bass"])
    backing_style = _weighted_pick(rng, BACKING_STYLES, prefs["backing"])
    drum_style = _weighted_pick(rng, DRUM_STYLES, prefs["drums"])
    melody_rhythm = _weighted_pick(rng, MELODY_RHYTHMS, prefs["melody"])
    motif_mode = rng.next_int(MOTIF_MODES)

    _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of, bass_style)
    _compose_backing(notes, emit, rng, scale_id, steps, chord_of, backing_style,
                     beats)
    _compose_drums(notes, emit, rng, beats, scale_id, steps, drum_style)
    if with_melody:
        _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of,
                        custom, melody_rhythm, motif_mode)
    return notes


# ---- ベース (三角波) ---------------------------------------------------------
# こちらも 3 軸の直積で組む: 動き 8 種 × 刻み 5 段 × 変化 5 種 = 200 種
# ・動き … 音程の並び (ペダル/歩き/アルペジオ/半音…)
# ・刻み … どの細かさで置くか (小節 → 16 分)
# ・変化 … 置く位置のずらし方 (素直/シンコペ/付点/裏押し/跳ね)

def _bm_pedal(chord, i):
    """ペダル: 根音を保つ。"""
    return chord.root


def _bm_root_fifth(chord, i):
    """根音と 5 度の往復。"""
    return (chord.root, chord.fifth)[i % 2]


def _bm_walk(chord, i):
    """歩き: 根音→根音→5度→3度。"""
    return (chord.root, chord.root, chord.fifth, chord.third)[i % 4]


def _bm_arp(chord, i):
    """アルペジオ: 根音→3度→5度→8度。"""
    return (chord.root, chord.third, chord.fifth, chord.root + 12)[i % 4]


def _bm_octave(chord, i):
    """オクターブ跳ね。"""
    return chord.root + (12 if i % 2 else 0)


def _bm_chromatic(chord, i):
    """半音経過を挟んで滑り込む。"""
    return (chord.root, chord.root - 1, chord.fifth, chord.fifth - 1)[i % 4]


def _bm_run(chord, i):
    """駆け上がり: 根音→5度→8度→3度。"""
    return (chord.root, chord.fifth, chord.root + 12, chord.third)[i % 4]


def _bm_third(chord, i):
    """3 度を軸にした柔らかい動き。"""
    return (chord.third, chord.root)[i % 2]


_BASS_MOTIONS = (
    _bm_pedal, _bm_root_fifth, _bm_walk, _bm_arp,
    _bm_octave, _bm_chromatic, _bm_run, _bm_third,
)


def _bass_grid(rhythm, msteps):
    """刻みの間隔 (ステップ)。半小節 → 4分 → 8分。

    小節をきれいに割り切る 2 の冪だけを使う。付点 (3/6 ステップ) を混ぜると
    型の重複は減るが、16 ステップの小節を割り切れず小節線で解決しない
    ポリリズムになる。**土台であるベースが拍から浮く**のは避ける。
    (重複はレジスター軸で稼ぐので、ここで無理をしなくてよい)
    """
    return (max(2, msteps // 2), 4, 2)[rhythm]


def _bv_straight(step, pos, grid, msteps):
    """素直: 刻みどおり。"""
    return step % grid == 0


def _bv_synco(step, pos, grid, msteps):
    """シンコペ: 刻みを 1 つ手前へ食い込ませる。

    grid==1 (16 分) では「1 つ手前」が存在しないので、裏 16 分だけを鳴らして
    素直な刻みと必ず違う形にする (degenerate させない)。
    """
    if grid <= 1:
        return step % 2 == 1
    return (step + 1) % grid == 0


def _bv_dotted(step, pos, grid, msteps):
    """付点: 刻みに加えて付点位置 (拍の 1/4 手前) も鳴らす。

    足す位置は奇数ステップにする。偶数だと 8 分刻みに飲み込まれ、
    さらに 7 だとグレース (直前に添える型) と同じ形になってしまう。
    """
    return step % grid == 0 or step % 8 == 5


def _bv_grace(step, pos, grid, msteps):
    """グレース: 刻みの直前に 16 分を添えて二度打ちにする。

    刻みの上乗せなので、どの刻みでも素直な形とは必ず違う。
    """
    return step % grid == 0 or (step + 1) % grid == 0


def _bv_accentup(step, pos, grid, msteps):
    """追い込み: 小節の後半で刻みが詰まって次へ押し出す。

    刻みに小節内の位置を掛け合わせるので、どの刻みでも別の形になる。
    """
    return step % grid == 0 or pos >= msteps * 3 // 4


def _bv_altbar(step, pos, grid, msteps):
    """2 小節フレーズ: 偶数小節は刻み、奇数小節は裏へずらす。

    2 小節周期なので、1 小節周期の型とは原理的に一致しない。
    """
    bar = (step - pos) // max(1, msteps)
    if bar % 2 == 0:
        return step % grid == 0
    return (step + max(1, grid // 2)) % grid == 0


_BASS_VARIATIONS = (_bv_straight, _bv_synco, _bv_dotted, _bv_grace,
                    _bv_altbar, _bv_accentup)

# レジスター (音域): 0 = 低音のまま / 1 = 1 オクターブ上げて中音域で弾ませる。
# 音高が必ず変わるので、同じ打点でも確実に別のパターンになる。
# しかも「土台を張る」「歌わせる」という音楽的に意味のある差になる。
_BASS_REGISTERS = (0, 12)

BASS_MOTION_COUNT = len(_BASS_MOTIONS)
BASS_RHYTHM_COUNT = 3
BASS_VARIATION_COUNT = len(_BASS_VARIATIONS)
BASS_REGISTER_COUNT = len(_BASS_REGISTERS)
_BASS_SUB = BASS_RHYTHM_COUNT * BASS_VARIATION_COUNT * BASS_REGISTER_COUNT


def decode_bass_style(style):
    """style 番号を (動き, 刻み, 変化, 音域) へ分解する。"""
    style %= BASS_MOTION_COUNT * _BASS_SUB
    motion, rest = divmod(style, _BASS_SUB)
    rhythm, rest = divmod(rest, BASS_VARIATION_COUNT * BASS_REGISTER_COUNT)
    variation, register = divmod(rest, BASS_REGISTER_COUNT)
    return motion, rhythm, variation, register


def bass_styles_with_motion(motions):
    """指定した動きを使う style 番号すべて (曲調ごとの得意型に使う)。"""
    wanted = frozenset(motions)
    total = BASS_MOTION_COUNT * _BASS_SUB
    return tuple(s for s in range(total) if decode_bass_style(s)[0] in wanted)


def _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of, style=0):
    """ベース (三角波): 動き×刻み×変化で弾く。1 オクターブ下で鳴らす。"""
    msteps = beats * 4
    drive = scale_id == "battle"      # 激しい曲は隙間を詰める
    motion_i, rhythm_i, variation_i, register_i = decode_bass_style(style)
    motion = _BASS_MOTIONS[motion_i]
    grid = _bass_grid(rhythm_i, msteps)
    onset = _BASS_VARIATIONS[variation_i]
    register = _BASS_REGISTERS[register_i]
    index = 0
    for step in range(steps):
        pos = step % msteps
        hit = False
        dur = 1

        if pos == 0:
            hit = True                # 小節頭は必ず土台を置く
        else:
            hit = onset(step, pos, grid, msteps)

        if drive and not hit and step % 2 == 0 and rng.chance(0.85):
            hit = True

        if hit:
            pitch = motion(chord_of(step), index) - 12 + register
            index += 1
            if pos == 0:
                dur = max(2, min(grid, msteps))   # 頭は少し伸ばす
            elif grid >= 4:
                dur = 2
            while pitch < PITCH_MIN:
                pitch += 12
            emit(pitch, step, WAVE_TRIANGLE, dur)


# ---- 伴奏 (ノコギリ波) -------------------------------------------------------
# ベース・リズムと同じく軸の直積で組む: 和音の取り方 5 × 置き方 4 × 長さ 5 = 100 種
# ・取り方 … どの構成音を鳴らすか (根音/3度/5度/上行アルペジオ/下行アルペジオ)
# ・置き方 … どこに置くか (拍頭/裏/8分/パッド)
# ・長さ   … 1 音の伸ばし方 (短く刺す ⇄ 長く敷く)

def _sb_root(chord, i):
    """根音を保つ (素直な支え)。"""
    return chord.root


def _sb_third(chord, i):
    """3 度で色をつける。"""
    return chord.third


def _sb_fifth(chord, i):
    """5 度で開いた響きに。"""
    return chord.fifth


def _sb_arp_up(chord, i):
    """上行アルペジオ。"""
    return (chord.root, chord.third, chord.fifth, chord.root + 12)[i % 4]


def _sb_arp_down(chord, i):
    """下行アルペジオ。"""
    return (chord.root + 12, chord.fifth, chord.third, chord.root)[i % 4]


_BACKING_VOICINGS = (_sb_root, _sb_third, _sb_fifth, _sb_arp_up, _sb_arp_down)


def _sp_beat(step, pos, msteps):
    """拍頭に置く。"""
    return step % 4 == 0


def _sp_offbeat(step, pos, msteps):
    """裏に置く (スカ/レゲエ風の刻み)。"""
    return step % 4 == 2


def _sp_eighth(step, pos, msteps):
    """8 分で刻む。"""
    return step % 2 == 0


def _sp_pad(step, pos, msteps):
    """半小節ごとに敷く (パッド)。"""
    return pos in (0, msteps // 2)


_BACKING_PLACEMENTS = (_sp_beat, _sp_offbeat, _sp_eighth, _sp_pad)

# 1 音の長さ。長いものは重なって持続音のように響く。
_BACKING_DURS = (1, 2, 3, 4, 6)

BACKING_VOICING_COUNT = len(_BACKING_VOICINGS)
BACKING_PLACEMENT_COUNT = len(_BACKING_PLACEMENTS)
BACKING_DUR_COUNT = len(_BACKING_DURS)
_BACKING_SUB = BACKING_PLACEMENT_COUNT * BACKING_DUR_COUNT


def decode_backing_style(style):
    """style 番号を (取り方, 置き方, 長さ) へ分解する。"""
    style %= BACKING_VOICING_COUNT * _BACKING_SUB
    voicing, rest = divmod(style, _BACKING_SUB)
    placement, dur = divmod(rest, BACKING_DUR_COUNT)
    return voicing, placement, dur


def backing_styles_with_voicing(voicings):
    """指定した和音の取り方を使う style 番号すべて (曲調ごとの得意型に使う)。"""
    wanted = frozenset(voicings)
    total = BACKING_VOICING_COUNT * _BACKING_SUB
    return tuple(s for s in range(total) if decode_backing_style(s)[0] in wanted)


def _compose_backing(notes, emit, rng, scale_id, steps, chord_of, style=0,
                     beats=4):
    """サブ (ノコギリ波): 取り方×置き方×長さで和音を添える。"""
    msteps = beats * 4
    heavy = scale_id == "battle"
    thin = scale_id == "japanese"     # 和風は間を活かして薄く
    voicing_i, placement_i, dur_i = decode_backing_style(style)
    voicing = _BACKING_VOICINGS[voicing_i]
    placed = _BACKING_PLACEMENTS[placement_i]
    hold = _BACKING_DURS[dur_i]
    index = 0
    for step in range(steps):
        pos = step % msteps
        hit = placed(step, pos, msteps)
        if thin and hit and step % 4 != 2 and not rng.chance(0.45):
            hit = False               # 和風は間引いて隙間を作る
        if heavy and not hit and step % 2 == 1 and rng.chance(0.5):
            hit = True                # 激しい曲は裏を刺して厚くする
        if not hit:
            continue
        pitch = voicing(chord_of(step), index)
        index += 1
        while pitch < PITCH_MIN:
            pitch += 12
        emit(pitch, step, WAVE_SAW, hold)


def _at(msteps, fraction):
    """小節を fraction (0..1) で割った位置のステップ。拍子が変わっても崩れない。"""
    return int(msteps * fraction)


def _on(pos, msteps, fractions):
    """pos が fractions のいずれかの位置か。小節単位のパターン用。"""
    return any(pos == _at(msteps, f) for f in fractions)


# ---- リズム (ノイズ) ---------------------------------------------------------
# 200 種を手書きすると保守できないので、**音楽的に意味のある 3 軸の直積**で組む
# (コード進行を機能和声のひな型から自動生成しているのと同じ考え方)。
#   骨格 13 種 × 密度 4 段 × アクセント 4 種 = 208 種
# ・骨格   … 芯の打点がどこに来るか (リズムの正体)
# ・密度   … 芯の隙間をどれだけ埋めるか (抜け ⇄ 詰め)
# ・アクセント … どの打点を長く鳴らすか (ノイズ 1 声なので長さが強弱になる)
# 軸が直交しているので、どの組み合わせも意味のあるリズムになる。

def _sk_beat(step, pos, msteps):
    """拍頭 — 素直な四つ打ちの芯。"""
    return step % 4 == 0


def _sk_eighth(step, pos, msteps):
    """8 分 — 走り続ける刻み。"""
    return step % 2 == 0


def _sk_triplet(step, pos, msteps):
    """3 分割風 — 拍を 3 つに割る位置 (ハネ/シャッフル感)。"""
    return step % 8 in (0, 3, 5)


def _sk_backbeat(step, pos, msteps):
    """バックビート — 2・4 拍だけを張る (拍頭は埋めない)。"""
    return _on(pos, msteps, (0.25, 0.75))


def _sk_halftime(step, pos, msteps):
    """ハーフタイム — 小節を 2 つに割るだけ。"""
    return pos in (0, msteps // 2)


def _sk_offbeat(step, pos, msteps):
    """裏打ち — スカ/レゲエの骨。"""
    return step % 4 == 2


def _sk_clave(step, pos, msteps):
    """ソン・クラーベ (3-2) — ラテンの骨格。"""
    return _on(pos, msteps, (0.0, 0.1875, 0.375, 0.625, 0.75))


def _sk_bossa(step, pos, msteps):
    """ボサノヴァ — 前へ転がる型。"""
    return _on(pos, msteps, (0.0, 0.1875, 0.375, 0.5, 0.6875, 0.875))


def _sk_amen(step, pos, msteps):
    """アーメン — 食い込むシンコペーション。"""
    return _on(pos, msteps, (0.0, 0.1875, 0.375, 0.625, 0.8125))


def _sk_gallop(step, pos, msteps):
    """ギャロップ — 付点で跳ねる疾走感。"""
    return step % 4 in (0, 3)


def _sk_tribal(step, pos, msteps):
    """トライバル — 拍頭と拍終わりを叩く太鼓寄り。"""
    return step % 4 in (0, 3) or step % 8 == 6


def _sk_dnb(step, pos, msteps):
    """ドラムンベース — 頭と 3 拍目裏が軸。"""
    return _on(pos, msteps, (0.0, 0.625)) or step % 8 == 5


def _sk_stutter(step, pos, msteps):
    """スタッター — 2 打ワンセットの反復。"""
    return step % 4 in (0, 1)


_DRUM_SKELETONS = (
    _sk_beat, _sk_eighth, _sk_triplet, _sk_backbeat, _sk_halftime,
    _sk_offbeat, _sk_clave, _sk_bossa, _sk_amen, _sk_gallop,
    _sk_tribal, _sk_dnb, _sk_stutter,
)

# 芯の隙間を埋める確率 (抜け → 詰め)。
# 上限を 0.85 まで上げると 16 分をほぼ全部叩いてしまい、ノイズ 1 声では
# 「シャーという壁」になって骨格の違いも埋もれる。0.65 に抑える。
# (激しい曲だけは別途 heavy の隙間埋めで厚くなる)
_DRUM_FILL = (0.0, 0.2, 0.42, 0.65)


# アクセントは「何打目か (nth)」も使う。拍の位置だけで決めると、その位置を
# 叩かない骨格ではアクセントが一度も出ず、型が潰れてしまうため。

def _acc_down(step, pos, msteps, nth):
    """拍頭を重くする (もっとも素直)。"""
    return 2 if step % 4 == 0 else 1


def _acc_back(step, pos, msteps, nth):
    """2 打ごとに張る (どんな骨格でも必ず効く)。"""
    return 3 if nth % 2 == 1 else 1


def _acc_triple(step, pos, msteps, nth):
    """3 打ごとに張る (3 対 4 のうねりが出る)。"""
    return 3 if nth % 3 == 2 else 1


def _acc_end(step, pos, msteps, nth):
    """小節終わりを重くする (次への煽り)。"""
    return 3 if pos >= _at(msteps, 0.75) else 1


_DRUM_ACCENTS = (_acc_down, _acc_back, _acc_triple, _acc_end)

DRUM_SKELETON_COUNT = len(_DRUM_SKELETONS)
DRUM_DENSITY_COUNT = len(_DRUM_FILL)
DRUM_ACCENT_COUNT = len(_DRUM_ACCENTS)


def decode_drum_style(style):
    """style 番号を (骨格, 密度, アクセント) へ分解する。"""
    style %= DRUM_SKELETON_COUNT * DRUM_DENSITY_COUNT * DRUM_ACCENT_COUNT
    skeleton, rest = divmod(style, DRUM_DENSITY_COUNT * DRUM_ACCENT_COUNT)
    density, accent = divmod(rest, DRUM_ACCENT_COUNT)
    return skeleton, density, accent


def drum_styles_with_skeleton(skeletons):
    """指定した骨格を使う style 番号すべて (曲調ごとの得意型を作るのに使う)。"""
    wanted = frozenset(skeletons)
    total = DRUM_SKELETON_COUNT * DRUM_DENSITY_COUNT * DRUM_ACCENT_COUNT
    return tuple(s for s in range(total) if decode_drum_style(s)[0] in wanted)


# 和風 (陰音階) でも自前の骨格を保つもの。他は太鼓の一打に置き換える。
# 太鼓に馴染む「間のある / 打ち込み系」だけを残す:
# 0 拍頭・2 三分割・4 ハーフタイム・10 トライバル。
# クラーベやボサノヴァは和風の情緒に合わないので太鼓へ倒す。
_JP_KEEP_SKELETONS = frozenset({0, 2, 4, 10})


# ---- 曲調 (性格グループ) ごとに似合うリズム/ベース ---------------------------
# 「禁止」ではなく「出やすくする」重み付け。曲調の性格を出しつつ、
# どの型も出る余地を残してバリエーションを保つ。
# 指定するのは **骨格/動き** の番号。密度・アクセント・刻みは自由に振れるので、
# 型が 200 種あっても表は 11 行のまま済む。

STYLE_WEIGHT = 4        # 得意な骨格が出る確率をこの倍率で上げる

# 骨格: 0拍頭 1八分 2三分割 3バックビート 4ハーフ 5裏打ち 6クラーベ
#       7ボサ 8アーメン 9ギャロップ 10トライバル 11DnB 12スタッター
# 動き: 0ペダル 1根音5度 2歩き 3アルペジオ 4オクターブ 5半音 6駆上がり 7三度
# 取り方: 0根音 1三度 2五度 3上行アルペジオ 4下行アルペジオ
# メロディのリズム: 0なめらか 1弾む 2引き延ばし 3細かい 4付点 5シンコペ
#                  6三連 7語り 8バースト 9前ノリ
_PREFERRED_KINDS = {
    music_mod.FAMILY_BRIGHT: {"drums": (0, 3, 1), "bass": (1, 3, 4),
                              "backing": (0, 3), "melody": (0, 1, 4)},
    music_mod.FAMILY_OPEN: {"drums": (0, 9, 4), "bass": (0, 2, 1),
                            "backing": (2, 3), "melody": (0, 2, 6)},
    music_mod.FAMILY_LYRIC: {"drums": (4, 3), "bass": (0, 7, 1),
                             "backing": (1, 4), "melody": (2, 7, 0)},
    music_mod.FAMILY_SORROW: {"drums": (4, 5, 8), "bass": (0, 5, 7),
                              "backing": (1, 0), "melody": (7, 2, 5)},
    music_mod.FAMILY_EXOTIC: {"drums": (6, 10, 12), "bass": (5, 2, 0),
                              "backing": (4, 1), "melody": (5, 9, 3)},
    music_mod.FAMILY_BLUES: {"drums": (3, 0, 9), "bass": (2, 5, 6),
                             "backing": (2, 1), "melody": (1, 5, 6)},
    music_mod.FAMILY_JAZZ: {"drums": (8, 7, 6), "bass": (2, 5, 3),
                            "backing": (3, 4), "melody": (6, 5, 9)},
    music_mod.FAMILY_DREAM: {"drums": (4, 5, 7), "bass": (0, 7, 3),
                             "backing": (2, 4), "melody": (2, 7, 6)},
    music_mod.FAMILY_FOLK5: {"drums": (10, 0, 4, 6), "bass": (0, 1, 7),
                             "backing": (0, 2), "melody": (2, 7, 0)},
    music_mod.FAMILY_SUNNY5: {"drums": (9, 7, 0), "bass": (4, 3, 1),
                              "backing": (3, 0), "melody": (1, 4, 8)},
    music_mod.FAMILY_FIERCE: {"drums": (1, 2, 11, 8), "bass": (6, 4, 3),
                              "backing": (0, 4), "melody": (3, 8, 4)},
}

# 種別の指定を、実際の style 番号の集合へ展開しておく (毎回計算しない)。
# メロディのリズムは番号がそのまま型なので、指定をそのまま使う。
_PREFERRED = {
    family: {
        "drums": drum_styles_with_skeleton(kinds["drums"]),
        "bass": bass_styles_with_motion(kinds["bass"]),
        "backing": backing_styles_with_voicing(kinds["backing"]),
        "melody": tuple(kinds["melody"]),
    }
    for family, kinds in _PREFERRED_KINDS.items()
}


def _weighted_pick(rng, count, preferred, weight=STYLE_WEIGHT):
    """得意な型を出やすくして 1 つ選ぶ。rng は必ず 1 回だけ消費する。

    禁止はしないので、どの型もいつかは出る (バリエーションを殺さない)。
    """
    pref = frozenset(i for i in preferred if 0 <= i < count)
    total = count + (weight - 1) * len(pref)
    ticket = rng.next_int(total)
    for index in range(count):
        share = weight if index in pref else 1
        if ticket < share:
            return index
        ticket -= share
    return count - 1


_NO_PREFS = {"drums": (), "bass": (), "backing": (), "melody": ()}


def _style_prefs(scale_id, custom=None):
    """その曲調が得意な型 (リズム/ベース/伴奏/メロディ)。未知でも必ず何か返す。"""
    family = music_mod.scale_family(scale_id, custom)
    return _PREFERRED.get(family, _NO_PREFS)


def _compose_drums(notes, emit, rng, beats, scale_id, steps, style=0):
    """リズム (ノイズ): 骨格×密度×アクセントで叩く。小節頭は必ず芯を置く。"""
    msteps = beats * 4
    heavy = scale_id == "battle"
    skeleton, density, accent = decode_drum_style(style)
    core = _DRUM_SKELETONS[skeleton]
    fill = _DRUM_FILL[density]
    accent_of = _DRUM_ACCENTS[accent]
    jp = scale_id == "japanese" and skeleton not in _JP_KEEP_SKELETONS
    nth = 0                       # 小節内で何打目か (アクセントの周期に使う)
    for step in range(steps):
        hit = False
        dur = 1
        pos = step % msteps
        if pos == 0:
            nth = 0

        if jp:
            # 和風の太鼓: 小節頭に長い一打
            if pos == 0:
                hit, dur = True, 4
            elif pos == msteps - 2:
                hit = True
        elif pos == 0:
            hit, dur = True, 2  # どの型でも小節頭は必ず鳴らす
        elif core(step, pos, msteps):
            nth += 1
            hit, dur = True, accent_of(step, pos, msteps, nth)
        elif fill > 0:
            hit = rng.chance(fill)

        if heavy and not hit and step % 2 == 0 and rng.chance(0.5):
            hit = True  # 激しい曲は隙間を埋める
        if hit:
            emit(DRUM_PITCH, step, WAVE_NOISE, dur)


def _onset_prob(step, msteps, rhythm):
    """メロディのリズム型ごとに、そのステップで音を出す確率を返す。

    rhythm 0: なめらか (表拍中心) / 1: 弾む (裏拍多め) /
           2: 引き延ばし (音数少なめ) / 3: 細かい (16分多め) /
           4: 付点・ギャロップ (拍頭と付点位置) / 5: シンコペ (裏拍主役)
    """
    on_beat = step % 4 == 0
    off_beat = step % 2 == 1
    if rhythm == 0:
        return 0.9 if on_beat else (0.35 if not off_beat else 0.15)
    if rhythm == 1:
        return 0.85 if on_beat else (0.7 if off_beat else 0.4)
    if rhythm == 2:
        return 0.85 if on_beat else 0.12
    if rhythm == 3:
        return 0.9 if on_beat else 0.6  # 細かい
    if rhythm == 4:
        # 付点・ギャロップ: 拍頭を強く、拍の直前 (16分裏) を弾ませる
        if on_beat:
            return 0.9
        return 0.6 if step % 4 == 3 else 0.2
    if rhythm == 5:
        # シンコペ: 表拍を抜いて裏拍を主役にする
        if on_beat:
            return 0.4
        return 0.8 if off_beat else 0.5
    if rhythm == 6:
        # 3 連風: 拍を 3 分割する位置に寄せる
        return 0.9 if step % 8 in (0, 3, 5) else 0.15
    if rhythm == 7:
        # 語り: 音数を絞って長く歌わせる
        return 0.7 if on_beat else 0.08
    if rhythm == 8:
        # バースト: 前半に 16 分を固め、後半は休む
        first_half = (step % msteps) < msteps // 2
        if on_beat:
            return 0.9
        return 0.75 if first_half else 0.15
    # rhythm 9: 前ノリ — 拍の直前に食い込んで歌い出す
    if on_beat:
        return 0.55
    return 0.85 if step % 4 == 3 else 0.3


def _melody_onsets(rng, msteps, rhythm, scale_id):
    """1小節目の発音位置を先に決める。

    リズム型の確率で振ったあと、`MELODY_MIN_ONSETS` に足りなければ拍頭から順に補う。
    位置を先に決め切るのは、「語り」「引き延ばし」のような疎な型でサイコロが
    全部外れ、**1〜2音しか鳴らない「メロディの無いフレーズ」**になるのを防ぐため。
    補う順序は固定で乱数を使わないので、再現性は保たれる。
    """
    hits = []
    for step in range(msteps):
        rest_prob = 1.0 - _onset_prob(step, msteps, rhythm)
        if scale_id == "japanese":
            rest_prob += 0.15  # 5音音階は間を活かす
        if step + 1 == msteps:
            rest_prob = max(rest_prob, 0.85)  # 小節の切れ目は空けて息継ぎ
        if rng.next_float() > rest_prob:
            hits.append(step)

    # 数えるのは「2小節目で展開される範囲」の音だけ。小節の終わり 4step のモチーフは
    # 終止形に置き換わるので、そこを埋めてもフレーズの音数は増えない。
    develop_end = max(4, msteps - 4)
    need = MELODY_MIN_ONSETS - sum(1 for s in hits if s < develop_end)
    if need > 0:
        # 補う順序は固定 (拍頭 → 拍の中間 → 残り)。乱数を使わないので再現性は保たれる。
        for step in (list(range(0, develop_end, 4))
                     + list(range(2, develop_end, 4))
                     + list(range(0, msteps, 2))):
            if need <= 0:
                break
            if step not in hits and step + 1 != msteps:
                hits.append(step)
                need -= 1
        hits.sort()
    return hits


def _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of,
                    custom=None, rhythm=0, motif_mode=0):
    """メロディ (パルス波): 1小節目でモチーフを作り、2小節目で展開して終止する。

    rhythm でリズムの型、motif_mode で 2 小節目の展開の仕方が変わる。
      motif_mode 0: そのまま反復 / 1: 上へずらす (上行シーケンス) /
                 2: 山を上下反転 (ミラー) / 3: 下へずらす (下行シーケンス)

    歌い方の制約は 3 つ。いずれも実測で見つかった歌えなさへの対策:
      ・同じ音は `MELODY_RUN_LIMIT` 回までしか続けない。
        跳躍ペナルティだけだと「留まる」が常に最安で、同音連打が延々続いてしまう。
      ・1小節あたり `MELODY_MIN_ONSETS` 音は必ず置く (`_melody_onsets`)。
      ・拍頭はコードトーンを維持したまま、裏拍では経過音を通す。
        全部がコードトーンだと安全すぎて歌の輪郭が出ない。
    """
    msteps = beats * 4
    melody_notes = [p for p in scale_pitches(key, scale_id, custom=custom)
                    if p >= root_note(key) + 12]
    if not melody_notes:
        return

    prev_index = len(melody_notes) // 2
    center = prev_index
    last_index = None  # 直前に鳴らした音のインデックス
    run = 0            # その音が続いている回数
    motif = {}         # step -> (音のインデックス, 長さ)。休符は登録しない。
    passing = set()    # 経過音を置いた step (2小節目でコードトーンへ寄せ直さない)
    onsets = frozenset(_melody_onsets(rng, msteps, rhythm, scale_id))

    step = 0
    while step < steps:
        hit = False
        target = prev_index
        dur = 1
        chord = chord_of(step)

        if step < msteps:
            # 1小節目: 先に決めた発音位置でモチーフを作る
            if step in onsets:
                hit = True
                rise = step < msteps // 2  # 前半は上へ、後半は下へ (山なり)
                as_passing = step % 4 != 0 and rng.chance(MELODY_PASSING_PROB)
                target = _pick_melody_note(rng, melody_notes, prev_index, chord,
                                           step, rise, run, as_passing)
                if rhythm == 2 and rng.chance(0.5):
                    dur = 2  # 引き延ばし型は長い音を好む
                elif rng.chance(0.3) and step % 2 == 0:
                    dur = 2
                if as_passing:
                    passing.add(step)
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
                    if step % msteps in passing:
                        target, dur = developed  # 経過音はそのまま通す
                    else:
                        target, dur = _shift_to_chord(melody_notes, developed,
                                                      chord)

        if hit:
            if target == last_index:
                if run >= MELODY_RUN_LIMIT:
                    # 上限に達した。寄せ直しで同音になった場合もここで解ける。
                    target = _step_away(melody_notes, target, chord)
                    run = 1 if target == last_index else 0
                else:
                    run += 1
            else:
                run = 1
            last_index = target
            prev_index = target
            emit(melody_notes[target], step, WAVE_PULSE, dur)
            if dur > 1:
                step += dur - 1
        step += 1


def _develop_motif(motif_entry, mode, center, count):
    """2 小節目でモチーフを展開する。返り値は (音のインデックス, 長さ)。"""
    index, dur = motif_entry
    if mode == 1:
        # 上行シーケンス: 音階内で 2 度上へ持ち上げる
        return min(count - 1, index + 2), dur
    if mode == 2:
        # ミラー: 中心の音を軸に上下を反転する
        return max(0, min(count - 1, 2 * center - index)), dur
    if mode == 3:
        # 下行シーケンス: 音階内で 2 度下へ落とす
        return max(0, index - 2), dur
    if mode == 4:
        # 拡大: 中心からの距離を広げて起伏を大きくする
        return max(0, min(count - 1, center + (index - center) * 2)), dur
    if mode == 5:
        # 縮小 + 引き延ばし: 起伏を狭めて音を長く歌わせる
        return max(0, min(count - 1, center + (index - center) // 2)), dur + 1
    return index, dur  # そのまま反復


def _pick_melody_note(rng, melody_notes, prev_index, chord, step, rise=True,
                      repeat=0, passing=False):
    """跳躍ペナルティとコードトーンボーナスで次の音を選ぶ。

    rise で旋律の向きを軽く誘導し、山なりの起伏を作る。
    repeat は直前の音が続いている回数。留まるほど高くつくようにして同音連打を抑える
    (跳躍 0 = ペナルティ 0 なので、これが無いと「動かない」が常に最安になる)。
    passing なら経過音として扱い、コードトーン優遇の代わりに順次進行を推す。
    """
    best = prev_index
    best_score = None
    chord_pcs = (chord.root % 12, chord.third % 12, chord.fifth % 12)
    for i, pitch in enumerate(melody_notes):
        jump = abs(i - prev_index)
        penalty = jump * 3 if jump > 4 else jump
        if i == prev_index:
            penalty += MELODY_REPEAT_PENALTY * repeat

        bonus = 0
        pc = pitch % 12
        is_chord = pc in chord_pcs
        if passing:
            if jump == 1:
                bonus = -4  # 隣の音階音へ (コードトーンかどうかは問わない)
        elif pc == chord_pcs[0]:
            bonus = -5
        elif pc == chord_pcs[1] or pc == chord_pcs[2]:
            bonus = -3

        if step % 4 == 0 and not is_chord:
            penalty += 10  # 拍の頭はコードトーンを強く推す

        if (i > prev_index) == rise and i != prev_index:
            bonus -= 1  # 旋律の起伏 (前半は上行、後半は下行を好む)

        score = penalty + bonus + rng.next_float() * 4
        if best_score is None or score < best_score:
            best_score = score
            best = i
    return best


def _step_away(melody_notes, index, chord):
    """同音連打を切るため隣の音階音へ逃がす。コードトーンがあればそちらを選ぶ。"""
    candidates = [i for i in (index + 1, index - 1, index + 2, index - 2)
                  if 0 <= i < len(melody_notes)]
    if not candidates:
        return index  # 音階に音が 1 つしかない (逃げ場が無いのでそのまま)
    chord_pcs = (chord.root % 12, chord.third % 12, chord.fifth % 12)
    for i in candidates:
        if melody_notes[i] % 12 in chord_pcs:
            return i
    return candidates[0]


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


# 軸の直積から決まるスタイル数 (定義の下でしか数えられないのでここで確定させる)
BASS_STYLES = BASS_MOTION_COUNT * _BASS_SUB   # 動き × 刻み × 変化 × 音域
BACKING_STYLES = BACKING_VOICING_COUNT * _BACKING_SUB  # 取り方 × 置き方 × 長さ
DRUM_STYLES = DRUM_SKELETON_COUNT * DRUM_DENSITY_COUNT * DRUM_ACCENT_COUNT
