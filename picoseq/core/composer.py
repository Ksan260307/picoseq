"""自動作成 — シード付きの決定論的な作曲器。

同じ (拍子, キー, スケール, シード) からは常に同じフレーズが生まれる。
コード進行の上に ベース → サブ → リズム → メロディ の順で 4 パートを重ねる。

パートごとに多数の「演奏スタイル」を用意し、シード値でその組み合わせを選ぶ。
  ベース 384 種 × 伴奏 600 種 × リズム 208 種 × メロディのリズム 10 種 × 展開 6 種
= 28 億通り超の下地に、各パートの音選びの乱数が乗る。

型が数百あるので 1 つずつ手書きせず**軸の直積**で組み立てる
(コード進行を機能和声のひな型から自動生成しているのと同じ考え方)。

  | パート | 軸 | 型 | 音符列 | **リズム(発音位置)** |
  |---|---|---|---|---|
  | リズム | 骨格13 × 密度4 × アクセント4 | 208 | 200 | 52 |
  | ベース | 動き8 × 刻み3 × 変化8 × 音域2 | 384 | 384 | 24 |
  | 伴奏   | 取り方5 × 置き方4 × 変化6 × 長さ5 | 600 | 110 | 22 |

**型の数とリズムの多様性は別物**。アクセントは音の長さ、動き/音域/取り方は音程を
変えるだけなので、そこを増やしても刻みの形は増えない。「別シードでも同じ刻み」を
減らしたいときはリズムに効く軸 (骨格・密度・置き方・変化) を増やすこと。
  ・伴奏は当初 取り方×置き方×長さ = 100 型あったが、刻みの形は置き方の 4 通りだけ
    だった → 60 シードの全ペアのうち **25% が伴奏の刻み完全一致**。
    ベースと同じ「変化」軸を足して 22 通りにし、一致率は 4.6% まで下がった。

軸が直交していれば型が潰れない。過去に踏んだ罠と対策:
  ・**数を稼ぐために音楽性を犠牲にしない**。ベースの刻みに 3/6 を混ぜると重複は
    消えるが、16 ステップの小節を割り切れず土台が拍から浮く。刻みは 2 の冪だけに
    戻し、重複は「音域 (オクターブ)」という音楽的に意味のある軸で稼ぐ。
  ・密度の上限を上げすぎるとノイズ 1 声が「壁」になり骨格の差も埋もれる (上限 0.65)。
  ・アクセントを拍の位置だけで決めると、その位置を叩かない骨格で一度も効かない
    → 「何打目か」でも張るようにしてある。
  ・**位置を決め打ちで足し引きする変化は、その位置を元から叩く型では何も起きない**
    (伴奏の「追い込み」を 8 分刻みに当てたら完全な無操作だった)。
    変化は置き方そのものを受け取って**変換する**形にしてある。

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
MELODY_SPAN = 24          # メロディに確保する音域の幅 (半音)。キーに依らず一定にする
MOTIF_MIRROR_SPAN = 3     # ミラー展開で元の音から離れられる上限 (音階の度数)
BACKING_MIN_NOTES = 3     # 間引いても伴奏に残す音数 (和音として聞こえる下限)
MELODY_PARALLEL_PENALTY = 3  # ベースと同じ向きに動くことの減点 (反行を取る)
MELODY_UNISON_PENALTY = 4    # ベースと同じ音名になることの減点 (並行オクターブ回避)

# 音符ごとの強弱 (note.SOFT_GAIN の段。0 = 最強)。
# これが無いと、アクセントは音の長さしか変えられず、フレーズの音量が平坦になる
# (実測で 1小節目と2小節目の音量比 1.03 倍 = ほぼ起伏なし)。
SOFT_ACCENT = 0   # アクセント・小節頭
SOFT_CORE = 1     # 芯の打点・拍の頭
SOFT_WEAK = 2     # 裏拍・経過音
SOFT_GHOST = 3    # 埋めの音 (ゴーストノート)


def _bar_of(step, msteps):
    """その step が何小節目か (0 始まり)。"""
    return step // max(1, msteps)


def _styles_with_kind(kinds, kind_count, sub):
    """指定した種類 (骨格/動き/取り方) に属する style 番号すべて。

    style = 種類 * sub + 下位軸 という並びなので、種類 k の型はちょうど
    range(k*sub, (k+1)*sub)。全 style を decode して選り分ける必要はない。
    """
    out = []
    for kind in sorted(frozenset(kinds)):
        if 0 <= kind < kind_count:
            out.extend(range(kind * sub, (kind + 1) * sub))
    return tuple(out)


# ---- 2 小節目の扱い (ベース・伴奏・リズムで共有) -----------------------------
# フレーズは 2 小節。**1 小節目と 2 小節目が同じだと、型をいくら増やしても
# 「同じ 1 小節の繰り返し」にしか聞こえない**。ここで 2 小節目だけを作り変える。
#
# 各パートの軸 (刻み・置き方・骨格) は 1 小節の形しか決めないので、この軸を
# 掛けると**リズムの形がそのまま倍々に増える**。52/24/22 種で頭打ちだった
# 「実際に鳴る形」を 200 種以上へ伸ばしているのは主にこの軸。
#
# 位置を決め打ちで足し引きしてはいけない。その位置を元から叩く型では無操作になり、
# 逆に叩かない型どうしが同じ形へ潰れる (伴奏の変化軸で実際に踏んだ失敗)。
# **その小節の打点リストを受け取り、打点の「何打目か」を基準に作り変える。**
#
# 入力: bar = その小節の打点 (step の昇順リスト), start = 小節の先頭 step
# 出力: 作り変えた step の集合。小節頭は呼び出し側が必ず足すので、
#       ここで消えても構わない (逆に、消しすぎて無音にはならない)。

def _pf_same(bar, start, msteps):
    """そのまま — 2 小節とも同じ形 (これまでの動き)。"""
    return set(bar)


def _pf_thin(bar, start, msteps):
    """間引く — 2 打に 1 打だけ残して問いかけに応える (呼びかけと応答)。"""
    return {step for nth, step in enumerate(bar) if nth % 2 == 0}


def _pf_push(bar, start, msteps):
    """煽る — 後半 1/4 を 16 分で埋めて次の小節へ押し出す。"""
    edge = start + _at(msteps, 0.75)
    out = {step for step in bar if step < edge}
    out.update(range(edge, start + msteps))
    return out


def _pf_shift(bar, start, msteps):
    """もたれ — 打点を 1 ステップ後ろへずらす (小節からは出さない)。"""
    last = start + msteps - 1
    return {min(step + 1, last) for step in bar}


def _pf_echo(bar, start, msteps):
    """二度打ち — 1 打おきに 16 分を添えて跳ねさせる。"""
    out = set(bar)
    last = start + msteps - 1
    out.update(min(step + 1, last) for nth, step in enumerate(bar) if nth % 2)
    return out


def _pf_swap(bar, start, msteps):
    """前後入れ替え — 小節の前半と後半をひっくり返し、1 つ後ろへずらす。

    ちょうど半小節だけ回してはいけない。**等間隔に並ぶ型は半分回すと自分自身に
    戻る** (四つ打ちも 8 分刻みも完全な無操作になった)。1 つ足した量で回すと、
    小節の長さと互いに素になるので、そうならない
    (拍子は必ず 4 の倍数ステップ ⇒ 半分+1 は奇数 ⇒ 共通の約数を持たない)。

    唯一の例外は 16 分がすべて埋まった小節。そこは何を回しても同じで、
    「全部鳴っている」以上に崩しようがない。
    """
    turn = msteps // 2 + 1
    return {start + (step - start + turn) % msteps for step in bar}


# 0 番は「そのまま」。曲調ごとの得意型はこの軸を指定しないので、
# 0 番が既定として自然に出る。
_PHRASE_FIGURES = (_pf_same, _pf_thin, _pf_push, _pf_shift, _pf_echo, _pf_swap)
PHRASE_FIGURE_COUNT = len(_PHRASE_FIGURES)


def _apply_figure(hits, figure, start, msteps, steps):
    """奇数小節 (2 小節目) だけ figure で作り変える。

    偶数小節は触らない。「1 小節目を提示し、2 小節目で崩す」形にすると、
    どの型でもフレーズとしての起伏が出る。
    """
    if _bar_of(start, msteps) % 2 == 0:
        return set(hits)
    bar = sorted(hits)
    return {step for step in figure(bar, start, msteps) if start <= step < steps}


def _metric_soft(step, msteps, floor=SOFT_GHOST):
    """拍の位置から弱さの段を決める。小節頭 > 拍頭 > 8分の裏 > 16分。

    floor で下限 (最も弱くできる段) を絞る。土台や主旋律は落としすぎると
    フレーズの芯が消えるので、パートごとに下限を変える。
    """
    pos = step % msteps
    if pos == 0:
        return SOFT_ACCENT
    if pos % 4 == 0:
        return min(SOFT_CORE, floor)
    if pos % 2 == 0:
        return min(SOFT_WEAK, floor)
    return floor


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

    重ねる層は**下の層と同じ音を同じ位置で鳴らさない** (`_resolve_overlap`)。
    層ごとに独立にパターンを選ぶだけだと、実測でリズムは 2 層で 59%・4 層で 74% が
    完全な重複になり、音量が上がるだけで層を足した意味が無かった。
    """
    base = _compose_notes(beats, key, scale_id, seed, progression, custom,
                          with_melody=True)  # レイヤー 0 (全パート)
    notes = list(base)
    prog = chosen_progression(scale_id, seed, custom, progression)  # base と同じ進行
    # 重なり判定はパート内だけで見る (別パートの同音は音色が違うので無駄にならない)
    taken = {}
    for note in base:
        taken.setdefault(note.wave, set()).add((note.step, note.pitch))
    for wave in range(PART_COUNT):
        count = layer_counts[wave] if wave < len(layer_counts) else 1
        for layer in range(1, count):
            notes.extend(_compose_extra_layer(wave, layer, beats, key, scale_id,
                                              seed, prog, custom,
                                              taken.setdefault(wave, set())))
    return build_phrase(notes)


