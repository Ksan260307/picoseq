"""PicoSeq モバイル版 — 同じ作曲エンジンを使う Kivy 製の軽量シェル。

デスクトップ版 (tkinter) はスマホでは動かないため、スマホには
この画面を Buildozer で APK にして届ける。曲のデータと音の合成は
picoseq.core をそのまま使うので、同じシード値なら同じ曲が鳴る。

機能: 自動作成 / ソング自動作成 / 音色・曲調・シード値の変更 / ループ再生。
"""

import os
import random
import threading

from kivy.app import App
from kivy.clock import Clock
from kivy.core.audio import SoundLoader
from kivy.graphics import Color, Rectangle
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import get_color_from_hex

from picoseq.core import actions
from picoseq.core.constants import SEED_MAX, SEED_MIN, SOUND_SETS
from picoseq.core.music import SCALE_IDS, SCALES
from picoseq.core.phrase import active_notes
from picoseq.core.project import new_project, steps_of
from picoseq.core.renderer import render_phrase_loop, render_song_loop
from picoseq.core.song import used_blocks
from picoseq.core.wavio import wav_bytes
from picoseq.ui.theme import PALETTES, SOUND_LABELS

PART_COLORS = ("#8fd177", "#68b9c9", "#e08a8a", "#d9b45a")
PITCH_MIN, PITCH_MAX = 36, 84


class RollPreview(Widget):
    """フレーズを色付きの四角で表示する簡易ピアノロール (表示のみ)。"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.project = None
        self.palette = PALETTES["retro8"]
        self.bind(size=lambda *a: self.redraw(), pos=lambda *a: self.redraw())

    def show(self, project):
        self.project = project
        self.palette = PALETTES[project.sound]
        self.redraw()

    def redraw(self):
        self.canvas.clear()
        if self.project is None or self.width < 10:
            return
        steps = steps_of(self.project)
        cell_w = self.width / steps
        cell_h = self.height / (PITCH_MAX - PITCH_MIN + 1)
        with self.canvas:
            Color(*get_color_from_hex(self.palette["GRID_BG"]))
            Rectangle(pos=self.pos, size=self.size)
            for _, note in active_notes(self.project.phrase):
                if note.step >= steps:
                    continue
                Color(*get_color_from_hex(PART_COLORS[note.wave]))
                x = self.x + note.step * cell_w
                y = self.y + (note.pitch - PITCH_MIN) * cell_h
                Rectangle(pos=(x + 1, y), size=(note.dur * cell_w - 2, cell_h * 0.9))


class PicoSeqMobile(App):
    title = "PicoSeq"

    def build(self):
        self.project = actions.generate_phrase(new_project())
        self.busy = False
        self.sound_obj = None

        root = BoxLayout(orientation="vertical", padding=12, spacing=8)

        self.status = Label(text="✨ 自動作成 を押してみましょう", size_hint_y=0.08)
        root.add_widget(self.status)

        self.preview = RollPreview(size_hint_y=0.44)
        root.add_widget(self.preview)

        row1 = BoxLayout(size_hint_y=0.12, spacing=8)
        row1.add_widget(self._button("✨ 自動作成", self.generate))
        row1.add_widget(self._button("🎼 ソング自動作成", self.generate_song))
        self.play_btn = self._button("▶ 再生", self.toggle_play)
        row1.add_widget(self.play_btn)
        root.add_widget(row1)

        row2 = BoxLayout(size_hint_y=0.12, spacing=8)
        self.sound_spin = Spinner(
            text=SOUND_LABELS[self.project.sound],
            values=[SOUND_LABELS[s] for s in SOUND_SETS])
        self.sound_spin.bind(text=self.on_sound)
        row2.add_widget(self.sound_spin)
        self.scale_spin = Spinner(
            text=SCALES[self.project.scale]["label"],
            values=[SCALES[s]["label"] for s in SCALE_IDS])
        self.scale_spin.bind(text=self.on_scale)
        row2.add_widget(self.scale_spin)
        root.add_widget(row2)

        row3 = BoxLayout(size_hint_y=0.12, spacing=8)
        row3.add_widget(Label(text="シード値", size_hint_x=0.3))
        self.seed_input = TextInput(text=str(self.project.seed),
                                    input_filter="int", multiline=False)
        row3.add_widget(self.seed_input)
        row3.add_widget(self._button("この値で再現", self.replay_seed))
        root.add_widget(row3)

        self.preview.show(self.project)
        self._apply_palette()
        return root

    def _button(self, text, handler):
        button = Button(text=text)
        button.bind(on_release=lambda *a: handler())
        return button

    def _apply_palette(self):
        from kivy.core.window import Window
        Window.clearcolor = get_color_from_hex(PALETTES[self.project.sound]["BG"])

    # ---- 操作 ----

    def generate(self):
        seed = random.randint(SEED_MIN, SEED_MAX)
        self.project = actions.generate_phrase(actions.set_seed(self.project, seed))
        self.seed_input.text = str(seed)
        self.preview.show(self.project)
        self.status.text = f"シード値 {seed} で作成しました"
        self._restart_if_playing()

    def replay_seed(self):
        try:
            seed = int(self.seed_input.text or "1")
        except ValueError:
            seed = 1
        self.project = actions.generate_phrase(actions.set_seed(self.project, seed))
        self.preview.show(self.project)
        self.status.text = f"シード値 {self.project.seed} の曲を再現しました"
        self._restart_if_playing()

    def generate_song(self):
        seed = random.randint(SEED_MIN, SEED_MAX)
        self.project = actions.generate_song(actions.set_seed(self.project, seed))
        self.seed_input.text = str(seed)
        self.preview.show(self.project)
        self.status.text = f"シード値 {seed} で 1 曲作りました (再生はソング全体)"
        self._restart_if_playing()

    def on_sound(self, _spinner, text):
        for sound, label in SOUND_LABELS.items():
            if label == text:
                self.project = actions.set_sound(self.project, sound)
        self._apply_palette()
        self.preview.show(self.project)
        self._restart_if_playing()

    def on_scale(self, _spinner, text):
        for scale_id in SCALE_IDS:
            if SCALES[scale_id]["label"] == text:
                self.project = actions.set_scale(self.project, scale_id)
        self.status.text = "曲調を変えました。✨ でもう一度作成してみましょう"

    # ---- 再生 ----

    def toggle_play(self):
        if self.sound_obj is not None:
            self.stop()
            return
        self.start()

    def start(self):
        if self.busy:
            return
        self.busy = True
        self.status.text = "曲を準備中…"
        project = self.project

        def work():
            if used_blocks(project.song) > 0:
                pcm = render_song_loop(project)
            else:
                pcm = render_phrase_loop(project)
            path = os.path.join(self.user_data_dir, "play.wav")
            with open(path, "wb") as f:
                f.write(wav_bytes(pcm))
            Clock.schedule_once(lambda dt: self._play_file(path))

        threading.Thread(target=work, daemon=True).start()

    def _play_file(self, path):
        self.busy = False
        self.sound_obj = SoundLoader.load(path)
        if self.sound_obj is None:
            self.status.text = "再生できませんでした"
            return
        self.sound_obj.loop = True
        self.sound_obj.play()
        self.play_btn.text = "■ 停止"
        self.status.text = "ループ再生中"

    def stop(self):
        if self.sound_obj is not None:
            self.sound_obj.stop()
            self.sound_obj = None
        self.play_btn.text = "▶ 再生"
        self.status.text = "停止しました"

    def _restart_if_playing(self):
        if self.sound_obj is not None:
            self.stop()
            self.start()


if __name__ == "__main__":
    PicoSeqMobile().run()
