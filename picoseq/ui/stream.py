"""ストリーミング再生 — Windows の winmm (waveOut) を ctypes で直接使う。

ファイル再生 (winsound) と違い、サンプル列を自分で送り続ける方式なので:

- **ループの継ぎ目で無音を挟まずに別のループへ乗り換えられる** (set_next)
  winsound は別ファイルを鳴らし直すため、そこで必ず途切れていた。
- 効果音を音楽に**重ねて**鳴らせる (play_oneshot)。スクラッチが music を止めない。

対応しない環境 (Windows 以外・デバイスが開けない) では open() が False を返すので、
呼び出し側は従来のファイル再生へフォールバックする。
"""

import ctypes
import sys
import threading
import time
from array import array

WHDR_DONE = 0x00000001
WAVE_MAPPER = 0xFFFFFFFF
SAMPLE_MAX = 32767
SAMPLE_MIN = -32768


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


def mix_into(chunk: array, source: array, start: int, offset: int) -> int:
    """source を chunk の offset 位置から重ねて、source の新しい読み位置を返す。

    16bit に収まるよう飽和させる。純粋な整数演算 (テストしやすいよう独立させている)。
    """
    take = min(len(source) - start, len(chunk) - offset)
    for i in range(take):
        value = chunk[offset + i] + source[start + i]
        if value > SAMPLE_MAX:
            value = SAMPLE_MAX
        elif value < SAMPLE_MIN:
            value = SAMPLE_MIN
        chunk[offset + i] = value
    return start + take


class StreamPlayer:
    """PCM を送り続けるループ再生器。継ぎ目なしの乗り換えと重ね合わせができる。"""

    def __init__(self, rate: int = 44100, frames: int = 2048, buffers: int = 6):
        self.rate = rate
        self.frames = frames
        self.buffers = buffers
        self._winmm = None
        self._handle = None
        self._bufs = []
        self._hdrs = []
        self._queued = []
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._loop = None        # array("h") 現在のループ
        self._next = None        # 境界で乗り換える次のループ
        self._pos = 0
        self._oneshots = []      # [[array, 読み位置], ...]
        self.loops = 0           # ループが一周した回数
        self.switches = 0        # 次のループへ乗り換えた回数

    # ---- 開閉 ----

    def open(self) -> bool:
        if not is_supported():
            return False
        try:
            winmm = ctypes.windll.winmm
        except (AttributeError, OSError):
            return False
        fmt = _WaveFormat(1, 1, self.rate, self.rate * 2, 2, 16, 0)
        handle = ctypes.c_void_p()
        if winmm.waveOutOpen(ctypes.byref(handle), WAVE_MAPPER,
                             ctypes.byref(fmt), 0, 0, 0) != 0:
            return False
        self._winmm = winmm
        self._handle = handle
        size = self.frames * 2
        for _ in range(self.buffers):
            buf = ctypes.create_string_buffer(size)
            hdr = _WaveHdr(lpData=ctypes.cast(buf, ctypes.c_char_p),
                           dwBufferLength=size)
            winmm.waveOutPrepareHeader(handle, ctypes.byref(hdr), ctypes.sizeof(hdr))
            self._bufs.append(buf)
            self._hdrs.append(hdr)
            self._queued.append(False)
        self._running = True
        self._thread = threading.Thread(target=self._feed, daemon=True)
        self._thread.start()
        return True

    def close(self):
        self._running = False
        thread = self._thread
        if thread is not None:
            thread.join(timeout=1.0)
        if self._handle is not None and self._winmm is not None:
            self._winmm.waveOutReset(self._handle)
            for hdr in self._hdrs:
                self._winmm.waveOutUnprepareHeader(self._handle, ctypes.byref(hdr),
                                                   ctypes.sizeof(hdr))
            self._winmm.waveOutClose(self._handle)
        self._handle = None
        self._hdrs = []
        self._bufs = []

    # ---- 再生の指示 ----

    def set_loop(self, pcm: bytes):
        """今すぐこのループに切り替える (先頭から)。"""
        data = array("h")
        data.frombytes(pcm)
        with self._lock:
            self._loop = data
            self._next = None
            self._pos = 0

    def replace_loop(self, pcm: bytes):
        """再生を止めず、今の位置を保ったまま中身だけ差し替える (パラメータの即時反映)。

        長さが変わる (テンポ変更) ときは、同じ相対位置へ読み替える。
        """
        data = array("h")
        data.frombytes(pcm)
        with self._lock:
            if not self._loop or not data:
                self._loop = data
                self._pos = 0
            else:
                fraction = self._pos / len(self._loop)
                self._loop = data
                self._pos = min(len(data) - 1, int(fraction * len(data)))
            self._next = None

    def set_next(self, pcm: bytes):
        """今のループが一周したところで、無音を挟まずこのループへ乗り換える。"""
        data = array("h")
        data.frombytes(pcm)
        with self._lock:
            if self._loop is None:      # 何も鳴っていなければ即開始
                self._loop = data
                self._pos = 0
            else:
                self._next = data

    def play_oneshot(self, pcm: bytes):
        """効果音を今の音に重ねて 1 回鳴らす。"""
        data = array("h")
        data.frombytes(pcm)
        with self._lock:
            if len(self._oneshots) > 8:
                self._oneshots.pop(0)
            self._oneshots.append([data, 0])

    def stop(self):
        """鳴らすものを空にする (デバイスは開いたまま無音を送り続ける)。"""
        with self._lock:
            self._loop = None
            self._next = None
            self._pos = 0
            self._oneshots = []

    @property
    def playing(self) -> bool:
        return self._loop is not None

    def loop_position(self):
        """ループ内の読み出し位置 (サンプル)。何も無ければ None。"""
        with self._lock:
            if self._loop is None:
                return None
            return self._pos

    # ---- 供給スレッド ----

    def _feed(self):
        while self._running:
            fed = False
            for i, hdr in enumerate(self._hdrs):
                if not self._running:
                    break
                if self._queued[i] and not (hdr.dwFlags & WHDR_DONE):
                    continue                      # まだ再生中
                data = self._next_chunk()
                ctypes.memmove(self._bufs[i], data, len(data))
                hdr.dwBufferLength = len(data)
                hdr.dwFlags &= ~WHDR_DONE
                self._winmm.waveOutWrite(self._handle, ctypes.byref(hdr),
                                         ctypes.sizeof(hdr))
                self._queued[i] = True
                fed = True
            if not fed:
                time.sleep(0.004)

    def _next_chunk(self) -> bytes:
        chunk = array("h", bytes(self.frames * 2))
        with self._lock:
            loop = self._loop
            if loop is not None and len(loop) > 0:
                filled = 0
                while filled < self.frames:
                    remain = len(loop) - self._pos
                    take = min(remain, self.frames - filled)
                    chunk[filled:filled + take] = loop[self._pos:self._pos + take]
                    self._pos += take
                    filled += take
                    if self._pos >= len(loop):    # 一周した = 継ぎ目
                        self._pos = 0
                        self.loops += 1
                        if self._next is not None:
                            loop = self._loop = self._next
                            self._next = None
                            self.switches += 1
            # 効果音を重ねる
            if self._oneshots:
                alive = []
                for shot in self._oneshots:
                    shot[1] = mix_into(chunk, shot[0], shot[1], 0)
                    if shot[1] < len(shot[0]):
                        alive.append(shot)
                self._oneshots = alive
        return chunk.tobytes()
