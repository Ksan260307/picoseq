"""四角形検出 — グレースケール格子から最大の四角形らしい領域を見つける。

手順:
  1. Otsu 法でしきい値を決めて二値化
  2. 明・暗の両極性で連結成分を探す (画像の 4 辺すべてに触れる成分 = 背景は除外)
  3. 最大成分の凸包を取り、包内で面積最大の 4 頂点を選ぶ
  4. 成分面積と四角形面積の比 (fill) で「四角形らしさ」を判定

座標・面積は整数演算。決定論的で、同じ格子からは常に同じ結果が出る。
"""

from typing import NamedTuple

MIN_AREA_RATIO = 100   # 成分は全画素の 1/100 以上
FILL_MIN = 0.70        # 成分面積 / 四角形面積 の下限
FILL_MAX = 1.30        # 同上限 (円などの膨らみはここで落ちる)


class Quad(NamedTuple):
    """検出結果。points は TL, TR, BR, BL の順の格子座標。"""
    points: tuple
    grid_w: int
    grid_h: int
    pixel_area: int  # 成分の画素数
    fill: float      # 成分面積 / 四角形面積


def otsu_threshold(grid: list) -> int:
    """クラス間分散を最大にするしきい値 (整数演算で厳密に比較)。"""
    hist = [0] * 256
    for row in grid:
        for v in row:
            hist[v] += 1
    total = sum(hist)
    sum_total = sum(i * hist[i] for i in range(256))

    best_t = 0
    best_score = -1
    weight_b = 0
    sum_b = 0
    for t in range(256):
        weight_b += hist[t]
        if weight_b == 0:
            continue
        weight_f = total - weight_b
        if weight_f == 0:
            break
        sum_b += t * hist[t]
        # クラス間分散 ∝ wB*wF*(muB-muF)^2 を分数を使わず整数で比較する
        diff = sum_b * weight_f - (sum_total - sum_b) * weight_b
        score = diff * diff // (weight_b * weight_f)
        if score > best_score:
            best_score = score
            best_t = t
    return best_t


def find_components(grid: list, threshold: int, dark: bool) -> list:
    """二値化して 4 連結成分を列挙する。各成分は (画素数, 触れた辺数, 画素リスト)。"""
    h = len(grid)
    w = len(grid[0])
    if dark:
        mask = [[v <= threshold for v in row] for row in grid]
    else:
        mask = [[v > threshold for v in row] for row in grid]

    seen = [[False] * w for _ in range(h)]
    components = []
    for sy in range(h):
        for sx in range(w):
            if not mask[sy][sx] or seen[sy][sx]:
                continue
            pixels = []
            borders = set()
            stack = [(sx, sy)]
            seen[sy][sx] = True
            while stack:
                x, y = stack.pop()
                pixels.append((x, y))
                if x == 0:
                    borders.add("L")
                if x == w - 1:
                    borders.add("R")
                if y == 0:
                    borders.add("T")
                if y == h - 1:
                    borders.add("B")
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            components.append((len(pixels), len(borders), pixels))
    return components


def convex_hull(points: list) -> list:
    """凸包 (Andrew の単調鎖)。反時計回りの頂点列を返す。"""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def polygon_area2(points) -> int:
    """多角形の符号なし面積の 2 倍 (靴ひも公式、整数)。"""
    total = 0
    n = len(points)
    for i in range(n):
        x1, y1 = points[i]
        x2, y2 = points[(i + 1) % n]
        total += x1 * y2 - x2 * y1
    return abs(total)


def best_quad_corners(hull: list) -> tuple:
    """凸包の頂点から、四角形の面積が最大になる 4 点を選ぶ。

    x+y / x-y の極値で初期化し、面積が増えなくなるまで 1 点ずつ置き換える。
    """
    corners = [
        min(hull, key=lambda p: p[0] + p[1]),  # TL
        max(hull, key=lambda p: p[0] - p[1]),  # TR
        max(hull, key=lambda p: p[0] + p[1]),  # BR
        min(hull, key=lambda p: p[0] - p[1]),  # BL
    ]
    for _ in range(5):
        improved = False
        for i in range(4):
            for p in hull:
                candidate = list(corners)
                candidate[i] = p
                if polygon_area2(candidate) > polygon_area2(corners):
                    corners = candidate
                    improved = True
        if not improved:
            break
    return _order_corners(corners)


def _order_corners(corners: list) -> tuple:
    """TL, TR, BR, BL の順に並べ直す。"""
    tl = min(corners, key=lambda p: p[0] + p[1])
    br = max(corners, key=lambda p: p[0] + p[1])
    rest = [p for p in corners if p is not tl and p is not br]
    if len(rest) != 2:  # 重複時のフェールセーフ
        rest = [p for p in corners if p != tl and p != br][:2]
        while len(rest) < 2:
            rest.append(tl)
    tr = max(rest, key=lambda p: p[0] - p[1])
    bl = min(rest, key=lambda p: p[0] - p[1])
    return (tl, tr, br, bl)


def detect_quad(grid: list):
    """格子から最も四角形らしい領域を探す。見つからなければ None。"""
    h = len(grid)
    w = len(grid[0]) if h else 0
    if w < 8 or h < 8:
        return None
    threshold = otsu_threshold(grid)
    min_area = max(16, w * h // MIN_AREA_RATIO)

    best = None
    for dark in (False, True):
        for area, borders, pixels in find_components(grid, threshold, dark):
            if area < min_area or borders == 4:
                continue
            hull = convex_hull(pixels)
            if len(hull) < 3:
                continue
            corners = best_quad_corners(hull)
            area2 = polygon_area2(corners)
            if area2 <= 0:
                continue
            fill = 2 * area / area2
            if not (FILL_MIN <= fill <= FILL_MAX):
                continue
            if best is None or area > best.pixel_area:
                best = Quad(points=tuple(corners), grid_w=w, grid_h=h,
                            pixel_area=area, fill=fill)
    return best
