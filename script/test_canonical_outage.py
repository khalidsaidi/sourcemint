"""Failing to RE-READ the head is not the same as the head having CHANGED.

Both once left `canonical` false, and main() returned 2 on that before it had
even compared the observed transfers against the ledger. So a confirmed
unledgered movement could sit in a complete, successfully scanned history and
be reported as a CI deferral -- a green build over real evidence. That is
issue #10's defect at a different gate: the run goes quiet because a later
read failed.

The two causes are now distinguished:

  * the head HASH CHANGED -- positive proof the snapshot's basis is gone, so
    observations tied to it are not evidence about the current chain. Still 2.
  * the head could NOT BE READ -- an outage, which says nothing about what was
    already observed. An unaccounted movement survives it, as it survives a
    failed page (test_history_scan) and a failed state read (test_allowance_outage).
"""
import unittest

from test_history_scan import ALICE, CHARLIE, Node, event, run

import verify_ledger as v


class HeadOutage(Node):
    """A complete scan observes an unledgered transfer; the mandatory head
    re-read then fails as an outage rather than a disagreement."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.events += [event(200, ALICE, CHARLIE, 40 * 10**18)]
        self.scanned = False

    def __call__(self, payload, endpoint=None):
        if payload["method"] == "eth_getLogs":
            self.scanned = True
        if payload["method"] == "eth_getBlockByNumber" and self.scanned:
            raise v.SourceUnavailable("RPC request budget exhausted")
        return super().__call__(payload, endpoint)


class HeadReorg(Node):
    """The same observation, but the head genuinely changed under us."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.events += [event(200, ALICE, CHARLIE, 40 * 10**18)]
        self.changed_head = True


class CanonicalOutage(unittest.TestCase):
    def test_unreadable_head_does_not_bury_an_observed_violation(self):
        code, output = run(HeadOutage())
        self.assertEqual(code, 1, output)
        self.assertIn("UNACCOUNTED", output)
        self.assertIn(CHARLIE, output)

    def test_a_changed_head_still_invalidates_the_observation(self):
        code, output = run(HeadReorg())
        self.assertEqual(code, 2, output)
        self.assertIn("no longer canonical", output)
        self.assertNotIn("RESULT: FAIL", output)

    def test_an_unreadable_head_without_a_violation_stays_inconclusive(self):
        class Clean(HeadOutage):
            def __init__(self, **kw):
                Node.__init__(self, **kw)
                self.scanned = False
        code, output = run(Clean())
        self.assertEqual(code, 2, output)
        self.assertNotIn("RESULT: FAIL", output)

    def test_the_cause_is_named_in_the_output(self):
        _, outage = run(HeadOutage())
        _, reorg = run(HeadReorg())
        self.assertIn("outage", outage)
        self.assertIn("replaced", reorg)


if __name__ == "__main__":
    unittest.main()
