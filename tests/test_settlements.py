"""RED-first tests for real CEP-8 settlement verification.

The hole these close
--------------------
`sms_send` accepted ANY non-empty `settlement_receipt` string as proof of
payment whenever the caller was not an owner and no token was attached
(`cvm_tools.py:338`). Nothing verified that a payment had ever happened, so an
arbitrary string bought a free SMS — bounded only by the pacer.

What a settlement receipt must be
---------------------------------
A **real** settlement the service itself issued, for **this** caller, worth at
least the price, and redeemable **exactly once**. Anything else is refused.

The store is deliberately narrow: the service is the only issuer, it prices the
receipt in sats, and redemption is a single conditional UPDATE so two racing
sends cannot both spend one receipt.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from app.settlements import (
    SettlementError,
    SettlementStore,
    issue_receipt,
    receipt_hash,
)


def _store(ttl_seconds: int | None = None) -> SettlementStore:
    if ttl_seconds is None:
        return SettlementStore(":memory:")
    return SettlementStore(":memory:", ttl_seconds=ttl_seconds)


# --------------------------------------------------------------------------- #
# issuing + verifying
# --------------------------------------------------------------------------- #
def test_a_freshly_issued_receipt_verifies():
    store = _store()
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    assert store.verify(receipt, pubkey="ab" * 32, price=2900) is True


def test_a_receipt_for_a_different_caller_is_refused():
    """Receipts are bound to the pubkey that paid. Someone else's is worthless."""
    store = _store()
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    assert store.verify(receipt, pubkey="cd" * 32, price=2900) is False


def test_a_receipt_worth_less_than_the_price_is_refused():
    store = _store()
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=1000)
    assert store.verify(receipt, pubkey="ab" * 32, price=2900) is False


def test_a_fabricated_receipt_is_refused():
    """The whole point: a string the service never issued proves nothing."""
    store = _store()
    assert store.verify("rcpt-1", pubkey="ab" * 32, price=2900) is False
    assert store.verify("", pubkey="ab" * 32, price=2900) is False
    assert store.verify("0" * 64, pubkey="ab" * 32, price=2900) is False


# --------------------------------------------------------------------------- #
# one receipt, one send
# --------------------------------------------------------------------------- #
def test_a_receipt_is_redeemable_exactly_once():
    store = _store()
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    assert store.redeem(receipt, pubkey="ab" * 32, price=2900) is True
    # second redemption of the same receipt must fail
    assert store.redeem(receipt, pubkey="ab" * 32, price=2900) is False


def test_concurrent_redemption_of_one_receipt_yields_exactly_one_winner():
    """Claiming must be a single conditional UPDATE, not read-then-write."""
    store = _store()
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    results: list[bool] = []
    lock = threading.Lock()

    def attempt() -> None:
        ok = store.redeem(receipt, pubkey="ab" * 32, price=2900)
        with lock:
            results.append(ok)

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1, results


def test_a_receipt_covers_one_send_not_a_balance():
    """2900 of postage buys one 2900 send; it is not a 2900-sat wallet."""
    store = _store()
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    assert store.redeem(receipt, pubkey="ab" * 32, price=2900) is True
    assert store.redeem(receipt, pubkey="ab" * 32, price=2900) is False


# --------------------------------------------------------------------------- #
# receipts are single-use objects, not guessable strings
# --------------------------------------------------------------------------- #
def test_receipts_are_unguessable_and_distinct():
    store = _store()
    a = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    b = issue_receipt(store, pubkey="ab" * 32, amount=2900)
    assert a != b
    assert len(a) >= 32


def test_the_receipt_hash_is_stable_and_not_the_receipt():
    assert receipt_hash("abc") == receipt_hash("abc")
    assert receipt_hash("abc") != "abc"


# --------------------------------------------------------------------------- #
# expiry: an old receipt must not be usable forever
# --------------------------------------------------------------------------- #
def test_an_expired_receipt_is_refused():
    store = _store(ttl_seconds=0)
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900, now=1000.0)
    assert store.verify(receipt, pubkey="ab" * 32, price=2900, now=1001.0) is False


def test_a_receipt_inside_its_window_is_accepted():
    store = _store(ttl_seconds=900)
    receipt = issue_receipt(store, pubkey="ab" * 32, amount=2900, now=1000.0)
    assert store.verify(receipt, pubkey="ab" * 32, price=2900, now=1500.0) is True


# --------------------------------------------------------------------------- #
# durability
# --------------------------------------------------------------------------- #
def test_a_receipt_survives_a_store_reopen(tmp_path):
    db = str(tmp_path / "settle.db")
    first = SettlementStore(db)
    receipt = issue_receipt(first, pubkey="ab" * 32, amount=2900)
    first.close()

    second = SettlementStore(db)
    assert second.verify(receipt, pubkey="ab" * 32, price=2900) is True
    assert second.redeem(receipt, pubkey="ab" * 32, price=2900) is True
    assert second.redeem(receipt, pubkey="ab" * 32, price=2900) is False


def test_the_store_never_leaks_sqlite_errors_to_callers():
    """A corrupt/unavailable store must refuse, not blow up the send path."""
    store = _store()
    store._conn.close()  # simulate a dead handle
    assert store.verify("whatever", pubkey="ab" * 32, price=2900) is False
    with pytest.raises(SettlementError):
        issue_receipt(store, pubkey="ab" * 32, amount=2900)
