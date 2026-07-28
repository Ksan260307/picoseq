"""画面の組み立てとヘルプのテスト。

ウィジェットが揃っているか、キー割り当てが効くか、ヘルプの文言が
日英そろっているかを見る。組み立ては app.py から builder.py へ切り出したので、
その入口 (_build_ui) が全区画を作ることをここで担保する。
"""

import unittest

from tests._ui_util import close_app, make_app, tk_available


class TestMixinComposition(unittest.TestCase):
    """アプリは用途ごとのミックスインを合成して出来ている (Tk 不要)。

    どれか 1 つを継承から落とすと、そのタブの操作がまるごと消える。
    落ちたことに気づけるよう、構成そのものを固定しておく。
    """

    def test_app_composes_every_mixin(self):
        from picoseq.ui.app import PicoSeqApp
        from picoseq.ui.builder import UIBuilderMixin
        from picoseq.ui.dj_control import DJMixin
        from picoseq.ui.fileio import FileIOMixin
        from picoseq.ui.patterns import PatternsMixin
        from picoseq.ui.selftest import SelfTestMixin
        from picoseq.ui.transport import TransportMixin
        for mixin in (UIBuilderMixin, TransportMixin, PatternsMixin,
                      FileIOMixin, DJMixin, SelfTestMixin):
            with self.subTest(mixin=mixin.__name__):
                self.assertTrue(issubclass(PicoSeqApp, mixin))

    def test_each_mixin_owns_its_entry_points(self):
        """代表的なメソッドが、期待したミックスイン側にあること。"""
        from picoseq.ui.builder import UIBuilderMixin
        from picoseq.ui.fileio import FileIOMixin
        from picoseq.ui.patterns import PatternsMixin
        from picoseq.ui.transport import TransportMixin
        cases = (
            (UIBuilderMixin, "_build_ui"),
            (TransportMixin, "toggle_play"),
            (PatternsMixin, "save_current_pattern"),
            (FileIOMixin, "do_export_wav"),
        )
        for mixin, name in cases:
            with self.subTest(mixin=mixin.__name__, name=name):
                self.assertIn(name, vars(mixin))


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestBuild(unittest.TestCase):
    """組み立ての結果 — 必要なウィジェットが揃っているか。"""

    @classmethod
    def setUpClass(cls):
        cls.app, cls.root = make_app()

    @classmethod
    def tearDownClass(cls):
        close_app(cls.app, cls.root)

    def test_all_tabs_are_built(self):
        for name in ("phrase_frame", "song_frame", "pattern_frame", "dj_frame"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(self.app, name))
                self.assertTrue(getattr(self.app, name).winfo_exists())

    def test_header_widgets_exist(self):
        for name in ("sound_box", "bpm_scale", "lang_box", "position_var"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(self.app, name))

    def test_phrase_controls_exist(self):
        for name in ("beats_box", "key_box", "scale_box", "seed_spin",
                     "tone_scale", "gate_scale", "volume_scale"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(self.app, name))

    def test_one_button_per_part(self):
        from picoseq.core.constants import PART_COUNT
        self.assertEqual(len(self.app.part_buttons), PART_COUNT)
        self.assertEqual(len(self.app.mute_buttons), PART_COUNT)

    def test_one_palette_button_per_pattern(self):
        from picoseq.core.constants import PATTERN_COUNT
        self.assertEqual(len(self.app.pattern_buttons), PATTERN_COUNT)

    def test_status_bar_variables_exist(self):
        for name in ("status_var", "count_var", "cell_var", "play_hint_var"):
            with self.subTest(name=name):
                self.assertTrue(hasattr(self.app, name))


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestKeyBindings(unittest.TestCase):
    """キー割り当て — 文字入力中は効かないこと。"""

    def setUp(self):
        self.app, self.root = make_app()

    def tearDown(self):
        close_app(self.app, self.root)

    def _event(self, widget):
        class Event:
            pass
        event = Event()
        event.widget = widget
        return event

    def test_digit_switches_part(self):
        self.app.select_part(0)
        self.app._on_digit(self._event(self.app.roll.canvas), 2)
        self.assertEqual(self.app.part, 2)

    def test_digit_is_ignored_while_typing(self):
        """シード値の入力中に 1〜4 を打ってもパートが飛ばない。"""
        self.app.select_part(0)
        self.app._on_digit(self._event(self.app.seed_spin), 2)
        self.assertEqual(self.app.part, 0)

    def test_typing_detects_entry_widgets(self):
        self.assertTrue(self.app._typing(self._event(self.app.seed_spin)))
        self.assertFalse(self.app._typing(self._event(self.app.roll.canvas)))

    def test_tab_key_cycles_all_tabs(self):
        seen = [self.app.tab]
        for _ in range(len(self.app.TABS)):
            self.app._on_tab_key(None)
            seen.append(self.app.tab)
        self.assertEqual(set(seen), set(self.app.TABS))
        self.assertEqual(seen[0], seen[-1])   # 一周して戻る

    def test_bound_keys_are_registered(self):
        """主要なキーが全体へ割り当てられている (Tk の表記に合わせて緩く見る)。"""
        bound = " ".join(str(b) for b in self.root.bind_all())
        for word in ("space", "Escape", "z", "y", "F1", "Tab", "Up", "Down"):
            with self.subTest(word=word):
                self.assertIn(word, bound)


class TestHelpContent(unittest.TestCase):
    """ヘルプ本文 — 日英で構成がそろっているか (Tk 不要)。"""

    def test_sections_have_the_same_shape(self):
        from picoseq.ui.help import SECTIONS_EN, SECTIONS_JA
        self.assertEqual(len(SECTIONS_JA), len(SECTIONS_EN))

    def test_every_item_has_a_body(self):
        from picoseq.ui.help import SECTIONS_EN, SECTIONS_JA
        for sections in (SECTIONS_JA, SECTIONS_EN):
            for heading, items in sections:
                self.assertTrue(heading.strip())
                self.assertTrue(items, f"{heading} が空")
                for title, body in items:
                    with self.subTest(heading=heading, title=title):
                        self.assertTrue(title.strip())
                        self.assertGreater(len(body), 10)

    def test_shortcut_lists_match(self):
        """項目数と説明の有無がそろっている (キー表記は言語で違ってよい)。"""
        from picoseq.ui.help import SHORTCUTS_EN, SHORTCUTS_JA
        self.assertEqual(len(SHORTCUTS_JA), len(SHORTCUTS_EN))
        for rows in (SHORTCUTS_JA, SHORTCUTS_EN):
            for key, description in rows:
                with self.subTest(key=key):
                    self.assertTrue(key.strip())
                    self.assertTrue(description.strip())

    def test_removed_features_are_not_mentioned(self):
        """消した機能の説明が残っていないこと (鼻歌は削除済み)。"""
        from picoseq.ui.help import SECTIONS_EN, SECTIONS_JA
        text = repr(SECTIONS_JA) + repr(SECTIONS_EN)
        for word in ("鼻歌", "humming", "マイク"):
            with self.subTest(word=word):
                self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
