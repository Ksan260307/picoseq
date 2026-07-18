"""コマンドライン: py -m picoseq.vision <画像> — 四角形を検出して音階を表示する。"""

import sys

from .harmony import describe, photo_scale_from_quads
from .image import load_gray_grid
from .quad import detect_quads


def main(argv) -> int:
    if len(argv) != 1:
        print("使い方: py -m picoseq.vision <画像ファイル (PNG/BMP/PPM/JPEG)>")
        return 2
    try:
        grid = load_gray_grid(argv[0])
    except (OSError, ValueError) as error:
        print(f"読み込み失敗: {error}")
        return 1
    quads = detect_quads(grid)
    if not quads:
        print("四角形が見つかりませんでした。被写体と背景の明暗差を付けてください。")
        return 1
    for i, quad in enumerate(quads):
        print(f"四角形 {i + 1}: コーナー {list(quad.points)} / "
              f"面積 {quad.pixel_area}px / fill {quad.fill:.2f}")
    print(describe(photo_scale_from_quads(quads)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
