"""Fixed-head history coverage, including the delegated roundtrip in issue #10.

The roundtrip is the same scenario reported by Chandain in
https://github.com/khalidsaidi/sourcemint/issues/10; all RPC here is offline.
"""
import copy
import contextlib
import io
import json
import os
import unittest
from unittest.mock import patch

import verify_ledger as v

TOKEN = '0x' + 'aa' * 20
ALICE = '0x' + '11' * 20
BOB = '0x' + '22' * 20
CHARLIE = '0x' + '33' * 20
SUPPLY = 100 * 10**18


def block_hash(n):
    return '0x' + format(n, '064x')


def event(n, sender, receiver, amount, index=0, tx=None):
    return {'address': TOKEN, 'blockNumber': hex(n), 'blockHash': block_hash(n),
            'transactionHash': tx or block_hash(1000 + n),
            'logIndex': hex(index), 'transactionIndex': '0x0', 'removed': False,
            'topics': [v.TRANSFER_TOPIC, '0x' + sender[2:].zfill(64),
                       '0x' + receiver[2:].zfill(64)],
            'data': '0x' + format(amount, '064x')}


def ledger():
    return {'token': TOKEN, 'chain_id': 8453, 'project_wallets': {'alice': ALICE},
            'entries': [{'tx': block_hash(1001), 'from': 'mint', 'to': ALICE,
                         'amount': '100', 'reason': 'genesis'}]}


class Node:
    def __init__(self, head=202, roundtrip=False):
        self.head = head
        self.events = [event(1, v.ZERO_ADDRESS, ALICE, SUPPLY)]
        if roundtrip:
            self.events += [event(200, ALICE, CHARLIE, 40 * 10**18),
                            event(201, CHARLIE, ALICE, 40 * 10**18)]
        self.calls = []
        self.fail_start = None
        self.changed_head = False
        self.wrong_chain = False
        self.receipts = {}
        self.head_reads = 0

    def __call__(self, payload, endpoint=None):
        self.calls.append((copy.deepcopy(payload), endpoint))
        method, params = payload['method'], payload['params']
        if method == 'eth_chainId':
            result = hex(8454 if self.wrong_chain and endpoint else 8453)
        elif method == 'eth_getBlockByNumber':
            number = self.head if params[0] == 'latest' else int(params[0], 16)
            self.head_reads += 1
            h = block_hash(number)
            if self.changed_head and self.head_reads >= 3:
                h = block_hash(number + 1)
            result = {'number': hex(number), 'hash': h}
        elif method == 'eth_getLogs':
            f = params[0]
            start, end = int(f['fromBlock'], 16), int(f['toBlock'], 16)
            assert f['address'] == TOKEN and f['topics'] == [v.TRANSFER_TOPIC]
            if self.fail_start is not None and start >= self.fail_start:
                raise v.SourceUnavailable('page unavailable')
            result = copy.deepcopy([e for e in self.events
                                    if start <= int(e['blockNumber'], 16) <= end])
        elif method == 'eth_getTransactionReceipt':
            result = self.receipts.get(params[0])
        elif method == 'eth_call':
            call, block = params
            assert block == {'blockHash': block_hash(self.head), 'requireCanonical': True}
            data = call['data']
            assert not data.startswith(v.ALLOWANCE_SELECTOR), 'allowance is not past history'
            if data == v.TOTAL_SUPPLY_SELECTOR:
                value = SUPPLY
            else:
                address = '0x' + data[-40:]
                value = 0
                seen = set()
                for e in self.events:
                    identity = (e["blockHash"], e["logIndex"])
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if int(e['blockNumber'], 16) > self.head:
                        continue
                    n = int(e['data'], 16)
                    if e['topics'][1][-40:] == address[2:]:
                        value -= n
                    if e['topics'][2][-40:] == address[2:]:
                        value += n
            result = '0x' + format(value, '064x')
        else:
            raise AssertionError('unexpected RPC method ' + method)
        return {'jsonrpc': '2.0', 'id': 1, 'result': result}


def run(node, led=None, **env):
    output = io.StringIO()
    settings = {'BASE_HISTORY_BLOCK_SPAN': '10000', 'BASE_HISTORY_MAX_REQUESTS': '2048',
                'BASE_HISTORY_TIMEOUT': '300', 'BASE_HISTORY_MAX_LOGS_PER_PAGE': '10000'}
    settings.update({k: str(value) for k, value in env.items()})
    with (patch.dict(os.environ, settings), patch.object(v, 'DEPLOYMENT_BLOCK', 1),
          patch.object(v, 'LEDGER_PATH') as path,
          patch.object(v, 'rpc_call', side_effect=node), contextlib.redirect_stdout(output)):
        path.read_text.return_value = json.dumps(led or ledger())
        result = v.main()
    return result, output.getvalue()


