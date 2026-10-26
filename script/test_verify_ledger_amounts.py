import unittest
from decimal import localcontext

from script.verify_ledger import AccountingViolation, amount_to_wei


class TestAmountToWei(unittest.TestCase):
    def test_whole_and_fractional_token_amounts(self):
        cases = {
            "0": 0,
            "1000000": 1_000_000 * 10**18,
            "0.5": 500_000_000_000_000_000,
            "1.2300": 1_230_000_000_000_000_000,
            "0.000000000000000001": 1,
            "1.000000000000000001": 1_000_000_000_000_000_001,
            "1000000.123456789012345678": 1_000_000_123_456_789_012_345_678,
            "0.5000000000000000000": 500_000_000_000_000_000,
        }
        for amount, expected in cases.items():
            with self.subTest(amount=amount):
                self.assertEqual(amount_to_wei(amount), expected)

    def test_large_amount_is_exact_regardless_of_decimal_context(self):
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(
                amount_to_wei("12345678901234567890.123456789012345678"),
                12_345_678_901_234_567_890_123_456_789_012_345_678,
            )

    def test_sub_wei_precision_is_rejected_without_rounding(self):
        for amount in ("0.0000000000000000001", "1.0000000000000000001"):
            with self.subTest(amount=amount):
                with self.assertRaisesRegex(AccountingViolation, "18 decimal places"):
                    amount_to_wei(amount)

    def test_invalid_or_negative_amount_is_rejected(self):
        for amount in ("", "invalid", "1,5", "-1", "-0.5", "NaN", "sNaN", "Infinity", "-Infinity"):
            with self.subTest(amount=amount):
                with self.assertRaises(AccountingViolation):
                    amount_to_wei(amount)

    def test_amount_must_remain_a_string_in_the_ledger(self):
        for amount in (None, 1, 0.5, True):
            with self.subTest(amount=amount):
                with self.assertRaisesRegex(AccountingViolation, "decimal string"):
                    amount_to_wei(amount)
