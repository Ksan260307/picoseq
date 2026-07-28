"""デモ用の中身づくり (`--demo`) — スクリーンショットと動作確認のため。

環境変数で開くタブや状態を選べる。製品の動作には関わらないので、
アプリ本体 (app.py) からは切り離してある。

  PICOSEQ_DEMO_TAB    song / pattern / dj のいずれかを開く
  PICOSEQ_DEMO_PHOTO  そのパスの写真でフォト音階ダイアログを開く
  PICOSEQ_DEMO_SOUND  音色セットを指定して開く
  PICOSEQ_DEMO_HELP   ヘルプを開いた状態にする
  PICOSEQ_DEMO_MUTE / PICOSEQ_DEMO_LAYERMUTE  消音の見た目を確認する
  PICOSEQ_DEMO_DETACH ピアノロールを切り離した状態にする
"""

import os

from ..core import actions
from ..core import dj as dj_core
from ..core.history import History
from . import theme
from .photo import PhotoDialog, analyze_photo


def load_demo(app):
    """デモ用に一曲ぶんの中身を入れる (スクリーンショット・体験用)。"""
    _fill_song(app)
    _apply_env(app)


def _fill_song(app):
    """2 パターン (通常・ボス戦) を作り、ソング構成へ並べる。"""
    app.project = actions.set_seed(app.project, 42)
    app.project = actions.generate_phrase(app.project)
    app.project = actions.save_pattern(app.project, 0)
    app.project = actions.set_scale(app.project, "battle")
    app.project = actions.set_seed(app.project, 7)
    app.project = actions.generate_phrase(app.project)
    app.project = actions.save_pattern(app.project, 1)
    # 長い名前 (マス目での省略表示の確認用)
    app.project = actions.rename_pattern(app.project, 0, "メインリフレイン")
    app.project = actions.rename_pattern(app.project, 1, "サビ")
    app.project = actions.load_pattern(app.project, 0)
    for track, block, pid in [(0, 0, 0), (0, 1, 0), (0, 2, 1), (0, 3, 1),
                              (1, 0, 0), (1, 2, 1), (3, 1, 1)]:
        app.project = actions.toggle_song_cell(app.project, track, block, pid)
    app.selected_pattern = 0
    app.history = History()
    app.refresh_all()


def _apply_env(app):
    """環境変数で指定された「見せたい状態」を適用する。"""
    tab = os.environ.get("PICOSEQ_DEMO_TAB")
    if tab in ("song", "pattern", "dj"):
        app.switch_tab(tab)
        if tab == "dj":
            _setup_dj(app)
    photo_path = os.environ.get("PICOSEQ_DEMO_PHOTO")
    if photo_path:
        def open_photo():
            grid, quads, photo = analyze_photo(photo_path)
            if quads:
                PhotoDialog(app, grid, quads, photo)
        app.root.after(400, open_photo)
    demo_sound = os.environ.get("PICOSEQ_DEMO_SOUND")
    if demo_sound in theme.SOUND_IDS:
        app.project = actions.set_sound(app.project, demo_sound)
        app._apply_theme(demo_sound)
    if os.environ.get("PICOSEQ_DEMO_HELP"):
        app.root.after(400, app.show_help)
    if os.environ.get("PICOSEQ_DEMO_MUTE"):
        app.toggle_mute(2)  # リズムを消音 (見た目確認用)
    if os.environ.get("PICOSEQ_DEMO_LAYERMUTE"):
        app.select_part(0)
        app.add_layer_action()          # メロディに 2 層目
        app.toggle_layer_mute(0, 1)     # 2 層目だけ消音 (レイヤーバー確認用)
    if os.environ.get("PICOSEQ_DEMO_DETACH"):
        app.root.after(500, app.roll_panel.detach)


def _setup_dj(app):
    """DJ 画面を「使い込んだ状態」にする (履歴・お気に入り・回転位置)。"""
    app.dj_set_noise(0, 2)
    app.dj_set_part_tone(0, 3, 80)           # サブの音色を変えて見た目確認
    app.dj_set_part_gate(0, 3, 40)
    app.dj_view._focus_part(0, 3)            # サブを選択した状態で開く
    app.dj_view.update_spin("a", True, 0.8)  # 見た目確認用に回転位置をずらす
    for i, (scale, key, bpm) in enumerate(   # 履歴・お気に入りの見た目確認用
            (("major", 0, 120), ("battle", 7, 150), ("minor", 3, 96),
             ("dorian", 5, 128), ("majpent", 9, 110), ("blues", 2, 88))):
        app.dj_history.append(dj_core.make_entry(scale, key, bpm, "retro8",
                                                 0, 100 + i, deck=i % 2))
    app.dj_favorites = app.dj_history[1:3]
    app._refresh_dj_log()
