"""PicoSeq 起動スクリプト。

使い方:
  py main.py            GUI を起動する
  py main.py --selftest 画面を出さずに配線を自己診断する (終了コード 0 = 正常)
"""

import sys


def _enable_dpi_awareness():
    """高 DPI 環境でにじまないようにする (Windows のみ・失敗しても続行)。"""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


def main() -> int:
    _enable_dpi_awareness()
    from picoseq.ui.app import run
    return run(selftest="--selftest" in sys.argv, demo="--demo" in sys.argv)


if __name__ == "__main__":
    sys.exit(main())