def _resolve_overlap(taken, pitch, step, wave, steps):
    """下の層と完全に重なる音をずらす。(音程, ステップ) か (None, None) を返す。

    重複はミックスでは「同じ音が少し大きくなる」だけで、層を足した甲斐がない。
    リズムは音程が固定なので 16 分ずらして裏で鳴らし (ゴーストノート)、
    音程を持つパートはオクターブへ逃がす (ユニゾン → オクターブ重ね)。
    どちらも空いていなければ捨てる。
    """
    if (step, pitch) not in taken:
        return pitch, step
    if wave == WAVE_NOISE:
        for alt in (step + 1, step - 1):
            if 0 <= alt < steps and (alt, pitch) not in taken:
                return pitch, alt
    else:
        for alt in (pitch + 12, pitch - 12):
            if PITCH_MIN <= alt <= PITCH_MAX and (step, alt) not in taken:
                return alt, step
    return None, None


def _compose_extra_layer(wave, layer, beats, key, scale_id, seed, prog, custom,
                         taken=None):
    """1 パートの追加レイヤーを 1 つ作る。そのパートの音だけを返す。

    taken は同じパートの下の層が既に鳴らしている (ステップ, 音程)。
    渡すと重なりを避け、避けた音はここへ足していく。
    """
    rng = Rng((seed * 7919 + wave * 131 + layer * 977 + 12345) & 0xFFFFFFFF)
    steps = steps_per_phrase(beats)
    out = []

    def emit(pitch, step, w, dur, soft=0):
        if taken is not None:
            pitch, step = _resolve_overlap(taken, pitch, step, wave, steps)
            if pitch is None:
                return
            taken.add((step, pitch))
        dur = min(dur, steps - step)
        if PITCH_MIN <= pitch <= PITCH_MAX and dur >= 1:
            out.append(Note(pitch, step, w, dur, layer, soft))

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
                      _pick_bass_style(rng, prefs))
    elif wave == WAVE_NOISE:
        _compose_drums(None, emit, rng, beats, scale_id, steps,
                       _pick_drum_style(rng, prefs))
    else:  # WAVE_SAW
        _compose_backing(None, emit, rng, scale_id, steps, chord_of,
                         _pick_backing_style(rng, prefs), beats)
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

    def emit(pitch, step, wave, dur, soft=0):
        dur = min(dur, steps - step)
        if PITCH_MIN <= pitch <= PITCH_MAX and dur >= 1:
            notes.append(Note(pitch, step, wave, dur, 0, soft))

    # 進行が指定されていなければ、シード値でコード進行を 1 つ選ぶ
    progression = _pick_progression(rng, scale_id, custom, progression)

    def chord_of(step):
        return chord_at(key, scale_id, step, beats, progression, custom)

    # シード値ごとに演奏スタイルを選ぶ (曲の性格が大きく変わる)。
    # リズムとベースは曲調が得意な型を出やすくする (禁止はしない)。
    prefs = _style_prefs(scale_id, custom)
    bass_style = _pick_bass_style(rng, prefs)
    backing_style = _pick_backing_style(rng, prefs)
    drum_style = _pick_drum_style(rng, prefs)
    melody_rhythm = _weighted_pick(rng, MELODY_RHYTHMS, prefs["melody"])
    motif_mode = rng.next_int(MOTIF_MODES)

    _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of, bass_style)
    _compose_backing(notes, emit, rng, scale_id, steps, chord_of, backing_style,
                     beats)
    _compose_drums(notes, emit, rng, beats, scale_id, steps, drum_style)
    if with_melody:
        # メロディはベースの動きを見て作る (反行を取り、並行オクターブを避ける)
        _compose_melody(notes, emit, rng, beats, key, scale_id, steps, chord_of,
                        custom, melody_rhythm, motif_mode,
                        bass_at=_bass_lookup(notes))
    return notes


