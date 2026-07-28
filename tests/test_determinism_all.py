"""決定論・順序独立・再現性の網羅テスト。

全 65 曲調 × 複数シードで、コア (作曲・レンダリング) が
「同じ入力 → 同じ出力」「評価順序によらない」を必ず満たすことを保証する。
テストは曲調ごとに動的生成し、どの曲調で壊れたかがすぐ分かるようにする。

レンダリングは重いので、レンダリング系のテストは 1 シードに絞り、
2 回目はキャッシュ経由 (= キャッシュ経路の一致も同時に検査) にして速さを保つ。

さらに**合成は低いサンプリング周波数で行う** (TEST_RATE)。ここで見たいのは
「同じ入力なら同じ出力」「足す順番によらない」という性質で、どちらも
サンプル数に依存しない。44.1kHz だと 65 曲調 × 2 種のレンダリングで
1 分以上かかり、開発中に回しづらくなる (音そのものの回帰は
test_renderer.py のゴールデン CRC が 44.1kHz で見張っている)。
"""

import random
import unittest
import zlib

from picoseq.core import actions
from picoseq.core.composer import (
    accompany_notes,
    chosen_progression,
    compose,
    compose_layers,
)
from picoseq.core.constants import SAMPLE_RATE, SOUND_SETS, WAVE_PULSE
from picoseq.core.music import SCALES, SCALE_IDS
from picoseq.core.phrase import count_notes
from picoseq.core.project import new_project
from picoseq.core.renderer import (
    clear_cache,
    phrase_events,
    render_events,
    render_phrase,
)
from picoseq.core.schedule import phrase_ticks

COMPOSE_SEEDS = (1, 42, 999)
RENDER_SEED = 42
TEST_RATE = 11025   # 性質の検査には十分。44.1kHz の 1/4 の時間で回る


def _project(scale, seed, key=0):
    return actions.generate_phrase(
        actions.set_key(actions.set_scale(
            actions.set_seed(new_project(), seed), scale), key))


# ---- 曲調ごとに動的生成するテスト群 -------------------------------------


class ComposeDeterminism(unittest.TestCase):
    """compose は同じ (拍子, キー, 曲調, シード) から必ず同じ結果。"""


class RenderDeterminism(unittest.TestCase):
    """render_phrase は同じプロジェクトから必ずビット等価 (キャッシュ経由でも)。"""


class AccompanyDeterminism(unittest.TestCase):
    """伴奏生成 (メロディ抜き) も決定論的。"""


class OrderIndependence(unittest.TestCase):
    """レンダリングは整数和なので、イベントの評価順序によらず同一。"""


class ProgressionValidity(unittest.TestCase):
    """選ばれる進行は必ずその曲調の音数に収まる。"""


class KeyDeterminism(unittest.TestCase):
    """代表的な複数キーで生成が決定論的、かつメロディが消えない。"""


def _compose_test(scale):
    def test(self):
        for beats in (3, 4):
            for seed in COMPOSE_SEEDS:
                a = compose(beats, 0, scale, seed)
                b = compose(beats, 0, scale, seed)
                self.assertEqual(a, b, f"beats={beats} seed={seed}")
    return test


def _render_test(scale):
    def test(self):
        p = _project(scale, RENDER_SEED)
        clear_cache()
        a = render_phrase(p, rate=TEST_RATE)   # 未キャッシュ
        b = render_phrase(p, rate=TEST_RATE)   # キャッシュ経由
        self.assertEqual(zlib.crc32(a), zlib.crc32(b))
        self.assertTrue(a, "無音になっている")
    return test


def _accompany_test(scale):
    def test(self):
        for seed in COMPOSE_SEEDS:
            a = accompany_notes(4, 0, scale, seed)
            b = accompany_notes(4, 0, scale, seed)
            self.assertEqual(a, b)
            self.assertFalse(any(n.wave == WAVE_PULSE for n in a),
                             "伴奏にメロディが混ざっている")
    return test


def _order_test(scale):
    def test(self):
        p = _project(scale, RENDER_SEED)
        events = phrase_events(p)
        tk = phrase_ticks(p)
        clear_cache()
        base = list(render_events(events, p.bpm, p.parts, tk, TEST_RATE,
                                  sound=p.sound))
        shuffled = events[:]
        random.Random(RENDER_SEED).shuffle(shuffled)
        other = list(render_events(shuffled, p.bpm, p.parts, tk, TEST_RATE,
                                   sound=p.sound))
        self.assertEqual(base, other, "評価順序で結果が変わった (順序独立性の破れ)")
    return test


def _progression_test(scale):
    def test(self):
        n = len(SCALES[scale]["intervals"])
        for seed in COMPOSE_SEEDS:
            prog = chosen_progression(scale, seed)
            self.assertEqual(len(prog), 4)
            for degree in prog:
                self.assertTrue(0 <= degree < n, f"度数 {degree} が範囲外")
    return test


def _key_test(scale):
    def test(self):
        for key in (0, 5, 7, 11):
            a = _project(scale, 42, key)
            b = _project(scale, 42, key)
            self.assertEqual(a.phrase, b.phrase)
            self.assertGreater(count_notes(a.phrase), 0)
    return test


for _sid in SCALE_IDS:
    setattr(ComposeDeterminism, f"test_{_sid}", _compose_test(_sid))
    setattr(RenderDeterminism, f"test_{_sid}", _render_test(_sid))
    setattr(AccompanyDeterminism, f"test_{_sid}", _accompany_test(_sid))
    setattr(OrderIndependence, f"test_{_sid}", _order_test(_sid))
    setattr(ProgressionValidity, f"test_{_sid}", _progression_test(_sid))
    setattr(KeyDeterminism, f"test_{_sid}", _key_test(_sid))


# ---- 音色ごとの決定論 ----------------------------------------------------


class SoundDeterminism(unittest.TestCase):
    """各音色で render が決定論的で無音にならない。"""


def _sound_test(sound):
    def test(self):
        p = actions.set_sound(_project("major", RENDER_SEED), sound)
        clear_cache()
        a = render_phrase(p, rate=TEST_RATE)
        b = render_phrase(p, rate=TEST_RATE)
        self.assertEqual(a, b)
        self.assertTrue(a)
    return test


for _snd in SOUND_SETS:
    setattr(SoundDeterminism, f"test_{_snd}", _sound_test(_snd))


class LayeredDeterminism(unittest.TestCase):
    """マルチレイヤー生成も決定論的で、レイヤーを増やすと音符が増える。"""

    def test_layers_are_deterministic(self):
        for seed in COMPOSE_SEEDS:
            a = compose_layers(4, 0, "major", seed, (2, 2, 1, 1))
            b = compose_layers(4, 0, "major", seed, (2, 2, 1, 1))
            self.assertEqual(a, b)

    def test_more_layers_more_notes(self):
        for seed in (1, 42, 100):
            base = count_notes(compose_layers(4, 0, "major", seed, (1, 1, 1, 1)))
            more = count_notes(compose_layers(4, 0, "major", seed, (3, 1, 1, 1)))
            self.assertGreaterEqual(more, base)


if __name__ == "__main__":
    unittest.main()
