"""操作 (アクション) のテスト — 純粋性・範囲収め・連鎖の整合。"""

import unittest

from picoseq.core import actions
from picoseq.core.constants import EMPTY_CELL, MAX_NOTES
from picoseq.core.note import Note, unpack_note
from picoseq.core.phrase import EMPTY_PHRASE, active_notes, build_phrase, count_notes
from picoseq.core.project import new_project, steps_of
from picoseq.core.song import EMPTY_SONG, get_cell


class TestSetters(unittest.TestCase):
    def setUp(self):
        self.p = new_project()

    def test_set_bpm_clamps(self):
        self.assertEqual(actions.set_bpm(self.p, 0).bpm, 60)
        self.assertEqual(actions.set_bpm(self.p, 999).bpm, 240)
        self.assertEqual(actions.set_bpm(self.p, 150).bpm, 150)

    def test_set_bpm_no_change_returns_same_object(self):
        self.assertIs(actions.set_bpm(self.p, self.p.bpm), self.p)

    def test_set_beats_resets_song(self):
        p = actions.toggle_song_cell(actions.save_pattern(self.p, 0), 0, 0, 0)
        self.assertNotEqual(p.song, EMPTY_SONG)
        p2 = actions.set_beats(p, 3)
        self.assertEqual(p2.beats, 3)
        self.assertEqual(p2.song, EMPTY_SONG)
        self.assertEqual(p2.phrase, p.phrase)  # フレーズは残す

    def test_set_beats_clamps(self):
        self.assertEqual(actions.set_beats(self.p, 1).beats, 2)
        self.assertEqual(actions.set_beats(self.p, 9).beats, 7)

    def test_set_beats_same_keeps_song(self):
        p = actions.toggle_song_cell(actions.save_pattern(self.p, 0), 0, 0, 0)
        self.assertIs(actions.set_beats(p, p.beats), p)

    def test_set_key_clamps(self):
        self.assertEqual(actions.set_key(self.p, -5).key, 0)
        self.assertEqual(actions.set_key(self.p, 99).key, 11)

    def test_set_scale(self):
        self.assertEqual(actions.set_scale(self.p, "battle").scale, "battle")
        with self.assertRaises(ValueError):
            actions.set_scale(self.p, "polka")

    def test_set_seed_clamps(self):
        self.assertEqual(actions.set_seed(self.p, 0).seed, 1)
        self.assertEqual(actions.set_seed(self.p, 10 ** 9).seed, 999_999)

    def test_set_progression(self):
        p = actions.set_progression(self.p, (0, 3, 1, 4))
        self.assertEqual(p.progression, (0, 3, 1, 4))
        p = actions.set_progression(p, None)
        self.assertIsNone(p.progression)

    def test_set_progression_validates(self):
        with self.assertRaises(ValueError):
            actions.set_progression(self.p, (0, 7))  # minor は 7 音 → 度数 0..6
        with self.assertRaises(ValueError):
            actions.set_progression(self.p, ())
        with self.assertRaises(ValueError):
            actions.set_progression(self.p, tuple(range(6)) * 3)  # 長すぎ

    def test_set_scale_resets_progression(self):
        """音階が変われば度数の意味が変わるため、進行は既定へ戻す。"""
        p = actions.set_progression(self.p, (0, 5, 2, 6))
        p = actions.set_scale(p, "japanese")
        self.assertIsNone(p.progression)

    def test_photo_scale_requires_custom(self):
        with self.assertRaises(ValueError):
            actions.set_scale(self.p, "photo")  # まだフォト音階が無い

    def test_set_custom_scale(self):
        p = actions.set_custom_scale(self.p, key=5, intervals=(3, 0, 10, 3),
                                     bpm=150, seed=77)
        self.assertEqual(p.scale, "photo")
        self.assertEqual(p.custom_scale, (0, 3, 10))  # 整列・重複除去
        self.assertEqual((p.key, p.bpm, p.seed), (5, 150, 77))
        # 別の曲調へ移ってもフォト音階は残っていて、戻れる
        p = actions.set_scale(p, "major")
        self.assertEqual(p.custom_scale, (0, 3, 10))
        p = actions.set_scale(p, "photo")
        self.assertEqual(p.scale, "photo")

    def test_set_custom_scale_adds_root(self):
        p = actions.set_custom_scale(self.p, 0, (4, 7, 11), 120, 1)
        self.assertEqual(p.custom_scale[0], 0)  # 0 (キー自身) を必ず含む

    def test_set_custom_scale_requires_three(self):
        with self.assertRaises(ValueError):
            actions.set_custom_scale(self.p, 0, (0, 5), 120, 1)

    def test_generate_with_photo_scale(self):
        p = actions.set_custom_scale(self.p, 0, (0, 2, 5, 7, 9), 120, 3)
        p = actions.generate_phrase(p)
        from picoseq.core.music import in_scale
        from picoseq.core.phrase import active_notes
        melody = [n for _, n in active_notes(p.phrase) if n.wave == 0]
        self.assertTrue(melody)
        for note in melody:
            self.assertTrue(in_scale(note.pitch, 0, "photo", p.custom_scale))

    def test_part_params(self):
        p = actions.set_part_tone(self.p, 2, 999)
        self.assertEqual(p.parts[2][0].tone, 100)
        p = actions.set_part_gate(p, 2, 0)
        self.assertEqual(p.parts[2][0].gate, 10)
        # 他パートは不変
        self.assertEqual(p.parts[0], self.p.parts[0])
        with self.assertRaises(ValueError):
            actions.set_part_tone(self.p, 4, 50)

    def test_part_volume(self):
        self.assertEqual(self.p.parts[1][0].volume, 100)      # 既定は 100
        p = actions.set_part_volume(self.p, 1, 40)
        self.assertEqual(p.parts[1][0].volume, 40)
        self.assertEqual(actions.set_part_volume(self.p, 1, 999).parts[1][0].volume, 100)
        self.assertEqual(actions.set_part_volume(self.p, 1, -5).parts[1][0].volume, 0)
        self.assertEqual(p.parts[0], self.p.parts[0])         # 他パートは不変
        self.assertIs(actions.set_part_volume(self.p, 1, 100), self.p)  # 無変更は同一


