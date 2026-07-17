"""決定論 PRNG (mulberry32)。

乱数は必ず明示シードから生成する。同じシードからは常に同じ列が出る。
整数演算のみなので、どの環境でも同一の結果になる。
"""

MASK32 = 0xFFFFFFFF


class Rng:
    """32bit 状態の決定論的乱数生成器。"""

    def __init__(self, seed: int):
        self.state = seed & MASK32

    def next_u32(self) -> int:
        """0 以上 2^32 未満の整数を返す。"""
        self.state = (self.state + 0x6D2B79F5) & MASK32
        t = self.state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK32
        t ^= (t + ((t ^ (t >> 7)) * (t | 61) & MASK32)) & MASK32
        return (t ^ (t >> 14)) & MASK32

    def next_float(self) -> float:
        """0.0 以上 1.0 未満の実数を返す。"""
        return self.next_u32() / 4294967296.0

    def next_int(self, n: int) -> int:
        """0 以上 n 未満の整数を返す。"""
        return self.next_u32() % n

    def chance(self, p: float) -> bool:
        """確率 p で True を返す。"""
        return self.next_float() < p
