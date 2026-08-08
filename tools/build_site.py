"""デモサイトの生成 — エンジンで作った曲を「聴けるページ」にする。

PicoSeq は tkinter のデスクトップアプリなのでブラウザでは動かない。
その代わり、**作曲エンジンだけを CI で回して音とピアノロールを書き出し**、
1 枚の HTML にまとめて GitHub Pages へ置く。訪れた人はアプリを入れずに
「シード値からどんな曲が出るのか」を耳で確かめられる。

なぜエンジンだけで成立するか:
  ・core は tkinter に依存しない純粋関数の集まり (画面が無くても動く)
  ・同じシード値からは常に同じ曲が出る → ページの内容も毎回同じ (再現可能)

使い方:
    python tools/build_site.py [出力先]     # 既定は site/
"""

import html
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from picoseq.core import actions                                # noqa: E402
from picoseq.core.composer import (                             # noqa: E402
    BACKING_STYLES, BASS_STYLES, DRUM_STYLES, MELODY_RHYTHMS, MOTIF_MODES,
    chosen_progression,
)
from picoseq.core.constants import (                            # noqa: E402
    PITCH_MAX, PITCH_MIN, WAVE_NOISE, WAVE_PULSE, WAVE_SAW, WAVE_TRIANGLE,
)
from picoseq.core.music import (                                # noqa: E402
    KEY_NAMES, SCALES, note_name, progression_choices, scale_family,
)
from picoseq.core.note import SOFT_GAIN                         # noqa: E402
from picoseq.core.phrase import active_notes, count_notes       # noqa: E402
from picoseq.core.project import new_project, steps_of          # noqa: E402
from picoseq.core.renderer import render_phrase, render_song    # noqa: E402
from picoseq.core.wavio import wav_bytes                        # noqa: E402

# 音は 22.05kHz で書き出す。チップチューンでは違いが分かりにくく、
# ページの重さが半分になる (アプリ内の再生・書き出しは 44.1kHz のまま)。
WEB_RATE = 22050

# ブラウザ版アプリの置き場所。tools/build_web.py が site/app/ に組み立てるので、
# このページからは相対リンクで届く (Pages のサブパス公開でも壊れない)。
APP_PATH = "app/"
REPO_URL = "https://github.com/Ksan260307/picoseq"

PART_COLORS = ("#8fd177", "#68b9c9", "#e08a8a", "#d9b45a")
PART_LABELS = ("メロディ", "ベース", "リズム", "サブ")
WAVE_ORDER = (WAVE_PULSE, WAVE_TRIANGLE, WAVE_NOISE, WAVE_SAW)

# 並べるサンプル。曲調の幅が伝わるように性格の違うものを選び、
# シード値は固定する (ページが毎回同じ内容になる = 再現可能)。
SAMPLES = (
    ("major", 0, 42, 4, "明るいメジャー"),
    ("minor", 9, 7, 4, "物憂げなマイナー"),
    ("battle", 2, 12, 4, "ボス戦"),
    ("japanese", 7, 3, 4, "和風"),
    ("dorian", 5, 21, 4, "ドリアン"),
    ("blues", 0, 55, 4, "ブルース"),
    ("ryukyu", 4, 9, 4, "琉球"),
    ("wholetone", 1, 33, 4, "全音音階"),
    ("pentatonic", 7, 18, 3, "ペンタトニック (3/4)"),
    ("harmonic", 11, 64, 4, "ハーモニックマイナー"),
    ("lydian", 3, 5, 5, "リディアン (5/4)"),
    ("phrygian", 8, 77, 4, "フリジアン"),
)

SONG_SAMPLE = ("major", 0, 2024, 4, "ソング自動作成 (イントロ→A→B→アウトロ)")


# ---- 音とピアノロール ------------------------------------------------------

def make_phrase(scale, key, seed, beats):
    """1 フレーズぶんのプロジェクトを作る (純粋・シード値で決まる)。"""
    project = actions.set_beats(new_project(), beats)
    project = actions.set_scale(project, scale)
    project = actions.set_key(project, key)
    project = actions.set_seed(project, seed)
    return actions.generate_phrase(project)


def make_song(scale, key, seed, beats):
    """1 曲ぶん (パターン 4 つ + 16 ブロック) のプロジェクトを作る。"""
    project = actions.set_beats(new_project(), beats)
    project = actions.set_scale(project, scale)
    project = actions.set_key(project, key)
    project = actions.set_seed(project, seed)
    return actions.generate_song(project)


