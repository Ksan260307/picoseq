"""音楽理論 — キー・スケール・コード・音名・周波数テーブル。"""

from typing import NamedTuple

from .constants import PITCH_MIN, PITCH_MAX

KEY_NAMES = (
    "C / Am", "C# / A#m", "D / Bm", "D# / Cm", "E / C#m", "F / Dm",
    "F# / D#m", "G / Em", "G# / Fm", "A / F#m", "A# / Gm", "B / G#m",
)

# スケール定義: 音程 (半音) と、半小節ごとに進む既定コード進行 (スケール度数)。
# label は「気分 (音楽用語)」の形。自動作成の曲調セレクタにそのまま並ぶ。
SCALES = {
    "major":      {"label": "明るい (メジャー)",         "intervals": (0, 2, 4, 5, 7, 9, 11),  "progression": (0, 3, 1, 4)},
    "minor":      {"label": "切ない (マイナー)",         "intervals": (0, 2, 3, 5, 7, 8, 10),  "progression": (0, 5, 2, 6)},
    "dorian":     {"label": "ほろ苦い (ドリアン)",       "intervals": (0, 2, 3, 5, 7, 9, 10),  "progression": (0, 3, 4, 0)},
    "mixolydian": {"label": "のどか (ミクソリディアン)", "intervals": (0, 2, 4, 5, 7, 9, 10),  "progression": (0, 6, 3, 4)},
    "lydian":     {"label": "夢見心地 (リディアン)",     "intervals": (0, 2, 4, 6, 7, 9, 11),  "progression": (0, 1, 4, 0)},
    "harmonic":   {"label": "妖しい (和声的短音階)",     "intervals": (0, 2, 3, 5, 7, 8, 11),  "progression": (0, 3, 4, 0)},
    "melodic":    {"label": "劇的 (旋律的短音階)",       "intervals": (0, 2, 3, 5, 7, 9, 11),  "progression": (0, 3, 4, 0)},
    "japanese":   {"label": "和風 (陰音階)",             "intervals": (0, 2, 3, 7, 8),         "progression": (0, 3, 0, 2)},
    "ryukyu":     {"label": "南国 (琉球音階)",           "intervals": (0, 4, 5, 7, 11),        "progression": (0, 2, 3, 0)},
    "pentatonic": {"label": "陽気 (メジャーペンタ)",     "intervals": (0, 2, 4, 7, 9),         "progression": (0, 3, 4, 0)},
    "blues":      {"label": "ブルージー (ブルース)",     "intervals": (0, 3, 5, 6, 7, 10),     "progression": (0, 3, 4, 0)},
    "wholetone":  {"label": "ふしぎ (全音音階)",         "intervals": (0, 2, 4, 6, 8, 10),     "progression": (0, 2, 4, 0)},
    "battle":     {"label": "ボス戦 (激しい)",           "intervals": (0, 1, 4, 5, 7, 8, 10),  "progression": (0, 5, 0, 6)},
    # --- 教会旋法の残り ---
    "phrygian":   {"label": "哀愁 (フリジアン)",          "intervals": (0, 1, 3, 5, 7, 8, 10),  "progression": (0, 3, 4, 0)},
    "locrian":    {"label": "不安定 (ロクリアン)",        "intervals": (0, 1, 3, 5, 6, 8, 10),  "progression": (0, 3, 4, 0)},
    # --- 旋律的短音階の旋法 ---
    "dorian_b2":  {"label": "怪しい東洋 (ドリアン♭2)",    "intervals": (0, 1, 3, 5, 7, 9, 10),  "progression": (0, 3, 4, 0)},
    "lydian_aug": {"label": "浮遊 (リディアン♯5)",        "intervals": (0, 2, 4, 6, 8, 9, 11),  "progression": (0, 3, 4, 0)},
    "lydian_dom": {"label": "近未来 (リディアン7th)",     "intervals": (0, 2, 4, 6, 7, 9, 10),  "progression": (0, 3, 4, 0)},
    "mixo_b6":    {"label": "黄昏 (ミクソ♭6)",            "intervals": (0, 2, 4, 5, 7, 8, 10),  "progression": (0, 3, 4, 0)},
    "locrian_n2": {"label": "薄暮 (ハーフディム)",        "intervals": (0, 2, 3, 5, 6, 8, 10),  "progression": (0, 3, 4, 0)},
    "altered":    {"label": "きわどい (オルタード)",      "intervals": (0, 1, 3, 4, 6, 8, 10),  "progression": (0, 3, 4, 0)},
    # --- 和声的短音階の旋法 ---
    "locrian_n6": {"label": "たそがれ (ロクリアン6th)",   "intervals": (0, 1, 3, 5, 6, 9, 10),  "progression": (0, 3, 4, 0)},
    "ionian_s5":  {"label": "荘厳 (アイオニアン♯5)",      "intervals": (0, 2, 4, 5, 8, 9, 11),  "progression": (0, 3, 4, 0)},
    "dorian_s4":  {"label": "ジプシー (ウクライナ短調)",  "intervals": (0, 2, 3, 6, 7, 9, 10),  "progression": (0, 3, 4, 0)},
    "lydian_s2":  {"label": "幻想 (リディアン♯2)",        "intervals": (0, 3, 4, 6, 7, 9, 11),  "progression": (0, 3, 4, 0)},
    "ultralocrian": {"label": "混沌 (ウルトラロクリアン)", "intervals": (0, 1, 3, 4, 6, 8, 9),   "progression": (0, 3, 4, 0)},
    "harmonic_major": {"label": "気高い (和声的長音階)",  "intervals": (0, 2, 4, 5, 7, 8, 11),  "progression": (0, 3, 4, 0)},
    # --- 各国・エキゾチック (7音) ---
    "double_harmonic": {"label": "アラビア (二重和声)",   "intervals": (0, 1, 4, 5, 7, 8, 11),  "progression": (0, 3, 4, 0)},
    "hungarian_minor": {"label": "情熱の短調 (ハンガリー)", "intervals": (0, 2, 3, 6, 7, 8, 11), "progression": (0, 3, 4, 0)},
    "hungarian_major": {"label": "情熱の長調 (ハンガリー)", "intervals": (0, 3, 4, 6, 7, 9, 10), "progression": (0, 3, 4, 0)},
    "neapolitan_minor": {"label": "ナポリ短調",           "intervals": (0, 1, 3, 5, 7, 8, 11),  "progression": (0, 3, 4, 0)},
    "neapolitan_major": {"label": "ナポリ長調",           "intervals": (0, 1, 3, 5, 7, 9, 11),  "progression": (0, 3, 4, 0)},
    "enigmatic":  {"label": "謎めいた (エニグマティック)", "intervals": (0, 1, 4, 6, 8, 10, 11), "progression": (0, 3, 4, 0)},
    "persian":    {"label": "ペルシャ",                   "intervals": (0, 1, 4, 5, 6, 8, 11),  "progression": (0, 3, 4, 0)},
    "oriental":   {"label": "オリエンタル",               "intervals": (0, 1, 4, 5, 6, 9, 10),  "progression": (0, 3, 4, 0)},
    "marva":      {"label": "夜明け (マルワ)",            "intervals": (0, 1, 4, 6, 7, 9, 11),  "progression": (0, 3, 4, 0)},
    "todi":       {"label": "瞑想 (トーディ)",            "intervals": (0, 1, 3, 6, 7, 8, 11),  "progression": (0, 3, 4, 0)},
    "purvi":      {"label": "夕暮れ (プールヴィ)",        "intervals": (0, 1, 4, 6, 7, 8, 11),  "progression": (0, 3, 4, 0)},
    "leading_whole_tone": {"label": "予感 (導音全音)",    "intervals": (0, 2, 4, 6, 8, 10, 11), "progression": (0, 3, 4, 0)},
    "kishimi":    {"label": "きしみ (変則短)",            "intervals": (0, 2, 3, 4, 6, 8, 10),  "progression": (0, 3, 4, 0)},
    "lydian_minor": {"label": "白昼夢 (リディアン短)",    "intervals": (0, 2, 4, 6, 7, 8, 10),  "progression": (0, 3, 4, 0)},
    "major_locrian": {"label": "崩落 (メジャーロクリアン)", "intervals": (0, 2, 4, 5, 6, 8, 10), "progression": (0, 3, 4, 0)},
    # --- 5 音音階 (世界) ---
    "minor_penta": {"label": "渋い (マイナーペンタ)",     "intervals": (0, 3, 5, 7, 10),        "progression": (0, 3, 4, 0)},
    "egyptian":   {"label": "砂漠 (エジプシャン)",        "intervals": (0, 2, 5, 7, 10),        "progression": (0, 3, 4, 0)},
    "man_gong":   {"label": "夜想 (マンゴン)",            "intervals": (0, 3, 5, 8, 10),        "progression": (0, 3, 4, 0)},
    "insen":      {"label": "都節 (陰旋)",                "intervals": (0, 1, 5, 7, 10),        "progression": (0, 3, 4, 0)},
    "iwato":      {"label": "厳か (岩戸)",                "intervals": (0, 1, 5, 6, 10),        "progression": (0, 3, 4, 0)},
    "kumoi":      {"label": "雅 (雲井)",                  "intervals": (0, 2, 3, 7, 9),         "progression": (0, 3, 4, 0)},
    "chinese":    {"label": "中華",                       "intervals": (0, 4, 6, 7, 11),        "progression": (0, 3, 4, 0)},
    "pelog":      {"label": "ガムラン (ペロッグ)",        "intervals": (0, 1, 3, 7, 8),         "progression": (0, 3, 4, 0)},
    "dominant_penta": {"label": "陽だまり (ドミナントペンタ)", "intervals": (0, 2, 4, 7, 10),    "progression": (0, 3, 4, 0)},
    "hon_kumoi":  {"label": "静寂 (本雲井)",              "intervals": (0, 1, 5, 7, 8),         "progression": (0, 3, 4, 0)},
    "yo":         {"label": "田舎 (陽旋)",                "intervals": (0, 2, 5, 7, 9),         "progression": (0, 3, 4, 0)},
    "bali":       {"label": "祈り (バリ)",                "intervals": (0, 1, 3, 7, 10),        "progression": (0, 3, 4, 0)},
    # --- 6 音音階 ---
    "major_blues": {"label": "陽気ブルース",              "intervals": (0, 2, 3, 4, 7, 9),      "progression": (0, 3, 4, 0)},
    "augmented":  {"label": "きらきら (オーグメント)",    "intervals": (0, 3, 4, 7, 8, 11),     "progression": (0, 3, 4, 0)},
    "prometheus": {"label": "神秘 (プロメテウス)",        "intervals": (0, 2, 4, 6, 9, 10),     "progression": (0, 3, 4, 0)},
    "tritone":    {"label": "二面性 (トライトーン)",      "intervals": (0, 1, 4, 6, 7, 10),     "progression": (0, 3, 4, 0)},
    "istrian":    {"label": "民謡 (イストリア)",          "intervals": (0, 1, 3, 4, 6, 7),      "progression": (0, 3, 4, 0)},
    "scriabin":   {"label": "神智 (スクリャービン)",      "intervals": (0, 1, 4, 6, 9, 10),     "progression": (0, 3, 4, 0)},
    # --- 8 音音階 ---
    "dim_wh":     {"label": "不穏 (ディミニッシュ)",      "intervals": (0, 2, 3, 5, 6, 8, 9, 11), "progression": (0, 3, 4, 0)},
    "dim_hw":     {"label": "スリル (コンディミ)",        "intervals": (0, 1, 3, 4, 6, 7, 9, 10), "progression": (0, 3, 4, 0)},
    "bebop_dom":  {"label": "ジャズ (ビバップ)",          "intervals": (0, 2, 4, 5, 7, 9, 10, 11), "progression": (0, 3, 4, 0)},
    "bebop_major": {"label": "スウィング (ビバップ長)",   "intervals": (0, 2, 4, 5, 7, 8, 9, 11), "progression": (0, 3, 4, 0)},
    "spanish8":   {"label": "スペイン (八音)",            "intervals": (0, 1, 3, 4, 5, 6, 8, 10), "progression": (0, 3, 4, 0)},
}
SCALE_IDS = tuple(SCALES)
DEFAULT_SCALE = "minor"
PHOTO_SCALE = "photo"  # 写真から抽出したカスタム音階 (プロジェクトごとに音の並びが違う)

