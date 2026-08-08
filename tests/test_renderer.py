"""レンダラのテスト — 加算順序・表示との分離・回帰。"""

import unittest
import zlib
from array import array

from picoseq.core import actions
from picoseq.core.constants import SAMPLE_RATE
from picoseq.core.project import new_project
from picoseq.core import renderer as renderer_mod
from picoseq.core.renderer import (
    TAIL_SECONDS,
    clear_cache,
    clip_to_pcm,
    render_events,
    render_phrase,
    render_phrase_loop,
    render_preview,
    render_song,
    render_song_loop,
)
from picoseq.core.renderer import _render_events_numpy, _render_events_python
from picoseq.core.schedule import Event, samples_per_tick
from picoseq.core.synth import voice_samples

# numpy は任意の依存。有無で通せるテストが変わる。
_HAVE_NUMPY = renderer_mod._np is not None

GOLDEN_PHRASE_CRC = 1819521355  # seed=42, 4/4, C major, 既定パート設定
GOLDEN_SONG_CRC = 3976110364    # 上記フレーズをパターン0 に保存し ブロック0,1 へ配置


def _seed42_project():
    return actions.generate_phrase(actions.set_seed(new_project(), 42))


class TestMixing(unittest.TestCase):
    def test_empty_is_silence(self):
        p = new_project()
        mix = render_events([], p.bpm, p.parts, 4)
        self.assertEqual(len(mix), 4 * samples_per_tick(p.bpm) + SAMPLE_RATE * TAIL_SECONDS)
        self.assertTrue(all(v == 0 for v in mix))

    def test_event_starts_at_tick_sample(self):
        p = new_project()
        spt = samples_per_tick(p.bpm)
        mix = render_events([Event(2, 60, 0, 1)], p.bpm, p.parts, 8)
        self.assertTrue(all(v == 0 for v in mix[: 2 * spt]))
        self.assertTrue(any(v != 0 for v in mix[2 * spt:]))

    def test_order_independence(self):
        """イベントの並び順を変えても結果は完全一致する。"""
        p = new_project()
        events = [Event(0, 60, 0, 4), Event(0, 48, 1, 4), Event(2, 55, 3, 2),
                  Event(2, 60, 2, 1), Event(1, 64, 0, 2)]
        forward = render_events(events, p.bpm, p.parts, 8)
        backward = render_events(list(reversed(events)), p.bpm, p.parts, 8)
        # 経路 (numpy / list) に依らず PCM で比較する
        self.assertEqual(clip_to_pcm(forward), clip_to_pcm(backward))

    def test_clip_to_pcm(self):
        pcm = clip_to_pcm([0, 100, -100, 40000, -40000])
        values = array("h")
        values.frombytes(pcm)
        self.assertEqual(list(values), [0, 100, -100, 32767, -32768])


class TestPhraseRender(unittest.TestCase):
    def test_deterministic_and_golden(self):
        p = _seed42_project()
        a = render_phrase(p)
        b = render_phrase(p)
        self.assertEqual(a, b)
        self.assertEqual(zlib.crc32(a), GOLDEN_PHRASE_CRC)

    def test_ignores_unrelated_state(self):
        """フレーズの音は ソング構成・パターン・シードの変更に影響されない (無関係な設定に音が影響されない)。"""
        p = _seed42_project()
        base = render_phrase(p)
        changed = actions.save_pattern(p, 3)
        changed = actions.toggle_song_cell(changed, 0, 0, 3)
        changed = actions.update(changed, seed=777)
        self.assertEqual(render_phrase(changed), base)

    def test_bpm_changes_length(self):
        p = _seed42_project()
        slow = render_phrase(actions.set_bpm(p, 60))
        fast = render_phrase(actions.set_bpm(p, 240))
        self.assertGreater(len(slow), len(fast))


