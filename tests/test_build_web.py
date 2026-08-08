"""ブラウザ版のテスト — 橋渡し API と、配る zip の中身。

ブラウザ (Pyodide) そのものはここでは動かせないが、危ないところはほぼ潰せる:
  ・zip だけを sys.path に置いて import できるか = Pyodide がやることと同じ
  ・bridge の各関数が正しく状態を変えるか (Python なのでそのまま呼べる)
  ・app.js が呼ぶ名前が bridge に実在するか / HTML の id と食い違わないか
残るのは Pyodide の起動と JS の実行だけ。
"""

import ast
import json
import re
import subprocess
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.build_web import (
    BLOCKED,
    ZIP_NAME,
    BrowserUnsafe,
    build,
    build_zip,
    check_browser_safe,
)

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


class BrowserSafetyTest(unittest.TestCase):
    """core がブラウザで動く形かの検査 (ビルドの門番)。"""

    def test_core_is_browser_safe(self):
        used = check_browser_safe()
        self.assertIn("array", used)
        self.assertFalse(set(used) & BLOCKED)

    def test_numpy_is_the_only_external_dependency(self):
        """外部依存は numpy だけ (しかも任意) — なので Pyodide でそのまま動く。"""
        external = [name for name in check_browser_safe()
                    if name not in sys.stdlib_module_names and name != "picoseq"]
        self.assertEqual(external, ["numpy"])

    def test_blocked_import_stops_the_build(self):
        """tkinter などが混じったら気づけること。"""
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "bad.py").write_text("import tkinter\n", encoding="utf-8")
            with self.assertRaises(BrowserUnsafe):
                check_browser_safe(folder)

    def test_blocked_list_covers_the_desktop_only_parts(self):
        for name in ("tkinter", "ctypes", "winsound", "threading"):
            with self.subTest(name=name):
                self.assertIn(name, BLOCKED)


