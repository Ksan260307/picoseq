"""アンドゥ / リドゥ履歴のテスト。"""

import unittest

from picoseq.core.history import History, can_redo, can_undo, record, redo, undo


class TestHistory(unittest.TestCase):
    def test_empty(self):
        h = History()
        self.assertFalse(can_undo(h))
        self.assertFalse(can_redo(h))
        self.assertIsNone(undo(h, "now"))
        self.assertIsNone(redo(h, "now"))

    def test_undo_redo_cycle(self):
        h = History()
        h = record(h, "v1")           # v1 → v2 と編集した
        h, snapshot = undo(h, "v2")   # v2 から戻る
        self.assertEqual(snapshot, "v1")
        self.assertTrue(can_redo(h))
        h, snapshot = redo(h, "v1")
        self.assertEqual(snapshot, "v2")
        self.assertTrue(can_undo(h))
        self.assertFalse(can_redo(h))

    def test_new_edit_clears_future(self):
        h = record(History(), "v1")
        h, _ = undo(h, "v2")
        h = record(h, "v1b")  # 戻った状態から別の編集
        self.assertFalse(can_redo(h))

    def test_multiple_undo(self):
        h = History()
        for v in ("v1", "v2", "v3"):
            h = record(h, v)
        h, s = undo(h, "v4")
        self.assertEqual(s, "v3")
        h, s = undo(h, "v3")
        self.assertEqual(s, "v2")
        h, s = undo(h, "v2")
        self.assertEqual(s, "v1")
        self.assertIsNone(undo(h, "v1"))

    def test_limit_keeps_recent(self):
        h = History(limit=3)
        for i in range(10):
            h = record(h, f"v{i}")
        self.assertEqual(len(h.past), 3)
        self.assertEqual(h.past, ("v7", "v8", "v9"))


if __name__ == "__main__":
    unittest.main()
