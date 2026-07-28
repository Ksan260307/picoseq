"""画像の読み込み — PPM / BMP / PNG は純 Python で復号する。

JPEG などその他の形式は Pillow があればそれで読む (端のアダプタ)。
出力は縮小したグレースケール格子 (行のリスト、値 0..255) に正規化する。
縮小とグレースケール化は整数演算で行う。
"""

import struct
import zlib
from pathlib import Path

MAX_DIM = 200  # 解析用格子の最大辺


def load_gray_grid(path, max_dim: int = MAX_DIM) -> list:
    """画像ファイル → 縮小グレースケール格子 (list[list[int]])。"""
    width, height, pixels = load_rgb(path)
    return downsample_gray(width, height, pixels, max_dim)


def load_rgb(path):
    """画像ファイル → (幅, 高さ, RGB タプルの平坦リスト)。"""
    data = Path(path).read_bytes()
    if data[:2] in (b"P6", b"P3"):
        return decode_ppm(data)
    if data[:2] == b"BM":
        return decode_bmp(data)
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return decode_png(data)
    return _decode_with_pillow(path)


def _decode_with_pillow(path):
    """Pillow があれば任せる (JPEG など内蔵デコーダで読めない形式用)。"""
    try:
        from PIL import Image
    except ImportError:
        raise ValueError(
            "対応していない画像形式です。PNG / BMP / PPM を使うか、"
            "Pillow をインストールしてください (JPEG 対応)。") from None
    with Image.open(path) as img:
        img = img.convert("RGB")
        # 解析には高解像度は不要なので、先に安全な大きさまで縮めておく
        img.thumbnail((MAX_DIM * 4, MAX_DIM * 4))
        return img.width, img.height, list(img.getdata())


# ---- PPM (P6 バイナリ / P3 テキスト) ----

def decode_ppm(data: bytes):
    """PPM (P3 テキスト / P6 バイナリ) を (幅, 高さ, RGB) にする。"""
    tokens = _ppm_tokens(data)
    magic = next(tokens)
    width = int(next(tokens))
    height = int(next(tokens))
    maxval = int(next(tokens))
    if maxval != 255:
        raise ValueError(f"PPM は maxval 255 のみ対応: {maxval}")
    if width <= 0 or height <= 0:
        raise ValueError("PPM の寸法が不正です。")

    if magic == b"P3":
        values = [int(next(tokens)) for _ in range(width * height * 3)]
    else:  # P6: maxval の直後の空白 1 文字に続いてバイナリ
        offset = _ppm_binary_offset(data)
        raw = data[offset: offset + width * height * 3]
        if len(raw) < width * height * 3:
            raise ValueError("PPM の画素データが足りません。")
        values = list(raw)
    pixels = [(values[i], values[i + 1], values[i + 2])
              for i in range(0, len(values), 3)]
    return width, height, pixels


def _ppm_tokens(data: bytes):
    """ヘッダ部のトークン (コメント # は行末まで無視)。"""
    i = 0
    while i < len(data):
        c = data[i:i + 1]
        if c.isspace():
            i += 1
        elif c == b"#":
            while i < len(data) and data[i:i + 1] != b"\n":
                i += 1
        else:
            start = i
            while i < len(data) and not data[i:i + 1].isspace():
                i += 1
            yield data[start:i]


def _ppm_binary_offset(data: bytes) -> int:
    """P6 のヘッダ末尾 (maxval の次の 1 空白の直後) を探す。"""
    count = 0  # 読んだトークン数 (P6, w, h, maxval で 4)
    i = 0
    while i < len(data):
        c = data[i:i + 1]
        if c == b"#":
            while i < len(data) and data[i:i + 1] != b"\n":
                i += 1
        elif c.isspace():
            i += 1
        else:
            while i < len(data) and not data[i:i + 1].isspace():
                i += 1
            count += 1
            if count == 4:
                return i + 1  # 直後の空白 1 文字を飛ばす
    raise ValueError("PPM ヘッダが壊れています。")


# ---- BMP (無圧縮 24/32bit) ----

