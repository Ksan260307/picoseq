"""マイク録音 — Windows の winmm を ctypes で直接使う簡易レコーダー。

依存パッケージなしでマイクから 16bit モノラル PCM を録る。
Windows 以外・マイクなしの環境では RuntimeError を投げる。
"""

import ctypes
import sys
import time

RECORD_RATE = 22050


def is_supported() -> bool:
    return sys.platform == "win32"


class _WaveFormat(ctypes.Structure):
    _fields_ = [
        ("wFormatTag", ctypes.c_ushort),
        ("nChannels", ctypes.c_ushort),
        ("nSamplesPerSec", ctypes.c_uint),
        ("nAvgBytesPerSec", ctypes.c_uint),
        ("nBlockAlign", ctypes.c_ushort),
        ("wBitsPerSample", ctypes.c_ushort),
        ("cbSize", ctypes.c_ushort),
    ]


class _WaveHdr(ctypes.Structure):
    _fields_ = [
        ("lpData", ctypes.c_char_p),
        ("dwBufferLength", ctypes.c_uint),
        ("dwBytesRecorded", ctypes.c_uint),
        ("dwUser", ctypes.c_void_p),
        ("dwFlags", ctypes.c_uint),
        ("dwLoops", ctypes.c_uint),
        ("lpNext", ctypes.c_void_p),
        ("reserved", ctypes.c_void_p),
    ]


WHDR_DONE = 0x00000001
WAVE_MAPPER = ctypes.c_uint(-1 & 0xFFFFFFFF)


def record(seconds: float, rate: int = RECORD_RATE) -> bytes:
    """マイクから録音して 16bit モノラル PCM を返す (呼び出し中はブロックする)。"""
    if not is_supported():
        raise RuntimeError("マイク録音は Windows のみ対応です。WAV ファイルを読み込んでください。")
    winmm = ctypes.windll.winmm

    fmt = _WaveFormat(
        wFormatTag=1,  # PCM
        nChannels=1,
        nSamplesPerSec=rate,
        nAvgBytesPerSec=rate * 2,
        nBlockAlign=2,
        wBitsPerSample=16,
        cbSize=0,
    )
    handle = ctypes.c_void_p()
    result = winmm.waveInOpen(ctypes.byref(handle), WAVE_MAPPER,
                              ctypes.byref(fmt), 0, 0, 0)
    if result != 0:
        raise RuntimeError(f"マイクを開けませんでした (エラー {result})。接続と権限を確認してください。")

    size = int(seconds * rate) * 2
    buffer = ctypes.create_string_buffer(size)
    header = _WaveHdr(lpData=ctypes.cast(buffer, ctypes.c_char_p),
                      dwBufferLength=size)
    try:
        winmm.waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        winmm.waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(header))
        winmm.waveInStart(handle)

        deadline = time.monotonic() + seconds + 1.0
        while not (header.dwFlags & WHDR_DONE) and time.monotonic() < deadline:
            time.sleep(0.05)
        winmm.waveInStop(handle)
        winmm.waveInReset(handle)
        winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        recorded = header.dwBytesRecorded or size
        return buffer.raw[:recorded]
    finally:
        winmm.waveInClose(handle)


def pcm_to_samples(pcm: bytes) -> list:
    """16bit PCM を整数サンプル列にする。"""
    from array import array
    values = array("h")
    values.frombytes(pcm[: len(pcm) // 2 * 2])
    return list(values)
