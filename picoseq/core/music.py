"""音楽理論 — キー・スケール・コード・音名・周波数テーブル。"""

from typing import NamedTuple

from .constants import PITCH_MIN, PITCH_MAX

KEY_NAMES = (
    "C / Am", "C# / A#m", "D / Bm", "D# / Cm", "E / C#m", "F / Dm",
    "F# / D#m", "G / Em", "G# / Fm", "A / F#m", "A# / Gm", "B / G#m",
)

# スケール定義: 音程 (半音) と、半小節ごとに進むコード進行 (スケール度数)
SCALES = {
    "major": {
        "label": "明るい (メジャー)",
        "intervals": (0, 2, 4, 5, 7, 9, 11),
        "progression": (0, 3, 1, 4),
    },
    "minor": {
        "label": "切ない (マイナー)",
        "intervals": (0, 2, 3, 5, 7, 8, 10),
        "progression": (0, 5, 2, 6),
    },
    "japanese": {
        "label": "和風 (陰音階)",
        "intervals": (0, 2, 3, 7, 8),
        "progression": (0, 3, 0, 2),
    },
    "battle": {
        "label": "ボス戦 (激しい)",
        "intervals": (0, 1, 4, 5, 7, 8, 10),
        "progression": (0, 5, 0, 6),
    },
}
SCALE_IDS = tuple(SCALES)
DEFAULT_SCALE = "minor"
PHOTO_SCALE = "photo"  # 写真から抽出したカスタム音階 (プロジェクトごとに音の並びが違う)


def default_progression(count: int) -> tuple:
    """音数 count の音階に合わせた無難な既定コード進行。"""
    return (0, min(3, count - 1), min(1, count - 1), min(4, count - 1))


def get_scale(scale_id: str, custom=None) -> dict:
    """音階定義 (label / intervals / progression) を返す。

    scale_id が "photo" のときは、プロジェクトが持つカスタム音程列 custom を使う。
    """
    if scale_id == PHOTO_SCALE:
        if not custom:
            raise ValueError("フォト音階が設定されていません。")
        return {
            "label": "📷 フォト音階",
            "intervals": tuple(custom),
            "progression": default_progression(len(custom)),
        }
    return SCALES[scale_id]

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")

# 平均律の周波数 (ミリヘルツ)。MIDI 36〜84。
# 実行時の浮動小数点 pow を避け、環境によらず同一の値を使う。
PITCH_MILLIHZ = (
    65406, 69296, 73416, 77782, 82407, 87307, 92499,
    97999, 103826, 110000, 116541, 123471, 130813, 138591,
    146832, 155563, 164814, 174614, 184997, 195998, 207652,
    220000, 233082, 246942, 261626, 277183, 293665, 311127,
    329628, 349228, 369994, 391995, 415305, 440000, 466164,
    493883, 523251, 554365, 587330, 622254, 659255, 698456,
    739989, 783991, 830609, 880000, 932328, 987767, 1046502,
)


class Chord(NamedTuple):
    root: int
    third: int
    fifth: int


def note_name(pitch: int) -> str:
    """MIDI ノート番号を音名にする。60 -> C4"""
    return NOTE_NAMES[pitch % 12] + str(pitch // 12 - 1)


def root_note(key: int) -> int:
    """キー (0=C .. 11=B) の基準ルート音。"""
    return 48 + key


def pitch_millihz(pitch: int) -> int:
    """MIDI ノート番号の周波数 (ミリヘルツ)。"""
    return PITCH_MILLIHZ[pitch - PITCH_MIN]


def scale_pitches(key: int, scale_id: str, lo: int = PITCH_MIN, hi: int = PITCH_MAX,
                  custom=None) -> list:
    """キーとスケールに属する音を昇順で返す。"""
    intervals = get_scale(scale_id, custom)["intervals"]
    root = root_note(key)
    out = []
    for octave in range(-2, 4):
        for iv in intervals:
            p = root + iv + octave * 12
            if lo <= p <= hi:
                out.append(p)
    return sorted(out)


def in_scale(pitch: int, key: int, scale_id: str, custom=None) -> bool:
    """その音がスケールに属するか。"""
    return (pitch - root_note(key)) % 12 in get_scale(scale_id, custom)["intervals"]


def chord_at(key: int, scale_id: str, step: int, beats: int,
             progression=None, custom=None) -> Chord:
    """そのステップで鳴っているコード (根音・3度・5度)。半小節ごとに進行する。

    progression を渡すとスケール既定の進行の代わりに使う (度数の列)。
    """
    scale = get_scale(scale_id, custom)
    intervals = scale["intervals"]
    if progression is None:
        progression = scale["progression"]
    half = max(2, beats * 4 // 2)
    degree = progression[(step // half) % len(progression)]
    n = len(intervals)

    def tone(offset: int) -> int:
        index = degree + offset
        octave_up = 12 if index >= n else 0
        return root_note(key) + intervals[index % n] + octave_up

    return Chord(tone(0), tone(2), tone(4))