def decode_bmp(data: bytes):
    """BMP (24/32bit 無圧縮) を (幅, 高さ, RGB) にする。"""
    if len(data) < 54:
        raise ValueError("BMP が短すぎます。")
    pixel_offset = struct.unpack_from("<I", data, 10)[0]
    width = struct.unpack_from("<i", data, 18)[0]
    height = struct.unpack_from("<i", data, 22)[0]
    bpp = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if compression not in (0, 3) or bpp not in (24, 32):
        raise ValueError(f"BMP は無圧縮 24/32bit のみ対応 (bpp={bpp})。")

    top_down = height < 0
    height = abs(height)
    bytes_per_pixel = bpp // 8
    stride = (width * bytes_per_pixel + 3) // 4 * 4

    pixels = []
    for row in range(height):
        y = row if top_down else height - 1 - row
        base = pixel_offset + y * stride
        line = []
        for x in range(width):
            i = base + x * bytes_per_pixel
            line.append((data[i + 2], data[i + 1], data[i]))  # BGR → RGB
        pixels.extend(line)
    return width, height, pixels


# ---- PNG (8bit, グレー / RGB / パレット / RGBA, 非インターレース) ----

_PNG_CHANNELS = {0: 1, 2: 3, 3: 1, 6: 4}


def decode_png(data: bytes):
    """PNG (8bit グレー/RGB/RGBA・インタレースなし) を (幅, 高さ, RGB) にする。"""
    pos = 8
    width = height = None
    color_type = None
    palette = None
    idat = bytearray()

    while pos + 8 <= len(data):
        length = struct.unpack_from(">I", data, pos)[0]
        kind = data[pos + 4: pos + 8]
        body = data[pos + 8: pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, color_type, _, _, interlace = struct.unpack(
                ">IIBBBBB", body)
            if depth != 8 or interlace != 0 or color_type not in _PNG_CHANNELS:
                raise ValueError("PNG は 8bit 非インターレースのみ対応です。")
        elif kind == b"PLTE":
            palette = [(body[i], body[i + 1], body[i + 2])
                       for i in range(0, len(body), 3)]
        elif kind == b"IDAT":
            idat.extend(body)
        elif kind == b"IEND":
            break

    if width is None:
        raise ValueError("PNG に IHDR がありません。")
    channels = _PNG_CHANNELS[color_type]
    raw = zlib.decompress(bytes(idat))
    scanlines = _png_unfilter(raw, width, height, channels)

    pixels = []
    for line in scanlines:
        for x in range(width):
            i = x * channels
            if color_type == 0:
                v = line[i]
                pixels.append((v, v, v))
            elif color_type == 3:
                pixels.append(palette[line[i]])
            else:  # 2 / 6
                pixels.append((line[i], line[i + 1], line[i + 2]))
    return width, height, pixels


def _png_unfilter(raw: bytes, width: int, height: int, channels: int) -> list:
    """フィルタ (0..4) を戻して走査線のリストを返す。"""
    stride = width * channels
    lines = []
    prev = bytearray(stride)
    pos = 0
    for _ in range(height):
        filter_type = raw[pos]
        line = bytearray(raw[pos + 1: pos + 1 + stride])
        pos += 1 + stride
        if filter_type == 1:    # Sub
            for i in range(channels, stride):
                line[i] = (line[i] + line[i - channels]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                line[i] = (line[i] + (left + prev[i]) // 2) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                up = prev[i]
                up_left = prev[i - channels] if i >= channels else 0
                line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"未知の PNG フィルタ: {filter_type}")
        lines.append(bytes(line))
        prev = line
    return lines


def _paeth(a: int, b: int, c: int) -> int:
    """PNG の Paeth 予測子 — a/b/c のうち予測値に最も近いものを返す。"""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


# ---- 縮小とグレースケール化 (整数演算) ----

def downsample_gray(width: int, height: int, pixels: list, max_dim: int) -> list:
    """ブロック平均で max_dim 以下に縮め、輝度 (0..255) の格子にする。"""
    block = max(1, (max(width, height) + max_dim - 1) // max_dim)
    out_w = (width + block - 1) // block
    out_h = (height + block - 1) // block
    grid = []
    for by in range(out_h):
        row = []
        for bx in range(out_w):
            total = 0
            count = 0
            for y in range(by * block, min((by + 1) * block, height)):
                base = y * width
                for x in range(bx * block, min((bx + 1) * block, width)):
                    r, g, b = pixels[base + x]
                    total += (r * 299 + g * 587 + b * 114) // 1000
                    count += 1
            row.append(total // count)
        grid.append(row)
    return grid
