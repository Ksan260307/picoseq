"""vision テスト用の合成画像ヘルパー (test* でないので収集されない)。"""

import struct
import zlib


def draw_quad_grid(width, height, corners, fg=230, bg=40):
    """凸四角形を塗ったグレースケール格子を作る。corners は時計回り。"""
    def inside(px, py):
        sign = None
        n = len(corners)
        for i in range(n):
            x1, y1 = corners[i]
            x2, y2 = corners[(i + 1) % n]
            cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
            if cross != 0:
                side = cross > 0
                if sign is None:
                    sign = side
                elif side != sign:
                    return False
        return True

    return [[fg if inside(x, y) else bg for x in range(width)]
            for y in range(height)]


def draw_circle_grid(width, height, cx, cy, radius, fg=230, bg=40):
    return [[fg if (x - cx) ** 2 + (y - cy) ** 2 <= radius ** 2 else bg
             for x in range(width)] for y in range(height)]


def make_ppm_p6(width, height, pixels, comment=None):
    header = b"P6\n"
    if comment:
        header += b"# " + comment + b"\n"
    header += f"{width} {height}\n255\n".encode()
    body = b"".join(bytes(p) for p in pixels)
    return header + body


def make_ppm_p3(width, height, pixels):
    lines = [f"P3\n{width} {height}\n255"]
    for r, g, b in pixels:
        lines.append(f"{r} {g} {b}")
    return "\n".join(lines).encode()


def make_bmp(width, height, pixels, top_down=False):
    """24bit 無圧縮 BMP。pixels は RGB タプルの平坦リスト (上から下)。"""
    stride = (width * 3 + 3) // 4 * 4
    data = bytearray()
    rows = range(height) if top_down else range(height - 1, -1, -1)
    for y in rows:
        line = bytearray()
        for x in range(width):
            r, g, b = pixels[y * width + x]
            line += bytes((b, g, r))
        line += b"\x00" * (stride - len(line))
        data += line
    h = -height if top_down else height
    header = struct.pack("<2sIHHI", b"BM", 54 + len(data), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, h, 1, 24, 0, len(data),
                       2835, 2835, 0, 0)
    return bytes(header + info + data)


def make_png(width, height, pixels, color_type=2, filter_type=0, palette=None):
    """8bit PNG。pixels は color_type に応じた値の平坦リスト。

    filter_type を指定すると全走査線にそのフィルタを適用する
    (デコーダのフィルタ復元を検査するため)。
    """
    channels = {0: 1, 2: 3, 3: 1, 6: 4}[color_type]
    stride = width * channels

    raw_lines = []
    for y in range(height):
        line = bytearray()
        for x in range(width):
            value = pixels[y * width + x]
            if channels == 1:
                line.append(value)
            else:
                line.extend(value)
        raw_lines.append(bytes(line))

    def paeth(a, b, c):
        p = a + b - c
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return c

    filtered = bytearray()
    prev = bytes(stride)
    for line in raw_lines:
        filtered.append(filter_type)
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = prev[i]
            up_left = prev[i - channels] if i >= channels else 0
            if filter_type == 0:
                out = line[i]
            elif filter_type == 1:
                out = line[i] - left
            elif filter_type == 2:
                out = line[i] - up
            elif filter_type == 3:
                out = line[i] - (left + up) // 2
            else:
                out = line[i] - paeth(left, up, up_left)
            filtered.append(out & 0xFF)
        prev = line

    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body)))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    if palette is not None:
        out += chunk(b"PLTE", b"".join(bytes(c) for c in palette))
    out += chunk(b"IDAT", zlib.compress(bytes(filtered)))
    out += chunk(b"IEND", b"")
    return out
