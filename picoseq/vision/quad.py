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


MAX_QUADS = 8


def quantile_threshold(grid: list, percent: int) -> int:
    """輝度ヒストグラムの percent % 点。中間調の被写体を拾う補助しきい値。"""
    hist = [0] * 256
    for row in grid:
        for v in row:
            hist[v] += 1
    target = sum(hist) * percent // 100
    total = 0
    for t in range(256):
        total += hist[t]
        if total >= target:
            return t
    return 255


def _bbox(points) -> tuple:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_overlap(a, b) -> float:
    """バウンディングボックスの IoU (重なり具合 0..1)。重複判定に使う。"""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    if inter == 0:
        return 0.0
    area_a = (ax1 - ax0) * (ay1 - ay0)
    area_b = (bx1 - bx0) * (by1 - by0)
    return inter / (area_a + area_b - inter)


def detect_quads(grid: list, max_count: int = MAX_QUADS) -> list:
    """格子から四角形らしい領域を複数探す (面積の大きい順、最大 max_count 個)。

    精度向上のため、大津のしきい値に加えて輝度の 30% / 70% 点でも二値化し、
    明・暗の両方の向きで候補を集める。重なった候補は面積の大きい方を残す。
    """
    h = len(grid)
    w = len(grid[0]) if h else 0
    if w < 8 or h < 8:
        return []
    min_area = max(16, w * h // MIN_AREA_RATIO)

    thresholds = sorted({otsu_threshold(grid),
                         quantile_threshold(grid, 30),
                         quantile_threshold(grid, 70)})
    candidates = []
    for threshold in thresholds:
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
                candidates.append(Quad(points=tuple(corners), grid_w=w, grid_h=h,
                                       pixel_area=area, fill=fill))

    # 面積の大きい順に採用し、既に採った四角形と重なるものは捨てる
    candidates.sort(key=lambda q: (-q.pixel_area, q.points))
    accepted = []
    for quad in candidates:
        box = _bbox(quad.points)
        if any(_bbox_overlap(box, _bbox(a.points)) > 0.5 for a in accepted):
            continue
        accepted.append(quad)
        if len(accepted) >= max_count:
            break
    return accepted


def detect_quad(grid: list):
    """最も大きい四角形を 1 つ返す (無ければ None)。"""
    quads = detect_quads(grid, max_count=1)
    return quads[0] if quads else None
