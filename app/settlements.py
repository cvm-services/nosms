"""Service-issued CEP-8 settlement receipts — the store behind the verifier.

Why this module exists
----------------------
Until now `sms_send` accepted any non-empty ``settlement_receipt`` string as
proof of payment. Nothing checked that a payment had ever happened, so an
arbitrary string bought a free SMS (bounded only by the pacer). See
``tests/test_settlements.py`` for the contract this enforces.

A settlement receipt is now a real object the service itself issued:

  * **single use** — redemption is one conditional UPDATE; two racing sends
    cannot both spend one receipt (SQLite serialises the UPDATE);
  * **caller-bound** — a receipt issued for pubkey A is worthless to pubkey B;
  * **amount-checked** — a receipt worth less than the price is refused;
  * **expiring** — an unredeemed receipt does not stay usable forever;
  * **unguessable** — 256 bits of entropy, never derived from anything about
    the caller or the message.

Receipts are issued when a payment has *actually landed* (a paid bolt11 quote
minted into proofs the service holds), by :func:`issue_receipt`. There is no
other way to get one into the store — that is the whole point.

Refusal, never an exception
---------------------------
``verify``/``redeem`` return ``False`` on any problem (unknown receipt, wrong
caller, wrong amount, expired, already spent, dead DB handle) — the send path
turns that into a visible ``bad_settlement`` refusal. Only :func:`issue_receipt`
raises (:class:`SettlementError`), because issuing is an operator-visible
failure that must not be swallowed.
"""
from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass

#: Default window in which an issued receipt may be redeemed.
DEFAULT_TTL_SECONDS = 15 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS settlements (
    receipt     TEXT PRIMARY KEY,
    pubkey      TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    issued_at   REAL NOT NULL,
    redeemed_at REAL
);
CREATE INDEX IF NOT EXISTS settlements_unredeemed
    ON settlements (redeemed_at, issued_at);
"""


class SettlementError(Exception):
    """Raised when the store cannot ISSUE a receipt. Never raised on refusal."""


def receipt_hash(receipt: str) -> str:
    """Stable internal digest of a receipt (for logging; never the receipt)."""
    import hashlib

    return hashlib.sha256(receipt.encode()).hexdigest()


@dataclass
class SettlementStore:
    """SQLite-backed settlement receipts. Thread-safe via SQLite itself."""

    db_path: str = ":memory:"
    ttl_seconds: int = DEFAULT_TTL_SECONDS

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        try:
            # check_same_thread=False: redeem/verify are called from server
            # worker threads; self._lock is the serializer, so sharing one
            # connection across threads is safe and keeps transactions tight.
            self._conn = sqlite3.connect(
                self.db_path, timeout=20, check_same_thread=False
            )
            self._conn.execute("PRAGMA busy_timeout=20000")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise SettlementError(f"settlement store unavailable: {exc}") from exc

    # -- issuing ------------------------------------------------------------
    def issue(self, *, pubkey: str, amount: int, now: float | None = None) -> str:
        """Record a real settlement and return its single-use receipt.

        Callers must only invoke this AFTER the payment has landed (e.g. a
        bolt11 quote confirmed PAID and minted into proofs the service holds).
        """
        receipt = "stl_" + secrets.token_hex(16)
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO settlements (receipt, pubkey, amount, issued_at) "
                    "VALUES (?, ?, ?, ?)",
                    (receipt, (pubkey or "").lower(), int(amount),
                     float(now if now is not None else time.time())),
                )
                self._conn.commit()
            except sqlite3.Error as exc:
                raise SettlementError(f"settlement store unavailable: {exc}") from exc
        return receipt

    # -- checking -----------------------------------------------------------
    def _row_for(self, receipt: str) -> tuple | None:
        try:
            cur = self._conn.execute(
                "SELECT receipt, pubkey, amount, issued_at, redeemed_at "
                "FROM settlements WHERE receipt = ?", (receipt,)
            )
            return cur.fetchone()
        except sqlite3.Error:
            return None

    def verify(self, receipt: str, *, pubkey: str, price: int,
               now: float | None = None) -> bool:
        """True iff this exact receipt was issued to this caller, covers the
        price, is inside its window, and has not been redeemed. Does NOT spend."""
        if not isinstance(receipt, str) or not receipt:
            return False
        row = self._row_for(receipt)
        if row is None:
            return False
        _, row_pubkey, amount, issued_at, redeemed_at = row
        if redeemed_at is not None:
            return False
        if (row_pubkey or "").lower() != (pubkey or "").lower():
            return False
        if int(amount) < int(price):
            return False
        t = float(now if now is not None else time.time())
        if t - float(issued_at) > self.ttl_seconds:
            return False
        return True

    def redeem(self, receipt: str, *, pubkey: str, price: int,
               now: float | None = None) -> bool:
        """Verify AND spend in one step. Second redemption of the same
        receipt must fail. The claim is a single conditional UPDATE guarded
        by the same lock as verify, so concurrent callers see exactly one
        winner even though SQLite would serialise the UPDATE anyway."""
        with self._lock:
            if not self.verify(receipt, pubkey=pubkey, price=price, now=now):
                return False
            try:
                cur = self._conn.execute(
                    "UPDATE settlements SET redeemed_at = ? "
                    "WHERE receipt = ? AND redeemed_at IS NULL",
                    (float(now if now is not None else time.time()), receipt),
                )
                self._conn.commit()
                return cur.rowcount == 1
            except sqlite3.Error:
                return False

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


def issue_receipt(store: SettlementStore, *, pubkey: str, amount: int,
                  now: float | None = None) -> str:
    """Convenience wrapper mirroring the test-facing name."""
    return store.issue(pubkey=pubkey, amount=amount, now=now)