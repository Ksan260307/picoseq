"""表示言語 — 日本語／英語の切替。

観測層 (UI) だけの関心事。確定状態 (Project) は言語に一切依存しない。
`t(key, **fmt)` で訳語を引く。未定義キーはキー名をそのまま返す (開発時の気づき用)。
"""

LANGS = ("ja", "en")
LANG_LABELS = {"ja": "日本語", "en": "English"}

_lang = "ja"


def get_lang() -> str:
    return _lang


def set_lang(lang: str):
    global _lang
    if lang in LANGS:
        _lang = lang


def t(key: str, **fmt) -> str:
    """訳語を引く。fmt があれば str.format で埋め込む。"""
    entry = STRINGS.get(key)
    if entry is None:
        return key.format(**fmt) if fmt else key
    text = entry.get(_lang) or entry.get("ja") or key
    return text.format(**fmt) if fmt else text


# パート名・波形名・音色名は観測層の表示物なので言語で切り替える。
PART_NAMES = {
    "ja": ("メロディ", "ベース", "リズム", "サブ"),
    "en": ("Melody", "Bass", "Rhythm", "Sub"),
}
PART_WAVES = {
    "ja": ("パルス波", "三角波", "ノイズ", "ノコギリ波"),
    "en": ("Pulse", "Triangle", "Noise", "Saw"),
}
SOUND_LABELS = {
    "ja": {"retro8": "ピコピコ 8bit", "warm16": "まろやか 16bit", "clear32": "きらめき 32bit"},
    "en": {"retro8": "Chiptune 8-bit", "warm16": "Mellow 16-bit", "clear32": "Crystal 32-bit"},
}


def part_name(index: int) -> str:
    return PART_NAMES[_lang][index]


def part_wave(index: int) -> str:
    return PART_WAVES[_lang][index]


def sound_label(sound_id: str) -> str:
    return SOUND_LABELS[_lang].get(sound_id, sound_id)


def sound_labels() -> dict:
    return SOUND_LABELS[_lang]


def scale_label(scale_id: str, ja_label: str) -> str:
    """曲調ラベル。英語表示なら英訳、無ければ日本語ラベルへフォールバック。"""
    if _lang == "en":
        return SCALE_EN.get(scale_id, ja_label)
    return ja_label


# 曲調の英語ラベル。日本語は music.SCALES[...]["label"] が正典なのでそちらは触らない。
SCALE_EN = {
    "major": "Bright (Major)",
    "minor": "Wistful (Minor)",
    "dorian": "Bittersweet (Dorian)",
    "mixolydian": "Easygoing (Mixolydian)",
    "lydian": "Dreamy (Lydian)",
    "harmonic": "Eerie (Harmonic minor)",
    "melodic": "Dramatic (Melodic minor)",
    "japanese": "Japanese (Yin scale)",
    "ryukyu": "Tropical (Ryukyu)",
    "pentatonic": "Cheerful (Major penta)",
    "blues": "Bluesy (Blues)",
    "wholetone": "Mysterious (Whole tone)",
    "battle": "Boss battle (Intense)",
    "phrygian": "Melancholy (Phrygian)",
    "locrian": "Unstable (Locrian)",
    "dorian_b2": "Exotic (Dorian b2)",
    "lydian_aug": "Floating (Lydian #5)",
    "lydian_dom": "Futuristic (Lydian dom)",
    "mixo_b6": "Dusky (Mixo b6)",
    "locrian_n2": "Twilight (Half-dim)",
    "altered": "Edgy (Altered)",
    "locrian_n6": "Gloaming (Locrian 6)",
    "ionian_s5": "Solemn (Ionian #5)",
    "dorian_s4": "Gypsy (Ukrainian minor)",
    "lydian_s2": "Fantasy (Lydian #2)",
    "ultralocrian": "Chaotic (Ultralocrian)",
    "harmonic_major": "Noble (Harmonic major)",
    "double_harmonic": "Arabian (Double harmonic)",
    "hungarian_minor": "Fiery minor (Hungarian)",
    "hungarian_major": "Fiery major (Hungarian)",
    "neapolitan_minor": "Neapolitan minor",
    "neapolitan_major": "Neapolitan major",
    "enigmatic": "Enigmatic",
    "persian": "Persian",
    "oriental": "Oriental",
    "marva": "Daybreak (Marva)",
    "todi": "Meditative (Todi)",
    "purvi": "Dusk (Purvi)",
    "leading_whole_tone": "Foreboding (Leading whole tone)",
    "kishimi": "Creaking (Altered minor)",
    "lydian_minor": "Daydream (Lydian minor)",
    "major_locrian": "Collapse (Major Locrian)",
    "minor_penta": "Mellow (Minor penta)",
    "egyptian": "Desert (Egyptian)",
    "man_gong": "Nocturne (Man Gong)",
    "insen": "In-sen",
    "iwato": "Austere (Iwato)",
    "kumoi": "Elegant (Kumoi)",
    "chinese": "Chinese",
    "pelog": "Gamelan (Pelog)",
    "dominant_penta": "Sunlit (Dominant penta)",
    "hon_kumoi": "Serene (Hon-Kumoi)",
    "yo": "Rustic (Yo scale)",
    "bali": "Prayer (Bali)",
    "major_blues": "Cheery blues",
    "augmented": "Sparkling (Augmented)",
    "prometheus": "Mystic (Prometheus)",
    "tritone": "Duality (Tritone)",
    "istrian": "Folk (Istrian)",
    "scriabin": "Theosophy (Scriabin)",
    "dim_wh": "Ominous (Diminished)",
    "dim_hw": "Thrilling (Combined dim)",
    "bebop_dom": "Jazz (Bebop)",
    "bebop_major": "Swing (Bebop major)",
    "spanish8": "Spanish (8-tone)",
    "photo": "Photo scale",
}


