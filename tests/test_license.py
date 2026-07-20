"""有料化 — プロダクトコード検証 (純粋) と無料枠ロジック (辞書ベース) のテスト。

無料枠ロジックは settings 辞書を直接渡す純粋関数を叩くので、実ファイルには触れない。
"""

import unittest

from picoseq.core.license import (
    FREE_DAILY_LIMIT,
    is_valid_code,
    make_code,
    normalize_code,
)
from picoseq.ui import licensing


class TestProductCode(unittest.TestCase):
    def test_generated_codes_validate(self):
        for serial in (0, 1, 42, 123456, 20260719, 999999999):
            code = make_code(serial)
            self.assertTrue(is_valid_code(code), code)

    def test_format_is_grouped(self):
        code = make_code(42)
        self.assertTrue(code.startswith("PICO-"))
        self.assertEqual(len(code.split("-")), 4)

    def test_rejects_garbage(self):
        for bad in ("", "garbage", "PICO", "PICO-AAAA-AAAA-AAAA",
                    "1234-5678", "PICOXXXXXXXXXXXX", None):
            self.assertFalse(is_valid_code(bad), bad)

    def test_wrong_checksum_rejected(self):
        code = make_code(7)
        body = normalize_code(code)
        # チェック末尾を 1 文字ずらすと必ず不正になる
        tampered = body[:-1] + ("A" if body[-1] != "A" else "B")
        self.assertFalse(is_valid_code(tampered))

    def test_normalize_ignores_separators_and_case(self):
        code = make_code(99)
        messy = "  " + code.lower().replace("-", " ") + " "
        self.assertTrue(is_valid_code(messy))

    def test_case_insensitive(self):
        code = make_code(55)
        self.assertTrue(is_valid_code(code.lower()))


class TestFreeTierLogic(unittest.TestCase):
    def test_free_by_default(self):
        self.assertFalse(licensing.is_pro_in({}))

    def test_full_quota_on_fresh_day(self):
        self.assertEqual(licensing.remaining_in({}, "2026-07-19"), FREE_DAILY_LIMIT)
        self.assertTrue(licensing.can_generate_in({}, "2026-07-19"))

    def test_recording_consumes_quota(self):
        s = {}
        for i in range(1, 6):
            s = licensing.with_recorded(s, "2026-07-19")
            self.assertEqual(licensing.used_today_in(s, "2026-07-19"), i)
        self.assertEqual(licensing.remaining_in(s, "2026-07-19"),
                         FREE_DAILY_LIMIT - 5)

    def test_quota_resets_next_day(self):
        s = {}
        for _ in range(3):
            s = licensing.with_recorded(s, "2026-07-19")
        # 別の日から見れば使用回数は 0
        self.assertEqual(licensing.used_today_in(s, "2026-07-20"), 0)
        self.assertEqual(licensing.remaining_in(s, "2026-07-20"), FREE_DAILY_LIMIT)

    def test_limit_blocks_generation(self):
        s = {"auto_gen_usage": {"date": "2026-07-19", "count": FREE_DAILY_LIMIT}}
        self.assertFalse(licensing.can_generate_in(s, "2026-07-19"))
        self.assertEqual(licensing.remaining_in(s, "2026-07-19"), 0)

    def test_corrupt_usage_treated_as_zero(self):
        for bad in ({"auto_gen_usage": "x"},
                    {"auto_gen_usage": {"date": "2026-07-19", "count": "oops"}},
                    {"auto_gen_usage": {"date": "2026-07-19", "count": -5}}):
            self.assertEqual(licensing.used_today_in(bad, "2026-07-19"), 0, bad)

    def test_activation_unlocks_unlimited(self):
        code = make_code(20260719)
        s, ok = licensing.with_activated({}, code)
        self.assertTrue(ok)
        self.assertTrue(licensing.is_pro_in(s))
        self.assertIsNone(licensing.remaining_in(s, "2026-07-19"))  # 無制限
        self.assertTrue(licensing.can_generate_in(s, "2026-07-19"))

    def test_activation_rejects_bad_code(self):
        s, ok = licensing.with_activated({}, "not-a-code")
        self.assertFalse(ok)
        self.assertNotIn("product_code", s)

    def test_pro_recording_is_noop(self):
        code = make_code(1)
        s, _ = licensing.with_activated({}, code)
        same = licensing.with_recorded(s, "2026-07-19")
        self.assertIs(same, s)  # 有料版は消費しない


if __name__ == "__main__":
    unittest.main()