class TestPhraseEdit(unittest.TestCase):
    def setUp(self):
        self.p = new_project()

    def test_place_note(self):
        p, slot = actions.place_note(self.p, 60, 0, 0)
        self.assertEqual(slot, 0)
        self.assertEqual(count_notes(p.phrase), 1)
        self.assertEqual(count_notes(self.p.phrase), 0)  # 元は不変

    def test_place_note_validates(self):
        with self.assertRaises(ValueError):
            actions.place_note(self.p, 35, 0, 0)  # 音域外
        with self.assertRaises(ValueError):
            actions.place_note(self.p, 60, steps_of(self.p), 0)  # グリッド外
        with self.assertRaises(ValueError):
            actions.place_note(self.p, 60, 0, 4)  # パート外

    def test_place_note_clamps_duration_to_grid(self):
        steps = steps_of(self.p)
        p, slot = actions.place_note(self.p, 60, steps - 2, 0, dur=10)
        self.assertEqual(unpack_note(p.phrase[slot]).dur, 2)

    def test_place_note_when_full(self):
        full = build_phrase([Note(60, 0, 0, 1)] * MAX_NOTES)
        p = actions.update(self.p, phrase=full)
        p2, slot = actions.place_note(p, 60, 0, 0)
        self.assertEqual(slot, -1)
        self.assertIs(p2, p)

    def test_erase_note(self):
        p, slot = actions.place_note(self.p, 60, 0, 0)
        p = actions.erase_note(p, slot)
        self.assertEqual(count_notes(p.phrase), 0)

    def test_erase_invalid_slot_is_noop(self):
        self.assertIs(actions.erase_note(self.p, 5), self.p)
        self.assertIs(actions.erase_note(self.p, -1), self.p)
        self.assertIs(actions.erase_note(self.p, 10 ** 6), self.p)

    def test_resize_note(self):
        p, slot = actions.place_note(self.p, 60, 0, 0)
        p = actions.resize_note(p, slot, 4)
        self.assertEqual(unpack_note(p.phrase[slot]).dur, 4)

    def test_resize_clamps_to_grid(self):
        steps = steps_of(self.p)
        p, slot = actions.place_note(self.p, 60, steps - 3, 0)
        p = actions.resize_note(p, slot, 99)
        self.assertEqual(unpack_note(p.phrase[slot]).dur, 3)

    def test_clear_phrase(self):
        p, _ = actions.place_note(self.p, 60, 0, 0)
        p = actions.clear_phrase(p)
        self.assertEqual(p.phrase, EMPTY_PHRASE)
        self.assertIs(actions.clear_phrase(self.p), self.p)


