"""MIDI 書き出しのテスト — 標準 SMF として読み解いて中身を照合する。"""

import struct
import unittest

from picoseq.core import actions
from picoseq.core.constants import WAVE_NOISE, WAVE_PULSE
from picoseq.core.midiio import (
    DRUM_NOTE,
    PPQ,
    TICKS_PER_STEP,
    midi_bytes,
    phrase_midi,
    song_midi,
    _vlq,
)
from picoseq.core.note import Note
from picoseq.core.phrase import build_phrase
from picoseq.core.project import new_project, update
from picoseq.core.schedule import phrase_events


def parse_smf(data):
    """最小限の SMF パーサ。(ppq, events, tempo_usec) を返す。

    events は (abs_tick, status, data1, data2) の列 (ノート系のみ)。
    """
    assert data[:4] == b"MThd", "MThd がない"
    _, fmt, ntrk, ppq = struct.unpack(">IHHH", data[4:14])
    assert fmt == 0 and ntrk == 1
    assert data[14:18] == b"MTrk", "MTrk がない"
    tlen = struct.unpack(">I", data[18:22])[0]
    track = data[22:22 + tlen]
    assert 22 + tlen == len(data), "トラック長が合わない"

    events = []
    tempo = None
    i = 0
    now = 0
    running = None

    def read_vlq(i):
        value = 0
        while True:
            byte = track[i]
            i += 1
            value = (value << 7) | (byte & 0x7F)
            if not byte & 0x80:
                return value, i

    while i < len(track):
        delta, i = read_vlq(i)
        now += delta
        status = track[i]
        if status == 0xFF:  # メタ
            i += 1
            meta = track[i]
            i += 1
            length, i = read_vlq(i)
            body = track[i:i + length]
            i += length
            if meta == 0x51:
                tempo = int.from_bytes(body, "big")
            continue
        if status & 0x80:
            running = status
            i += 1
        else:
            status = running
        kind = status & 0xF0
        if kind in (0x80, 0x90):
            d1, d2 = track[i], track[i + 1]
            i += 2
            events.append((now, status, d1, d2))
        elif kind == 0xC0:
            i += 1  # プログラムチェンジ (データ 1 バイト)
        else:
            i += 2
    return ppq, events, tempo


def _note_ons(events):
    return [e for e in events if (e[1] & 0xF0) == 0x90 and e[3] > 0]


def _note_offs(events):
    return [e for e in events
            if (e[1] & 0xF0) == 0x80 or ((e[1] & 0xF0) == 0x90 and e[3] == 0)]


class TestVlq(unittest.TestCase):
    def test_small(self):
        self.assertEqual(_vlq(0), b"\x00")
        self.assertEqual(_vlq(127), b"\x7f")

    def test_multibyte(self):
        self.assertEqual(_vlq(128), b"\x81\x00")
        self.assertEqual(_vlq(192), b"\x81\x40")
        self.assertEqual(_vlq(8192), b"\xc0\x00")


class TestStructure(unittest.TestCase):
    def _project(self, seed=42):
        return actions.generate_phrase(actions.set_seed(new_project(), seed))

    def test_valid_header_and_ppq(self):
        ppq, events, tempo = parse_smf(phrase_midi(self._project()))
        self.assertEqual(ppq, PPQ)

    def test_note_counts_match_events(self):
        for seed in (1, 42, 123, 500):
            with self.subTest(seed=seed):
                project = self._project(seed)
                _, events, _ = parse_smf(phrase_midi(project))
                source = len(phrase_events(project))
                self.assertEqual(len(_note_ons(events)), source)
                self.assertEqual(len(_note_offs(events)), source)

    def test_tempo_matches_bpm(self):
        for bpm in (60, 120, 180, 240):
            with self.subTest(bpm=bpm):
                project = actions.set_bpm(self._project(), bpm)
                _, _, tempo = parse_smf(phrase_midi(project))
                self.assertEqual(round(60_000_000 / tempo), bpm)

    def test_deterministic(self):
        project = self._project()
        self.assertEqual(phrase_midi(project), phrase_midi(project))

    def test_empty_is_valid_minimal_file(self):
        data = midi_bytes([], 120)
        ppq, events, tempo = parse_smf(data)
        self.assertEqual(events, [])
        self.assertEqual(round(60_000_000 / tempo), 120)


class TestMapping(unittest.TestCase):
    def test_drums_on_channel_10(self):
        notes = [Note(60, 0, WAVE_NOISE, 1)]
        project = update(new_project(), phrase=build_phrase(notes))
        _, events, _ = parse_smf(phrase_midi(project))
        ons = _note_ons(events)
        self.assertEqual(len(ons), 1)
        status, note = ons[0][1], ons[0][2]
        self.assertEqual(status & 0x0F, 9)   # MIDI ch10 (0 基点で 9)
        self.assertEqual(note, DRUM_NOTE)

    def test_note_timing(self):
        notes = [Note(60, 2, WAVE_PULSE, 3)]  # step2 から 3 ステップ
        project = update(new_project(), phrase=build_phrase(notes))
        _, events, _ = parse_smf(phrase_midi(project))
        on = _note_ons(events)[0]
        off = _note_offs(events)[0]
        self.assertEqual(on[0], 2 * TICKS_PER_STEP)
        self.assertEqual(off[0], (2 + 3) * TICKS_PER_STEP)

    def test_melody_pitch_preserved(self):
        notes = [Note(67, 0, WAVE_PULSE, 1)]
        project = update(new_project(), phrase=build_phrase(notes))
        _, events, _ = parse_smf(phrase_midi(project))
        self.assertEqual(_note_ons(events)[0][2], 67)


class TestSong(unittest.TestCase):
    def test_song_midi_valid(self):
        p = actions.generate_phrase(actions.set_seed(new_project(), 42))
        p = actions.save_pattern(p, 0)
        p = actions.toggle_song_cell(p, 0, 0, 0)
        p = actions.toggle_song_cell(p, 0, 1, 0)
        ppq, events, tempo = parse_smf(song_midi(p))
        self.assertEqual(ppq, PPQ)
        self.assertTrue(_note_ons(events))


if __name__ == "__main__":
    unittest.main()
