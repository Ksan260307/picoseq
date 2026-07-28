"""音色セットのテスト — 3 音色の決定論・違い・既定音色の完全互換。"""

import unittest
import zlib

from picoseq.core import actions
from picoseq.core.constants import DEFAULT_SOUND, SOUND_SETS
from picoseq.core.project import new_project
from picoseq.core.renderer import (
    clear_cache,
    clip_to_pcm,
    render_phrase,
    render_preview,
)
from picoseq.core.serialize import dumps, loads, to_jsonable
from picoseq.core.synth import PEAKS, render_voice


class TestSoundSets(unittest.TestCase):
    def test_three_sets(self):
        self.assertEqual(SOUND_SETS, ("retro8", "warm16", "clear32"))
        self.assertEqual(DEFAULT_SOUND, "retro8")

    def test_default_matches_golden(self):
        """既定の retro8 の各波形を回帰検査する。

        値は tests/test_synth.py の GOLDEN_VOICE_CRC と同じ (音を変える変更は
        両方を更新する)。旧版とのビット互換は既に手放している:
        ベース(1) は倍音を重ねて可聴化し (擬似ベース強調)、
        その後 4 パートの音量配分を実測 RMS で釣り合わせ直したため全波形が変わった。
        """
        golden = {0: 3039640967, 1: 3219326059, 2: 157465462, 3: 4004919461}
        for wave, crc in golden.items():
            with self.subTest(wave=wave):
                voice = render_voice(wave, 60, 5512, 50, 80)
                self.assertEqual(zlib.crc32(clip_to_pcm(voice)), crc)

    def test_each_sound_is_deterministic(self):
        for sound in SOUND_SETS:
            for wave in range(4):
                with self.subTest(sound=sound, wave=wave):
                    a = render_voice(wave, 60, 5512, 50, 80, sound=sound)
                    b = render_voice(wave, 60, 5512, 50, 80, sound=sound)
                    self.assertEqual(a, b)
                    self.assertTrue(a, "無音になっている")

    def test_sounds_differ(self):
        for wave in range(4):
            with self.subTest(wave=wave):
                voices = {sound: tuple(render_voice(wave, 60, 5512, 50, 80, sound=sound))
                          for sound in SOUND_SETS}
                self.assertNotEqual(voices["retro8"], voices["warm16"])
                self.assertNotEqual(voices["retro8"], voices["clear32"])

    def test_amplitude_bounded(self):
        for sound in SOUND_SETS:
            for wave in range(4):
                with self.subTest(sound=sound, wave=wave):
                    voice = render_voice(wave, 60, 5512, 50, 80, sound=sound)
                    limit = PEAKS[wave] * 2 + 1
                    self.assertTrue(all(abs(v) <= limit for v in voice))


class TestSoundInProject(unittest.TestCase):
    def test_set_sound(self):
        p = actions.set_sound(new_project(), "clear32")
        self.assertEqual(p.sound, "clear32")
        self.assertIs(actions.set_sound(p, "clear32"), p)  # 無変更は同一
        with self.assertRaises(ValueError):
            actions.set_sound(p, "chiptune9000")

    def test_render_follows_project_sound(self):
        p = actions.generate_phrase(actions.set_seed(new_project(), 42))
        clear_cache()
        retro = render_phrase(p)
        clear_cache()
        warm = render_phrase(actions.set_sound(p, "warm16"))
        self.assertNotEqual(retro, warm)

    def test_cache_keeps_sounds_apart(self):
        """キャッシュ越しでも音色が混ざらない。"""
        clear_cache()
        a = render_preview(0, 60, 50, 80, sound="retro8")
        b = render_preview(0, 60, 50, 80, sound="warm16")
        a2 = render_preview(0, 60, 50, 80, sound="retro8")
        self.assertNotEqual(a, b)
        self.assertEqual(a, a2)

    def test_serialize_roundtrip(self):
        p = actions.set_sound(new_project(), "warm16")
        self.assertEqual(loads(dumps(p)).sound, "warm16")

    def test_old_data_defaults_to_retro8(self):
        """v3 以前 (sound 無し) のデータは既定音色になる (後方互換)。"""
        import json
        data = to_jsonable(new_project())
        data["schema"] = 3
        del data["sound"]
        self.assertEqual(loads(json.dumps(data)).sound, "retro8")

    def test_invalid_sound_falls_back(self):
        import json
        data = to_jsonable(new_project())
        data["sound"] = "vinyl78"
        self.assertEqual(loads(json.dumps(data)).sound, "retro8")


class TestThemePalettes(unittest.TestCase):
    def test_palettes_cover_all_sounds(self):
        from picoseq.ui import theme
        self.assertEqual(set(theme.PALETTES), set(SOUND_SETS))
        self.assertEqual(set(theme.SOUND_LABELS), set(SOUND_SETS))
        # どのパレットも同じキーを持つ (差し替えても参照切れしない)
        keys = set(theme.PALETTES["retro8"])
        for sound in SOUND_SETS:
            self.assertEqual(set(theme.PALETTES[sound]), keys)

    def test_set_palette_switches_and_restores(self):
        from picoseq.ui import theme
        try:
            theme.set_palette("warm16")
            self.assertEqual(theme.BG, theme.PALETTES["warm16"]["BG"])
            self.assertNotEqual(theme.BG, theme.PALETTES["retro8"]["BG"])
        finally:
            theme.set_palette("retro8")
        self.assertEqual(theme.BG, theme.PALETTES["retro8"]["BG"])

    def test_labels_avoid_console_names(self):
        """UI の音色名にゲーム機の固有名詞を使わない。"""
        from picoseq.ui import theme
        banned = ("ファミコン", "スーファミ", "スーパーファミコン", "GBA",
                  "ゲームボーイ", "SNES", "NES", "Nintendo", "任天堂")
        for label in theme.SOUND_LABELS.values():
            for word in banned:
                self.assertNotIn(word, label)


if __name__ == "__main__":
    unittest.main()