# ---- UI 文字列 ----

STRINGS = {
    # 窓・共通
    "title": {"ja": "PicoSeq — レトロピコピコ・シーケンサー v2",
              "en": "PicoSeq — Retro Chiptune Sequencer v2"},
    "unsaved_prefix": {"ja": "● 未保存  ", "en": "● Unsaved  "},
    # ヘッダー
    "tab_phrase": {"ja": "🎵 フレーズ", "en": "🎵 Phrase"},
    "tab_song": {"ja": "🧩 ソング", "en": "🧩 Song"},
    "lbl_sound": {"ja": "音色", "en": "Sound"},
    "lbl_tempo": {"ja": "テンポ", "en": "Tempo"},
    "lbl_lang": {"ja": "言語", "en": "Lang"},
    "btn_help": {"ja": "❓ ヘルプ", "en": "❓ Help"},
    "btn_import": {"ja": "⬆ 取込", "en": "⬆ Import"},
    "btn_export": {"ja": "⬇ 書出", "en": "⬇ Export"},
    "btn_load": {"ja": "📂 読込", "en": "📂 Load"},
    "btn_save": {"ja": "💾 保存", "en": "💾 Save"},
    # フレーズ操作バー
    "btn_play": {"ja": "▶ 再生", "en": "▶ Play"},
    "btn_stop": {"ja": "■ 停止", "en": "■ Stop"},
    "btn_preparing": {"ja": "⏳ 準備中…", "en": "⏳ Preparing…"},
    "lbl_beats": {"ja": "拍子", "en": "Beats"},
    "lbl_key": {"ja": "キー", "en": "Key"},
    "lbl_scale": {"ja": "曲調", "en": "Mood"},
    "lbl_seed": {"ja": "シード値", "en": "Seed"},
    "btn_auto": {"ja": "✨ 自動作成", "en": "✨ Auto"},
    "btn_surprise": {"ja": "🎲 サプライズ", "en": "🎲 Surprise"},
    "btn_hum": {"ja": "🎤 鼻歌から", "en": "🎤 From humming"},
    "btn_photo": {"ja": "📷 写真から", "en": "📷 From photo"},
    "btn_arrange": {"ja": "🎸 伴奏づけ", "en": "🎸 Add backing"},
    # パート・スライダーバー
    "lbl_part": {"ja": "パート", "en": "Part"},
    "lbl_tone": {"ja": "音色", "en": "Tone"},
    "lbl_gate": {"ja": "長さ", "en": "Length"},
    "btn_reverse": {"ja": "🔄 反転", "en": "🔄 Reverse"},
    "btn_register": {"ja": "★ 登録", "en": "★ Save pat."},
    "btn_clear": {"ja": "🗑 クリア", "en": "🗑 Clear"},
    "btn_midi": {"ja": "🎹 MIDI", "en": "🎹 MIDI"},
    "btn_wav": {"ja": "🎧 WAV", "en": "🎧 WAV"},
    # レイヤーバー
    "lbl_layers_of": {"ja": "{part} のレイヤー", "en": "{part} layers"},
    "btn_add_layer": {"ja": "＋ 追加", "en": "＋ Add"},
    "btn_remove_layer": {"ja": "✕ {n} を削除", "en": "✕ Delete {n}"},
    # ソングタブ
    "btn_play_song": {"ja": "▶ ソング再生", "en": "▶ Play song"},
    "btn_song_auto": {"ja": "✨ ソング自動作成", "en": "✨ Auto song"},
    "btn_clear_song": {"ja": "🗑 構成クリア", "en": "🗑 Clear song"},
    "btn_wav_song": {"ja": "🎵 WAV書出", "en": "🎵 Export WAV"},
    "btn_midi_song": {"ja": "🎹 MIDI書出", "en": "🎹 Export MIDI"},
    "lbl_pattern": {"ja": "パターン", "en": "Pattern"},
    "btn_delete": {"ja": "🗑 削除", "en": "🗑 Delete"},
    "btn_load_to_editor": {"ja": "✏ 編集へ読込", "en": "✏ Load to editor"},
    # ヒント (ステータスバー既定)
    "hint_phrase": {
        "ja": "左クリック: 置く / そのまま右へドラッグ: 伸ばす / 音符クリックか右クリック: 消す / 左端の鍵盤: 試聴",
        "en": "Left-click: place / drag right: lengthen / click note or right-click: erase / left keys: preview"},
    "hint_song": {
        "ja": "パレットでフレーズを選び、マスをクリックして配置。同じマスをもう一度で消去。",
        "en": "Pick a phrase from the palette and click a cell to place it. Click again to erase."},
    # カウンタ・セル
    "counts": {
        "ja": "音符 {notes}/{max} ・ パターン {used}/{pats} ・ ブロック {blocks}/16{extra}",
        "en": "Notes {notes}/{max} · Patterns {used}/{pats} · Blocks {blocks}/16{extra}"},
    "counts_extra_photo": {"ja": " ・ 進行: フォト", "en": " · Prog: photo"},
    "cell_hint": {"ja": "{note} ・ {measure}小節 {beat}拍",
                  "en": "{note} · bar {measure} beat {beat}"},
    # 再生位置
    "position": {"ja": "▶ {measure} : {beat}", "en": "▶ {measure} : {beat}"},
    "live_reflect": {"ja": "♻ リアルタイム反映", "en": "♻ Live update"},
    # ステータス・メッセージ
    "st_no_undo": {"ja": "戻れる操作がありません。", "en": "Nothing to undo."},
    "st_no_redo": {"ja": "やり直せる操作がありません。", "en": "Nothing to redo."},
    "st_undone": {"ja": "元に戻しました。", "en": "Undone."},
    "st_redone": {"ja": "やり直しました。", "en": "Redone."},
    "st_layer_max": {"ja": "レイヤーは最大 {max} 個までです。", "en": "Up to {max} layers."},
    "st_layer_added": {
        "ja": "「{part}」にレイヤー {n} を追加しました。✨ 自動作成でこの層にも音が入ります。",
        "en": "Added layer {n} to \"{part}\". ✨ Auto will fill this layer too."},
    "st_layer_removed": {"ja": "レイヤー {n} を削除しました (↩ で戻せます)。",
                         "en": "Removed layer {n} (↩ to undo)."},
    "st_notes_full": {"ja": "音符が一杯です (最大 {max})。", "en": "Note buffer full (max {max})."},
    "st_clear_phrase_q": {"ja": "現在のフレーズをすべて消しますか?", "en": "Erase the entire current phrase?"},
    "ttl_clear": {"ja": "クリア", "en": "Clear"},
    "st_phrase_cleared": {"ja": "フレーズを消しました (↩ で戻せます)。", "en": "Phrase cleared (↩ to undo)."},
    "st_part_empty": {"ja": "「{part}」には音がありません。", "en": "\"{part}\" has no notes."},
    "st_part_cleared": {"ja": "「{part}」パートを消しました (↩ で戻せます)。",
                        "en": "Cleared the \"{part}\" part (↩ to undo)."},
    "st_no_transpose": {"ja": "移調できませんでした (これ以上は音域の外です)。",
                        "en": "Cannot transpose further (out of range)."},
    "st_transposed_up": {"ja": "1 オクターブ上げました。", "en": "Raised one octave."},
    "st_transposed_down": {"ja": "1 オクターブ下げました。", "en": "Lowered one octave."},
    "st_no_reverse": {"ja": "反転する音がありません。", "en": "No notes to reverse."},
    "st_reversed": {"ja": "フレーズを時間反転しました (もう一度押すと戻ります)。",
                    "en": "Phrase reversed in time (press again to restore)."},
    "st_auto_made": {"ja": "シード値 {seed} で作成 (コード進行 {prog})。気に入ったら ★ 登録!",
                     "en": "Made with seed {seed} (progression {prog}). Like it? ★ Save pat.!"},
    "st_seed_reproduced": {"ja": "シード値 {seed} の曲を再現 (コード進行 {prog})。",
                           "en": "Reproduced seed {seed} (progression {prog})."},
    "st_surprise": {"ja": "🎲 「{scale}」×「{sound}」×シード値 {seed} (コード進行 {prog})！",
                    "en": "🎲 \"{scale}\" × \"{sound}\" × seed {seed} (progression {prog})!"},
    "st_no_melody": {
        "ja": "メロディがありません。メロディ (パート1) を置いてから「🎸 伴奏づけ」を押してください。",
        "en": "No melody. Place a melody (part 1), then press \"🎸 Add backing\"."},
    "ttl_arrange": {"ja": "伴奏づけ", "en": "Add backing"},
    "st_arrange_q": {"ja": "メロディ以外のパートは作り直されます。続けますか?",
                     "en": "Non-melody parts will be regenerated. Continue?"},
    "st_arranged": {"ja": "メロディに合わせて伴奏を付けました。曲調・シードを変えると雰囲気が変わります。",
                    "en": "Added backing to your melody. Change mood/seed for a different feel."},
    "st_hum_placed": {"ja": "鼻歌から {n} 音のメロディを置きました。「🎸 伴奏づけ」で伴奏も付けられます。",
                      "en": "Placed a {n}-note melody from your humming. Try \"🎸 Add backing\" too."},
    "dlg_pick_photo": {"ja": "写真を選ぶ", "en": "Choose a photo"},
    "ft_image": {"ja": "画像", "en": "Image"},
    "ft_all": {"ja": "すべて", "en": "All files"},
    "st_analyzing_photo": {"ja": "写真を解析中…", "en": "Analyzing photo…"},
    "st_no_quads": {
        "ja": "四角形が見つかりませんでした。\n被写体 (紙・カードなど) と背景の明暗差をはっきりさせてください。",
        "en": "No rectangles found.\nMake the subject (paper, card, etc.) contrast clearly with the background."},
    "st_quads_found": {"ja": "四角形を {n} 個検出しました。内容を確認してください。",
                       "en": "Detected {n} rectangle(s). Please review."},
    "st_photo_composed": {"ja": "写真の音階で作曲しました。曲調に「📷 フォト音階」が追加されています。",
                          "en": "Composed with the photo scale. \"📷 Photo scale\" was added to Mood."},
    "st_photo_added": {"ja": "曲調に「📷 フォト音階」を追加しました。この音だけで作曲してみましょう。",
                       "en": "Added \"📷 Photo scale\" to Mood. Try composing with just these notes."},
    "photo_scale_label": {"ja": "📷 フォト音階", "en": "📷 Photo scale"},
    "st_pat_full": {"ja": "パターンが一杯です (最大 8 個)。ソング画面で不要なものを削除してください。",
                    "en": "Patterns full (max 8). Delete unused ones on the Song screen."},
    "st_pat_saved": {"ja": "パターン F{n} に登録しました。ソング画面で配置できます。",
                     "en": "Saved to pattern F{n}. Place it on the Song screen."},
    "st_pat_selected": {"ja": "F{n} を選択中。マスをクリックで配置。",
                        "en": "F{n} selected. Click a cell to place."},
    "st_pick_pattern": {"ja": "先にパターンを選んでください。", "en": "Select a pattern first."},
    "ttl_load": {"ja": "読込", "en": "Load"},
    "st_load_pat_q": {"ja": "編集中のフレーズを F{n} で置き換えますか?",
                      "en": "Replace the current phrase with F{n}?"},
    "st_pat_loaded": {"ja": "F{n} を編集画面へ読み込みました。", "en": "Loaded F{n} into the editor."},
    "ttl_delete": {"ja": "削除", "en": "Delete"},
    "st_delete_pat_q": {"ja": "パターン F{n} を削除しますか?\nソング構成からも取り除かれます。",
                        "en": "Delete pattern F{n}?\nIt will also be removed from the song."},
    "st_pick_pattern_first": {"ja": "先に上のパレットからパターンを選んでください。",
                              "en": "First pick a pattern from the palette above."},
    "ttl_song_auto": {"ja": "ソング自動作成", "en": "Auto song"},
    "st_song_auto_q": {"ja": "パターン 1〜4 とソング構成を作り直します。続けますか?\n(パターン 5〜8 は残ります)",
                       "en": "Patterns 1-4 and the song will be rebuilt. Continue?\n(Patterns 5-8 are kept)"},
    "st_song_made": {"ja": "シード値 {seed} で 1 曲作りました。イントロ→Aメロ→Bメロ→アウトロの構成です。▶ で聴いてみましょう。",
                     "en": "Made a full song with seed {seed}. Intro→A→B→Outro. Press ▶ to listen."},
    "st_clear_song_q": {"ja": "ソング構成をすべて消しますか?\n(パターン自体は残ります)",
                        "en": "Clear the whole song?\n(The patterns themselves are kept)"},
    "st_song_empty": {"ja": "ソングが空です。パレットからフレーズを配置してください。",
                      "en": "Song is empty. Place phrases from the palette."},
    "st_phrase_empty": {"ja": "フレーズが空です。音符を置くか ✨ 自動作成 を試してください。",
                        "en": "Phrase is empty. Place notes or try ✨ Auto."},
    "st_looping": {"ja": "ループ再生中。編集するとリアルタイムで反映されます。Space か ■ で停止。",
                   "en": "Looping. Edits apply live. Space or ■ to stop."},
    "st_stopped_empty": {"ja": "盤面が空になったので停止しました。", "en": "Stopped: the board became empty."},
    "st_saved": {"ja": "保存しました → {path}", "en": "Saved → {path}"},
    "st_no_savedata": {"ja": "保存データがまだありません。", "en": "No saved data yet."},
    "st_loaded_from": {"ja": "読み込みました ← {path}", "en": "Loaded ← {path}"},
    "dlg_export_project": {"ja": "プロジェクトを書き出す", "en": "Export project"},
    "ft_project": {"ja": "PicoSeq プロジェクト", "en": "PicoSeq project"},
    "st_exported": {"ja": "書き出しました → {path}", "en": "Exported → {path}"},
    "dlg_import_project": {"ja": "プロジェクトを取り込む", "en": "Import project"},
    "ft_project_json": {"ja": "プロジェクト JSON (旧版も可)", "en": "Project JSON (legacy ok)"},
    "st_file_unreadable": {"ja": "ファイルを読めませんでした。", "en": "Could not read the file."},
    "st_imported_from": {"ja": "取り込みました ← {path}", "en": "Imported ← {path}"},
    "st_replace_q": {"ja": "現在の内容を置き換えます。よろしいですか?", "en": "This replaces the current content. OK?"},
    "st_song_empty_export": {"ja": "ソングが空です。先にフレーズを配置してください。",
                             "en": "Song is empty. Place phrases first."},
    "st_phrase_empty_export": {"ja": "フレーズが空です。", "en": "Phrase is empty."},
    "dlg_export_wav": {"ja": "WAV を書き出す", "en": "Export WAV"},
    "ft_wav": {"ja": "WAV 音声", "en": "WAV audio"},
    "st_exporting_wav": {"ja": "WAV を書き出し中…", "en": "Exporting WAV…"},
    "st_wav_exported": {"ja": "書き出しました → {path} ({sec} 秒)", "en": "Exported → {path} ({sec} s)"},
    "dlg_export_midi": {"ja": "MIDI を書き出す", "en": "Export MIDI"},
    "ft_midi": {"ja": "MIDI ファイル", "en": "MIDI file"},
    "st_midi_exported": {"ja": "MIDI を書き出しました → {path}", "en": "Exported MIDI → {path}"},
    "st_error": {"ja": "エラー: {msg}", "en": "Error: {msg}"},
    "st_close_save_q": {"ja": "終了する前に保存しますか?", "en": "Save before quitting?"},
    "ttl_beats_change": {"ja": "拍子の変更", "en": "Change beats"},
    "st_beats_change_q": {"ja": "拍子を変えるとソング構成はリセットされます。続けますか?",
                          "en": "Changing beats resets the song. Continue?"},
    "st_sound_changed": {"ja": "音色を「{label}」に変えました。背景も衣替えしています。",
                         "en": "Switched sound to \"{label}\". The theme changed to match."},
    "st_lang_changed": {"ja": "表示を日本語にしました。", "en": "Switched display to English."},
    # 鼻歌ダイアログ
    "hum_title": {"ja": "鼻歌からメロディを作る", "en": "Make a melody from humming"},
    "hum_head": {"ja": "🎤 鼻歌からメロディを作る", "en": "🎤 Make a melody from humming"},
    "hum_intro": {
        "ja": "「ラララ〜」と口ずさんだ声の高さを読み取って、\nいま選んでいるキー・曲調の音に合わせたメロディにします。",
        "en": "Reads the pitch of your humming and snaps it\nto the current key and mood."},
    "hum_ready": {"ja": "録音するか、録音済みの WAV ファイルを選んでください。",
                  "en": "Record, or choose a recorded WAV file."},
    "hum_record": {"ja": "● 録音する ({sec}秒)", "en": "● Record ({sec}s)"},
    "hum_open_wav": {"ja": "📁 WAV を開く", "en": "📁 Open WAV"},
    "hum_make": {"ja": "♪ メロディにする", "en": "♪ Make melody"},
    "hum_close": {"ja": "閉じる", "en": "Close"},
    "hum_no_mic": {"ja": "この環境ではマイク録音できません。WAV ファイルを使ってください。",
                   "en": "Mic recording isn't available here. Please use a WAV file."},
    "hum_recording_btn": {"ja": "● 録音中… 歌ってください!", "en": "● Recording… sing!"},
    "hum_recording": {"ja": "録音中です ({sec} 秒間)。マイクに向かって歌ってください。",
                      "en": "Recording ({sec} s). Sing into the mic."},
    "hum_open_title": {"ja": "鼻歌の WAV を開く", "en": "Open humming WAV"},
    "hum_analyzing_file": {"ja": "ファイルを解析中…", "en": "Analyzing file…"},
    "hum_analyzing_pitch": {"ja": "声の高さを解析中…", "en": "Analyzing pitch…"},
    "hum_not_heard": {"ja": "メロディを聞き取れませんでした。\nもう少し大きな声で、ゆっくり歌ってみてください。",
                      "en": "Couldn't hear a melody.\nTry singing a bit louder and slower."},
    "hum_heard": {"ja": "{n} 個の音を聞き取りました。「♪ メロディにする」で盤面に置きます。",
                  "en": "Heard {n} notes. Press \"♪ Make melody\" to place them."},
    "hum_err_16bit": {"ja": "16bit の WAV のみ対応しています。", "en": "Only 16-bit WAV is supported."},
    "hum_err_channels": {"ja": "モノラルかステレオの WAV のみ対応しています。",
                         "en": "Only mono or stereo WAV is supported."},
    # フォト音階ダイアログ
    "photo_title": {"ja": "フォト音階 — 写真から音階を取り込む",
                    "en": "Photo scale — import a scale from a photo"},
    "photo_gen": {"ja": "♪ この音階で自動作成", "en": "♪ Auto with this scale"},
    "photo_only": {"ja": "🎼 音階だけ取り込む", "en": "🎼 Import scale only"},
    "photo_close": {"ja": "閉じる", "en": "Close"},
    # ミュート
    "st_muted": {"ja": "「{part}」を消音しました (再生・WAV に反映)。",
                 "en": "Muted \"{part}\" (applies to playback & WAV)."},
    "st_unmuted": {"ja": "「{part}」の消音を解除しました。", "en": "Unmuted \"{part}\"."},
    "st_layer_muted": {"ja": "「{part}」レイヤー {n} を消音しました。",
                       "en": "Muted \"{part}\" layer {n}."},
    "st_layer_unmuted": {"ja": "「{part}」レイヤー {n} の消音を解除しました。",
                         "en": "Unmuted \"{part}\" layer {n}."},
    "lbl_mute": {"ja": "消音", "en": "Mute"},
    # ズーム (盤面の拡大・縮小)
    "lbl_zoom": {"ja": "表示", "en": "Zoom"},
    "zoom_reset": {"ja": "拡大・縮小をリセットしました。", "en": "Zoom reset."},
    # パネル (切り離し / 再ドック)
    "panel_detach": {"ja": "⧉ 切り離し", "en": "⧉ Detach"},
    "panel_redock": {"ja": "⧈ 戻す", "en": "⧈ Dock"},
    "panel_transport": {"ja": "操作", "en": "Controls"},
    "panel_roll": {"ja": "ピアノロール", "en": "Piano roll"},
    "panel_song": {"ja": "ソング構成", "en": "Song"},
    "panel_mixer": {"ja": "パート / ミキサー", "en": "Parts / Mixer"},
    # パターン編集タブ
    "tab_pattern": {"ja": "🗂 パターン", "en": "🗂 Patterns"},
    "panel_pattern": {"ja": "パターン編集", "en": "Pattern editor"},
    "hint_pattern": {
        "ja": "パターン (最大 8) を管理します。編集で盤面へ読込・名称変更・複製・削除・試聴ができます。",
        "en": "Manage patterns (up to 8): edit loads it onto the board, plus rename, duplicate, delete, preview."},
    "pat_save_new": {"ja": "＋ 現在のフレーズを保存", "en": "＋ Save current phrase"},
    "pat_empty": {"ja": "(空き)", "en": "(empty)"},
    "pat_unnamed": {"ja": "(名称なし)", "en": "(unnamed)"},
    "pat_notes": {"ja": "♪ {n}", "en": "♪ {n}"},
    "pat_edit": {"ja": "✏ 編集", "en": "✏ Edit"},
    "pat_rename": {"ja": "🏷 名称", "en": "🏷 Rename"},
    "pat_dup": {"ja": "⧉ 複製", "en": "⧉ Duplicate"},
    "pat_del": {"ja": "🗑 削除", "en": "🗑 Delete"},
    "pat_play": {"ja": "▶ 試聴", "en": "▶ Play"},
    "pat_save_here": {"ja": "＋ ここへ保存", "en": "＋ Save here"},
    "dlg_rename_title": {"ja": "パターン名の変更", "en": "Rename pattern"},
    "dlg_rename_prompt": {"ja": "パターン名", "en": "Pattern name"},
    "ok": {"ja": "OK", "en": "OK"},
    "cancel": {"ja": "キャンセル", "en": "Cancel"},
    "st_pat_renamed": {"ja": "F{n} を「{name}」にしました。", "en": "Renamed F{n} to \"{name}\"."},
    "st_pat_cleared_name": {"ja": "F{n} の名前を消しました。", "en": "Cleared the name of F{n}."},
    "st_pat_duplicated": {"ja": "F{src} を F{dst} に複製しました。", "en": "Duplicated F{src} to F{dst}."},
    "st_pat_no_room": {"ja": "空きスロットがありません (最大 8 個)。不要なものを削除してください。",
                       "en": "No free slot (max 8). Delete an unused one first."},
    "st_pat_phrase_empty": {"ja": "保存する音符がありません。先にフレーズを作ってください。",
                            "en": "Nothing to save. Make a phrase first."},
    "st_pat_previewing": {"ja": "F{n}「{label}」を試聴中。", "en": "Previewing F{n} \"{label}\"."},
    # ソング画面の改善
    "song_placing": {"ja": "配置中: {label}", "en": "Placing: {label}"},
    "song_placing_none": {"ja": "配置するパターンを下から選んでください。",
                          "en": "Pick a pattern below to place."},
    "song_block": {"ja": "ブロック", "en": "Block"},
    "song_go_patterns": {"ja": "🗂 パターン管理へ", "en": "🗂 Manage patterns"},
    "song_cell_hint": {"ja": "T{track} ブロック{block}: {label}",
                       "en": "T{track} block {block}: {label}"},
    "song_cell_empty": {"ja": "T{track} ブロック{block}: (空き)",
                        "en": "T{track} block {block}: (empty)"},
    "btn_preview": {"ja": "▶ 試聴", "en": "▶ Preview"},
    "st_preview_pick": {"ja": "試聴するパターンを下のパレットから選んでください。",
                        "en": "Pick a pattern below to preview."},
    "palette_hint": {"ja": "F{n}: {label}", "en": "F{n}: {label}"},
    # DJ モード
    "tab_dj": {"ja": "🎧 DJ", "en": "🎧 DJ"},
    "hint_dj": {
        "ja": "DJ モード: ▶ で回すと 8 小節ごとに次のフレーズへ自動で進み続けます。ディスクをドラッグでスクラッチ、🔁 で固定、KILL やノイズで盛り上げよう。",
        "en": "DJ mode: press ▶ and it keeps advancing to a new phrase every 8 bars. Drag a disc to scratch, 🔁 to hold, build energy with KILL and noise."},
    "dj_deck": {"ja": "デッキ {deck}", "en": "Deck {deck}"},
    "dj_seed": {"ja": "シード {seed}", "en": "Seed {seed}"},
    "dj_roll": {"ja": "🎲 生成", "en": "🎲 Roll"},
    "dj_mood": {"ja": "🎼 曲調", "en": "🎼 Mood"},
    "dj_mood_label": {"ja": "曲調", "en": "Mood"},
    "dj_play": {"ja": "▶ 回す", "en": "▶ Spin"},
    "dj_stop": {"ja": "■ 停止", "en": "■ Stop"},
    "dj_crossfade": {"ja": "クロスフェーダー", "en": "Crossfader"},
    "dj_tempo": {"ja": "テンポ", "en": "Tempo"},
    "dj_tap": {"ja": "タップ", "en": "Tap"},
    "dj_noise": {"ja": "ノイズ", "en": "Noise"},
    "dj_filter": {"ja": "フィルター", "en": "Filter"},
    "dj_hold": {"ja": "ループ固定", "en": "Hold loop"},
    "dj_kill": {"ja": "KILL (消音)", "en": "KILL (mute)"},
    "st_dj_rolled": {"ja": "デッキ {deck} を シード {seed} で生成。", "en": "Rolled deck {deck} with seed {seed}."},
    "st_dj_mood": {"ja": "デッキ {deck} の曲調を「{mood}」に。", "en": "Deck {deck} mood → \"{mood}\"."},
    "st_dj_switch": {"ja": "デッキ {deck} に切り替えました。", "en": "Switched to deck {deck}."},
    "st_dj_hold_on": {"ja": "ループ固定 ON — 現在のフレーズを繰り返します。",
                      "en": "Hold ON — looping the current phrase."},
    "st_dj_hold_off": {"ja": "ループ固定 OFF — 8 小節ごとに次のフレーズへ進みます。",
                       "en": "Hold OFF — advancing to a new phrase every 8 bars."},
    "st_dj_noise": {"ja": "ノイズ量を {level} にしました。", "en": "Noise level set to {level}."},
}