class HistoryScan(unittest.TestCase):
    def test_delegated_roundtrip_is_not_hidden_by_restored_balance_or_revocation(self):
        node = Node(roundtrip=True)
        code, output = run(node)
        self.assertEqual(code, 1, output)
        self.assertIn('UNACCOUNTED', output)
        self.assertFalse(any(x[0]['method'] == 'eth_getTransactionCount' for x in node.calls))

    def test_complete_matching_history_can_succeed(self):
        self.assertEqual(run(Node())[0], 0)

    def test_pages_cover_every_block_once_including_short_final_page(self):
        node = Node(head=27)
        self.assertEqual(run(node, BASE_HISTORY_BLOCK_SPAN=10)[0], 0)
        pages = [x[0]['params'][0] for x in node.calls if x[0]['method'] == 'eth_getLogs']
        self.assertEqual([(int(p['fromBlock'], 16), int(p['toBlock'], 16)) for p in pages],
                         [(1, 10), (11, 20), (21, 27)])

    def test_earlier_confirmed_violation_survives_later_page_outage(self):
        node = Node(roundtrip=True)
        node.fail_start = 201
        code, output = run(node, BASE_HISTORY_BLOCK_SPAN=100)
        self.assertEqual(code, 1, output)
        self.assertIn('history incomplete', output)

    def test_partial_history_without_observed_violation_is_inconclusive(self):
        node = Node()
        node.fail_start = 101
        code, output = run(node, BASE_HISTORY_BLOCK_SPAN=100)
        self.assertEqual(code, 2, output)
        self.assertIn('COULD NOT VERIFY', output)

    def test_exhausted_request_budget_reserves_canonical_checks(self):
        node = Node(head=30)
        code, output = run(node, BASE_HISTORY_BLOCK_SPAN=10, BASE_HISTORY_MAX_REQUESTS=8)
        self.assertEqual(code, 2, output)
        self.assertEqual(len(node.calls), 8)
        self.assertIn('budget exhausted', output)

    def test_violation_before_budget_exhaustion_remains_a_finding(self):
        node = Node(head=30)
        node.events += [event(2, ALICE, CHARLIE, 1)]
        code, output = run(node, BASE_HISTORY_BLOCK_SPAN=10, BASE_HISTORY_MAX_REQUESTS=8)
        self.assertEqual(code, 1, output)
        self.assertEqual(len(node.calls), 8)

    def test_head_change_invalidates_unconfirmed_observations(self):
        node = Node(roundtrip=True)
        node.changed_head = True
        self.assertEqual(run(node)[0], 2)

    def test_two_endpoint_chain_mismatch_stops_before_logs(self):
        node = Node(); node.wrong_chain = True
        self.assertEqual(run(node)[0], 2)
        self.assertFalse(any(x[0]['method'] == 'eth_getLogs' for x in node.calls))

    def test_duplicate_wire_log_is_not_a_second_movement(self):
        node = Node(); node.events *= 2
        self.assertEqual(run(node)[0], 0)

    def test_real_duplicate_movements_with_distinct_log_indices_are_counted(self):
        node = Node(); tx = block_hash(1002)
        node.events += [event(2, ALICE, CHARLIE, 0, 0, tx), event(2, ALICE, CHARLIE, 0, 1, tx)]
        led = ledger(); led['entries'] += [{'tx': tx, 'from': ALICE, 'to': CHARLIE,
                                          'amount': '0', 'reason': 'one recorded event'}]
        self.assertEqual(run(node, led)[0], 1)

    def test_malformed_pages_are_not_empty_complete_pages(self):
        changes = [lambda e: e.update(removed=True),
                   lambda e: e.update(address=BOB),
                   lambda e: e.update(blockHash='0x123'),
                   lambda e: e.update(data='0x00'),
                   lambda e: e['topics'].append(block_hash(1)),
                   lambda e: e['topics'].__setitem__(1, '0x01' + e['topics'][1][4:])]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                node = Node(); change(node.events[0])
                self.assertEqual(run(node)[0], 2)

    def test_conflicting_duplicate_log_is_inconclusive(self):
        node = Node(); changed = copy.deepcopy(node.events[0]); changed['data'] = block_hash(1)
        node.events.append(changed)
        self.assertEqual(run(node)[0], 2)

    def test_known_result_cap_cannot_mark_a_page_complete(self):
        self.assertEqual(run(Node(), BASE_HISTORY_MAX_LOGS_PER_PAGE=1)[0], 2)

    def test_case_normalization_preserves_amount_above_float_precision(self):
        node = Node()
        node.events[0]['topics'] = ['0x' + x[2:].upper() for x in node.events[0]['topics']]
        node.events[0]['transactionHash'] = '0x' + node.events[0]['transactionHash'][2:].upper()
        self.assertEqual(run(node)[0], 0)

    def test_future_or_pending_ledger_transaction_is_not_a_false_violation(self):
        for receipt in [None, {'blockNumber': hex(203), 'blockHash': block_hash(203),
                              'transactionHash': block_hash(9000)}]:
            with self.subTest(receipt=receipt):
                node = Node(); tx = block_hash(9000); node.receipts[tx] = receipt
                led = ledger(); led['entries'].append({'tx': tx, 'from': ALICE,
                    'to': BOB, 'amount': '0', 'reason': 'outside snapshot'})
                self.assertEqual(run(node, led)[0], 2)

    def test_complete_absent_entry_with_covered_canonical_receipt_is_a_finding(self):
        node = Node(); tx = block_hash(9000)
        node.receipts[tx] = {'blockNumber': '0x2', 'blockHash': block_hash(2),
                             'transactionHash': tx}
        led = ledger(); led['entries'].append({'tx': tx, 'from': ALICE, 'to': BOB,
                                             'amount': '0', 'reason': 'not in receipt logs'})
        self.assertEqual(run(node, led)[0], 1)

    def test_invalid_configuration_is_inconclusive_without_rpc(self):
        for key, value in [('BASE_HISTORY_BLOCK_SPAN', '0'), ('BASE_HISTORY_TIMEOUT', 'nan'),
                           ('BASE_HISTORY_MAX_REQUESTS', '-1')]:
            with self.subTest(key=key):
                node = Node(); self.assertEqual(run(node, **{key: value})[0], 2)
                self.assertEqual(node.calls, [])


    def test_wrong_header_height_is_not_accepted_as_the_requested_snapshot(self):
        class WrongHeight(Node):
            def __call__(self, payload, endpoint=None):
                result = super().__call__(payload, endpoint)
                if payload['method'] == 'eth_getBlockByNumber' and payload['params'][0] != 'latest':
                    result['result']['number'] = hex(int(result['result']['number'], 16) + 1)
                return result
        self.assertEqual(run(WrongHeight())[0], 2)

    def test_one_confirmed_absent_entry_survives_another_pending_entry(self):
        node = Node(); led = ledger()
        for i in [9000, 9001]:
            tx = block_hash(i)
            led['entries'].append({'tx': tx, 'from': ALICE, 'to': BOB,
                                   'amount': '0', 'reason': 'claimed event'})
        node.receipts[block_hash(9000)] = {
            'transactionHash': block_hash(9000), 'blockNumber': '0x2', 'blockHash': block_hash(2)}
        self.assertEqual(run(node, led)[0], 1)

    def test_total_retained_log_budget_leaves_coverage_incomplete(self):
        node = Node(roundtrip=True)
        self.assertEqual(run(node, BASE_HISTORY_MAX_LOGS=1)[0], 2)

    def test_a_list_without_coverage_metadata_cannot_claim_verified(self):
        with patch.object(v, 'fetch_transfers', return_value=[]):
            self.assertEqual(run(Node())[0], 2)