class TestSongRender(unittest.TestCase):
    def test_golden(self):
        p = _seed42_project()
        p = actions.save_pattern(p, 0)
        p = actions.toggle_song_cell(p, 0, 0, 0)
        p = actions.toggle_song_cell(p, 0, 1, 0)
        pcm = render_song(p)
        self.assertEqual(zlib.crc32(pcm), GOLDEN_SONG_CRC)

    def test_empty_song_is_one_block_of_silence(self):
        p = new_project()
        pcm = render_song(p)
        spt = samples_per_tick(p.bpm)
        expected = (32 * spt + SAMPLE_RATE * TAIL_SECONDS) * 2  # 16bit
        self.assertEqual(len(pcm), expected)
        self.assertEqual(pcm, b"\x00" * expected)

    def test_blocks_are_placed(self):
        """ブロック 1 だけに配置すると、ブロック 0 は無音になる。"""
        p = _seed42_project()
        p = actions.save_pattern(p, 0)
        p = actions.toggle_song_cell(p, 0, 1, 0)
        pcm = render_song(p)
        spt = samples_per_tick(p.bpm)
        block_bytes = 32 * spt * 2
        self.assertEqual(pcm[:block_bytes], b"\x00" * block_bytes)
        self.assertNotEqual(pcm[block_bytes: 2 * block_bytes],
                            b"\x00" * block_bytes)


class TestLoopRender(unittest.TestCase):
    def test_loop_length_is_exact(self):
        p = _seed42_project()
        pcm = render_phrase_loop(p)
        spt = samples_per_tick(p.bpm)
        self.assertEqual(len(pcm), 32 * spt * 2)  # 尻尾なし

    def test_wrap_folds_tail_to_head(self):
        """折り返しミックス = 尻尾付きミックスをループ長で畳んだもの。"""
        p = new_project()
        events = [Event(6, 60, 0, 4)]  # 8 tick 中 6 拍目から長い音 → 尻尾がはみ出す
        spt = samples_per_tick(p.bpm)
        loop_len = 8 * spt
        plain = list(render_events(events, p.bpm, p.parts, 8))
        wrapped = list(render_events(events, p.bpm, p.parts, 8, wrap=True))
        folded = [0] * loop_len
        for i, value in enumerate(plain):
            folded[i % loop_len] += int(value)
        self.assertEqual([int(v) for v in wrapped], folded)

    def test_song_loop_deterministic(self):
        p = _seed42_project()
        p = actions.save_pattern(p, 0)
        p = actions.toggle_song_cell(p, 0, 0, 0)
        self.assertEqual(render_song_loop(p), render_song_loop(p))


@unittest.skipUnless(_HAVE_NUMPY, "numpy が無い環境 (純 Python 経路のみ)")
class TestBackendEquivalence(unittest.TestCase):
    """numpy 経路と純 Python 経路は完全一致でなければならない (リファレンス実装との比較)。

    numpy は任意の依存なので、無い環境ではこの比較そのものが成り立たない
    (`_render_events_numpy` を直接呼ぶため、本体の自動フォールバックは効かない)。
    CI では numpy 有りのジョブ (pages.yml) がこの一致を確かめ、
    numpy 無しのジョブ (ci.yml) が純 Python 経路だけを確かめる。
    """

    def _events(self):
        p = _seed42_project()
        p = actions.save_pattern(p, 0)
        p = actions.toggle_song_cell(p, 0, 0, 0)
        p = actions.toggle_song_cell(p, 1, 1, 0)
        from picoseq.core.schedule import song_events, song_ticks
        return song_events(p), p, song_ticks(p)

    def test_numpy_matches_python_wrap(self):
        events, p, ticks = self._events()
        clear_cache()
        py = clip_to_pcm(_render_events_python(events, p.bpm, p.parts, ticks, SAMPLE_RATE, True))
        clear_cache()
        np_pcm = clip_to_pcm(_render_events_numpy(events, p.bpm, p.parts, ticks, SAMPLE_RATE, True))
        self.assertEqual(py, np_pcm)

    def test_numpy_matches_python_tail(self):
        events, p, ticks = self._events()
        clear_cache()
        py = clip_to_pcm(_render_events_python(events, p.bpm, p.parts, ticks, SAMPLE_RATE, False))
        clear_cache()
        np_pcm = clip_to_pcm(_render_events_numpy(events, p.bpm, p.parts, ticks, SAMPLE_RATE, False))
        self.assertEqual(py, np_pcm)

    def test_long_note_wraps_multiple_times(self):
        """ループ長より長い音符でも両経路が一致する (折り返しの多重ラップ)。"""
        p = new_project()
        events = [Event(0, 60, 1, 200)]  # 200 tick の音を 4 tick ループへ
        clear_cache()
        py = _render_events_python(events, p.bpm, p.parts, 4, SAMPLE_RATE, True)
        clear_cache()
        np_pcm = _render_events_numpy(events, p.bpm, p.parts, 4, SAMPLE_RATE, True)
        self.assertEqual(clip_to_pcm(py), clip_to_pcm(np_pcm))


