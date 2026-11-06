"""Counterexamples from the independent review of the fixed-head scan."""
import copy
import unittest

import verify_ledger as v
import test_history_scan as h


def entry(tx, amount='40', sender=h.ALICE, receiver=h.BOB):
    return {'tx': tx, 'from': sender, 'to': receiver, 'amount': amount, 'reason': 'snapshot boundary'}


class SnapshotConsistency(unittest.TestCase):
    def test_pending_and_future_nonzero_transfers_are_inconclusive(self):
        for receipt in [None, {'transactionHash': h.block_hash(9000),
                'blockNumber': hex(203), 'blockHash': h.block_hash(203)}]:
            with self.subTest(receipt=receipt):
                node = h.Node(); led = h.ledger(); led['entries'].append(entry(h.block_hash(9000)))
                node.receipts[h.block_hash(9000)] = receipt
                self.assertEqual(h.run(node, led)[0], 2)

    def test_pending_mint_or_burn_does_not_make_a_supply_finding(self):
        for sender, receiver in [('mint', h.ALICE), (h.ALICE, v.ZERO_ADDRESS)]:
            with self.subTest(sender=sender):
                node = h.Node(); led = h.ledger()
                led['entries'].append(entry(h.block_hash(9000), sender=sender, receiver=receiver))
                self.assertEqual(h.run(node, led)[0], 2)

    def test_independent_transfer_finding_survives_pending_nonzero_entry(self):
        node = h.Node(); node.events.append(h.event(2, h.ALICE, h.CHARLIE, 0))
        led = h.ledger(); led['entries'].append(entry(h.block_hash(9000)))
        self.assertEqual(h.run(node, led)[0], 1)

    def test_independent_missing_finding_survives_pending_nonzero_entry(self):
        node = h.Node(); led = h.ledger()
        led['entries'] += [entry(h.block_hash(9000), amount='0'), entry(h.block_hash(9001))]
        node.receipts[h.block_hash(9000)] = {'transactionHash': h.block_hash(9000),
                                           'blockNumber': '0x2', 'blockHash': h.block_hash(2)}
        self.assertEqual(h.run(node, led)[0], 1)

    def test_malformed_receipt_transaction_hash_is_inconclusive_not_traceback(self):
        for value in [None, 123, [], '0x12', h.block_hash(7)]:
            with self.subTest(value=value):
                node = h.Node(); led = h.ledger(); led['entries'].append(entry(h.block_hash(9000), amount='0'))
                node.receipts[h.block_hash(9000)] = {'transactionHash': value,
                        'blockNumber': '0x2', 'blockHash': h.block_hash(2)}
                self.assertEqual(h.run(node, led)[0], 2)

    def test_same_log_identity_at_two_heights_invalidates_history(self):
        node = h.Node(); other = h.event(101, h.ALICE, h.BOB, 0)
        other['blockHash'] = h.block_hash(1); node.events.append(other)
        self.assertEqual(h.run(node, BASE_HISTORY_BLOCK_SPAN=100)[0], 2)

    def test_different_hashes_at_one_height_invalidate_history(self):
        node = h.Node(); other = h.event(1, h.ALICE, h.BOB, 0, index=1)
        other['blockHash'] = h.block_hash(500); node.events.append(other)
        self.assertEqual(h.run(node)[0], 2)

    def test_a_log_at_head_must_have_the_frozen_head_hash(self):
        node = h.Node(); other = h.event(202, h.ALICE, h.BOB, 0)
        other['blockHash'] = h.block_hash(500); node.events.append(other)
        self.assertEqual(h.run(node)[0], 2)

    def test_reorg_during_receipt_check_does_not_create_a_false_finding(self):
        class ReorgNode(h.Node):
            changed = False
            def __call__(self, payload, endpoint=None):
                if payload['method'] == 'eth_getTransactionReceipt':
                    self.changed = True
                if self.changed and payload['method'] == 'eth_call':
                    raise v.SourceUnavailable('old snapshot is not canonical')
                result = super().__call__(payload, endpoint)
                if self.changed and payload['method'] == 'eth_getBlockByNumber':
                    result['result']['hash'] = h.block_hash(int(result['result']['number'], 16) + 500)
                return result
        node = ReorgNode(); tx = h.block_hash(9000)
        node.receipts[tx] = {'transactionHash': tx, 'blockNumber': '0x2', 'blockHash': h.block_hash(502)}
        led = h.ledger(); led['entries'].append(entry(tx, amount='0'))
        self.assertEqual(h.run(node, led)[0], 2)

    def test_stable_head_missing_finding_survives_a_state_only_outage(self):
        class StateOutage(h.Node):
            def __call__(self, payload, endpoint=None):
                if payload['method'] == 'eth_call':
                    raise v.SourceUnavailable('state read unavailable')
                return super().__call__(payload, endpoint)
        node = StateOutage(); tx = h.block_hash(9000)
        node.receipts[tx] = {'transactionHash': tx, 'blockNumber': '0x2', 'blockHash': h.block_hash(2)}
        led = h.ledger(); led['entries'].append(entry(tx, amount='0'))
        self.assertEqual(h.run(node, led)[0], 1)

    def test_natural_head_growth_does_not_move_the_snapshot(self):
        class Growing(h.Node):
            advanced = False
            def __call__(self, payload, endpoint=None):
                result = super().__call__(payload, endpoint)
                if payload['method'] == 'eth_getLogs':
                    self.advanced = True
                if self.advanced and payload['method'] == 'eth_getBlockByNumber' and payload['params'][0] == 'latest':
                    result['result'] = {'number': hex(self.head + 1), 'hash': h.block_hash(self.head + 1)}
                return result
        self.assertEqual(h.run(Growing())[0], 0)


    def test_same_hash_at_different_heights_with_distinct_indices_is_rejected(self):
        node = h.Node(); other = h.event(101, h.ALICE, h.BOB, 0, index=1)
        other['blockHash'] = h.block_hash(1); node.events.append(other)
        self.assertEqual(h.run(node, BASE_HISTORY_BLOCK_SPAN=100)[0], 2)

    def test_bad_receipt_does_not_downgrade_an_independent_transfer_finding(self):
        node = h.Node(); node.events.append(h.event(2, h.ALICE, h.CHARLIE, 0))
        tx = h.block_hash(9000); led = h.ledger(); led['entries'].append(entry(tx))
        node.receipts[tx] = {'transactionHash': None, 'blockNumber': '0x2', 'blockHash': h.block_hash(2)}
        self.assertEqual(h.run(node, led)[0], 1)


if __name__ == '__main__':
    unittest.main()