class TestEditTools(unittest.TestCase):
    def _project(self, notes):
        return actions.update(new_project(), phrase=build_phrase(notes))

    def test_transpose_shifts_pitched_parts(self):
        p = self._project([Note(60, 0, 0, 1), Note(48, 4, 1, 1)])
        up = actions.transpose(p, 12)
        pitches = sorted(n.pitch for _, n in active_notes(up.phrase))
        self.assertEqual(pitches, [60, 72])

    def test_transpose_keeps_drums_fixed(self):
        p = self._project([Note(60, 0, 2, 1)])  # noise
        up = actions.transpose(p, 12)
        self.assertEqual([n.pitch for _, n in active_notes(up.phrase)], [60])

    def test_transpose_drops_out_of_range(self):
        p = self._project([Note(84, 0, 0, 1)])  # C6 上限
        self.assertEqual(count_notes(actions.transpose(p, 12).phrase), 0)
        p = self._project([Note(36, 0, 0, 1)])  # C2 下限
        self.assertEqual(count_notes(actions.transpose(p, -12).phrase), 0)

    def test_transpose_zero_is_noop(self):
        p = self._project([Note(60, 0, 0, 1)])
        self.assertIs(actions.transpose(p, 0), p)

    def test_clear_part(self):
        p = self._project([Note(60, 0, 0, 1), Note(48, 0, 1, 1), Note(60, 2, 2, 1)])
        cleared = actions.clear_part(p, 2)
        waves = {n.wave for _, n in active_notes(cleared.phrase)}
        self.assertEqual(waves, {0, 1})

    def test_clear_part_absent_is_noop(self):
        p = self._project([Note(60, 0, 0, 1)])
        self.assertIs(actions.clear_part(p, 3), p)

    def test_clear_part_validates(self):
        with self.assertRaises(ValueError):
            actions.clear_part(new_project(), 4)

    def test_reverse_mirrors_time(self):
        p = self._project([Note(60, 0, 0, 4), Note(64, 28, 0, 4)])  # 32 steps
        rev = actions.reverse_phrase(p)
        placed = sorted((n.step, n.pitch) for _, n in active_notes(rev.phrase))
        self.assertEqual(placed, [(0, 64), (28, 60)])

    def test_reverse_twice_restores(self):
        p = actions.generate_phrase(actions.set_seed(new_project(), 5))
        self.assertEqual(actions.reverse_phrase(actions.reverse_phrase(p)).phrase,
                         p.phrase)

    def test_reverse_empty_is_noop(self):
        p = new_project()
        self.assertIs(actions.reverse_phrase(p), p)


class TestGenerate(unittest.TestCase):
    def test_deterministic(self):
        p = actions.set_seed(new_project(), 77)
        a = actions.generate_phrase(p)
        b = actions.generate_phrase(p)
        self.assertEqual(a.phrase, b.phrase)
        self.assertGreater(count_notes(a.phrase), 0)

    def test_seed_changes_result(self):
        p = new_project()
        a = actions.generate_phrase(actions.set_seed(p, 1))
        b = actions.generate_phrase(actions.set_seed(p, 2))
        self.assertNotEqual(a.phrase, b.phrase)

    def test_notes_fit_grid(self):
        p = actions.generate_phrase(actions.set_beats(new_project(), 5))
        steps = steps_of(p)
        for _, note in active_notes(p.phrase):
            self.assertLess(note.step, steps)
            self.assertLessEqual(note.step + note.dur, steps)

    def test_progression_changes_result(self):
        """カスタム進行を設定すると自動作成の結果が変わる。"""
        p = actions.set_seed(new_project(), 7)
        default = actions.generate_phrase(p)
        custom = actions.generate_phrase(actions.set_progression(p, (2, 2, 2, 2)))
        self.assertNotEqual(default.phrase, custom.phrase)


