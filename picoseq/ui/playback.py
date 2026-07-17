"""再生アダプタ — winsound による非同期 WAV 再生と、表示用の再生時計。

時計は実時間 (time.monotonic) を使うが、これは再生位置の「表示」にだけ使う。
確定状態 (プロジェクト) には一切影響させない (表示適応)。
"""

import time

try:
    import winsound
except ImportError:  # Windows 以外
    winsound = None

BYTES_PER_SAMPLE = 2  # 16bit モノラル


def rotate_pcm(pcm: bytes, offset_samples: int) -> bytes:
    """16bit PCM をサンプル単位で回転する (offset から始まるように並べ替える)。

    ループの途中から再生し直すために使う。回転しても内容は同じループ。
    """
    total = len(pcm) // BYTES_PER_SAMPLE
    if total == 0:
        return pcm
    cut = (offset_samples % total) * BYTES_PER_SAMPLE
    return pcm[cut:] + pcm[:cut]


class SoundPlayer:
    """WAV ファイルの非同期再生。silent=True なら何もしない (自己診断用)。"""

    def __init__(self, silent: bool = False):
        self.silent = silent or winsound is None

    def play_file(self, path: str, loop: bool = False):
        if self.silent:
            return
        flags = winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        if loop:
            flags |= winsound.SND_LOOP
        winsound.PlaySound(path, flags)

    def stop(self):
        if self.silent:
            return
        winsound.PlaySound(None, winsound.SND_PURGE)


class PlayClock:
    """ループ再生の経過位置 (秒)。表示にのみ使う (表示適応)。

    offset は「音声をどの位置から鳴らし始めたか」。演奏中に編集して
    現在位置から再生し直すとき、音声を回転させた分を offset に持たせると
    再生ヘッドの表示が途切れずに続く。
    """

    def __init__(self):
        self.started_at = None
        self.duration = 0.0
        self.offset = 0.0

    def start(self, duration_seconds: float, offset_seconds: float = 0.0):
        self.duration = max(duration_seconds, 0.001)
        self.offset = offset_seconds % self.duration
        self.started_at = time.monotonic()

    def stop(self):
        self.started_at = None

    def position(self):
        """ループ内の現在位置 (秒)。停止中は None。"""
        if self.started_at is None:
            return None
        return (self.offset + time.monotonic() - self.started_at) % self.duration