def roll_svg(project, width=560, height=180):
    """ピアノロールを SVG にする。外部ファイルを使わないので HTML へ直接埋められる。

    音の**強弱**は不透明度で表す (アプリのピアノロールが明るさで表すのと同じ考え方)。
    """
    steps = steps_of(project)
    notes = [n for _, n in active_notes(project.phrase) if n.step < steps]
    pitches = [n.pitch for n in notes if n.wave != WAVE_NOISE]
    low = min(pitches, default=60) - 2
    high = max(pitches, default=72) + 2
    span = max(12, high - low)
    unit_w = width / steps
    unit_h = height / span

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" '
             f'aria-label="ピアノロール" class="roll">']
    parts.append(f'<rect width="{width}" height="{height}" class="roll-bg"/>')
    for step in range(0, steps + 1, 4):        # 拍線 (4 ステップ = 1 拍)
        x = round(step * unit_w, 2)
        bar = step % (project.beats * 4) == 0   # 小節線は濃く
        parts.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{height}" '
                     f'class="{"roll-bar" if bar else "roll-beat"}"/>')
    for wave in WAVE_ORDER:
        color = PART_COLORS[wave]
        for note in notes:
            if note.wave != wave:
                continue
            dur = min(note.dur, steps - note.step)
            x = round(note.step * unit_w, 2)
            w = round(max(1.5, dur * unit_w - 1), 2)
            if wave == WAVE_NOISE:              # リズムは音程を持たないので下端へ
                y = round(height - unit_h * 1.5, 2)
                h = round(unit_h, 2)
            else:
                y = round((high - note.pitch) * unit_h, 2)
                h = round(max(2.0, unit_h - 1), 2)
            opacity = SOFT_GAIN[note.soft] / 100
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
                         f'fill="{color}" opacity="{opacity:.2f}" rx="1"/>')
    parts.append("</svg>")
    return "".join(parts)


def part_counts(project):
    """パートごとの音数 (画面の下に出る内訳と同じ考え方)。"""
    notes = [n for _, n in active_notes(project.phrase)]
    return [sum(1 for n in notes if n.wave == wave) for wave in WAVE_ORDER]


def progression_text(project):
    """使われたコード進行を Am→F→C→G のような文字列にする。"""
    from picoseq.core.music import chord_at
    prog = project.progression or chosen_progression(
        project.scale, project.seed, project.custom_scale)
    names = []
    half = project.beats * 2
    for index in range(len(prog)):
        chord = chord_at(project.key, project.scale, index * half,
                         project.beats, prog, project.custom_scale)
        root = note_name(chord.root)[:-1]        # 音名からオクターブ番号を落とす
        minor = (chord.third - chord.root) % 12 == 3
        names.append(root + ("m" if minor else ""))
    return "→".join(names)


# ---- HTML -----------------------------------------------------------------

def _card(sample_dir, scale, key, seed, beats, label, project, pcm_name, kind):
    """サンプル 1 つぶんのカード。音・ピアノロール・内訳を並べる。"""
    counts = part_counts(project)
    breakdown = " / ".join(f"{name} {n}"
                           for name, n in zip(PART_LABELS, counts))
    meta = (f"{KEY_NAMES[key]}・{beats}/4・{project.bpm} BPM・"
            f"シード値 {seed}")
    return f"""
      <article class="card">
        <h3>{html.escape(label)}</h3>
        <p class="meta">{html.escape(meta)}</p>
        <p class="meta">コード進行 {html.escape(progression_text(project))}</p>
        {roll_svg(project)}
        <audio controls preload="none" src="{sample_dir}/{pcm_name}"></audio>
        <p class="meta">{html.escape(breakdown)}（{kind}・全 {count_notes(project.phrase)} 音）</p>
      </article>"""


def build(out_dir: Path) -> dict:
    """サイトを書き出し、作った内容の要約を返す。"""
    samples = out_dir / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    cards = []
    written = []

    for scale, key, seed, beats, label in SAMPLES:
        project = make_phrase(scale, key, seed, beats)
        name = f"{scale}-{key}-{seed}.wav"
        (samples / name).write_bytes(
            wav_bytes(render_phrase(project, rate=WEB_RATE), rate=WEB_RATE))
        written.append(name)
        cards.append(_card("samples", scale, key, seed, beats, label, project,
                           name, "2 小節"))

    scale, key, seed, beats, label = SONG_SAMPLE
    song = make_song(scale, key, seed, beats)
    song_name = f"song-{scale}-{seed}.wav"
    (samples / song_name).write_bytes(
        wav_bytes(render_song(song, rate=WEB_RATE), rate=WEB_RATE))
    written.append(song_name)
    song_card = _card("samples", scale, key, seed, beats, label, song,
                      song_name, "16 ブロック")

    page = _page(cards, song_card)
    (out_dir / "index.html").write_text(page, encoding="utf-8", newline="\n")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")   # _ 始まりも配信する
    return {"samples": written, "cards": len(cards) + 1, "bytes": len(page)}


