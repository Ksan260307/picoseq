"""再生の制御と保存・書き出しのテスト (app から切り出した 2 つの層)。

音は鳴らせない (silent) が、「何を鳴らそうとしたか」「何を書き出したか」は
確かめられる。selftest は通しで 1 回しか触らないので、
空のときの断り方や、書き出しの中身をここで押さえる。
"""

import unittest
import wave
from pathlib import Path
from tempfile import TemporaryDirectory

from tests._ui_util import close_app, make_app, pump, tk_available


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestTransport(unittest.TestCase):
    """再生できるか / できないかの判定と、ループ長の計算。"""

    def setUp(self):
        self.app, self.root = make_app()

    def tearDown(self):
        close_app(self.app, self.root)

    def test_empty_phrase_is_not_playable(self):
        self.app.clear_phrase()
        self.assertFalse(self.app._playable("phrase"))
        self.assertTrue(self.app.status_var.get())      # 理由が出る

    def test_generated_phrase_is_playable(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        self.assertTrue(self.app._playable("phrase"))

    def test_empty_song_is_not_playable(self):
        self.assertFalse(self.app._playable("song"))

    def test_loop_ticks_match_the_mode(self):
        from picoseq.core.schedule import phrase_ticks, song_ticks
        p = self.app.project
        self.assertEqual(self.app._loop_ticks("phrase", p), phrase_ticks(p))
        self.assertEqual(self.app._loop_ticks("song", p), song_ticks(p))

    def test_loop_pcm_length_is_exact(self):
        """ループ用の PCM は尻尾を付けない (継ぎ目が空かないように)。"""
        from picoseq.core import actions
        from picoseq.core.schedule import phrase_ticks, samples_per_tick
        self.app.commit(actions.generate_phrase(self.app.project))
        p = self.app.project
        pcm = self.app._render_loop_pcm("phrase", p)
        self.assertEqual(len(pcm), phrase_ticks(p) * samples_per_tick(p.bpm) * 2)

    def test_mute_is_reflected_in_the_loop(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        full = self.app._render_loop_pcm("phrase", self.app.project)
        for wave in range(4):
            self.app.toggle_mute(wave)
        silent = self.app._render_loop_pcm("phrase", self.app.project)
        self.assertNotEqual(full, silent)
        self.assertEqual(silent, b"\x00" * len(silent))

    def test_stop_clears_the_playhead(self):
        self.app.stop_playback()
        self.assertIsNone(self.app.play_mode)
        self.assertEqual(self.app.position_var.get(), "")

    def test_still_playable_notices_an_emptied_phrase(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        self.assertTrue(self.app._still_playable("phrase"))
        self.app.commit(actions.clear_phrase(self.app.project))
        self.assertFalse(self.app._still_playable("phrase"))

    def test_run_bg_delivers_the_result(self):
        """裏スレッドの結果が UI スレッドへ渡る。"""
        box = {}
        self.app._run_bg(lambda: 6 * 7, lambda value: box.setdefault("v", value))
        pump(self.root, lambda: "v" in box)
        self.assertEqual(box.get("v"), 42)

    def test_run_bg_reports_errors(self):
        def boom():
            raise ValueError("わざと失敗")

        self.app._run_bg(boom, lambda value: None)
        pump(self.root, lambda: "わざと失敗" in self.app.status_var.get())
        self.assertIn("わざと失敗", self.app.status_var.get())


@unittest.skipUnless(tk_available(), "tkinter が使えない環境")
class TestFileIO(unittest.TestCase):
    """保存・読込と、WAV / MIDI 書き出し。"""

    def setUp(self):
        self.app, self.root = make_app()
        self.tmp = TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.app.autosave_file = self.dir / "project.json"

    def tearDown(self):
        close_app(self.app, self.root)
        self.tmp.cleanup()

    def test_save_then_load_roundtrip(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(
            actions.set_seed(self.app.project, 42)))
        before = self.app.project
        self.app.do_save()
        self.assertTrue(self.app.autosave_file.exists())
        self.app.clear_phrase()
        self.app.do_load()
        self.assertEqual(self.app.project, before)

    def test_save_clears_the_unsaved_mark(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        self.assertTrue(self.app._dirty)
        self.app.do_save()
        self.assertFalse(self.app._dirty)

    def test_load_without_a_file_is_reported(self):
        self.app.do_load()
        self.assertTrue(self.app.status_var.get())

    def test_broken_file_is_refused(self):
        self.app.autosave_file.write_text("これは JSON ではない", encoding="utf-8")
        before = self.app.project
        self.app.do_load()
        self.assertEqual(self.app.project, before)     # 壊れたデータで上書きしない

    def test_export_needs_something_to_export(self):
        self.app.clear_phrase()
        self.assertFalse(self.app._export_ready("phrase"))
        self.assertFalse(self.app._export_ready("song"))

    def test_wav_export_writes_a_readable_file(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        path = self.dir / "out.wav"
        self.app._ask_save_path = lambda *a, **k: str(path)
        self.app.do_export_wav("phrase")
        self.assertTrue(pump(self.root, path.exists), "WAV が書き出されない")
        with wave.open(str(path)) as f:
            self.assertEqual(f.getframerate(), 44100)
            self.assertGreater(f.getnframes(), 0)

    def test_midi_export_writes_a_smf(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        path = self.dir / "out.mid"
        self.app._ask_save_path = lambda *a, **k: str(path)
        self.app.do_export_midi("phrase")
        self.assertEqual(path.read_bytes()[:4], b"MThd")

    def test_cancelling_the_dialog_writes_nothing(self):
        from picoseq.core import actions
        self.app.commit(actions.generate_phrase(self.app.project))
        self.app._ask_save_path = lambda *a, **k: None
        self.app.do_export_midi("phrase")
        self.assertEqual(list(self.dir.glob("*.mid")), [])


if __name__ == "__main__":
    unittest.main()
