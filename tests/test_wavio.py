"""WAV 符号化のテスト — 標準ライブラリ wave での照合 (基準実装照合)。"""

import io
import struct
import unittest
import wave

from picoseq.core.wavio import wav_bytes


class TestWavBytes(unittest.TestCase):
    def test_header_fields(self):
        pcm = b"\x01\x02\x03\x04"
        data = wav_bytes(pcm, 44100)
        self.assertEqual(data[0:4], b"RIFF")
        self.assertEqual(struct.unpack("<I", data[4:8])[0], 36 + len(pcm))
        self.assertEqual(data[8:12], b"WAVE")
        self.assertEqual(data[12:16], b"fmt ")
        self.assertEqual(data[36:40], b"data")
        self.assertEqual(struct.unpack("<I", data[40:44])[0], len(pcm))
        self.assertEqual(len(data), 44 + len(pcm))

    def test_stdlib_wave_can_parse(self):
        """標準ライブラリの wave モジュールで開けること。"""
        pcm = struct.pack("<8h", 0, 1000, -1000, 32767, -32768, 5, -5, 0)
        data = wav_bytes(pcm, 22050)
        with wave.open(io.BytesIO(data)) as f:
            self.assertEqual(f.getnchannels(), 1)
            self.assertEqual(f.getsampwidth(), 2)
            self.assertEqual(f.getframerate(), 22050)
            self.assertEqual(f.getnframes(), 8)
            self.assertEqual(f.readframes(8), pcm)

    def test_empty_pcm(self):
        data = wav_bytes(b"", 44100)
        self.assertEqual(len(data), 44)


if __name__ == "__main__":
    unittest.main()