def _bass_lookup(notes):
    """step からその時点のベース音を引く関数を返す。無ければ None を返す。

    メロディはベースの後に作るので、ここで土台の動きを参照できる。
    """
    line = sorted(((n.step, n.pitch) for n in notes if n.wave == WAVE_TRIANGLE))
    if not line:
        return None

    def bass_at(step):
        found = None
        for start, pitch in line:
            if start > step:
                break
            found = pitch
        return found

    return bass_at


# ---- ベース (三角波) ---------------------------------------------------------
# 軸の直積で組む: 動き 8 × 刻み 3 × 変化 16 × 2小節目 5 × 音域 2
# ・動き … 音程の並び (ペダル/歩き/アルペジオ/半音…)。刻みの形は変えない
# ・刻み … どの細かさで置くか (半小節 / 4分 / 8分)
# ・変化 … 1 小節の中での置き方 (素直/シンコペ/付点/ハネ/クラーベ…)
# ・2小節目 … 2 小節目をどう崩すか (共有軸。_PHRASE_FIGURES を参照)
# ・音域 … 低音のまま / 1 オクターブ上。これも刻みの形は変えない
# **刻みの形** (実際に鳴る打点の並び) を決めるのは 刻み × 変化 × 2小節目 の 3 軸だけ。
# 動きと音域をいくら増やしても形は増えないので、数える時はこの 3 軸で数える。

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


# 変化は「足す」「ずらす」だけにしてある。**間引く型は作らない** —
# 小節頭は必ず打つ仕様なので、粗い刻み (半小節) を間引くと 1 和音 1 打まで減り、
# 動き 8 種が全部「根音 1 発」に潰れて別スタイルが同じ音符列になる (実装して却下)。

def _bv_anticipate(step, pos, grid, msteps):
    """先取り: 小節の変わり目だけ 16 分早く入って次の和音を予告する。

    小節末に 1 打足すだけなので、どの刻みでも素直な形と 1 打だけ違う。
    """
    if pos == msteps - 1:
        return True
    return step % grid == 0