class TestPatterns(unittest.TestCase):
    def setUp(self):
        p, _ = actions.place_note(new_project(), 60, 0, 0)
        self.p = p

    def test_save_pattern(self):
        p = actions.save_pattern(self.p, 2)
        self.assertTrue(p.patterns[2].used)
        self.assertEqual(p.patterns[2].notes, p.phrase)
        with self.assertRaises(ValueError):
            actions.save_pattern(self.p, 8)

    def test_load_pattern(self):
        p = actions.save_pattern(self.p, 0)
        p = actions.clear_phrase(p)
        p = actions.load_pattern(p, 0)
        self.assertEqual(p.phrase, self.p.phrase)

    def test_load_unused_is_noop(self):
        self.assertIs(actions.load_pattern(self.p, 3), self.p)

    def test_delete_pattern_clears_song_refs(self):
        p = actions.save_pattern(self.p, 0)
        p = actions.save_pattern(p, 1)
        p = actions.toggle_song_cell(p, 0, 0, 0)
        p = actions.toggle_song_cell(p, 1, 2, 1)
        p = actions.delete_pattern(p, 0)
        self.assertFalse(p.patterns[0].used)
        self.assertEqual(get_cell(p.song, 0, 0), EMPTY_CELL)
        self.assertEqual(get_cell(p.song, 1, 2), 1)  # 他パターンは残る

    def test_delete_unused_is_noop(self):
        self.assertIs(actions.delete_pattern(self.p, 5), self.p)

    def test_free_pattern_slot(self):
        self.assertEqual(actions.free_pattern_slot(self.p), 0)
        p = actions.save_pattern(self.p, 0)
        self.assertEqual(actions.free_pattern_slot(p), 1)
        for i in range(8):
            p = actions.save_pattern(p, i)
        self.assertEqual(actions.free_pattern_slot(p), -1)

    def test_save_defaults_to_empty_name(self):
        p = actions.save_pattern(self.p, 0)
        self.assertEqual(p.patterns[0].name, "")

    def test_rename_pattern(self):
        p = actions.save_pattern(self.p, 0)
        p = actions.rename_pattern(p, 0, "  Aメロ  ")   # 前後空白は落とす
        self.assertEqual(p.patterns[0].name, "Aメロ")
        self.assertEqual(p.patterns[0].notes, self.p.phrase)  # 音符は不変

    def test_rename_unused_is_noop(self):
        self.assertIs(actions.rename_pattern(self.p, 3, "x"), self.p)

    def test_rename_same_is_noop(self):
        p = actions.rename_pattern(actions.save_pattern(self.p, 0), 0, "Solo")
        self.assertIs(actions.rename_pattern(p, 0, "Solo"), p)

    def test_rename_clamps_length(self):
        p = actions.save_pattern(self.p, 0)
        p = actions.rename_pattern(p, 0, "x" * 100)
        from picoseq.core.constants import PATTERN_NAME_MAX
        self.assertEqual(len(p.patterns[0].name), PATTERN_NAME_MAX)

    def test_save_preserves_existing_name(self):
        """名前付きスロットへ上書き保存しても名前は消えない。"""
        p = actions.rename_pattern(actions.save_pattern(self.p, 0), 0, "Verse")
        p2, _ = actions.place_note(p, 64, 4, 0)
        p2 = actions.save_pattern(p2, 0)  # name 未指定 → 既存名を保持
        self.assertEqual(p2.patterns[0].name, "Verse")

    def test_duplicate_pattern(self):
        p = actions.rename_pattern(actions.save_pattern(self.p, 0), 0, "Riff")
        p, dest = actions.duplicate_pattern(p, 0)
        self.assertEqual(dest, 1)
        self.assertTrue(p.patterns[1].used)
        self.assertEqual(p.patterns[1].notes, p.patterns[0].notes)
        self.assertEqual(p.patterns[1].name, "Riff 2")

    def test_duplicate_unused_returns_minus_one(self):
        _, dest = actions.duplicate_pattern(self.p, 3)
        self.assertEqual(dest, -1)

    def test_duplicate_full_returns_minus_one(self):
        p = self.p
        for i in range(8):
            p = actions.save_pattern(p, i)
        p2, dest = actions.duplicate_pattern(p, 0)
        self.assertEqual(dest, -1)
        self.assertIs(p2, p)

    def test_generate_song_names_patterns(self):
        p = actions.generate_song(actions.set_seed(new_project(), 42))
        self.assertEqual([p.patterns[i].name for i in range(4)],
                         ["Intro", "A", "B", "Outro"])


class TestSongEdit(unittest.TestCase):
    def setUp(self):
        self.p = actions.save_pattern(new_project(), 0)

    def test_toggle_cell(self):
        p = actions.toggle_song_cell(self.p, 0, 0, 0)
        self.assertEqual(get_cell(p.song, 0, 0), 0)
        p = actions.toggle_song_cell(p, 0, 0, 0)
        self.assertEqual(get_cell(p.song, 0, 0), EMPTY_CELL)

    def test_toggle_unused_pattern_is_noop(self):
        self.assertIs(actions.toggle_song_cell(self.p, 0, 0, 7), self.p)

    def test_toggle_bounds(self):
        with self.assertRaises(ValueError):
            actions.toggle_song_cell(self.p, 4, 0, 0)
        with self.assertRaises(ValueError):
            actions.toggle_song_cell(self.p, 0, 16, 0)

    def test_erase_cell(self):
        p = actions.toggle_song_cell(self.p, 2, 3, 0)
        p = actions.erase_song_cell(p, 2, 3)
        self.assertEqual(get_cell(p.song, 2, 3), EMPTY_CELL)
        self.assertIs(actions.erase_song_cell(p, 2, 3), p)

    def test_clear_song(self):
        p = actions.toggle_song_cell(self.p, 0, 0, 0)
        p = actions.clear_song(p)
        self.assertEqual(p.song, EMPTY_SONG)
        self.assertIs(actions.clear_song(p), p)


if __name__ == "__main__":
    unittest.main()
