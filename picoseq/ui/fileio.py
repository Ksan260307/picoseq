"""保存・読込・書き出し — ファイルに触れる操作をまとめた層。

`PicoSeqApp` が継承する。保存先の決定 (ダイアログ) と、書き出しの中身
(直列化・レンダリング) の呼び分けだけを持ち、形式そのものは core 側にある。
"""

from pathlib import Path
from tkinter import filedialog

from ..core.constants import SAMPLE_RATE
from ..core.history import History
from ..core.midiio import phrase_midi, song_midi
from ..core.phrase import count_notes
from ..core.renderer import render_phrase, render_song
from ..core.serialize import LoadError, dumps, loads
from ..core.song import used_blocks
from ..core.wavio import wav_bytes
from . import storage
from .i18n import t


class FileIOMixin:
    """プロジェクトの保存・読込と、WAV / MIDI の書き出し。"""

    def do_save(self):
        """既定の保存先へ上書き保存する。"""
        storage.save_text(self.autosave_file, dumps(self.project))
        self.saved_snapshot = dumps(self.project)
        self._set_dirty(False)
        self.set_status(t("st_saved", path=self.autosave_file))

    def do_load(self):
        """既定の保存先から読み込む。"""
        text = storage.load_text(self.autosave_file)
        if text is None:
            self.set_status(t("st_no_savedata"))
            return
        self._load_text(text, t("st_loaded_from", path=self.autosave_file))

    def do_export(self):
        """場所を選んでプロジェクトを書き出す。"""
        path = self._ask_save_path(t("dlg_export_project"), "picoseq_project.json",
                                   [(t("ft_project"), "*.json")])
        if not path:
            return
        storage.save_text(Path(path), dumps(self.project))
        self.set_status(t("st_exported", path=path))

    def do_import(self):
        """場所を選んでプロジェクトを取り込む。"""
        path = None if self.silent else filedialog.askopenfilename(
            title=t("dlg_import_project"),
            filetypes=[(t("ft_project_json"), "*.json"), (t("ft_all"), "*.*")])
        if not path:
            return
        text = storage.load_text(Path(path))
        if text is None:
            self.alert(t("st_file_unreadable"))
            return
        self._load_text(text, t("st_imported_from", path=path))

    def _load_text(self, text, ok_message):
        """JSON 文字列を今のプロジェクトへ差し替える (確認つき)。"""
        try:
            project = loads(text)
        except LoadError as error:
            self.alert(str(error))
            return
        if not self.confirm(t("ttl_load"), t("st_replace_q")):
            return
        self.stop_playback()
        self.project = project
        self.history = History()
        self.saved_snapshot = dumps(project)
        self.selected_pattern = next(
            (i for i, p in enumerate(project.patterns) if p.used), -1)
        if not self._ensure_theme():  # 別の音色で保存したデータなら配色も合わせる
            self.refresh_all()
        self._set_dirty(False)
        self.set_status(ok_message)

    def do_export_wav(self, mode):
        """フレーズ／ソングを WAV に書き出す (合成は裏で回す)。"""
        project = self.project
        if not self._export_ready(mode):
            return
        name = "picoseq_song.wav" if mode == "song" else "picoseq_phrase.wav"
        path = self._ask_save_path(t("dlg_export_wav"), name,
                                   [(t("ft_wav"), "*.wav")])
        if not path:
            return
        self.set_status(t("st_exporting_wav"))
        mute = self.mute_pairs()

        def work():
            pcm = (render_song(project, mute=mute) if mode == "song"
                   else render_phrase(project, mute=mute))
            return wav_bytes(pcm)

        def done(wav):
            Path(path).write_bytes(wav)
            seconds = (len(wav) - 44) / 2 / SAMPLE_RATE
            self.set_status(t("st_wav_exported", path=path, sec=f"{seconds:.1f}"))

        self._run_bg(work, done)

    def do_export_midi(self, mode):
        """フレーズ／ソングを MIDI ファイルとして書き出す (DAW や楽譜ソフト用)。"""
        project = self.project
        if not self._export_ready(mode):
            return
        name = "picoseq_song.mid" if mode == "song" else "picoseq_phrase.mid"
        path = self._ask_save_path(t("dlg_export_midi"), name,
                                   [(t("ft_midi"), "*.mid")])
        if not path:
            return
        data = song_midi(project) if mode == "song" else phrase_midi(project)
        Path(path).write_bytes(data)
        self.set_status(t("st_midi_exported", path=path))

    def _export_ready(self, mode) -> bool:
        """書き出す中身があるか。無ければ案内を出して False。"""
        if mode == "song" and used_blocks(self.project.song) == 0:
            self.alert(t("st_song_empty_export"))
            return False
        if mode == "phrase" and count_notes(self.project.phrase) == 0:
            self.alert(t("st_phrase_empty_export"))
            return False
        return True

    def _ask_save_path(self, title, initial, filetypes):
        """保存先を尋ねる。silent (自己診断) では常に None。"""
        if self.silent:
            return None
        return filedialog.asksaveasfilename(
            title=title, initialfile=initial, defaultextension=filetypes[0][1][1:],
            filetypes=filetypes)
