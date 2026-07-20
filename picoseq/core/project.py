"""プロジェクト — アプリの全データを 1 つの不変オブジェクトで持つ。"""

from dataclasses import dataclass, field, replace

from .constants import DEFAULT_SOUND, PART_COUNT, PATTERN_COUNT, steps_per_phrase
from .music import DEFAULT_SCALE
from .phrase import EMPTY_PHRASE
from .song import EMPTY_SONG


@dataclass(frozen=True)
class PartParams:
    """1 レイヤーの音作りパラメータ (整数 %)。"""
    tone: int = 50  # 音色 0..100
    gate: int = 80  # 音の長さ 10..100


@dataclass(frozen=True)
class Pattern:
    """保存済みフレーズ 1 スロット。"""
    used: bool = False
    notes: tuple = EMPTY_PHRASE


# 各パート (波形) は 1〜8 レイヤーを持つ。既定は各パート 1 レイヤーずつ。
_DEFAULT_PARTS = tuple((PartParams(),) for _ in range(PART_COUNT))


@dataclass(frozen=True)
class Project:
    """アプリ全体の状態。"""
    bpm: int = 120
    beats: int = 4          # 拍子 (n/4)
    key: int = 0            # 0=C .. 11=B
    scale: str = DEFAULT_SCALE
    seed: int = 1           # 自動作成のシード
    progression: tuple = None    # カスタムコード進行 (度数の列)。None = 音階の既定
    custom_scale: tuple = None   # 写真から抽出した音階 (半音の列)。scale="photo" で使う
    sound: str = DEFAULT_SOUND   # 音色セット (retro8 / warm16 / clear32)
    # parts[wave] = そのパートのレイヤーごとの PartParams のタプル (1〜8)
    parts: tuple = _DEFAULT_PARTS
    phrase: tuple = EMPTY_PHRASE
    patterns: tuple = tuple(Pattern() for _ in range(PATTERN_COUNT))
    song: tuple = EMPTY_SONG


def new_project() -> Project:
    """初期状態のプロジェクト。"""
    return Project()


def steps_of(project: Project) -> int:
    """現在の拍子でのフレーズ総ステップ数。"""
    return steps_per_phrase(project.beats)


def layer_count(project: Project, wave: int) -> int:
    """そのパートのレイヤー数。"""
    return len(project.parts[wave])


def part_params(project: Project, wave: int, layer: int) -> PartParams:
    """(wave, layer) の音作りパラメータ。範囲外は最後のレイヤーに丸める。

    ソングでは、レイヤーの多いパターンを少ないプロジェクトで鳴らすことがあるため。
    """
    layers = project.parts[wave]
    if layer >= len(layers):
        layer = len(layers) - 1
    return layers[layer]


# dataclasses.replace の再輸出 (アクション実装で使う)
update = replace
