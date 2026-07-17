"""CLI: py -m picoseq.vision <画像> — 四角形を検出して和音を表示する。"""

import sys

from .harmony import describe, harmony_from_quad
from .image import load_gray_grid
from .quad import detect_quad


def main(argv) -> int:
    if len(argv) != 1:
        print("使い方: py -m picoseq.vision <画像ファイル (PNG/BMP/PPM/JPEG)>")
        return 2
    try:
        grid = load_gray_grid(argv[0])
    except (OSError, ValueError) as error:
        print(f"読み込み失敗: {error}")
        return 1
    quad = detect_quad(grid)
    if quad is None:
        print("四角形が見つかりませんでした。被写体と背景の明暗差を付けてください。")
        return 1
    print(f"検出: {quad.grid_w}x{quad.grid_h} 格子 / コーナー {list(quad.points)} "
          f"/ fill {quad.fill:.2f}")
    print(describe(harmony_from_quad(quad)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