def _bv_halfshift(step, pos, grid, msteps):
    """後半ずらし: 小節の後半だけ刻みを半分ずらす (前後で表情が変わる)。

    位置で条件を分けるので 1 小節周期。2 小節周期の altbar とは別物。
    """
    if pos < msteps // 2:
        return step % grid == 0
    return (step + max(1, grid // 2)) % grid == 0


def _bv_gallop(step, pos, grid, msteps):
    """ギャロップ: 刻みに拍の 3/4 位置を足して跳ねさせる。"""
    return step % grid == 0 or step % 4 == 3


def _bv_pairs(step, pos, grid, msteps):
    """二度打ち: 刻みの**直後**に 16 分を添えて 2 打ワンセットにする。

    「刻みを半分の細かさにする」型 (倍速) は作らない。それは刻み軸そのもので、
    細かい刻みの素直な型と完全に同じ形になる (実測で 10 通りが潰れた)。
    グレース (直前に添える) とは打点が 1 つずれるので別の形。
    """
    return step % grid == 0 or (step - 1) % grid == 0


def _bv_triplet(step, pos, grid, msteps):
    """3 分割: 刻みに拍を 3 つに割る位置を足す (ハネ感)。"""
    return step % grid == 0 or step % 8 in (3, 5)


def _bv_fillend(step, pos, grid, msteps):
    """小節終わりの詰め: 最後の 2 ステップを 16 分で埋めて次へ渡す。

    accentup (後半 1/4) より狭い範囲なので、同じ刻みでも別の形になる。
    """
    return step % grid == 0 or pos >= msteps - 2


def _bv_swing(step, pos, grid, msteps):
    """ハネ: 刻みを 1 つおきに 1 ステップ後ろへ倒す。

    ずらすのは奇数番目の刻みだけ。全部ずらすと刻みが丸ごと平行移動するだけで、
    シンコペと同じ形に潰れる (細かい刻みで実際に重なった)。
    """
    if step % grid == 0:
        return (step // grid) % 2 == 0
    if (step - 1) % grid == 0:
        return ((step - 1) // grid) % 2 == 1
    return False


def _bv_clave(step, pos, grid, msteps):
    """クラーベ: 刻みにラテンの芯を足す (拍から少しずれた 3 点)。"""
    return step % grid == 0 or _on(pos, msteps, (0.1875, 0.375, 0.625))


def _bv_headroll(step, pos, grid, msteps):
    """頭で転がす: 小節頭の直後に 16 分を 2 つ添える。"""
    return step % grid == 0 or pos in (1, 2)


def _bv_ramp(step, pos, grid, msteps):
    """後半だけ細かく: 前半は刻みどおり、後半は刻みを半分に割る。

    halfshift (後半をずらす) と違い、後半を**詰める**ので密度が変わる。
    """
    if pos < msteps // 2:
        return step % grid == 0
    return step % max(1, grid // 2) == 0


def _bv_edge(step, pos, grid, msteps):
    """3 対 4: 刻みに小節の 1/3・2/3 位置を足す (拍とずれたうねり)。

    足す位置が拍を割り切らないので、どの刻みの素直な形とも一致しない。
    """
    return step % grid == 0 or _on(pos, msteps, (1 / 3, 2 / 3))


def _bv_tailroll(step, pos, grid, msteps):
    """後半を転がす: 小節の後半だけ裏 16 分を足して駆け抜ける。"""
    return step % grid == 0 or (pos >= msteps // 2 and step % 2 == 1)


_BASS_VARIATIONS = (_bv_straight, _bv_synco, _bv_dotted, _bv_grace,
                    _bv_altbar, _bv_accentup, _bv_anticipate, _bv_halfshift,
                    _bv_gallop, _bv_pairs, _bv_triplet, _bv_fillend,
                    _bv_swing, _bv_clave, _bv_headroll, _bv_ramp,
                    _bv_edge, _bv_tailroll)

# レジスター (音域): 0 = 低音のまま / 1 = 1 オクターブ上げて中音域で弾ませる。
# 音高が必ず変わるので、同じ打点でも確実に別のパターンになる。
# しかも「土台を張る」「歌わせる」という音楽的に意味のある差になる。
_BASS_REGISTERS = (0, 12)

BASS_MOTION_COUNT = len(_BASS_MOTIONS)
BASS_RHYTHM_COUNT = 3
BASS_VARIATION_COUNT = len(_BASS_VARIATIONS)
BASS_REGISTER_COUNT = len(_BASS_REGISTERS)
BASS_FIGURE_COUNT = PHRASE_FIGURE_COUNT
_BASS_SUB = (BASS_RHYTHM_COUNT * BASS_VARIATION_COUNT * BASS_FIGURE_COUNT
             * BASS_REGISTER_COUNT)


def decode_bass_style(style):
    """style 番号を (動き, 刻み, 変化, 2小節目, 音域) へ分解する。"""
    style %= BASS_MOTION_COUNT * _BASS_SUB
    motion, rest = divmod(style, _BASS_SUB)
    rhythm, rest = divmod(rest, BASS_VARIATION_COUNT * BASS_FIGURE_COUNT
                          * BASS_REGISTER_COUNT)
    variation, rest = divmod(rest, BASS_FIGURE_COUNT * BASS_REGISTER_COUNT)
    figure, register = divmod(rest, BASS_REGISTER_COUNT)
    return motion, rhythm, variation, figure, register


def bass_styles_with_motion(motions):
    """指定した動きを使う style 番号すべて (曲調ごとの得意型に使う)。

    動きは番号の最上位の桁なので、走査せず範囲で出せる。全 style を
    decode して選り分けると、型が数千種になったとき起動が目に見えて遅くなる。
    """
    return _styles_with_kind(motions, BASS_MOTION_COUNT, _BASS_SUB)


def _bass_hits(onset, figure, grid, msteps, steps):
    """ベースの打点を作る。小節ごとに刻み→変化→2 小節目の順で組む。

    小節頭は figure のあとで必ず足し直す。「もたれ」のように全体を後ろへ
    ずらす型では頭が消えてしまい、土台が抜けて拍が見えなくなるため。
    """
    hits = set()
    for start in range(0, steps, msteps):
        bar = {start}
        bar.update(step for step in range(start + 1, min(start + msteps, steps))
                   if onset(step, step - start, grid, msteps))
        hits |= _apply_figure(bar, figure, start, msteps, steps)
        hits.add(start)
    return hits


def _compose_bass(notes, emit, rng, beats, scale_id, steps, chord_of, style=0):
    """ベース (三角波): 動き×刻み×変化×2小節目で弾く。1 オクターブ下で鳴らす。"""
    msteps = beats * 4
    drive = scale_id == "battle"      # 激しい曲は隙間を詰める
    motion_i, rhythm_i, variation_i, figure_i, register_i = \
        decode_bass_style(style)
    motion = _BASS_MOTIONS[motion_i]
    grid = _bass_grid(rhythm_i, msteps)
    onset = _BASS_VARIATIONS[variation_i]
    register = _BASS_REGISTERS[register_i]
    hits = _bass_hits(onset, _PHRASE_FIGURES[figure_i], grid, msteps, steps)
    # index は曲の頭からの通し番号。和音の変わり目で 0 へ戻せば必ず根音から入るが、
    # **刻みが和音と同じ幅のとき 1 和音 1 打になり、8 種の動きが全部同じ形へ潰れる**
    # (実測で試して却下)。根音以外から入るのは転回形として自然なので、通しのままにする。
    index = 0
    for step in range(steps):
        pos = step % msteps
        dur = 1
        hit = step in hits        # 小節頭は _bass_hits が必ず含める

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
            # 土台なので落としすぎない (下限は SOFT_WEAK)
            emit(pitch, step, WAVE_TRIANGLE, dur,
                 _metric_soft(step, msteps, SOFT_WEAK))


# ---- 伴奏 (ノコギリ波) -------------------------------------------------------
# ベース・リズムと同じく軸の直積で組む:
#   取り方 5 × 置き方 6 × 変化 8 × 2小節目 5 × 長さ 5
# ・取り方 … どの構成音を鳴らすか (根音/3度/5度/上行アルペジオ/下行アルペジオ)
# ・置き方 … どこに置くか (拍頭/裏/8分/パッド/跳ね/クラーベ)
# ・変化   … 1 小節の中での崩し方 (下の解説を参照)
# ・2小節目 … 2 小節目をどう崩すか (共有軸。_PHRASE_FIGURES を参照)
# ・長さ   … 1 音の伸ばし方 (短く刺す ⇄ 長く敷く)
# **リズムの形**を決めるのは 置き方 × 変化 × 2小節目 の 3 軸だけ。

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


def _sp_gallop(step, pos, msteps):
    """2 拍ひとまとまりで跳ねる (頭・付点・次の拍頭)。

    「毎拍の頭と 3/4」にすると打点が等間隔に並ぶため、シンコペを当てたときに
    8 分刻みと同じ形へ潰れる (実測で 6 通りが重複した)。2 拍周期にしてずらす。
    """
    return step % 8 in (0, 3, 4)


def _sp_clave(step, pos, msteps):
    """クラーベの位置に置く (拍から少しずれたラテンの芯)。"""
    return _on(pos, msteps, (0.0, 0.1875, 0.375, 0.625, 0.75))


def _sp_dotted(step, pos, msteps):
    """付点 8 分ごとに置く (3 ステップおき)。

    拍を割り切らないので、拍に乗る他の置き方とは必ず別の形になる。
    """
    return pos % 3 == 0


_BACKING_PLACEMENTS = (_sp_beat, _sp_offbeat, _sp_eighth, _sp_pad,
                       _sp_gallop, _sp_clave, _sp_dotted)


# 変化 — 置き方が等間隔グリッドしか作れないので、この軸でリズムを崩す。
# 置き方 4 種だけだと伴奏の**リズムの形が 4 通り**しかなく、別シードでも
# 4 回に 1 回は同じ刻みになってしまう (ベースの「変化 6 種」と同じ役割の軸)。
#
# 変化は**小節ぶんの発音位置の列を受け取って作り直す**。
#   ・位置を決め打ちで足す/抜くと、その位置を元から叩く型では何も起きない
#     (「追い込み」を 8 分刻みに当てたら完全な無操作だった)。
#   ・さらに悪いことに、決め打ちだと**別の置き方が同じ形へ潰れる**
#     (拍頭型とパッド型に同じシンコペを当てたら、どちらも [0,3,8,11] になった)。
#   打点の「何打目か」を基準に動かせば、置き方の性格を保ったまま崩せる。
# 返り値: {step: 先取りか}。先取り (アンティシペーション) は次の和音を鳴らす。


def _bk_straight(bar, start, msteps):
    """置き方そのまま。"""
    return {step: False for step in bar}


def _bk_synco(bar, start, msteps):
    """1 打おきに 16 分前へ食い込ませる (シンコペ)。"""
    return {(step - 1 if nth % 2 and step > start else step): False
            for nth, step in enumerate(bar)}


def _bk_pickup(bar, start, msteps):
    """小節の最後の打点を小節の末尾へ動かし、次の和音を先取りする。

    動かす先は**最後の 16 分**。1 手前 (msteps-2) だと、8 分刻みや裏打ちの型では
    そこが元々の最後の打点なので何も起きず、素直な型と同じ形に潰れる。
    """
    out = {step: False for step in bar[:-1]}
    if bar:
        out[start + msteps - 1] = True
    return out


def _bk_altbar(bar, start, msteps):
    """2 小節フレーズ — 2 小節目は前半を休んで後半だけ返す (呼びかけと応答)。"""
    if (start // msteps) % 2:
        return {step: False for step in bar if step - start >= msteps // 2}
    return {step: False for step in bar}


def _bk_push(bar, start, msteps):
    """小節の後半 1/4 を 16 分で刻んで次へ煽る (追い込み)。"""
    edge = start + _at(msteps, 0.75)
    out = {step: False for step in bar if step < edge}
    out.update({step: False for step in range(edge, start + msteps)})
    return out


def _bk_lag(bar, start, msteps):
    """小節の後半だけ 16 分後ろへずらす (もたれ)。"""
    half = start + msteps // 2
    return {(min(step + 1, start + msteps - 1) if step >= half else step): False
            for step in bar}


def _bk_double(bar, start, msteps):
    """二度打ち — 各打点の直後に 16 分を添えて厚くする。"""
    out = {step: False for step in bar}
    last = start + msteps - 1
    out.update({min(step + 1, last): False for step in bar})
    return out


def _bk_roll(bar, start, msteps):
    """転がし — 最初の 2 打の**あいだ**を 16 分で埋めて頭から転がす。

    埋める場所を末尾にしてはいけない。
    ・「最後の打点から小節末まで」→ まばらな置き方では追い込み (後半 1/4) と同じ範囲。
    ・「最後の 2 打のあいだ」→ 跳ねる置き方では最後の 2 打が隣り合っていて無操作。
    どの置き方でも先頭 2 打は必ず離れているので、頭を埋めれば必ず何かが変わる。
    """
    out = {step: False for step in bar}
    if len(bar) >= 2:
        out.update({step: False for step in range(bar[0], bar[1])})
    return out


def _bk_mirror(bar, start, msteps):
    """反転 — 打点を左右に折り返し、さらに 1 ステップ後ろへ置く。

    素直に折り返すだけでは足りない。**等間隔に並ぶ置き方は折り返しても
    自分自身に戻る** (付点 8 分ごとの型で完全な無操作になった)。
    1 つずらせば、どの置き方でも必ず別の形になる。
    """
    return {start + (msteps - (step - start) + 1) % msteps: False
            for step in bar}


# 回す量。拍を割り切る量 (小節の 1/4 など) にしてはいけない —
# 拍頭・裏・8 分のように周期が拍と揃った置き方が**そっくり自分自身に戻る**。
# 付点 8 分ぶん (3 ステップ) は 2 とも 4 とも互いに素なので、そうならない。
_BACKING_TURN = 3


def _bk_rotate(bar, start, msteps):
    """回転 — 打点をまとめて付点 8 分ぶん後ろへ回す (はみ出しは頭へ戻る)。

    反転と違い打点の間隔の並びまで保つ。**拍子に依らず**必ず別の形になるので、
    小節が短い拍子 (3/4 など) でも形の数が落ちない。
    """
    return {start + (step - start + _BACKING_TURN) % msteps: False
            for step in bar}


_BACKING_VARIATIONS = (_bk_straight, _bk_synco, _bk_pickup, _bk_altbar,
                       _bk_push, _bk_lag, _bk_double, _bk_roll, _bk_mirror,
                       _bk_rotate)


def _backing_hits(placed, vary, figure, steps, msteps):
    """置き方で発音位置を作り、変化で崩し、2 小節目を作り変える。

    返り値は {step: 先取りか}。2 小節目の作り変えで増えた打点は先取りにしない
    (先取りは「次の和音を予告する」意味を持つので、崩しで勝手に増やさない)。
    """
    hits = {}
    for start in range(0, steps, msteps):
        bar = [step for step in range(start, min(start + msteps, steps))
               if placed(step, step - start, msteps)]
        varied = {step: pickup for step, pickup in vary(bar, start, msteps).items()
                  if 0 <= step < steps}
        for step in _apply_figure(varied, figure, start, msteps, steps):
            hits[step] = varied.get(step, False)
    return hits

# 1 音の長さ。長いものは重なって持続音のように響く。
_BACKING_DURS = (1, 2, 3, 4, 6)

BACKING_VOICING_COUNT = len(_BACKING_VOICINGS)
BACKING_PLACEMENT_COUNT = len(_BACKING_PLACEMENTS)
BACKING_VARIATION_COUNT = len(_BACKING_VARIATIONS)
BACKING_FIGURE_COUNT = PHRASE_FIGURE_COUNT
BACKING_DUR_COUNT = len(_BACKING_DURS)
_BACKING_SUB = (BACKING_PLACEMENT_COUNT * BACKING_VARIATION_COUNT
                * BACKING_FIGURE_COUNT * BACKING_DUR_COUNT)


def decode_backing_style(style):
    """style 番号を (取り方, 置き方, 変化, 2小節目, 長さ) へ分解する。"""
    style %= BACKING_VOICING_COUNT * _BACKING_SUB
    voicing, rest = divmod(style, _BACKING_SUB)
    placement, rest = divmod(rest, BACKING_VARIATION_COUNT
                             * BACKING_FIGURE_COUNT * BACKING_DUR_COUNT)
    variation, rest = divmod(rest, BACKING_FIGURE_COUNT * BACKING_DUR_COUNT)
    figure, dur = divmod(rest, BACKING_DUR_COUNT)
    return voicing, placement, variation, figure, dur


def backing_styles_with_voicing(voicings):
    """指定した和音の取り方を使う style 番号すべて (曲調ごとの得意型に使う)。"""
    return _styles_with_kind(voicings, BACKING_VOICING_COUNT, _BACKING_SUB)


def _compose_backing(notes, emit, rng, scale_id, steps, chord_of, style=0,
                     beats=4):
    """サブ (ノコギリ波): 取り方×置き方×変化×長さで和音を添える。"""
    msteps = beats * 4
    heavy = scale_id == "battle"
    thin = scale_id == "japanese"     # 和風は間を活かして薄く
    voicing_i, placement_i, variation_i, figure_i, dur_i = \
        decode_backing_style(style)
    voicing = _BACKING_VOICINGS[voicing_i]
    placed = _BACKING_PLACEMENTS[placement_i]
    vary = _BACKING_VARIATIONS[variation_i]
    hold = _BACKING_DURS[dur_i]
    hits = _backing_hits(placed, vary, _PHRASE_FIGURES[figure_i], steps, msteps)
    index = 0
    for step in range(steps):
        pickup = hits.get(step)
        hit = pickup is not None
        if thin and hit and step % 4 != 2:
            # 和風は間引いて隙間を作る。ただし BACKING_MIN_NOTES 音は必ず残す。
            # 全部抜けると伴奏パートが消え、1〜2 音だと和音として聞こえない
            # (パッド + 先取りの組み合わせで 32 ステップ中 1 音まで減っていた)。
            spare = rng.chance(0.45)  # 乱数の消費数を一定にするため必ず引く
            if not spare and index >= BACKING_MIN_NOTES:
                hit = False
        if heavy and not hit and step % 2 == 1 and rng.chance(0.5):
            hit = True                # 激しい曲は裏を刺して厚くする
            pickup = False
        if not hit:
            continue
        # 先取りは次の和音を鳴らす (鳴る位置は小節末なので 2step 先を見る)
        chord = chord_of(min(step + 2, steps - 1)) if pickup else chord_of(step)
        pitch = voicing(chord, index)
        index += 1
        while pitch < PITCH_MIN:
            pitch += 12
        # 4 パートで最も小さいので、弱くするのは 1 段まで
        emit(pitch, step, WAVE_SAW, hold,
             _metric_soft(step, msteps, SOFT_CORE))


def _at(msteps, fraction):
    """小節を fraction (0..1) で割った位置のステップ。拍子が変わっても崩れない。"""
    return int(msteps * fraction)


def _on(pos, msteps, fractions):
    """pos が fractions のいずれかの位置か。小節単位のパターン用。"""
    return any(pos == _at(msteps, f) for f in fractions)


# ---- リズム (ノイズ) ---------------------------------------------------------
# 何百種も手書きすると保守できないので、**音楽的に意味のある軸の直積**で組む
# (コード進行を機能和声のひな型から自動生成しているのと同じ考え方)。
#   骨格 20 種 × 密度 4 段 × 2小節目 5 種 × アクセント 4 種
# ・骨格   … 芯の打点がどこに来るか (リズムの正体)
# ・密度   … 芯の隙間をどれだけ埋めるか (抜け ⇄ 詰め)
# ・2小節目 … 2 小節目をどう崩すか (共有軸。_PHRASE_FIGURES を参照)
# ・アクセント … どの打点を長く鳴らすか (ノイズ 1 声なので長さが強弱になる)
# 軸が直交しているので、どの組み合わせも意味のあるリズムになる。
# **リズムの形**を決めるのは 骨格 × 密度 × 2小節目 の 3 軸 (アクセントは長さだけ)。

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


# ここから下は後から足した骨格。**必ず末尾に足す** — 曲調ごとの得意リズムを
# 骨格の番号で指定しているので、途中に挿すと全曲調の性格が入れ替わってしまう。

def _sk_march(step, pos, msteps):
    """行進 — 拍頭に加えて 1・3 拍の裏を踏む (歩く足取り)。"""
    return step % 4 == 0 or step % 8 == 2


def _sk_samba(step, pos, msteps):
    """サンバ — 前に転がりながら裏で跳ねる。"""
    return _on(pos, msteps, (0.0, 0.125, 0.3125, 0.5, 0.625, 0.8125))


def _sk_rumba(step, pos, msteps):
    """ルンバ・クラーベ (2-3) — ソン・クラーベの裏返し。"""
    return _on(pos, msteps, (0.0, 0.1875, 0.4375, 0.625, 0.75))


def _sk_funk(step, pos, msteps):
    """16 分ファンク — 拍頭と拍の直前で食う。"""
    return step % 4 == 0 or step % 8 == 7


def _sk_house(step, pos, msteps):
    """ハウス — 四つ打ちに 2 拍ごとの開きハットを重ねる。

    「拍頭 + 裏 8 分すべて」にすると 8 分刻みと同じ形になるので、
    開きハットは 2 拍に 1 回だけにする。
    """
    return step % 4 == 0 or step % 8 == 6


def _sk_shuffle(step, pos, msteps):
    """シャッフル — 3 連の 1 つ目と 3 つ目 (跳ねる 8 分)。"""
    return step % 6 in (0, 4)


def _sk_breaks(step, pos, msteps):
    """ブレイクビーツ — 頭を食い、2 拍目裏から転がす。"""
    return _on(pos, msteps, (0.0, 0.25, 0.4375, 0.5625, 0.875))


_DRUM_SKELETONS = (
    _sk_beat, _sk_eighth, _sk_triplet, _sk_backbeat, _sk_halftime,
    _sk_offbeat, _sk_clave, _sk_bossa, _sk_amen, _sk_gallop,
    _sk_tribal, _sk_dnb, _sk_stutter,
    _sk_march, _sk_samba, _sk_rumba, _sk_funk, _sk_house,
    _sk_shuffle, _sk_breaks,
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
DRUM_FIGURE_COUNT = PHRASE_FIGURE_COUNT
DRUM_ACCENT_COUNT = len(_DRUM_ACCENTS)
_DRUM_SUB = DRUM_DENSITY_COUNT * DRUM_FIGURE_COUNT * DRUM_ACCENT_COUNT


def decode_drum_style(style):
    """style 番号を (骨格, 密度, 2小節目, アクセント) へ分解する。"""
    style %= DRUM_SKELETON_COUNT * _DRUM_SUB
    skeleton, rest = divmod(style, _DRUM_SUB)
    density, rest = divmod(rest, DRUM_FIGURE_COUNT * DRUM_ACCENT_COUNT)
    figure, accent = divmod(rest, DRUM_ACCENT_COUNT)
    return skeleton, density, figure, accent


def drum_styles_with_skeleton(skeletons):
    """指定した骨格を使う style 番号すべて (曲調ごとの得意型を作るのに使う)。"""
    return _styles_with_kind(skeletons, DRUM_SKELETON_COUNT, _DRUM_SUB)


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

# 指定は**種類の番号のまま**持つ。style 番号の集合へ展開してはいけない —
# 型が 1 万種規模になった今、展開すると起動時に十数万個の番号を並べることになる。
# 抽選は _pick_by_kind が種類の番号のまま扱える。
_PREFERRED = {
    family: dict(kinds) for family, kinds in _PREFERRED_KINDS.items()
}


def _weighted_pick(rng, count, preferred, weight=STYLE_WEIGHT):
    """得意な型を出やすくして 1 つ選ぶ。rng は必ず 1 回だけ消費する。

    禁止はしないので、どの型もいつかは出る (バリエーションを殺さない)。
    型数が小さい軸 (メロディのリズム) 用。型が数千種ある軸は _pick_by_kind へ。
    """
    return _pick_by_kind(rng, count, 1, preferred, weight)


def _pick_by_kind(rng, kind_count, sub, preferred, weight=STYLE_WEIGHT):
    """種類 (骨格/動き/取り方) に重みを付けて型を 1 つ選ぶ。

    style = 種類 * sub + 下位軸 という並びなので、**種類の数だけ** 走査すれば
    足りる。型を 1 つずつ数え上げると、型が 1 万種ある伴奏では作曲のたびに
    1 万回まわることになる (型を増やしたら実測で効いた)。

    抽選券の配り方は型ごとに数えるのと同じ: 得意な種類の型は weight 枚、
    それ以外は 1 枚。種類の中では下位軸が一様に出る。rng は 1 回だけ消費する。
    """
    pref = frozenset(k for k in preferred if 0 <= k < kind_count)
    total = sub * (kind_count + (weight - 1) * len(pref))
    ticket = rng.next_int(total)
    for kind in range(kind_count):
        share = weight if kind in pref else 1
        span = share * sub
        if ticket < span:
            return kind * sub + ticket // share
        ticket -= span
    return kind_count * sub - 1


_NO_PREFS = {"drums": (), "bass": (), "backing": (), "melody": ()}


def _style_prefs(scale_id, custom=None):
    """その曲調が得意な**種類** (リズムの骨格 / ベースの動き / 伴奏の取り方 /
    メロディのリズム)。未知の曲調でも必ず何か返す。"""
    family = music_mod.scale_family(scale_id, custom)
    return _PREFERRED.get(family, _NO_PREFS)


def _pick_drum_style(rng, prefs):
    """曲調に合わせてリズムの型を 1 つ選ぶ (骨格に重みを付ける)。"""
    return _pick_by_kind(rng, DRUM_SKELETON_COUNT, _DRUM_SUB, prefs["drums"])


def _pick_bass_style(rng, prefs):
    """曲調に合わせてベースの型を 1 つ選ぶ (動きに重みを付ける)。"""
    return _pick_by_kind(rng, BASS_MOTION_COUNT, _BASS_SUB, prefs["bass"])


def _pick_backing_style(rng, prefs):
    """曲調に合わせて伴奏の型を 1 つ選ぶ (和音の取り方に重みを付ける)。"""
    return _pick_by_kind(rng, BACKING_VOICING_COUNT, _BACKING_SUB,
                         prefs["backing"])


def _drum_core_hits(core, figure, msteps, steps):
    """芯の打点を作る。骨格で組み、2 小節目だけ figure で作り変える。

    小節頭は含めない。呼び出し側が「どの型でも小節頭は必ず鳴らす」を
    別扱いにしているので、ここで足すと打数 (nth) が二重になる。
    """
    hits = set()
    for start in range(0, steps, msteps):
        bar = {step for step in range(start + 1, min(start + msteps, steps))
               if core(step, step - start, msteps)}
        hits |= _apply_figure(bar, figure, start, msteps, steps)
    hits.discard(0)
    return {step for step in hits if step % msteps != 0}


def _compose_drums(notes, emit, rng, beats, scale_id, steps, style=0):
    """リズム (ノイズ): 骨格×密度×2小節目×アクセントで叩く。小節頭は必ず芯を置く。"""
    msteps = beats * 4
    heavy = scale_id == "battle"
    skeleton, density, figure, accent = decode_drum_style(style)
    core_hits = _drum_core_hits(_DRUM_SKELETONS[skeleton],
                                _PHRASE_FIGURES[figure], msteps, steps)
    fill = _DRUM_FILL[density]
    accent_of = _DRUM_ACCENTS[accent]
    jp = scale_id == "japanese" and skeleton not in _JP_KEEP_SKELETONS
    nth = 0                       # 小節内で何打目か (アクセントの周期に使う)
    for step in range(steps):
        hit = False
        dur = 1
        soft = SOFT_GHOST          # 埋めた音は弱く (下で芯・アクセントを上書き)
        pos = step % msteps
        if pos == 0:
            nth = 0

        if jp:
            # 和風の太鼓: 小節頭に長い一打
            if pos == 0:
                hit, dur, soft = True, 4, SOFT_ACCENT
            elif pos == msteps - 2:
                hit, soft = True, SOFT_CORE
        elif pos == 0:
            hit, dur, soft = True, 2, SOFT_ACCENT  # どの型でも小節頭は必ず鳴らす
        elif step in core_hits:
            nth += 1
            hit, dur = True, accent_of(step, pos, msteps, nth)
            # アクセントは長さだけでなく**強さ**でも張る。長さだけだと
            # フレーズの音量が平坦になり、拍の階層が耳に伝わらない。
            soft = SOFT_ACCENT if dur > 1 else SOFT_CORE
        elif fill > 0:
            hit = rng.chance(fill)

        if heavy and not hit and step % 2 == 0 and rng.chance(0.5):
            hit = True  # 激しい曲は隙間を埋める
        if hit:
            if step >= steps - msteps // 2:
                # フレーズ最後の半小節は一段強く (次のループへの煽り)。
                # 拍の階層だけだと 1 小節目と 2 小節目が同じ音量になり、
                # フレーズ全体としての起伏が出ない。
                soft = max(SOFT_ACCENT, soft - 1)
            emit(DRUM_PITCH, step, WAVE_NOISE, dur, soft)


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
                    custom=None, rhythm=0, motif_mode=0, bass_at=None):
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
    # メロディが使う音域。「主音の 1 オクターブ上から上限まで」だけだと、
    # 床はキーとともに上がるのに天井 (PITCH_MAX) は動かないので、
    # **高いキーほど幅が潰れる** (実測で C は 24 半音、B は 13 半音しかなかった)。
    # 少なくとも MELODY_SPAN 半音は確保する (キー 0 では従来と同じ床になる)。
    low = min(root_note(key) + 12, PITCH_MAX - MELODY_SPAN)
    melody_notes = [p for p in scale_pitches(key, scale_id, custom=custom)
                    if p >= low]
    if not melody_notes:
        return

    prev_index = len(melody_notes) // 2
    center = prev_index
    last_index = None  # 直前に鳴らした音のインデックス
    run = 0            # その音が続いている回数
    motif = {}         # step -> (音のインデックス, 長さ)。休符は登録しない。
    passing = set()    # 経過音を置いた step (2小節目でコードトーンへ寄せ直さない)
    onsets = frozenset(_melody_onsets(rng, msteps, rhythm, scale_id))
    last_bass = None   # 前の音の時点でのベース音 (反行を取るために覚えておく)

    step = 0
    while step < steps:
        hit = False
        target = prev_index
        dur = 1
        chord = chord_of(step)
        bass_now = bass_at(step) if bass_at else None

        if step < msteps:
            # 1小節目: 先に決めた発音位置でモチーフを作る
            if step in onsets:
                hit = True
                rise = step < msteps // 2  # 前半は上へ、後半は下へ (山なり)
                as_passing = step % 4 != 0 and rng.chance(MELODY_PASSING_PROB)
                move = 0 if None in (bass_now, last_bass) else bass_now - last_bass
                target = _pick_melody_note(rng, melody_notes, prev_index, chord,
                                           step, rise, run, as_passing,
                                           move, bass_now)
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
                    moved = _step_away(melody_notes, target, chord)
                    if moved != target:
                        target = moved
                        run = 1        # 逃がした先での 1 音目
                    else:
                        run += 1       # 逃げ場が無い (音階に音が 1 つ) だけ
                else:
                    run += 1
            else:
                run = 1
            last_index = target
            prev_index = target
            last_bass = bass_now
            # 主旋律なので下限は SOFT_WEAK。経過音はもう 1 段落として通り道にする。
            soft = _metric_soft(step, msteps, SOFT_WEAK)
            if step % msteps in passing:
                soft = SOFT_WEAK
            emit(melody_notes[target], step, WAVE_PULSE, dur, soft)
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
        # ミラー: 中心の音を軸に上下を反転する。
        # 素の反転は端の音が中心をまたいで大きく飛び (実測 平均 8.9 半音、他の型は
        # 2.5〜4)、「展開」より別のメロディに聞こえてしまう。元の音からの距離を
        # MOTIF_MIRROR_SPAN 度以内に抑えて、反転の向きだけを残す (平均 4.8 半音)。
        mirrored = 2 * center - index
        mirrored = max(index - MOTIF_MIRROR_SPAN,
                       min(index + MOTIF_MIRROR_SPAN, mirrored))
        return max(0, min(count - 1, mirrored)), dur
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
                      repeat=0, passing=False, bass_move=0, bass_pitch=None):
    """跳躍ペナルティとコードトーンボーナスで次の音を選ぶ。

    rise で旋律の向きを軽く誘導し、山なりの起伏を作る。
    repeat は直前の音が続いている回数。留まるほど高くつくようにして同音連打を抑える
    (跳躍 0 = ペナルティ 0 なので、これが無いと「動かない」が常に最安になる)。
    passing なら経過音として扱い、コードトーン優遇の代わりに順次進行を推す。
    bass_move / bass_pitch は土台の動きと今の音。ベースと同じ向きに動くこと
    (並行) と同じ音名になること (ユニゾン・オクターブ) を減点し、反行を取る。
    実測で 反行 22% / 連続する並行オクターブ 4.0% だったのを改善するため。
    """
    best = prev_index
    best_score = None
    chord_pcs = (chord.root % 12, chord.third % 12, chord.fifth % 12)
    bass_pc = None if bass_pitch is None else bass_pitch % 12
    for i, pitch in enumerate(melody_notes):
        jump = abs(i - prev_index)
        penalty = jump * 3 if jump > 4 else jump
        if i == prev_index:
            penalty += MELODY_REPEAT_PENALTY * repeat
        elif bass_move and (i > prev_index) == (bass_move > 0):
            penalty += MELODY_PARALLEL_PENALTY   # ベースと同じ向き = 並行
        if bass_pc is not None and pitch % 12 == bass_pc:
            penalty += MELODY_UNISON_PENALTY     # 土台と同じ音名 = 声部が薄くなる

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
BASS_STYLES = BASS_MOTION_COUNT * _BASS_SUB       # 動き×刻み×変化×2小節目×音域
BACKING_STYLES = BACKING_VOICING_COUNT * _BACKING_SUB  # 取り方×置き方×変化×2小節目×長さ
DRUM_STYLES = DRUM_SKELETON_COUNT * _DRUM_SUB     # 骨格×密度×2小節目×アクセント

# 実際に鳴る「リズムの形」の数 = 打点を決める軸だけの積。
# 型の数 (上) は音程や長さの違いも含むので、**変化の実感はこちらで測る**。
BASS_SHAPES = BASS_RHYTHM_COUNT * BASS_VARIATION_COUNT * BASS_FIGURE_COUNT
BACKING_SHAPES = (BACKING_PLACEMENT_COUNT * BACKING_VARIATION_COUNT
                  * BACKING_FIGURE_COUNT)
DRUM_SHAPES = DRUM_SKELETON_COUNT * DRUM_DENSITY_COUNT * DRUM_FIGURE_COUNT