# ---- コード進行の自動生成 ----
# 各音階のコード進行は、機能和声 (T=トニック / S=サブドミナント / D=ドミナント) の
# ひな型に、その機能に属する度数を当てはめて大量に作る。
# 度数は音階の「位置」で機能を割り当てるので、どの音階でも音楽的な流れになる。

PROGRESSION_LIMIT = 480  # 1 音階あたりの進行数の上限


def _function_templates() -> tuple:
    """4 和音ぶんの機能の並び (0=T 1=S 2=D) を音楽的な条件で列挙する。

    ・トニックかサブドミナントで始める (調を示す/導く)
    ・トニックかドミナントで終える (終止感)
    ・少なくとも 2 種類の機能を使う (停滞させない)
    ・同じ機能を 3 連続させない
    """
    templates = []
    for a in range(3):
        for b in range(3):
            for c in range(3):
                for d in range(3):
                    combo = (a, b, c, d)
                    if a not in (0, 1) or d not in (0, 2):
                        continue
                    if len(set(combo)) < 2:
                        continue
                    if a == b == c or b == c == d:
                        continue
                    templates.append(combo)
    return tuple(templates)


_FUNCTION_TEMPLATES = _function_templates()


def _function_groups(n: int):
    """音数 n の音階を、位置でトニック/サブドミナント/ドミナントに分ける。"""
    if n >= 7:
        return ((0, 2, 5), (1, 3), (4, 6))
    if n == 6:
        return ((0, 2, 4), (1, 3), (5,))
    if n == 5:
        return ((0, 2), (3,), (1, 4))
    if n == 4:
        return ((0, 2), (3,), (1,))
    return ((0,), (min(2, n - 1),), (min(1, n - 1),))  # 3 音以下


