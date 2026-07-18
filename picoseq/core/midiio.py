"""MIDI 書き出し — 曲を標準 MIDI ファイル (SMF) にする純粋関数。

DAW や楽譜ソフトで開けるように、フレーズ／ソングを 1 トラックの
フォーマット 0 で出力する。パートは MIDI チャンネルで分ける:
  メロディ→ch1(矩形波リード) / ベース→ch2(シンセベース) /
  サブ→ch3(ノコギリリード) / リズム→ch10(ドラム)。

Tick(16分音符) を PPQ 基準の MIDI 時間に変換する。整数演算のみで、
同じ曲からは常に同じバイト列が出る。
"""

import struct

from .constants import WAVE_NOISE, WAVE_PULSE, WAVE_SAW, WAVE_TRIANGLE
from .schedule import phrase_events, phrase_ticks, song_events, song_ticks

PPQ = 96                      # 4分音符あたりの MIDI tick
TICKS_PER_STEP = PPQ // 4     # 16分音符 = 24 MIDI tick

# パート → (チャンネル, 音色番号, 音高補正)。ドラムは ch9(0基点=GMの10ch)。
_CHANNEL = {WAVE_PULSE: 0, WAVE_TRIANGLE: 1, WAVE_SAW: 2, WAVE_NOISE: 9}
_PROGRAM = {WAVE_PULSE: 80, WAVE_TRIANGLE: 38, WAVE_SAW: 81}  # 矩形/シンセベース/ノコギリ
_PITCH_ADJUST = {WAVE_TRIANGLE: -12}  # ベースは再生音と同じく 1 オクターブ下
_VELOCITY = {WAVE_PULSE: 100, WAVE_TRIANGLE: 95, WAVE_SAW: 85, WAVE_NOISE: 110}
DRUM_NOTE = 38                # リズムは GM のスネアに割り当てる


def _vlq(value: int) -> bytes:
    """可変長数値 (MIDI のデルタタイム表現)。"""
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def _tempo_meta(bpm: int) -> bytes:
    """テンポのメタイベント (4分音符あたりのマイクロ秒)。"""
    usec = 60_000_000 // bpm
    return b"\xff\x51\x03" + struct.pack(">I", usec)[1:]


def _clamp_note(pitch: int) -> int:
    return max(0, min(127, pitch))


def midi_bytes(events, bpm: int) -> bytes:
    """イベント列を 16bit... ではなく MIDI ファイルのバイト列にする。"""
    # (絶対tick, 種別 0=消音/1=発音, チャンネル, 音高, 強さ) を集める
    raw = []
    for event in events:
        channel = _CHANNEL[event.wave]
        if event.wave == WAVE_NOISE:
            note = DRUM_NOTE
        else:
            note = _clamp_note(event.pitch + _PITCH_ADJUST.get(event.wave, 0))
        velocity = _VELOCITY[event.wave]
        start = event.tick * TICKS_PER_STEP
        end = (event.tick + event.dur) * TICKS_PER_STEP
        raw.append((start, 1, channel, note, velocity))
        raw.append((end, 0, channel, note, 0))

    # 同一 tick では 消音→発音 の順 (同じ音の連結が切れないように)
    raw.sort(key=lambda e: (e[0], e[1]))

    track = bytearray()
    track += _vlq(0) + _tempo_meta(bpm)
    # 使うチャンネルに音色を割り当てる (発音より前・時刻 0)
    used_waves = {event.wave for event in events}
    for wave in (WAVE_PULSE, WAVE_TRIANGLE, WAVE_SAW):
        if wave in used_waves:
            track += _vlq(0) + bytes([0xC0 | _CHANNEL[wave], _PROGRAM[wave]])

    prev = 0
    for abs_tick, kind, channel, note, velocity in raw:
        track += _vlq(abs_tick - prev)
        prev = abs_tick
        status = (0x90 if kind == 1 else 0x80) | channel
        track += bytes([status, note, velocity])
    track += _vlq(0) + b"\xff\x2f\x00"  # トラック終端

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, PPQ)
    track_chunk = b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    return header + track_chunk


def phrase_midi(project) -> bytes:
    """現在のフレーズを MIDI にする。"""
    return midi_bytes(phrase_events(project), project.bpm)


def song_midi(project) -> bytes:
    """ソング構成全体を MIDI にする。"""
    return midi_bytes(song_events(project), project.bpm)
