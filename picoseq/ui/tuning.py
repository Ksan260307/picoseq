"""UI の調整用の定数だけを集めた小さなモジュール。

app / dj_control / selftest が共有する。どこにも依存しないので循環 import を起こさない。
"""

LIVE_DEBOUNCE_MS = 140      # 演奏中の編集をまとめて再レンダリングする間隔
DJ_RENDER_DEBOUNCE_MS = 120  # DJ: 次ループの事前レンダリングをまとめる間隔
DJ_ADVANCE_LOOPS = 4        # DJ: 何ループ流したら自動で次へ進むか (2小節×4 = 8小節)
DJ_SCRATCH_MS = 45          # スクラッチ音の最短間隔 (ミリ秒)
DJ_HISTORY_COMMIT_MS = 800  # つまみ操作を履歴へ確定するまでの待ち (デバウンス)
SURPRISE_BPM = (80, 180)    # サプライズのテンポの振れ幅 (極端に速い/遅いを避ける)
