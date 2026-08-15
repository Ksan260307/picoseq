"""デモサイト生成のテスト。

CI が公開するページなので、壊れても誰も気づかないまま出てしまう。
「参照先のファイルが実在するか」「外部リソースを引いていないか」
「同じコードから同じページが出るか」を機械で押さえる。
"""

import re
import unittest
import wave
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.build_site import (
    SAMPLES,
    SONG_SAMPLE,
    WEB_RATE,
    build,
    make_phrase,
    make_song,
    progression_text,
    roll_svg,
)


class _TagChecker(HTMLParser):
    """開いたタグが閉じられているかだけを見る簡易チェッカ。"""

    VOID = {"meta", "link", "br", "hr", "img", "input", "source"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.problems = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.problems.append(f"余分な </{tag}>")
        elif self.stack[-1] != tag:
            self.problems.append(f"</{tag}> の位置が合わない (開いているのは {self.stack[-1]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
        else:
            self.stack.pop()


class SiteBuildTest(unittest.TestCase):
    """一度だけ書き出して、その内容を全テストで調べる。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = TemporaryDirectory()
        cls.dir = Path(cls.tmp.name) / "site"
        cls.summary = build(cls.dir)
        cls.html = (cls.dir / "index.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ---- 出来上がったもの ----

    def test_index_and_samples_exist(self):
        self.assertTrue((self.dir / "index.html").exists())
        self.assertEqual(len(self.summary["samples"]), len(SAMPLES) + 1)
        for name in self.summary["samples"]:
            with self.subTest(name=name):
                self.assertTrue((self.dir / "samples" / name).exists())

    def test_nojekyll_is_written(self):
        """Pages が _ 始まりのパスも配信するようにする。"""
        self.assertTrue((self.dir / ".nojekyll").exists())

    def test_every_wav_is_readable_audio(self):
        for name in self.summary["samples"]:
            path = self.dir / "samples" / name
            with self.subTest(name=name), wave.open(str(path)) as f:
                self.assertEqual(f.getframerate(), WEB_RATE)
                self.assertEqual(f.getnchannels(), 1)
                self.assertEqual(f.getsampwidth(), 2)
                self.assertGreater(f.getnframes(), WEB_RATE)   # 1 秒以上ある

    def test_song_sample_is_longer_than_a_phrase(self):
        """1 曲 (16 ブロック) は 2 小節のフレーズより長い。"""
        phrase = self.dir / "samples" / f"{SAMPLES[0][0]}-{SAMPLES[0][1]}-{SAMPLES[0][2]}.wav"
        song = self.dir / "samples" / f"song-{SONG_SAMPLE[0]}-{SONG_SAMPLE[2]}.wav"
        self.assertGreater(song.stat().st_size, phrase.stat().st_size * 4)

    # ---- HTML の中身 ----

    def test_html_tags_are_balanced(self):
        checker = _TagChecker()
        checker.feed(self.html)
        self.assertEqual(checker.problems, [])
        self.assertEqual(checker.stack, [])

    def test_has_the_basics(self):
        for needle in ("<!DOCTYPE html>", 'lang="ja"', "<title>",
                       'name="viewport"', 'charset="utf-8"'):
            with self.subTest(needle=needle):
                self.assertIn(needle, self.html)

    def test_no_external_resources(self):
        """外部の CDN やフォントを引かない (オフラインでも同じに見える)。"""
        for pattern in ('src="http', 'href="http://', 'src="//',
                        "@import", "googleapis"):
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, self.html)

    def test_only_repository_link_is_external(self):
        """外部リンクはリポジトリへの 1 本だけ (誘導先を増やさない)。"""
        links = re.findall(r'href="(https?://[^"]+)"', self.html)
        self.assertEqual(len(links), 1)
        self.assertIn("github.com", links[0])

    def test_every_referenced_file_exists(self):
        for src in re.findall(r'src="([^"]+)"', self.html):
            with self.subTest(src=src):
                self.assertTrue((self.dir / src).exists(), f"{src} が無い")

    def test_one_audio_player_per_sample(self):
        players = self.html.count("<audio")
        self.assertEqual(players, len(SAMPLES) + 1)
        self.assertEqual(self.html.count('preload="none"'), players)

    def test_one_roll_per_sample(self):
        self.assertEqual(self.html.count("<svg"), len(SAMPLES) + 1)

    def test_shows_seed_and_progression(self):
        """再現に必要な情報 (シード値とコード進行) が各カードに出る。

        本文の説明でも「シード値」に触れるので、数字が続く形だけを数える。
        """
        seeds = re.findall(r"シード値 \d+", self.html)
        self.assertEqual(len(seeds), len(SAMPLES) + 1)
        chords = re.findall(r"コード進行 [A-G]", self.html)
        self.assertEqual(len(chords), len(SAMPLES) + 1)

    def test_stats_come_from_the_code(self):
        from picoseq.core.composer import (
            BACKING_STYLES, BASS_STYLES, DRUM_STYLES,
        )
        for count in (DRUM_STYLES, BASS_STYLES, BACKING_STYLES):
            with self.subTest(count=count):
                self.assertIn(f"{count:,} 種", self.html)

    def test_rhythm_shape_counts_are_measured_not_declared(self):
        """打点の並びの数は宣言値ではなく、実際に生成して数えた値であること。

        型の数は音程や長さの違いも含むので「たくさんある」の根拠にならない。
        ここが手書きの数字に戻ると、増やしたつもりで増えていない事故に気づけない。
        """
        from tools.build_site import _rhythm_shapes
        bass, backing, drums = _rhythm_shapes()
        self.assertIn(f"{drums} / {bass} / {backing} 通り", self.html)
        for shapes in (bass, backing, drums):
            self.assertGreaterEqual(shapes, 200)

    def test_theme_supports_light_and_dark(self):
        self.assertIn("color-scheme: light dark", self.html)
        self.assertIn("prefers-color-scheme: dark", self.html)

    def test_removed_features_are_not_advertised(self):
        for word in ("鼻歌", "humming"):
            with self.subTest(word=word):
                self.assertNotIn(word, self.html)


class DeterminismTest(unittest.TestCase):
    """同じコードからは同じページ・同じ音が出る (エンジンが決定論なので)。"""

    def test_page_is_byte_identical(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            build(Path(a))
            build(Path(b))
            first = (Path(a) / "index.html").read_bytes()
            second = (Path(b) / "index.html").read_bytes()
            self.assertEqual(first, second)

    def test_samples_are_byte_identical(self):
        with TemporaryDirectory() as a, TemporaryDirectory() as b:
            build(Path(a))
            build(Path(b))
            for path in sorted((Path(a) / "samples").iterdir()):
                other = Path(b) / "samples" / path.name
                with self.subTest(name=path.name):
                    self.assertEqual(path.read_bytes(), other.read_bytes())


class PiecesTest(unittest.TestCase):
    """部品ごとの検査 (書き出しを伴わないので速い)。"""

    def test_sample_list_is_valid(self):
        from picoseq.core.constants import BEATS_MAX, BEATS_MIN
        from picoseq.core.music import KEY_NAMES, SCALE_IDS
        for scale, key, seed, beats, label in SAMPLES + (SONG_SAMPLE,):
            with self.subTest(scale=scale):
                self.assertIn(scale, SCALE_IDS)
                self.assertTrue(0 <= key < len(KEY_NAMES))
                self.assertTrue(BEATS_MIN <= beats <= BEATS_MAX)
                self.assertTrue(label.strip())

    def test_samples_are_musically_different(self):
        """並べる意味があること (同じ曲を 12 個載せない)。"""
        phrases = {make_phrase(s, k, seed, b).phrase
                   for s, k, seed, b, _ in SAMPLES}
        self.assertEqual(len(phrases), len(SAMPLES))

    def test_roll_svg_draws_every_note(self):
        project = make_phrase("major", 0, 42, 4)
        from picoseq.core.phrase import count_notes
        svg = roll_svg(project)
        self.assertTrue(svg.startswith("<svg"))
        self.assertTrue(svg.endswith("</svg>"))
        # 音符の矩形は fill 付き。背景と拍線には fill を書かない
        self.assertEqual(svg.count("fill=\"#"), count_notes(project.phrase))

    def test_roll_svg_shows_dynamics_as_opacity(self):
        project = make_phrase("major", 0, 42, 4)
        opacities = set(re.findall(r'opacity="([0-9.]+)"', roll_svg(project)))
        self.assertGreater(len(opacities), 1, "強弱が反映されていない")

    def test_roll_svg_scales_with_the_meter(self):
        """拍子が変わると引く線の本数も変わる。

        小節線の数は 3 本のまま (2 小節なので) なので、拍線を含めて数える。
        """
        four = roll_svg(make_phrase("major", 0, 42, 4))
        five = roll_svg(make_phrase("major", 0, 42, 5))
        self.assertLess(four.count("<line"), five.count("<line"))

    def test_progression_text_is_readable(self):
        text = progression_text(make_phrase("minor", 0, 7, 4))
        self.assertIn("→", text)
        self.assertEqual(len(text.split("→")), 4)

    def test_song_sample_fills_the_grid(self):
        from picoseq.core.song import used_blocks
        song = make_song(*SONG_SAMPLE[:4])
        self.assertEqual(used_blocks(song.song), 16)


if __name__ == "__main__":
    unittest.main()
