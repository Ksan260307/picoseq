"""パターンとソング構成の操作 — 保存したフレーズを並べて 1 曲にする層。

`PicoSeqApp` が継承する。パターン編集タブ (一覧・名前・複製・削除) と、
ソング画面のマス目操作をまとめて持つ。状態の変更はすべて core.actions 経由。
"""

import random
import tkinter as tk

from ..core import actions
from ..core.constants import EMPTY_CELL, PATTERN_COUNT, SEED_MAX, SEED_MIN
from ..core.phrase import count_notes
from ..core.renderer import render_phrase
from ..core.song import used_blocks
from . import theme
from .i18n import t


class PatternsMixin:
    """パターンの管理と、ソング構成への配置。"""

    # ---- パターン共通 ----

    def pattern_label(self, slot: int) -> str:
        """パターンの表示名。名前があればそれ、無ければ F 番号。"""
        pattern = self.project.patterns[slot]
        return pattern.name if pattern.name else f"F{slot + 1}"

    def save_current_pattern(self):
        """フレーズ画面の ★登録 — 空きスロットへ現在のフレーズを保存する。"""
        slot = actions.free_pattern_slot(self.project)
        if slot == -1:
            self.alert(t("st_pat_no_room"))
            return
        self.commit(actions.save_pattern(self.project, slot))
        self.selected_pattern = slot
        self.set_status(t("st_pat_saved", n=slot + 1))

    def select_pattern(self, slot):
        """パレットでパターンを選ぶ (マス目に置く対象になる)。"""
        if self.project.patterns[slot].used:
            self.selected_pattern = slot
            self._update_palette()
            self._update_placing()
            self.song_view.redraw_cells()  # 選択パターンのセル強調を更新

    # ---- パターン編集タブ ----

    def _rebuild_pattern_list(self):
        """パターン一覧を作り直す。"""
        if not hasattr(self, "pattern_list"):
            return
        for child in self.pattern_list.winfo_children():
            child.destroy()
        for slot in range(PATTERN_COUNT):
            self._pattern_row(slot)

    def _pattern_row(self, slot):
        """一覧の 1 行 (使用中なら操作ボタン、空きなら保存ボタン)。"""
        pattern = self.project.patterns[slot]
        row = tk.Frame(self.pattern_list, bg=theme.PANEL)
        row.pack(fill="x", pady=2)
        color = theme.PATTERN_COLORS[slot % len(theme.PATTERN_COLORS)]
        tk.Label(row, text=f"F{slot + 1}", font=theme.FONT_BOLD, width=4,
                 bg=color if pattern.used else theme.BTN_BG,
                 fg=theme.KEY_TEXT if pattern.used else theme.TEXT_DIM
                 ).pack(side="left", padx=(0, 8), ipady=2)
        if pattern.used:
            self._pattern_row_filled(row, slot, pattern)
        else:
            tk.Label(row, text=t("pat_empty"), font=theme.FONT, bg=theme.PANEL,
                     fg=theme.TEXT_DIM, anchor="w", width=24).pack(side="left")
            self._button(row, t("pat_save_here"),
                         lambda s=slot: self.save_pattern_here(s)
                         ).pack(side="right", padx=2)

    def _pattern_row_filled(self, row, slot, pattern):
        """使用中スロットの行 — 名前・音数と、コンパクトな操作ボタン。"""
        name = pattern.name or t("pat_unnamed")
        tk.Label(row, text=name, font=theme.FONT_BOLD, bg=theme.PANEL,
                 fg=theme.TEXT if pattern.name else theme.TEXT_DIM,
                 anchor="w", width=18).pack(side="left")
        tk.Label(row, text=t("pat_notes", n=count_notes(pattern.notes)),
                 font=theme.FONT_SMALL, bg=theme.PANEL, fg=theme.TEXT_DIM,
                 width=6, anchor="w").pack(side="left", padx=(6, 10))
        # アイコン中心のボタンで行幅を抑える (右詰めなので逆順に並べる)
        self._row_button(row, "🗑", t("pat_del"),
                         lambda s=slot: self.delete_pattern_slot(s), danger=True)
        self._row_button(row, "⧉", t("pat_dup"),
                         lambda s=slot: self.duplicate_pattern_action(s))
        self._row_button(row, "🏷", t("pat_rename"),
                         lambda s=slot: self.rename_pattern_action(s))
        self._row_button(row, "▶", t("pat_play"),
                         lambda s=slot: self.play_pattern(s))
        self._row_button(row, t("pat_edit"), t("pat_edit"),
                         lambda s=slot: self.edit_pattern(s), accent=True)

    def _row_button(self, parent, label, tip, command, accent=False, danger=False):
        """パターン行用の小さめボタン (右詰め)。label は文字/絵文字。"""
        fg = theme.ACCENT if accent else (theme.DANGER if danger else theme.TEXT)
        btn = tk.Button(parent, text=label, command=command,
                        font=theme.FONT_BOLD if accent else theme.FONT,
                        bg=theme.BTN_BG, fg=fg, activebackground=theme.BTN_ACTIVE,
                        relief="flat", bd=1, padx=6, pady=2, takefocus=0,
                        cursor="hand2")
        btn.pack(side="right", padx=2)
        return btn

    def save_new_pattern(self):
        """空きスロットを探して現在のフレーズを保存する。"""
        slot = actions.free_pattern_slot(self.project)
        if slot == -1:
            self.alert(t("st_pat_no_room"))
            return
        self.save_pattern_here(slot)

    def save_pattern_here(self, slot):
        """指定スロットへ現在のフレーズを保存する。"""
        if count_notes(self.project.phrase) == 0:
            self.alert(t("st_pat_phrase_empty"))
            return
        self.commit(actions.save_pattern(self.project, slot))
        self.selected_pattern = slot
        self._rebuild_pattern_list()
        self.set_status(t("st_pat_saved", n=slot + 1))

    def edit_pattern(self, slot):
        """パターンを盤面へ読み込んでフレーズ画面へ移る。"""
        if not self.project.patterns[slot].used:
            return
        self.commit(actions.load_pattern(self.project, slot))
        self.selected_pattern = slot
        self.switch_tab("phrase")
        self.set_status(t("st_pat_loaded", n=slot + 1))

    def rename_pattern_action(self, slot):
        """パターンに名前を付ける (空文字なら名前なしへ戻す)。"""
        pattern = self.project.patterns[slot]
        if not pattern.used:
            return
        name = self._ask_text(t("dlg_rename_title"), t("dlg_rename_prompt"),
                              pattern.name)
        if name is None:
            return
        new_project = actions.rename_pattern(self.project, slot, name)
        if new_project is self.project:
            return
        self.commit(new_project)
        self._rebuild_pattern_list()
        final = self.project.patterns[slot].name
        if final:
            self.set_status(t("st_pat_renamed", n=slot + 1, name=final))
        else:
            self.set_status(t("st_pat_cleared_name", n=slot + 1))

    def duplicate_pattern_action(self, slot):
        """パターンを空きスロットへ複製する。"""
        new_project, dest = actions.duplicate_pattern(self.project, slot)
        if dest == -1:
            self.alert(t("st_pat_no_room"))
            return
        self.commit(new_project)
        self.selected_pattern = dest
        self._rebuild_pattern_list()
        self.set_status(t("st_pat_duplicated", src=slot + 1, dst=dest + 1))

    def delete_pattern_slot(self, slot):
        """パターンを削除する (確認つき)。"""
        if not self.project.patterns[slot].used:
            return
        if self.confirm(t("ttl_delete"), t("st_delete_pat_q", n=slot + 1)):
            self.commit(actions.delete_pattern(self.project, slot))
            if self.selected_pattern == slot:
                self.selected_pattern = next(
                    (i for i, p in enumerate(self.project.patterns) if p.used), -1)
            self._rebuild_pattern_list()

    def play_pattern(self, slot):
        """パターンを 1 回だけ試聴する (演奏中でも重ねて鳴らす)。"""
        pattern = self.project.patterns[slot]
        if not pattern.used or self.silent:
            return
        if self.play_mode and not self.stream_ok:
            return                       # 重ねられない環境では演奏中は試聴しない
        temp = actions.update(self.project, phrase=pattern.notes)
        self._play_oneshot(render_phrase(temp, mute=self.mute_pairs()))
        self.set_status(t("st_pat_previewing", n=slot + 1,
                          label=self.pattern_label(slot)))

    def _ask_text(self, title, prompt, initial=""):
        """1 行テキストを尋ねる小さなダイアログ。OK で文字列、キャンセルで None。"""
        if self.silent:
            return None
        win = tk.Toplevel(self.root)
        win.title(title)
        win.configure(bg=theme.BG)
        win.transient(self.root)
        win.grab_set()
        win.resizable(False, False)
        tk.Label(win, text=prompt, font=theme.FONT, bg=theme.BG, fg=theme.TEXT
                 ).pack(padx=18, pady=(16, 4))
        var = tk.StringVar(value=initial)
        entry = tk.Entry(win, textvariable=var, font=theme.FONT, width=30,
                         bg=theme.BTN_BG, fg=theme.TEXT,
                         insertbackground=theme.TEXT, relief="flat")
        entry.pack(padx=18, pady=4)
        result = {"value": None}

        def ok():
            result["value"] = var.get()
            win.destroy()

        bar = tk.Frame(win, bg=theme.BG)
        bar.pack(pady=(8, 16))
        self._button(bar, t("ok"), ok, accent=True).pack(side="left", padx=6)
        self._button(bar, t("cancel"), win.destroy).pack(side="left", padx=6)
        entry.bind("<Return>", lambda e: ok())
        win.bind("<Escape>", lambda e: win.destroy())
        win.after(10, lambda: (entry.focus_set(), entry.select_range(0, "end")))
        self.root.wait_window(win)
        return result["value"]

    # ---- ソング構成 ----

    def _update_placing(self):
        """「配置中: 名前」の表示を今の選択に合わせる。"""
        if hasattr(self, "placing_var"):
            if self.selected_pattern == -1:
                self.placing_var.set(t("song_placing_none"))
            else:
                self.placing_var.set(
                    t("song_placing",
                      label=self.pattern_label(self.selected_pattern)))

    def song_click(self, track, block):
        """マス目に選択中のパターンを置く (同じものなら外す)。"""
        if self.selected_pattern == -1:
            self.set_status(t("st_pick_pattern_first"))
            return
        self.commit(actions.toggle_song_cell(self.project, track, block,
                                             self.selected_pattern))

    def song_erase(self, track, block):
        """マス目を空にする。"""
        self.commit(actions.erase_song_cell(self.project, track, block))

    def show_song_hint(self, track, block):
        """マス目に触れたら、そこにあるパターン名をステータスに出す。"""
        from ..core.song import get_cell
        pid = get_cell(self.project.song, track, block)
        if pid == EMPTY_CELL:
            self.cell_var.set(t("song_cell_empty", track=track + 1,
                                block=block + 1))
        else:
            self.cell_var.set(t("song_cell_hint", track=track + 1,
                                block=block + 1, label=self.pattern_label(pid)))

    def clear_song_hint(self):
        """マス目の説明を消す。"""
        self.cell_var.set("")

    def _on_palette_hover(self, slot):
        """パレットのボタンに触れたら、その中身の名前を出す (F番号だけでは分かりにくいので)。"""
        if self.project.patterns[slot].used:
            self.cell_var.set(t("palette_hint", n=slot + 1,
                                label=self.pattern_label(slot)))

    def preview_selected_pattern(self):
        """ソング画面で、選択中のパターンをその場で 1 回試聴する。"""
        if self.selected_pattern == -1:
            self.set_status(t("st_preview_pick"))
            return
        self.play_pattern(self.selected_pattern)

    def generate_song_auto(self):
        """1 曲ぶんの自動作成 — 新しいシード値でパターンと構成を丸ごと作る。"""
        touched = (used_blocks(self.project.song) > 0
                   or any(p.used for p in self.project.patterns[:4]))
        if touched and not self.confirm(t("ttl_song_auto"), t("st_song_auto_q")):
            return
        seed = random.randint(SEED_MIN, SEED_MAX)
        p = actions.set_seed(self.project, seed)
        self.commit(actions.generate_song(p), full=True)
        self.selected_pattern = 1  # Aメロを選んでおく
        self._update_palette()
        self.set_status(t("st_song_made", seed=seed))

    def clear_song(self):
        """ソング構成を空にする (確認つき。パターン自体は残る)。"""
        if used_blocks(self.project.song) == 0:
            return
        if self.confirm(t("ttl_clear"), t("st_clear_song_q")):
            self.commit(actions.clear_song(self.project))
