"""The nonce search must find every transaction, including the awkward cases."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_history import blocks_with_transactions, unexplained_balance  # noqa: E402

ADDR = "0x497d34b1d0790f374B32467093d303533399c819"


def fake_chain(tx_blocks):
    """nonce_at() for a wallet whose transactions sit in `tx_blocks`."""
    calls = []

    def nonce_at(_addr, block):
        calls.append(block)
        return sum(1 for b in tx_blocks if b <= block)

    return nonce_at, calls


class NonceSearch(unittest.TestCase):
    def find(self, tx_blocks, low=0, high=1_000_000):
        nonce_at, calls = fake_chain(tx_blocks)
        return sorted(blocks_with_transactions(ADDR, low, high, nonce_at)), calls

    def test_no_transactions_costs_two_calls(self):
        found, calls = self.find([])
        self.assertEqual(found, [])
        self.assertEqual(len(calls), 2, "an idle wallet should not be searched")

    def test_finds_a_single_transaction(self):
        self.assertEqual(self.find([123_456])[0], [123_456])

    def test_finds_every_transaction(self):
        blocks = [1, 500, 999_999, 250_000, 250_001]
        self.assertEqual(self.find(blocks)[0], sorted(blocks))

    def test_two_transactions_in_one_block_are_both_found(self):
        found, _ = self.find([42, 42])
        self.assertEqual(found, [42, 42], "a block can hold several of our txs")

    def test_transaction_at_the_very_last_block(self):
        self.assertEqual(self.find([1_000_000])[0], [1_000_000])

    def test_cost_is_logarithmic_not_linear(self):
        _, calls = self.find([7, 999_000])
        self.assertLess(len(calls), 60,
                        "searching a million blocks must not approach a scan")

    def test_an_out_and_back_round_trip_is_still_visible(self):
        # The case a balance comparison cannot see: tokens leave and return.
        # The wallet signed the outbound leg, so the nonce moved.
        found, _ = self.find([900])
        self.assertEqual(found, [900])


class TransferFromDetection(unittest.TestCase):
    def test_a_balance_matching_the_ledger_is_explained(self):
        self.assertEqual(unexplained_balance(98_500, 98_500), 0)

    def test_a_short_balance_reveals_a_movement_we_did_not_sign(self):
        self.assertGreater(unexplained_balance(98_500, 98_000), 0)

    def test_an_unexpected_credit_is_reported_too(self):
        self.assertLess(unexplained_balance(98_500, 99_000), 0)


if __name__ == "__main__":
    unittest.main()
