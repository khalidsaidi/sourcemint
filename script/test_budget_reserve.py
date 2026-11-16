"""The mandatory head re-check must stay affordable in time, not just requests.

A full scan runs for an hour, so it will spend the clock down to the deadline.
If only requests are reserved, the canonical re-check that confirms the fixed
head is unaffordable the moment the scan ends, and a complete, clean history
still reports itself unverified. Found by running the real scan against Base
mainnet, where it returned:

    COULD NOT VERIFY: fixed-head history was not confirmed canonical.
      RPC time budget exhausted before retry
"""
import unittest
from unittest.mock import patch

import verify_ledger as v


class TimeReserve(unittest.TestCase):
    def budget(self, now):
        with patch.object(v.time, "monotonic", return_value=now):
            return v.RpcBudget(requests=100, seconds=100)

    def test_scan_stops_early_so_the_recheck_can_still_run(self):
        b = self.budget(0.0)
        b.reserve, b.reserve_seconds = 2, 10.0
        # 95s in: past the scan's effective deadline (100 - 10), not the real one
        with patch.object(v.time, "monotonic", return_value=95.0):
            with self.assertRaises(v.SourceUnavailable):
                b.check()
            # the scan is over; both reserves lift together
            b.reserve, b.reserve_seconds = 0, 0.0
            b.check()          # the head re-check is still affordable

    def test_requests_are_reserved_the_same_way(self):
        b = self.budget(0.0)
        b.reserve = 2
        b.used = 98
        with patch.object(v.time, "monotonic", return_value=1.0):
            with self.assertRaises(v.SourceUnavailable):
                b.check()
            b.reserve = 0
            b.check()

    def test_a_retry_pause_respects_the_reserve(self):
        b = self.budget(0.0)
        b.reserve_seconds = 10.0
        with patch.object(v.time, "monotonic", return_value=85.0):
            # 5s remain before the scan deadline; a 6s backoff would eat the reserve
            with self.assertRaises(v.SourceUnavailable):
                b.pause(6.0)

    def test_the_real_deadline_still_ends_the_run(self):
        b = self.budget(0.0)
        with patch.object(v.time, "monotonic", return_value=101.0):
            with self.assertRaises(v.SourceUnavailable):
                b.check()


if __name__ == "__main__":
    unittest.main()
