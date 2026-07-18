"""配色とフォント — 音色セットに合わせて切り替わるパレット。

set_palette(sound) を呼ぶとモジュール変数 (BG, PANEL, ...) が差し替わる。
描画コードは毎回 theme.BG のように参照するため、切替後に再描画すれば反映される。
"""

# 音色セットごとのパレット。キーは共通。
PALETTES = {
    # ピコピコ 8bit — 深緑 (携帯ゲーム機の液晶風)
    "retro8": {
        "BG": "#0c1911", "PANEL": "#132717", "PANEL_EDGE": "#2c5236",
        "GRID_BG": "#162c1c", "ROW_SCALE": "#1c3a25", "ROW_ROOT": "#25492e",
        "GRID_LINE": "#24422c", "GRID_BEAT": "#33583d", "GRID_MEASURE": "#55855c",
        "TEXT": "#cde6a5", "TEXT_DIM": "#7fa876", "ACCENT": "#9bbc0f",
        "PLAYHEAD": "#f4f6cf", "DANGER": "#e08a8a",
        "KEY_WHITE": "#9bbc0f", "KEY_BLACK": "#33583d",
        "KEY_TEXT": "#0f2413", "KEY_TEXT_ON_BLACK": "#cde6a5",
        "BTN_BG": "#1d3a26", "BTN_ACTIVE": "#2f5a3a",
        "BTN_ON": "#9bbc0f", "BTN_ON_TEXT": "#12240f",
    },
    # まろやか 16bit — 深紫 (ホールのような落ち着いた雰囲気)
    "warm16": {
        "BG": "#171126", "PANEL": "#211936", "PANEL_EDGE": "#4a3a6e",
        "GRID_BG": "#251c3d", "ROW_SCALE": "#2e2450", "ROW_ROOT": "#3a2e64",
        "GRID_LINE": "#352a56", "GRID_BEAT": "#473968", "GRID_MEASURE": "#6d5a96",
        "TEXT": "#e4d9f7", "TEXT_DIM": "#a08fc4", "ACCENT": "#c9a0ff",
        "PLAYHEAD": "#f6efff", "DANGER": "#f09090",
        "KEY_WHITE": "#c9a0ff", "KEY_BLACK": "#473968",
        "KEY_TEXT": "#221641", "KEY_TEXT_ON_BLACK": "#e4d9f7",
        "BTN_BG": "#2e2450", "BTN_ACTIVE": "#453768",
        "BTN_ON": "#c9a0ff", "BTN_ON_TEXT": "#221641",
    },
    # きらめき 32bit — 藍と水色 (クリアな液晶風)
    "clear32": {
        "BG": "#0b1420", "PANEL": "#101e30", "PANEL_EDGE": "#2b5170",
        "GRID_BG": "#132539", "ROW_SCALE": "#18304a", "ROW_ROOT": "#1e3f5e",
        "GRID_LINE": "#1d3a54", "GRID_BEAT": "#2a4f6e", "GRID_MEASURE": "#4a7fa5",
        "TEXT": "#d2ecfa", "TEXT_DIM": "#7fa9c4", "ACCENT": "#66d9e8",
        "PLAYHEAD": "#effbff", "DANGER": "#f09090",
        "KEY_WHITE": "#66d9e8", "KEY_BLACK": "#2a4f6e",
        "KEY_TEXT": "#0a2530", "KEY_TEXT_ON_BLACK": "#d2ecfa",
        "BTN_BG": "#183350", "BTN_ACTIVE": "#255075",
        "BTN_ON": "#66d9e8", "BTN_ON_TEXT": "#0a2530",
    },
}

# UI に出す音色名 (固有のゲーム機名は使わない)
SOUND_LABELS = {
    "retro8": "ピコピコ 8bit",
    "warm16": "まろやか 16bit",
    "clear32": "きらめき 32bit",
}
SOUND_IDS = tuple(SOUND_LABELS)


def set_palette(sound: str):
    """パレットを音色セットに合わせて切り替える。"""
    palette = PALETTES[sound]
    globals().update(palette)


# 既定パレットを展開 (BG などのモジュール変数を作る)
set_palette("retro8")

# パート (メロディ / ベース / リズム / サブ) — 全パレット共通
PART_COLORS = ("#8fd177", "#68b9c9", "#e08a8a", "#d9b45a")
PART_NAMES = ("メロディ", "ベース", "リズム", "サブ")
PART_WAVES = ("パルス波", "三角波", "ノイズ", "ノコギリ波")

# パターンパレット (旧版と同系の 8 色) — 全パレット共通
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
