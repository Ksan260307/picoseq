"""統合テスト — 作曲 → 保存 → 復元 → 合成 → WAV の全経路。"""

import io
import json
import unittest
import wave
import zlib

from picoseq.core import actions
from picoseq.core.note import pack_note
from picoseq.core.phrase import count_notes
from picoseq.core.project import new_project
from picoseq.core.renderer import render_song
from picoseq.core.serialize import dumps, loads
from picoseq.core.wavio import wav_bytes

GOLDEN_SONG_CRC = 3976110364


def _build_song_project():
    p = new_project()
    p = actions.set_seed(p, 42)
    p = actions.generate_phrase(p)
    p = actions.save_pattern(p, 0)
    p = actions.toggle_song_cell(p, 0, 0, 0)
    p = actions.toggle_song_cell(p, 0, 1, 0)
    return p


class TestFullPipeline(unittest.TestCase):
    def test_compose_save_load_render_wav(self):
        p = _build_song_project()

        # 保存して復元しても同一
        restored = loads(dumps(p))
        self.assertEqual(restored, p)

        # 合成結果は既知の値 (再現性 + 回帰)
        pcm = render_song(restored)
        self.assertEqual(zlib.crc32(pcm), GOLDEN_SONG_CRC)

        # WAV として標準ライブラリで読める
        data = wav_bytes(pcm)
        with wave.open(io.BytesIO(data)) as f:
            self.assertEqual(f.getframerate(), 44100)
            self.assertEqual(f.getnframes(), len(pcm) // 2)

    def test_pipeline_is_reproducible(self):
        """全経路を 2 回実行してビット等価 (再現性テスト)。"""
        first = wav_bytes(render_song(_build_song_project()))
        second = wav_bytes(render_song(_build_song_project()))
        self.assertEqual(first, second)

    def test_legacy_save_renders(self):
        """旧版のセーブデータを移行してそのまま鳴らせる。"""
        buffer = [0] * 1024
        buffer[0] = pack_note(60, 0, 0, 4)
        buffer[1] = pack_note(48, 0, 1, 8)
        legacy = {
            "beats": 4,
            "currentBuffer": buffer,
            "favorites": [buffer] + [[0] * 1024] * 7,
            "isUsed": [True] + [False] * 7,
            "songGrid": [0, 0] + [255] * 62,
            "partSettings": {"0": {"tone": 0.5, "length": 0.8}},
        }
        p = loads(json.dumps(legacy))
        self.assertEqual(count_notes(p.phrase), 2)
        pcm = render_song(p)
        self.assertNotEqual(pcm, b"\x00" * len(pcm))

    def test_photo_to_song_pipeline(self):
        """写真 (合成・四角形 2 個) → 音階抽出 → 自動作成 → 保存往復。"""
        from picoseq.vision.harmony import photo_scale_from_quads
        from picoseq.vision.quad import detect_quads
        from tests._vision_util import draw_quad_grid

        grid = draw_quad_grid(160, 120, [(15, 20), (70, 20), (70, 90), (15, 90)])
        for y in range(30, 81):
            for x in range(100, 141):
                grid[y][x] = 230  # 2 つ目の四角形
        quads = detect_quads(grid)
        self.assertEqual(len(quads), 2)
        photo = photo_scale_from_quads(quads)

        p = actions.set_custom_scale(new_project(), photo.key, photo.intervals,
                                     photo.bpm, photo.seed)
        p = actions.generate_phrase(p)

        self.assertGreater(count_notes(p.phrase), 0)
        self.assertEqual(p.scale, "photo")
        restored = loads(dumps(p))
        self.assertEqual(restored, p)
        self.assertEqual(restored.custom_scale, p.custom_scale)

        # 同じ写真からは同じ曲 (取り込んだ値が記録されるため再現できる)
        p2 = actions.generate_phrase(p)
        self.assertEqual(p.phrase, p2.phrase)

        # メロディはフォト音階の音だけを使う
        from picoseq.core.music import in_scale
        from picoseq.core.phrase import active_notes
        for _, note in active_notes(p.phrase):
            if note.wave == 0:
                self.assertTrue(in_scale(note.pitch, p.key, "photo", p.custom_scale))

    def test_undo_snapshot_roundtrip(self):
        """スナップショット (直列化) 経由の復元が編集で使える形で往復する。"""
        p = _build_song_project()
        snapshot = dumps(p)
        p2, _ = actions.place_note(p, 70, 3, 0)
        self.assertNotEqual(p2, p)
        self.assertEqual(loads(snapshot), p)


if __name__ == "__main__":
    unittest.main()
