"""WAV 形式の符号化 — 16bit モノラル PCM をファイルバイト列にする。"""

import struct

from .constants import SAMPLE_RATE


def wav_bytes(pcm: bytes, rate: int = SAMPLE_RATE) -> bytes:
    """16bit モノラル PCM を WAV ファイルのバイト列にする。"""
    channels = 1
    width = 2
    byte_rate = rate * channels * width
    block_align = channels * width
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(pcm),
        b"WAVE",
        b"fmt ",
        16,          # fmt チャンク長
        1,           # PCM (無圧縮)
        channels,
        rate,
        byte_rate,
        block_align,
        width * 8,   # ビット深度
        b"data",
        len(pcm),
    )
    return header + pcm
