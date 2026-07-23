"""レンダラ — イベント列から PCM を合成する純粋関数。

ミキシングは幅広整数の加算で行い、最後に 1 回だけクリップする。
整数加算は足す順番を変えても結果が変わらないため、常に同じ音になる。

高速化 (結果は不変):
- 音声キャッシュ: 同じ (波形,音高,長さ,音色,ゲート) の音は一度だけ合成して使い回す。
  ソングは同じパターンを何度も鳴らすので効果が大きい。
- numpy があればミックスを配列演算で行う。整数加算なので純 Python と**ビット等価**。
  無ければ純 Python 経路で同じ結果を出す (どこでも動くリファレンス実装)。
"""

from array import array

from .constants import DEFAULT_SOUND, SAMPLE_RATE
from .project import Project
from .schedule import (
    phrase_events,
    phrase_ticks,
    samples_per_tick,
    song_events,
    song_ticks,
)
from .synth import render_voice

try:
    import numpy as _np
except ImportError:  # numpy が無ければ純 Python 経路
    _np = None

TAIL_SECONDS = 1  # 最後の音の余韻ぶん
_VOICE_CACHE_LIMIT = 4096
_voice_cache = {}


def clear_cache():
    """音声キャッシュを空にする (テスト・省メモリ用)。"""
    _voice_cache.clear()


def _cached_voice(wave, pitch, dur_samples, tone, gate, rate, sound):
    """音声を合成またはキャッシュから返す。純粋関数の記憶化。"""
    key = (wave, pitch, dur_samples, tone, gate, rate, sound)
    voice = _voice_cache.get(key)
    if voice is None:
        voice = render_voice(wave, pitch, dur_samples, tone, gate, rate, sound)
        if len(_voice_cache) >= _VOICE_CACHE_LIMIT:
            _voice_cache.clear()
        _voice_cache[key] = voice
    return voice


def render_events(events, bpm: int, parts: tuple, total_ticks: int,
                  rate: int = SAMPLE_RATE, wrap: bool = False,
                  sound: str = DEFAULT_SOUND, mute=()):
    """イベント列をミックスして幅広整数のサンプル列 (list または numpy 配列) を返す。

    wrap=False: 末尾に余韻ぶんの尻尾を付ける (書き出し用)。
    wrap=True : 長さをちょうど total_ticks にし、はみ出す音は先頭へ折り返す
                (ループ再生用。継ぎ目が途切れない)。
    mute      : 消音する (wave, layer) の集合。同じ集合なら結果は決定的。
    """
    if mute:
        events = [e for e in events if (e.wave, e.layer) not in mute]
    if _np is not None:
        return _render_events_numpy(events, bpm, parts, total_ticks, rate, wrap, sound)
    return _render_events_python(events, bpm, parts, total_ticks, rate, wrap, sound)


def _mix_extent(total_ticks, spt, wrap, rate):
    loop_len = total_ticks * spt
    total = loop_len if wrap else loop_len + rate * TAIL_SECONDS
    return loop_len, total


def _layer_params(parts, wave, layer):
    """(wave, layer) の音作りパラメータ。範囲外は最後のレイヤーへ丸める。"""
    layers = parts[wave]
    if layer >= len(layers):
        layer = len(layers) - 1
    return layers[layer]


def _render_events_python(events, bpm, parts, total_ticks, rate, wrap,
                          sound=DEFAULT_SOUND):
    """リファレンス実装 (純 Python)。numpy 経路はこれと完全一致でなければならない。"""
    spt = samples_per_tick(bpm, rate)
    loop_len, total = _mix_extent(total_ticks, spt, wrap, rate)
    mix = [0] * total
    for event in events:
        part = _layer_params(parts, event.wave, event.layer)
        voice = _cached_voice(event.wave, event.pitch, event.dur * spt,
                              part.tone, part.gate, rate, sound)
        start = event.tick * spt
        if wrap:
            for i, value in enumerate(voice):
                mix[(start + i) % loop_len] += value
        else:
            end = min(len(voice), total - start)
            for i in range(end):
                mix[start + i] += voice[i]
    return mix


def _render_events_numpy(events, bpm, parts, total_ticks, rate, wrap,
                         sound=DEFAULT_SOUND):
    """numpy によるミックス。整数加算なので純 Python と同じ結果になる。"""
    spt = samples_per_tick(bpm, rate)
    loop_len, total = _mix_extent(total_ticks, spt, wrap, rate)
    mix = _np.zeros(total, dtype=_np.int64)
    for event in events:
        part = _layer_params(parts, event.wave, event.layer)
        voice = _cached_voice(event.wave, event.pitch, event.dur * spt,
                              part.tone, part.gate, rate, sound)
        if not voice:
            continue
        varr = _np.asarray(voice, dtype=_np.int64)
        start = event.tick * spt
        if wrap:
            _add_wrapped(mix, varr, start, loop_len)
        else:
            end = min(len(varr), total - start)
            if end > 0:
                mix[start:start + end] += varr[:end]
    return mix


def _add_wrapped(mix, varr, start, loop_len):
    """varr を start から加え、loop_len を超える分は先頭へ折り返す。"""
    pos = start % loop_len
    i = 0
    n = len(varr)
    while i < n:
        chunk = min(loop_len - pos, n - i)
        mix[pos:pos + chunk] += varr[i:i + chunk]
        i += chunk
        pos = 0


def clip_to_pcm(mix) -> bytes:
    """幅広整数のサンプル列を 16bit PCM (リトルエンディアン) にする。"""
    if _np is not None and isinstance(mix, _np.ndarray):
        clipped = _np.clip(mix, -32768, 32767).astype("<i2")
        return clipped.tobytes()
    clipped = array("h", (min(32767, max(-32768, v)) for v in mix))
    return clipped.tobytes()


def render_phrase(project: Project, rate: int = SAMPLE_RATE, mute=()) -> bytes:
    """現在のフレーズを 16bit PCM にする。"""
    mix = render_events(phrase_events(project), project.bpm, project.parts,
                        phrase_ticks(project), rate, sound=project.sound, mute=mute)
    return clip_to_pcm(mix)


def render_song(project: Project, rate: int = SAMPLE_RATE, mute=()) -> bytes:
    """ソング構成全体を 16bit PCM にする。"""
    mix = render_events(song_events(project), project.bpm, project.parts,
                        song_ticks(project), rate, sound=project.sound, mute=mute)
    return clip_to_pcm(mix)


def render_phrase_loop(project: Project, rate: int = SAMPLE_RATE, mute=()) -> bytes:
    """ループ再生用のフレーズ PCM (長さちょうど・折り返しミックス)。"""
    mix = render_events(phrase_events(project), project.bpm, project.parts,
                        phrase_ticks(project), rate, wrap=True, sound=project.sound,
                        mute=mute)
    return clip_to_pcm(mix)


def render_song_loop(project: Project, rate: int = SAMPLE_RATE, mute=()) -> bytes:
    """ループ再生用のソング PCM。"""
    mix = render_events(song_events(project), project.bpm, project.parts,
                        song_ticks(project), rate, wrap=True, sound=project.sound,
                        mute=mute)
    return clip_to_pcm(mix)


def render_preview(wave: int, pitch: int, tone: int, gate: int,
                   rate: int = SAMPLE_RATE, sound: str = DEFAULT_SOUND) -> bytes:
    """鍵盤プレビュー用の単音 PCM。"""
    voice = _cached_voice(wave, pitch, rate // 4, tone, gate, rate, sound)
    return clip_to_pcm(voice)
