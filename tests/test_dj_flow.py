"""DJ の連続フロー (自動進行 / ループ固定 / 呼び戻し) の回帰テスト。

これらは「事前レンダリングした次フレーズ」と「今流しているフレーズ」を
取り違えると壊れる。実際に壊れた履歴があるので、シード選択のロジックを
音声デバイス無しで直接検証する。

背景 (回帰の内容):
`_dj_want_seed` は _dj_prepare_auto が**次フレーズ用のランダム値**へ書き換える。
そのため `_dj_queue(seed=None)` が「今のシード」へ戻し忘れると、
つまみを触るだけで未来のフレーズへ飛び、ループ固定も呼び戻しも効かなくなる。
"""

import unittest

from picoseq.ui.tuning import DJ_ADVANCE_LOOPS


class _FakeDeckApp:
    """_dj_queue / _dj_should_swap だけを取り出して試すための最小の器。

    Tk も音声デバイスも使わない (CI でもどこでも走る)。
    """

    def __init__(self, current_seed=1000):
        from picoseq.ui.dj_control import DJMixin
        self.dj_decks = [{"seed": current_seed, "hold": False}]
        self.dj_active = 0
        self._dj_want_seed = current_seed
        self._dj_pending = "OLD"
        self._dj_apply_now = False
        self.scheduled = 0
        # mixin のメソッドを束縛して使う
        self._queue = DJMixin._dj_queue.__get__(self)
        self._deck = DJMixin._dj_deck.__get__(self)

    # _dj_queue が呼ぶもの
    def _dj_deck(self, deck=None):
        return self.dj_decks[self.dj_active if deck is None else deck]

    def _dj_schedule_render(self):
        self.scheduled += 1


class TestQueueSeedSelection(unittest.TestCase):
    """つまみ操作 (seed 未指定) は必ず「今流しているシード」を作り直す。"""

    def test_knob_change_keeps_current_seed(self):
        app = _FakeDeckApp(current_seed=1000)
        # 事前レンダリングが次フレーズ用の乱数を書き込んだ状態を再現
        app._dj_want_seed = 987654
        app._queue(seed=None, immediate=True)
        self.assertEqual(app._dj_want_seed, 1000,
                         "つまみ操作で未来のフレーズへ飛んでいる (回帰)")

    def test_explicit_seed_is_honored(self):
        app = _FakeDeckApp(current_seed=1000)
        app._queue(seed=555, immediate=True)
        self.assertEqual(app._dj_want_seed, 555)

    def test_recall_style_change_uses_deck_seed(self):
        """呼び戻しはデッキへシードを入れてから seed 未指定で queue する。"""
        app = _FakeDeckApp(current_seed=1000)
        app._dj_want_seed = 987654            # 事前レンダリングの残骸
        app.dj_decks[0]["seed"] = 4242        # 呼び戻したシード
        app._queue(seed=None, immediate=True)
        self.assertEqual(app._dj_want_seed, 4242,
                         "呼び戻したフレーズではなく別のフレーズが鳴る (回帰)")

    def test_queue_discards_stale_pending_and_schedules(self):
        app = _FakeDeckApp()
        app._queue(seed=None, immediate=True)
        self.assertIsNone(app._dj_pending)     # 古い準備は捨てる
        self.assertTrue(app._dj_apply_now)
        self.assertEqual(app.scheduled, 1)

    def test_queue_non_immediate_keeps_flag_false(self):
        app = _FakeDeckApp()
        app._queue(seed=7, immediate=False)
        self.assertFalse(app._dj_apply_now)


class TestAdvanceDecision(unittest.TestCase):
    """自動進行の判定 — ループ固定が確実に効き、固定を外すと再開する。"""

    def setUp(self):
        from picoseq.ui.dj_control import DJMixin
        self.swap = DJMixin._dj_should_swap

    def test_advances_after_configured_loops(self):
        n = DJ_ADVANCE_LOOPS
        self.assertFalse(self.swap(n - 1, False, True, False, n))
        self.assertTrue(self.swap(n, False, True, False, n))

    def test_hold_blocks_advance_forever(self):
        n = DJ_ADVANCE_LOOPS
        for count in range(n, n * 10):
            self.assertFalse(self.swap(count, True, True, False, n),
                             "ループ固定中に進んでしまった")

    def test_unhold_resumes_advance(self):
        n = DJ_ADVANCE_LOOPS
        self.assertFalse(self.swap(n + 3, True, True, False, n))
        self.assertTrue(self.swap(n + 3, False, True, False, n))

    def test_no_pending_never_advances(self):
        """準備できていないのに進めると無音が入る。"""
        self.assertFalse(self.swap(99, False, False, False, DJ_ADVANCE_LOOPS))

    def test_manual_swap_overrides_hold(self):
        self.assertTrue(self.swap(1, True, True, True, DJ_ADVANCE_LOOPS))


class TestNextText(unittest.TestCase):
    """案内表示 — 固定中はそれが分かり、進行中は残り小節が減っていく。"""

    def _app(self, hold=False, loop_count=0):
        from picoseq.ui.dj_control import DJMixin

        class A:
            pass
        a = A()
        a.dj_decks = [{"hold": hold}]
        a.dj_active = 0
        a._dj_loop_count = loop_count
        a._dj_deck = DJMixin._dj_deck.__get__(a)
        a._dj_next_text = DJMixin._dj_next_text.__get__(a)
        return a

    def test_blank_when_stopped(self):
        self.assertEqual(self._app()._dj_next_text(False), "")

    def test_shows_hold(self):
        text = self._app(hold=True)._dj_next_text(True)
        self.assertTrue(text)
        self.assertNotIn("0", text)      # 小節数ではなく固定の案内

    def test_countdown_decreases(self):
        first = self._app(loop_count=0)._dj_next_text(True)
        later = self._app(loop_count=DJ_ADVANCE_LOOPS - 1)._dj_next_text(True)
        self.assertNotEqual(first, later)

    def test_never_negative(self):
        text = self._app(loop_count=DJ_ADVANCE_LOOPS * 5)._dj_next_text(True)
        self.assertNotIn("-", text)


if __name__ == "__main__":
    unittest.main()