class WireBudget(unittest.TestCase):
    def setUp(self):
        v._last_call[0] = 0
        v._pace[0] = 0

    def test_every_actual_retry_consumes_one_budget_unit(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, size):
                return json.dumps({'jsonrpc': '2.0', 'id': 1,
                    'error': {'code': -32005, 'message': 'rate limit'}}).encode()
        budget = v.RpcBudget(requests=3)
        with (patch.object(v, 'urlopen', return_value=Response()) as opened,
              patch.object(v.time, 'sleep')):
            with self.assertRaises(v.SourceUnavailable):
                budget.call(v.rpc_call, {'jsonrpc': '2.0', 'id': 1,
                            'method': 'eth_blockNumber', 'params': []}, 'https://invalid.test')
        self.assertEqual(opened.call_count, 3)
        self.assertEqual(budget.used, 3)

    def test_response_body_read_is_bounded(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, size):
                self.size = size
                return b'x' * size
        response = Response(); budget = v.RpcBudget(response_bytes=8)
        with patch.object(v, 'urlopen', return_value=response):
            with self.assertRaises(v.SourceUnavailable):
                budget.call(v.rpc_call, {}, 'https://invalid.test')
        self.assertEqual(response.size, 9)
        self.assertEqual(budget.used, 1)

    def test_expired_deadline_does_not_send_a_request(self):
        budget = v.RpcBudget(); budget.deadline = 0
        with patch.object(v, 'urlopen') as opened:
            with self.assertRaises(v.SourceUnavailable):
                budget.call(v.rpc_call, {}, 'https://invalid.test')
        opened.assert_not_called()


if __name__ == '__main__':
    unittest.main()
