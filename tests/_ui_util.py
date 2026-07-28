"""UI テストの下ごしらえ — 画面を出さずにアプリを 1 つ建てる。

Tk が使えない環境 (CI の Linux など) では tk_available() が False になり、
呼び出し側のテストはまるごとスキップされる。
"""


def tk_available() -> bool:
    """Tk のウィンドウを作れるか (ディスプレイの有無で決まる)。"""
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:       # noqa: BLE001 - ディスプレイが無い等
        return False


def make_app(silent: bool = True):
    """(app, root) を返す。片付けは close_app() で行う。"""
    import tkinter as tk

    from picoseq.ui.app import PicoSeqApp
    root = tk.Tk()
    root.withdraw()
    return PicoSeqApp(root, silent=silent), root


def pump(root, condition, timeout: float = 15.0) -> bool:
    """condition() が真になるまでイベントを回す。裏スレッドの完了待ちに使う。

    `_run_bg` は `after(50, poll)` で結果を取りに来るので、
    待つ側もタイマーが動く程度に休みながら回す必要がある
    (update() を全速で呼び続けるとタイマーの時刻に届かない)。
    """
    import time
    limit = time.monotonic() + timeout
    while time.monotonic() < limit:
        if condition():
            return True
        root.update()
        time.sleep(0.02)
    return condition()


def close_app(app, root):
    """予約済みコールバックを取り消してからウィンドウを壊す。

    取り消さないと、破棄後に発火した予約が Tk のエラーを吐く。
    """
    try:
        app.cancel_pending()
    except Exception:       # noqa: BLE001 - 片付けで落ちない
        pass
    try:
        root.destroy()
    except Exception:       # noqa: BLE001
        pass