def _stats_rows():
    """演奏スタイルの数をコードから読んで表にする (手書きの数字とズレない)。"""
    combos = (BASS_STYLES * BACKING_STYLES * DRUM_STYLES
              * MELODY_RHYTHMS * MOTIF_MODES)
    progressions = sum(len(progression_choices(s)) for s in SCALES
                       if s != "photo")
    families = sorted({scale_family(s) for s in SCALES if s != "photo"})
    return [
        ("曲調", f"{len(SCALES) - 1} 種類"),
        ("コード進行", f"約 {progressions // 1000} 千通り (機能和声から自動生成)"),
        ("リズム", f"{DRUM_STYLES} 種 (骨格 13 × 密度 4 × アクセント 4)"),
        ("ベース", f"{BASS_STYLES} 種 (動き 8 × 刻み 3 × 変化 8 × 音域 2)"),
        ("伴奏", f"{BACKING_STYLES} 種 (取り方 5 × 置き方 4 × 変化 6 × 長さ 5)"),
        ("演奏スタイルの組み合わせ", f"{combos:,} 通り"),
        ("曲調の性格グループ", f"{len(families)} グループ"),
    ]


def _page(cards, song_card) -> str:
    """1 枚もののページ。CSS は埋め込み、外部リソースは一切使わない。"""
    stats = "".join(f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
                    for k, v in _stats_rows())
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PicoSeq — 自動生成デモ</title>
<meta name="description" content="PicoSeq の作曲エンジンが生成したフレーズを、
インストールせずにブラウザで聴けるデモページ。">
<style>
:root {{
  color-scheme: light dark;
  --bg: #f6f7f4; --fg: #23262b; --dim: #5d636e;
  --panel: #ffffff; --edge: #d8dbd5; --accent: #2f7d4f;
  --grid: #eceee8; --line: #dfe2dc;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #14171a; --fg: #e6e9e4; --dim: #9aa2ad;
    --panel: #1c2024; --edge: #2b3137; --accent: #8fd177;
    --grid: #10130f; --line: #262b25;
  }}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; padding: 0 1.2rem 4rem; background: var(--bg); color: var(--fg);
  font: 16px/1.7 system-ui, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif;
}}
main {{ max-width: 62rem; margin: 0 auto; }}
header {{ padding: 3rem 0 1.5rem; }}
h1 {{ margin: 0 0 .3rem; font-size: 2rem; letter-spacing: .02em; }}
h1 span {{ color: var(--accent); }}
.lede {{ color: var(--dim); margin: 0 0 1rem; max-width: 46rem; }}
h2 {{ margin: 2.5rem 0 .5rem; font-size: 1.25rem; }}
h2::before {{ content: "▚ "; color: var(--accent); }}
h3 {{ margin: 0 0 .2rem; font-size: 1rem; }}
.grid {{
  display: grid; gap: 1rem; padding: 0;
  grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr));
}}
.card {{
  background: var(--panel); border: 1px solid var(--edge); border-radius: 6px;
  padding: .9rem 1rem 1rem;
}}
.meta {{ margin: .1rem 0; color: var(--dim); font-size: .82rem; }}
.roll {{
  display: block; width: 100%; height: auto; margin: .6rem 0 .5rem;
  border: 1px solid var(--edge); border-radius: 3px; background: var(--grid);
}}
.roll-bg {{ fill: var(--grid); }}
.roll-beat {{ stroke: var(--line); stroke-width: 1; }}
.roll-bar {{ stroke: var(--edge); stroke-width: 1.5; }}
audio {{ width: 100%; margin: .2rem 0 .3rem; }}
table {{ border-collapse: collapse; width: 100%; max-width: 46rem; }}
th, td {{ text-align: left; padding: .35rem .6rem; border-bottom: 1px solid var(--edge); }}
th {{ color: var(--dim); font-weight: 600; white-space: nowrap; }}
code {{
  background: var(--panel); border: 1px solid var(--edge); border-radius: 3px;
  padding: .1rem .35rem; font-size: .9em;
}}
.note {{
  border-left: 3px solid var(--accent); padding: .1rem 0 .1rem .8rem;
  color: var(--dim); margin: 1rem 0;
}}
footer {{ margin-top: 3rem; color: var(--dim); font-size: .85rem; }}
a {{ color: var(--accent); }}
.cta {{ display: flex; gap: .8rem; align-items: center; flex-wrap: wrap;
  margin: 1.2rem 0 .6rem; }}