class ZipTest(unittest.TestCase):
    """配る zip の中身と再現性。"""

    def test_contains_core_and_bridge(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ZIP_NAME
            build_zip(path)
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        self.assertIn("bridge.py", names)
        self.assertIn("picoseq/__init__.py", names)
        self.assertIn("picoseq/core/composer.py", names)
        self.assertIn("picoseq/core/renderer.py", names)

    def test_excludes_the_desktop_ui(self):
        """tkinter を掴む ui は入れない (入れると Pyodide で import 失敗)。"""
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ZIP_NAME
            build_zip(path)
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
        self.assertFalse([n for n in names if n.startswith("picoseq/ui/")])
        self.assertFalse([n for n in names if n.startswith("picoseq/vision/")])

    def test_zip_is_reproducible(self):
        """中身が同じなら zip も 1 バイト違わない (CI の成果物が毎回同じ)。"""
        with TemporaryDirectory() as tmp:
            first = Path(tmp) / "a.zip"
            second = Path(tmp) / "b.zip"
            build_zip(first)
            build_zip(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_zip_is_small_enough_to_serve(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / ZIP_NAME
            build_zip(path)
            self.assertLess(path.stat().st_size, 300 * 1024)


class ZipRunsAloneTest(unittest.TestCase):
    """zip を展開しただけで動くか — Pyodide がするのと同じことを別プロセスで試す。"""

    def test_bridge_works_from_the_zip_only(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            build_zip(folder / ZIP_NAME)
            with zipfile.ZipFile(folder / ZIP_NAME) as zf:
                zf.extractall(folder / "unpacked")
            script = (
                "import json, sys\n"
                f"sys.path.insert(0, {str(folder / 'unpacked')!r})\n"
                "import bridge\n"
                "bridge.generate(42)\n"
                "view = json.loads(bridge.snapshot())\n"
                "pcm = bridge.loop_pcm()\n"
                "print(view['count'], len(pcm), view['progression'])\n"
            )
            # リポジトリを見に行かせないため、cwd を展開先にして起動する。
            # 出力に矢印を含むので、子プロセスの文字コードも UTF-8 に固定する。
            import os
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            result = subprocess.run(
                [sys.executable, "-c", script], cwd=folder, env=env,
                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        count, pcm_len, progression = result.stdout.split()
        self.assertGreater(int(count), 0)
        self.assertGreater(int(pcm_len), 0)
        self.assertIn("→", progression)


class BridgeApiTest(unittest.TestCase):
    """橋渡し API — 状態が期待どおり変わるか。"""

    def setUp(self):
        sys.path.insert(0, str(WEB))
        import bridge
        from importlib import reload
        self.bridge = reload(bridge)     # テストごとに状態を戻す

    def tearDown(self):
        sys.path.remove(str(WEB))

    def view(self):
        return json.loads(self.bridge.snapshot())

    def test_catalog_lists_every_choice(self):
        from picoseq.core.music import SCALE_IDS
        catalog = json.loads(self.bridge.catalog())
        self.assertEqual(len(catalog["scales"]), len(SCALE_IDS))
        self.assertEqual(len(catalog["keys"]), 12)
        self.assertEqual(len(catalog["parts"]), 4)
        self.assertEqual(catalog["rate"], self.bridge.WEB_RATE)

    def test_generate_is_reproducible(self):
        self.bridge.generate(42)
        first = self.view()["notes"]
        self.bridge.generate(7)
        self.bridge.generate(42)
        self.assertEqual(self.view()["notes"], first)

    def test_generate_returns_the_seed(self):
        self.assertEqual(self.bridge.generate(123), 123)
        self.assertEqual(self.view()["seed"], 123)

    def test_settings_are_applied(self):
        self.bridge.set_scale("battle")
        self.bridge.set_key(7)
        self.bridge.set_beats(5)
        self.bridge.set_bpm(150)
        view = self.view()
        self.assertEqual(view["scale"], "battle")
        self.assertEqual(view["key"], 7)
        self.assertEqual(view["beats"], 5)
        self.assertEqual(view["bpm"], 150)
        self.assertEqual(view["steps"], 5 * 4 * 2)

    def test_surprise_sets_everything_at_once(self):
        self.bridge.surprise("japanese", 3, 3, 96, 555)
        view = self.view()
        self.assertEqual((view["scale"], view["key"], view["beats"],
                          view["bpm"], view["seed"]),
                         ("japanese", 3, 3, 96, 555))
        self.assertGreater(view["count"], 0)

    def test_toggle_note_places_then_erases(self):
        self.bridge.clear_all()
        self.assertTrue(self.bridge.toggle_note(60, 0))
        self.assertEqual(self.view()["count"], 1)
        self.assertFalse(self.bridge.toggle_note(60, 0))
        self.assertEqual(self.view()["count"], 0)

    def test_note_goes_to_the_selected_part(self):
        self.bridge.clear_all()
        self.bridge.select_part(2)
        self.bridge.toggle_note(60, 0)
        self.assertEqual(self.view()["notes"][0]["wave"], 2)

    def test_resize_note_lengthens(self):
        self.bridge.clear_all()
        self.bridge.toggle_note(60, 0)
        self.bridge.resize_note(60, 0, 4)
        self.assertEqual(self.view()["notes"][0]["dur"], 4)

    def test_cycle_soft_walks_the_levels(self):
        self.bridge.clear_all()
        self.bridge.toggle_note(60, 0)
        levels = [self.bridge.cycle_soft(60, 0) for _ in range(4)]
        self.assertEqual(levels, [1, 2, 3, 0])

    def test_cycle_soft_on_empty_cell_is_ignored(self):
        self.bridge.clear_all()
        self.assertEqual(self.bridge.cycle_soft(60, 0), -1)

    def test_clear_part_keeps_other_parts(self):
        self.bridge.generate(42)
        self.bridge.select_part(0)
        self.bridge.clear_part()
        waves = {note["wave"] for note in self.view()["notes"]}
        self.assertNotIn(0, waves)
        self.assertTrue(waves)

    def test_transpose_and_reverse_change_the_phrase(self):
        self.bridge.generate(42)
        before = self.view()["notes"]
        self.bridge.transpose(12)
        self.assertNotEqual(self.view()["notes"], before)
        self.bridge.transpose(-12)
        self.bridge.reverse()
        self.assertNotEqual(self.view()["notes"], before)

    def test_arrange_adds_the_other_parts(self):
        self.bridge.clear_all()
        self.bridge.select_part(0)
        for step in (0, 4, 8, 12):
            self.bridge.toggle_note(60 + step // 4, step)
        self.bridge.arrange()
        waves = {note["wave"] for note in self.view()["notes"]}
        self.assertEqual(waves, {0, 1, 2, 3})

    def test_part_settings_follow_the_selection(self):
        self.bridge.select_part(1)
        self.bridge.set_part_tone(70)
        self.bridge.set_part_gate(45)
        params = json.loads(self.bridge.part_settings())
        self.assertEqual((params["tone"], params["gate"]), (70, 45))
        self.bridge.select_part(0)
        self.assertNotEqual(json.loads(self.bridge.part_settings())["tone"], 70)

    def test_loop_pcm_length_is_exact(self):
        from picoseq.core.schedule import phrase_ticks, samples_per_tick
        self.bridge.generate(42)
        pcm = self.bridge.loop_pcm()
        view = self.view()
        spt = samples_per_tick(view["bpm"], self.bridge.WEB_RATE)
        self.assertEqual(len(pcm), view["loopTicks"] * spt * 2)

    def test_wav_download_is_a_wav(self):
        self.bridge.generate(42)
        data = self.bridge.wav_download()
        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(data[8:12], b"WAVE")

    def test_json_roundtrip(self):
        self.bridge.generate(99)
        text = self.bridge.export_json()
        before = self.view()
        self.bridge.clear_all()
        self.assertTrue(self.bridge.import_json(text))
        self.assertEqual(self.view(), before)

    def test_broken_json_is_refused(self):
        self.bridge.generate(42)
        before = self.view()
        self.assertFalse(self.bridge.import_json("これは JSON ではない"))
        self.assertEqual(self.view(), before)

    def test_pitch_label_is_readable(self):
        self.assertEqual(self.bridge.pitch_label(60), "C4")

    def test_snapshot_hides_notes_beyond_the_grid(self):
        """拍子を縮めたとき、はみ出した音符は描画対象に出さない。"""
        self.bridge.set_beats(7)
        self.bridge.generate(42)
        self.bridge.set_beats(2)
        view = self.view()
        self.assertTrue(all(n["step"] < view["steps"] for n in view["notes"]))


class WiringTest(unittest.TestCase):
    """JS ↔ Python ↔ HTML の名前合わせ (ここがずれると黙って動かない)。"""

    @classmethod
    def setUpClass(cls):
        cls.js = (WEB / "app.js").read_text(encoding="utf-8")
        cls.html = (WEB / "index.html").read_text(encoding="utf-8")
        tree = ast.parse((WEB / "bridge.py").read_text(encoding="utf-8"))
        cls.api = {node.name for node in tree.body
                   if isinstance(node, ast.FunctionDef)
                   and not node.name.startswith("_")}

    def test_js_only_calls_functions_that_exist(self):
        called = set(re.findall(r"bridge\.(\w+)\(", self.js))
        missing = sorted(called - self.api)
        self.assertEqual(missing, [], f"bridge に無い関数を呼んでいる: {missing}")

    def test_js_uses_ids_that_exist_in_the_html(self):
        used = set(re.findall(r'\$\("([\w-]+)"\)', self.js))
        ids = set(re.findall(r'id="([\w-]+)"', self.html))
        missing = sorted(used - ids)
        self.assertEqual(missing, [], f"HTML に無い id を参照している: {missing}")

    def test_html_loads_the_static_files(self):
        self.assertIn('src="app.js"', self.html)
        self.assertIn('href="style.css"', self.html)

    def test_pyodide_version_is_pinned(self):
        """CDN の版を固定する (勝手に上がって壊れないように)。"""
        match = re.search(r"pyodide/v(\d+\.\d+\.\d+)/full/", self.js)
        self.assertIsNotNone(match, "Pyodide の版が固定されていない")

    def test_only_pyodide_is_fetched_from_outside(self):
        urls = set(re.findall(r'"(https?://[^"]+)"', self.js))
        self.assertTrue(all("pyodide" in url for url in urls), urls)

    def test_zip_name_matches_what_the_js_fetches(self):
        self.assertIn(f'fetch("{ZIP_NAME}")', self.js)


class BuildOutputTest(unittest.TestCase):
    """組み立てた出力先の中身。"""

    def test_build_writes_everything(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "app"
            summary = build(out)
            for name in ("index.html", "style.css", "app.js", ZIP_NAME):
                with self.subTest(name=name):
                    self.assertTrue((out / name).exists())
            self.assertGreater(summary["modules"], 15)

    def test_static_files_are_copied_verbatim(self):
        with TemporaryDirectory() as tmp:
            out = Path(tmp) / "app"
            build(out)
            self.assertEqual((out / "app.js").read_bytes(),
                             (WEB / "app.js").read_bytes())


if __name__ == "__main__":
    unittest.main()
