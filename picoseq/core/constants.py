"""共通定数 — データ形式の上限値とパート定義。"""

APP_ID = "picoseq"
# v2: progression / v3: custom_scale / v4: sound / v5: パートのレイヤー / v6: パターン名
# v7: パートごとの音量
SCHEMA_VERSION = 7

# パターン名の最大文字数
PATTERN_NAME_MAX = 24

# 音色セット (シンセの性格)。UI での表示名は theme 側で持つ
SOUND_SETS = ("retro8", "warm16", "clear32")
DEFAULT_SOUND = "retro8"

# カスタム進行の長さの上限
PROGRESSION_MAX_LEN = 16

# フォト音階の音数 (半音クラスの数)
CUSTOM_SCALE_MIN = 3
CUSTOM_SCALE_MAX = 12

# 音域 (MIDI ノート番号)
PITCH_MIN = 36  # C2
PITCH_MAX = 84  # C6
PITCH_COUNT = PITCH_MAX - PITCH_MIN + 1

# フレーズ
MAX_NOTES = 1024  # フレーズあたりの最大音符数
MEASURES = 2      # フレーズの小節数
BEATS_MIN = 2     # 拍子の下限 (2/4)
BEATS_MAX = 7     # 拍子の上限 (7/4)

# パート (波形)
WAVE_PULSE = 0     # メロディ: パルス波
WAVE_TRIANGLE = 1  # ベース: 三角波
WAVE_NOISE = 2     # リズム: ノイズ
WAVE_SAW = 3       # サブ: ノコギリ波
PART_COUNT = 4
MAX_LAYERS = 8     # 1 パートあたりのレイヤー (重ね) の上限

# ソング
PATTERN_COUNT = 8
SONG_TRACKS = 4
SONG_BLOCKS = 16
EMPTY_CELL = 255  # ソングセルの空値

# テンポとシード
BPM_MIN = 60
BPM_MAX = 240
SEED_MIN = 1
SEED_MAX = 999_999

# 音声
SAMPLE_RATE = 44100


def steps_per_phrase(beats: int) -> int:
    """1フレーズの総ステップ数 (16分音符単位)。"""
    return beats * 4 * MEASURES


MAX_STEPS = steps_per_phrase(BEATS_MAX)  # 56


def clamp(value: int, lo: int, hi: int) -> int:
    """value を [lo, hi] に収める。"""
    return max(lo, min(hi, value))