class TestMute(unittest.TestCase):
    """ミュート — 消音した (パート, レイヤー) の音だけが消え、他は不変。"""

    def _multi_part_project(self):
        p = _seed42_project()
        return actions.arrange_accompaniment(p)  # 4 パートすべてに音が入る (各 1 層)

    def test_mute_removes_only_that_part(self):
        p = self._multi_part_project()
        from picoseq.core.schedule import phrase_events, phrase_ticks
        events = phrase_events(p)
        waves = {e.wave for e in events}
        self.assertEqual(waves, {0, 1, 2, 3})  # 前提: 全パートに音がある

        full = render_phrase(p)
        muted_rhythm = render_phrase(p, mute={(2, 0)})
        self.assertNotEqual(full, muted_rhythm)

        # リズム (wave 2, layer 0) だけを抜いたイベントの描画と一致する
        kept = [e for e in events if (e.wave, e.layer) != (2, 0)]
        expected = clip_to_pcm(render_events(
            kept, p.bpm, p.parts, phrase_ticks(p), sound=p.sound))
        self.assertEqual(muted_rhythm, expected)

    def test_mute_all_is_silence(self):
        p = self._multi_part_project()
        pcm = render_phrase(p, mute={(0, 0), (1, 0), (2, 0), (3, 0)})
        self.assertEqual(pcm, b"\x00" * len(pcm))

    def test_no_mute_matches_default(self):
        p = self._multi_part_project()
        self.assertEqual(render_phrase(p), render_phrase(p, mute=set()))

    def test_mute_is_deterministic(self):
        p = self._multi_part_project()
        self.assertEqual(render_song_loop(p, mute={(1, 0), (3, 0)}),
                         render_song_loop(p, mute={(1, 0), (3, 0)}))

    def test_layer_mute_targets_one_layer(self):
        """メロディに 2 層作り、片方だけ消音すると出力が変わり、両方消すと更に変わる。"""
        from picoseq.core.constants import WAVE_PULSE
        p = _seed42_project()
        p = actions.add_layer(p, WAVE_PULSE)          # メロディに 2 層目
        p = actions.generate_phrase(p)                # 両層に音が入る
        from picoseq.core.schedule import phrase_events
        layers = {e.layer for e in phrase_events(p) if e.wave == WAVE_PULSE}
        self.assertIn(1, layers)                      # 前提: 2 層目にも音がある

        full = render_phrase(p)
        one = render_phrase(p, mute={(WAVE_PULSE, 1)})
        both = render_phrase(p, mute={(WAVE_PULSE, 0), (WAVE_PULSE, 1)})
        self.assertNotEqual(full, one)
        self.assertNotEqual(one, both)


class TestVoiceCache(unittest.TestCase):
    def test_cache_preserves_output(self):
        p = _seed42_project()
        clear_cache()
        cold = render_phrase(p)
        warm = render_phrase(p)  # 2 回目はキャッシュ経由
        self.assertEqual(cold, warm)

    def test_golden_holds_with_cache(self):
        clear_cache()
        self.assertEqual(zlib.crc32(render_phrase(_seed42_project())), GOLDEN_PHRASE_CRC)


class TestPreview(unittest.TestCase):
    def test_preview_note(self):
        pcm = render_preview(0, 60, 50, 80)
        self.assertEqual(len(pcm), voice_samples(SAMPLE_RATE // 4, 80) * 2)
        self.assertNotEqual(pcm, b"\x00" * len(pcm))


if __name__ == "__main__":
    unittest.main()
