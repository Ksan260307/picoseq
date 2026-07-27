"""幅に応じて自動で折り返すツールバー。

tkinter には flow レイアウトが無いので自前で用意する。pack だけで横一列に
並べると、ウィンドウが狭いときに右端の部品が**画面外へ出て操作できなくなる**
(保存・読込が押せない等)。FlowBar は幅が変わるたびに並べ直し、
どんな幅でもすべての部品に手が届くようにする。

使い方:
    bar = FlowBar(parent, bg=theme.BG)
    bar.pack(fill="x")
    bar.add(widget)                 # 左から順に流す
    bar.add(widget, pin_right=True) # 1 行に収まるときだけ右寄せ (従来の見た目)
    bar.done()                      # 全部足したら呼ぶ (自然幅を確定)

・部品は FlowBar の子として作ること (place で配置するため)。
・ラベル+入力のように離れてほしくない組は、呼び出し側で 1 つの Frame に
  まとめてから add する (FlowBar はその Frame を 1 単位として扱う)。
"""

import tkinter as tk

GAP = 4        # 部品どうしの横の間隔
ROW_GAP = 4    # 折り返した行の間隔
EDGE = 6       # 右端に残す余白 (ウィンドウ枠にぴったり付けない)


class FlowBar(tk.Frame):
    def __init__(self, parent, bg, gap=GAP, row_gap=ROW_GAP, **kw):
        super().__init__(parent, bg=bg, **kw)
        self._gap = gap
        self._row_gap = row_gap
        self._cells = []        # [(widget, pin_right)]
        self._natural = 0       # 1 行に並べたときの幅 (初期ウィンドウ幅の目安)
        self._pending = None    # 最後に届いた幅 (まだ反映していないもの)
        self._applied = -1      # 反映済みの幅
        self._queued = False    # after_idle を予約済みか
        self._laying_out = False
        self.on_reflow = None   # 並べ直したあとに呼ぶ (行数が変わると高さも変わる)
        self.bind("<Configure>", self._on_configure)

    # ---- 組み立て ----

    def add(self, widget, pin_right=False):
        """部品を登録する。widget は self の子であること。"""
        self._cells.append((widget, pin_right))
        return widget

    def done(self):
        """登録完了。1 行ぶんの自然幅を要求幅として持たせる。

        これがあると初回起動時に「1 行で収まる広さ」で窓が開き、
        狭めたときだけ折り返しに切り替わる。
        """
        self.update_idletasks()
        total = sum(w.winfo_reqwidth() for w, _ in self._cells)
        total += self._gap * max(0, len(self._cells) - 1)
        self._natural = total
        height = max((w.winfo_reqheight() for w, _ in self._cells), default=1)
        self.configure(width=total, height=height)
        self._pending = self.winfo_width() or total
        self._flush()

    def refresh(self):
        """部品の中身が変わって幅が伸び縮みしたときに並べ直す。"""
        self.update_idletasks()
        self._pending = self.winfo_width() or self._natural
        self._applied = -1          # 同じ幅でも作り直させる
        self._flush()

    # ---- 並べ直し ----

    def _on_configure(self, event):
        """幅の変化を覚えておき、手が空いたところで 1 回だけ並べ直す。

        並べ直し中に届いた <Configure> を捨ててはいけない。捨てると
        「その後もう <Configure> が来ない」場合に古い幅のままになり、
        ウィンドウを縮めても折り返さない (= 部品が画面外に残る) ことがある。
        """
        if not self._cells:
            return
        self._pending = event.width
        if self._queued:
            return
        self._queued = True
        self.after_idle(self._flush)

    def _flush(self):
        self._queued = False
        if self._laying_out:                 # 進行中なら次の空きへ回す
            self._queued = True
            self.after_idle(self._flush)
            return
        width = self._pending
        if width is None or abs(width - self._applied) < 2:
            return
        self._applied = width
        self._relayout(width)

    def _relayout(self, avail):
        if not self._cells or self._laying_out:
            return
        if avail <= 1:
            avail = self._natural or 1
        avail = max(1, avail - EDGE)      # 右端に少し余白を残す
        self._laying_out = True
        try:
            rows = self._flow(avail)
            self._place(rows, avail)
        finally:
            self._laying_out = False

    def _flow(self, avail):
        """貪欲に行へ詰める。返り値は [[(widget, pin_right), ...], ...]。"""
        rows = [[]]
        x = 0
        for cell in self._cells:
            w = cell[0].winfo_reqwidth()
            step = w if not rows[-1] else w + self._gap
            if rows[-1] and x + step > avail:
                rows.append([])
                x = w
            else:
                x += step
            rows[-1].append(cell)
        return rows

    def _place(self, rows, avail):
        y = 0
        total_h = 0
        single = len(rows) == 1
        for row in rows:
            row_h = max((w.winfo_reqheight() for w, _ in row), default=0)
            # 1 行に収まるときだけ pin_right を右寄せ (従来の見た目を保つ)
            pinned = [c for c in row if c[1]] if single else []
            flowing = [c for c in row if c not in pinned]
            x = 0
            for widget, _ in flowing:
                widget.place(x=x, y=y + (row_h - widget.winfo_reqheight()) // 2)
                x += widget.winfo_reqwidth() + self._gap
            rx = avail
            for widget, _ in reversed(pinned):
                rx -= widget.winfo_reqwidth()
                widget.place(x=max(x, rx),
                             y=y + (row_h - widget.winfo_reqheight()) // 2)
                rx -= self._gap
            y += row_h + self._row_gap
            total_h = y
        self.configure(height=max(1, total_h - self._row_gap))
        if self.on_reflow is not None:
            self.on_reflow()


def group(parent, bg):
    """ラベル+入力などを 1 単位にまとめるための入れ物。"""
    return tk.Frame(parent, bg=bg)
