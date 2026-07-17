"""自動伴奏のテスト — メロディ検出・進行推定・伴奏生成の決定論と整合。"""

import unittest

from picoseq.core import actions
from picoseq.core.arranger import (
    arrange,
    has_only_melody,
    infer_progression,
    melody_notes,
)
from picoseq.core.constants import (
    WAVE_NOISE,
    WAVE_PULSE,
    WAVE_SAW,
    WAVE_TRIANGLE,
)
from picoseq.core.music import SCALES
from picoseq.core.note import Note
from picoseq.core.phrase import active_notes, build_phrase, count_notes
from picoseq.core.project import new_project, update


def _melody_project(scale="major", key=0, notes=None):
    if notes is None:
        notes = [Note(72, 0, WAVE_PULSE, 2), Note(76, 4, WAVE_PULSE, 2),
                 Note(74, 8, WAVE_PULSE, 2), Note(77, 12, WAVE_PULSE, 2),
                 Note(72, 16, WAVE_PULSE, 2), Note(79, 20, WAVE_PULSE, 2),
                 Note(76, 24, WAVE_PULSE, 2), Note(72, 28, WAVE_PULSE, 4)]
    p = new_project()
    p = actions.set_scale(p, scale)
    p = actions.set_key(p, key)
    return update(p, phrase=build_phrase(notes))


class TestMelodyDetection(unittest.TestCase):
    def test_has_only_melody_true(self):
        self.assertTrue(has_only_melody(_melody_project()))

    def test_has_only_melody_false_when_empty(self):
        self.assertFalse(has_only_melody(new_project()))

    def test_has_only_melody_false_with_other_parts(self):
        p = _melody_project()
        p, _ = actions.place_note(p, 48, 0, WAVE_TRIANGLE)
        self.assertFalse(has_only_melody(p))

    def test_melody_notes_only_pulse(self):
        p = _melody_project()
        p, _ = actions.place_note(p, 48, 0, WAVE_TRIANGLE)
        notes = melody_notes(p)
        self.assertTrue(all(n.wave == WAVE_PULSE for n in notes))
        self.assertEqual(len(notes), 8)


class TestInference(unittest.TestCase):
    def test_progression_length_and_range(self):
        for scale in SCALES:
            for beats in (2, 3, 4, 5, 7):
                p = _melody_project(scale=scale)
                p = actions.set_beats(p, beats)
                prog = infer_progression(p)
                n = len(SCALES[scale]["intervals"])
                self.assertEqual(len(prog), 4)
                for degree in prog:
                    self.assertTrue(0 <= degree < n)

    def test_tonic_melody_infers_tonic_chord(self):
        # すべて C (メジャーの根音) のメロディ → 各窓とも度数 0 (C コード)
        notes = [Note(72, s, WAVE_PULSE, 2) for s in range(0, 32, 4)]
        p = _melody_project(scale="major", notes=notes)
        self.assertEqual(infer_progression(p), (0, 0, 0, 0))

    def test_deterministic(self):
        p = _melody_project()
        self.assertEqual(infer_progression(p), infer_progression(p))


class TestArrange(unittest.TestCase):
    def test_adds_all_parts(self):
        buffer, prog = arrange(_melody_project())
        waves = {n.wave for _, n in active_notes(buffer)}
        self.assertEqual(waves, {WAVE_PULSE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW})
        self.assertIsNotNone(prog)

    def test_melody_preserved(self):
        p = _melody_project()
        original = melody_notes(p)
        buffer, _ = arrange(p)
        arranged_melody = [n for _, n in active_notes(buffer) if n.wave == WAVE_PULSE]
        self.assertEqual(sorted(original), sorted(arranged_melody))

    def test_empty_returns_unchanged(self):
        p = new_project()
        buffer, prog = arrange(p)
        self.assertEqual(buffer, p.phrase)
        self.assertIsNone(prog)

    def test_deterministic(self):
        p = _melody_project()
        self.assertEqual(arrange(p), arrange(p))

    def test_seed_changes_accompaniment(self):
        p1 = actions.set_seed(_melody_project(), 1)
        p2 = actions.set_seed(_melody_project(), 2)
        self.assertNotEqual(arrange(p1)[0], arrange(p2)[0])


class TestArrangeAction(unittest.TestCase):
    def test_records_progression(self):
        p = actions.arrange_accompaniment(_melody_project())
        self.assertIsNotNone(p.progression)
        waves = {n.wave for _, n in active_notes(p.phrase)}
        self.assertEqual(waves, {WAVE_PULSE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW})

    def test_noop_without_melody(self):
        p = new_project()
        self.assertIs(actions.arrange_accompaniment(p), p)

    def test_regenerate_matches_progression(self):
        """伴奏づけ後の進行で再度自動作成しても、その進行が使われる (再現性)。"""
        p = actions.arrange_accompaniment(_melody_project())
        prog = p.progression
        regenerated = actions.generate_phrase(p)
        self.assertEqual(regenerated.progression, prog)


if __name__ == "__main__":
    unittest.main()
