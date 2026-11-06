#!/usr/bin/env python3
"""Find blocks containing transactions signed by a wallet.

Nonce changes do not discover token movements initiated by third parties.
A transferFrom roundtrip can restore both balance and allowance, so these
helpers are not a complete token-history source. The verifier scans token
Transfer logs continuously instead. unexplained_balance compares state only;
a zero difference does not establish movement-history completeness.
"""


def blocks_with_transactions(address, low, high, nonce_at):
    """Every block in which `address` sent a transaction, within (low, high].

    `nonce_at(address, block)` returns the account's nonce as of that block.
    Costs about O(k log n) calls for k transactions over n blocks, versus the
    O(n / window) of paging logs across the whole range.
    """
    found = []

    def walk(lo, hi, nonce_lo, nonce_hi):
        if nonce_hi == nonce_lo:
            return                      # nothing was sent in this span
        if hi - lo <= 1:
            # `hi` is the only candidate left; it may hold several.
            found.extend([hi] * (nonce_hi - nonce_lo))
            return
        mid = (lo + hi) // 2
        nonce_mid = nonce_at(address, mid)
        walk(lo, mid, nonce_lo, nonce_mid)
        walk(mid, hi, nonce_mid, nonce_hi)

    walk(low, high, nonce_at(address, low), nonce_at(address, high))
    return found


def unexplained_balance(expected_wei, actual_wei):
    """Return the expected-minus-observed balance difference in wei.

    A zero state difference cannot prove that no intermediate movements
    occurred. Use continuous token logs when verifying transfer history.
    """
    return expected_wei - actual_wei
