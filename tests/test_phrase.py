"""フレーズバッファ操作のテスト。"""

import unittest

from picoseq.core.constants import MAX_NOTES
from picoseq.core.note import Note, unpack_note
from picoseq.core.phrase import (
    EMPTY_PHRASE,
    active_notes,
    add_note,
    build_phrase,
    count_notes,
    find_note_at,
    notes_at_step,
    remove_note,
    resize_note,
)


class TestAddRemove(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(len(EMPTY_PHRASE), MAX_NOTES)
        self.assertEqual(count_notes(EMPTY_PHRASE), 0)

    def test_add_fills_first_slot(self):
        buffer, slot = add_note(EMPTY_PHRASE, 60, 0, 0)
        self.assertEqual(slot, 0)
        self.assertEqual(unpack_note(buffer[0]), Note(60, 0, 0, 1))
        self.assertEqual(count_notes(buffer), 1)

    def test_add_second_note(self):
        buffer, _ = add_note(EMPTY_PHRASE, 60, 0, 0)
        buffer, slot = add_note(buffer, 62, 4, 1, dur=2)
        self.assertEqual(slot, 1)
        self.assertEqual(unpack_note(buffer[1]), Note(62, 4, 1, 2))

    def test_add_reuses_freed_slot(self):
        buffer, a = add_note(EMPTY_PHRASE, 60, 0, 0)
        buffer, _ = add_note(buffer, 62, 1, 0)
        buffer = remove_note(buffer, a)
        buffer, slot = add_note(buffer, 64, 2, 0)
        self.assertEqual(slot, a)

    def test_add_when_full(self):
        full = build_phrase([Note(60, 0, 0, 1)] * MAX_NOTES)
        buffer, slot = add_note(full, 62, 1, 0)
        self.assertEqual(slot, -1)
        self.assertIs(buffer, full)

    def test_original_unchanged(self):
        buffer, _ = add_note(EMPTY_PHRASE, 60, 0, 0)
        self.assertEqual(count_notes(EMPTY_PHRASE), 0)
        self.assertEqual(count_notes(buffer), 1)


class TestFind(unittest.TestCase):
    def setUp(self):
        self.buffer, self.slot = add_note(EMPTY_PHRASE, 60, 4, 0, dur=3)

    def test_find_at_start(self):
        self.assertEqual(find_note_at(self.buffer, 60, 4, 0), self.slot)

    def test_find_within_duration(self):
        self.assertEqual(find_note_at(self.buffer, 60, 5, 0), self.slot)
        self.assertEqual(find_note_at(self.buffer, 60, 6, 0), self.slot)

    def test_find_outside_duration(self):
        self.assertEqual(find_note_at(self.buffer, 60, 7, 0), -1)
        self.assertEqual(find_note_at(self.buffer, 60, 3, 0), -1)

    def test_find_wrong_pitch(self):
        self.assertEqual(find_note_at(self.buffer, 61, 4, 0), -1)

    def test_find_wrong_part(self):
        """別パートの音符は選択できない (パートごとの編集)。"""
        self.assertEqual(find_note_at(self.buffer, 60, 4, 1), -1)


class TestResize(unittest.TestCase):
    def test_resize(self):
        buffer, slot = add_note(EMPTY_PHRASE, 60, 0, 0)
        buffer = resize_note(buffer, slot, 4)
        self.assertEqual(unpack_note(buffer[slot]).dur, 4)

    def test_resize_clamps(self):
        buffer, slot = add_note(EMPTY_PHRASE, 60, 0, 0)
        self.assertEqual(unpack_note(resize_note(buffer, slot, 0)[slot]).dur, 1)
        self.assertEqual(unpack_note(resize_note(buffer, slot, 999)[slot]).dur, 255)


class TestQueries(unittest.TestCase):
    def test_notes_at_step(self):
        buffer, _ = add_note(EMPTY_PHRASE, 60, 4, 0, dur=3)
        buffer, _ = add_note(buffer, 48, 4, 1)
        buffer, _ = add_note(buffer, 50, 5, 1)
        notes = notes_at_step(buffer, 4)
        self.assertEqual(len(notes), 2)
        # 継続中でも開始ステップでなければ返さない
        self.assertEqual(len(notes_at_step(buffer, 6)), 0)

    def test_active_notes(self):
        buffer, a = add_note(EMPTY_PHRASE, 60, 0, 0)
        buffer, b = add_note(buffer, 62, 1, 1, dur=2)
        result = active_notes(buffer)
        self.assertEqual(result, [(a, Note(60, 0, 0, 1)), (b, Note(62, 1, 1, 2))])


class TestBuild(unittest.TestCase):
    def test_build_orders_from_head(self):
        buffer = build_phrase([Note(60, 0, 0, 1), Note(62, 1, 1, 2)])
        self.assertEqual(unpack_note(buffer[0]), Note(60, 0, 0, 1))
        self.assertEqual(unpack_note(buffer[1]), Note(62, 1, 1, 2))
        self.assertEqual(count_notes(buffer), 2)

    def test_build_truncates_overflow(self):
        buffer = build_phrase([Note(60, 0, 0, 1)] * (MAX_NOTES + 10))
        self.assertEqual(count_notes(buffer), MAX_NOTES)
        self.assertEqual(len(buffer), MAX_NOTES)


if __name__ == "__main__":
    unittest.main()