.cta .note {{ margin: 0; border: 0; padding: 0; }}
.bigbtn {{
  display: inline-block; background: var(--accent); color: var(--bg);
  border-radius: 4px; padding: .5rem 1.1rem; font-weight: 600;
  text-decoration: none; white-space: nowrap;
}}
.bigbtn:hover {{ filter: brightness(1.1); }}
.legend {{ display: flex; gap: .9rem; flex-wrap: wrap; margin: .3rem 0 0;
  padding: 0; list-style: none; font-size: .82rem; color: var(--dim); }}
.legend i {{ display: inline-block; width: .8rem; height: .8rem; border-radius: 2px;
  margin-right: .3rem; vertical-align: -1px; }}
</style>
</head>
<body>
<main>
<header>
  <h1><span>PicoSeq</span> — 自動生成デモ</h1>
  <p class="lede">
    ファミコン風のピコピコ音楽を作るデスクトップアプリ
    <strong>PicoSeq</strong> の作曲エンジンが生成した曲です。
    アプリを入れずに、ここで鳴らして確かめられます。
  </p>
  <p class="lede">
    どのサンプルも <strong>シード値から決まる</strong>ので、
    アプリで同じ曲調・キー・シード値を入れれば同じ曲が出ます。
    このページ自体も CI がエンジンを回して作っており、
    コードを変えなければ毎回同じ内容になります。
  </p>
  <p class="cta">
    <a class="bigbtn" href="{APP_PATH}">ブラウザでアプリを開く</a>
    <span class="note">インストール不要。自分でシード値を変えて作曲できます。</span>
  </p>
  <ul class="legend">
    <li><i style="background:{PART_COLORS[0]}"></i>メロディ</li>
    <li><i style="background:{PART_COLORS[1]}"></i>ベース</li>
    <li><i style="background:{PART_COLORS[2]}"></i>リズム</li>
    <li><i style="background:{PART_COLORS[3]}"></i>サブ</li>
    <li>色の濃さ = 音の強さ</li>
  </ul>
</header>

<h2>フレーズ（2 小節）</h2>
<div class="grid">{"".join(cards)}
</div>

<h2>1 曲まるごと</h2>
<div class="grid">{song_card}
</div>

<h2>エンジンの規模</h2>
<table>{stats}</table>
<p class="note">
  数字はコードから読んで書き出しています。実装を変えればこの表も変わります。
</p>

<h2>アプリを使う</h2>
<p>
  <a class="bigbtn" href="{APP_PATH}">ブラウザ版を開く</a>
  ページの中で Python 本体（Pyodide）を読み込み、
  <strong>デスクトップ版と同じ core パッケージ</strong>をそのまま動かします。
  エンジンが 1 つなので、同じシード値なら出てくる曲も同じです。
  初回だけ Python の読み込みに十数秒かかります。
</p>
<p class="note">
  ブラウザ版でできること: 自動作成・サプライズ・音を置く／伸ばす／強さを変える・
  移調・反転・伴奏付け・WAV 書き出し・JSON の保存と読み込み。<br>
  デスクトップ版だけの機能: DJ モード、写真から音階を作る機能、MIDI 書き出し、
  切り離せるパネル、ソング画面。
</p>
<p>
  Windows 用のビルドは
  <a href="{REPO_URL}/actions">リポジトリの Actions</a> から
  ダウンロードできます（フォルダ版が起動が速く、単一ファイル版は持ち運び向き）。
  Python がある環境なら <code>py main.py</code> で直接動きます。
</p>

<footer>
  生成: PicoSeq の作曲エンジン（core パッケージ・Python 標準ライブラリのみ）／
  音声は 16bit {WEB_RATE // 1000}kHz モノラル WAV
</footer>
</main>
</body>
</html>
"""


def main(argv) -> int:
    """コマンドラインから site/ を書き出す。"""
    out_dir = Path(argv[0]) if argv else ROOT / "site"
    summary = build(out_dir)
    print(f"{out_dir} を作りました: "
          f"カード {summary['cards']} 枚 / 音声 {len(summary['samples'])} 本 / "
          f"index.html {summary['bytes'] // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