def _product(groups):
    """各スロットの候補リストから直積を作る (itertools.product 相当)。"""
    result = [()]
    for options in groups:
        result = [combo + (opt,) for combo in result for opt in options]
    return result


def _generate_progressions(n: int) -> list:
    """音数 n の音階向けに、機能和声のひな型からコード進行を生成する。"""
    groups = _function_groups(n)
    out = []
    seen = set()
    for template in _FUNCTION_TEMPLATES:
        for combo in _product([groups[func] for func in template]):
            if combo not in seen and all(0 <= d < n for d in combo):
                seen.add(combo)
                out.append(combo)
    return out


def _build_library(default, n: int) -> tuple:
    """既定進行を先頭に、生成した進行を続けて上限まで並べる。"""
    ordered = []
    seen = set()
    for prog in [tuple(default)] + _generate_progressions(n):
        if prog not in seen and len(prog) == 4 and all(0 <= d < n for d in prog):
            seen.add(prog)
            ordered.append(prog)
        if len(ordered) >= PROGRESSION_LIMIT:
            break
    return tuple(ordered)


SCALE_PROGRESSIONS = {
    sid: _build_library(SCALES[sid]["progression"], len(SCALES[sid]["intervals"]))
    for sid in SCALES
}
_PHOTO_LIBRARY_CACHE = {}


