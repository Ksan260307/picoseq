"""配色とフォント — ゲームボーイ風の深緑パレット。"""

# 背景系
BG = "#0c1911"          # 最深部
PANEL = "#132717"       # パネル
PANEL_EDGE = "#2c5236"  # パネル枠
GRID_BG = "#162c1c"     # ロールの地
ROW_SCALE = "#1c3a25"   # スケール内の行
ROW_ROOT = "#25492e"    # ルート音の行
GRID_LINE = "#24422c"
GRID_BEAT = "#33583d"
GRID_MEASURE = "#55855c"

# 前景系
TEXT = "#cde6a5"
TEXT_DIM = "#7fa876"
ACCENT = "#9bbc0f"
PLAYHEAD = "#f4f6cf"
DANGER = "#e08a8a"

# 鍵盤
KEY_WHITE = "#9bbc0f"
KEY_BLACK = "#33583d"
KEY_TEXT = "#0f2413"
KEY_TEXT_ON_BLACK = "#cde6a5"

# ボタン
BTN_BG = "#1d3a26"
BTN_ACTIVE = "#2f5a3a"
BTN_ON = "#9bbc0f"
BTN_ON_TEXT = "#12240f"

# パート (メロディ / ベース / リズム / サブ)
PART_COLORS = ("#8fd177", "#68b9c9", "#e08a8a", "#d9b45a")
PART_NAMES = ("メロディ", "ベース", "リズム", "サブ")
PART_WAVES = ("パルス波", "三角波", "ノイズ", "ノコギリ波")

# パターンパレット (旧版と同系の 8 色)
PATTERN_COLORS = ("#ff7b9c", "#60d394", "#aaf683", "#ffd97d",
                  "#ff9b85", "#84dcc6", "#a5ffd6", "#ffa69e")

FONT = ("Yu Gothic UI", 10)
FONT_SMALL = ("Yu Gothic UI", 9)
FONT_BOLD = ("Yu Gothic UI", 10, "bold")
FONT_TITLE = ("Yu Gothic UI", 13, "bold")
FONT_MONO = ("Consolas", 8)
FONT_MONO_BOLD = ("Consolas", 8, "bold")


def dim(color: str, percent: int = 45) -> str:
    """色を暗くする (percent = 残す明るさ %)。非選択パートの音符に使う。"""
    r = int(color[1:3], 16) * percent // 100
    g = int(color[3:5], 16) * percent // 100
    b = int(color[5:7], 16) * percent // 100
    return f"#{r:02x}{g:02x}{b:02x}"
