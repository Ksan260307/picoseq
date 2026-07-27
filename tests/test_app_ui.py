"""機能単位の UI テスト — アプリを実際に組み立ててコントローラ経路を個別に検証する。

これまで UI は巨大な `--selftest` 1 本に頼っていた。ここでは Tk を silent で建て、
機能ごとに独立したテストにすることで「どの操作が壊れたか」を切り分けやすくする。

Tk が使えない環境ではモジュールごとスキップする (CI の windows では動く)。
"""

import unittest

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.withdraw()
    _root.destroy()
    _TK_OK = True
except Exception:       # noqa: BLE001 - ディスプレイが無い等
    _TK_OK = False

if _TK_OK:
    from picoseq.core import actions
    from picoseq.core import dj as dj_core
    from picoseq.core.constants import (
        PART_COUNT, PITCH_MAX, PITCH_MIN, WAVE_PULSE, WAVE_SAW,
    )
    from picoseq.core.phrase import active_notes, count_notes
    from picoseq.core.project import layer_count, new_project
    from picoseq.ui.app import PicoSeqApp


@unittest.skipUnless(_TK_OK, "Tk が使えない環境")
class AppUITest(unittest.TestCase):
    """各テストで silent なアプリを新規に建て、状態が漏れないようにする。"""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = PicoSeqApp(self.root, silent=True)

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:   # noqa: BLE001
            pass

    def notes(self):
        return list(active_notes(self.app.project.phrase))

    # ---- タブ ----

    def test_tabs_switch(self):
        for tab in ("phrase", "pattern", "song", "dj", "phrase"):
            self.app.switch_tab(tab)
            self.assertEqual(self.app.tab, tab)

    # ---- パート音作り ----

    def test_part_tone_gate_volume_setters(self):
        self.app.switch_tab("phrase")
        self.app.select_part(2)
        self.app._on_tone_change("70")
        self.app._on_gate_change("40")
        self.app._on_volume_change("55")
        p = self.app.project.parts[2][0]
        self.assertEqual((p.tone, p.gate, p.volume), (70, 40, 55))

    def test_volume_zero_silences_part(self):
        self.app.generate_auto()
        from picoseq.core.renderer import clear_cache, render_phrase
        clear_cache()
        base = render_phrase(self.app.project)
        clear_cache()
        quiet = render_phrase(actions.set_part_volume(self.app.project, WAVE_SAW, 0))
        self.assertNotEqual(base, quiet)

    def test_part_selection_syncs_sliders(self):
        self.app.select_part(0)
        self.app._on_volume_change("30")
        self.app.select_part(1)
        # パート 1 は既定 100 のまま (パート 0 の 30 に引きずられない)
        self.assertEqual(self.app.project.parts[1][0].volume, 100)

    # ---- レイヤー ----

    def test_add_and_remove_layer(self):
        self.app.select_part(0)
        before = layer_count(self.app.project, 0)
        self.app.add_layer_action()
        self.assertEqual(layer_count(self.app.project, 0), before + 1)

    # ---- 編集ツール ----

    def test_generate_auto_makes_notes(self):
        self.app.generate_auto()
        self.assertGreater(count_notes(self.app.project.phrase), 0)

    def test_transpose_shifts_and_stays_in_range(self):
        # 中音域が出る固定シードで (乱数だと高音域だけになり ±1oct で音域外に出る)
        self.app.project = actions.generate_phrase(
            actions.set_scale(actions.set_seed(new_project(), 42), "major"))
        before = [n.pitch for _, n in self.notes() if n.wave == WAVE_PULSE]
        self.app.transpose_up()
        after = [n.pitch for _, n in self.notes() if n.wave == WAVE_PULSE]
        self.assertNotEqual(after, before)
        self.assertTrue(after)
        for _, n in self.notes():
            self.assertTrue(PITCH_MIN <= n.pitch <= PITCH_MAX)

    def test_reverse_twice_restores(self):
        self.app.generate_auto()
        before = dumps_phrase(self.app)
        self.app.reverse_phrase_action()
        self.app.reverse_phrase_action()
        self.assertEqual(dumps_phrase(self.app), before)

    def test_clear_part_removes_only_that_part(self):
        self.app.generate_auto()
        self.app.clear_part_action(2)
        waves = {n.wave for _, n in self.notes()}
        self.assertNotIn(2, waves)

    def test_undo_redo(self):
        self.app.generate_auto()
        first = dumps_phrase(self.app)
        self.app.generate_auto()
        self.assertNotEqual(dumps_phrase(self.app), first)
        self.app.undo_action()
        self.assertEqual(dumps_phrase(self.app), first)
        self.app.redo_action()
        self.assertNotEqual(dumps_phrase(self.app), first)

    # ---- パターン / ソング ----

    def test_pattern_save_and_song_toggle(self):
        self.app.generate_auto()
        self.app.save_current_pattern()
        used = [i for i, p in enumerate(self.app.project.patterns) if p.used]
        self.assertTrue(used)
        self.app.switch_tab("song")
        self.app.select_pattern(used[0])
        self.app.song_click(0, 0)
        self.assertNotEqual(self.app.project.song[0], 255)

    # ---- 音色・言語 ----

    def test_sound_change_syncs_theme(self):
        self.app.sound_box.current(1)   # warm16
        self.app._on_sound_change()
        self.assertEqual(self.app.project.sound, self.app.theme_sound)

    def test_language_switch_rebuilds(self):
        import picoseq.ui.i18n as i18n
        self.app.lang_box.current(1)    # en
        self.app._on_lang_change()
        self.assertEqual(i18n.get_lang(), "en")
        self.app.lang_box.current(0)
        self.app._on_lang_change()

    # ---- DJ モード ----

    def test_dj_per_deck_independent(self):
        self.app.switch_tab("dj")
        self.app.dj_set_tempo(1, 200)
        self.app.dj_set_noise(1, 4)
        self.app.dj_set_part_volume(1, WAVE_PULSE, 40)
        self.assertEqual(self.app.dj_decks[1]["bpm"], 200)
        self.assertNotEqual(self.app.dj_decks[0]["bpm"], 200)
        self.assertEqual(self.app.dj_decks[1]["volumes"][WAVE_PULSE], 40)
        self.assertEqual(self.app.dj_decks[0]["volumes"][WAVE_PULSE], 100)

    def test_dj_crossfade_switches_active(self):
        self.app.switch_tab("dj")
        self.app.dj_set_crossfade(80)
        self.assertEqual(self.app.dj_active, 1)
        self.app.dj_set_crossfade(10)
        self.assertEqual(self.app.dj_active, 0)

    def test_dj_roll_records_history(self):
        self.app.switch_tab("dj")
        self.app.dj_history = []
        self.app.dj_roll(0)
        self.assertEqual(len(self.app.dj_history), 1)

    def test_dj_recall_restores_and_holds(self):
        self.app.switch_tab("dj")
        entry = dj_core.make_entry("battle", 7, 96, "retro8", 1, 4242,
                                   volumes=(60, 70, 80, 90))
        self.app.dj_recall(entry, 1)
        self.assertEqual(self.app.dj_decks[1]["scale"], "battle")
        self.assertEqual(self.app.dj_decks[1]["volumes"], [60, 70, 80, 90])
        self.assertTrue(self.app.dj_decks[1]["hold"])

    def test_dj_keep_saves_pattern_without_changing_board(self):
        self.app.switch_tab("dj")
        self.app.dj_roll(0)
        board = self.app.project.phrase
        slot = self.app.dj_keep()
        self.assertGreaterEqual(slot, 0)
        self.assertTrue(self.app.project.patterns[slot].used)
        self.assertEqual(self.app.project.phrase, board)

    def test_dj_favorite_toggle_persists_in_state(self):
        self.app.switch_tab("dj")
        saved = list(self.app.dj_favorites)
        try:
            self.app.dj_favorites = []
            entry = self.app._dj_entry()
            self.assertTrue(self.app.dj_toggle_favorite(entry))
            self.assertTrue(dj_core.is_favorite(self.app.dj_favorites, entry))
        finally:
            import picoseq.ui.storage as storage
            self.app.dj_favorites = saved
            s = storage.load_settings()
            s["dj_favorites"] = saved
            storage.save_settings(s)

    def test_dj_kill_mutes_part(self):
        self.app.switch_tab("dj")
        self.app.dj_kill(0, 2)
        self.assertIn(2, self.app.dj_decks[0]["muted"])
        self.app.dj_kill(0, 2)
        self.assertNotIn(2, self.app.dj_decks[0]["muted"])

    # ---- サプライズ ----

    def test_surprise_randomizes_within_range(self):
        self.app.generate_surprise()
        self.assertGreater(count_notes(self.app.project.phrase), 0)
        for wave in range(PART_COUNT):
            for lyr in self.app.project.parts[wave]:
                self.assertTrue(0 <= lyr.tone <= 100)
                self.assertTrue(25 <= lyr.gate <= 100)


def dumps_phrase(app):
    from picoseq.core.serialize import dumps
    return dumps(app.project)


if __name__ == "__main__":
    unittest.main()