def default_progression(count: int) -> tuple:
    """音数 count の音階に合わせた無難な既定コード進行。"""
    return (0, min(3, count - 1), min(1, count - 1), min(4, count - 1))


def progression_choices(scale_id: str, custom=None) -> tuple:
    """その音階で使えるコード進行の候補一覧。自動作成が 1 つ選ぶ。"""
    if scale_id == PHOTO_SCALE:
        n = len(custom) if custom else 3
        if n not in _PHOTO_LIBRARY_CACHE:
            _PHOTO_LIBRARY_CACHE[n] = _build_library(default_progression(n), n)
        return _PHOTO_LIBRARY_CACHE[n]
    return SCALE_PROGRESSIONS[scale_id]


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


def chord_name(chord: Chord) -> str:
    """コードの名前を作る (例: C, Am, Bdim, Caug)。"""
    root = NOTE_NAMES[chord.root % 12]
    third = (chord.third - chord.root) % 12
    fifth = (chord.fifth - chord.root) % 12
    quality = {(4, 7): "", (3, 7): "m", (3, 6): "dim", (4, 8): "aug"}.get(
        (third, fifth), "")
    return root + quality


def progression_names(key: int, scale_id: str, progression, custom=None) -> list:
    """コード進行を音名の列にする (例: ['Am', 'F', 'C', 'G'])。"""
    return [chord_name(chord_at(key, scale_id, 0, 4, (degree,), custom))
            for degree in progression]
