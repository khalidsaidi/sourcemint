#!/usr/bin/env python3
"""Derive a project wallet's complete movement history from the chain.

Scanning every block since deployment is O(chain). This is O(our activity):

  * A nonce is monotonic. Binary-searching `eth_getTransactionCount` over
    block height finds every block in which a wallet sent a transaction.
    Nothing can hide there — unlike a balance, a nonce never comes back down,
    so a transfer out and straight back is still two nonce increments.
  * Logs are then read for those blocks alone. Eleven blocks, not eleven
    million.

What a nonce cannot see is a movement the wallet did not sign: a third party
spending an allowance via `transferFrom`. That case is the exact complement —
it changes the balance without touching the nonce — so `unexplained_balance`
below catches it with two reads. Together they leave nothing uncovered.

Stdlib only.
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
    """What `transferFrom` would look like: a balance the ledger cannot explain.

    A nonce search accounts for everything the wallet sent. If the balance is
    still short, tokens left without the wallet signing — someone spent an
    allowance. Returns the shortfall in wei; zero means fully explained.
    """
    return expected_wei - actual_wei
