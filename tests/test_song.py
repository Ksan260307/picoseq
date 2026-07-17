"""ソンググリッド操作のテスト。"""

import unittest

from picoseq.core.constants import EMPTY_CELL, SONG_BLOCKS, SONG_TRACKS
from picoseq.core.song import (
    EMPTY_SONG,
    cell_index,
    clear_pattern_refs,
    get_cell,
    set_cell,
    toggle_cell,
    used_blocks,
)


class TestCells(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(len(EMPTY_SONG), SONG_TRACKS * SONG_BLOCKS)
        self.assertTrue(all(v == EMPTY_CELL for v in EMPTY_SONG))

    def test_set_and_get(self):
        song = set_cell(EMPTY_SONG, 1, 2, 5)
        self.assertEqual(get_cell(song, 1, 2), 5)
        self.assertEqual(get_cell(song, 0, 0), EMPTY_CELL)
        self.assertEqual(get_cell(EMPTY_SONG, 1, 2), EMPTY_CELL)  # 元は不変

    def test_bounds(self):
        for track, block in [(-1, 0), (SONG_TRACKS, 0), (0, -1), (0, SONG_BLOCKS)]:
            with self.subTest(track=track, block=block):
                with self.assertRaises(ValueError):
                    cell_index(track, block)

    def test_toggle_places_and_removes(self):
        song = toggle_cell(EMPTY_SONG, 0, 0, 3)
        self.assertEqual(get_cell(song, 0, 0), 3)
        song = toggle_cell(song, 0, 0, 3)
        self.assertEqual(get_cell(song, 0, 0), EMPTY_CELL)

    def test_toggle_replaces_other_pattern(self):
        song = toggle_cell(EMPTY_SONG, 0, 0, 3)
        song = toggle_cell(song, 0, 0, 5)
        self.assertEqual(get_cell(song, 0, 0), 5)


class TestPatternRefs(unittest.TestCase):
    def test_clear_refs_only_matching(self):
        song = set_cell(EMPTY_SONG, 0, 0, 2)
        song = set_cell(song, 1, 3, 2)
        song = set_cell(song, 2, 5, 4)
        song = clear_pattern_refs(song, 2)
        self.assertEqual(get_cell(song, 0, 0), EMPTY_CELL)
        self.assertEqual(get_cell(song, 1, 3), EMPTY_CELL)
        self.assertEqual(get_cell(song, 2, 5), 4)


class TestUsedBlocks(unittest.TestCase):
    def test_empty_is_zero(self):
        self.assertEqual(used_blocks(EMPTY_SONG), 0)

    def test_rightmost_block_counts(self):
        song = set_cell(EMPTY_SONG, 0, 5, 1)
        self.assertEqual(used_blocks(song), 6)

    def test_max_over_tracks(self):
        song = set_cell(EMPTY_SONG, 0, 2, 1)
        song = set_cell(song, 3, 9, 1)
        self.assertEqual(used_blocks(song), 10)

    def test_last_block(self):
        song = set_cell(EMPTY_SONG, 2, SONG_BLOCKS - 1, 0)
        self.assertEqual(used_blocks(song), SONG_BLOCKS)


if __name__ == "__main__":
    unittest.main()
