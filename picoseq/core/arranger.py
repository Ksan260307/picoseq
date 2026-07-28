"""自動伴奏 — 盤面のメロディからコード進行を推定し、他パートを付ける。

盤面にメロディ (パルス波) だけがある状態から、そのメロディに合う
ベース・サブ・リズムを決定論的に生成する。純粋関数。

流れ:
  1. メロディ音を半小節ごとの窓に分ける
  2. 各窓で、スケール各度数のコードにメロディ音がどれだけ乗るか採点し、
     最も一致する度数を選ぶ → コード進行を推定
  3. 推定した進行で composer の伴奏生成を駆動し、メロディに重ねる

キー・スケールはプロジェクト設定を使う。進行の長さは常に 4 (2小節×半小節)。
"""

from .composer import accompany_notes
from .constants import WAVE_PULSE, steps_per_phrase
from .music import chord_at, get_scale
from .phrase import active_notes, build_phrase
from .project import Project, steps_of


def melody_notes(project: Project) -> list:
    """盤面のメロディ (パルス波) 音を返す。"""
    steps = steps_of(project)
    return [note for _, note in active_notes(project.phrase)
            if note.wave == WAVE_PULSE and note.step < steps]


def has_only_melody(project: Project) -> bool:
    """盤面にメロディ音があり、かつ他パートが無いか。"""
    has_melody = False
    for _, note in active_notes(project.phrase):
        if note.wave == WAVE_PULSE:
            has_melody = True
        else:
            return False
    return has_melody


def half_measure(beats: int) -> int:
    """半小節のステップ数 (composer のコード進行の刻みと一致)。"""
    return max(2, beats * 4 // 2)


def infer_progression(project: Project) -> tuple:
    """メロディから半小節ごとのコード度数を推定する。

    各窓で、度数 d のコード構成音 (根音・3度・5度) にメロディ音が
    どれだけ乗るかを、音の長さで重み付けして採点する。根音一致を重く見る。
    同点は小さい度数を優先し、決定論を保つ。
    """
    beats = project.beats
    steps = steps_per_phrase(beats)
    half = half_measure(beats)
    window_count = max(1, steps // half)
    n = len(get_scale(project.scale, project.custom_scale)["intervals"])
    melody = melody_notes(project)

    degrees = []
    for w in range(window_count):
        lo = w * half
        hi = lo + half
        # 窓に鳴っているメロディ音を集める (開始が窓内、または継続中)
        window = [note for note in melody
                  if note.step < hi and note.step + note.dur > lo]

        best_degree = 0
        best_score = None
        for d in range(n):
            chord = chord_at(project.key, project.scale, lo, beats, (d,),
                             project.custom_scale)
            root_pc = chord.root % 12
            third_pc = chord.third % 12
            fifth_pc = chord.fifth % 12
            score = 0
            for note in window:
                pc = note.pitch % 12
                weight = note.dur
                # 窓の頭に近い音・拍の頭の音を重く見る
                if note.step <= lo:
                    weight += 1
                if pc == root_pc:
                    score += weight * 3
                elif pc == third_pc or pc == fifth_pc:
                    score += weight * 2
            if best_score is None or score > best_score:
                best_score = score
                best_degree = d
        degrees.append(best_degree)
    return tuple(degrees)


def arrange(project: Project):
    """メロディを保ったまま伴奏を生成する。

    (新しいフレーズバッファ, 推定した進行) を返す。メロディが無ければ
    (元のバッファ, None) を返す。
    """
    melody = melody_notes(project)
    if not melody:
        return project.phrase, None

    progression = infer_progression(project)
    accompaniment = accompany_notes(project.beats, project.key, project.scale,
                                    project.seed, progression, project.custom_scale)
    # メロディを先頭に置く (盤面の内容を優先して残す)
    merged = list(melody) + list(accompaniment)
    return build_phrase(merged), progression
