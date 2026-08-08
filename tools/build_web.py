"""ブラウザ版の組み立て — core を zip に固めて web/ と一緒に置く。

デスクトップ版の tkinter 画面はブラウザで動かないが、**core は動く**:
標準ライブラリだけで書かれていて、tkinter も ctypes も threading も使わない。
そこで core をそのまま zip にして Pyodide (CPython on WASM) へ渡し、
画面だけ HTML/Canvas で作り直す。エンジンは 1 つのままなので音は同じ。

ここでやること:
  1. core がブラウザで動く形かを検査する (使えない import が混じったら失敗)
  2. picoseq/core + bridge.py を zip にまとめる
  3. web/ の静的ファイルを出力先へコピーする

使い方:
    python tools/build_web.py [出力先]      # 既定は site/app/
"""

import ast
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "picoseq" / "core"
WEB = ROOT / "web"

# ブラウザ (Pyodide) で使えない・使ってはいけないモジュール。
# core がこれらを掴んだ瞬間にブラウザ版は起動しなくなるので、ビルドで止める。
BLOCKED = frozenset({
    "tkinter", "ctypes", "winsound", "subprocess", "multiprocessing",
    "socket", "sounddevice", "PIL", "threading",
})

# zip に入れる静的ファイル以外 (そのままコピーするもの)
STATIC = ("index.html", "style.css", "app.js")

ZIP_NAME = "picoseq-core.zip"


class BrowserUnsafe(Exception):
    """core がブラウザで動かない形になっている。"""


def check_browser_safe(folder: Path = CORE) -> list:
    """core が使っている外部モジュールを返す。使えないものがあれば例外。"""
    used = set()
    problems = []
    for path in sorted(folder.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                used.add(name)
                if name in BLOCKED:
                    problems.append(f"{path.name}:{node.lineno} {name}")
    if problems:
        raise BrowserUnsafe(
            "core がブラウザで動かないモジュールを import しています: "
            + ", ".join(problems))
    return sorted(used)


def build_zip(dest: Path) -> int:
    """core と bridge.py を zip にまとめ、入れたファイル数を返す。

    ファイル順と日時を固定して書く。こうすると**中身が同じなら zip も同じ**に
    なり、CI が毎回同じ成果物を出す (再現可能なビルド)。
    """
    check_browser_safe()
    members = [(ROOT / "picoseq" / "__init__.py", "picoseq/__init__.py"),
               (CORE / "__init__.py", "picoseq/core/__init__.py")]
    for path in sorted(CORE.glob("*.py")):
        if path.name != "__init__.py":
            members.append((path, f"picoseq/core/{path.name}"))
    members.append((WEB / "bridge.py", "bridge.py"))

    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, name in members:
            item = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            item.compress_type = zipfile.ZIP_DEFLATED
            item.external_attr = 0o644 << 16
            zf.writestr(item, path.read_bytes())
    return len(members)


def build(out_dir: Path) -> dict:
    """出力先にブラウザ版を組み立て、要約を返す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    count = build_zip(out_dir / ZIP_NAME)
    for name in STATIC:
        shutil.copyfile(WEB / name, out_dir / name)
    return {
        "modules": count,
        "zip_bytes": (out_dir / ZIP_NAME).stat().st_size,
        "static": list(STATIC),
    }


def main(argv) -> int:
    """コマンドラインから site/app/ を組み立てる。"""
    out_dir = Path(argv[0]) if argv else ROOT / "site" / "app"
    try:
        summary = build(out_dir)
    except BrowserUnsafe as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
    print(f"{out_dir} を作りました: "
          f"モジュール {summary['modules']} 個 / "
          f"{ZIP_NAME} {summary['zip_bytes'] // 1024} KB / "
          f"静的ファイル {len(summary['static'])} 個")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
